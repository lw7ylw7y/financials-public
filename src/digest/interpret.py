"""Gemini API call for the digest's holistic AI interpretation.

Uses gemini-3.8-flash, a free-tier model (per ai.google.dev/gemini-api/docs/pricing),
since this is a short, well-specified commentary task with low request
volume — well within the free tier's daily/per-minute limits.

One call per digest, reasoning across *all 8* indicators' 12-month
historical windows together (not one call per updated indicator) plus,
where applicable, pre-computed named-heuristic values (heuristics.py),
and returns a short plain-English summary. The improving/mixed/weakening
read of each group (leading, coincident, lagging) and each indicator's
favorable/unfavorable classification are computed in code
(market_read.py) and given to the model as facts to explain, never to
decide. Deliberately excludes the
AI's own past interpretations from the input, to avoid anchoring on
earlier reads.
"""

import logging
import os
import sys
from datetime import date

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

from gemini_models import fallback_models
from market_read import compute_market_read

# What each group tells the investor, as the AI is told to describe it.
GROUP_MEANING = {
    "leading": "an outlook: usually turns months before the economy does",
    "coincident": "how the economy is doing now",
    "lagging": "confirms the past: reflects the economy 6 to 12 months ago",
}

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
# No retries: the free tier's 20-requests/day cap counts every attempt,
# including failed ones, so retrying against a sustained backend outage
# (the observed real-world failure mode) burns through the day's whole
# quota for zero successes rather than helping with a one-off blip.
MAX_ATTEMPTS = 1

SYSTEM_PROMPT = """You are a macroeconomic commentator writing for a long-term, \
buy-and-hold individual investor who is not a professional trader.

You will be given all the tracked economic indicators (grouped as leading, \
coincident, or lagging), each with its readings over the last 12 months \
(daily series are sampled weekly), which \
one(s) published a new value this run, and sometimes a pre-computed \
named-heuristic value (the Sahm Rule) — use that computed value as given, don't recompute it yourself. \
You are also given each indicator's computed statistics and favorable / \
neutral / unfavorable classification, and a computed read (improving, \
mixed or weakening) for each of the three groups. Improving means most of \
a group's indicators are moving the favorable way compared with their own \
past 12 months, weakening the unfavorable way, mixed no clear direction \
(flat, or signals offsetting). A group is held at mixed when the data now \
lean one way but the read a month earlier did not agree, so a mixed group \
can have a score that leans; say so rather than explaining it away. The \
yield curve is the one indicator judged from its level: it is unfavorable \
if it was inverted at any time in the past 12 months, whatever its \
current direction. These describe direction, not whether \
the economy is large or small, and they are not a forecast for stock prices. The groups are read \
separately and never combined into one overall read: leading indicators \
are an outlook, coincident indicators show how the economy is doing now, \
and lagging indicators confirm what happened some 6 to 12 months ago. \
Those were produced by fixed rules from the readings; treat them as \
given facts. Do not state a different read for any group, do not offer \
an overall read, do not reclassify an indicator, and don't recompute the \
statistics.

Reason across all the indicators together, not just the one(s) that just \
updated — connect indicators to each other where relevant (e.g. \
unemployment ticking up while inflation cools), and reason from each \
one's historical window, not just its single most recent change, to \
distinguish a real multi-month trend from a one-off noisy blip. Explain \
in plain English, in 3-6 sentences, what changed and why it matters for a \
long-term buy-and-hold investor, and say why each group's computed read \
follows from the indicators that drove it, and how the three groups \
relate (for example leading turning before coincident, or lagging data \
still confirming an older picture).
"""


class Interpretation(BaseModel):
    summary: str


class InterpretationError(Exception):
    """Raised for any failure to obtain a usable AI interpretation."""


# A daily series holds ~250 readings a year; past this many, the prompt
# gets one reading per week instead, keeping it short without hiding the trend.
MAX_PROMPT_READINGS = 60


def _weekly_sample(history_window: list[dict]) -> list[dict]:
    """The last reading of each ISO week, oldest to newest."""
    by_week = {}
    for entry in history_window:
        by_week[date.fromisoformat(entry["date"]).isocalendar()[:2]] = entry
    return list(by_week.values())


def _format_history(history_window: list[dict]) -> str:
    if len(history_window) > MAX_PROMPT_READINGS:
        history_window = _weekly_sample(history_window)
    return "\n".join(f"- {entry['date']}: {entry['value']}" for entry in history_window)


def _format_heuristic(heuristic: dict | None) -> str:
    if not heuristic:
        return "(none)"
    return "\n".join(f"- {key}: {value}" for key, value in heuristic.items())


def _format_stats(stats: dict) -> str:
    def shown(value, suffix=""):
        return "n/a" if value is None else f"{value}{suffix}"

    return (
        f"Computed: {stats['classification']}"
        f"{' (' + stats['reason'] + ')' if stats['reason'] else ''}; "
        f"percentile in 12 months={shown(stats['percentile'])}, z={shown(stats['z'])}, "
        f"change 1m/3m/6m={shown(stats['change_1m'])}/{shown(stats['change_3m'])}/"
        f"{shown(stats['change_6m'])}, recent trend={shown(stats['trend'])}"
    )


def build_user_prompt(indicators_context: list[dict], updated_keys: list[str]) -> str:
    """`indicators_context`: one entry per indicator with data to report —
    {"key", "name", "category", "history_window", "heuristic"}. `updated_keys`
    names which of those published a new value this run. The computed
    statistics and the read of each group are derived from `indicators_context`
    here.
    """
    market_read = compute_market_read(indicators_context)
    updated_names = [
        ind["name"] for ind in indicators_context if ind["key"] in updated_keys
    ]

    sections = []
    for ind in indicators_context:
        marker = " — NEW VALUE THIS RUN" if ind["key"] in updated_keys else ""
        sections.append(
            f"### {ind['name']} ({ind['category']}){marker}\n"
            f"Readings over the last 12 months (oldest to newest; one per week for daily series):\n"
            f"{_format_history(ind['history_window'])}\n"
            f"Computed heuristic values:\n"
            f"{_format_heuristic(ind['heuristic'])}\n"
            f"{_format_stats(market_read['indicators'][ind['key']])}"
        )

    read_lines = []
    for group, meaning in GROUP_MEANING.items():
        info = market_read["groups"][group]
        if info["read"] is None:
            read_lines.append(
                f"Computed read, {group} ({meaning}): none yet (only {info['scored']} of "
                f"{info['total']} indicators have enough history to score). "
                "Do not offer a read of your own for this group; describe what the data shows."
            )
        else:
            read_lines.append(
                f"Computed read, {group} ({meaning}): {info['read']} "
                f"(score {info['score']}, based on {info['scored']} of {info['total']} indicators)"
            )
    if market_read["relationship"]:
        read_lines.append(f"How the groups relate: {market_read['relationship']}")
    policy = market_read["policy"]
    if policy["stance"]:
        inflation = (f", recent inflation {policy['inflation']}% (CPI, six-month annualized), real rate "
                     f"{policy['real_rate']}%, neutral real rate about {policy['neutral_real_rate']}%"
                     if policy["inflation"] is not None else "")
        why = f" ({policy['reason']}, so it is accommodative whatever recent inflation was)" if policy["reason"] else ""
        read_lines.append(
            f"Policy stance (context about what the Fed is doing, not one of the three reads and not a sign of the "
            f"economy's health): {policy['stance']}{why}; fed funds {policy['fed_funds']}%{inflation}"
        )
    return (
        f"{chr(10).join(read_lines)}\n"
        f"Indicators with a new value this run: {', '.join(updated_names) or '(none)'}\n\n"
        + "\n\n".join(sections)
    )


def _parse(text: str | None, source: str) -> dict:
    if not text:
        raise InterpretationError(f"{source} returned no text content")
    try:
        parsed = Interpretation.model_validate_json(text)
    except ValidationError as e:
        raise InterpretationError(f"could not parse {source} response: {e}") from e
    return {"summary": parsed.summary}


def _interpret_with_gemini(prompt: str, client: genai.Client | None, model: str = MODEL) -> dict:
    try:
        client = client or genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=MAX_ATTEMPTS)
            )
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=Interpretation,
            ),
        )
    except errors.APIError as e:
        raise InterpretationError(f"Gemini API call failed: {e}") from e
    except ValueError as e:
        # genai.Client() raises a bare ValueError (not an APIError) when no
        # API key is configured — still a "the AI call is unusable" case
        # that must degrade gracefully, not crash the run.
        raise InterpretationError(f"Gemini client not configured: {e}") from e
    return _parse(response.text, "Gemini")


def _run_with_fallbacks(prompt: str, client: genai.Client | None) -> dict:
    """Gemini, then each fallback Gemini model in turn; the first
    usable result wins. An explicitly injected `client` is used alone."""
    sources = [(MODEL, lambda: _interpret_with_gemini(prompt, client))]
    if client is None:
        sources += [
            (model, lambda model=model: _interpret_with_gemini(prompt, None, model))
            for model in fallback_models()
        ]

    failures = []
    for name, attempt in sources:
        try:
            return attempt()
        except InterpretationError as e:
            logger.warning("%s interpretation failed: %s", name, e)
            failures.append(f"{name}: {e}")
    raise InterpretationError("; ".join(failures))


def interpret(
    indicators_context: list[dict],
    updated_keys: list[str],
    client: genai.Client | None = None,
) -> dict:
    """Return {"summary": str}: the explanation of the computed read.

    Tries Gemini first, then each fallback Gemini model in turn
    if each fails for any reason (the free tier's sustained 503s are
    the usual cause). An explicitly injected `client` is used alone,
    with no fallback.

    Raises InterpretationError when every source fails, so the caller
    (post_release.py) can degrade gracefully to a table-and-countdown-only
    digest rather than blocking on a broken AI call.
    """
    prompt = build_user_prompt(indicators_context, updated_keys)

    return _run_with_fallbacks(prompt, client)

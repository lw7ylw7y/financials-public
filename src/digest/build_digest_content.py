"""Shared table/countdown/AI-assembly logic (Stories 4/5/6), extracted
out of post_release.py so the weekly digest email and the v2
Indicator Digest Page's on-demand live pull build identical content
from identical logic — one code path, not two divergent ones.

`build_digest_content` is the single entry point either caller needs:
given a state and which indicator keys are new this run, it returns the
table, the countdown, and the AI interpretation (or None on failure),
and persists a successful AI result to `state["last_ai_response"]` so a
later fallback (the page's Saved state) has something to show.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from email_template import CATEGORY_ORDER
from heuristics import heuristic_for
from indicators_config import INDICATORS
from market_read import compute_market_read, group_reads
from interpret import InterpretationError
from interpret import interpret as default_interpret

logger = logging.getLogger(__name__)

# After a failed AI call, a retry that isn't triggered by genuinely new data
# waits this long, so a page load or scheduled run during an outage doesn't
# spend one request per model every time.
AI_RETRY_COOLDOWN = timedelta(minutes=15)


def config_for(key: str, stored: dict) -> dict:
    """The indicator's configured name and group, else the stored ones (an indicator
    no longer in the config). The stored copy is whatever it was when the indicator last
    got a new reading."""
    return INDICATORS.get(key, stored)


def build_indicators_context(state: dict) -> list[dict]:
    """One entry per indicator with any history, for the AI prompt and table.

    Each entry: {"key", "name", "category", "history_window" (every
    stored reading, i.e. the last 12 months whatever the series'
    frequency), "heuristic"}.
    """
    context = []
    for key, indicator in state.get("indicators", {}).items():
        history = indicator.get("history", [])
        if not history:
            continue
        config = config_for(key, indicator)
        context.append(
            {
                "key": key,
                "name": config["name"],
                "category": config["category"],
                "history_window": history,
                "heuristic": heuristic_for(key, history),
            }
        )
    return context


def sparkline_cid(key: str) -> str:
    return f"spark-{key}"


def build_table(indicators_context: list[dict]) -> dict:
    """Group indicators into Leading/Coincident/Lagging rows for the table.

    Each row: name, latest_value, latest_date, prior_value (None if
    fewer than 2 history entries on file), sparkline_cid (email-only —
    matches a key in post_release.build_sparkline_images's returned
    dict), sparkline_values (the raw history_window values, oldest
    first — used by the web page to draw an inline SVG trend line;
    the email ignores it since it renders sparkline_cid as a CID image
    instead).
    """
    grouped = {category: [] for category in CATEGORY_ORDER}
    for ind in indicators_context:
        history = ind["history_window"]
        latest = history[-1]
        prior = history[-2] if len(history) >= 2 else None
        grouped.setdefault(ind["category"], []).append(
            {
                "name": ind["name"],
                "latest_value": latest["value"],
                "latest_date": latest["date"],
                "prior_value": prior["value"] if prior else None,
                "sparkline_cid": sparkline_cid(ind["key"]),
                "sparkline_values": [entry["value"] for entry in history],
            }
        )
    return grouped


def build_countdown(state: dict, today: date | None = None) -> dict:
    """Return {"entries": [...], "soonest": entry|None} for indicators with
    a next_release_date, sorted soonest-first.
    """
    today = today or date.today()
    entries = []
    for key, indicator in state.get("indicators", {}).items():
        next_date = indicator.get("next_release_date")
        if not next_date:
            continue
        days_until = (date.fromisoformat(next_date) - today).days
        entries.append(
            {
                "key": key,
                "name": config_for(key, indicator)["name"],
                "next_release_date": next_date,
                "days_until": days_until,
            }
        )
    entries.sort(key=lambda e: e["days_until"])
    return {"entries": entries, "soonest": entries[0] if entries else None}


def _latest_dates(state: dict) -> dict[str, str]:
    return {
        key: indicator["history"][-1]["date"]
        for key, indicator in state.get("indicators", {}).items()
        if indicator.get("history")
    }


def build_read_view(market_read: dict, ai_take: dict | None) -> dict | None:
    """What the page and email show: the computed read of each group,
    plus the AI's explanation only while it was written for those same
    reads.

    `{"groups": {group: {"read" (None until the group has enough history),
    "score", "scored", "total"}}, "relationship" (a sentence, or None),
    "policy" (the policy stance, see `policy_stance`), "summary" (None
    when no explanation matches)}`; None only when there
    are no indicators at all. An explanation written for different reads
    would contradict the badges beside it, so it's dropped rather than
    shown.
    """
    matches = (
        ai_take is not None
        and "computed_reads" in ai_take
        and ai_take["computed_reads"] == group_reads(market_read)
    )
    summary = ai_take["summary"] if matches else None
    if not any(group["total"] for group in market_read["groups"].values()):
        return None
    return {
        "groups": market_read["groups"],
        "relationship": market_read["relationship"],
        "policy": market_read["policy"],
        "summary": summary,
    }


def stale_indicator_keys(state: dict) -> list[str]:
    """Indicators whose latest reading the stored AI take doesn't cover yet.

    `last_ai_response["as_of"]` records each indicator's latest date at
    the time the take was generated. Anything differing from what's
    stored now (or everything, if there's no take or it predates
    `as_of`) is data the AI hasn't seen -- e.g. because every model
    failed when it arrived. A take written for a different computed
    read than the current one is stale for every indicator.
    """
    take = state.get("last_ai_response") or {}
    as_of = take.get("as_of") or {}
    if take:
        current_reads = group_reads(compute_market_read(build_indicators_context(state)))
        if take.get("computed_reads") != current_reads:
            return list(_latest_dates(state))
    return [key for key, latest in _latest_dates(state).items() if as_of.get(key) != latest]


def ai_retry_keys(state: dict, now: datetime) -> list[str]:
    """Stale indicator keys worth another AI attempt right now: none if
    the take is current, or if the last attempt failed within
    `AI_RETRY_COOLDOWN`."""
    keys = stale_indicator_keys(state)
    failed_at = state.get("ai_last_failed_at")
    if keys and failed_at and now - datetime.fromisoformat(failed_at) < AI_RETRY_COOLDOWN:
        return []
    return keys


def build_digest_content(
    state: dict,
    updated_keys: list[str],
    interpret_fn=default_interpret,
    now: datetime | None = None,
) -> dict:
    """Assemble {"indicators_context", "table", "countdown", "ai_result",
    "market_read", "read_view"}.

    `market_read` is the computed reads (see market_read.py) and
    `read_view` what to show for them (`build_read_view`). The AI only
    writes the explanation: on a successful call its result is
    `{"summary", "computed_reads"}` with the computed reads of the three
    groups, persisted to `state["last_ai_response"]` as
    `{"summary", "computed_reads", "generated_at", "as_of"}`,
    overwriting any previous one. On failure, leaves
    `last_ai_response` untouched, records `state["ai_last_failed_at"]`,
    and returns `ai_result=None`; `read_view` still carries the computed
    read, with the explanation only if the stored one still matches it.
    `ai_retry_keys` uses both to retry later.
    """
    now = now or datetime.now(timezone.utc)
    indicators_context = build_indicators_context(state)
    table = build_table(indicators_context)
    countdown = build_countdown(state)
    market_read = compute_market_read(indicators_context)

    ai_result = None
    try:
        ai_result = interpret_fn(indicators_context, updated_keys)
    except InterpretationError as e:
        logger.warning("AI interpretation failed error=%s", e)
        state["ai_last_failed_at"] = now.isoformat()

    if ai_result is not None:
        ai_result = {"summary": ai_result["summary"], "computed_reads": group_reads(market_read)}
        state["last_ai_response"] = {
            "summary": ai_result["summary"],
            "computed_reads": ai_result["computed_reads"],
            "generated_at": now.isoformat(),
            "as_of": _latest_dates(state),
        }
        state.pop("ai_last_failed_at", None)

    return {
        "indicators_context": indicators_context,
        "table": table,
        "countdown": countdown,
        "ai_result": ai_result,
        "market_read": market_read,
        "read_view": build_read_view(market_read, state.get("last_ai_response")),
    }

"""The indicator digest's verdicts, computed from stored history.

Every number and classification here is plain arithmetic on the readings
already on file, so the same history always gives the same read and no
AI call is involved. The AI's job is to explain this read, not to make it.

Per indicator: the latest reading's percentile and z-score within the
12-month window, change over 1/3/6 months, and the sign of the recent
trend. An indicator with a favorable direction is classified by how far
its recent readings (the last `RECENT_DAYS`) sit from the window's own
mean, in standard deviations: past `SIGNAL_Z` in the favorable direction
is "favorable", past it the other way "unfavorable", unless the recent
trend points the opposite way, which makes it "neutral" (a level that
is good for the year but already turning is a mixed signal). A triggered named
heuristic (the Sahm Rule) forces "unfavorable". Each
group (leading, coincident, lagging) then gets a read of its own, the
average of its indicators' classifications; the groups are never combined,
because they speak about different times.

A cumulative series (`kind` "change" in indicators_config) is read as the
percent change between consecutive readings, since its level only drifts
upward and a level z-score would always look favorable (or, for CPI,
unfavorable).
"""

import math
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fred"))

from heuristics import heuristic_for
from indicators_config import INDICATORS

# The recent stretch compared against the whole window.
RECENT_DAYS = 90
# Fewest readings (after any change transform) in the window, and in its
# recent stretch, for an indicator to be scored at all.
MIN_READINGS = 6
MIN_RECENT_READINGS = 3
# Standard deviations the recent readings must sit from the window's mean
# before the move counts as favorable or unfavorable rather than noise.
SIGNAL_Z = 0.5
# Normalized recent slope (change over RECENT_DAYS, in window std devs)
# below which the trend is called flat.
FLAT_TREND_Z = 0.25
# The Sahm Rule's own recession-signal threshold.
SAHM_TRIGGER = 0.5

# Policy stance: the real fed funds rate (the rate minus recent inflation) against
# an estimate of the neutral real rate. The estimate is the FOMC's own longer-run
# median for the fed funds rate (3.0% in its 2025 projections) minus its 2%
# inflation target; it is uncertain by about a point and should be refreshed when
# the FOMC changes it.
NEUTRAL_REAL_RATE = 1.0
# At or below a fed funds rate this low policy is accommodative whatever inflation did: with
# the rate at the floor and inflation near zero the real rate can read positive, which says nothing
# about how tight policy is.
ZERO_RATE_LIMIT = 0.5
ZERO_RATE_REASON = "the fed funds rate is near zero"
# How far the real rate must sit from the neutral estimate to be called
# restrictive or accommodative rather than near neutral (percentage points).
STANCE_BAND = 0.5
# Inflation is the CPI's change over about six months, annualized: it needs a
# reading this many days back, give or take, and is more current than a year-over-year
# figure (which the stored 12 months of history cannot supply).
INFLATION_LOOKBACK_DAYS = 182
INFLATION_LOOKBACK_TOLERANCE_DAYS = 20

# The groups are read one at a time and never combined: leading is an
# outlook, coincident is the present, lagging confirms the past.
GROUPS = ("leading", "coincident", "lagging")
# Average of favorable(+1)/neutral(0)/unfavorable(-1) at or past which a
# group's read is improving/weakening.
READ_THRESHOLD = 0.25
# A group reads improving or weakening only if the read computed from the
# history as it stood this many days earlier says the same; otherwise it
# reads mixed. A single month's swing is not a change of direction.
PERSISTENCE_DAYS = 30
# Fewest scored indicators a group needs for a read of its own.
MIN_SCORED_FOR_READ = 2
_RANK = {"weakening": 0, "mixed": 1, "improving": 2}

_CHANGE_MONTHS = (1, 3, 6)
_SCORE = {"favorable": 1, "neutral": 0, "unfavorable": -1}


def _series(history: list[dict], kind: str) -> list[tuple[date, float]]:
    points = [(date.fromisoformat(r["date"]), r["value"]) for r in history]
    if kind != "change":
        return points
    return [
        (points[i][0], (points[i][1] / points[i - 1][1] - 1) * 100)
        for i in range(1, len(points))
        if points[i - 1][1] != 0
    ]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _slope(points: list[tuple[date, float]]) -> float:
    """Least-squares slope, in value units per day."""
    xs = [(d - points[0][0]).days for d, _ in points]
    ys = [v for _, v in points]
    x_mean, y_mean = _mean(xs), _mean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


def _change_over(history: list[dict], months: int) -> float | None:
    """Latest value minus the reading on or before `months` * 30 days
    earlier; None when the window doesn't reach back that far."""
    latest_date = date.fromisoformat(history[-1]["date"])
    target = latest_date - timedelta(days=30 * months)
    earlier = [r for r in history if date.fromisoformat(r["date"]) <= target]
    if not earlier:
        return None
    return round(history[-1]["value"] - earlier[-1]["value"], 4)


def _heuristic_triggered(heuristic: dict | None) -> str | None:
    """A sentence naming the named heuristic that forces "unfavorable",
    or None when none has triggered."""
    if not heuristic:
        return None
    sahm = heuristic.get("sahm_rule_value")
    if sahm is not None and sahm >= SAHM_TRIGGER:
        return f"Sahm Rule at {sahm} (recession signal at {SAHM_TRIGGER})"
    return None


def indicator_stats(
    history: list[dict],
    favorable_direction: str | None,
    kind: str = "level",
    heuristic: dict | None = None,
) -> dict:
    """Statistics and classification for one indicator.

    `history` is chronological {"date", "value"} entries. Returns
    {"latest", "percentile", "z", "change_1m", "change_3m", "change_6m",
    "trend", "recent_z", "classification", "reason"}; `classification` is
    "favorable", "neutral", "unfavorable", "context" (no favorable
    direction) or "insufficient" (too little history). Statistics that
    can't be computed from the history on file are None.
    """
    stats = {
        "latest": history[-1]["value"],
        "percentile": None,
        "z": None,
        "change_1m": None,
        "change_3m": None,
        "change_6m": None,
        "trend": None,
        "recent_z": None,
        "classification": "insufficient",
        "reason": "",
    }
    for months in _CHANGE_MONTHS:
        stats[f"change_{months}m"] = _change_over(history, months)

    points = _series(history, kind)
    if len(points) < MIN_READINGS:
        stats["reason"] = f"only {len(points)} readings on file"
        return stats

    values = [v for _, v in points]
    mean, std = _mean(values), _std(values)
    latest_value = values[-1]
    below = sum(v < latest_value for v in values)
    equal = sum(v == latest_value for v in values)
    stats["percentile"] = round((below + 0.5 * equal) / len(values) * 100)
    stats["z"] = round((latest_value - mean) / std, 2) if std else 0.0

    cutoff = points[-1][0] - timedelta(days=RECENT_DAYS)
    recent = [(d, v) for d, v in points if d >= cutoff]
    if len(recent) >= MIN_RECENT_READINGS:
        normalized = _slope(recent) * RECENT_DAYS / std if std else 0.0
        stats["trend"] = (
            "flat"
            if abs(normalized) < FLAT_TREND_Z
            else "rising" if normalized > 0 else "falling"
        )
    if len(recent) >= MIN_RECENT_READINGS:
        stats["recent_z"] = round((_mean([v for _, v in recent]) - mean) / std, 2) if std else 0.0

    if favorable_direction is None:
        stats["classification"] = "context"
        stats["reason"] = "no inherent good direction; shown as context"
        return stats

    triggered = _heuristic_triggered(heuristic)
    if triggered:
        stats["classification"] = "unfavorable"
        stats["reason"] = triggered
        return stats

    if kind == "inversion":
        lowest = min(history, key=lambda r: r["value"])
        if lowest["value"] < 0:
            stats["classification"] = "unfavorable"
            stats["reason"] = f"inverted in the last 12 months (lowest {lowest['value']} on {lowest['date']})"
        else:
            stats["classification"] = "neutral"
            stats["reason"] = "not inverted in the last 12 months"
        return stats

    if stats["recent_z"] is None:
        stats["reason"] = f"only {len(recent)} recent readings"
        return stats

    sign = 1 if favorable_direction == "higher" else -1
    signed = sign * stats["recent_z"]
    trend_sign = {"rising": 1, "falling": -1}.get(stats["trend"], 0) * sign
    if signed >= SIGNAL_Z and trend_sign >= 0:
        stats["classification"] = "favorable"
    elif signed <= -SIGNAL_Z and trend_sign <= 0:
        stats["classification"] = "unfavorable"
    else:
        stats["classification"] = "neutral"
    if stats["recent_z"] == 0:
        stats["reason"] = "recent readings at the 12-month average"
    else:
        word = "above" if stats["recent_z"] > 0 else "below"
        stats["reason"] = (
            f"recent readings {abs(stats['recent_z'])} std devs {word} the 12-month average"
        )
    return stats


def _group_read(scores: list[int]) -> dict:
    """{"read", "score", "scored"} for the favorable/neutral/unfavorable
    scores of one group's scored indicators (equally weighted)."""
    scored = len(scores)
    score = round(sum(scores) / scored, 2) if scored else None
    read = None
    if score is not None and scored >= MIN_SCORED_FOR_READ:
        if score >= READ_THRESHOLD:
            read = "improving"
        elif score <= -READ_THRESHOLD:
            read = "weakening"
        else:
            read = "mixed"
    return {"read": read, "score": score, "scored": scored}


def relationship(reads: dict[str, str | None]) -> str | None:
    """One or two plain sentences on how the three reads sit together,
    or None when fewer than two groups have a read. `reads` maps each
    group to "improving", "mixed", "weakening" or None. Leading is compared
    with coincident (is the outlook better or worse than the present?),
    then lagging with coincident (has the confirmation caught up?)."""
    leading, coincident, lagging = reads.get("leading"), reads.get("coincident"), reads.get("lagging")
    if sum(read is not None for read in (leading, coincident, lagging)) < 2:
        return None
    present = [read for read in (leading, coincident, lagging) if read is not None]
    if len(present) == 3 and len(set(present)) == 1:
        return f"All three groups agree: {present[0]}."
    sentences = []
    if leading is not None and coincident is not None and leading != coincident:
        if _RANK[leading] < _RANK[coincident]:
            sentences.append("The outlook is weaker than the present: leading indicators are turning down before current conditions have, an early warning.")
        else:
            sentences.append("The outlook is stronger than the present: leading indicators are improving before current conditions have.")
    if lagging is not None and coincident is not None and lagging != coincident:
        if _RANK[lagging] < _RANK[coincident]:
            sentences.append("The lagging data, which reflects the past 6 to 12 months, has not caught up with current conditions yet.")
        else:
            sentences.append("The lagging data, which reflects the past 6 to 12 months, is still better than current conditions.")
    if coincident is None and leading is not None and lagging is not None and leading != lagging:
        # No present-day read to anchor on: compare the outlook with the confirmation directly.
        if _RANK[leading] < _RANK[lagging]:
            sentences.append("The outlook is weaker than the lagging data, which reflects the past 6 to 12 months, an early warning.")
        else:
            sentences.append("The outlook is stronger than the lagging data, which reflects the past 6 to 12 months.")
    if not sentences:
        sentences.append("The groups that have a read agree." if len(set(present)) == 1 else "The groups that have a read differ.")
    return " ".join(sentences)


def policy_stance(fed_funds: list[dict] | None, cpi: list[dict] | None) -> dict:
    """How tight monetary policy is, from the stored fed funds and CPI
    history: {"stance": "restrictive"|"near neutral"|"accommodative"|None,
    "fed_funds", "inflation", "real_rate", "neutral_real_rate", "gap",
    "reason"}. Inflation is the CPI's six-month change, annualized. The real
    rate is the latest fed funds rate minus that inflation; the stance
    compares it with `NEUTRAL_REAL_RATE`, except that a fed funds rate below
    `ZERO_RATE_LIMIT` is always accommodative (the stance is then set even when
    inflation cannot be worked out, and `reason` says why). This describes what the Fed is
    doing to credit, not how the economy is doing, so it is shown beside
    the three reads and never inside one. With no fed funds reading, or
    no CPI reading about six months before the latest one, the stance is
    None and `reason` says why.
    """
    result = {"stance": None, "fed_funds": None, "fed_funds_date": None, "inflation": None, "cpi_date": None,
              "real_rate": None, "neutral_real_rate": NEUTRAL_REAL_RATE, "gap": None, "reason": ""}
    if not fed_funds:
        result["reason"] = "no fed funds reading on file"
        return result
    result["fed_funds"], result["fed_funds_date"] = fed_funds[-1]["value"], fed_funds[-1]["date"]
    near_zero = result["fed_funds"] < ZERO_RATE_LIMIT
    if near_zero:
        result["stance"], result["reason"] = "accommodative", ZERO_RATE_REASON
    if not cpi:
        result["reason"] = result["reason"] or "no CPI readings on file"
        return result
    latest_date = date.fromisoformat(cpi[-1]["date"])
    target = latest_date - timedelta(days=INFLATION_LOOKBACK_DAYS)
    earlier = [r for r in cpi[:-1]
               if abs((date.fromisoformat(r["date"]) - target).days) <= INFLATION_LOOKBACK_TOLERANCE_DAYS]
    if not earlier:
        result["reason"] = result["reason"] or "no CPI reading about six months before the latest one"
        return result
    base = min(earlier, key=lambda r: abs((date.fromisoformat(r["date"]) - target).days))
    if base["value"] <= 0 or cpi[-1]["value"] <= 0:
        result["reason"] = result["reason"] or "CPI readings that cannot give an inflation rate"
        return result
    days = (latest_date - date.fromisoformat(base["date"])).days
    inflation = ((cpi[-1]["value"] / base["value"]) ** (365 / days) - 1) * 100
    real_rate = result["fed_funds"] - inflation
    # Round once, and decide on what is shown: a gap displayed as 0.5 points is
    # never called near neutral.
    gap = round(real_rate - NEUTRAL_REAL_RATE, 1)
    result.update(
        inflation=round(inflation, 1),
        cpi_date=cpi[-1]["date"],
        real_rate=round(real_rate, 1),
        gap=gap,
        stance="accommodative" if near_zero else "restrictive" if gap >= STANCE_BAND
        else "accommodative" if gap <= -STANCE_BAND else "near neutral",
    )
    return result


def _read_groups(indicators_context: list[dict]) -> tuple[dict, dict]:
    """(per-indicator stats, per-group {"read", "score", "scored", "total"})
    for one context, before the persistence rule."""
    indicators = {}
    scores: dict[str, list[int]] = {group: [] for group in GROUPS}
    totals = {group: 0 for group in GROUPS}
    for ind in indicators_context:
        config = INDICATORS.get(ind["key"], {})
        stats = indicator_stats(
            ind["history_window"],
            config.get("favorable_direction"),
            config.get("kind", "level"),
            ind.get("heuristic"),
        )
        stats["name"] = ind["name"]
        indicators[ind["key"]] = stats
        if ind["category"] in totals:
            totals[ind["category"]] += 1
            if stats["classification"] in _SCORE:
                scores[ind["category"]].append(_SCORE[stats["classification"]])
    return indicators, {group: {**_group_read(scores[group]), "total": totals[group]} for group in GROUPS}


def _known_on(reading: dict) -> date:
    """The day a reading became known to us: the day it was first fetched, else
    its own date. A monthly reading is dated its first of the month but is not
    public for weeks, so its date alone says nothing about what was known."""
    try:
        return date.fromisoformat((reading.get("fetched_at") or reading["date"])[:10])
    except ValueError:
        return date.fromisoformat(reading["date"])


def _context_as_of(indicators_context: list[dict], cutoff: date) -> list[dict]:
    """The context with each history cut to the readings known on or before
    `cutoff` (`_known_on`); an indicator with none left is dropped."""
    earlier = []
    for ind in indicators_context:
        history = [r for r in ind["history_window"] if _known_on(r) <= cutoff]
        if history:
            earlier.append({**ind, "history_window": history, "heuristic": heuristic_for(ind["key"], history)})
    return earlier


def compute_market_read(indicators_context: list[dict], as_of: date | None = None) -> dict:
    """The read of each group in `indicators_context` entries
    ({"key", "name", "category", "history_window", "heuristic"}).

    Returns {"groups": {group: {"read": "improving"|"mixed"|"weakening"|None,
    "score": float|None, "scored": int, "total": int}},
    "relationship": str|None, "policy": policy_stance's result,
    "indicators": {key: indicator_stats + "name"}}. `scored`
    counts the group's indicators that were favorable, neutral or
    unfavorable; with fewer than `MIN_SCORED_FOR_READ` the group has no
    read. An improving or weakening read stands only if the read from the
    data known `PERSISTENCE_DAYS` earlier (before `as_of`, by default the latest
    day any reading became known) agrees and was made from as many scored
    indicators, else the group reads "mixed"; with too little
    earlier history to read the group, today's read stands. There is no
    overall read: the groups look at different time frames and are not
    averaged together.
    """
    indicators, groups = _read_groups(indicators_context)
    known = [_known_on(r) for ind in indicators_context for r in ind["history_window"]]
    if known:
        as_of = as_of or max(known)
        _, earlier = _read_groups(_context_as_of(indicators_context, as_of - timedelta(days=PERSISTENCE_DAYS)))
        for group in GROUPS:
            raw = groups[group]["read"]
            # An earlier read from fewer scored indicators (a series stored only recently) is
            # not comparable with today's, so it is not used.
            comparable = earlier[group]["scored"] >= groups[group]["scored"]
            if raw in ("improving", "weakening") and comparable and earlier[group]["read"] not in (None, raw):
                groups[group]["read"] = "mixed"
    histories = {ind["key"]: ind["history_window"] for ind in indicators_context}
    return {
        "groups": groups,
        "relationship": relationship({group: groups[group]["read"] for group in GROUPS}),
        "policy": policy_stance(histories.get("fed_funds_rate"), histories.get("cpi")),
        "indicators": indicators,
    }


def group_reads(market_read: dict) -> dict[str, str | None]:
    """{group: read} from `compute_market_read`'s result: the compact form
    stored beside an AI explanation to tell whether it still matches."""
    return {group: market_read["groups"][group]["read"] for group in GROUPS}

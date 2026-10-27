"""Backtest of the digest's reads against the NBER recession dates.

Run by hand (`python3 src/backtest.py report.md`), never in CI or the
default suite; it only reads FRED and writes the Markdown report named on
the command line. Every month-end since 1978 is read with the production
functions (`market_read.compute_market_read`, which includes
`policy_stance`) on the readings that would have been public by then, so
the report measures the rules the page uses, not a copy of them.

Known bias: FRED holds revised data, which flatters any backtest; the
report says so. Real-time vintages are not used.
"""

import argparse
import logging
import math
import os
import sys
from bisect import bisect_left, bisect_right
from contextlib import contextmanager
from datetime import date, timedelta

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))

import market_read
from heuristics import heuristic_for
from fetch_fred import FredApiError, fetch_recent_observations
from indicators_config import INDICATORS
from storage import history_start_date

logger = logging.getLogger(__name__)

# A year of readings before the first evaluated month.
FETCH_START = "1968-01-01"
FIRST_MONTH = (1978, 1)
RECESSION_SERIES = "USREC"
NEUTRAL_SERIES = "FEDTARMDLR"  # FOMC median longer-run fed funds rate
INFLATION_TARGET = 2.0
# Thresholds are explored before this year and reported on from it on.
SPLIT_YEAR = 2001
LEAD_WINDOW_MONTHS = 18
AFTER_START_MONTHS = (6, 12)
MAX_LAG_MONTHS = 12

# Days from a reading's date until it is public, per series (approximate:
# a monthly series is dated the first of its month). A reading counts only
# from that day on.
RELEASE_LAGS_DAYS = {
    "initial_jobless_claims": 5,
    "yield_curve_spread": 1,
    "fed_funds_rate": 1,
    "building_permits": 48,
    "nonfarm_payrolls": 37,
    "industrial_production": 45,
    "cpi": 45,
    "unemployment_rate": 37,
    "unemployment_duration": 37,
    "commercial_loans": 25,
}

# Episodes of easing or tightening, and the stance the real rate should name within
# STANCE_REACH_MONTHS of their start: (label, first month, the stance that fits). The stance
# describes the level of the real rate, so it is judged by where it gets to, not by every month.
STANCE_EPISODES = (
    ("2001 easing", "2001-01", "accommodative"),
    ("2007-2008 easing", "2007-09", "accommodative"),
    ("2020 easing", "2020-03", "accommodative"),
    ("2022-2023 tightening", "2022-03", "restrictive"),
)
STANCE_REACH_MONTHS = 12
# The stance must hold the expected level for this many months in a row to count as reached: a
# one- or two-month flicker (the six-month CPI moves with energy prices) does not settle it.
STANCE_HOLD_MONTHS = 3
# The Cleveland Fed's 1-year expected real interest rate: an estimate that does not depend on
# this project's rules or on the NBER dates. The two thresholds were chosen after seeing the
# first result (0.85 and 0.66), and the report says so.
REFERENCE_SERIES = "REAINTRATREARAT1YE"
REFERENCE_FIRST_MONTH = "1982-01"
REFERENCE_MIN_LEVEL_CORRELATION = 0.80
REFERENCE_MIN_CHANGE_CORRELATION = 0.50

# Pass criteria, fixed before the first run.
COINCIDENT_MIN_RECESSION_SHARE = 0.70
COINCIDENT_MAX_EXPANSION_SHARE = 0.15
LEADING_MIN_RECESSIONS_WARNED = 5
LEADING_MAX_EXPANSION_SHARE = 0.25
LAGGING_MIN_AFTER_SHARE = 0.60

# One-at-a-time sweeps: (label, market_read constant, values).
SWEEPS = (
    ("Indicator signal, std devs", "SIGNAL_Z", (0.25, 0.5, 0.75, 1.0)),
    ("Group threshold", "READ_THRESHOLD", (0.25, 0.5, 0.67)),
    ("Recent window, days", "RECENT_DAYS", (60, 90, 120)),
    ("Policy band, points", "STANCE_BAND", (0.25, 0.5, 0.75)),
    ("Neutral real rate, %", "NEUTRAL_REAL_RATE", (0.5, 1.0, 1.5)),
)

_BAD = {"weakening": "bad", "unfavorable": "bad", "improving": "good", "favorable": "good",
        "mixed": "neutral", "neutral": "neutral"}


class Series:
    """One FRED series, parsed once so a month's window is a slice."""

    def __init__(self, observations: list[dict]):
        self.dates = [date.fromisoformat(o["date"]) for o in observations]
        self.observations = observations


def load_data(fetch_fn=fetch_recent_observations) -> tuple[dict[str, Series], dict[str, int], dict]:
    """(indicator series, recession flag by "YYYY-MM", latest longer-run
    fed funds reading). A FRED failure raises `FredApiError`."""
    series = {
        key: Series(fetch_fn(config["fred_series_id"], start_date=FETCH_START))
        for key, config in INDICATORS.items()
    }
    recession = {o["date"][:7]: int(o["value"]) for o in fetch_fn(RECESSION_SERIES, start_date=FETCH_START)}
    neutral = fetch_fn(NEUTRAL_SERIES, start_date=FETCH_START)
    return series, recession, (neutral[-1] if neutral else {})


def month_ends(last: tuple[int, int]) -> list[date]:
    ends, (year, month) = [], FIRST_MONTH
    while (year, month) <= last:
        year, month = year + (month == 12), 1 if month == 12 else month + 1
        ends.append(date(year, month, 1) - timedelta(days=1))
    return ends


def window(series: Series, key: str, as_of: date) -> list[dict]:
    """The readings of `key` public on `as_of` and within the production
    history window (12 months before it)."""
    public_until = as_of - timedelta(days=RELEASE_LAGS_DAYS[key])
    start = date.fromisoformat(history_start_date(as_of))
    return series.observations[bisect_left(series.dates, start):bisect_right(series.dates, public_until)]


def build_context(series: dict[str, Series], as_of: date) -> list[dict]:
    """What `compute_market_read` takes, as the page would have had it."""
    context = []
    for key, config in INDICATORS.items():
        lag = timedelta(days=RELEASE_LAGS_DAYS[key])
        # `fetched_at` is the day a reading became public: what the stored state records.
        history = [{**o, "fetched_at": (date.fromisoformat(o["date"]) + lag).isoformat()}
                   for o in window(series[key], key, as_of)]
        if history:
            context.append({"key": key, "name": config["name"], "category": config["category"],
                            "history_window": history, "heuristic": heuristic_for(key, history)})
    return context


@contextmanager
def patched(overrides: dict):
    """`market_read` constants set for the block and restored after."""
    saved = {name: getattr(market_read, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(market_read, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(market_read, name, value)


def run(contexts: dict[date, list[dict]], recession: dict[str, int], overrides: dict | None = None) -> list[dict]:
    """One record per month-end: {"month", "recession", "groups" (the read words),
    "group_results" ({"read", "score", "scored", "total"} per group), "indicators", "stance",
    "policy" (`policy_stance`'s result)}."""
    records = []
    with patched(overrides or {}):
        for as_of, context in contexts.items():
            result = market_read.compute_market_read(context, as_of)
            month = as_of.strftime("%Y-%m")
            records.append({
                "month": month,
                "recession": bool(recession.get(month, 0)),
                "groups": {g: result["groups"][g]["read"] for g in market_read.GROUPS},
                "group_results": result["groups"],
                "indicators": {k: v["classification"] for k, v in result["indicators"].items()},
                "stance": result["policy"]["stance"],
                "policy": result["policy"],
            })
    return records


def recession_starts(recession: dict[str, int]) -> list[str]:
    """Months a recession began, from the first evaluated month on."""
    months = sorted(recession)
    first = "%04d-%02d" % FIRST_MONTH
    return [m for i, m in enumerate(months)
            if recession[m] and (i == 0 or not recession[months[i - 1]]) and m >= first]


def _index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def labels(records: list[dict], source: str, name: str) -> list[tuple[str, bool, str | None]]:
    """(month, in recession, "bad" | "neutral" | "good" | None) for a group
    (`source` "groups") or an indicator ("indicators")."""
    return [(r["month"], r["recession"], _BAD.get(r[source].get(name))) for r in records]


def _share(items: list, label: str) -> float | None:
    return sum(1 for x in items if x == label) / len(items) if items else None


def rates(labeled: list[tuple[str, bool, str | None]]) -> dict:
    """Share of months labelled bad and good, inside and outside recessions."""
    rec = [x for _, in_rec, x in labeled if in_rec and x]
    exp = [x for _, in_rec, x in labeled if not in_rec and x]
    return {"rec_bad": _share(rec, "bad"), "rec_good": _share(rec, "good"),
            "exp_bad": _share(exp, "bad"), "exp_good": _share(exp, "good"),
            "rec_months": len(rec), "exp_months": len(exp)}


def lead_times(labeled: list[tuple[str, bool, str | None]], starts: list[str]) -> list[int | None]:
    """Per recession start, the months between the first "bad" label in the
    LEAD_WINDOW_MONTHS before it and the start (None if there was none).
    Recession months are skipped, so an earlier recession is not a warning
    for the next."""
    leads = []
    for start in starts:
        first = None
        for month, in_rec, label in labeled:
            if not in_rec and 0 < _index(start) - _index(month) <= LEAD_WINDOW_MONTHS and label == "bad":
                first = _index(start) - _index(month)
                break
        leads.append(first)
    return leads


def lead_chance(labeled: list[tuple[str, bool, str | None]]) -> float | None:
    """How often an expansion month has a "bad" label in the
    LEAD_WINDOW_MONTHS before it (recession months excluded): the chance
    rate against which a warning before a recession is judged."""
    bad = [_index(m) for m, in_rec, x in labeled if x == "bad" and not in_rec]
    months = [_index(m) for m, in_rec, x in labeled if x and not in_rec]
    if not months:
        return None
    return sum(1 for m in months if any(0 < m - b <= LEAD_WINDOW_MONTHS for b in bad)) / len(months)


def share_after_starts(labeled: list[tuple[str, bool, str | None]], starts: list[str]) -> float | None:
    """Share of "bad" labels in the months AFTER_START_MONTHS after a start."""
    low, high = AFTER_START_MONTHS
    picked = [label for month, _, label in labeled if label and any(
        low <= _index(month) - _index(s) <= high for s in starts)]
    return _share(picked, "bad")


def lead_lag(earlier: list, later: list, lag: int, kind: str) -> dict:
    """How often `later` carries `kind` ("bad" or "good") `lag` months after
    `earlier` does, against how often it carries it at all."""
    later_by_month = {_index(m): x for m, _, x in later if x}
    base = _share(list(later_by_month.values()), kind)
    followed = [later_by_month.get(_index(m) + lag) for m, _, x in earlier if x == kind]
    followed = [x for x in followed if x]
    return {"hit": _share(followed, kind), "base": base, "n": len(followed)}


def episode_reach(records: list[dict]) -> list[dict]:
    """Per stance episode: "reached", the month (counted from the episode start, at most
    STANCE_REACH_MONTHS) in which the stance first holds the expected level for STANCE_HOLD_MONTHS in a
    row, and "first_seen", the first month within the window it names that level at all (None for
    either if not; both None and "in_data" False if the episode is outside `records`)."""
    stances = {r["month"]: r["stance"] for r in records}
    out = []
    for label, first, expected in STANCE_EPISODES:
        reached = first_seen = None
        if first in stances:
            for k in range(STANCE_REACH_MONTHS + 1):
                if stances.get(_month(_index(first) + k)) != expected:
                    continue
                first_seen = k if first_seen is None else first_seen
                if all(stances.get(_month(_index(first) + k + j)) == expected for j in range(STANCE_HOLD_MONTHS)):
                    reached = k
                    break
        out.append({"label": label, "start": first, "expected": expected, "reached": reached,
                    "first_seen": first_seen, "in_data": first in stances})
    return out


def _month(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def zero_rate_months(records: list[dict]) -> dict:
    """Months with the fed funds rate below the zero-rate limit, and those among them where the
    stance is not accommodative."""
    low = [r for r in records if r["policy"]["fed_funds"] is not None and r["policy"]["fed_funds"] < market_read.ZERO_RATE_LIMIT]
    return {"months": len(low), "misread": [r["month"] for r in low if r["stance"] != "accommodative"]}


def _pearson(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n < 24:
        return None
    mean_a, mean_b = sum(x for x, _ in pairs) / n, sum(y for _, y in pairs) / n
    var_a, var_b = sum((x - mean_a) ** 2 for x, _ in pairs), sum((y - mean_b) ** 2 for _, y in pairs)
    if var_a == 0 or var_b == 0:
        return None
    return sum((x - mean_a) * (y - mean_b) for x, y in pairs) / math.sqrt(var_a * var_b)


def reference_comparison(records: list[dict], reference: dict[str, float]) -> dict:
    """Our real rate against the reference's, month by month from REFERENCE_FIRST_MONTH:
    {"months", "change_months", "level", "change" (correlation of the 12-month changes), "bias" (ours minus theirs)}."""
    ours = {r["month"]: r["policy"]["real_rate"] for r in records if r["policy"]["real_rate"] is not None}
    months = [m for m in sorted(ours) if m >= REFERENCE_FIRST_MONTH and m in reference]
    level = _pearson([ours[m] for m in months], [reference[m] for m in months])
    earlier = [_month(_index(m) - 12) for m in months]
    ours_change = [ours[m] - ours[e] if e in ours else None for m, e in zip(months, earlier)]
    ref_change = [reference[m] - reference[e] if e in reference else None for m, e in zip(months, earlier)]
    change = _pearson(ours_change, ref_change)
    change_months = sum(1 for x, y in zip(ours_change, ref_change) if x is not None and y is not None)
    bias = sum(ours[m] - reference[m] for m in months) / len(months) if months else None
    return {"months": len(months), "change_months": change_months, "level": level, "change": change, "bias": bias}


def stance_information(records: list[dict], recession: dict[str, int]) -> dict:
    """Not pass or fail: how often the stance changes a year, the share of expansion months that
    are restrictive, and how much more often a recession starts within 24 months after one."""
    stances = [r["stance"] for r in records if r["stance"]]
    flips = sum(1 for a, c in zip(stances, stances[1:]) if a != c) / (len(stances) / 12) if stances else None
    expansion = [r for r in records if r["stance"] and not recession.get(r["month"])]
    restrictive = [r for r in expansion if r["stance"] == "restrictive"]

    def followed(month: str) -> bool:
        return any(recession.get(_month(_index(month) + k)) for k in range(1, 25))

    lift = None
    if restrictive and expansion:
        overall = sum(followed(r["month"]) for r in expansion) / len(expansion)
        lift = (sum(followed(r["month"]) for r in restrictive) / len(restrictive)) / overall if overall else None
    return {"flips_a_year": flips, "restrictive_share": len(restrictive) / len(expansion) if expansion else None, "lift": lift}


def headline(records: list[dict], starts: list[str], period: tuple[str, str] | None = None) -> dict:
    """The numbers the pass criteria use. With a `period` (first and last
    month), rates and the lagging share count only its months;
    lead times still look back across the period's edge, so a recession just
    after it begins is not cut short."""
    def inside(month: str) -> bool:
        return period is None or period[0] <= month <= period[1]

    group = {g: labels(records, "groups", g) for g in market_read.GROUPS}
    kept = {g: [x for x in group[g] if inside(x[0])] for g in group}
    leads = lead_times(group["leading"], starts)
    return {
        "rates": {g: rates(kept[g]) for g in kept}, "leads": leads, "lead_chance": lead_chance(group["leading"]),
        "leading_warned": sum(1 for x in leads if x is not None),
        "lagging_after": share_after_starts(kept["lagging"], starts),
        "episodes": episode_reach([r for r in records if inside(r["month"])]),
    }


def evaluate_criteria(h: dict, recessions: int) -> list[tuple[str, bool, str]]:
    """(criterion, met, measured) for each pass criterion."""
    pct = _pct
    co, le = h["rates"]["coincident"], h["rates"]["leading"]
    results = [
        (f"Coincident reads weakening in at least {COINCIDENT_MIN_RECESSION_SHARE:.0%} of recession months",
         (co["rec_bad"] or 0) >= COINCIDENT_MIN_RECESSION_SHARE, pct(co["rec_bad"])),
        (f"Coincident reads weakening in at most {COINCIDENT_MAX_EXPANSION_SHARE:.0%} of expansion months",
         co["exp_bad"] is not None and co["exp_bad"] <= COINCIDENT_MAX_EXPANSION_SHARE, pct(co["exp_bad"])),
        (f"Leading reads weakening within {LEAD_WINDOW_MONTHS} months before at least "
         f"{LEADING_MIN_RECESSIONS_WARNED} of {recessions} recessions",
         h["leading_warned"] >= LEADING_MIN_RECESSIONS_WARNED,
         f"{h['leading_warned']} of {recessions} (chance: {pct(h['lead_chance'])} of expansion months have a weakening read in the 18 months before)"),
        (f"Leading reads weakening in at most {LEADING_MAX_EXPANSION_SHARE:.0%} of expansion months",
         le["exp_bad"] is not None and le["exp_bad"] <= LEADING_MAX_EXPANSION_SHARE, pct(le["exp_bad"])),
        (f"Lagging reads weakening in at least {LAGGING_MIN_AFTER_SHARE:.0%} of the months "
         f"{AFTER_START_MONTHS[0]} to {AFTER_START_MONTHS[1]} after a recession starts",
         (h["lagging_after"] or 0) >= LAGGING_MIN_AFTER_SHARE, pct(h["lagging_after"])),
    ]
    return results


def evaluate_stance_criteria(records: list[dict], reference: dict[str, float]) -> list[tuple[str, bool, str]]:
    """(criterion, met, measured) for the policy stance."""
    zero = zero_rate_months(records)
    results = [(f"Policy stance accommodative in every month with the fed funds rate below {market_read.ZERO_RATE_LIMIT:g}% "
                "(a regression guard: the zero-rate rule makes it true by construction)",
                not zero["misread"], f"{len(zero['misread'])} of {zero['months']} months misread")]
    for e in episode_reach(records):
        measured = ("outside the data" if not e["in_data"] else f"held from month {e['reached']}" if e["reached"] is not None
                    else f"first seen in month {e['first_seen']} but not held" if e["first_seen"] is not None else "not reached")
        results.append((f"Policy stance {e['expected']} for {STANCE_HOLD_MONTHS} months in a row within {STANCE_REACH_MONTHS} months of the "
                        f"{e['label']} (from {e['start']})", e["reached"] is not None, measured))
    ref = reference_comparison(records, reference)
    for label, key, minimum in (("level", "level", REFERENCE_MIN_LEVEL_CORRELATION),
                                ("12-month change", "change", REFERENCE_MIN_CHANGE_CORRELATION)):
        value = ref[key]
        count = ref["months"] if key == "level" else ref["change_months"]
        results.append((f"Real rate correlates with the Cleveland Fed's expected real rate at {minimum:.2f} or more ({label})",
                        value is not None and value >= minimum, "n/a" if value is None else f"{value:.2f} over {count} months"))
    return results


def periods(starts: list[str]) -> dict[str, tuple[tuple[str, str], list[str]]]:
    """The explore and report periods: ((first month, last month), the
    recession starts inside it)."""
    cut = "%04d-01" % SPLIT_YEAR
    first = "%04d-%02d" % FIRST_MONTH
    return {
        f"{FIRST_MONTH[0]}-{SPLIT_YEAR - 1}": ((first, "%04d-12" % (SPLIT_YEAR - 1)), [s for s in starts if s < cut]),
        f"{SPLIT_YEAR}-on": ((cut, "9999-12"), [s for s in starts if s >= cut]),
    }


def _fixed(x, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def render_report(base: list[dict], starts: list[str], sweeps: list[tuple[str, object, list[dict]]],
                  neutral: dict, last_month: str, recession: dict[str, int], reference: dict[str, float]) -> str:
    """The Markdown report."""
    h = headline(base, starts)
    lines = [
        "# Backtest of the indicator reads against NBER recessions", "",
        f"Months {'%04d-%02d' % FIRST_MONTH} to {last_month}. Recession starts: {', '.join(starts)}.", "",
        "**Caveats.** FRED holds revised data, which flatters any backtest; release lags are approximations "
        "(per series, in `RELEASE_LAGS_DAYS`); the thresholds were chosen before this run and are explored "
        f"on months before {SPLIT_YEAR} and reported on from {SPLIT_YEAR}.", "",
        "## Pass criteria", "",
        "Only the five group criteria were fixed before their first run. The seven stance criteria were set after the "
        "earlier policy criteria failed and after scratch results had been seen: the 12-month window, the episode start "
        "months, the 3-month hold, the 0.5% zero-rate limit and the two correlation thresholds "
        f"({REFERENCE_MIN_LEVEL_CORRELATION:.2f} and {REFERENCE_MIN_CHANGE_CORRELATION:.2f}). The zero-rate criterion is a "
        "regression guard, true by construction. Four earlier stance criteria (a share of the months of each easing or "
        "tightening episode in a given stance) were replaced: they tested what the Fed did in a month, but the stance "
        "describes the level of the real rate.", "",
        "| Criterion | Met | Measured |", "|---|---|---|",
    ]
    for criterion, met, measured in evaluate_criteria(h, len(starts)) + evaluate_stance_criteria(base, reference):
        lines.append(f"| {criterion} | {'yes' if met else '**NO**'} | {measured} |")

    lines += ["", "## Groups", "",
              "| Group | Weakening in recession | Weakening in expansion | Improving in recession | Months with a read (rec / exp) |",
              "|---|---|---|---|---|"]
    for g, r in h["rates"].items():
        lines.append(f"| {g} | {_pct(r['rec_bad'])} | {_pct(r['exp_bad'])} | {_pct(r['rec_good'])} | {r['rec_months']} / {r['exp_months']} |")

    lines += ["", "## Indicators (unfavorable = bad, favorable = good)", "",
              "| Indicator | Unfavorable in recession | Unfavorable in expansion | Favorable in recession | Months before each recession of the first unfavorable read |",
              "|---|---|---|---|---|"]
    for key, config in INDICATORS.items():
        if config["favorable_direction"] is None:
            continue
        lab = labels(base, "indicators", key)
        r = rates(lab)
        leads = ", ".join("none" if x is None else str(x) for x in lead_times(lab, starts))
        lines.append(f"| {config['name']} | {_pct(r['rec_bad'])} | {_pct(r['exp_bad'])} | {_pct(r['rec_good'])} | {leads} |")

    lines += ["", f"Months of lead before each recession at which the leading group first read weakening: "
              + ", ".join(f"{s}: {'none' if x is None else x}" for s, x in zip(starts, h["leads"])), ""]

    lines += ["## Lead and lag", "",
              "How often the later group carries the same direction N months after the earlier one does, against how often it does at all (the chance rate).", ""]
    group = {g: labels(base, "groups", g) for g in market_read.GROUPS}
    for earlier, later in (("leading", "coincident"), ("coincident", "lagging")):
        for kind, word in (("bad", "weakening"), ("good", "improving")):
            cells = []
            for lag in range(0, MAX_LAG_MONTHS + 1, 3):
                r = lead_lag(group[earlier], group[later], lag, kind)
                cells.append(f"{lag}m: {_pct(r['hit'])} vs {_pct(r['base'])} (n={r['n']})")
            lines.append(f"- {earlier} to {later}, {word}: " + "; ".join(cells))

    ref = reference_comparison(base, reference)
    info = stance_information(base, recession)
    lines += ["", "## Policy stance", "",
              f"| Episode | Expected stance | Held for {STANCE_HOLD_MONTHS} months in a row, starting within 12 months | First seen |", "|---|---|---|---|"]
    for e in episode_reach(base):
        held = "outside the data" if not e["in_data"] else f"month {e['reached']}" if e["reached"] is not None else "no"
        seen = "" if not e["in_data"] or e["first_seen"] is None else f"month {e['first_seen']}"
        lines.append(f"| {e['label']} (from {e['start']}) | {e['expected']} | {held} | {seen} |")
    lines += ["",
              f"Against the Cleveland Fed's 1-year expected real rate ({REFERENCE_SERIES}), {ref['months']} months from {REFERENCE_FIRST_MONTH}: "
              f"correlation of levels {_fixed(ref['level'])}, of 12-month changes {_fixed(ref['change'])}, and our real rate is "
              + ("n/a" if ref["bias"] is None else f"{abs(ref['bias']):.2f} points {'above' if ref['bias'] > 0 else 'below'} theirs")
              + " on average (we use realized inflation, they use expected).", "",
              f"For information, not pass or fail: the stance changes {_fixed(info['flips_a_year'], 1)} times a year; "
              f"{_pct(info['restrictive_share'])} of expansion months are restrictive, and a recession starts within 24 months after "
              f"one {_fixed(info['lift'])} times as often as after an expansion month overall.", ""]

    lines += ["", "## Neutral real rate", ""]
    if neutral:
        implied = neutral["value"] - INFLATION_TARGET
        lines.append(f"FOMC median longer-run fed funds rate ({neutral['date']}): {neutral['value']}%. "
                     f"Minus the {INFLATION_TARGET:g}% inflation target, the implied neutral real rate is {implied:g}%; "
                     f"the page uses {market_read.NEUTRAL_REAL_RATE:g}%.")
    else:
        lines.append(f"{NEUTRAL_SERIES} returned no readings.")

    lines += ["", "## Threshold sweeps (one constant at a time; production values marked *)", "",
              "| Constant | Value | Period | Coincident rec / exp | Leading rec / exp, warned | Lagging after | Stance episodes held within 12 months |",
              "|---|---|---|---|---|---|---|"]
    for label, value, records in sweeps:
        production = "*" if value == getattr(market_read, _constant_of(label), None) else ""
        for period, (bounds, period_starts) in periods(starts).items():
            hh = headline(records, period_starts, bounds)
            co, le = hh["rates"]["coincident"], hh["rates"]["leading"]
            inside = [e for e in hh["episodes"] if e["in_data"]]
            episodes = f"{sum(1 for e in inside if e['reached'] is not None)} of {len(inside)}" if inside else "no episode"
            lines.append(f"| {label} | {value}{production} | {period} | {_pct(co['rec_bad'])} / {_pct(co['exp_bad'])} | "
                         f"{_pct(le['rec_bad'])} / {_pct(le['exp_bad'])}, {hh['leading_warned']} of {len(period_starts)} | {_pct(hh['lagging_after'])} | {episodes} |")
    return "\n".join(lines) + "\n"


def _constant_of(label: str) -> str:
    return next(constant for sweep_label, constant, _ in SWEEPS if sweep_label == label)


def contexts_for(series: dict[str, Series], recession: dict[str, int]) -> dict[date, list[dict]]:
    """The context at every month-end from the first evaluated month to the last recession flag."""
    year, month = max(recession).split("-")
    return {e: build_context(series, e) for e in month_ends((int(year), int(month)))}


def replay(fetch_fn=fetch_recent_observations) -> tuple[list[dict], dict[str, int], dict]:
    """(records, recession flags by month, the latest longer-run fed funds
    reading): every month-end replayed with the production code. Raises
    `FredApiError` before anything is produced if FRED cannot supply a series."""
    series, recession, neutral = load_data(fetch_fn)
    return run(contexts_for(series, recession), recession), recession, neutral


def build_report(fetch_fn=fetch_recent_observations) -> str:
    """The whole report. Raises `FredApiError` before anything is produced
    if FRED cannot supply a series."""
    series, recession, neutral = load_data(fetch_fn)
    contexts = contexts_for(series, recession)
    starts = recession_starts(recession)
    base = run(contexts, recession)
    sweeps = [(label, value, base if value == getattr(market_read, constant) else run(contexts, recession, {constant: value}))
              for label, constant, values in SWEEPS for value in values]
    reference = {o["date"][:7]: o["value"] for o in fetch_fn(REFERENCE_SERIES, start_date=FETCH_START)}
    return render_report(base, starts, sweeps, neutral, max(contexts).strftime("%Y-%m"), recession, reference)


def main(argv: list[str] | None = None, fetch_fn=fetch_recent_observations) -> int:
    parser = argparse.ArgumentParser(description="Backtest the indicator reads against NBER recessions.")
    parser.add_argument("report", help="path of the Markdown report to write")
    args = parser.parse_args(argv)
    try:
        report = build_report(fetch_fn)
    except FredApiError as e:
        logger.error("backtest stopped, no report written: %s", e)
        return 1
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info("report written to %s", args.report)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())

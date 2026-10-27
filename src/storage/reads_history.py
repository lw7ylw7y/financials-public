"""The saved monthly group reads, the NBER recession months, and the fit
that lines each group's curve up with those months.

Two Redis hashes, one atomic field per month ("2026-10"), never a blob:
`indicator_reads` (the three groups' read, score, scored and total, the
policy stance, `source` "live" or "replay", and `saved_at`) and
`nber_recessions` (1 in a recession month, else 0). A live entry is the
last Indicator Check run in its month, so the current month is in
progress until the next one starts. A replay entry is the backtest's
month-end read on today's revised data; a live write onto a month the
replay filled replaces it.

A Redis failure raises `KvStoreError`; the caller decides what it means
(the job logs and goes on, the page shows the card as unavailable).

`fit_alignment` is pure: for each group, the shift in months that best
matches its weakness to the recession months, used only when it clearly
beats no shift and both halves of the history agree.
"""

import math
import os
import sys
from datetime import datetime, timezone

_STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_STORAGE_DIR, "..", "web"))

from kv_store import hgetall_json, hset_json, hset_many_json  # noqa: E402

READS_KEY = "indicator_reads"
RECESSIONS_KEY = "nber_recessions"
GROUPS = ("leading", "coincident", "lagging")
# Fields per multi-field write, so one request stays a few hundred KB.
WRITE_CHUNK = 200

# The fit: shifts tried (months; a positive shift means the group's weakness comes before the
# recession months, a negative one after), the gain over no shift a shift must show, how far
# apart the shifts found in the two halves of the history may be, the year that splits them, and
# the shortest history worth fitting.
SEARCH_MONTHS = range(-18, 25)
MIN_GAIN = 0.05
MAX_HALF_DISAGREEMENT = 3
SPLIT_MONTH = "2001-01"
MIN_HISTORY_MONTHS = 120


def make_entry(groups: dict, stance: str | None, source: str, now: datetime | None = None) -> dict:
    """The stored shape of one month's read: `groups` is `compute_market_read`'s
    "groups" and `stance` the policy stance."""
    now = now or datetime.now(timezone.utc)
    return {
        "groups": {g: {k: groups[g][k] for k in ("read", "score", "scored", "total")} for g in GROUPS},
        "stance": stance,
        "source": source,
        "saved_at": now.isoformat(),
    }


def month_of(now: datetime) -> str:
    return now.strftime("%Y-%m")


def save_month(month: str, entry: dict) -> None:
    """Writes one month's field, replacing only that month."""
    hset_json(READS_KEY, month, entry)


def load_reads() -> dict[str, dict]:
    return hgetall_json(READS_KEY)


def save_missing(entries: dict[str, dict], existing: set[str]) -> int:
    """Writes the entries for months not in `existing`, in a few
    multi-field writes; returns how many were written."""
    missing = {m: e for m, e in entries.items() if m not in existing}
    items = sorted(missing.items())
    for i in range(0, len(items), WRITE_CHUNK):
        hset_many_json(READS_KEY, dict(items[i:i + WRITE_CHUNK]))
    return len(items)


def load_recessions() -> dict[str, int]:
    return {m: int(v) for m, v in hgetall_json(RECESSIONS_KEY).items()}


def save_recessions(flags: dict[str, int]) -> None:
    """Writes the given months' flags in one multi-field write."""
    if flags:
        hset_many_json(RECESSIONS_KEY, {m: int(v) for m, v in flags.items()})


def _month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def _month_name(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _correlation(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n < 24:
        return None
    mean_a, mean_b = sum(x for x, _ in pairs) / n, sum(y for _, y in pairs) / n
    var_a = sum((x - mean_a) ** 2 for x, _ in pairs)
    var_b = sum((y - mean_b) ** 2 for _, y in pairs)
    if var_a == 0 or var_b == 0:
        return None
    return sum((x - mean_a) * (y - mean_b) for x, y in pairs) / math.sqrt(var_a * var_b)


def _lagged_correlation(weakness: list, recession: list, shift: int) -> float | None:
    """Correlation of weakness at month t with the recession flag at t + shift."""
    if shift >= 0:
        return _correlation(weakness[:len(weakness) - shift] if shift else weakness, recession[shift:])
    return _correlation(weakness[-shift:], recession[:len(recession) + shift])


def _best_shift(weakness: list, recession: list) -> tuple[int, float, float] | None:
    """(best shift, its correlation, the correlation with no shift)."""
    scored = [(k, _lagged_correlation(weakness, recession, k)) for k in SEARCH_MONTHS]
    scored = [(k, c) for k, c in scored if c is not None]
    zero = dict(scored).get(0)
    if not scored or zero is None:
        return None
    best, corr = max(scored, key=lambda kc: kc[1])
    return best, corr, zero


def fit_alignment(reads: dict[str, dict], recessions: dict[str, int]) -> dict[str, dict]:
    """Per group: {"shift": months used (0 if none), "best", "gain", "halves": (first, second),
    "applied": bool, "reason": why not, if not}. A group's curve is drawn `shift` months later,
    so a shift of -7 (weakness that comes 7 months after the recession months) draws it 7 months
    earlier, onto them."""
    both = sorted(m for m in reads if m in recessions)
    months = []
    if both:
        # One slot per calendar month, so a month missing from either hash is a hole that the
        # correlation skips; it must not shift the later months' positions.
        first, last = _month_index(both[0]), _month_index(both[-1])
        months = [_month_name(i) for i in range(first, last + 1)]
    result = {}
    for group in GROUPS:
        base = {"shift": 0, "best": None, "gain": None, "halves": None, "applied": False, "reason": ""}
        if len(months) < MIN_HISTORY_MONTHS:
            result[group] = {**base, "reason": f"fewer than {MIN_HISTORY_MONTHS // 12} years of history"}
            continue
        weakness = []
        for m in months:
            score = reads[m]["groups"][group]["score"] if m in reads else None
            weakness.append(None if score is None else -score)
        flags = [float(recessions[m]) if m in recessions else None for m in months]
        whole = _best_shift(weakness, flags)
        cut = next((i for i, m in enumerate(months) if m >= SPLIT_MONTH), len(months))
        first = _best_shift(weakness[:cut], flags[:cut]) if cut >= MIN_HISTORY_MONTHS // 2 else None
        second = _best_shift(weakness[cut:], flags[cut:]) if len(months) - cut >= MIN_HISTORY_MONTHS // 2 else None
        if whole is None:
            result[group] = {**base, "reason": "no usable scores"}
            continue
        best, corr, zero = whole
        gain = round(corr - zero, 2)
        halves = (first[0] if first else None, second[0] if second else None)
        entry = {**base, "best": best, "gain": gain, "halves": halves}
        if gain < MIN_GAIN:
            entry["reason"] = f"best shift {best} months beats no shift by only {gain:.2f}"
        elif None in halves or abs(halves[0] - halves[1]) > MAX_HALF_DISAGREEMENT:
            entry["reason"] = f"the two halves of the history disagree ({halves[0]} and {halves[1]} months)"
        else:
            entry.update(shift=best, applied=True)
        result[group] = entry
    return result

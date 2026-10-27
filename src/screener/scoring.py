"""Screener scoring: pure functions, no I/O.

Turns EDGAR company facts and Finnhub figures into a candidate record
of raw numbers, then evaluates the hard filters and the ranking score
from a record and a settings object. Filters and score are computed
whenever they are needed, never stored, so changing a setting changes
the answer immediately. `ScreenSettings`' defaults are the starting
values; a value of `None` switches that filter off.

Return on investment (`roi`) is Finnhub's `roiTTM`, not a computed
return on invested capital.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone

# SIC codes counted as tech: computer and office equipment, telecom
# equipment, electronic components and semiconductors, test and
# measurement instruments, software and computer services.
TECH_SIC = frozenset(
    list(range(3570, 3580))
    + [3661, 3663, 3669]
    + list(range(3670, 3680))
    + [3825, 3826, 3829]
    + list(range(7370, 7380))
)

STAGE_NON_TECH = "non_tech"
STAGE_NO_CIK = "no_cik"
STAGE_TECH = "tech"
STAGES = (STAGE_NON_TECH, STAGE_NO_CIK, STAGE_TECH)

ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A")
CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
OPERATING_CASH_FLOW_TAGS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
SHARES_TAG = "WeightedAverageNumberOfSharesOutstandingBasic"

# A fiscal year is 350 to 380 days; anything else is a quarter or a
# transition period.
_FISCAL_YEAR_DAYS = (350, 380)
# A share count that grows (or shrinks to one over) this many times in
# one year is a split or reverse split, not dilution or a buyback.
SPLIT_JUMP_RATIO = 3
_FCF_YEARS = 3
_SHARE_YEARS = 4
# Annual figures whose latest fiscal year ended longer ago than this are
# not current (a company that stopped tagging, or moved to IFRS).
MAX_FIGURE_AGE_DAYS = 548

FLAG_IFRS = "IFRS filer, not scored yet"
FLAG_NO_OPERATING_CASH_FLOW = "No operating cash flow reported"
FLAG_NO_CAPEX = "Capex not reported"
FLAG_FEW_SHARE_YEARS = "Fewer than two years of share data"
FLAG_OLD_FIGURES = "Latest annual figures are more than 18 months old"


@dataclass(frozen=True)
class ScreenSettings:
    """The hard filters. The market cap band is always applied; every
    other value can be `None` to switch that filter off.
    """

    market_cap_min_m: float = 1200.0
    market_cap_max_m: float = 22700.0
    net_margin_min: float | None = 0.0       # percent, strictly above
    fcf_min_m: float | None = 0.0            # $ millions, latest fiscal year, strictly above
    max_debt_equity: float | None = 0.5      # at most
    max_dilution_pct: float | None = 5.0     # percent a year, at most
    min_roi_pct: float | None = 5.0          # percent, at least
    stale_years: float | None = 10.0         # listed at least this many years ...
    stale_min_growth_pct: float = 10.0       # ... with revenue growth below this is stale


DEFAULT_SETTINGS = ScreenSettings()

# A dismissed name is flagged as improved when its score has risen by at
# least this many points since it was dismissed.
IMPROVED_SCORE_DELTA = 10.0


def _annual_points(facts: dict, tag: str, unit: str) -> dict[str, float]:
    points = facts.get(tag, {}).get("units", {}).get(unit, [])
    values = {}
    for point in sorted(points, key=lambda p: p.get("filed", "")):
        if point.get("form") not in ANNUAL_FORMS or "start" not in point:
            continue
        days = (date.fromisoformat(point["end"]) - date.fromisoformat(point["start"])).days
        if _FISCAL_YEAR_DAYS[0] <= days <= _FISCAL_YEAR_DAYS[1]:
            values[point["end"]] = point["val"]
    return values


def _annual_values(facts: dict, tags, unit: str) -> dict[str, float]:
    """Fiscal-year-end date to value, from annual filings. Tags are
    merged per fiscal year, the earlier tag in `tags` winning, so a
    company that changed which concept it reports keeps its history.
    A later filing for the same year (an amendment) wins within a tag.
    """
    merged = {}
    for tag in tags:
        for end, value in _annual_points(facts, tag, unit).items():
            merged.setdefault(end, value)
    return merged


def _latest_annual_end(taxonomy_facts: dict) -> str | None:
    """The latest fiscal year end of any annual figure in a taxonomy."""
    latest = None
    for fact in taxonomy_facts.values():
        for points in fact.get("units", {}).values():
            for point in points:
                if point.get("form") in ANNUAL_FORMS and "start" in point:
                    if latest is None or point["end"] > latest:
                        latest = point["end"]
    return latest


def _other_unit(facts: dict, tags) -> str | None:
    """A non-USD unit an operating-cash-flow tag is reported in, if any."""
    for tag in tags:
        for unit in facts.get(tag, {}).get("units", {}):
            if unit != "USD":
                return unit
    return None


def extract_edgar_figures(company_facts: dict, today: date) -> dict:
    """Free cash flow, share counts and dilution from EDGAR company
    facts: {"fcf_by_year": {fiscal year end: $ millions}, "shares_by_year":
    {fiscal year end: millions}, "dilution_pct_per_year": float | None,
    "flags": [str]}.

    A company is flagged, and kept out of the ranking, when its figures
    cannot be trusted: an IFRS filer (other tags, often another
    currency, or newer than its us-gaap data), cash flow reported in
    another currency, no operating cash flow, capex missing for the
    latest year, latest annual figures more than `MAX_FIGURE_AGE_DAYS`
    old, fewer than two years of share counts, or a share count that
    changes `SPLIT_JUMP_RATIO` times in a year in either direction (a
    split or reverse split, which would read as huge dilution or a
    huge buyback). Whatever figures could be read are still returned,
    so a flagged row can be checked by hand. `today` is required so the
    freshness check never reads a hidden clock.
    """
    taxonomies = company_facts.get("facts", {})
    gaap = taxonomies.get("us-gaap", {})
    empty = {"fcf_by_year": {}, "shares_by_year": {}, "dilution_pct_per_year": None}

    operating = _annual_values(gaap, OPERATING_CASH_FLOW_TAGS, "USD")
    ifrs_end = _latest_annual_end(taxonomies["ifrs-full"]) if "ifrs-full" in taxonomies else None
    is_ifrs_filer = "ifrs-full" in taxonomies and (not operating or (ifrs_end and ifrs_end > max(operating)))

    flags = []
    capex = _annual_values(gaap, CAPEX_TAGS, "USD")

    fcf_by_year = {}
    if not operating:
        foreign_unit = _other_unit(gaap, OPERATING_CASH_FLOW_TAGS)
        flags.append(f"Cash flow reported in {foreign_unit}, not scored yet" if foreign_unit else FLAG_NO_OPERATING_CASH_FLOW)
    elif max(operating) not in capex:
        flags.append(FLAG_NO_CAPEX)
    else:
        years = sorted(set(operating) & set(capex))[-_FCF_YEARS:]
        fcf_by_year = {year: (operating[year] - capex[year]) / 1e6 for year in years}

    shares = _annual_values(gaap, (SHARES_TAG,), "shares")
    ends = sorted(shares)[-_SHARE_YEARS:]
    shares_by_year = {end: shares[end] / 1e6 for end in ends}
    dilution = None
    if len(ends) < 2:
        flags.append(FLAG_FEW_SHARE_YEARS)
    else:
        for earlier, later in zip(ends, ends[1:]):
            if not (shares[earlier] and shares[later]):
                continue
            ratio = shares[later] / shares[earlier]
            if ratio >= SPLIT_JUMP_RATIO:
                flags.append(f"Possible stock split (shares rose {ratio:.1f}x in one year, {later[:4]})")
            elif ratio <= 1 / SPLIT_JUMP_RATIO:
                flags.append(f"Possible reverse split (shares fell to {ratio:.2f}x in one year, {later[:4]})")
        span_years = (date.fromisoformat(ends[-1]) - date.fromisoformat(ends[0])).days / 365.25
        if span_years and shares[ends[0]]:
            dilution = ((shares[ends[-1]] / shares[ends[0]]) ** (1 / span_years) - 1) * 100

    latest_ends = [latest for latest in (max(operating, default=None), max(ends, default=None)) if latest]
    if latest_ends and (today - date.fromisoformat(min(latest_ends))).days > MAX_FIGURE_AGE_DAYS:
        flags.append(FLAG_OLD_FIGURES)

    return {
        "fcf_by_year": fcf_by_year,
        "shares_by_year": shares_by_year,
        "dilution_pct_per_year": dilution,
        "flags": [FLAG_IFRS] if is_ifrs_filer else flags,
    }


def build_candidate_record(
    cik: int, profile: dict, metrics: dict, figures: dict, now: datetime | None = None
) -> dict:
    """The raw numbers behind every filter, as stored: `profile` is
    `finnhub_client.fetch_company_profile`'s result, `metrics` is
    `fetch_stock_metrics`'s, `figures` is `extract_edgar_figures`'s.
    No pass or fail and no score: those are computed when read.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "name": profile.get("name"),
        "cik": cik,
        "ipo_date": profile.get("ipo_date"),
        "week52_low": metrics.get("low"),
        "week52_high": metrics.get("high"),
        "market_cap": profile.get("market_cap") or metrics.get("market_cap"),
        "pe_ratio": metrics.get("pe_ratio"),
        "peg_ratio": metrics.get("peg_ratio"),
        "metrics": {
            "roi": metrics.get("roi"),
            "roe": metrics.get("roe"),
            "net_margin": metrics.get("net_margin"),
            "debt_to_equity": metrics.get("debt_to_equity"),
            "eps_growth": metrics.get("eps_growth"),
        },
        "revenue_growth": metrics.get("revenue_growth"),
        "fcf_by_year": figures["fcf_by_year"],
        "shares_by_year": figures["shares_by_year"],
        "dilution_pct_per_year": figures["dilution_pct_per_year"],
        "flags": list(figures["flags"]),
        "market_at": stamp,
        "scored_at": stamp,
    }


def is_tech_sic(sic: int | None) -> bool:
    return sic in TECH_SIC


def classify_symbol(cik: int | None, sic: int | None) -> str:
    """The universe stage for a symbol: no CIK in EDGAR's ticker file
    (it may appear there later), a non-tech SIC (never looked at
    again), or tech.
    """
    if cik is None:
        return STAGE_NO_CIK
    return STAGE_TECH if is_tech_sic(sic) else STAGE_NON_TECH


def is_stale(record: dict, settings: ScreenSettings = DEFAULT_SETTINGS, today: date | None = None) -> bool:
    """Listed `stale_years` or more with revenue growth below the
    minimum. A company with no (or an unreadable) listing date or no
    growth figure is never called stale: a gap in the data doesn't
    remove a name.
    """
    if settings.stale_years is None:
        return False
    ipo_date, growth = record.get("ipo_date"), record.get("revenue_growth")
    if not ipo_date or growth is None:
        return False
    try:
        listed = date.fromisoformat(ipo_date)
    except ValueError:
        return False
    years = ((today or date.today()) - listed).days / 365.25
    return years >= settings.stale_years and growth < settings.stale_min_growth_pct


def _latest_fcf_m(record: dict) -> float | None:
    fcf = record.get("fcf_by_year") or {}
    return fcf[max(fcf)] if fcf else None


def evaluate(record: dict, settings: ScreenSettings = DEFAULT_SETTINGS, today: date | None = None) -> dict:
    """{"flagged": bool, "checks": {filter name: bool}, "passes": bool}.

    A missing figure fails the filter that needs it. A flagged record
    (data that cannot be trusted) never passes, whatever its numbers.
    Only filters that are switched on appear in `checks`.
    """
    metrics = record.get("metrics") or {}
    checks = {}

    cap = record.get("market_cap")
    checks["market_cap"] = cap is not None and settings.market_cap_min_m <= cap <= settings.market_cap_max_m
    if settings.net_margin_min is not None:
        value = metrics.get("net_margin")
        checks["net_margin"] = value is not None and value > settings.net_margin_min
    if settings.fcf_min_m is not None:
        value = _latest_fcf_m(record)
        checks["free_cash_flow"] = value is not None and value > settings.fcf_min_m
    if settings.max_debt_equity is not None:
        value = metrics.get("debt_to_equity")
        checks["debt_equity"] = value is not None and value <= settings.max_debt_equity
    if settings.max_dilution_pct is not None:
        value = record.get("dilution_pct_per_year")
        checks["dilution"] = value is not None and value <= settings.max_dilution_pct
    if settings.min_roi_pct is not None:
        value = metrics.get("roi")
        checks["roi"] = value is not None and value >= settings.min_roi_pct
    if settings.stale_years is not None:
        checks["not_stale"] = not is_stale(record, settings, today)

    flagged = bool(record.get("flags"))
    return {"flagged": flagged, "checks": checks, "passes": not flagged and all(checks.values())}


def symbols_to_fetch(universe: dict[str, dict], candidates: dict[str, dict], settings: ScreenSettings = DEFAULT_SETTINGS) -> list[str]:
    """Tech symbols whose stored market cap is inside the band and that
    have no candidate record yet, sorted: the ones the job fetches in
    full. A symbol whose market cap is unknown is not in any band.
    """
    return sorted(
        symbol
        for symbol, entry in universe.items()
        if entry["stage"] == STAGE_TECH
        and symbol not in candidates
        and entry["market_cap"] is not None
        and settings.market_cap_min_m <= entry["market_cap"] <= settings.market_cap_max_m
    )


def percentile_ranks(values: list[float]) -> list[float]:
    """0 to 100 for each value: its position among the others, ties
    sharing the average position. A single value ranks 50.
    """
    count = len(values)
    if count == 1:
        return [50.0]
    order = sorted(range(count), key=lambda i: values[i])
    ranks = [0.0] * count
    start = 0
    while start < count:
        end = start
        while end + 1 < count and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 / (count - 1) * 100
        start = end + 1
    return ranks


def score_candidates(
    records: dict[str, dict], settings: ScreenSettings = DEFAULT_SETTINGS, today: date | None = None
) -> dict[str, float]:
    """Symbol to score (0 to 100) for every record that passes every
    filter, whatever its shortlist or dismissed status, so dismissing
    never changes another name's score. The score is the mean
    percentile rank, among those names, of ROI, revenue growth, net
    margin, low dilution and low debt/equity, equally weighted; any
    missing figure (possible when its filter is switched off) ranks
    worst on that measure. A name that fails a filter has
    no entry.
    """
    passing = {s: r for s, r in records.items() if evaluate(r, settings, today)["passes"]}
    if not passing:
        return {}
    symbols = list(passing)

    def column(pick) -> list[float]:
        return percentile_ranks([pick(passing[s]) for s in symbols])

    def higher_is_better(value):
        return value if value is not None else float("-inf")

    def lower_is_better(value):
        return -value if value is not None else float("-inf")

    columns = [
        column(lambda r: higher_is_better((r.get("metrics") or {}).get("roi"))),
        column(lambda r: higher_is_better(r.get("revenue_growth"))),
        column(lambda r: higher_is_better((r.get("metrics") or {}).get("net_margin"))),
        column(lambda r: lower_is_better(r.get("dilution_pct_per_year"))),
        column(lambda r: lower_is_better((r.get("metrics") or {}).get("debt_to_equity"))),
    ]
    return {
        symbol: round(sum(col[i] for col in columns) / len(columns), 1) for i, symbol in enumerate(symbols)
    }


def dismissal_snapshot(
    symbol: str, records: dict[str, dict], settings: ScreenSettings = DEFAULT_SETTINGS, today: date | None = None
) -> dict:
    """What a dismissed name looked like when it was dismissed:
    {"score_at_dismissal": float | None, "passed_at_dismissal": bool}.
    A name that failed the filters, or is flagged, has no score and did
    not pass.
    """
    passed = evaluate(records[symbol], settings, today)["passes"]
    score = score_candidates(records, settings, today).get(symbol) if passed else None
    return {"score_at_dismissal": score, "passed_at_dismissal": passed}


def improved_since_dismissal(status: dict, passes_now: bool, score_now: float | None) -> bool:
    """True when a dismissed name now passes every filter and either did
    not pass when it was dismissed or its score has risen by at least
    `IMPROVED_SCORE_DELTA`. A name with no recorded score that passed
    then cannot be compared, so it is not improved.
    """
    if not passes_now:
        return False
    if not status.get("passed_at_dismissal"):
        return True
    before = status.get("score_at_dismissal")
    return before is not None and score_now is not None and score_now - before >= IMPROVED_SCORE_DELTA

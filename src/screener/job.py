"""Nightly screener job: classify new symbols, keep known ones fresh, and
build the candidate records the page ranks.

Run as `python3 src/screener/job.py` (the scheduled workflow does). Each
run, in order:

1. Symbols in Finnhub's Nasdaq/NYSE common-stock list that are not in
   `screener_universe` yet get a stage (no CIK in EDGAR, non-tech, or
   tech with a market cap). Symbols already marked `no_cik` are looked
   up again, since a new listing can appear in Finnhub before EDGAR.
2. Each candidate whose earnings dates are missing or more than 7 days
   old gets them (`screener_earnings`): the next report from Finnhub's
   earnings calendar, the last from EDGAR (the filing date of its latest
   10-Q or annual report). Then every tech symbol that is due, oldest
   first, is refreshed: a candidate is due 3 days after its last report
   was filed if it has not been refreshed since (90 days after its last refresh when no date is
   known) and gets its metrics and EDGAR facts again (whatever its
   shortlist or dismissed status, which this job never reads); a tech
   symbol without a record is due 90 days after its last check and
   gets a market cap check.
3. Every tech symbol inside the saved market cap band (the default
   band until one is saved) with no candidate record is fetched in
   full and becomes a candidate, and gets its earnings dates.

Progress is saved per symbol, so a run that stops at the Finnhub call
cap or a rate limit is simply continued by the next night's run. A 429
or 403 stops the run and is never retried; any other failure for one
symbol is logged by symbol only and the run carries on. Prices are not
the job's business: the page fetches them live.
"""

import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (_HERE, os.path.join(os.path.dirname(_HERE), "web")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import edgar_client  # noqa: E402
import finnhub_client  # noqa: E402
import scoring  # noqa: E402
import settings as screen_settings  # noqa: E402
import store  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_NIGHTLY_CALL_CAP = 1500
REFRESH_AFTER = timedelta(days=90)
# Finnhub and EDGAR need a few days after a report to publish the quarter.
EARNINGS_MARGIN = timedelta(days=3)
EARNINGS_DATES_MAX_AGE = timedelta(days=7)
# Finnhub's free tier allows 60 calls a minute.
FINNHUB_MIN_INTERVAL = 1.1


class CallCapReached(Exception):
    """This run's Finnhub call budget is used up."""


class _FinnhubBudget:
    """Counts and paces every Finnhub call made through it."""

    def __init__(self, module, cap: int, pace):
        self._module = module
        self._cap = cap
        self._pace = pace
        self.calls = 0

    def call(self, name: str, *args, **kwargs):
        if self.calls >= self._cap:
            raise CallCapReached()
        self.calls += 1
        self._pace()
        return getattr(self._module, name)(*args, **kwargs)


def _make_pacer(min_interval: float):
    last = [0.0]

    def pace():
        wait = min_interval - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()

    return pace


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _redact(error: Exception) -> str:
    """`error` as log text without any API token a request URL carried."""
    return re.sub(r"token=[^&\s'\")]+", "token=REDACTED", str(error))


def run_job(
    now: datetime | None = None,
    call_cap: int = DEFAULT_NIGHTLY_CALL_CAP,
    *,
    finnhub=finnhub_client,
    edgar=edgar_client,
    job_store=store,
    settings_store=screen_settings,
    pace=None,
) -> dict:
    """Runs the work order and returns (and saves) the run counts."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    band = settings_store.load_settings()
    budget = _FinnhubBudget(finnhub, call_cap, pace or _make_pacer(FINNHUB_MIN_INTERVAL))
    counts = {
        "new": 0, "no_cik_rechecked": 0, "refreshed": 0, "new_candidates": 0, "dates_fetched": 0, "failed": 0, "stopped": None,
    }

    symbols = finnhub.fetch_us_common_stocks()
    listed = set(symbols)
    budget.calls += 1
    ciks = edgar.fetch_ticker_ciks()
    universe = job_store.load_universe()
    candidates = job_store.load_candidates()
    earnings = job_store.load_earnings()
    profiles: dict[str, dict] = {}

    def fetch_profile(symbol: str) -> dict:
        if symbol not in profiles:
            profiles[symbol] = budget.call("fetch_company_profile", symbol)
        return profiles[symbol]

    def classify(symbol: str, cik: int | None) -> None:
        """Gives `symbol` a stage; a tech symbol also gets its market cap."""
        sic = None
        if cik is not None:
            summary = edgar.fetch_submissions_summary(cik)
            sic = summary["sic"] if summary else None
        stage = scoring.classify_symbol(cik, sic)
        entry = {"cik": cik, "sic": sic, "stage": stage, "market_cap": None, "checked_at": stamp}
        if stage == scoring.STAGE_TECH:
            entry["market_cap"] = fetch_profile(symbol)["market_cap"]
        job_store.save_universe_entry(symbol, entry)
        universe[symbol] = entry

    def build_candidate(symbol: str, entry: dict) -> None:
        profile = fetch_profile(symbol)
        metrics = budget.call("fetch_stock_metrics", symbol, require_range=False)
        facts = edgar.fetch_company_facts(entry["cik"])
        figures = scoring.extract_edgar_figures(facts or {}, today=now.date())
        record = scoring.build_candidate_record(entry["cik"], profile, metrics, figures, now)
        job_store.save_candidate(symbol, record)
        candidates[symbol] = record
        entry = {**entry, "market_cap": record["market_cap"], "checked_at": stamp}
        job_store.save_universe_entry(symbol, entry)
        universe[symbol] = entry

    def check_market_cap(symbol: str, entry: dict) -> None:
        profile = budget.call("fetch_company_profile", symbol)
        profiles[symbol] = profile
        entry = {**entry, "market_cap": profile["market_cap"], "checked_at": stamp}
        job_store.save_universe_entry(symbol, entry)
        universe[symbol] = entry

    def fetch_earnings(symbol: str) -> None:
        """`next` is Finnhub's projected next report; `last` is the filing
        date of the company's latest 10-Q or annual report (Finnhub's
        free calendar lists no past reports)."""
        entry = {
            "next": budget.call("fetch_next_earnings_date", symbol, now.date()),
            "last": edgar.fetch_latest_report_date(universe[symbol]["cik"]),
            "fetched_at": stamp,
        }
        job_store.save_earnings(symbol, entry)
        earnings[symbol] = entry

    def attempt(symbol: str, action) -> bool:
        """Runs one symbol's work; a rate limit stops the run, any other
        problem for the symbol is logged by symbol and skipped.
        """
        try:
            action()
            return True
        except (edgar_client.EdgarRateLimited, finnhub_client.FinnhubRateLimited):
            raise
        except (
            edgar_client.EdgarApiError,
            finnhub_client.FinnhubApiError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            requests.RequestException,
        ) as e:
            logger.warning("screener: skipping %s: %s: %s", symbol, type(e).__name__, _redact(e))
            counts["failed"] += 1
            return False

    try:
        for symbol in sorted(set(symbols) - set(universe)):
            if attempt(symbol, lambda s=symbol: classify(s, edgar.lookup_cik(s, ciks))):
                counts["new"] += 1

        for symbol in sorted(s for s, e in universe.items() if e["stage"] == scoring.STAGE_NO_CIK and s in listed):
            cik = edgar.lookup_cik(symbol, ciks)
            if cik is not None and attempt(symbol, lambda s=symbol, c=cik: classify(s, c)):
                counts["no_cik_rechecked"] += 1

        date_attempts: set[str] = set()

        def fetch_missing_dates() -> None:
            """Dates for every candidate that has none or only old ones and
            was not tried yet this run, oldest first, so a run that stops
            at the cap resumes there."""
            def fetched_at(symbol: str) -> datetime:
                entry = earnings.get(symbol)
                return _parse_time(entry["fetched_at"]) if entry else datetime.min.replace(tzinfo=timezone.utc)

            for symbol in sorted((s for s in candidates if s in listed and s not in date_attempts and now - fetched_at(s) > EARNINGS_DATES_MAX_AGE), key=fetched_at):
                date_attempts.add(symbol)
                if attempt(symbol, lambda s=symbol: fetch_earnings(s)):
                    counts["dates_fetched"] += 1

        fetch_missing_dates()

        def last_refreshed(symbol: str) -> datetime:
            """A candidate is due by its own `market_at`, so a lost universe
            hash (which resets every `checked_at`) cannot hide stale ones.
            """
            stamped = (candidates.get(symbol) or {}).get("market_at")
            return _parse_time(stamped or universe[symbol]["checked_at"])

        def is_due(symbol: str) -> bool:
            """A candidate with a known last earnings date is due once the
            margin after it has passed and it has not been refreshed since;
            everything else is due 90 days after its last refresh."""
            last = (earnings.get(symbol) or {}).get("last") if symbol in candidates else None
            if last:
                trigger = _parse_time(last) + EARNINGS_MARGIN
                return now >= trigger and last_refreshed(symbol) < trigger
            return now - last_refreshed(symbol) > REFRESH_AFTER

        due = sorted(
            (s for s, e in universe.items() if e["stage"] == scoring.STAGE_TECH and s in listed and is_due(s)),
            key=last_refreshed,
        )
        for symbol in due:
            action = (lambda s=symbol: build_candidate(s, universe[s])) if symbol in candidates else (lambda s=symbol: check_market_cap(s, universe[s]))
            if attempt(symbol, action):
                counts["refreshed"] += 1

        for symbol in scoring.symbols_to_fetch(universe, candidates, band):
            if symbol in listed and attempt(symbol, lambda s=symbol: build_candidate(s, universe[s])):
                counts["new_candidates"] += 1

        fetch_missing_dates()
    except CallCapReached:
        counts["stopped"] = "call cap reached"
    except (edgar_client.EdgarRateLimited, finnhub_client.FinnhubRateLimited) as e:
        counts["stopped"] = "rate limited"
        logger.warning("screener: stopping, rate limited: %s", e)

    counts["finnhub_calls"] = budget.calls
    job_store.save_state(
        {
            "initial_pass_done": all(s in universe for s in symbols),
            "universe_total": len(symbols),
            "universe_checked": sum(1 for s in symbols if s in universe),
            "last_run_at": stamp,
            "last_run_counts": counts,
        }
    )
    logger.info("screener: run finished %s", counts)
    return counts


def _call_cap_from_environment() -> int:
    raw = os.environ.get("SCREENER_NIGHTLY_CALL_CAP")
    if raw is None or raw.strip() == "":
        return DEFAULT_NIGHTLY_CALL_CAP
    try:
        cap = int(raw)
    except ValueError:
        raise SystemExit(f"SCREENER_NIGHTLY_CALL_CAP must be a whole number, got {raw!r}")
    if cap < 1:
        raise SystemExit("SCREENER_NIGHTLY_CALL_CAP must be at least 1")
    return cap


def main() -> None:
    if not os.environ.get("SEC_CONTACT"):
        raise SystemExit("SEC_CONTACT is not set; the job will not call EDGAR without it")
    run_job(call_cap=_call_cap_from_environment())


if __name__ == "__main__":
    main()

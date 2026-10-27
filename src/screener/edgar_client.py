"""Thin client for the three SEC EDGAR endpoints the screener needs:
the ticker-to-CIK file, a company's submissions summary (name and SIC
code), and its XBRL company facts. EDGAR is free and keyless but asks
every caller to identify itself, so each request sends `SEC_CONTACT`
(a name and email) as the User-Agent, and the client refuses to call
EDGAR without it. Requests are spaced to at most 5 a second, half
EDGAR's stated limit, and a 429 or 403 raises `EdgarRateLimited`
instead of retrying: the caller stops and leaves the symbol for the
next run.
"""

import os
import threading
import time

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

MIN_REQUEST_INTERVAL = 0.2
_TIMEOUT = 30

_session = requests.Session()
_pacing_lock = threading.Lock()
_last_request_at = 0.0


class EdgarApiError(Exception):
    """Raised for any EDGAR request or response problem."""


class EdgarRateLimited(EdgarApiError):
    """EDGAR answered 429 or 403; do not retry now."""


def _pace() -> None:
    global _last_request_at
    with _pacing_lock:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _get_json(url: str) -> dict | None:
    """`None` for a 404 (EDGAR has no such company or facts)."""
    contact = os.environ.get("SEC_CONTACT")
    if not contact:
        raise EdgarApiError("SEC_CONTACT not set")

    _pace()
    try:
        response = _session.get(url, headers={"User-Agent": contact}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise EdgarApiError(f"request failed for {url}: {e}") from e

    if response.status_code == 404:
        return None
    if response.status_code in (429, 403):
        raise EdgarRateLimited(f"EDGAR answered {response.status_code} for {url}")
    if response.status_code != 200:
        raise EdgarApiError(f"EDGAR answered {response.status_code} for {url}")
    try:
        return response.json()
    except ValueError as e:
        raise EdgarApiError(f"unexpected response for {url}: {e}") from e


def fetch_ticker_ciks() -> dict[str, int]:
    """Every ticker EDGAR knows, as EDGAR writes it, mapped to its CIK.
    Class shares use a hyphen here (`BRK-A`); use `lookup_cik` to find
    one from Finnhub's dot form (`BRK.A`).
    """
    listing = _get_json(TICKERS_URL)
    if listing is None:
        raise EdgarApiError("EDGAR ticker file not found")
    try:
        return {entry["ticker"]: int(entry["cik_str"]) for entry in listing.values()}
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise EdgarApiError(f"unexpected ticker file format: {e}") from e


def lookup_cik(symbol: str, ciks: dict[str, int]) -> int | None:
    """`symbol`'s CIK, trying it as written and then with dots turned
    into hyphens, or `None` if EDGAR has no such ticker.
    """
    if symbol in ciks:
        return ciks[symbol]
    return ciks.get(symbol.replace(".", "-"))


def fetch_submissions_summary(cik: int) -> dict | None:
    """{"name": str | None, "sic": int | None, "sic_description": str | None}
    from the company's submissions record, or `None` if EDGAR has none.
    """
    submissions = _get_json(SUBMISSIONS_URL.format(cik=cik))
    if submissions is None:
        return None
    try:
        sic = int(submissions.get("sic"))
    except (TypeError, ValueError):
        sic = None
    return {
        "name": submissions.get("name"),
        "sic": sic,
        "sic_description": submissions.get("sicDescription"),
    }


# Forms that carry a quarter's or year's results; amendments and 8-Ks do not.
REPORT_FORMS = ("10-Q", "10-K", "10-KT", "20-F", "40-F")


def fetch_latest_report_date(cik: int) -> str | None:
    """The filing date ("YYYY-MM-DD") of the company's latest 10-Q,
    10-K, 20-F or 40-F, or `None` if it has none (or EDGAR has no such
    company). A foreign filer's quarterly results come in 6-Ks that
    cannot be told apart from other 6-Ks, so only its annual report
    counts.
    """
    submissions = _get_json(SUBMISSIONS_URL.format(cik=cik))
    if submissions is None:
        return None
    try:
        recent = submissions["filings"]["recent"]
        dates = [date for form, date in zip(recent["form"], recent["filingDate"]) if form in REPORT_FORMS]
    except (KeyError, TypeError) as e:
        raise EdgarApiError(f"unexpected submissions format for CIK {cik}: {e}") from e
    return max(dates) if dates else None


def fetch_company_facts(cik: int) -> dict | None:
    """The company's full XBRL facts (a large document, hundreds of KB),
    or `None` if EDGAR has none.
    """
    return _get_json(COMPANY_FACTS_URL.format(cik=cik))

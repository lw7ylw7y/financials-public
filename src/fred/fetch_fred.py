"""Thin client for the FRED series/observations and release/dates endpoints."""

import os
import re
from datetime import date

import requests

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


class FredApiError(Exception):
    """Raised for any FRED request/response problem for a single series."""


def _redact(error: Exception) -> str:
    """`error` as text with the API key removed: a `requests` error message
    includes the full request URL, whose query string carries the key, and
    these messages end up in logs.
    """
    return re.sub(r"api_key=[^&\s'\")]+", "api_key=REDACTED", str(error))


def _json_body(response, what: str) -> dict:
    """The response's JSON object. FRED answers a maintenance window with
    an HTML page and status 200, so a body that is not JSON must surface as
    a `FredApiError` (which every caller already handles per series), not
    as a `ValueError` that ends the whole run."""
    try:
        body = response.json()
    except ValueError as e:
        raise FredApiError(f"FRED returned a non-JSON response for {what}") from e
    if not isinstance(body, dict):
        raise FredApiError(f"FRED returned an unexpected response for {what}")
    return body


def fetch_recent_observations(
    series_id: str,
    limit: int = 12,
    api_key: str | None = None,
    start_date: str | None = None,
) -> list[dict]:
    """Fetch the most recent `limit` observations for a FRED series, or,
    if `start_date` (ISO "YYYY-MM-DD") is given, every observation from
    that date on regardless of `limit` -- a fixed time span holds the
    same number of readings for a daily, weekly or monthly series only
    if the count is left to the series' own frequency.

    Returns a list of {"date": "YYYY-MM-DD", "value": float}, oldest to
    newest (matching how history is stored). Observations with no value
    yet (FRED uses "." for those) are skipped, so the result may have
    fewer than `limit` entries. Raises FredApiError on a missing key or
    request failure.
    """
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        raise FredApiError("FRED_API_KEY not set")

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
    }
    if start_date:
        params["observation_start"] = start_date
    else:
        params["limit"] = limit
    try:
        response = requests.get(
            f"{FRED_BASE_URL}/series/observations", params=params, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FredApiError(f"request failed for series {series_id}: {_redact(e)}") from e

    observations = _json_body(response, f"series {series_id}").get("observations") or []
    result = []
    for obs in observations:
        raw_value = obs.get("value")
        if raw_value is None or raw_value == ".":
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        result.append({"date": obs["date"], "value": value})

    result.reverse()  # API returns newest-first; history is stored oldest-first
    return result


def fetch_next_release_date(
    release_id: str, api_key: str | None = None, today: str | None = None
) -> str | None:
    """Fetch the next scheduled date for a FRED release.

    Returns the earliest release date on or after `today` (ISO
    "YYYY-MM-DD", defaults to the current date), or None if the release
    has no such date. The endpoint returns dates spanning the release's
    full history rather than just upcoming ones, so "next" is picked out
    by filtering client-side rather than trusting API ordering.
    """
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        raise FredApiError("FRED_API_KEY not set")
    today = today or date.today().isoformat()

    params = {
        "release_id": release_id,
        "api_key": api_key,
        "file_type": "json",
        "include_release_dates_with_no_data": "true",
    }
    try:
        response = requests.get(
            f"{FRED_BASE_URL}/release/dates", params=params, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise FredApiError(f"request failed for release {release_id}: {_redact(e)}") from e

    release_dates = _json_body(response, f"release {release_id}").get("release_dates") or []
    upcoming = [
        entry["date"] for entry in release_dates if entry.get("date", "") >= today
    ]
    return min(upcoming) if upcoming else None

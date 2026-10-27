"""Orchestrator — ingest FRED data, refresh the release calendar, keep
the AI response fresh, and send the one digest email.

Fetches the latest values for each configured indicator, tags them with
its category, skips values already seen (no duplicate processing),
absorbs any revision FRED has made to a stored reading, and never
lets one indicator's failure stop the others. Also refreshes each
indicator's next scheduled release date, before building the digest, so
its countdown reflects the latest calendar data. Ingestion and the
calendar refresh run every scheduled check (every 6 hours); the AI
response is refreshed on that same cadence, whenever this run found new
data (`post_release.refresh_ai_response_if_updated`) — decoupled from
the digest email, which stays throttled separately
(`post_release.maybe_send_digest_email`) to a weekly rollup (sent only
when the digest's actual content has meaningfully changed since the
last send AND at least a week has passed), since several indicators
update daily and would otherwise trigger near-constant emails.
Persistence and querying live in storage.py, Redis-backed on a hosted
deployment.
"""

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))

from fetch_fred import FredApiError, fetch_next_release_date, fetch_recent_observations
from indicators_config import INDICATORS
from build_digest_content import build_indicators_context
from market_read import compute_market_read
from post_release import maybe_send_digest_email, refresh_ai_response_if_updated
from reads_history import make_entry, month_of, save_month, save_recessions
from storage import load_state, save_state, trim_history
from kv_store import KvStoreError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# How many of a series' most recent observations each run fetches. The
# newest may be a new reading; the rest are checked against stored
# history for revisions (FRED re-publishes payrolls, industrial
# production, permits and others for several months after release). A
# monthly series' 12 cover the whole stored 12-month window.
REVISION_LOOKBACK = 12
# How many of the NBER recession flag's latest months each run refreshes: the NBER dates a
# turning point months after the fact, so recent flags can change.
RECESSION_LOOKBACK = 24


def _fetch_observations(
    item: tuple[str, dict], fetch_fn
) -> tuple[str, list[dict] | None, Exception | None]:
    key, config = item
    try:
        observations = fetch_fn(config["fred_series_id"], limit=REVISION_LOOKBACK)
        if not observations:
            raise FredApiError(f"no observations for series {config['fred_series_id']}")
        return key, observations, None
    except FredApiError as e:
        return key, None, e


def _absorb_revisions(history: list[dict], observations: list[dict], now: str, key: str = "") -> int:
    """Update, in place, any stored reading whose date appears in
    `observations` with a different value. The reading keeps its
    `fetched_at`; the earlier value is kept as `previous_value` and the
    time as `revised_at`. Dates not already stored are not added (only
    the newest observation is appended, by the caller). Returns how many
    readings changed. `key` only labels the log line.
    """
    by_date = {entry["date"]: entry for entry in history}
    revised = 0
    for observation in observations:
        entry = by_date.get(observation["date"])
        if entry is None or entry["value"] == observation["value"]:
            continue
        logger.info(
            "absorbed revision indicator=%s date=%s old=%s new=%s",
            key, observation["date"], entry["value"], observation["value"],
        )
        entry["previous_value"] = entry["value"]
        entry["value"] = observation["value"]
        entry["revised_at"] = now
        revised += 1
    return revised


def run_ingestion(state: dict, fetch_fn=fetch_recent_observations) -> dict:
    """Fetch the latest observations for every configured indicator.

    The fetches themselves run concurrently (one thread per indicator —
    only ten of them, well within FRED's rate limit) since they're
    independent I/O calls; everything after a fetch resolves (revision
    check, dedup check, history append) still runs single-threaded,
    sequentially, so `state` is never mutated from more than one thread
    at a time.

    `fetch_fn(series_id, limit=...)` returns observations oldest to
    newest. The newest is appended to history only if its date is
    strictly newer than the last stored one; earlier ones that match a
    stored date but carry a different value revise that stored reading
    (`_absorb_revisions`).

    Mutates `state` in place and returns a dict of indicator key ->
    result:
      {"status": "updated"|"revised"|"unchanged", "date", "value",
       "revised": int, "category", "name"}
      {"status": "error", "error": str}
    "updated" is a new reading; "revised" is no new reading but at least
    one stored value changed.
    """
    state.setdefault("indicators", {})
    results = {}

    with ThreadPoolExecutor(max_workers=len(INDICATORS)) as executor:
        fetched = list(
            executor.map(lambda item: _fetch_observations(item, fetch_fn), INDICATORS.items())
        )

    now = datetime.now(timezone.utc).isoformat()
    for key, observations, error in fetched:
        config = INDICATORS[key]
        if error is not None:
            logger.error("fetch failed indicator=%s error=%s", key, error)
            results[key] = {"status": "error", "error": str(error)}
            continue

        observation = observations[-1]
        stored = state["indicators"].get(key, {})
        history = stored.get("history", [])
        if history and stored.get("fred_series_id") not in (None, config["fred_series_id"]):
            # A different series' readings (e.g. a monthly average vs. a
            # daily rate) aren't comparable, so they don't carry over.
            logger.warning(
                "series changed indicator=%s old=%s new=%s; discarding old history",
                key, stored.get("fred_series_id"), config["fred_series_id"],
            )
            history = []
            stored = {**stored, "next_release_date": None}
        last_entry = history[-1] if history else None

        if last_entry is not None and observation["date"] < last_entry["date"]:
            # The response ends before what is already stored: a stale or
            # cached response, whose older values must not overwrite
            # newer ones.
            logger.warning(
                "ignoring stale response indicator=%s newest=%s stored=%s",
                key, observation["date"], last_entry["date"],
            )
            revised = 0
        else:
            revised = _absorb_revisions(history, observations, now, key)

        # "New" means a strictly newer date than what's already stored —
        # not just "different from the last entry". A same-or-older date
        # must never be appended: an out-of-order append would corrupt
        # the chronological record. Its value, if it differs, was
        # absorbed above as a revision.
        is_new = last_entry is None or observation["date"] > last_entry["date"]

        result = {
            "date": observation["date"],
            "value": observation["value"],
            "revised": revised,
            "category": config["category"],
            "name": config["name"],
        }
        if not is_new:
            results[key] = {**result, "status": "revised" if revised else "unchanged"}
            continue

        new_entry = {
            "date": observation["date"],
            "value": observation["value"],
            "fetched_at": now,
        }
        state["indicators"][key] = {
            "name": config["name"],
            "category": config["category"],
            "fred_series_id": config["fred_series_id"],
            "fred_release_id": config.get("fred_release_id"),
            "history": trim_history(history + [new_entry]),
            "next_release_date": stored.get("next_release_date"),
        }
        results[key] = {**result, "status": "updated"}

    return results


def update_release_calendar(state: dict, fetch_fn=fetch_next_release_date) -> dict:
    """Refresh next_release_date for every indicator with a fred_release_id.

    Indicators with no fred_release_id (e.g. the yield curve spread,
    which updates continuously, or Fed Funds Rate, whose mapped release
    bundles many series at a cadence unrelated to its own) have no
    meaningful countdown and are excluded from it. Any stale
    next_release_date left over from a previous config is cleared here
    too, so removing an indicator's release_id actually takes effect
    rather than leaving old data behind. Overwrites next_release_date in
    place rather than appending, since it's a single current value, not
    a history.
    """
    state.setdefault("indicators", {})
    results = {}

    to_fetch = []
    for key, config in INDICATORS.items():
        release_id = config.get("fred_release_id")
        if release_id is None:
            indicator = state["indicators"].get(key)
            if indicator is not None:
                indicator["next_release_date"] = None
            continue
        to_fetch.append((key, release_id))

    def _fetch(item):
        key, release_id = item
        try:
            return key, release_id, fetch_fn(release_id), None
        except FredApiError as e:
            return key, release_id, None, e

    # Same reasoning as run_ingestion: only the fetches (independent
    # I/O) run concurrently, one thread per indicator with a
    # release_id — the state mutation below stays single-threaded.
    with ThreadPoolExecutor(max_workers=max(len(to_fetch), 1)) as executor:
        fetched = list(executor.map(_fetch, to_fetch))

    for key, release_id, next_date, error in fetched:
        config = INDICATORS[key]
        if error is not None:
            logger.error("release date fetch failed indicator=%s error=%s", key, error)
            results[key] = {"status": "error", "error": str(error)}
            continue

        indicator = state["indicators"].setdefault(
            key,
            {
                "name": config["name"],
                "category": config["category"],
                "fred_series_id": config["fred_series_id"],
                "fred_release_id": release_id,
                "history": [],
            },
        )
        indicator["next_release_date"] = next_date
        results[key] = {"status": "updated", "next_release_date": next_date}

    return results


def record_reads(state: dict, now: datetime | None = None, fetch_fn=fetch_recent_observations) -> dict:
    """Saves this month's group reads (replacing only this month's entry) and
    refreshes the recent recession flags. A failure here is logged and never
    fails the run: the history is a record for the chart, not core data.
    Returns {"reads": "saved"|"skipped"|"error", "recessions": "saved"|"error"}."""
    now = now or datetime.now(timezone.utc)
    result = {"reads": "skipped", "recessions": "error"}
    try:
        context = build_indicators_context(state)
        if context:
            market_read = compute_market_read(context)
            save_month(month_of(now), make_entry(market_read["groups"], market_read["policy"]["stance"], "live", now))
            result["reads"] = "saved"
    except Exception as e:  # noqa: BLE001 -- a record for the chart must never turn the check red
        logger.error("saving this month's reads failed: %s", type(e).__name__)
        result["reads"] = "error"
    try:
        flags = {o["date"][:7]: o["value"] for o in fetch_fn("USREC", limit=RECESSION_LOOKBACK)}
        save_recessions(flags)
        result["recessions"] = "saved"
    except Exception as e:  # noqa: BLE001 -- same
        logger.error("refreshing the recession flags failed: %s", type(e).__name__)
    return result


def main() -> dict:
    state = load_state()
    results = run_ingestion(state)
    calendar_results = update_release_calendar(state)

    updated_keys = [key for key, r in results.items() if r["status"] == "updated"]
    refresh_ai_response_if_updated(state, updated_keys)
    digest_result = maybe_send_digest_email(state)

    save_state(state)
    record_reads(state)

    updated = sum(1 for r in results.values() if r["status"] == "updated")
    revised = sum(r.get("revised", 0) for r in results.values())
    unchanged = sum(1 for r in results.values() if r["status"] in ("unchanged", "revised"))
    errors = sum(1 for r in results.values() if r["status"] == "error")
    logger.info(
        "ingestion complete: %d updated, %d unchanged, %d errors, %d stored values revised",
        updated,
        unchanged,
        errors,
        revised,
    )

    calendar_updated = sum(
        1 for r in calendar_results.values() if r["status"] == "updated"
    )
    calendar_errors = sum(
        1 for r in calendar_results.values() if r["status"] == "error"
    )
    logger.info(
        "release calendar refresh complete: %d updated, %d errors",
        calendar_updated,
        calendar_errors,
    )

    if digest_result["status"] == "skipped":
        logger.info("digest email: skipped (%s)", digest_result["reason"])
    else:
        logger.info("digest email: %s", digest_result["status"])
    return results


if __name__ == "__main__":
    main()

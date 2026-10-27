"""Redis storage for the screener's job-written data: the universe of
symbols the job has classified, the candidate records it has fetched
and each candidate's earnings dates. All three are hashes with one
field per symbol, so a write touches only its own symbol and never
reads or rewrites another. A Redis failure raises `KvStoreError` (core data, not a cache), so a caller
never mistakes a failed read for an empty store.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (os.path.join(os.path.dirname(_HERE), "web"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import kv_store  # noqa: E402
from scoring import STAGES  # noqa: E402

UNIVERSE_KEY = "screener_universe"
CANDIDATES_KEY = "screener_candidates"
EARNINGS_KEY = "screener_earnings"


def save_universe_entry(symbol: str, entry: dict) -> None:
    """`entry` is {"cik", "sic", "stage", "market_cap", "checked_at"}."""
    if entry.get("stage") not in STAGES:
        raise ValueError(f"unknown stage {entry.get('stage')!r} for {symbol}")
    kv_store.hset_json(UNIVERSE_KEY, symbol, entry)


def load_universe() -> dict[str, dict]:
    return kv_store.hgetall_json(UNIVERSE_KEY)


def save_candidate(symbol: str, record: dict) -> None:
    """`record` is what `scoring.build_candidate_record` returns."""
    kv_store.hset_json(CANDIDATES_KEY, symbol, record)


def load_candidates() -> dict[str, dict]:
    return kv_store.hgetall_json(CANDIDATES_KEY)


def load_candidate(symbol: str) -> dict | None:
    return kv_store.hget_json(CANDIDATES_KEY, symbol)


def save_earnings(symbol: str, entry: dict) -> None:
    """`entry` is {"next", "last", "fetched_at"}: the dates may be `None`."""
    kv_store.hset_json(EARNINGS_KEY, symbol, entry)


def load_earnings() -> dict[str, dict]:
    return kv_store.hgetall_json(EARNINGS_KEY)


STATE_KEY = "screener_state"


def load_state() -> dict:
    """The job's run record: {"initial_pass_done", "universe_total",
    "universe_checked", "last_run_at", "last_run_counts"}. Empty before
    the first run.
    """
    return kv_store.get_json(STATE_KEY) or {}


def save_state(state: dict) -> None:
    """Whole-blob replace; only the job writes it, one run at a time."""
    kv_store.set_json(STATE_KEY, state)

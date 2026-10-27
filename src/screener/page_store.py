"""Redis storage for the data the screener page owns, as opposed to the
job's candidates and universe (`store.py`): each shortlist or dismiss
decision, each note and the cached live quotes. The job never reads
or writes the first two. A Redis failure raises `KvStoreError`, so a
caller never mistakes a failed read for an empty store.
"""

import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (os.path.join(os.path.dirname(_HERE), "web"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import kv_store  # noqa: E402

STATUS_KEY = "screener_status"
NOTES_KEY = "screener_notes"
QUOTES_KEY = "screener_quotes"
MAX_NOTE_CHARS = 2000


def load_statuses() -> dict[str, dict]:
    """Symbol to {"status": "shortlisted" | "dismissed", "at",
    "checked_at" (optional), ...}; a symbol with no entry is New."""
    return kv_store.hgetall_json(STATUS_KEY)


def save_status(symbol: str, entry: dict) -> None:
    kv_store.hset_json(STATUS_KEY, symbol, entry)


def load_status(symbol: str) -> dict | None:
    """One symbol's status entry, or `None` if it is New."""
    return kv_store.hget_json(STATUS_KEY, symbol)


def mark_checked(symbol: str, when: date) -> bool:
    """Records `when` as the date the investor's review of `symbol` last
    looked at its figures, on its shortlisted or dismissed entry, and
    leaves the rest of the entry as it is. Returns False, writing
    nothing, when the symbol has no status. The periodic review calls
    this; nothing in the app does.
    """
    entry = load_status(symbol)
    if not entry:
        return False
    save_status(symbol, {**entry, "checked_at": when.isoformat()})
    return True


def clear_status(symbol: str) -> None:
    """Back to New."""
    kv_store.hdel_json(STATUS_KEY, symbol)


def save_note(symbol: str, entry: dict) -> None:
    kv_store.hset_json(NOTES_KEY, symbol, entry)


def clear_note(symbol: str) -> None:
    kv_store.hdel_json(NOTES_KEY, symbol)


def load_notes() -> dict[str, dict]:
    """Symbol to {"text", "at"}."""
    return kv_store.hgetall_json(NOTES_KEY)


def load_quotes(symbols: list[str]) -> dict[str, dict]:
    """Symbol to {"price", "change", "change_percent", "quoted_at"}
    for each of `symbols` that has one cached."""
    quotes = {}
    for symbol in symbols:
        quote = kv_store.hget_json(QUOTES_KEY, symbol)
        if quote:
            quotes[symbol] = quote
    return quotes


def save_quote(symbol: str, quote: dict) -> None:
    kv_store.hset_json(QUOTES_KEY, symbol, quote)

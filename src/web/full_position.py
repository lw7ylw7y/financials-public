"""The "Full Position" marks: symbols the investor has ticked to say the
position is as big as wanted, shown greyed out on the Ticker Dashboard and
the screener's Shortlisted tab. One hash, one field per symbol, so a click
is one atomic write and never touches another symbol. A mark is
non-critical display state: `load_marks` degrades to "no marks" on a Redis
failure and says so, while the writes raise `KvStoreError`.
"""

import logging
from datetime import datetime, timezone

import kv_store
from kv_store import KvStoreError

FULL_POSITION_KEY = "full_position"
UNREADABLE_NOTE = "Full-position marks couldn't be loaded."

logger = logging.getLogger(__name__)


def load_marks() -> tuple[frozenset[str], bool]:
    """(symbols marked, whether the read worked). On a failure the set is
    empty, the error class is logged and the flag is False."""
    try:
        return frozenset(kv_store.hgetall_json(FULL_POSITION_KEY)), True
    except KvStoreError as e:
        logger.error("full position marks unreadable: %s", type(e).__name__)
        return frozenset(), False


def set_mark(symbol: str, full: bool, now: datetime | None = None) -> None:
    if full:
        kv_store.hset_json(FULL_POSITION_KEY, symbol, {"at": (now or datetime.now(timezone.utc)).isoformat()})
    else:
        kv_store.hdel_json(FULL_POSITION_KEY, symbol)

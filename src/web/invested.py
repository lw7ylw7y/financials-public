"""The "Invested" amounts: the total dollars the investor has put into a
symbol, shown and edited on the Ticker Dashboard's `individual` table. One
hash, one field per symbol (`{amount, at}`), so a save is one atomic write.
The amount is private: it is never logged. It is display state read at
render time: `load_amounts` degrades to "none" on a Redis failure and says
so, while the writes raise `KvStoreError`.
"""

import logging
from datetime import datetime, timezone

import kv_store
from kv_store import KvStoreError

INVESTED_KEY = "invested"
UNREADABLE_NOTE = "Invested amounts couldn't be loaded."
MAX_AMOUNT = 1_000_000_000.0

logger = logging.getLogger(__name__)


def load_amounts() -> tuple[dict[str, float], bool]:
    """(symbol to amount, whether the read worked). On a failure the
    mapping is empty, the error class is logged and the flag is False. A
    stored value that is not a usable amount is left out."""
    try:
        stored = kv_store.hgetall_json(INVESTED_KEY)
    except KvStoreError as e:
        logger.error("invested amounts unreadable: %s", type(e).__name__)
        return {}, False
    amounts = {}
    for symbol, entry in stored.items():
        amount = entry.get("amount") if isinstance(entry, dict) else None
        if valid_amount(amount):
            amounts[symbol] = float(amount)
    return amounts, True


def valid_amount(value) -> bool:
    """A real number from 0 to `MAX_AMOUNT` (not a bool, not NaN). The range
    is checked first: `math.isfinite` raises on an integer too large for a
    float, and JSON can carry one."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= MAX_AMOUNT


def set_amount(symbol: str, amount: float | None, now: datetime | None = None) -> None:
    """Saves `amount` for `symbol`, or clears it when `amount` is `None`."""
    if amount is None:
        kv_store.hdel_json(INVESTED_KEY, symbol)
    else:
        kv_store.hset_json(INVESTED_KEY, symbol, {"amount": round(float(amount), 2), "at": (now or datetime.now(timezone.utc)).isoformat()})

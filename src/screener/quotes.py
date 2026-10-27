"""Live quotes for the screener page. A quote under `QUOTE_TTL` old is
reused from the `screener_quotes` cache without a Finnhub call, so
reloading the page never spends quota; the window lives here, not as a
Redis TTL, because an expired entry is the fallback when a fetch fails.
"""

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (os.path.join(os.path.dirname(_HERE), "web"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import finnhub_client  # noqa: E402
import page_store  # noqa: E402
from kv_store import KvStoreError  # noqa: E402

logger = logging.getLogger(__name__)

QUOTE_TTL = timedelta(minutes=5)
MAX_SYMBOLS = 25
# Sized like ticker_dashboard's per-group fetch pool.
QUOTE_WORKERS = 5
# After a 429, no request fetches for this long: the page sends several
# batches at once, and each would otherwise keep spending calls.
RATE_LIMIT_COOLDOWN_SECONDS = 60
_rate_limited_until = 0.0


def is_usable(quote: dict | None) -> bool:
    """A cached entry that has a price and a parseable time."""
    try:
        float(quote["price"])
        datetime.fromisoformat(quote["quoted_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return True


def is_fresh(quote: dict, now: datetime) -> bool:
    return now - datetime.fromisoformat(quote["quoted_at"]) < QUOTE_TTL


def get_quotes(
    symbols: list[str],
    now: datetime | None = None,
    fetch_quote=finnhub_client.fetch_quote,
) -> dict[str, dict | None]:
    """Symbol to its quote, for each of `symbols` (at most `MAX_SYMBOLS`):
    the cached one if fresh, else a new Finnhub quote, written back one
    atomic field at a time. A failed fetch returns the older cached quote,
    or None if there is none. A 429 stops further fetches in this call and
    is never retried, and also pauses fetching for `RATE_LIMIT_COOLDOWN_SECONDS` in later calls. Cache reads propagate `KvStoreError`; a failed cache
    write is logged and the fetched quote is still returned.
    """
    now = now or datetime.now(timezone.utc)
    cached = {s: q for s, q in page_store.load_quotes(symbols).items() if is_usable(q)}
    result = {s: cached.get(s) for s in symbols}
    due = [s for s in symbols if s not in cached or not is_fresh(cached[s], now)]

    def fetch(symbol: str) -> None:
        global _rate_limited_until
        if time.monotonic() < _rate_limited_until:
            return
        try:
            quote = fetch_quote(symbol)
        except finnhub_client.FinnhubRateLimited:
            _rate_limited_until = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
            logger.warning("Finnhub rate limit reached; no more quotes this request")
            return
        except finnhub_client.FinnhubApiError as e:
            logger.warning("quote failed for %s: %s", symbol, e)
            return
        quote["quoted_at"] = now.isoformat()
        result[symbol] = quote
        try:
            page_store.save_quote(symbol, quote)
        except KvStoreError as e:  # a cache write must not lose a good quote
            logger.warning("quote cache write failed for %s: %s", symbol, e)

    with ThreadPoolExecutor(max_workers=QUOTE_WORKERS) as pool:
        list(pool.map(fetch, due))
    return result

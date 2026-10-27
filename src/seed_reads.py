"""One-time seed of the saved monthly reads -- replays every month since
1978 with the production code (`backtest.replay`) and writes the months
that have no entry yet, with `source` "replay", plus the NBER recession
flags. Run by hand (`python3 src/seed_reads.py`); it writes production
Redis. Safe to repeat: it reads the stored months first and writes only
missing ones, so it never replaces a live entry (a live write landing
between its read and its write is the one case it cannot see, and a
live entry written later replaces a replay month anyway).

A FRED or Redis failure stops it before anything is written (FRED) or
leaves the months written so far in place (Redis); running it again
finishes the job.
"""

import logging
import os
import sys
from datetime import datetime, timezone

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SRC_DIR)
for _subdir in ("fred", "storage", "digest", "mailer", "web"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))

import backtest
import reads_history
from fetch_fred import FredApiError
from kv_store import KvStoreError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def seed(replay_fn=backtest.replay, load_fn=reads_history.load_reads, save_missing_fn=reads_history.save_missing,
         save_recessions_fn=reads_history.save_recessions, now: datetime | None = None) -> dict:
    """Writes the missing months and the recession flags; returns
    {"written": months written, "recession_months": flags written}. Raises
    `FredApiError` (nothing written) if the replay cannot get its data."""
    now = now or datetime.now(timezone.utc)
    records, recession, _ = replay_fn()
    entries = {
        r["month"]: reads_history.make_entry(r["group_results"], r["stance"], "replay", now)
        for r in records
    }
    written = save_missing_fn(entries, set(load_fn()))
    save_recessions_fn(recession)
    return {"written": written, "recession_months": len(recession)}


def main() -> int:
    try:
        result = seed()
    except FredApiError as e:
        logger.error("seed stopped, nothing written: %s", e)
        return 1
    except KvStoreError as e:
        logger.error("seed stopped on a storage error (run it again to finish): %s", e)
        return 1
    logger.info("wrote %d replay months and %d recession flags", result["written"], result["recession_months"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

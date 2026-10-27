import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "storage"), os.path.join(_SRC, "web"), os.path.join(_SRC, "fred"), os.path.join(_SRC, "digest")):
    sys.path.insert(0, _p)

import seed_reads
from fetch_fred import FredApiError
from kv_store import KvStoreError

NOW = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
RESULTS = {g: {"read": "mixed", "score": 0.1, "scored": 3, "total": 3} for g in ("leading", "coincident", "lagging")}


def replay_of(months):
    records = [{"month": m, "group_results": RESULTS, "stance": "near neutral"} for m in months]
    return lambda: (records, {m: 0 for m in months}, {})


class TestSeed(unittest.TestCase):
    def run_seed(self, months, existing, **kwargs):
        written, flags = [], []
        result = seed_reads.seed(
            replay_fn=kwargs.get("replay_fn", replay_of(months)),
            load_fn=lambda: {m: {} for m in existing},
            save_missing_fn=lambda entries, have: written.append((entries, have)) or len([m for m in entries if m not in have]),
            save_recessions_fn=flags.append,
            now=NOW,
        )
        return result, written, flags

    def test_it_fills_only_missing_months_marked_as_replay(self):
        result, written, flags = self.run_seed(["2000-01", "2000-02", "2000-03"], ["2000-02"])

        entries, have = written[0]
        self.assertEqual(have, {"2000-02"})
        self.assertEqual(result["written"], 2)
        self.assertTrue(all(e["source"] == "replay" for e in entries.values()))
        self.assertEqual(entries["2000-01"]["groups"]["leading"]["score"], 0.1)
        self.assertEqual(flags[0], {"2000-01": 0, "2000-02": 0, "2000-03": 0})

    def test_a_second_run_writes_nothing(self):
        result, _, _ = self.run_seed(["2000-01", "2000-02"], ["2000-01", "2000-02"])

        self.assertEqual(result["written"], 0)

    def test_it_never_replaces_a_live_entry(self):
        with mock.patch("reads_history.hset_many_json") as many, \
             mock.patch("reads_history.hgetall_json", return_value={"2000-02": {"source": "live"}}):
            seed_reads.seed(replay_fn=replay_of(["2000-01", "2000-02"]), save_recessions_fn=lambda f: None, now=NOW)

        self.assertEqual(sorted(many.call_args.args[1]), ["2000-01"])

    def test_a_fred_failure_writes_nothing_and_exits_nonzero(self):
        def failing():
            raise FredApiError("maintenance")

        with mock.patch("reads_history.hset_many_json") as many, mock.patch("seed_reads.seed", side_effect=FredApiError("maintenance")):
            self.assertEqual(seed_reads.main(), 1)
        with mock.patch("reads_history.hset_many_json") as many, mock.patch("reads_history.hgetall_json", return_value={}):
            with self.assertRaises(FredApiError):
                seed_reads.seed(replay_fn=failing, now=NOW)
            many.assert_not_called()

    def test_a_storage_failure_exits_nonzero(self):
        with mock.patch("seed_reads.seed", side_effect=KvStoreError("down")):
            self.assertEqual(seed_reads.main(), 1)


class TestReplayMatchesProduction(unittest.TestCase):
    def test_the_replay_matches_compute_market_read(self):
        from datetime import date

        import backtest
        import market_read
        from indicators_config import INDICATORS

        def monthly(i0):
            return [{"date": f"{2019 + i // 12}-{i % 12 + 1:02d}-01", "value": 100.0 + i * (1 + i0 % 3) + (i % 4)} for i in range(36)]

        series = {key: backtest.Series(monthly(n)) for n, key in enumerate(INDICATORS)}
        as_of = date(2021, 11, 30)
        context = backtest.build_context(series, as_of)

        record = backtest.run({as_of: context}, {})[0]
        direct = market_read.compute_market_read(context, as_of)

        self.assertEqual(record["group_results"], direct["groups"])
        self.assertEqual(record["stance"], direct["policy"]["stance"])


if __name__ == "__main__":
    unittest.main()

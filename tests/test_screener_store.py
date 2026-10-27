import os
import sys
import unittest
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import store
from kv_store import KvStoreError


class TestUniverse(unittest.TestCase):
    @patch("store.kv_store.hset_json")
    def test_saves_one_field_per_symbol(self, mock_hset):
        entry = {"cik": 1, "sic": 3674, "stage": "tech", "market_cap": 120.0, "checked_at": "2026-10-19T05:30:00+00:00"}

        store.save_universe_entry("GCTS", entry)

        mock_hset.assert_called_once_with("screener_universe", "GCTS", entry)

    @patch("store.kv_store.hset_json")
    def test_rejects_an_unknown_stage_without_writing(self, mock_hset):
        with self.assertRaises(ValueError):
            store.save_universe_entry("GCTS", {"stage": "out_of_band"})

        mock_hset.assert_not_called()

    @patch("store.kv_store.hset_json")
    def test_every_stage_is_accepted(self, mock_hset):
        for stage in ("non_tech", "no_cik", "tech"):
            store.save_universe_entry("X", {"stage": stage})

        self.assertEqual(mock_hset.call_count, 3)

    @patch("store.kv_store.hgetall_json", return_value={"GCTS": {"stage": "tech"}})
    def test_loads_the_whole_universe(self, mock_hgetall):
        self.assertEqual(store.load_universe(), {"GCTS": {"stage": "tech"}})
        mock_hgetall.assert_called_once_with("screener_universe")

    @patch("store.kv_store.hgetall_json", side_effect=KvStoreError("down"))
    def test_a_redis_failure_propagates_instead_of_looking_empty(self, _hgetall):
        with self.assertRaises(KvStoreError):
            store.load_universe()


class TestCandidates(unittest.TestCase):
    @patch("store.kv_store.hset_json")
    def test_saves_one_field_per_symbol_touching_nothing_else(self, mock_hset):
        store.save_candidate("DSP", {"name": "Viant"})

        mock_hset.assert_called_once_with("screener_candidates", "DSP", {"name": "Viant"})

    @patch("store.kv_store.hgetall_json", return_value={"DSP": {"name": "Viant"}})
    def test_loads_all_candidates(self, mock_hgetall):
        self.assertEqual(store.load_candidates(), {"DSP": {"name": "Viant"}})
        mock_hgetall.assert_called_once_with("screener_candidates")

    @patch("store.kv_store.hset_json", side_effect=KvStoreError("down"))
    def test_a_write_failure_propagates(self, _hset):
        with self.assertRaises(KvStoreError):
            store.save_candidate("DSP", {})


class TestEarnings(unittest.TestCase):
    @patch("store.kv_store.hset_json")
    def test_saves_one_field_per_symbol(self, mock_hset):
        entry = {"next": "2026-11-05", "last": "2026-08-05", "fetched_at": "2026-10-20T05:30:00+00:00"}

        store.save_earnings("DSP", entry)

        mock_hset.assert_called_once_with("screener_earnings", "DSP", entry)

    @patch("store.kv_store.hgetall_json", return_value={"DSP": {"next": None, "last": None}})
    def test_loads_every_symbols_dates(self, mock_hgetall):
        self.assertEqual(store.load_earnings(), {"DSP": {"next": None, "last": None}})
        mock_hgetall.assert_called_once_with("screener_earnings")

    @patch("store.kv_store.hgetall_json", side_effect=KvStoreError("down"))
    def test_a_redis_failure_propagates(self, _hgetall):
        with self.assertRaises(KvStoreError):
            store.load_earnings()


class TestState(unittest.TestCase):
    @patch("store.kv_store.get_json", return_value=None)
    def test_state_is_empty_before_the_first_run(self, mock_get):
        self.assertEqual(store.load_state(), {})
        mock_get.assert_called_once_with("screener_state")

    @patch("store.kv_store.get_json", return_value={"last_run_at": "2026-10-20T05:30:00+00:00"})
    def test_loads_the_saved_state(self, _get):
        self.assertEqual(store.load_state(), {"last_run_at": "2026-10-20T05:30:00+00:00"})

    @patch("store.kv_store.set_json")
    def test_saves_the_state_as_one_blob(self, mock_set):
        store.save_state({"initial_pass_done": True})

        mock_set.assert_called_once_with("screener_state", {"initial_pass_done": True})

    @patch("store.kv_store.get_json", side_effect=KvStoreError("down"))
    def test_a_redis_failure_propagates(self, _get):
        with self.assertRaises(KvStoreError):
            store.load_state()


if __name__ == "__main__":
    unittest.main()

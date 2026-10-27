import glob
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.join(_SRC, "web"))

import invested
from kv_store import KvStoreError


class TestLoadAmounts(unittest.TestCase):
    @patch("invested.kv_store.hgetall_json", return_value={"AAPL": {"amount": 1500.5, "at": "x"}, "MSFT": {"amount": 0, "at": "y"}})
    def test_returns_each_symbols_amount_from_the_one_hash(self, mock_hgetall):
        self.assertEqual(invested.load_amounts(), ({"AAPL": 1500.5, "MSFT": 0.0}, True))
        mock_hgetall.assert_called_once_with("invested")

    @patch("invested.kv_store.hgetall_json", return_value={"G": {"amount": 10**400}})
    def test_a_stored_integer_too_large_for_a_float_is_left_out_not_a_crash(self, _hgetall):
        self.assertEqual(invested.load_amounts(), ({}, True))

    @patch("invested.kv_store.hgetall_json", return_value={"A": {"amount": "lots"}, "B": {"amount": -5}, "C": "x", "D": {"amount": True},
                                                          "E": {"amount": float("inf")}, "F": {}})
    def test_unusable_stored_values_are_left_out(self, _hgetall):
        self.assertEqual(invested.load_amounts(), ({}, True))

    @patch("invested.kv_store.hgetall_json", side_effect=KvStoreError("secret detail"))
    def test_a_redis_failure_degrades_and_logs_only_the_error_class(self, _hgetall):
        with self.assertLogs("invested", level="ERROR") as logs:
            result = invested.load_amounts()

        self.assertEqual(result, ({}, False))
        self.assertIn("KvStoreError", logs.output[0])
        self.assertNotIn("secret detail", logs.output[0])


class TestValidAmount(unittest.TestCase):
    def test_accepts_zero_whole_and_fractional_amounts_up_to_the_limit(self):
        for value in (0, 1, 250.75, invested.MAX_AMOUNT):
            self.assertTrue(invested.valid_amount(value), value)

    def test_rejects_negative_huge_non_finite_boolean_and_non_numbers(self):
        for value in (-0.01, invested.MAX_AMOUNT + 1, float("nan"), float("inf"), True, False, "100", None, [1], 10**400, -(10**400)):
            self.assertFalse(invested.valid_amount(value), value)


class TestSetAmount(unittest.TestCase):
    @patch("invested.kv_store.hdel_json")
    @patch("invested.kv_store.hset_json")
    def test_saving_is_one_field_write_rounded_to_cents_and_clearing_one_field_delete(self, mock_hset, mock_hdel):
        now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

        invested.set_amount("AAPL", 1234.567, now)
        mock_hset.assert_called_once_with("invested", "AAPL", {"amount": 1234.57, "at": now.isoformat()})
        mock_hdel.assert_not_called()

        invested.set_amount("AAPL", None)
        mock_hdel.assert_called_once_with("invested", "AAPL")
        self.assertEqual(mock_hset.call_count, 1)

    @patch("invested.kv_store.hset_json", side_effect=KvStoreError("down"))
    def test_a_failed_write_raises(self, _hset):
        with self.assertRaises(KvStoreError):
            invested.set_amount("AAPL", 10)


class TestIsolation(unittest.TestCase):
    def test_no_job_digest_storage_or_screener_module_mentions_the_amounts(self):
        paths = []
        for pattern in ("screener/*.py", "digest/*.py", "storage/*.py", "mailer/*.py", "fred/*.py", "main.py", "backfill.py"):
            paths += glob.glob(os.path.join(_SRC, pattern))
        paths.append(os.path.join(_SRC, "web", "screener_page.py"))
        for path in paths:
            with open(path) as f:
                source = f.read()
                self.assertNotIn("import invested", source, path)
                self.assertNotIn('"invested"', source, path)


if __name__ == "__main__":
    unittest.main()

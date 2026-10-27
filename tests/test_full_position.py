import glob
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.join(_SRC, "web"))

import full_position
from kv_store import KvStoreError


class TestLoadMarks(unittest.TestCase):
    @patch("full_position.kv_store.hgetall_json", return_value={"SPY": {"at": "x"}, "AAPL": {"at": "y"}})
    def test_returns_the_marked_symbols_and_reads_the_one_hash(self, mock_hgetall):
        marks, known = full_position.load_marks()

        self.assertEqual((marks, known), (frozenset({"SPY", "AAPL"}), True))
        mock_hgetall.assert_called_once_with("full_position")

    @patch("full_position.kv_store.hgetall_json", return_value={})
    def test_an_empty_hash_is_known_and_empty(self, _hgetall):
        self.assertEqual(full_position.load_marks(), (frozenset(), True))

    @patch("full_position.kv_store.hgetall_json", side_effect=KvStoreError("secret detail"))
    def test_a_redis_failure_degrades_to_no_marks_and_logs_only_the_error_class(self, _hgetall):
        with self.assertLogs("full_position", level="ERROR") as logs:
            result = full_position.load_marks()

        self.assertEqual(result, (frozenset(), False))
        self.assertIn("KvStoreError", logs.output[0])
        self.assertNotIn("secret detail", logs.output[0])


class TestSetMark(unittest.TestCase):
    @patch("full_position.kv_store.hdel_json")
    @patch("full_position.kv_store.hset_json")
    def test_ticking_is_one_field_write_and_unticking_one_field_delete(self, mock_hset, mock_hdel):
        now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

        full_position.set_mark("AAPL", True, now)
        mock_hset.assert_called_once_with("full_position", "AAPL", {"at": now.isoformat()})
        mock_hdel.assert_not_called()

        full_position.set_mark("AAPL", False)
        mock_hdel.assert_called_once_with("full_position", "AAPL")
        self.assertEqual(mock_hset.call_count, 1)

    @patch("full_position.kv_store.hset_json", side_effect=KvStoreError("down"))
    def test_a_failed_write_raises(self, _hset):
        with self.assertRaises(KvStoreError):
            full_position.set_mark("AAPL", True)


class TestIsolation(unittest.TestCase):
    def test_no_job_or_digest_module_reads_or_writes_the_marks(self):
        paths = []
        for pattern in ("screener/*.py", "digest/*.py", "storage/*.py", "mailer/*.py", "fred/*.py", "main.py", "backfill.py"):
            paths += glob.glob(os.path.join(_SRC, pattern))
        self.assertTrue(paths)
        for path in paths:
            with open(path) as f:
                self.assertNotIn("full_position", f.read(), path)


if __name__ == "__main__":
    unittest.main()

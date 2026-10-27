import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import page_store
import scoring
from kv_store import KvStoreError


class TestStatusesAndNotes(unittest.TestCase):
    @patch("page_store.kv_store.hgetall_json", return_value={"AAA": {"status": "dismissed"}})
    def test_loads_every_status(self, mock_hgetall):
        self.assertEqual(page_store.load_statuses(), {"AAA": {"status": "dismissed"}})
        mock_hgetall.assert_called_once_with("screener_status")

    @patch("page_store.kv_store.hgetall_json", return_value={"AAA": {"text": "t"}})
    def test_loads_every_note(self, mock_hgetall):
        self.assertEqual(page_store.load_notes(), {"AAA": {"text": "t"}})
        mock_hgetall.assert_called_once_with("screener_notes")

    @patch("page_store.kv_store.hgetall_json", side_effect=KvStoreError("down"))
    def test_a_redis_failure_propagates_for_each_read(self, _hgetall):
        for load in (page_store.load_statuses, page_store.load_notes):
            with self.subTest(load=load.__name__):
                with self.assertRaises(KvStoreError):
                    load()


class TestWrites(unittest.TestCase):
    @patch("page_store.kv_store.hset_json")
    def test_a_status_and_a_note_are_one_atomic_field_each(self, mock_hset):
        page_store.save_status("AAA", {"status": "shortlisted"})
        page_store.save_note("AAA", {"text": "t"})

        self.assertEqual([c.args[:2] for c in mock_hset.call_args_list],
                         [("screener_status", "AAA"), ("screener_notes", "AAA")])

    @patch("page_store.kv_store.hdel_json")
    def test_clearing_deletes_only_that_symbols_field(self, mock_hdel):
        page_store.clear_status("AAA")
        page_store.clear_note("AAA")

        self.assertEqual([c.args for c in mock_hdel.call_args_list],
                         [("screener_status", "AAA"), ("screener_notes", "AAA")])


class TestMarkChecked(unittest.TestCase):
    @patch("page_store.kv_store.hset_json")
    @patch("page_store.kv_store.hget_json", return_value={"status": "dismissed", "at": "2026-09-01T10:00:00+00:00",
                                                          "score_at_dismissal": 61.5, "passed_at_dismissal": True})
    def test_records_the_date_and_keeps_the_rest_of_the_entry(self, _hget, mock_hset):
        self.assertTrue(page_store.mark_checked("AAA", date(2026, 10, 20)))

        field, entry = mock_hset.call_args.args[1:]
        self.assertEqual(field, "AAA")
        self.assertEqual(entry["checked_at"], "2026-10-20")
        self.assertEqual((entry["status"], entry["score_at_dismissal"], entry["passed_at_dismissal"]), ("dismissed", 61.5, True))

    @patch("page_store.kv_store.hset_json")
    @patch("page_store.kv_store.hget_json", return_value=None)
    def test_a_symbol_with_no_status_is_left_alone(self, _hget, mock_hset):
        self.assertFalse(page_store.mark_checked("AAA", date(2026, 10, 20)))

        mock_hset.assert_not_called()

    @patch("page_store.kv_store.hget_json", side_effect=KvStoreError("down"))
    def test_a_failed_read_raises_instead_of_writing(self, _hget):
        with self.assertRaises(KvStoreError):
            page_store.mark_checked("AAA", date(2026, 10, 20))


class TestQuotes(unittest.TestCase):
    @patch("page_store.kv_store.hget_json", side_effect=lambda key, symbol: {"AAA": {"price": 1.0}}.get(symbol))
    def test_loads_only_the_symbols_that_have_a_cached_quote(self, _hget):
        self.assertEqual(page_store.load_quotes(["AAA", "BBB"]), {"AAA": {"price": 1.0}})

    @patch("page_store.kv_store.hset_json")
    def test_saves_one_field_per_symbol(self, mock_hset):
        page_store.save_quote("AAA", {"price": 1.0})

        mock_hset.assert_called_once_with("screener_quotes", "AAA", {"price": 1.0})


if __name__ == "__main__":
    unittest.main()

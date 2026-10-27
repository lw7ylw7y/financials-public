import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "fred"), os.path.join(_SRC, "storage"), os.path.join(_SRC, "digest"),
           os.path.join(_SRC, "mailer"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import main
from fetch_fred import FredApiError
from kv_store import KvStoreError

NOW = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)


def state():
    return {"indicators": {"initial_jobless_claims": {
        "name": "Initial Jobless Claims", "category": "leading", "next_release_date": None,
        "history": [{"date": f"2026-0{m}-01", "value": 220000.0 - 1000 * m, "fetched_at": "2026-09-01T00:00:00+00:00"} for m in range(1, 9)]}}}


def fetch(series_id, limit=12):
    return [{"date": "2026-08-01", "value": 0.0}, {"date": "2026-09-01", "value": 0.0}]


class TestRecordReads(unittest.TestCase):
    def test_this_months_reads_are_saved_as_a_live_entry_and_the_flags_refreshed(self):
        with mock.patch("main.save_month") as save, mock.patch("main.save_recessions") as flags:
            result = main.record_reads(state(), NOW, fetch)

        self.assertEqual(result, {"reads": "saved", "recessions": "saved"})
        month, entry = save.call_args.args
        self.assertEqual(month, "2026-10")
        self.assertEqual(entry["source"], "live")
        self.assertEqual(flags.call_args.args[0], {"2026-08": 0.0, "2026-09": 0.0})

    def test_a_save_failure_is_logged_and_does_not_stop_the_flags_or_the_run(self):
        with mock.patch("main.save_month", side_effect=KvStoreError("down")), mock.patch("main.save_recessions") as flags, \
             self.assertLogs("main", level="ERROR") as logs:
            result = main.record_reads(state(), NOW, fetch)

        self.assertEqual(result, {"reads": "error", "recessions": "saved"})
        flags.assert_called_once()
        self.assertNotIn("220000", "".join(logs.output))

    def test_a_fred_failure_keeps_the_stored_flags(self):
        def failing(series_id, limit=12):
            raise FredApiError("maintenance")

        with mock.patch("main.save_month"), mock.patch("main.save_recessions") as flags:
            result = main.record_reads(state(), NOW, failing)

        self.assertEqual(result, {"reads": "saved", "recessions": "error"})
        flags.assert_not_called()

    def test_an_unexpected_error_anywhere_still_does_not_fail_the_run(self):
        def odd(series_id, limit=12):
            return [{"unexpected": "shape"}]

        with mock.patch("main.compute_market_read", side_effect=TypeError("odd")), mock.patch("main.save_recessions"):
            result = main.record_reads(state(), NOW, odd)

        self.assertEqual(result, {"reads": "error", "recessions": "error"})

    def test_a_flag_write_failure_does_not_raise(self):
        with mock.patch("main.save_month"), mock.patch("main.save_recessions", side_effect=KvStoreError("down")):
            self.assertEqual(main.record_reads(state(), NOW, fetch)["recessions"], "error")

    def test_with_no_indicators_nothing_is_saved(self):
        with mock.patch("main.save_month") as save, mock.patch("main.save_recessions"):
            result = main.record_reads({"indicators": {}}, NOW, fetch)

        self.assertEqual(result["reads"], "skipped")
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()

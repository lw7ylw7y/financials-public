import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)
sys.path.insert(0, os.path.dirname(__file__))

import live_pull

NOW = datetime(2026, 9, 12, 18, 0, 0, tzinfo=timezone.utc)


def make_state(last_ai_response=None):
    state = {
        "indicators": {
            "cpi": {
                "name": "CPI",
                "category": "lagging",
                "history": [
                    {"date": "2026-08-01", "value": 334.131, "fetched_at": "2026-09-01T00:00:00+00:00"}
                ],
                "next_release_date": "2026-09-11",
            },
        }
    }
    if last_ai_response is not None:
        state["last_ai_response"] = last_ai_response
    return state


from readfixtures import NO_STANCE

NO_READS = {"leading": None, "coincident": None, "lagging": None}
# make_state() holds one lagging indicator: no group has enough history for a read.
ONE_LAGGING_GROUP = {
    "leading": {"read": None, "score": None, "scored": 0, "total": 0},
    "coincident": {"read": None, "score": None, "scored": 0, "total": 0},
    "lagging": {"read": None, "score": None, "scored": 0, "total": 1},
}


class TestGetInitialPageData(unittest.TestCase):
    def test_renders_from_stored_data_with_no_live_calls(self):
        stored_ai = {
            "summary": "Old read.",
            "computed_reads": NO_READS,
            "generated_at": "2026-09-05T00:00:00+00:00",
        }
        state = make_state(last_ai_response=stored_ai)

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion"
        ) as mock_ingest:
            data = live_pull.get_initial_page_data()

        mock_ingest.assert_not_called()
        self.assertEqual(data["values_status"], "saved")
        self.assertEqual(data["values_timestamp"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(data["ai_status"], "saved")
        self.assertEqual(
            data["ai_result"],
            {"groups": ONE_LAGGING_GROUP, "relationship": None, "policy": NO_STANCE, "summary": "Old read."},
        )

    def test_no_ai_response_on_file_reports_none(self):
        state = make_state()

        with patch("live_pull.load_state", return_value=state):
            data = live_pull.get_initial_page_data()

        self.assertEqual(data["ai_status"], "none")
        # Too little history for a read, and no explanation: the view still
        # exists so the page can say "no read yet".
        self.assertEqual(
            data["ai_result"],
            {"groups": ONE_LAGGING_GROUP, "relationship": None, "policy": NO_STANCE, "summary": None},
        )


CURRENT_AI = {
    "summary": "Current read.",
    "generated_at": "2026-09-05T00:00:00+00:00",
    "computed_reads": NO_READS,
    "as_of": {"cpi": "2026-08-01"},
}
FRESH_CONTENT = {
    "indicators_context": [],
    "table": {"lagging": []},
    "countdown": {"entries": [], "soonest": None},
    "ai_result": {"summary": "Fresh read.", "computed_reads": NO_READS},
}


class TestCheckForUpdates(unittest.TestCase):
    def test_no_indicators_updated_reports_no_update_and_skips_ai(self):
        state = make_state(last_ai_response=CURRENT_AI)

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "unchanged"}}
        ), patch("live_pull.update_release_calendar") as mock_calendar, patch(
            "live_pull.build_digest_content"
        ) as mock_build, patch("live_pull.save_state") as mock_save:
            result = live_pull.check_for_updates(now=NOW)

        self.assertEqual(result, {"data_updated": False})
        mock_calendar.assert_not_called()
        mock_build.assert_not_called()
        mock_save.assert_not_called()

    def test_a_revision_alone_is_saved_without_an_ai_call_or_repaint(self):
        state = make_state(last_ai_response=CURRENT_AI)

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion",
            return_value={"cpi": {"status": "revised", "revised": 1}},
        ), patch("live_pull.update_release_calendar") as mock_calendar, patch(
            "live_pull.build_digest_content"
        ) as mock_build, patch("live_pull.save_state") as mock_save:
            result = live_pull.check_for_updates(now=NOW)

        self.assertEqual(result, {"data_updated": False})
        mock_save.assert_called_once()
        mock_build.assert_not_called()
        mock_calendar.assert_not_called()

    def test_all_indicators_erroring_reports_no_update(self):
        state = make_state(last_ai_response=CURRENT_AI)

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "error", "error": "boom"}}
        ), patch("live_pull.build_digest_content") as mock_build:
            result = live_pull.check_for_updates(now=NOW)

        self.assertEqual(result, {"data_updated": False})
        mock_build.assert_not_called()

    def test_an_updated_indicator_triggers_calendar_refresh_and_ai_call(self):
        state = make_state()
        content = {
            "indicators_context": [],
            "table": {"lagging": []},
            "countdown": {"entries": [], "soonest": None},
            "ai_result": {"summary": "Fresh read.", "computed_reads": NO_READS},
        }

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "updated"}}
        ), patch("live_pull.update_release_calendar", return_value={}) as mock_calendar, patch(
            "live_pull.build_digest_content", return_value=content
        ) as mock_build, patch("live_pull.save_state") as mock_save:
            result = live_pull.check_for_updates(now=NOW)

        mock_calendar.assert_called_once()
        mock_build.assert_called_once_with(state, ["cpi"], now=NOW)
        mock_save.assert_called_once_with(state)
        self.assertTrue(result["data_updated"])
        self.assertEqual(result["content"], content)
        self.assertEqual(result["checked_at"], NOW)

    def test_stale_ai_take_is_retried_even_though_nothing_new_arrived(self):
        state = make_state()  # no AI take on file: e.g. every model failed when the data arrived

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "unchanged"}}
        ), patch("live_pull.update_release_calendar") as mock_calendar, patch(
            "live_pull.build_digest_content", return_value=FRESH_CONTENT
        ) as mock_build, patch("live_pull.save_state") as mock_save:
            result = live_pull.check_for_updates(now=NOW)

        mock_build.assert_called_once_with(state, ["cpi"], now=NOW)
        mock_calendar.assert_not_called()
        mock_save.assert_called_once_with(state)
        self.assertTrue(result["data_updated"])

    def test_retry_within_the_cooldown_makes_no_ai_call(self):
        state = make_state()
        state["ai_last_failed_at"] = (NOW - timedelta(minutes=5)).isoformat()

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "unchanged"}}
        ), patch("live_pull.build_digest_content") as mock_build, patch(
            "live_pull.save_state"
        ) as mock_save:
            result = live_pull.check_for_updates(now=NOW)

        mock_build.assert_not_called()
        mock_save.assert_not_called()
        self.assertEqual(result, {"data_updated": False})

    def test_a_retry_that_fails_again_is_saved_but_reports_no_update(self):
        state = make_state()
        failed = {**FRESH_CONTENT, "ai_result": None}

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "unchanged"}}
        ), patch("live_pull.build_digest_content", return_value=failed), patch(
            "live_pull.save_state"
        ) as mock_save:
            result = live_pull.check_for_updates(now=NOW)

        mock_save.assert_called_once_with(state)
        self.assertEqual(result, {"data_updated": False})

    def test_new_data_still_updates_when_the_ai_fails(self):
        state = make_state(last_ai_response=CURRENT_AI)
        failed = {**FRESH_CONTENT, "ai_result": None}

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", return_value={"cpi": {"status": "updated"}}
        ), patch("live_pull.update_release_calendar", return_value={}), patch(
            "live_pull.build_digest_content", return_value=failed
        ), patch("live_pull.save_state"):
            result = live_pull.check_for_updates(now=NOW)

        self.assertTrue(result["data_updated"])

    def test_unexpected_exception_reports_no_update_without_crashing(self):
        state = make_state()

        with patch("live_pull.load_state", return_value=state), patch(
            "live_pull.run_ingestion", side_effect=RuntimeError("network down")
        ):
            result = live_pull.check_for_updates(now=NOW)

        self.assertEqual(result, {"data_updated": False})


if __name__ == "__main__":
    unittest.main()

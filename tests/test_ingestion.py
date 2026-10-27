import os
import sys
import time
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from fetch_fred import FredApiError
import main
from main import run_ingestion

FIXTURES = {
    "ICSA": {"date": "2026-09-04", "value": 235000.0},
    "T10Y2Y": {"date": "2026-09-04", "value": 0.3},
    "PERMIT": {"date": "2026-08-01", "value": 1400.0},
    "PAYEMS": {"date": "2026-08-01", "value": 158000.0},
    "INDPRO": {"date": "2026-08-01", "value": 103.2},
    "DFF": {"date": "2026-08-01", "value": 5.25},
    "CPIAUCSL": {"date": "2026-08-01", "value": 314.5},
    "UNRATE": {"date": "2026-08-01", "value": 4.1},
    "UEMPMED": {"date": "2026-08-01", "value": 9.8},
    "BUSLOANS": {"date": "2026-08-01", "value": 2820.0},
}


def fake_fetch_factory(responses):
    """`responses` maps a series to one observation (the newest) or to a
    list of observations, oldest first, or to an exception to raise."""

    def fake_fetch(series_id, limit=12):
        response = responses[series_id]
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, list) else [response]

    return fake_fetch


class TestRunIngestion(unittest.TestCase):
    def test_a_changed_series_discards_the_old_series_history(self):
        state = {
            "indicators": {
                "fed_funds_rate": {
                    "name": "Fed Funds Rate",
                    "category": "lagging",
                    "fred_series_id": "FEDFUNDS",
                    "fred_release_id": None,
                    "history": [{"date": "2026-08-01", "value": 3.63, "fetched_at": "t"}],
                    "next_release_date": None,
                }
            }
        }
        responses = dict(FIXTURES)
        responses["DFF"] = {"date": "2026-09-24", "value": 3.88}

        run_ingestion(state, fetch_fn=fake_fetch_factory(responses))

        entry = state["indicators"]["fed_funds_rate"]
        self.assertEqual(entry["fred_series_id"], "DFF")
        self.assertEqual([e["value"] for e in entry["history"]], [3.88])

    def test_a_missing_stored_series_id_keeps_existing_history(self):
        state = {
            "indicators": {
                "fed_funds_rate": {
                    "name": "Fed Funds Rate",
                    "category": "lagging",
                    "history": [{"date": "2026-08-01", "value": 3.63, "fetched_at": "t"}],
                    "next_release_date": None,
                }
            }
        }
        responses = dict(FIXTURES)
        responses["DFF"] = {"date": "2026-09-24", "value": 3.88}

        run_ingestion(state, fetch_fn=fake_fetch_factory(responses))

        history = state["indicators"]["fed_funds_rate"]["history"]
        self.assertEqual([e["value"] for e in history], [3.63, 3.88])

    def test_all_ten_indicators_processed_and_tagged(self):
        fetch_fn = fake_fetch_factory(FIXTURES)
        state = {"indicators": {}}

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(len(results), 10)
        self.assertEqual(results["initial_jobless_claims"]["category"], "leading")
        self.assertEqual(results["nonfarm_payrolls"]["category"], "coincident")
        self.assertEqual(results["fed_funds_rate"]["category"], "lagging")
        self.assertTrue(all(r["status"] == "updated" for r in results.values()))

    def test_one_indicator_failure_does_not_block_others(self):
        responses = dict(FIXTURES)
        responses["ICSA"] = FredApiError("simulated outage")
        fetch_fn = fake_fetch_factory(responses)
        state = {"indicators": {}}

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "error")
        self.assertIn("simulated outage", results["initial_jobless_claims"]["error"])
        other_statuses = [
            r["status"] for k, r in results.items() if k != "initial_jobless_claims"
        ]
        self.assertTrue(all(status == "updated" for status in other_statuses))

    def test_unchanged_value_is_not_reprocessed(self):
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(FIXTURES)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "unchanged")
        self.assertEqual(
            len(state["indicators"]["initial_jobless_claims"]["history"]), 1
        )

    def test_older_date_than_stored_is_ignored_not_appended(self):
        # Simulates a stale/cached FRED response returning an older
        # observation than what's already on file.
        responses = dict(FIXTURES)
        responses["ICSA"] = {"date": "2026-08-28", "value": 220000.0}
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(responses)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "unchanged")
        history = state["indicators"]["initial_jobless_claims"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["date"], "2026-09-04")

    def test_newer_date_is_appended(self):
        responses = dict(FIXTURES)
        responses["ICSA"] = {"date": "2026-09-11", "value": 240000.0}
        state = {
            "indicators": {
                "initial_jobless_claims": {
                    "name": "Initial Jobless Claims",
                    "category": "leading",
                    "history": [
                        {
                            "date": "2026-09-04",
                            "value": 235000.0,
                            "fetched_at": "2026-09-04T12:00:00Z",
                        }
                    ],
                }
            }
        }
        fetch_fn = fake_fetch_factory(responses)

        results = run_ingestion(state, fetch_fn=fetch_fn)

        self.assertEqual(results["initial_jobless_claims"]["status"], "updated")
        history = state["indicators"]["initial_jobless_claims"]["history"]
        self.assertEqual([e["date"] for e in history], ["2026-09-04", "2026-09-11"])

    def test_fetches_run_concurrently_not_sequentially(self):
        # 10 indicators each sleeping 0.1s: sequential would take >=1.0s;
        # concurrent (one thread per indicator) should take close to 0.1s.
        def slow_fetch(series_id, limit=12):
            time.sleep(0.1)
            return [FIXTURES[series_id]]

        state = {"indicators": {}}
        started = time.monotonic()
        run_ingestion(state, fetch_fn=slow_fetch)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.4)

    def test_results_ordered_by_config_not_completion(self):
        # Give initial_jobless_claims (first in INDICATORS) the longest
        # delay so it resolves last -- results must still come back keyed
        # correctly per indicator regardless of fetch completion order.
        delays = {"ICSA": 0.05}

        def fake_fetch(series_id, limit=12):
            time.sleep(delays.get(series_id, 0.0))
            return [FIXTURES[series_id]]

        state = {"indicators": {}}
        results = run_ingestion(state, fetch_fn=fake_fetch)

        self.assertEqual(results["initial_jobless_claims"]["status"], "updated")
        self.assertEqual(results["initial_jobless_claims"]["date"], "2026-09-04")
        self.assertTrue(all(r["status"] == "updated" for r in results.values()))


def stored_state(entries):
    return {
        "indicators": {
            "building_permits": {
                "name": "Building Permits",
                "category": "leading",
                "fred_series_id": "PERMIT",
                "fred_release_id": "27",
                "history": entries,
                "next_release_date": None,
            }
        }
    }


def entry(date, value):
    return {"date": date, "value": value, "fetched_at": "2026-09-01T00:00:00+00:00"}


class TestRevisions(unittest.TestCase):
    def run_permits(self, state, observations):
        responses = {**FIXTURES, "PERMIT": observations}
        return run_ingestion(state, fetch_fn=fake_fetch_factory(responses))

    def test_a_revised_value_replaces_the_stored_one_and_keeps_the_old(self):
        state = stored_state([entry("2026-07-01", 1380.0), entry("2026-08-01", 1394.0)])

        results = self.run_permits(
            state,
            [{"date": "2026-07-01", "value": 1380.0}, {"date": "2026-08-01", "value": 1403.0}],
        )

        history = state["indicators"]["building_permits"]["history"]
        self.assertEqual(history[-1]["value"], 1403.0)
        self.assertEqual(history[-1]["previous_value"], 1394.0)
        self.assertIn("revised_at", history[-1])
        self.assertEqual(history[-1]["fetched_at"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(len(history), 2)
        self.assertEqual(results["building_permits"]["status"], "revised")
        self.assertEqual(results["building_permits"]["revised"], 1)

    def test_an_older_reading_is_revised_and_a_new_one_appended_in_one_run(self):
        state = stored_state([entry("2026-06-01", 1350.0), entry("2026-07-01", 1380.0)])

        results = self.run_permits(
            state,
            [
                {"date": "2026-06-01", "value": 1355.0},
                {"date": "2026-07-01", "value": 1380.0},
                {"date": "2026-08-01", "value": 1403.0},
            ],
        )

        history = state["indicators"]["building_permits"]["history"]
        self.assertEqual([e["date"] for e in history], ["2026-06-01", "2026-07-01", "2026-08-01"])
        self.assertEqual(history[0]["value"], 1355.0)
        self.assertEqual(history[0]["previous_value"], 1350.0)
        self.assertNotIn("previous_value", history[1])
        self.assertEqual(results["building_permits"]["status"], "updated")
        self.assertEqual(results["building_permits"]["revised"], 1)

    def test_an_unchanged_value_is_not_marked_revised(self):
        state = stored_state([entry("2026-08-01", 1394.0)])

        results = self.run_permits(state, [{"date": "2026-08-01", "value": 1394.0}])

        history = state["indicators"]["building_permits"]["history"]
        self.assertNotIn("revised_at", history[0])
        self.assertEqual(results["building_permits"]["status"], "unchanged")
        self.assertEqual(results["building_permits"]["revised"], 0)

    def test_a_date_not_already_stored_is_not_added_by_the_lookback(self):
        # 2026-06-01 is in FRED's window but was never stored: it is not
        # appended out of order (backfill.py's job).
        state = stored_state([entry("2026-07-01", 1380.0)])

        self.run_permits(
            state,
            [
                {"date": "2026-06-01", "value": 1350.0},
                {"date": "2026-07-01", "value": 1380.0},
            ],
        )

        history = state["indicators"]["building_permits"]["history"]
        self.assertEqual([e["date"] for e in history], ["2026-07-01"])

    def test_the_same_revision_is_not_applied_twice(self):
        state = stored_state([entry("2026-08-01", 1394.0)])
        observations = [{"date": "2026-08-01", "value": 1403.0}]

        self.run_permits(state, observations)
        second = self.run_permits(state, observations)

        history = state["indicators"]["building_permits"]["history"]
        self.assertEqual(history[0]["previous_value"], 1394.0)
        self.assertEqual(second["building_permits"]["status"], "unchanged")

    def test_a_second_different_revision_replaces_previous_value(self):
        state = stored_state([entry("2026-08-01", 1394.0)])

        self.run_permits(state, [{"date": "2026-08-01", "value": 1403.0}])
        third = self.run_permits(state, [{"date": "2026-08-01", "value": 1410.0}])

        history = state["indicators"]["building_permits"]["history"]
        self.assertEqual(history[0]["value"], 1410.0)
        self.assertEqual(history[0]["previous_value"], 1403.0)
        self.assertEqual(third["building_permits"]["status"], "revised")

    def test_a_stale_response_never_overwrites_newer_stored_values(self):
        # FRED (or a cache) answers with a window that ends before the
        # newest stored reading; its older values must not win.
        state = stored_state([entry("2026-07-01", 1380.0), entry("2026-08-01", 1394.0)])

        results = self.run_permits(state, [{"date": "2026-07-01", "value": 1111.0}])

        history = state["indicators"]["building_permits"]["history"]
        self.assertEqual([e["value"] for e in history], [1380.0, 1394.0])
        self.assertEqual(results["building_permits"]["status"], "unchanged")

    def test_an_empty_response_is_an_error_not_a_crash(self):
        state = stored_state([entry("2026-08-01", 1394.0)])

        results = self.run_permits(state, [])

        self.assertEqual(results["building_permits"]["status"], "error")
        self.assertEqual(state["indicators"]["building_permits"]["history"][0]["value"], 1394.0)

    def test_the_lookback_is_requested(self):
        seen = {}

        def fake_fetch(series_id, limit=None):
            seen[series_id] = limit
            return [FIXTURES[series_id]]

        run_ingestion({"indicators": {}}, fetch_fn=fake_fetch)
        self.assertEqual(set(seen.values()), {main.REVISION_LOOKBACK})


if __name__ == "__main__":
    unittest.main()

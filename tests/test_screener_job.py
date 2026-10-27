import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener"), os.path.join(_SRC, "web"), os.path.dirname(__file__)):
    sys.path.insert(0, _p)

import logging

import edgar_client
import finnhub_client
from kv_store import KvStoreError
import job
import scoring
from edgar_client import EdgarApiError, EdgarRateLimited
from finnhub_client import FinnhubApiError, FinnhubRateLimited
from test_scoring import GOOD_CAPEX, GOOD_OCF, GOOD_SHARES, _facts

NOW = datetime(2026, 10, 20, 5, 30, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
DAY = timedelta(days=1)
OLD = (NOW - timedelta(days=91)).isoformat()
RECENT = (NOW - timedelta(days=30)).isoformat()

GOOD_METRICS = {
    "low": 8.0, "high": 15.0, "market_cap": 5000.0, "pe_ratio": 20.0, "peg_ratio": 1.5, "roi": 12.0, "roe": 12.0,
    "net_margin": 8.0, "debt_to_equity": 0.2, "eps_growth": 4.0, "revenue_growth": 20.0,
}


class FakeStore:
    def __init__(self, universe=None, candidates=None, earnings=None):
        self.universe = dict(universe or {})
        self.candidates = dict(candidates or {})
        self.earnings = dict(earnings or {})
        self.state = None

    def load_earnings(self):
        return dict(self.earnings)

    def save_earnings(self, symbol, entry):
        self.earnings[symbol] = entry

    def load_universe(self):
        return dict(self.universe)

    def load_candidates(self):
        return dict(self.candidates)

    def save_universe_entry(self, symbol, entry):
        self.universe[symbol] = entry

    def save_candidate(self, symbol, record):
        self.candidates[symbol] = record

    def save_state(self, state):
        self.state = state


class FakeFinnhub:
    def __init__(self, symbols, profiles=None, metrics=None, fail=None, rate_limit_on=None, dates=None):
        self.symbols = symbols
        self.dates = dates or {}
        self.profiles = profiles or {}
        self.metrics = metrics or {}
        self.fail = fail or {}
        self.rate_limit_on = rate_limit_on
        self.calls = []

    def fetch_us_common_stocks(self):
        return list(self.symbols)

    def _enter(self, kind, symbol):
        self.calls.append((kind, symbol))
        if symbol == self.rate_limit_on:
            raise FinnhubRateLimited("429")
        if symbol in self.fail:
            raise FinnhubApiError("boom")

    def fetch_company_profile(self, symbol):
        self._enter("profile", symbol)
        return self.profiles.get(symbol, {"name": symbol + " Inc", "market_cap": 5000.0, "ipo_date": "2021-02-18"})

    def fetch_next_earnings_date(self, symbol, today):
        self._enter("earnings", symbol)
        return self.dates.get(symbol, {}).get("next")

    def fetch_stock_metrics(self, symbol, require_range=True):
        self._enter("metrics", symbol)
        return self.metrics.get(symbol, GOOD_METRICS)


class FakeEdgar:
    lookup_cik = staticmethod(edgar_client.lookup_cik)

    def __init__(self, ciks, sics=None, facts=None, fail_summary=None, rate_limit_summary=None, report_dates=None,
                 rate_limit_report_date=None):
        self.ciks = ciks
        self.sics = sics or {}
        self.facts = facts or {}
        self.fail_summary = fail_summary or set()
        self.rate_limit_summary = rate_limit_summary
        self.report_dates = report_dates or {}
        self.rate_limit_report_date = rate_limit_report_date
        self.calls = []

    def fetch_ticker_ciks(self):
        return dict(self.ciks)

    def fetch_submissions_summary(self, cik):
        self.calls.append(("summary", cik))
        if cik == self.rate_limit_summary:
            raise EdgarRateLimited("429")
        if cik in self.fail_summary:
            raise EdgarApiError("boom")
        return {"name": f"Co{cik}", "sic": self.sics.get(cik, 7372), "sic_description": "x"}

    def fetch_latest_report_date(self, cik):
        self.calls.append(("report_date", cik))
        if cik == self.rate_limit_report_date:
            raise EdgarRateLimited("429")
        return self.report_dates.get(cik)

    def fetch_company_facts(self, cik):
        self.calls.append(("facts", cik))
        return self.facts.get(cik, _facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES))


def _entry(stage="tech", market_cap=5000.0, checked_at=RECENT, cik=1, sic=7372):
    return {"cik": cik, "sic": sic, "stage": stage, "market_cap": market_cap, "checked_at": checked_at}


class FakeSettings:
    def __init__(self, settings=scoring.DEFAULT_SETTINGS):
        self.settings = settings

    def load_settings(self):
        return self.settings


def _run(finnhub, edgar, store, cap=1500, settings=None):
    return job.run_job(NOW, cap, finnhub=finnhub, edgar=edgar, job_store=store, settings_store=FakeSettings(settings or scoring.DEFAULT_SETTINGS), pace=lambda: None)


class TestClassifyingNewSymbols(unittest.TestCase):
    def test_new_symbols_get_a_stage(self):
        store = FakeStore()
        finnhub = FakeFinnhub(["GCTS", "NOCIK", "BANK"], profiles={"GCTS": {"name": "GCT", "market_cap": 120.0, "ipo_date": "2022-01-01"}})
        edgar = FakeEdgar({"GCTS": 10, "BANK": 20}, sics={10: 3674, 20: 6021})

        counts = _run(finnhub, edgar, store)

        self.assertEqual(store.universe["NOCIK"]["stage"], "no_cik")
        self.assertEqual(store.universe["BANK"]["stage"], "non_tech")
        self.assertEqual(store.universe["GCTS"]["stage"], "tech")
        self.assertEqual(store.universe["GCTS"]["market_cap"], 120.0)
        self.assertEqual(store.universe["GCTS"]["checked_at"], STAMP)
        self.assertEqual(counts["new"], 3)

    def test_only_tech_symbols_cost_a_finnhub_call(self):
        finnhub = FakeFinnhub(["NOCIK", "BANK"])
        edgar = FakeEdgar({"BANK": 20}, sics={20: 6021})

        _run(finnhub, edgar, FakeStore())

        self.assertEqual(finnhub.calls, [])

    def test_a_dotted_class_share_is_found_by_its_hyphen_form(self):
        store = FakeStore()
        finnhub = FakeFinnhub(["BRK.A"])
        edgar = FakeEdgar({"BRK-A": 1067983}, sics={1067983: 6331})

        _run(finnhub, edgar, store)

        self.assertEqual(store.universe["BRK.A"]["stage"], "non_tech")
        self.assertEqual(store.universe["BRK.A"]["cik"], 1067983)

    def test_a_tech_symbol_inside_the_band_becomes_a_candidate_with_a_complete_record(self):
        store = FakeStore()
        finnhub = FakeFinnhub(["DSP"], profiles={"DSP": {"name": "Viant", "market_cap": 2851.2, "ipo_date": "2021-02-18"}})
        edgar = FakeEdgar({"DSP": 77})

        counts = _run(finnhub, edgar, store)

        record = store.candidates["DSP"]
        self.assertEqual(record["name"], "Viant")
        self.assertEqual(record["cik"], 77)
        self.assertEqual(record["ipo_date"], "2021-02-18")
        self.assertEqual(record["market_cap"], 2851.2)
        self.assertIn("2025-12-31", record["shares_by_year"])
        self.assertEqual(record["metrics"]["roi"], 12.0)
        self.assertEqual(counts["new_candidates"], 1)

    def test_the_profile_fetched_while_classifying_is_reused_not_fetched_twice(self):
        finnhub = FakeFinnhub(["DSP"])

        _run(finnhub, FakeEdgar({"DSP": 77}), FakeStore())

        self.assertEqual(finnhub.calls.count(("profile", "DSP")), 1)

    def test_a_tech_symbol_outside_the_band_is_classified_but_not_fetched_in_full(self):
        store = FakeStore()
        finnhub = FakeFinnhub(["BIG"], profiles={"BIG": {"name": "Big", "market_cap": 50000.0, "ipo_date": "1990-01-01"}})

        _run(finnhub, FakeEdgar({"BIG": 5}), store)

        self.assertEqual(store.universe["BIG"]["market_cap"], 50000.0)
        self.assertNotIn("BIG", store.candidates)
        self.assertNotIn(("metrics", "BIG"), finnhub.calls)

    def test_a_symbol_with_no_edgar_company_facts_becomes_a_flagged_candidate(self):
        store = FakeStore()
        edgar = FakeEdgar({"DSP": 77}, facts={77: None})

        _run(FakeFinnhub(["DSP"]), edgar, store)

        self.assertTrue(store.candidates["DSP"]["flags"])


class TestNoCikRecheck(unittest.TestCase):
    def test_a_no_cik_symbol_is_classified_once_edgar_maps_it(self):
        store = FakeStore(universe={"NEWCO": _entry(stage="no_cik", market_cap=None, cik=None, sic=None)})
        edgar = FakeEdgar({"NEWCO": 99})

        counts = _run(FakeFinnhub(["NEWCO"]), edgar, store)

        self.assertEqual(store.universe["NEWCO"]["stage"], "tech")
        self.assertEqual(store.universe["NEWCO"]["cik"], 99)
        self.assertEqual(counts["no_cik_rechecked"], 1)
        self.assertIn("NEWCO", store.candidates)

    def test_a_no_cik_symbol_that_is_still_unmapped_costs_nothing(self):
        store = FakeStore(universe={"NEWCO": _entry(stage="no_cik", market_cap=None, cik=None, sic=None)})
        finnhub, edgar = FakeFinnhub(["NEWCO"]), FakeEdgar({})

        _run(finnhub, edgar, store)

        self.assertEqual(finnhub.calls, [])
        self.assertEqual(edgar.calls, [])
        self.assertEqual(store.universe["NEWCO"]["stage"], "no_cik")


class TestNinetyDayRefresh(unittest.TestCase):
    def test_non_tech_symbols_are_never_rechecked(self):
        store = FakeStore(universe={"BANK": _entry(stage="non_tech", market_cap=None, checked_at=OLD, sic=6021)})
        finnhub, edgar = FakeFinnhub(["BANK"]), FakeEdgar({"BANK": 1})

        counts = _run(finnhub, edgar, store)

        self.assertEqual(finnhub.calls, [])
        self.assertEqual(edgar.calls, [])
        self.assertEqual(counts["refreshed"], 0)

    def test_a_recently_checked_symbol_is_left_alone(self):
        store = FakeStore(universe={"DSP": _entry(checked_at=RECENT)}, candidates={"DSP": {"name": "old", "market_at": RECENT}},
                          earnings={"DSP": {"next": None, "last": None, "fetched_at": (NOW - DAY).isoformat()}})
        finnhub = FakeFinnhub(["DSP"])

        _run(finnhub, FakeEdgar({"DSP": 1}), store)

        self.assertEqual(finnhub.calls, [])
        self.assertEqual(store.candidates["DSP"]["name"], "old")

    def test_an_out_of_band_symbol_without_a_record_gets_only_a_market_cap_check(self):
        store = FakeStore(universe={"BIG": _entry(market_cap=50000.0, checked_at=OLD)})
        finnhub = FakeFinnhub(["BIG"], profiles={"BIG": {"name": "Big", "market_cap": 48000.0, "ipo_date": "1990-01-01"}})

        _run(finnhub, FakeEdgar({"BIG": 1}), store)

        self.assertEqual(finnhub.calls, [("profile", "BIG")])
        self.assertEqual(store.universe["BIG"]["market_cap"], 48000.0)
        self.assertEqual(store.universe["BIG"]["checked_at"], STAMP)
        self.assertNotIn("BIG", store.candidates)

    def test_a_symbol_that_has_grown_into_the_band_becomes_a_candidate_the_same_night(self):
        store = FakeStore(universe={"GROW": _entry(market_cap=job.scoring.DEFAULT_SETTINGS.market_cap_min_m / 4, checked_at=OLD)})
        finnhub = FakeFinnhub(["GROW"], profiles={"GROW": {"name": "Grow", "market_cap": job.scoring.DEFAULT_SETTINGS.market_cap_min_m + 300.0, "ipo_date": "2023-01-01"}})

        counts = _run(finnhub, FakeEdgar({"GROW": 1}), store)

        self.assertIn("GROW", store.candidates)
        self.assertEqual(counts["new_candidates"], 1)
        self.assertEqual(finnhub.calls.count(("profile", "GROW")), 1)

    def test_a_candidate_is_refreshed_with_metrics_and_facts_whatever_its_status(self):
        old_record = {"name": "Old", "market_cap": 400.0}
        store = FakeStore(universe={"DSP": _entry(checked_at=OLD)}, candidates={"DSP": old_record})
        finnhub, edgar = FakeFinnhub(["DSP"]), FakeEdgar({"DSP": 1})

        counts = _run(finnhub, edgar, store)

        self.assertEqual(store.candidates["DSP"]["name"], "DSP Inc")
        self.assertEqual(store.candidates["DSP"]["market_at"], STAMP)
        self.assertEqual(store.universe["DSP"]["checked_at"], STAMP)
        self.assertEqual(store.universe["DSP"]["market_cap"], 5000.0)
        self.assertEqual(counts["refreshed"], 1)
        self.assertIn(("facts", 1), edgar.calls)

    def test_a_candidate_that_left_the_band_keeps_its_record_and_is_refreshed(self):
        above_the_band = job.scoring.DEFAULT_SETTINGS.market_cap_max_m + 1000.0
        store = FakeStore(universe={"DSP": _entry(checked_at=OLD)}, candidates={"DSP": {"name": "Old"}})
        finnhub = FakeFinnhub(["DSP"], profiles={"DSP": {"name": "Grown", "market_cap": above_the_band, "ipo_date": "2021-02-18"}})

        _run(finnhub, FakeEdgar({"DSP": 1}), store)

        self.assertEqual(store.candidates["DSP"]["name"], "Grown")
        self.assertEqual(store.universe["DSP"]["market_cap"], above_the_band)

    def test_a_candidate_is_due_by_its_own_market_at_not_the_universe_checked_at(self):
        recent_record = {"name": "Recent", "market_at": RECENT}
        stale_record = {"name": "Stale", "market_at": OLD}
        store = FakeStore(
            universe={"FRESH": _entry(checked_at=OLD, cik=1), "LOST": _entry(checked_at=STAMP, cik=2)},
            candidates={"FRESH": recent_record, "LOST": stale_record},
        )
        finnhub = FakeFinnhub(["FRESH", "LOST"])

        _run(finnhub, FakeEdgar({"FRESH": 1, "LOST": 2}), store)

        self.assertEqual(store.candidates["FRESH"], recent_record)
        self.assertEqual(store.candidates["LOST"]["name"], "LOST Inc")

    def test_a_symbol_that_left_finnhubs_list_is_not_refreshed_and_keeps_its_record(self):
        record = {"name": "Gone", "market_at": OLD, "market_cap": 400.0}
        store = FakeStore(universe={"GONE": _entry(checked_at=OLD)}, candidates={"GONE": record})
        finnhub = FakeFinnhub(["OTHER"])

        _run(finnhub, FakeEdgar({"OTHER": 9}, sics={9: 6021}), store)

        self.assertEqual(finnhub.calls, [])
        self.assertEqual(store.candidates["GONE"], record)

    def test_a_failed_refresh_keeps_the_stored_record_and_dates(self):
        record = {"name": "Old", "market_at": OLD, "market_cap": 400.0}
        for failure in ("metrics", "facts"):
            store = FakeStore(universe={"DSP": _entry(checked_at=OLD)}, candidates={"DSP": dict(record)})
            if failure == "metrics":
                finnhub, edgar = FakeFinnhub(["DSP"]), FakeEdgar({"DSP": 1})
                finnhub.fetch_stock_metrics = lambda symbol, require_range=True: (_ for _ in ()).throw(FinnhubApiError("boom"))
            else:
                finnhub, edgar = FakeFinnhub(["DSP"]), FakeEdgar({"DSP": 1})
                edgar.fetch_company_facts = lambda cik: (_ for _ in ()).throw(EdgarApiError("boom"))

            counts = _run(finnhub, edgar, store)

            self.assertEqual(counts["failed"], 1, failure)
            self.assertEqual(store.candidates["DSP"], record, failure)
            self.assertEqual(store.universe["DSP"]["checked_at"], OLD, failure)

    def test_a_naive_stored_timestamp_is_read_as_utc(self):
        store = FakeStore(universe={"BIG": _entry(market_cap=50000.0, checked_at="2026-01-01T00:00:00")})
        finnhub = FakeFinnhub(["BIG"], profiles={"BIG": {"name": "Big", "market_cap": 50000.0, "ipo_date": "1990-01-01"}})

        _run(finnhub, FakeEdgar({"BIG": 1}), store)

        self.assertEqual(finnhub.calls, [("profile", "BIG")])

    def test_the_oldest_are_refreshed_first_when_the_cap_runs_out(self):
        days = lambda n: (NOW - timedelta(days=n)).isoformat()
        store = FakeStore(
            universe={
                "MID": _entry(market_cap=50000.0, checked_at=days(120), cik=2),
                "OLDEST": _entry(market_cap=50000.0, checked_at=days(300), cik=1),
                "NEWEST": _entry(market_cap=50000.0, checked_at=days(95), cik=3),
            }
        )
        finnhub = FakeFinnhub(["MID", "OLDEST", "NEWEST"])

        counts = _run(finnhub, FakeEdgar({}), store, cap=3)

        self.assertEqual([c[1] for c in finnhub.calls], ["OLDEST", "MID"])
        self.assertEqual(store.universe["NEWEST"]["checked_at"], days(95))
        self.assertEqual(counts["stopped"], "call cap reached")

    def test_a_lost_candidate_record_is_rebuilt_for_an_in_band_symbol(self):
        store = FakeStore(universe={"DSP": _entry(market_cap=5000.0, checked_at=RECENT, cik=77)})

        counts = _run(FakeFinnhub(["DSP"]), FakeEdgar({"DSP": 77}), store)

        record = store.candidates["DSP"]
        self.assertEqual(record["cik"], 77)
        self.assertEqual(record["name"], "DSP Inc")
        self.assertTrue(record["ipo_date"])
        self.assertTrue(record["shares_by_year"])
        self.assertEqual(counts["new_candidates"], 1)


class TestCapAndResume(unittest.TestCase):
    def test_a_run_stops_at_the_cap_and_the_next_run_continues_without_repeating(self):
        symbols = ["A", "B", "C", "D"]
        ciks = {s: i + 1 for i, s in enumerate(symbols)}
        store = FakeStore()
        edgar = FakeEdgar(ciks, sics={1: 7372, 2: 7372, 3: 7372, 4: 7372})

        first_finnhub = FakeFinnhub(symbols, profiles={s: {"name": s, "market_cap": 50000.0, "ipo_date": "2000-01-01"} for s in symbols})
        first = _run(first_finnhub, edgar, store, cap=3)

        self.assertEqual(first["stopped"], "call cap reached")
        self.assertEqual(sorted(store.universe), ["A", "B"])
        self.assertFalse(store.state["initial_pass_done"])
        self.assertEqual(store.state["universe_checked"], 2)

        second_finnhub = FakeFinnhub(symbols, profiles=first_finnhub.profiles)
        second = _run(second_finnhub, edgar, store, cap=10)

        self.assertIsNone(second["stopped"])
        self.assertEqual(sorted(store.universe), symbols)
        self.assertEqual([c[1] for c in second_finnhub.calls], ["C", "D"])
        self.assertTrue(store.state["initial_pass_done"])

    def test_the_state_records_totals_and_the_run_time(self):
        store = FakeStore()

        _run(FakeFinnhub(["BANK", "NOCIK"]), FakeEdgar({"BANK": 1}, sics={1: 6021}), store)

        self.assertEqual(store.state["universe_total"], 2)
        self.assertEqual(store.state["universe_checked"], 2)
        self.assertTrue(store.state["initial_pass_done"])
        self.assertEqual(store.state["last_run_at"], STAMP)
        self.assertEqual(store.state["last_run_counts"]["new"], 2)


class TestFailures(unittest.TestCase):
    def test_an_unexpected_error_from_one_symbol_is_skipped_not_fatal(self):
        store = FakeStore()
        edgar = FakeEdgar({"A": 1, "B": 2, "C": 3})
        original = edgar.fetch_submissions_summary

        def flaky(cik):
            if cik == 2:
                raise KeyError("point")
            return original(cik)

        edgar.fetch_submissions_summary = flaky

        counts = _run(FakeFinnhub(["A", "B", "C"]), edgar, store)

        self.assertEqual(counts["failed"], 1)
        self.assertIn("A", store.universe)
        self.assertIn("C", store.universe)
        self.assertIsNotNone(store.state)

    def test_a_malformed_edgar_fact_does_not_stop_the_candidates_after_it(self):
        store = FakeStore(universe={"A": _entry(cik=1, checked_at=RECENT), "B": _entry(cik=2, checked_at=RECENT)})
        edgar = FakeEdgar({"A": 1, "B": 2}, facts={1: {"facts": {"us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"form": "10-K", "start": "x", "end": "y", "val": 1}]}}}}}})

        counts = _run(FakeFinnhub(["A", "B"]), edgar, store)

        self.assertEqual(counts["failed"], 1)
        self.assertIn("B", store.candidates)

    def test_the_cap_hitting_between_two_calls_for_one_symbol_writes_nothing_for_it(self):
        store = FakeStore(universe={"DSP": _entry(cik=1, checked_at=RECENT)})
        finnhub = FakeFinnhub(["DSP"])

        counts = _run(finnhub, FakeEdgar({"DSP": 1}), store, cap=2)

        self.assertEqual(finnhub.calls, [("profile", "DSP")])
        self.assertEqual(counts["stopped"], "call cap reached")
        self.assertNotIn("DSP", store.candidates)
        self.assertEqual(store.universe["DSP"]["checked_at"], RECENT)

    def test_the_log_never_carries_the_api_token(self):
        class LeakyFinnhub(FakeFinnhub):
            def fetch_company_profile(self, symbol):
                raise FinnhubApiError("403 Client Error: Forbidden for url: https://finnhub.io/api/v1/stock/profile2?symbol=X&token=SECRETKEY")

        with self.assertLogs("job", level="WARNING") as logs:
            _run(LeakyFinnhub(["A"]), FakeEdgar({"A": 1}), FakeStore())

        self.assertNotIn("SECRETKEY", "\n".join(logs.output))
        self.assertIn("token=REDACTED", "\n".join(logs.output))

    def test_one_symbols_failure_does_not_stop_the_run(self):
        store = FakeStore()
        finnhub = FakeFinnhub(["A", "B", "C"], fail={"B": True})
        edgar = FakeEdgar({"A": 1, "B": 2, "C": 3})

        counts = _run(finnhub, edgar, store)

        self.assertEqual(counts["failed"], 1)
        self.assertIn("A", store.universe)
        self.assertIn("C", store.universe)
        self.assertNotIn("B", store.universe)
        self.assertIsNone(counts["stopped"])

    def test_an_edgar_failure_for_one_symbol_is_skipped(self):
        store = FakeStore()
        edgar = FakeEdgar({"A": 1, "B": 2}, fail_summary={1})

        counts = _run(FakeFinnhub(["A", "B"]), edgar, store)

        self.assertEqual(counts["failed"], 1)
        self.assertIn("B", store.universe)

    def test_a_finnhub_rate_limit_stops_the_run_and_still_saves_state(self):
        store = FakeStore()
        finnhub = FakeFinnhub(["A", "B", "C"], rate_limit_on="B")
        edgar = FakeEdgar({"A": 1, "B": 2, "C": 3})

        counts = _run(finnhub, edgar, store)

        self.assertEqual(counts["stopped"], "rate limited")
        self.assertIn("A", store.universe)
        self.assertNotIn("C", store.universe)
        self.assertEqual(finnhub.calls.count(("profile", "B")), 1)
        self.assertEqual(store.state["last_run_counts"]["stopped"], "rate limited")

    def test_an_edgar_rate_limit_stops_the_run(self):
        store = FakeStore()
        edgar = FakeEdgar({"A": 1, "B": 2, "C": 3}, rate_limit_summary=2)

        counts = _run(FakeFinnhub(["A", "B", "C"]), edgar, store)

        self.assertEqual(counts["stopped"], "rate limited")
        self.assertNotIn("C", store.universe)
        self.assertEqual(edgar.calls.count(("summary", 2)), 1)

    def test_a_storage_failure_propagates_and_saves_no_state(self):
        from kv_store import KvStoreError

        class BrokenStore(FakeStore):
            def save_universe_entry(self, symbol, entry):
                raise KvStoreError("down")

        store = BrokenStore()

        with self.assertRaises(KvStoreError):
            _run(FakeFinnhub(["A"]), FakeEdgar({"A": 1}), store)

        self.assertIsNone(store.state)


class TestPacing(unittest.TestCase):
    def test_every_finnhub_call_is_paced_including_the_ones_that_hit_the_cap_check(self):
        paced = []
        finnhub = FakeFinnhub(["DSP"])

        job.run_job(NOW, 10, finnhub=finnhub, edgar=FakeEdgar({"DSP": 1}), job_store=FakeStore(), settings_store=FakeSettings(), pace=lambda: paced.append(1))

        self.assertEqual(len(paced), len(finnhub.calls))

    @patch("job.time.sleep")
    @patch("job.time.monotonic")
    def test_the_pacer_keeps_finnhub_calls_under_the_per_minute_limit(self, mock_monotonic, mock_sleep):
        pace = job._make_pacer(1.1)
        mock_monotonic.side_effect = [100.0, 100.0, 100.3, 100.3]

        pace()
        pace()

        self.assertAlmostEqual(mock_sleep.call_args.args[0], 0.8, places=2)


def _candidate(market_at):
    return {"name": "old", "market_at": market_at}


def _earnings(last=None, next_=None, fetched_at=(NOW - DAY).isoformat()):
    return {"last": last, "next": next_, "fetched_at": fetched_at}


class TestEarningsDates(unittest.TestCase):
    def run_one(self, earnings=None, market_at=RECENT, dates=None, checked_at=RECENT, report_dates=None, **kwargs):
        store = FakeStore(universe={"DSP": _entry(checked_at=checked_at)}, candidates={"DSP": _candidate(market_at)},
                          earnings={"DSP": earnings} if earnings else {})
        finnhub = FakeFinnhub(["DSP"], dates=dates)
        counts = _run(finnhub, FakeEdgar({"DSP": 1}, report_dates=report_dates), store, **kwargs)
        return store, finnhub, counts

    def test_a_candidate_with_no_dates_gets_them_stored_with_a_fetch_time(self):
        store, finnhub, counts = self.run_one(dates={"DSP": {"next": "2026-11-05"}}, report_dates={1: "2026-08-05"})

        self.assertEqual(store.earnings["DSP"], {"next": "2026-11-05", "last": "2026-08-05", "fetched_at": STAMP})
        self.assertEqual(counts["dates_fetched"], 1)

    def test_dates_fetched_within_a_week_are_not_fetched_again(self):
        _, finnhub, counts = self.run_one(earnings=_earnings(fetched_at=(NOW - 6 * DAY).isoformat()))

        self.assertNotIn(("earnings", "DSP"), finnhub.calls)
        self.assertEqual(counts["dates_fetched"], 0)

    def test_dates_older_than_a_week_are_fetched_again(self):
        _, finnhub, counts = self.run_one(earnings=_earnings(fetched_at=(NOW - 8 * DAY).isoformat()))

        self.assertIn(("earnings", "DSP"), finnhub.calls)

    def test_a_candidate_is_refreshed_once_the_margin_after_its_last_report_has_passed(self):
        last = (NOW - 4 * DAY).date().isoformat()
        store, finnhub, counts = self.run_one(earnings=_earnings(last=last), market_at=(NOW - 20 * DAY).isoformat())

        self.assertEqual(counts["refreshed"], 1)
        self.assertEqual(store.candidates["DSP"]["market_at"], STAMP)

    def test_a_candidate_is_not_refreshed_inside_the_margin(self):
        last = (NOW - 2 * DAY).date().isoformat()
        _, _, counts = self.run_one(earnings=_earnings(last=last), market_at=(NOW - 20 * DAY).isoformat())

        self.assertEqual(counts["refreshed"], 0)

    def test_a_candidate_refreshed_after_the_margin_is_not_refreshed_again(self):
        last = (NOW - 10 * DAY).date().isoformat()
        _, _, counts = self.run_one(earnings=_earnings(last=last), market_at=(NOW - 2 * DAY).isoformat())

        self.assertEqual(counts["refreshed"], 0)

    def test_a_candidate_with_a_last_date_is_not_refreshed_on_the_ninety_day_rule(self):
        last = (NOW - 100 * DAY).date().isoformat()
        _, _, counts = self.run_one(earnings=_earnings(last=last), market_at=(NOW - 95 * DAY).isoformat())

        self.assertEqual(counts["refreshed"], 0)

    def test_a_candidate_with_no_last_date_still_refreshes_after_ninety_days(self):
        _, _, old = self.run_one(earnings=_earnings(), market_at=(NOW - 91 * DAY).isoformat())
        _, _, recent = self.run_one(earnings=_earnings(), market_at=(NOW - 89 * DAY).isoformat())

        self.assertEqual((old["refreshed"], recent["refreshed"]), (1, 0))

    def test_a_symbol_without_a_record_keeps_the_ninety_day_market_cap_check(self):
        store = FakeStore(universe={"BIG": _entry(market_cap=50000.0, checked_at=OLD)})
        finnhub = FakeFinnhub(["BIG"], profiles={"BIG": {"name": "Big", "market_cap": 48000.0, "ipo_date": "1990-01-01"}})

        counts = _run(finnhub, FakeEdgar({"BIG": 1}), store)

        self.assertEqual(counts["refreshed"], 1)
        self.assertNotIn("BIG", store.candidates)
        self.assertNotIn(("earnings", "BIG"), finnhub.calls)

    def test_a_newly_built_candidate_gets_its_dates_the_same_run(self):
        store = FakeStore(universe={"DSP": _entry(checked_at=RECENT)})
        finnhub = FakeFinnhub(["DSP"], dates={"DSP": {"next": "2026-11-05"}})

        _run(finnhub, FakeEdgar({"DSP": 1}, report_dates={1: "2026-08-05"}), store)

        self.assertEqual(store.earnings["DSP"]["last"], "2026-08-05")

    def test_the_oldest_dates_are_fetched_first_when_the_cap_stops_the_run(self):
        store = FakeStore(universe={s: _entry(checked_at=RECENT) for s in ("AAA", "BBB")},
                          candidates={s: _candidate(RECENT) for s in ("AAA", "BBB")},
                          earnings={"AAA": _earnings(fetched_at=(NOW - 8 * DAY).isoformat()),
                                    "BBB": _earnings(fetched_at=(NOW - 30 * DAY).isoformat())})
        finnhub = FakeFinnhub(["AAA", "BBB"])

        counts = _run(finnhub, FakeEdgar({"AAA": 1, "BBB": 2}), store, cap=2)

        self.assertEqual(finnhub.calls, [("earnings", "BBB")])
        self.assertEqual(counts["stopped"], "call cap reached")

    def test_a_rate_limit_on_the_calendar_stops_the_run_and_is_not_retried(self):
        store = FakeStore(universe={s: _entry(checked_at=RECENT) for s in ("AAA", "BBB")},
                          candidates={s: _candidate(RECENT) for s in ("AAA", "BBB")})
        finnhub = FakeFinnhub(["AAA", "BBB"], rate_limit_on="AAA")

        counts = _run(finnhub, FakeEdgar({"AAA": 1, "BBB": 2}), store)

        self.assertEqual(counts["stopped"], "rate limited")
        self.assertEqual(finnhub.calls, [("earnings", "AAA")])

    def test_an_edgar_rate_limit_while_fetching_the_last_report_stops_the_run(self):
        store = FakeStore(universe={"DSP": _entry(checked_at=RECENT)}, candidates={"DSP": _candidate(RECENT)})
        edgar = FakeEdgar({"DSP": 1}, rate_limit_report_date=1)

        counts = _run(FakeFinnhub(["DSP"]), edgar, store)

        self.assertEqual(counts["stopped"], "rate limited")
        self.assertEqual(store.earnings, {})
        self.assertEqual(edgar.calls.count(("report_date", 1)), 1)

    def test_a_missing_report_date_is_stored_as_none(self):
        store, _, _ = self.run_one(dates={"DSP": {"next": "2026-11-05"}})

        self.assertEqual((store.earnings["DSP"]["next"], store.earnings["DSP"]["last"]), ("2026-11-05", None))

    def test_another_error_skips_that_symbol_only(self):
        store = FakeStore(universe={s: _entry(checked_at=RECENT) for s in ("AAA", "BBB")},
                          candidates={s: _candidate(RECENT) for s in ("AAA", "BBB")})
        finnhub = FakeFinnhub(["AAA", "BBB"], fail={"AAA": True})

        counts = _run(finnhub, FakeEdgar({"AAA": 1, "BBB": 2}), store)

        self.assertEqual((counts["failed"], counts["dates_fetched"]), (1, 1))
        self.assertIn("BBB", store.earnings)
        self.assertNotIn("AAA", store.earnings)


class TestSavedMarketCapBand(unittest.TestCase):
    def test_a_symbol_inside_a_widened_saved_band_is_fetched_tonight(self):
        store = FakeStore(universe={"BIG": _entry(market_cap=50000.0)})
        finnhub = FakeFinnhub(["BIG"], profiles={"BIG": {"name": "Big", "market_cap": 50000.0, "ipo_date": "1990-01-01"}})
        wider = scoring.ScreenSettings(market_cap_max_m=60000.0)

        counts = _run(finnhub, FakeEdgar({"BIG": 1}), store, settings=wider)

        self.assertIn("BIG", store.candidates)
        self.assertEqual(counts["new_candidates"], 1)

    def test_the_same_symbol_is_left_alone_with_the_default_band(self):
        store = FakeStore(universe={"BIG": _entry(market_cap=50000.0)})
        finnhub = FakeFinnhub(["BIG"])

        _run(finnhub, FakeEdgar({"BIG": 1}), store)

        self.assertEqual(store.candidates, {})

    def test_a_failed_settings_read_stops_the_job_loudly(self):
        class Failing:
            def load_settings(self):
                raise KvStoreError("down")

        with self.assertRaises(KvStoreError):
            job.run_job(NOW, 10, finnhub=FakeFinnhub([]), edgar=FakeEdgar({}), job_store=FakeStore(), settings_store=Failing(), pace=lambda: None)


class TestIsolationFromTriage(unittest.TestCase):
    def test_the_job_never_references_the_status_or_notes_keys(self):
        with open(job.__file__) as f:
            source = f.read()

        for key in ("screener_status", "screener_notes", "screener_settings", "page_store"):
            self.assertNotIn(key, source)

    def test_the_job_only_reads_the_settings_and_never_saves_them(self):
        with open(job.__file__) as f:
            source = f.read()

        self.assertNotIn("save_form", source)
        self.assertIn("settings_store.load_settings()", source)


class TestEntryPoint(unittest.TestCase):
    @patch("job.run_job")
    @patch.dict(os.environ, {}, clear=True)
    def test_refuses_to_run_without_sec_contact(self, mock_run):
        with self.assertRaises(SystemExit):
            job.main()

        mock_run.assert_not_called()

    @patch("job.run_job")
    @patch.dict(os.environ, {"SEC_CONTACT": "Test test@example.com"}, clear=True)
    def test_uses_the_default_cap_when_unset(self, mock_run):
        job.main()

        self.assertEqual(mock_run.call_args.kwargs["call_cap"], 1500)

    @patch("job.run_job")
    @patch.dict(os.environ, {"SEC_CONTACT": "Test test@example.com", "SCREENER_NIGHTLY_CALL_CAP": "300"}, clear=True)
    def test_reads_the_cap_from_the_environment(self, mock_run):
        job.main()

        self.assertEqual(mock_run.call_args.kwargs["call_cap"], 300)

    @patch("job.run_job")
    def test_rejects_a_bad_cap(self, mock_run):
        for bad in ("abc", "0", "-5"):
            with patch.dict(os.environ, {"SEC_CONTACT": "x y", "SCREENER_NIGHTLY_CALL_CAP": bad}, clear=True):
                with self.assertRaises(SystemExit):
                    job.main()

        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

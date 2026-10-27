import os
import sys
import tempfile
import unittest
from datetime import date

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "digest")):
    sys.path.insert(0, _p)

import backtest
import market_read
from heuristics import heuristic_for
from fetch_fred import FredApiError
from indicators_config import INDICATORS


def monthly(start_year, months, value):
    out = []
    for i in range(months):
        year, month = start_year + i // 12, i % 12 + 1
        out.append({"date": f"{year}-{month:02d}-01", "value": value(i)})
    return out


class TestWindow(unittest.TestCase):
    def test_a_window_never_holds_a_reading_published_after_the_evaluation_date(self):
        series = backtest.Series(monthly(2020, 24, lambda i: float(i)))
        lag = backtest.RELEASE_LAGS_DAYS["nonfarm_payrolls"]

        as_of = date(2021, 6, 30)
        history = backtest.window(series, "nonfarm_payrolls", as_of)

        self.assertTrue(history)
        for reading in history:
            published = date.fromisoformat(reading["date"]).toordinal() + lag
            self.assertLessEqual(published, as_of.toordinal())
        # June's reading is dated 1 June but not public until 8 July.
        self.assertNotIn("2021-06-01", [r["date"] for r in history])
        self.assertIn("2021-05-01", [r["date"] for r in history])

    def test_a_window_spans_the_production_twelve_months(self):
        series = backtest.Series(monthly(2018, 60, lambda i: float(i)))

        history = backtest.window(series, "unemployment_rate", date(2021, 6, 30))

        self.assertEqual(history[0]["date"], "2020-07-01")

    def test_production_reads_are_what_the_backtest_reproduces(self):
        series = {key: backtest.Series(monthly(2019, 36, lambda i, k=n: 100.0 + i * (1 + k % 3) + (i % 4)))
                  for n, key in enumerate(INDICATORS)}
        as_of = date(2021, 11, 30)
        context = backtest.build_context(series, as_of)

        record = backtest.run({as_of: context}, {})[0]
        direct = market_read.compute_market_read(context, as_of)

        self.assertEqual(record["groups"], {g: direct["groups"][g]["read"] for g in market_read.GROUPS})
        self.assertEqual(record["stance"], direct["policy"]["stance"])
        self.assertEqual(record["group_results"], direct["groups"])
        for entry in context:
            self.assertEqual(entry["heuristic"], heuristic_for(entry["key"], entry["history_window"]))

    def test_an_override_applies_inside_the_run_only(self):
        series = {key: backtest.Series(monthly(2019, 36, lambda i: float(i % 5))) for key in INDICATORS}
        as_of = date(2021, 11, 30)
        context = backtest.build_context(series, as_of)
        before = market_read.SIGNAL_Z

        backtest.run({as_of: context}, {}, {"SIGNAL_Z": 3.0})

        self.assertEqual(market_read.SIGNAL_Z, before)


class TestSweepAtProduction(unittest.TestCase):
    def setUp(self):
        series = {key: backtest.Series(monthly(2019, 36, lambda i, k=n: 100.0 + i * (1 + k % 3) + (i % 4)))
                  for n, key in enumerate(INDICATORS)}
        self.as_of = date(2021, 11, 30)
        self.contexts = {self.as_of: backtest.build_context(series, self.as_of)}

    def test_each_swept_constant_at_its_production_value_reproduces_the_base_run(self):
        base = backtest.run(self.contexts, {})
        for _, constant, _ in backtest.SWEEPS:
            with self.subTest(constant=constant):
                swept = backtest.run(self.contexts, {}, {constant: getattr(market_read, constant)})
                self.assertEqual(swept, base)

    def test_a_constant_is_restored_when_the_run_fails(self):
        before = market_read.SIGNAL_Z
        with self.assertRaises(RuntimeError):
            with backtest.patched({"SIGNAL_Z": 9.0}):
                self.assertEqual(market_read.SIGNAL_Z, 9.0)
                raise RuntimeError("boom")

        self.assertEqual(market_read.SIGNAL_Z, before)

    def test_every_series_has_a_release_lag(self):
        self.assertEqual(set(backtest.RELEASE_LAGS_DAYS), set(INDICATORS))

    def test_a_weekly_series_is_public_five_days_later(self):
        series = backtest.Series([{"date": "2021-06-05", "value": 1.0}, {"date": "2021-06-12", "value": 2.0}])

        history = backtest.window(series, "initial_jobless_claims", date(2021, 6, 16))

        self.assertEqual([r["date"] for r in history], ["2021-06-05"])


class TestRecessions(unittest.TestCase):
    def test_starts_are_the_first_month_of_each_run_from_the_first_evaluated_month(self):
        flags = {"1977-11": 1, "1977-12": 1, "1978-01": 0, "1978-02": 0, "1978-03": 1, "1978-04": 1,
                 "1978-05": 0, "1979-01": 1}

        self.assertEqual(backtest.recession_starts(flags), ["1978-03", "1979-01"])

    def test_lead_time_is_months_before_the_start_of_the_first_bad_label_in_the_window(self):
        rows = [("2000-%02d" % m, False, "neutral") for m in range(1, 13)]
        rows[5] = ("2000-06", False, "bad")   # 7 months before 2001-01
        rows[9] = ("2000-10", False, "bad")
        late = [("2001-01", True, "bad")]

        leads = backtest.lead_times(rows + late, ["2001-01"])

        self.assertEqual(leads, [7])

    def test_an_earlier_recessions_months_are_not_a_warning(self):
        rows = [("1999-%02d" % m, True, "bad") for m in range(7, 13)] + [("2000-%02d" % m, False, "neutral") for m in range(1, 13)]

        self.assertEqual(backtest.lead_times(rows, ["2001-01"]), [None])

    def test_the_window_is_eighteen_months_not_nineteen(self):
        inside = [("1999-07", False, "bad")]     # 18 months before 2001-01
        outside = [("1999-06", False, "bad")]    # 19 months before

        self.assertEqual(backtest.lead_times(inside, ["2001-01"]), [18])
        self.assertEqual(backtest.lead_times(outside, ["2001-01"]), [None])

    def test_the_chance_rate_counts_expansion_months_with_an_earlier_bad_label(self):
        rows = [("2000-01", False, "bad")] + [("2000-%02d" % m, False, "neutral") for m in range(2, 5)] + [("2002-01", False, "neutral")]

        self.assertAlmostEqual(backtest.lead_chance(rows), 3 / 5)

    def test_no_bad_label_inside_the_window_is_none(self):
        rows = [("1999-01", False, "bad")] + [("2000-%02d" % m, False, "neutral") for m in range(1, 13)]

        self.assertEqual(backtest.lead_times(rows, ["2001-01"]), [None])

    def test_month_ends_run_from_january_1978_through_the_last_month(self):
        ends = backtest.month_ends((1978, 3))

        self.assertEqual(ends, [date(1978, 1, 31), date(1978, 2, 28), date(1978, 3, 31)])


class TestMetrics(unittest.TestCase):
    def test_rates_split_recession_from_expansion_and_ignore_months_without_a_read(self):
        rows = [("2000-01", True, "bad"), ("2000-02", True, "bad"), ("2000-03", True, "good"), ("2000-04", True, None),
                ("2000-05", False, "bad"), ("2000-06", False, "neutral"), ("2000-07", False, "neutral"), ("2000-08", False, "neutral")]

        r = backtest.rates(rows)

        self.assertAlmostEqual(r["rec_bad"], 2 / 3)
        self.assertAlmostEqual(r["rec_good"], 1 / 3)
        self.assertAlmostEqual(r["exp_bad"], 0.25)
        self.assertEqual((r["rec_months"], r["exp_months"]), (3, 4))

    def test_empty_inputs_give_none_not_zero(self):
        self.assertIsNone(backtest.rates([])["rec_bad"])
        self.assertIsNone(backtest.share_after_starts([], ["2000-01"]))

    def test_share_after_a_start_counts_only_months_six_to_twelve_later(self):
        rows = [("2000-%02d" % m, True, "bad" if m in (7, 8) else "neutral") for m in range(1, 13)]

        self.assertAlmostEqual(backtest.share_after_starts(rows, ["2000-01"]), 2 / 6)

    def test_lead_lag_compares_with_the_chance_rate(self):
        earlier = [("2000-%02d" % m, False, "bad" if m in (1, 2) else "neutral") for m in range(1, 7)]
        later = [("2000-%02d" % m, False, "bad" if m in (3, 4) else "neutral") for m in range(1, 7)]

        r = backtest.lead_lag(earlier, later, 2, "bad")

        self.assertEqual(r["hit"], 1.0)
        self.assertAlmostEqual(r["base"], 2 / 6)
        self.assertEqual(r["n"], 2)

    def months_from(self, start, stances, funds=None, real=None):
        out = []
        for k, stance in enumerate(stances):
            index = backtest._index(start) + k
            out.append({"month": f"{index // 12:04d}-{index % 12 + 1:02d}", "stance": stance,
                        "policy": {"fed_funds": funds[k] if funds else 3.0, "real_rate": real[k] if real else 1.0}})
        return out

    def test_an_episode_is_reached_in_the_month_the_stance_starts_a_held_run_at_the_expected_level(self):
        records = self.months_from("2001-01", ["restrictive", "restrictive", "near neutral", "accommodative", "accommodative", "accommodative"])

        episode = backtest.episode_reach(records)[0]

        self.assertEqual((episode["label"], episode["reached"], episode["first_seen"], episode["in_data"]), ("2001 easing", 3, 3, True))

    def test_a_flicker_shorter_than_the_hold_is_first_seen_but_not_reached(self):
        records = self.months_from("2001-01", ["restrictive", "accommodative", "accommodative", "restrictive", "near neutral", "restrictive"] * 3)

        episode = backtest.episode_reach(records)[0]

        self.assertIsNone(episode["reached"])
        self.assertEqual(episode["first_seen"], 1)

    def test_a_run_that_starts_inside_the_window_may_continue_past_it(self):
        records = self.months_from("2001-01", ["restrictive"] * 11 + ["accommodative"] * 4)

        self.assertEqual(backtest.episode_reach(records)[0]["reached"], 11)

    def test_a_run_that_starts_after_the_window_is_not_reached(self):
        records = self.months_from("2001-01", ["restrictive"] * 13 + ["accommodative"] * 4)

        episode = backtest.episode_reach(records)[0]

        self.assertIsNone(episode["reached"])
        self.assertIsNone(episode["first_seen"])

    def test_the_reach_window_is_inclusive_of_month_twelve(self):
        records = self.months_from("2001-01", ["restrictive"] * 12 + ["accommodative"] * 3)

        self.assertEqual(backtest.episode_reach(records)[0]["reached"], 12)

    def test_an_episode_outside_the_data_is_marked_so(self):
        records = self.months_from("2010-01", ["restrictive"] * 3)

        self.assertFalse(any(e["in_data"] for e in backtest.episode_reach(records)))

    def test_zero_rate_months_that_are_not_accommodative_are_listed(self):
        records = self.months_from("2015-01", ["accommodative", "restrictive", "restrictive"], funds=[0.1, 0.2, 0.5])

        zero = backtest.zero_rate_months(records)

        self.assertEqual(zero["months"], 2)
        self.assertEqual(zero["misread"], ["2015-02"])

    def test_the_reference_comparison_reports_level_change_and_bias(self):
        months = [f"{1990 + i // 12}-{i % 12 + 1:02d}" for i in range(60)]
        reference = {m: 1.0 + 0.1 * i + (0.3 if i % 5 == 0 else 0) for i, m in enumerate(months)}
        records = [{"month": m, "stance": None, "policy": {"fed_funds": 3.0, "real_rate": reference[m] - 0.4}} for m in months]

        ref = backtest.reference_comparison(records, reference)

        self.assertAlmostEqual(ref["level"], 1.0)
        self.assertAlmostEqual(ref["change"], 1.0)
        self.assertAlmostEqual(ref["bias"], -0.4)
        self.assertEqual(ref["months"], 60)

    def test_pearson_needs_24_pairs_and_some_variation(self):
        self.assertIsNone(backtest._pearson(list(range(23)), list(range(23))))
        self.assertIsNone(backtest._pearson([1.0] * 30, list(range(30))))
        self.assertAlmostEqual(backtest._pearson(list(range(30)), list(range(30))), 1.0)
        self.assertAlmostEqual(backtest._pearson([None] + list(range(30)), [5] + list(range(30))), 1.0)

    def test_a_change_with_no_year_earlier_reading_is_skipped_not_counted(self):
        months = [f"{1990 + i // 12}-{i % 12 + 1:02d}" for i in range(40)]
        reference = {m: 1.0 + 0.1 * i + (0.3 if i % 5 == 0 else 0) for i, m in enumerate(months)}
        del reference[months[20]]
        records = [{"month": m, "stance": None, "policy": {"fed_funds": 3.0, "real_rate": 1.0 + 0.1 * i + (0.3 if i % 5 == 0 else 0)}}
                   for i, m in enumerate(months)]

        ref = backtest.reference_comparison(records, reference)

        self.assertEqual(ref["months"], 39)
        self.assertLess(ref["change_months"], ref["months"] - 12)
        self.assertAlmostEqual(ref["change"], 1.0)

    def test_months_before_the_reference_starts_are_left_out(self):
        records = [{"month": f"1979-{m:02d}", "stance": None, "policy": {"fed_funds": 3.0, "real_rate": 1.0}} for m in range(1, 13)]

        ref = backtest.reference_comparison(records, {})

        self.assertEqual((ref["months"], ref["level"], ref["bias"]), (0, None, None))

    def test_stance_criteria_are_met_or_not_from_the_records_and_the_reference(self):
        months = [f"{1982 + i // 12}-{i % 12 + 1:02d}" for i in range(480)]
        reference = {m: 1.0 + 0.1 * (i % 40) for i, m in enumerate(months)}
        records = [{"month": m, "stance": "accommodative", "policy": {"fed_funds": 0.1, "real_rate": reference[m]}} for m in months]

        results = backtest.evaluate_stance_criteria(records, reference)

        self.assertEqual(len(results), 7)
        self.assertIn("regression guard", results[0][0])
        self.assertTrue(results[0][1])
        self.assertTrue(all(met for _, met, _ in results[5:]))
        records[10]["stance"] = "restrictive"
        self.assertFalse(backtest.evaluate_stance_criteria(records, reference)[0][1])

    def test_the_stance_information_is_the_flip_rate_share_and_lift(self):
        months = [f"{1990 + i // 12}-{i % 12 + 1:02d}" for i in range(48)]
        records = [{"month": m, "stance": "restrictive" if i < 24 else "near neutral", "policy": {}} for i, m in enumerate(months)]
        recession = {months[30]: 1}

        info = backtest.stance_information(records, recession)

        self.assertAlmostEqual(info["flips_a_year"], 0.25)
        self.assertAlmostEqual(info["restrictive_share"], 24 / 47)
        self.assertIsNotNone(info["lift"])

    def test_criteria_report_a_failure_as_not_met(self):
        weak = {"rec_bad": 0.5, "exp_bad": 0.3, "rec_good": 0.0, "exp_good": 0.0, "rec_months": 10, "exp_months": 10}
        h = {"rates": {"leading": weak, "coincident": weak, "lagging": weak}, "leads": [3, None],
             "leading_warned": 1, "lead_chance": 0.5, "lagging_after": 0.2,
             "episodes": []}

        results = backtest.evaluate_criteria(h, 2)

        self.assertTrue(results)
        self.assertFalse(any(met for _, met, _ in results))

    def test_a_criterion_at_its_threshold_is_met(self):
        good = {"rec_bad": 0.70, "exp_bad": 0.15, "rec_good": 0.0, "exp_good": 0.0, "rec_months": 10, "exp_months": 10}
        leading = {**good, "exp_bad": 0.25}
        h = {"rates": {"leading": leading, "coincident": good, "lagging": good}, "leads": [1] * 5,
             "leading_warned": 5, "lead_chance": 0.5, "lagging_after": 0.60, "episodes": []}

        self.assertTrue(all(met for _, met, _ in backtest.evaluate_criteria(h, 6)))


class TestHeadlinePeriod(unittest.TestCase):
    def test_lead_times_look_back_across_the_period_edge_but_rates_do_not(self):
        records = [{"month": "2000-%02d" % m, "recession": False, "stance": None,
                    "groups": {"leading": "weakening", "coincident": None, "lagging": None}, "indicators": {}}
                   for m in range(1, 13)]
        records.append({"month": "2001-01", "recession": True, "stance": None,
                        "groups": {"leading": "mixed", "coincident": None, "lagging": None}, "indicators": {}})

        h = backtest.headline(records, ["2001-01"], ("2001-01", "9999-12"))

        self.assertEqual(h["leads"], [12])
        self.assertEqual(h["rates"]["leading"]["exp_months"], 0)


class TestRun(unittest.TestCase):
    def fetch(self, series_id, start_date=None):
        if series_id == "USREC":
            return monthly(1968, 12 * 59, lambda i: 1.0 if 1980 * 12 <= 1968 * 12 + i < 1980 * 12 + 6 else 0.0)
        if series_id == "FEDTARMDLR":
            return [{"date": "2026-09-16", "value": 3.2}]
        if series_id == "REAINTRATREARAT1YE":
            return monthly(1982, 12 * 45, lambda i: 1.0 + (i % 11) * 0.1)
        return monthly(1968, 12 * 59, lambda i: 100.0 + (i % 17) + i * 0.01)

    def test_the_report_has_every_section_and_the_production_values_marked(self):
        report = backtest.build_report(self.fetch)

        for heading in ("Pass criteria", "## Groups", "## Indicators", "Lead and lag", "## Policy stance",
                        "Neutral real rate", "Threshold sweeps"):
            self.assertIn(heading, report)
        self.assertIn("1.2%", report)
        self.assertIn("Cleveland Fed", report)
        self.assertNotIn("Policy stance through episodes", report)
        self.assertNotIn("in at least 50% of", report)
        self.assertIn("for 3 months in a row within 12 months of the 2001 easing", report)
        self.assertIn("regression guard", report)
        self.assertRegex(report, r"our real rate is [\d.]+ points (above|below) theirs")
        self.assertIn("Only the five group criteria were fixed before their first run", report)
        self.assertIn("0.5*", report)
        self.assertEqual(market_read.SIGNAL_Z, 0.5)

    def test_a_missing_reference_series_writes_no_report(self):
        def fetch(series_id, start_date=None):
            if series_id == "REAINTRATREARAT1YE":
                raise FredApiError("not found")
            return self.fetch(series_id, start_date)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.md")
            with self.assertLogs("backtest", level="ERROR"):
                code = backtest.main([path], fetch_fn=fetch)

            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(path))

    def test_a_fred_failure_writes_no_report(self):
        def failing(series_id, start_date=None):
            raise FredApiError("maintenance")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.md")
            with self.assertLogs("backtest", level="ERROR"):
                code = backtest.main([path], fetch_fn=failing)

            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(path))

    def test_a_good_run_writes_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.md")
            self.assertEqual(backtest.main([path], fetch_fn=self.fetch), 0)

            with open(path, encoding="utf-8") as f:
                self.assertIn("# Backtest of the indicator reads", f.read())


if __name__ == "__main__":
    unittest.main()

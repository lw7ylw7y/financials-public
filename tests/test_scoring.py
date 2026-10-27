import os
import sys
import unittest
from datetime import date, datetime, timezone

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener")):
    sys.path.insert(0, _p)

from scoring import (
    DEFAULT_SETTINGS,
    IMPROVED_SCORE_DELTA,
    FLAG_FEW_SHARE_YEARS,
    FLAG_IFRS,
    FLAG_NO_CAPEX,
    FLAG_NO_OPERATING_CASH_FLOW,
    FLAG_OLD_FIGURES,
    ScreenSettings,
    STAGE_NO_CIK,
    STAGE_NON_TECH,
    STAGE_TECH,
    build_candidate_record,
    classify_symbol,
    dismissal_snapshot,
    improved_since_dismissal,
    evaluate,
    extract_edgar_figures,
    is_stale,
    is_tech_sic,
    percentile_ranks,
    score_candidates,
)

TODAY = date(2026, 10, 19)


def _point(end, val, form="10-K", days=364, filed=None):
    start = date.fromisoformat(end).toordinal() - days
    return {"start": date.fromordinal(start).isoformat(), "end": end, "val": val, "form": form, "filed": filed or end}


def _facts(ocf=None, capex=None, shares=None, taxonomy="us-gaap", extra_gaap=None):
    gaap = {}
    if ocf is not None:
        gaap["NetCashProvidedByUsedInOperatingActivities"] = {"units": {"USD": [_point(e, v) for e, v in ocf.items()]}}
    if capex is not None:
        gaap["PaymentsToAcquirePropertyPlantAndEquipment"] = {"units": {"USD": [_point(e, v) for e, v in capex.items()]}}
    if shares is not None:
        gaap["WeightedAverageNumberOfSharesOutstandingBasic"] = {
            "units": {"shares": [_point(e, v) for e, v in shares.items()]}
        }
    gaap.update(extra_gaap or {})
    return {"facts": {taxonomy: gaap}}


GOOD_OCF = {"2023-12-31": 20e6, "2024-12-31": 30e6, "2025-12-31": 60e6}
GOOD_CAPEX = {"2023-12-31": 2e6, "2024-12-31": 3e6, "2025-12-31": 6e6}
GOOD_SHARES = {"2022-12-31": 40e6, "2023-12-31": 40.4e6, "2024-12-31": 40.8e6, "2025-12-31": 41.2e6}


class TestExtractEdgarFigures(unittest.TestCase):
    def test_free_cash_flow_is_operating_cash_flow_minus_capex_in_millions(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES), today=TODAY)

        self.assertEqual(figures["fcf_by_year"], {"2023-12-31": 18.0, "2024-12-31": 27.0, "2025-12-31": 54.0})
        self.assertEqual(figures["flags"], [])

    def test_keeps_only_the_last_three_years_of_cash_flow(self):
        ocf = {"2021-12-31": 1e6, **GOOD_OCF}
        capex = {"2021-12-31": 0.5e6, **GOOD_CAPEX}

        figures = extract_edgar_figures(_facts(ocf, capex, GOOD_SHARES), today=TODAY)

        self.assertEqual(sorted(figures["fcf_by_year"]), ["2023-12-31", "2024-12-31", "2025-12-31"])

    def test_dilution_is_annualized_share_growth(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES), today=TODAY)

        self.assertAlmostEqual(figures["dilution_pct_per_year"], 0.99, places=1)
        self.assertEqual(figures["shares_by_year"]["2025-12-31"], 41.2)

    def test_negative_dilution_from_buybacks(self):
        shares = {"2023-12-31": 50e6, "2024-12-31": 48e6, "2025-12-31": 46e6}

        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, shares), today=TODAY)

        self.assertLess(figures["dilution_pct_per_year"], 0)

    def test_missing_capex_is_flagged_and_gives_no_free_cash_flow(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, None, GOOD_SHARES), today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_NO_CAPEX])
        self.assertEqual(figures["fcf_by_year"], {})

    def test_capex_missing_for_the_latest_year_only_is_flagged(self):
        capex = {k: v for k, v in GOOD_CAPEX.items() if k != "2025-12-31"}

        figures = extract_edgar_figures(_facts(GOOD_OCF, capex, GOOD_SHARES), today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_NO_CAPEX])

    def test_missing_operating_cash_flow_is_flagged(self):
        figures = extract_edgar_figures(_facts(None, GOOD_CAPEX, GOOD_SHARES), today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_NO_OPERATING_CASH_FLOW])

    def test_fewer_than_two_years_of_shares_is_flagged(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, {"2025-12-31": 41e6}), today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_FEW_SHARE_YEARS])
        self.assertIsNone(figures["dilution_pct_per_year"])

    def test_share_count_jump_of_three_times_is_flagged_as_a_split(self):
        shares = {"2023-12-31": 10e6, "2024-12-31": 30e6, "2025-12-31": 31e6}

        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, shares), today=TODAY)

        self.assertEqual(len(figures["flags"]), 1)
        self.assertIn("Possible stock split", figures["flags"][0])
        self.assertIn("2024", figures["flags"][0])
        self.assertEqual(figures["shares_by_year"]["2024-12-31"], 30.0)
        self.assertTrue(evaluate(build_candidate_record(1, {"market_cap": 5000.0}, {"roi": 12.0, "net_margin": 8.0, "debt_to_equity": 0.1, "revenue_growth": 20.0}, figures), DEFAULT_SETTINGS, TODAY)["flagged"])

    def test_share_count_jump_just_under_three_times_is_not_a_split(self):
        shares = {"2023-12-31": 10e6, "2024-12-31": 29.9e6, "2025-12-31": 30e6}

        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, shares), today=TODAY)

        self.assertEqual(figures["flags"], [])

    def test_share_count_drop_to_a_third_or_less_is_flagged_as_a_reverse_split(self):
        shares = {"2023-12-31": 100e6, "2024-12-31": 10e6, "2025-12-31": 10.2e6}

        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, shares), today=TODAY)

        self.assertEqual(len(figures["flags"]), 1)
        self.assertIn("Possible reverse split", figures["flags"][0])
        self.assertIn("2024", figures["flags"][0])

    def test_a_share_count_drop_just_under_the_limit_is_a_buyback_not_a_split(self):
        shares = {"2023-12-31": 100e6, "2024-12-31": 34e6, "2025-12-31": 33e6}

        self.assertEqual(extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, shares), today=TODAY)["flags"], [])

    def test_figures_exactly_548_days_old_are_current_and_549_days_old_are_flagged(self):
        facts = _facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES)
        year_end = date(2025, 12, 31)

        on_the_limit = extract_edgar_figures(facts, today=date.fromordinal(year_end.toordinal() + 548))
        past_the_limit = extract_edgar_figures(facts, today=date.fromordinal(year_end.toordinal() + 549))

        self.assertEqual(on_the_limit["flags"], [])
        self.assertEqual(past_the_limit["flags"], [FLAG_OLD_FIGURES])

    def test_a_share_count_falling_to_exactly_a_third_is_a_reverse_split(self):
        shares = {"2023-12-31": 30e6, "2024-12-31": 10e6, "2025-12-31": 10e6}

        flags = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, shares), today=TODAY)["flags"]

        self.assertEqual(len(flags), 1)
        self.assertIn("Possible reverse split", flags[0])

    def test_amended_filings_are_read_for_every_annual_form(self):
        for form in ("10-K/A", "10-KT", "10-KT/A", "20-F/A", "40-F", "40-F/A"):
            facts = _facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES)
            for tag in facts["facts"]["us-gaap"].values():
                for point in tag["units"].get("USD", []) + tag["units"].get("shares", []):
                    point["form"] = form

            self.assertEqual(extract_edgar_figures(facts, today=TODAY)["flags"], [], form)

    def test_stale_annual_figures_are_flagged(self):
        old_ocf = {"2014-12-31": 20e6, "2015-12-31": 30e6, "2016-12-31": 60e6}
        old_capex = {"2014-12-31": 2e6, "2015-12-31": 3e6, "2016-12-31": 6e6}
        old_shares = {"2014-12-31": 40e6, "2015-12-31": 40.4e6, "2016-12-31": 40.8e6}

        figures = extract_edgar_figures(_facts(old_ocf, old_capex, old_shares), today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_OLD_FIGURES])

    def test_figures_under_eighteen_months_old_are_current(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES), today=date(2027, 3, 1))

        self.assertEqual(figures["flags"], [])

    def test_a_company_that_moved_to_ifrs_is_flagged_not_scored_on_old_us_gaap_data(self):
        facts = _facts({"2015-12-31": 30e6, "2016-12-31": 60e6}, {"2015-12-31": 3e6, "2016-12-31": 6e6},
                       {"2015-12-31": 40e6, "2016-12-31": 40.8e6})
        facts["facts"]["ifrs-full"] = {"CashFlowsFromUsedInOperatingActivities": {"units": {"EUR": [_point("2025-12-31", 5e6, form="20-F")]}}}

        figures = extract_edgar_figures(facts, today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_IFRS])
        self.assertEqual(figures["shares_by_year"]["2016-12-31"], 40.8)
        self.assertEqual(figures["fcf_by_year"]["2016-12-31"], 54.0)

    def test_a_us_gaap_company_with_an_unused_ifrs_section_is_not_flagged_as_ifrs(self):
        facts = _facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES)
        facts["facts"]["ifrs-full"] = {"Equity": {"units": {"USD": [_point("2020-12-31", 1.0, form="20-F")]}}}

        self.assertEqual(extract_edgar_figures(facts, today=TODAY)["flags"], [])

    def test_cash_flow_in_another_currency_is_flagged_with_that_reason(self):
        facts = _facts(None, None, GOOD_SHARES)
        facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"] = {
            "units": {"ILS": [_point("2025-12-31", 5e6)]}
        }

        flags = extract_edgar_figures(facts, today=TODAY)["flags"]

        self.assertEqual(flags, ["Cash flow reported in ILS, not scored yet"])

    def test_a_changed_capex_tag_keeps_the_history_of_both(self):
        facts = _facts(GOOD_OCF, {"2023-12-31": 2e6, "2024-12-31": 3e6}, GOOD_SHARES)
        facts["facts"]["us-gaap"]["PaymentsToAcquireProductiveAssets"] = {"units": {"USD": [_point("2025-12-31", 6e6)]}}

        figures = extract_edgar_figures(facts, today=TODAY)

        self.assertEqual(figures["flags"], [])
        self.assertEqual(figures["fcf_by_year"]["2025-12-31"], 54.0)

    def test_the_continuing_operations_cash_flow_tag_is_read(self):
        facts = _facts(None, GOOD_CAPEX, GOOD_SHARES)
        facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"] = {
            "units": {"USD": [_point(e, v) for e, v in GOOD_OCF.items()]}
        }

        self.assertEqual(extract_edgar_figures(facts, today=TODAY)["flags"], [])

    def test_ifrs_filer_is_flagged_not_scored(self):
        facts = {"facts": {"ifrs-full": {"CashFlowsFromUsedInOperatingActivities": {}}}}

        figures = extract_edgar_figures(facts, today=TODAY)

        self.assertEqual(figures["flags"], [FLAG_IFRS])
        self.assertEqual(figures["fcf_by_year"], {})

    def test_20f_and_40f_filings_are_read_like_10k(self):
        ocf = {e: v for e, v in GOOD_OCF.items()}
        facts = _facts(ocf, GOOD_CAPEX, GOOD_SHARES)
        for tag in facts["facts"]["us-gaap"].values():
            for unit in tag["units"].values():
                for point in unit:
                    point["form"] = "20-F"

        self.assertEqual(extract_edgar_figures(facts, today=TODAY)["flags"], [])

    def test_quarterly_points_are_ignored(self):
        facts = _facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES)
        facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"].append(
            _point("2026-03-31", 9e9, form="10-Q", days=90)
        )

        figures = extract_edgar_figures(facts, today=TODAY)

        self.assertNotIn("2026-03-31", figures["fcf_by_year"])

    def test_an_amendment_overrides_the_original_for_the_same_year(self):
        facts = _facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES)
        facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"].append(
            _point("2025-12-31", 70e6, form="10-K/A", filed="2026-06-01")
        )

        self.assertEqual(extract_edgar_figures(facts, today=TODAY)["fcf_by_year"]["2025-12-31"], 64.0)


def _record(**overrides):
    record = {
        "name": "Acme", "cik": 1, "ipo_date": "2021-02-18", "market_cap": 5000.0,
        "metrics": {"roi": 12.0, "roe": 12.0, "net_margin": 8.0, "debt_to_equity": 0.2, "eps_growth": 5.0},
        "revenue_growth": 20.0, "fcf_by_year": {"2024-12-31": 5.0, "2025-12-31": 10.0},
        "dilution_pct_per_year": 1.0, "flags": [],
    }
    record.update(overrides)
    return record


def _with_metrics(**metrics):
    base = {"roi": 12.0, "roe": 12.0, "net_margin": 8.0, "debt_to_equity": 0.2, "eps_growth": 5.0}
    base.update(metrics)
    return _record(metrics=base)


class TestEvaluate(unittest.TestCase):
    def test_a_good_record_passes_every_filter(self):
        result = evaluate(_record(), DEFAULT_SETTINGS, TODAY)

        self.assertTrue(result["passes"])
        self.assertFalse(result["flagged"])
        self.assertEqual(
            set(result["checks"]), {"market_cap", "net_margin", "free_cash_flow", "debt_equity", "dilution", "roi", "not_stale"}
        )

    def test_market_cap_band_edges_are_inclusive(self):
        self.assertTrue(evaluate(_record(market_cap=1200.0), today=TODAY)["checks"]["market_cap"])
        self.assertTrue(evaluate(_record(market_cap=22700.0), today=TODAY)["checks"]["market_cap"])
        self.assertFalse(evaluate(_record(market_cap=1199.9), today=TODAY)["checks"]["market_cap"])
        self.assertFalse(evaluate(_record(market_cap=22700.1), today=TODAY)["checks"]["market_cap"])

    def test_net_margin_must_be_strictly_above_zero(self):
        self.assertFalse(evaluate(_with_metrics(net_margin=0.0), today=TODAY)["checks"]["net_margin"])
        self.assertTrue(evaluate(_with_metrics(net_margin=0.1), today=TODAY)["checks"]["net_margin"])

    def test_free_cash_flow_uses_the_latest_year_and_must_be_above_zero(self):
        negative_latest = _record(fcf_by_year={"2024-12-31": 50.0, "2025-12-31": -1.0})
        zero_latest = _record(fcf_by_year={"2025-12-31": 0.0})

        self.assertFalse(evaluate(negative_latest, today=TODAY)["checks"]["free_cash_flow"])
        self.assertFalse(evaluate(zero_latest, today=TODAY)["checks"]["free_cash_flow"])

    def test_debt_equity_at_the_limit_passes_and_above_fails(self):
        self.assertTrue(evaluate(_with_metrics(debt_to_equity=0.5), today=TODAY)["checks"]["debt_equity"])
        self.assertFalse(evaluate(_with_metrics(debt_to_equity=0.51), today=TODAY)["checks"]["debt_equity"])

    def test_dilution_at_the_limit_passes_and_above_fails(self):
        self.assertTrue(evaluate(_record(dilution_pct_per_year=5.0), today=TODAY)["checks"]["dilution"])
        self.assertFalse(evaluate(_record(dilution_pct_per_year=5.01), today=TODAY)["checks"]["dilution"])

    def test_roi_at_the_limit_passes_and_below_fails(self):
        self.assertTrue(evaluate(_with_metrics(roi=5.0), today=TODAY)["checks"]["roi"])
        self.assertFalse(evaluate(_with_metrics(roi=4.9), today=TODAY)["checks"]["roi"])

    def test_a_missing_figure_fails_its_filter(self):
        self.assertFalse(evaluate(_with_metrics(roi=None), today=TODAY)["checks"]["roi"])
        self.assertFalse(evaluate(_with_metrics(debt_to_equity=None), today=TODAY)["checks"]["debt_equity"])
        self.assertFalse(evaluate(_with_metrics(net_margin=None), today=TODAY)["checks"]["net_margin"])
        self.assertFalse(evaluate(_record(dilution_pct_per_year=None), today=TODAY)["checks"]["dilution"])
        self.assertFalse(evaluate(_record(fcf_by_year={}), today=TODAY)["checks"]["free_cash_flow"])
        self.assertFalse(evaluate(_record(market_cap=None), today=TODAY)["checks"]["market_cap"])

    def test_a_flagged_record_never_passes_whatever_its_numbers(self):
        result = evaluate(_record(flags=["Capex not reported"]), DEFAULT_SETTINGS, TODAY)

        self.assertTrue(result["flagged"])
        self.assertFalse(result["passes"])

    def test_switching_a_filter_off_removes_it_from_the_checks(self):
        settings = ScreenSettings(min_roi_pct=None, stale_years=None)

        result = evaluate(_with_metrics(roi=-50.0), settings, TODAY)

        self.assertNotIn("roi", result["checks"])
        self.assertNotIn("not_stale", result["checks"])
        self.assertTrue(result["passes"])

    def test_a_custom_threshold_changes_the_answer(self):
        loose = ScreenSettings(max_debt_equity=1.0)

        self.assertTrue(evaluate(_with_metrics(debt_to_equity=0.8), loose, TODAY)["passes"])
        self.assertFalse(evaluate(_with_metrics(debt_to_equity=0.8), DEFAULT_SETTINGS, TODAY)["passes"])


class TestIsStale(unittest.TestCase):
    def test_long_listed_with_low_growth_is_stale(self):
        self.assertTrue(is_stale(_record(ipo_date="2005-01-01", revenue_growth=9.9), today=TODAY))

    def test_long_listed_with_growth_at_the_minimum_is_not_stale(self):
        self.assertFalse(is_stale(_record(ipo_date="2005-01-01", revenue_growth=10.0), today=TODAY))

    def test_recently_listed_with_low_growth_is_not_stale(self):
        self.assertFalse(is_stale(_record(ipo_date="2021-02-18", revenue_growth=-5.0), today=TODAY))

    def test_listed_exactly_ten_years_counts(self):
        self.assertTrue(is_stale(_record(ipo_date="2016-10-18", revenue_growth=0.0), today=TODAY))
        self.assertFalse(is_stale(_record(ipo_date="2016-10-25", revenue_growth=0.0), today=TODAY))

    def test_missing_listing_date_or_growth_is_not_stale(self):
        self.assertFalse(is_stale(_record(ipo_date=None, revenue_growth=0.0), today=TODAY))
        self.assertFalse(is_stale(_record(ipo_date="2005-01-01", revenue_growth=None), today=TODAY))

    def test_an_unreadable_listing_date_is_not_stale(self):
        self.assertFalse(is_stale(_record(ipo_date="not a date", revenue_growth=0.0), today=TODAY))

    def test_off_when_years_is_none(self):
        self.assertFalse(is_stale(_record(ipo_date="2005-01-01", revenue_growth=0.0), ScreenSettings(stale_years=None), TODAY))


class TestPercentileRanks(unittest.TestCase):
    def test_orders_from_zero_to_one_hundred(self):
        self.assertEqual(percentile_ranks([30, 10, 20]), [100.0, 0.0, 50.0])

    def test_ties_share_the_average_position(self):
        self.assertEqual(percentile_ranks([1, 2, 2, 3]), [0.0, 50.0, 50.0, 100.0])

    def test_all_equal_values_rank_the_same(self):
        self.assertEqual(percentile_ranks([5, 5, 5]), [50.0, 50.0, 50.0])

    def test_a_single_value_ranks_fifty(self):
        self.assertEqual(percentile_ranks([7]), [50.0])


class TestScoreCandidates(unittest.TestCase):
    def _records(self):
        return {
            "BEST": _record(
                metrics={"roi": 30.0, "roe": 1, "net_margin": 20.0, "debt_to_equity": 0.0, "eps_growth": 1},
                revenue_growth=40.0, dilution_pct_per_year=-1.0,
            ),
            "MID": _record(
                metrics={"roi": 15.0, "roe": 1, "net_margin": 10.0, "debt_to_equity": 0.2, "eps_growth": 1},
                revenue_growth=20.0, dilution_pct_per_year=2.0,
            ),
            "LOW": _record(
                metrics={"roi": 6.0, "roe": 1, "net_margin": 2.0, "debt_to_equity": 0.4, "eps_growth": 1},
                revenue_growth=11.0, dilution_pct_per_year=4.0,
            ),
        }

    def test_best_on_every_measure_scores_one_hundred_and_worst_zero(self):
        scores = score_candidates(self._records(), DEFAULT_SETTINGS, TODAY)

        self.assertEqual(scores["BEST"], 100.0)
        self.assertEqual(scores["MID"], 50.0)
        self.assertEqual(scores["LOW"], 0.0)

    def test_a_name_that_fails_a_filter_has_no_score_and_is_not_ranked(self):
        records = self._records()
        records["BAD"] = _with_metrics(roi=1.0)

        scores = score_candidates(records, DEFAULT_SETTINGS, TODAY)

        self.assertNotIn("BAD", scores)
        self.assertEqual(scores["BEST"], 100.0)

    def test_flagged_names_are_not_scored(self):
        records = self._records()
        records["FLAGGED"] = _record(flags=["Capex not reported"])

        self.assertNotIn("FLAGGED", score_candidates(records, DEFAULT_SETTINGS, TODAY))

    def test_missing_revenue_growth_ranks_worst_on_that_measure(self):
        records = self._records()
        records["NOGROWTH"] = _record(
            metrics={"roi": 30.0, "roe": 1, "net_margin": 20.0, "debt_to_equity": 0.0, "eps_growth": 1},
            revenue_growth=None, dilution_pct_per_year=-1.0, ipo_date=None,
        )

        scores = score_candidates(records, DEFAULT_SETTINGS, TODAY)

        self.assertLess(scores["NOGROWTH"], scores["BEST"])

    def test_a_filter_switched_off_with_that_figure_missing_ranks_it_worst_instead_of_crashing(self):
        records = self._records()
        records["NODE"] = _record(
            metrics={"roi": 30.0, "roe": 1, "net_margin": 20.0, "debt_to_equity": None, "eps_growth": 1},
            revenue_growth=40.0, dilution_pct_per_year=-1.0,
        )
        settings = ScreenSettings(max_debt_equity=None)

        scores = score_candidates(records, settings, TODAY)

        self.assertIn("NODE", scores)
        self.assertLess(scores["NODE"], 100.0)

    def test_every_filter_off_and_every_figure_missing_still_scores(self):
        bare = _record(
            metrics={"roi": None, "roe": None, "net_margin": None, "debt_to_equity": None, "eps_growth": None},
            revenue_growth=None, dilution_pct_per_year=None, fcf_by_year={},
        )
        settings = ScreenSettings(
            net_margin_min=None, fcf_min_m=None, max_debt_equity=None, max_dilution_pct=None, min_roi_pct=None, stale_years=None
        )

        self.assertEqual(score_candidates({"BARE": bare, "OTHER": _record()}, settings, TODAY)["BARE"], 0.0)

    def test_a_record_missing_keys_ranks_worst_instead_of_raising(self):
        records = self._records()
        records["SPARSE"] = {"flags": [], "market_cap": 5000.0}
        settings = ScreenSettings(
            net_margin_min=None, fcf_min_m=None, max_debt_equity=None, max_dilution_pct=None, min_roi_pct=None, stale_years=None
        )

        self.assertEqual(score_candidates(records, settings, TODAY)["SPARSE"], 0.0)

    def test_one_passing_candidate_scores_fifty(self):
        self.assertEqual(score_candidates({"ONLY": _record()}, DEFAULT_SETTINGS, TODAY), {"ONLY": 50.0})

    def test_no_candidates_gives_an_empty_result(self):
        self.assertEqual(score_candidates({}, DEFAULT_SETTINGS, TODAY), {})
        self.assertEqual(score_candidates({"BAD": _with_metrics(roi=0.0)}, DEFAULT_SETTINGS, TODAY), {})

    def test_loosening_a_filter_brings_a_name_into_the_ranking(self):
        records = self._records()
        records["NEW"] = _with_metrics(debt_to_equity=0.8)

        self.assertNotIn("NEW", score_candidates(records, DEFAULT_SETTINGS, TODAY))
        self.assertIn("NEW", score_candidates(records, ScreenSettings(max_debt_equity=1.0), TODAY))


class TestDismissalSnapshot(unittest.TestCase):
    def test_a_passing_name_records_its_score(self):
        records = {"A": _record(), "B": _record(metrics={"roi": 40.0, "roe": 1, "net_margin": 30.0, "debt_to_equity": 0.0, "eps_growth": 1})}

        snapshot = dismissal_snapshot("A", records, today=TODAY)

        self.assertTrue(snapshot["passed_at_dismissal"])
        self.assertEqual(snapshot["score_at_dismissal"], score_candidates(records, today=TODAY)["A"])

    def test_a_failing_or_flagged_name_has_no_score_and_did_not_pass(self):
        failing = _record(metrics={"roi": 1.0, "roe": 1, "net_margin": 5.0, "debt_to_equity": 0.1, "eps_growth": 1})
        flagged = _record(flags=["Capex not reported"])

        for record in (failing, flagged):
            snapshot = dismissal_snapshot("X", {"X": record}, today=TODAY)
            self.assertEqual(snapshot, {"score_at_dismissal": None, "passed_at_dismissal": False})


class TestImprovedSinceDismissal(unittest.TestCase):
    def test_a_rise_of_exactly_the_delta_is_improved_and_just_below_is_not(self):
        status = {"passed_at_dismissal": True, "score_at_dismissal": 60.0}

        self.assertTrue(improved_since_dismissal(status, True, 60.0 + IMPROVED_SCORE_DELTA))
        self.assertFalse(improved_since_dismissal(status, True, 60.0 + IMPROVED_SCORE_DELTA - 0.1))

    def test_a_name_that_did_not_pass_then_and_passes_now_is_improved(self):
        self.assertTrue(improved_since_dismissal({"passed_at_dismissal": False, "score_at_dismissal": None}, True, 50.0))

    def test_a_name_that_still_fails_is_never_improved(self):
        self.assertFalse(improved_since_dismissal({"passed_at_dismissal": False}, False, None))
        self.assertFalse(improved_since_dismissal({"passed_at_dismissal": True, "score_at_dismissal": 10.0}, False, None))

    def test_a_name_that_passed_then_with_no_recorded_score_cannot_be_compared(self):
        self.assertFalse(improved_since_dismissal({"passed_at_dismissal": True}, True, 90.0))


class TestBuildCandidateRecord(unittest.TestCase):
    def test_stores_raw_numbers_and_no_pass_fail_or_score(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES), today=TODAY)
        profile = {"name": "Viant", "market_cap": 851.2, "ipo_date": "2021-02-18"}
        metrics = {
            "low": 8.0, "high": 15.0, "market_cap": 900.0, "pe_ratio": 20.0, "peg_ratio": 1.5,
            "roi": 11.4, "roe": 11.0, "net_margin": 2.2, "debt_to_equity": 0.0,
            "eps_growth": 3.0, "revenue_growth": 22.0,
        }
        now = datetime(2026, 10, 19, 5, 30, tzinfo=timezone.utc)

        record = build_candidate_record(1234, profile, metrics, figures, now)

        self.assertEqual(record["name"], "Viant")
        self.assertEqual(record["cik"], 1234)
        self.assertEqual(record["ipo_date"], "2021-02-18")
        self.assertEqual(record["market_cap"], 851.2)
        self.assertEqual(record["metrics"]["roi"], 11.4)
        self.assertEqual(record["revenue_growth"], 22.0)
        self.assertEqual(record["fcf_by_year"], figures["fcf_by_year"])
        self.assertEqual(record["shares_by_year"], figures["shares_by_year"])
        self.assertEqual(record["market_at"], record["scored_at"])
        self.assertTrue(record["market_at"].startswith("2026-10-19"))
        self.assertNotIn("score", record)
        self.assertNotIn("filters_passed", record)

    def test_a_company_without_a_52_week_range_still_builds_and_evaluates(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES), today=TODAY)
        profile = {"name": "Tiny", "market_cap": 2000.0, "ipo_date": "2022-05-01"}
        metrics = {
            "low": None, "high": None, "market_cap": None, "pe_ratio": None, "peg_ratio": None,
            "roi": 9.0, "roe": 9.0, "net_margin": 4.0, "debt_to_equity": 0.1,
            "eps_growth": None, "revenue_growth": 15.0,
        }

        record = build_candidate_record(7, profile, metrics, figures)

        self.assertIsNone(record["week52_low"])
        self.assertTrue(evaluate(record, DEFAULT_SETTINGS, TODAY)["passes"])

    def test_market_cap_falls_back_to_the_metrics_value(self):
        figures = extract_edgar_figures(_facts(GOOD_OCF, GOOD_CAPEX, GOOD_SHARES), today=TODAY)

        record = build_candidate_record(
            7, {"name": "X", "market_cap": None, "ipo_date": None},
            {"low": 1.0, "high": 2.0, "market_cap": 300.0, "roi": 6.0}, figures,
        )

        self.assertEqual(record["market_cap"], 300.0)

    def test_a_flagged_company_keeps_its_flags_and_does_not_pass(self):
        figures = extract_edgar_figures({"facts": {"ifrs-full": {}}}, today=TODAY)

        record = build_candidate_record(7, {"name": "Globant", "market_cap": 1700.0, "ipo_date": "2014-07-24"}, {"roi": 6.0}, figures)

        self.assertEqual(record["flags"], [FLAG_IFRS])
        self.assertFalse(evaluate(record, DEFAULT_SETTINGS, TODAY)["passes"])


class TestClassifySymbol(unittest.TestCase):
    def test_no_cik_wins_over_any_sic(self):
        self.assertEqual(classify_symbol(None, 3674), STAGE_NO_CIK)
        self.assertEqual(classify_symbol(None, None), STAGE_NO_CIK)

    def test_tech_sic_is_tech(self):
        self.assertEqual(classify_symbol(1851961, 3674), STAGE_TECH)

    def test_other_or_missing_sic_is_non_tech(self):
        self.assertEqual(classify_symbol(1, 2834), STAGE_NON_TECH)
        self.assertEqual(classify_symbol(1, None), STAGE_NON_TECH)


class TestIsTechSic(unittest.TestCase):
    def test_tech_codes(self):
        for sic in (3674, 7372, 3661, 3577, 3825):
            self.assertTrue(is_tech_sic(sic), sic)

    def test_non_tech_and_missing_codes(self):
        for sic in (2834, 6021, 1311, None):
            self.assertFalse(is_tech_sic(sic), sic)


if __name__ == "__main__":
    unittest.main()

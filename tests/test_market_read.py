import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "digest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "fred"))

import market_read
from market_read import compute_market_read, indicator_stats

START = date(2026, 1, 1)


def monthly(values):
    return [
        {"date": (START + timedelta(days=30 * i)).isoformat(), "value": v}
        for i, v in enumerate(values)
    ]


def ctx(key, category, values, heuristic=None):
    return {
        "key": key,
        "name": key,
        "category": category,
        "history_window": monthly(values),
        "heuristic": heuristic,
    }


RISING = [4.0 + 0.1 * i for i in range(12)]
INVERTED = [0.5 - 0.1 * i for i in range(12)]  # falls from +0.5 to -0.6
FALLING = list(reversed(RISING))
FLAT = [4.0] * 12
ACCELERATING_PRICES = [100 * 1.001 ** (i * (i + 1) / 2) for i in range(12)]  # inflation speeding up


class TestIndicatorStats(unittest.TestCase):
    def test_rising_series_is_unfavorable_when_lower_is_better(self):
        stats = indicator_stats(monthly(RISING), "lower")
        self.assertEqual(stats["classification"], "unfavorable")
        self.assertEqual(stats["trend"], "rising")
        self.assertEqual(stats["latest"], RISING[-1])
        self.assertGreater(stats["percentile"], 90)
        self.assertGreater(stats["z"], 1)

    def test_same_series_is_favorable_when_higher_is_better(self):
        self.assertEqual(indicator_stats(monthly(RISING), "higher")["classification"], "favorable")

    def test_falling_series_is_favorable_when_lower_is_better(self):
        self.assertEqual(indicator_stats(monthly(FALLING), "lower")["classification"], "favorable")

    def test_flat_series_has_zero_variance_and_is_neutral(self):
        stats = indicator_stats(monthly(FLAT), "higher")
        self.assertEqual(stats["classification"], "neutral")
        self.assertEqual(stats["z"], 0.0)
        self.assertEqual(stats["trend"], "flat")

    def test_no_favorable_direction_is_context_not_scored(self):
        self.assertEqual(indicator_stats(monthly(RISING), None)["classification"], "context")

    def test_too_few_readings_is_insufficient(self):
        stats = indicator_stats(monthly([4.0, 4.1, 4.2]), "lower")
        self.assertEqual(stats["classification"], "insufficient")
        self.assertIsNone(stats["z"])

    def test_changes_over_1_3_6_months(self):
        stats = indicator_stats(monthly(RISING), "lower")
        self.assertAlmostEqual(stats["change_1m"], 0.1, places=3)
        self.assertAlmostEqual(stats["change_3m"], 0.3, places=3)
        self.assertAlmostEqual(stats["change_6m"], 0.6, places=3)

    def test_change_is_none_when_history_does_not_reach_back(self):
        stats = indicator_stats(monthly(RISING[:3]), "lower")
        self.assertIsNotNone(stats["change_1m"])
        self.assertIsNone(stats["change_6m"])

    def test_signal_threshold_boundary(self):
        # Recent readings sit exactly at the window mean: below the threshold.
        values = [4.0, 4.2] * 6
        self.assertEqual(indicator_stats(monthly(values), "lower")["classification"], "neutral")

    def test_cumulative_series_is_read_as_percent_changes(self):
        # A steadily growing level would look "favorable" as a level; as
        # constant growth it is neutral.
        level = [100 * 1.003**i for i in range(12)]
        stats = indicator_stats(monthly(level), "higher", kind="change")
        self.assertEqual(stats["classification"], "neutral")

    def test_cumulative_series_slowing_growth_is_unfavorable(self):
        level = [100.0]
        for rate in [0.5] * 8 + [0.1] * 4:
            level.append(level[-1] * (1 + rate / 100))
        stats = indicator_stats(monthly(level), "higher", kind="change")
        self.assertEqual(stats["classification"], "unfavorable")

    def test_sahm_rule_trigger_forces_unfavorable(self):
        stats = indicator_stats(monthly(FLAT), "lower", heuristic={"sahm_rule_value": 0.5})
        self.assertEqual(stats["classification"], "unfavorable")
        self.assertIn("Sahm", stats["reason"])

    def test_a_curve_inverted_anywhere_in_the_window_is_unfavorable(self):
        for values in (INVERTED, [-0.1] + [1.0] * 11, [1.0] * 11 + [-0.1]):
            with self.subTest(values=values):
                stats = indicator_stats(monthly(values), "higher", kind="inversion")
                self.assertEqual(stats["classification"], "unfavorable")
                self.assertIn("lowest", stats["reason"])

    def test_a_curve_never_below_zero_is_neutral_never_favorable(self):
        for values in (RISING, FALLING, [0.0] * 12, [1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]):
            with self.subTest(values=values):
                stats = indicator_stats(monthly(values), "higher", kind="inversion")
                self.assertEqual(stats["classification"], "neutral")

    def test_a_curve_with_too_little_history_is_insufficient(self):
        stats = indicator_stats(monthly([-0.5, -0.4]), "higher", kind="inversion")
        self.assertEqual(stats["classification"], "insufficient")

    def test_untriggered_heuristics_do_not_change_the_classification(self):
        stats = indicator_stats(monthly(RISING), "higher", heuristic={"sahm_rule_value": 0.1})
        self.assertEqual(stats["classification"], "favorable")


class TestBoundaries(unittest.TestCase):
    def series(self, recent_level):
        """12 monthly readings, nine at 4.0 and three at `recent_level`
        (the last 90 days), so recent_z depends only on `recent_level`."""
        return monthly([4.0] * 9 + [recent_level] * 3)

    def test_just_past_the_signal_threshold_is_classified(self):
        # A step in the last quarter of any size is far past SIGNAL_Z once
        # measured in the window's own standard deviations.
        self.assertEqual(indicator_stats(self.series(4.1), "higher")["classification"], "favorable")
        self.assertEqual(indicator_stats(self.series(3.9), "higher")["classification"], "unfavorable")

    def test_below_the_signal_threshold_is_neutral(self):
        # An old blip leaves the last 90 days within half a standard
        # deviation of the window mean.
        values = [4.0] * 2 + [4.4] + [4.0] * 9
        stats = indicator_stats(monthly(values), "higher")
        self.assertLess(abs(stats["recent_z"]), market_read.SIGNAL_Z)
        self.assertEqual(stats["classification"], "neutral")

    def test_trend_veto_makes_a_good_level_neutral_when_it_is_turning(self):
        # High for the year, then clearly rolling over in the last 90 days.
        values = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 4.6, 4.2, 3.8, 3.4]
        stats = indicator_stats(monthly(values), "lower")
        # Recent readings sit below the window mean (favorable for "lower")
        # and the trend is falling (also favorable): classified favorable.
        self.assertEqual(stats["classification"], "favorable")
        # The same shape reversed: recent readings above the mean for a
        # "lower is better" series but the trend falling gives a veto.
        veto = [3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 5.0, 4.6, 4.2, 3.8]
        vetoed = indicator_stats(monthly(veto), "lower")
        self.assertGreater(vetoed["recent_z"], market_read.SIGNAL_Z)
        self.assertEqual(vetoed["trend"], "falling")
        self.assertEqual(vetoed["classification"], "neutral")

    def test_too_few_recent_readings_is_insufficient(self):
        # Quarterly readings 100 days apart: at most one falls in 90 days.
        history = [
            {"date": (START + timedelta(days=100 * i)).isoformat(), "value": 4.0 + 0.1 * i}
            for i in range(8)
        ]
        stats = indicator_stats(history, "higher")
        self.assertEqual(stats["classification"], "insufficient")
        self.assertIn("recent readings", stats["reason"])

    def test_a_group_needs_two_scored_indicators_for_a_read(self):
        one = [ctx("building_permits", "leading", RISING)]
        two = one + [ctx("initial_jobless_claims", "leading", FALLING)]

        self.assertIsNone(compute_market_read(one)["groups"]["leading"]["read"])
        self.assertEqual(compute_market_read(two)["groups"]["leading"]["read"], "improving")

    def test_group_read_thresholds(self):
        # Equal weights: one favorable and one neutral is +0.5 (improving); one favorable, one
        # neutral and one unfavorable is 0 (neutral); the line is READ_THRESHOLD.
        favorable = ctx("building_permits", "leading", RISING)
        neutral = ctx("initial_jobless_claims", "leading", FLAT)
        unfavorable = ctx("yield_curve_spread", "leading", INVERTED)
        self.assertEqual(compute_market_read([favorable, neutral])["groups"]["leading"]["read"], "improving")
        self.assertEqual(compute_market_read([favorable, neutral, unfavorable])["groups"]["leading"]["read"], "mixed")
        self.assertEqual(compute_market_read([neutral, unfavorable])["groups"]["leading"]["read"], "weakening")


def groups(**reads):
    return {g: {"read": reads.get(g), "score": 0.0, "scored": 2, "total": 2} for g in market_read.GROUPS}


class TestPersistence(unittest.TestCase):
    def read(self, now, earlier):
        from unittest import mock
        with mock.patch.object(market_read, "_read_groups",
                               side_effect=[({}, groups(leading=now)), ({}, groups(leading=earlier))]):
            return compute_market_read([ctx("building_permits", "leading", RISING)])["groups"]["leading"]["read"]

    def test_a_directional_read_stands_when_the_earlier_read_agrees(self):
        self.assertEqual(self.read("weakening", "weakening"), "weakening")
        self.assertEqual(self.read("improving", "improving"), "improving")

    def test_a_directional_read_that_the_earlier_read_does_not_confirm_is_mixed(self):
        for earlier in ("mixed", "improving"):
            self.assertEqual(self.read("weakening", earlier), "mixed")
        self.assertEqual(self.read("improving", "weakening"), "mixed")

    def test_with_no_earlier_read_todays_read_stands(self):
        self.assertEqual(self.read("weakening", None), "weakening")

    def test_a_mixed_or_missing_read_is_unchanged(self):
        self.assertEqual(self.read("mixed", "weakening"), "mixed")
        self.assertIsNone(self.read(None, "weakening"))

    def test_the_earlier_read_uses_the_history_up_to_thirty_days_before_the_latest_reading(self):
        history = monthly(RISING)
        earlier = market_read._context_as_of(
            [{"key": "building_permits", "name": "x", "category": "leading", "history_window": history, "heuristic": None}],
            date.fromisoformat(history[-1]["date"]) - timedelta(days=market_read.PERSISTENCE_DAYS),
        )

        self.assertEqual(len(earlier[0]["history_window"]), 11)

    def test_a_reading_is_known_from_the_day_it_was_fetched_not_the_day_it_is_dated(self):
        history = [{"date": "2026-04-01", "value": 1.0, "fetched_at": "2026-05-06T10:00:00+00:00"},
                   {"date": "2026-05-01", "value": 2.0, "fetched_at": "2026-06-05T10:00:00+00:00"}]
        entry = {"key": "nonfarm_payrolls", "name": "x", "category": "coincident", "history_window": history, "heuristic": None}

        earlier = market_read._context_as_of([entry], date(2026, 5, 31))

        self.assertEqual([r["date"] for r in earlier[0]["history_window"]], ["2026-04-01"])

    def test_an_indicator_with_no_history_that_early_is_dropped(self):
        late = [{"date": "2026-06-01", "value": 1.0}]
        earlier = market_read._context_as_of(
            [{"key": "building_permits", "name": "x", "category": "leading", "history_window": late, "heuristic": None}],
            date(2026, 5, 1),
        )

        self.assertEqual(earlier, [])

    def test_the_sahm_value_is_recomputed_for_the_earlier_history(self):
        values = [3.5] * 11 + [4.5]
        history = monthly(values)
        entry = {"key": "unemployment_rate", "name": "x", "category": "coincident", "history_window": history,
                 "heuristic": {"sahm_rule_value": 0.33}}
        earlier = market_read._context_as_of([entry], date.fromisoformat(history[-2]["date"]))

        self.assertIsNone(earlier[0]["heuristic"])  # eleven readings are too few for the rule

    def two_leading(self, claims, permits, fetched_offset=0):
        """Claims (lower is better) and permits (higher is better) as real histories, each
        reading fetched `fetched_offset` days after its date."""
        entries = []
        for key, values in (("initial_jobless_claims", claims), ("building_permits", permits)):
            history = [{**r, "fetched_at": (date.fromisoformat(r["date"]) + timedelta(days=fetched_offset)).isoformat()}
                       for r in monthly(values)]
            entries.append({"key": key, "name": key, "category": "leading", "history_window": history, "heuristic": None})
        return entries

    def test_a_group_that_leans_now_and_leaned_the_same_way_a_month_ago_keeps_its_read(self):
        read = compute_market_read(self.two_leading(FALLING, RISING))

        self.assertEqual(read["groups"]["leading"]["read"], "improving")

    def test_a_group_that_leans_now_but_not_a_month_ago_reads_mixed(self):
        # The last month flips both series favorable; before it they were flat.
        claims = [4.0] * 11 + [3.0]
        permits = [4.0] * 11 + [5.0]
        read = compute_market_read(self.two_leading(claims, permits))

        self.assertEqual(read["groups"]["leading"]["score"], 1.0)
        self.assertEqual(read["groups"]["leading"]["read"], "mixed")

    def test_a_pinned_as_of_decides_what_a_month_earlier_means(self):
        claims = [4.0] * 11 + [3.0]
        permits = [4.0] * 11 + [5.0]
        entries = self.two_leading(claims, permits)
        later = date.fromisoformat(entries[0]["history_window"][-1]["date"]) + timedelta(days=60)

        read = compute_market_read(entries, as_of=later)

        self.assertEqual(read["groups"]["leading"]["read"], "improving")  # a month earlier is still after the flip

    def test_readings_without_a_fetch_time_count_from_their_own_date(self):
        entries = self.two_leading(FALLING, RISING)
        for entry in entries:
            for reading in entry["history_window"]:
                del reading["fetched_at"]

        self.assertEqual(compute_market_read(entries)["groups"]["leading"]["read"], "improving")

    def test_a_malformed_fetch_time_falls_back_to_the_readings_date(self):
        entries = self.two_leading(FALLING, RISING)
        entries[0]["history_window"][-1]["fetched_at"] = "not a time"

        self.assertEqual(compute_market_read(entries)["groups"]["leading"]["read"], "improving")

    def test_freshly_backfilled_readings_leave_todays_read_standing(self):
        # Every reading was stored only just now, so nothing was known a month ago.
        entries = self.two_leading(FALLING, RISING)
        today = date.fromisoformat(entries[0]["history_window"][-1]["date"])
        for entry in entries:
            for reading in entry["history_window"]:
                reading["fetched_at"] = today.isoformat()

        self.assertEqual(compute_market_read(entries)["groups"]["leading"]["read"], "improving")

    def test_an_earlier_read_from_fewer_scored_indicators_is_not_used(self):
        from unittest import mock
        now = {g: {"read": None, "score": 0.0, "scored": 0, "total": 3} for g in market_read.GROUPS}
        before = {g: dict(v) for g, v in now.items()}
        now["leading"].update(read="weakening", scored=3)
        before["leading"].update(read="improving", scored=2)

        with mock.patch.object(market_read, "_read_groups", side_effect=[({}, now), ({}, before)]):
            read = compute_market_read([ctx("building_permits", "leading", RISING)])

        self.assertEqual(read["groups"]["leading"]["read"], "weakening")

    def test_a_new_indicator_with_one_reading_is_insufficient_and_harmless(self):
        entries = self.two_leading(FALLING, RISING)
        entries.append({"key": "unemployment_duration", "name": "x", "category": "lagging",
                        "history_window": [{"date": "2026-12-01", "value": 9.0, "fetched_at": "2026-12-20T00:00:00+00:00"}],
                        "heuristic": None})

        read = compute_market_read(entries)

        self.assertEqual(read["indicators"]["unemployment_duration"]["classification"], "insufficient")
        self.assertEqual(read["groups"]["leading"]["read"], "improving")

    def test_no_readings_at_all_gives_no_reads_and_no_error(self):
        read = compute_market_read([])

        self.assertTrue(all(g["read"] is None for g in read["groups"].values()))

    def test_unemployment_is_a_coincident_indicator_and_the_yield_curve_is_read_as_a_state(self):
        from indicators_config import INDICATORS
        self.assertEqual(INDICATORS["unemployment_rate"]["category"], "coincident")
        self.assertEqual(INDICATORS["yield_curve_spread"]["kind"], "inversion")


class TestComputeMarketRead(unittest.TestCase):
    GROWING = [150000 + i * i * 40 for i in range(12)]  # accelerating

    def indicators(self, claims, payrolls, permits, spread, unemployment):
        return [
            ctx("initial_jobless_claims", "leading", claims),
            ctx("nonfarm_payrolls", "coincident", payrolls),
            ctx("building_permits", "leading", permits),
            ctx("yield_curve_spread", "leading", spread),
            ctx("unemployment_rate", "lagging", unemployment, {"sahm_rule_value": 0.0}),
        ]

    def test_there_is_no_overall_read(self):
        read = compute_market_read(self.indicators(FALLING, self.GROWING, RISING, RISING, FALLING))

        self.assertEqual(set(read), {"groups", "relationship", "policy", "indicators"})
        self.assertEqual(set(read["groups"]), {"leading", "coincident", "lagging"})

    def test_each_group_is_read_on_its_own(self):
        # Leading all favorable; lagging unemployment rising (unfavorable) with a second lagging indicator.
        indicators = self.indicators(FALLING, self.GROWING, RISING, RISING, RISING)
        indicators.append(ctx("unemployment_duration", "lagging", RISING))
        read = compute_market_read(indicators)

        self.assertEqual(read["groups"]["leading"]["read"], "improving")
        self.assertEqual(read["groups"]["lagging"]["read"], "weakening")
        self.assertEqual((read["groups"]["leading"]["scored"], read["groups"]["leading"]["total"]), (3, 3))
        self.assertGreater(read["groups"]["leading"]["score"], 0.25)
        self.assertLess(read["groups"]["lagging"]["score"], -0.25)

    def test_a_group_with_one_indicator_has_no_read_but_the_others_do(self):
        read = compute_market_read(self.indicators(FALLING, self.GROWING, RISING, RISING, FALLING))

        self.assertIsNone(read["groups"]["coincident"]["read"])  # one coincident indicator
        self.assertIsNone(read["groups"]["lagging"]["read"])  # one lagging indicator
        self.assertEqual((read["groups"]["coincident"]["scored"], read["groups"]["coincident"]["total"]), (1, 1))
        self.assertEqual(read["groups"]["leading"]["read"], "improving")

    def test_mixed_signals_inside_a_group_are_neutral(self):
        read = compute_market_read(self.indicators(FLAT, FLAT, FLAT, FLAT, FLAT))

        self.assertEqual(read["groups"]["leading"]["read"], "mixed")

    def test_a_context_indicator_is_counted_in_its_groups_total_but_not_scored(self):
        indicators = self.indicators(FLAT, FLAT, FLAT, FLAT, FLAT)
        indicators.append(ctx("not_a_configured_indicator", "lagging", RISING))
        read = compute_market_read(indicators)

        self.assertEqual((read["groups"]["lagging"]["scored"], read["groups"]["lagging"]["total"]), (1, 2))
        self.assertEqual(read["indicators"]["not_a_configured_indicator"]["classification"], "context")

    def test_the_fed_funds_rate_is_context_not_scored_in_either_direction(self):
        for series in (FALLING, RISING):
            read = compute_market_read([ctx("fed_funds_rate", "lagging", series), ctx("unemployment_duration", "lagging", FALLING)])
            self.assertEqual(read["indicators"]["fed_funds_rate"]["classification"], "context")
            self.assertEqual((read["groups"]["lagging"]["scored"], read["groups"]["lagging"]["total"]), (1, 2))

    def test_cpi_is_context_and_the_new_lagging_indicators_are_scored(self):
        read = compute_market_read([
            ctx("cpi", "lagging", ACCELERATING_PRICES),
            ctx("unemployment_duration", "lagging", RISING),
            ctx("commercial_loans", "lagging", self.GROWING),
        ])

        self.assertEqual(read["indicators"]["cpi"]["classification"], "context")
        self.assertEqual((read["groups"]["lagging"]["scored"], read["groups"]["lagging"]["total"]), (2, 3))
        self.assertIn(read["indicators"]["unemployment_duration"]["classification"], ("favorable", "neutral", "unfavorable"))

    def test_result_does_not_depend_on_input_order(self):
        indicators = self.indicators(FALLING, FLAT, RISING, RISING, FALLING)
        self.assertEqual(
            compute_market_read(indicators)["groups"],
            compute_market_read(list(reversed(indicators)))["groups"],
        )

    def test_group_reads_is_the_compact_form(self):
        read = compute_market_read(self.indicators(FALLING, self.GROWING, RISING, RISING, FALLING))

        self.assertEqual(market_read.group_reads(read), {"leading": "improving", "coincident": None, "lagging": None})

    def test_thresholds_are_named_constants(self):
        for name in (
            "RECENT_DAYS", "MIN_READINGS", "SIGNAL_Z", "READ_THRESHOLD", "GROUPS",
            "MIN_SCORED_FOR_READ", "SAHM_TRIGGER",
        ):
            self.assertTrue(hasattr(market_read, name))
        self.assertFalse(hasattr(market_read, "CATEGORY_WEIGHTS"))


class TestRecentReadings(unittest.TestCase):
    def test_a_monthly_series_needs_three_readings_in_the_last_90_days_to_be_scored(self):
        history = monthly([4.0, 4.1, 4.0, 4.1, 4.0, 4.1, 4.0, 4.1, 4.0, 4.1])
        # The latest reading moved 120 days on: only it falls in the last 90 days.
        two_recent = history[:-1] + [{"date": (date.fromisoformat(history[-1]["date"]) + timedelta(days=120)).isoformat(), "value": 5.0}]

        self.assertNotEqual(indicator_stats(history, "higher")["classification"], "insufficient")
        self.assertEqual(indicator_stats(two_recent, "higher")["classification"], "insufficient")

    def test_exactly_two_recent_readings_is_not_enough(self):
        history = monthly([4.0, 4.1] * 4) + [
            {"date": (START + timedelta(days=30 * 8 + 60)).isoformat(), "value": 4.2},
            {"date": (START + timedelta(days=30 * 8 + 120)).isoformat(), "value": 4.3},
        ]
        stats = indicator_stats(history, "higher")

        self.assertEqual(market_read.MIN_RECENT_READINGS, 3)
        self.assertEqual(stats["classification"], "insufficient")
        self.assertIn("recent readings", stats["reason"])


class TestSkippedMonthlyRelease(unittest.TestCase):
    def test_a_skipped_monthly_release_leaves_a_series_unscored_until_three_readings_are_back_in_90_days(self):
        # Releases dated the 1st; October 2025 is missing (as when a release is cancelled).
        dates = ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01", "2025-06-01", "2025-07-01",
                 "2025-08-01", "2025-09-01", "2025-11-01", "2025-12-01", "2026-01-01"]
        history = [{"date": d, "value": 4.0 + 0.05 * (i % 3)} for i, d in enumerate(dates)]
        gapped = indicator_stats(history[:10], "higher")  # latest 2025-11-01: only Sep and Nov within 90 days
        recovered = indicator_stats(history[:12], "higher")  # latest 2026-01-01: Nov, Dec and Jan

        self.assertEqual(gapped["classification"], "insufficient")
        self.assertIn("recent readings", gapped["reason"])
        self.assertNotEqual(recovered["classification"], "insufficient")


class TestPolicyStance(unittest.TestCase):
    def cpi(self, then, now, days=182):
        end = date(2026, 9, 1)
        return [{"date": (end - timedelta(days=days)).isoformat(), "value": then}, {"date": end.isoformat(), "value": now}]

    def funds(self, rate):
        return [{"date": "2026-10-19", "value": rate}]

    def test_a_rate_below_the_zero_limit_is_accommodative_even_when_the_real_rate_reads_high(self):
        # Fed funds at 0.1% with falling prices: the real rate is +1.9%, which alone would be restrictive.
        stance = market_read.policy_stance(self.funds(0.1), self.cpi(100.0, 99.0))

        self.assertEqual(stance["stance"], "accommodative")
        self.assertGreater(stance["real_rate"], 1.5)
        self.assertEqual(stance["reason"], market_read.ZERO_RATE_REASON)
        self.assertIsNotNone(stance["gap"])

    def test_the_zero_limit_itself_is_judged_by_the_real_rate(self):
        just_below = market_read.policy_stance(self.funds(0.49), self.cpi(100.0, 99.0))
        at_limit = market_read.policy_stance(self.funds(market_read.ZERO_RATE_LIMIT), self.cpi(100.0, 99.0))

        self.assertEqual(just_below["stance"], "accommodative")
        self.assertEqual(at_limit["stance"], "restrictive")
        self.assertEqual(at_limit["reason"], "")

    def test_a_near_zero_rate_is_accommodative_even_without_a_usable_cpi(self):
        for cpi in (None, [], [{"date": "2026-09-01", "value": 100.0}]):
            with self.subTest(cpi=cpi):
                stance = market_read.policy_stance(self.funds(0.1), cpi)

                self.assertEqual(stance["stance"], "accommodative")
                self.assertEqual(stance["reason"], market_read.ZERO_RATE_REASON)
                self.assertIsNone(stance["inflation"])

    def test_a_near_zero_rate_keeps_its_reason_when_the_cpi_cannot_give_an_inflation_rate(self):
        stance = market_read.policy_stance(self.funds(0.1), self.cpi(0.0, 100.0))

        self.assertEqual(stance["stance"], "accommodative")
        self.assertEqual(stance["reason"], market_read.ZERO_RATE_REASON)
        self.assertIsNone(stance["inflation"])

    def test_without_a_usable_cpi_and_a_normal_rate_there_is_no_stance(self):
        stance = market_read.policy_stance(self.funds(4.5), None)

        self.assertIsNone(stance["stance"])
        self.assertEqual(stance["reason"], "no CPI readings on file")

    def test_a_real_rate_well_above_neutral_is_restrictive(self):
        stance = market_read.policy_stance(self.funds(4.5), self.cpi(100.0, 100.995))  # about 2.0% inflation

        self.assertEqual(stance["stance"], "restrictive")
        self.assertAlmostEqual(stance["inflation"], 2.0, delta=0.1)
        self.assertAlmostEqual(stance["real_rate"], 2.5, delta=0.1)
        self.assertGreaterEqual(stance["gap"], market_read.STANCE_BAND)

    def test_a_real_rate_below_neutral_is_accommodative(self):
        stance = market_read.policy_stance(self.funds(3.9), self.cpi(100.0, 101.8))  # about 3.6% inflation

        self.assertEqual(stance["stance"], "accommodative")
        self.assertLessEqual(stance["gap"], -market_read.STANCE_BAND)

    def test_a_real_rate_near_the_neutral_estimate_is_near_neutral(self):
        self.assertEqual(market_read.policy_stance(self.funds(3.0), self.cpi(100.0, 100.995))["stance"], "near neutral")

    def test_the_bands_around_the_neutral_estimate(self):
        # Inflation of 2.0% a year: the real rate is fed funds - 2.0 and the gap that minus 1.0.
        now = 100.0 * 1.02 ** (182 / 365)
        cpi = self.cpi(100.0, now)
        for rate, expected in ((3.6, "restrictive"), (3.4, "near neutral"), (2.6, "near neutral"), (2.4, "accommodative")):
            with self.subTest(rate=rate):
                self.assertEqual(market_read.policy_stance(self.funds(rate), cpi)["stance"], expected)

    def test_the_exact_band_edges(self):
        # No change in prices: inflation is exactly 0, so the real rate is the fed funds rate itself.
        flat = self.cpi(100.0, 100.0)
        for rate, expected in ((1.5, "restrictive"), (1.4, "near neutral"), (0.6, "near neutral"), (0.5, "accommodative")):
            with self.subTest(rate=rate):
                self.assertEqual(market_read.policy_stance(self.funds(rate), flat)["stance"], expected)

    def test_the_stance_is_decided_on_the_gap_that_is_shown(self):
        # A real rate 0.46 above neutral shows as a 0.5 gap, and is called restrictive to match.
        stance = market_read.policy_stance(self.funds(1.46), self.cpi(100.0, 100.0))

        self.assertEqual((stance["gap"], stance["stance"]), (0.5, "restrictive"))

    def test_it_carries_the_dates_of_the_readings_it_used(self):
        stance = market_read.policy_stance(self.funds(3.0), self.cpi(100.0, 101.0))

        self.assertEqual((stance["fed_funds_date"], stance["cpi_date"]), ("2026-10-19", "2026-09-01"))

    def test_cpi_readings_that_cannot_give_a_rate_say_so(self):
        for then, now in ((0.0, 100.0), (-5.0, 100.0), (100.0, 0.0)):
            with self.subTest(then=then, now=now):
                stance = market_read.policy_stance(self.funds(3.0), self.cpi(then, now))
                self.assertIsNone(stance["stance"])
                self.assertIn("cannot give an inflation rate", stance["reason"])

    def test_falling_prices_raise_the_real_rate(self):
        stance = market_read.policy_stance(self.funds(2.0), self.cpi(100.0, 99.0))

        self.assertLess(stance["inflation"], 0)
        self.assertEqual(stance["stance"], "restrictive")

    def test_it_says_why_when_it_cannot_judge(self):
        for funds, cpi, reason in (
            (None, self.cpi(100.0, 101.0), "no fed funds reading"),
            ([], self.cpi(100.0, 101.0), "no fed funds reading"),
            (self.funds(4.0), None, "no CPI readings"),
            (self.funds(4.0), [{"date": "2026-09-01", "value": 100.0}], "six months"),
            (self.funds(4.0), self.cpi(100.0, 101.0, days=60), "six months"),
            (self.funds(4.0), self.cpi(100.0, 101.0, days=300), "six months"),
        ):
            with self.subTest(reason=reason, cpi=cpi is None):
                stance = market_read.policy_stance(funds, cpi)
                self.assertIsNone(stance["stance"])
                self.assertIn(reason, stance["reason"])

    def test_the_reading_closest_to_six_months_back_is_used_within_the_tolerance(self):
        end = date(2026, 9, 1)
        cpi = [{"date": (end - timedelta(days=days)).isoformat(), "value": value}
               for days, value in ((196, 90.0), (180, 100.0), (170, 95.0))] + [{"date": end.isoformat(), "value": 101.0}]
        cpi.sort(key=lambda r: r["date"])

        stance = market_read.policy_stance(self.funds(3.0), cpi)

        self.assertAlmostEqual(stance["inflation"], ((101.0 / 100.0) ** (365 / 180) - 1) * 100, delta=0.1)

    def test_compute_market_read_carries_it_from_the_stored_histories(self):
        indicators = [ctx("fed_funds_rate", "lagging", [4.0] * 12), ctx("cpi", "lagging", [100 * 1.002 ** i for i in range(12)])]
        read = compute_market_read(indicators)

        self.assertIsNotNone(read["policy"]["stance"])
        self.assertEqual(read["policy"]["fed_funds"], 4.0)
        self.assertEqual(compute_market_read([])["policy"]["reason"], "no fed funds reading on file")


class TestRelationship(unittest.TestCase):
    def reads(self, leading, coincident, lagging):
        return {"leading": leading, "coincident": coincident, "lagging": lagging}

    def test_all_three_agreeing_says_so(self):
        self.assertEqual(market_read.relationship(self.reads("improving", "improving", "improving")),
                         "All three groups agree: improving.")

    def test_a_weaker_outlook_than_the_present_is_an_early_warning(self):
        text = market_read.relationship(self.reads("weakening", "mixed", "mixed"))

        self.assertIn("outlook is weaker than the present", text)
        self.assertIn("early warning", text)

    def test_a_stronger_outlook_than_the_present_is_an_early_improvement(self):
        text = market_read.relationship(self.reads("improving", "mixed", "mixed"))

        self.assertIn("outlook is stronger than the present", text)

    def test_lagging_behind_the_present_is_called_out_with_its_time_frame(self):
        worse = market_read.relationship(self.reads("mixed", "mixed", "weakening"))
        better = market_read.relationship(self.reads("mixed", "mixed", "improving"))

        self.assertIn("has not caught up", worse)
        self.assertIn("6 to 12 months", worse)
        self.assertIn("still better than current conditions", better)

    def test_both_comparisons_can_appear_together(self):
        text = market_read.relationship(self.reads("weakening", "mixed", "improving"))

        self.assertIn("weaker than the present", text)
        self.assertIn("still better than current conditions", text)

    def test_two_groups_that_agree_and_the_third_missing(self):
        self.assertEqual(market_read.relationship(self.reads("mixed", "mixed", None)),
                         "The groups that have a read agree.")

    def test_without_a_coincident_read_the_outlook_is_compared_with_the_lagging_data_directly(self):
        weaker = market_read.relationship(self.reads("weakening", None, "improving"))
        stronger = market_read.relationship(self.reads("improving", None, "weakening"))

        self.assertIn("outlook is weaker than the lagging data", weaker)
        self.assertIn("early warning", weaker)
        self.assertIn("outlook is stronger than the lagging data", stronger)
        self.assertNotIn("agree", weaker + stronger)

    def test_without_a_coincident_read_two_agreeing_groups_agree_and_never_say_differ(self):
        self.assertEqual(market_read.relationship(self.reads("improving", None, "improving")),
                         "The groups that have a read agree.")

    def test_the_sentence_is_never_the_false_agreement_when_the_reads_differ(self):
        every = [None, "weakening", "mixed", "improving"]
        for leading in every:
            for coincident in every:
                for lagging in every:
                    reads = self.reads(leading, coincident, lagging)
                    text = market_read.relationship(reads)
                    present = {r for r in reads.values() if r}
                    if text is not None and len(present) > 1:
                        self.assertNotIn("agree", text.replace("do not agree", ""), reads)
                    if text is not None and len(present) == 1:
                        self.assertIn("agree", text, reads)

    def test_fewer_than_two_reads_gives_no_sentence(self):
        self.assertIsNone(market_read.relationship(self.reads("improving", None, None)))
        self.assertIsNone(market_read.relationship(self.reads(None, None, None)))

    def test_compute_market_read_carries_the_sentence(self):
        indicators = [
            ctx("initial_jobless_claims", "leading", RISING), ctx("building_permits", "leading", FALLING),
            ctx("nonfarm_payrolls", "coincident", FLAT), ctx("industrial_production", "coincident", FLAT),
        ]
        read = compute_market_read(indicators)

        self.assertEqual(read["groups"]["leading"]["read"], "weakening")
        self.assertIn("early warning", read["relationship"])


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "web"))

import ticker_verdicts
from ticker_verdicts import by_ticker, compute_ticker_verdicts


def _range(off_high):
    """A 52-week range whose high is 100 and whose width is 25, with the
    price `off_high` percent below the high: off 20 sits at 20% of the
    range, off 5 at 80%."""
    if off_high is None:
        return {}
    return {"price": 100.0 - off_high, "week52_low": 75.0, "week52_high": 100.0}


def fund(symbol, off_high=None, r26=None):
    return {"symbol": symbol, "pct_off_high": off_high, "return_26w": r26, **_range(off_high)}


def narrow(symbol, off_high, r26):
    """Price `off_high` percent under a high of 100, in a range only half a
    point deep: at the bottom of its own range however close to the high."""
    price = 100.0 - off_high
    return {"symbol": symbol, "pct_off_high": off_high, "return_26w": r26,
            "price": price, "week52_low": price - 0.5, "week52_high": 100.0}


def stock(symbol, off_high, r26, peg, roe, margin, rev, eps, debt, pe=20.0):
    return {
        **_range(off_high),
        "symbol": symbol, "pct_off_high": off_high, "return_26w": r26, "peg_ratio": peg,
        "roe": roe, "net_margin": margin, "revenue_growth": rev, "eps_growth": eps,
        "debt_to_equity": debt, "pe_ratio": pe,
    }


def verdicts(result):
    return {t["symbol"]: v for v, ts in result["tickers_by_verdict"].items() for t in ts}


def reasoning(result, symbol):
    for entries in result["tickers_by_verdict"].values():
        for entry in entries:
            if entry["symbol"] == symbol:
                return entry["reasoning"]
    raise KeyError(symbol)


class TestFundVerdicts(unittest.TestCase):
    def test_far_below_high_and_lagging_peers_is_a_discount_and_the_mirror_overpriced(self):
        group = [fund("A", 20.0, -5.0), fund("B", 10.0, 5.0), fund("C", 5.0, 30.0)]
        got = verdicts(compute_ticker_verdicts({"sector": group}))
        self.assertEqual(got, {"A": "discount", "B": "fair", "C": "overpriced"})

    def test_one_signal_alone_is_not_enough(self):
        # A is furthest below its high but its return sits mid-pack.
        group = [fund("A", 20.0, 10.0), fund("B", 10.0, 5.0), fund("C", 5.0, 15.0)]
        self.assertEqual(verdicts(compute_ticker_verdicts({"sector": group}))["A"], "fair")

    def test_position_is_the_funds_own_range_whatever_its_peers_do(self):
        # All three sit at 20% of their own ranges: each is "near its low"
        # on position, and with equal returns that alone is not enough.
        group = [fund("A", 20.0, 5.0), fund("B", 20.0, 5.0), fund("C", 20.0, 5.0)]
        result = compute_ticker_verdicts({"sector": group})
        self.assertEqual(set(verdicts(result).values()), {"fair"})
        for symbol in ("A", "B", "C"):
            self.assertIn("near its low", reasoning(result, symbol))

    def test_a_calm_fund_is_not_cheap_for_being_close_to_its_high(self):
        # 4% below its high but at the top of a narrow range: dear, not cheap.
        group = [
            {"symbol": "CALM", "pct_off_high": 4.0, "return_26w": 5.0,
             "price": 100.0, "week52_low": 95.0, "week52_high": 100.5},
            fund("B", 10.0, 5.0), fund("C", 10.0, 5.0),
        ]
        result = compute_ticker_verdicts({"bonds": group})
        self.assertIn("near its high", reasoning(result, "CALM"))

    def test_nothing_within_the_guard_of_its_high_is_a_discount(self):
        group = [narrow("A", 2.5, -5.0), narrow("B", 2.0, 5.0), narrow("C", 1.0, 30.0)]
        result = compute_ticker_verdicts({"sector": group})
        self.assertEqual(verdicts(result)["A"], "fair")
        self.assertIn("not a discount", reasoning(result, "A"))

    def test_guard_boundary(self):
        at = [narrow("A", 3.0, -5.0), narrow("B", 2.0, 5.0), narrow("C", 1.0, 30.0)]
        below = [narrow("A", 2.9, -5.0), narrow("B", 2.0, 5.0), narrow("C", 1.0, 30.0)]
        self.assertEqual(verdicts(compute_ticker_verdicts({"g": at}))["A"], "discount")
        self.assertEqual(verdicts(compute_ticker_verdicts({"g": below}))["A"], "fair")

    def test_reasoning_names_the_numbers_and_says_a_fund_has_no_pe(self):
        group = [fund("A", 20.04, -5.0), fund("B", 10.0, 5.0), fund("C", 5.0, 30.0)]
        text = reasoning(compute_ticker_verdicts({"sector": group}), "A")
        self.assertIn("Price at 20% of its own 52-week range (20.0% below its high)", text)
        self.assertIn("-5.0%", text)
        self.assertIn("no P/E", text)

    def test_order_of_the_group_does_not_matter(self):
        group = [fund("A", 20.0, -5.0), fund("B", 10.0, 5.0), fund("C", 5.0, 30.0)]
        forward = verdicts(compute_ticker_verdicts({"g": group}))
        backward = verdicts(compute_ticker_verdicts({"g": list(reversed(group))}))
        self.assertEqual(forward, backward)


class TestUnscored(unittest.TestCase):
    def test_a_ticker_with_no_data_is_not_scored_or_counted(self):
        group = [fund("A", 20.0, -5.0), fund("B", 10.0, 5.0), fund("C", 5.0, 30.0), fund("N")]
        result = compute_ticker_verdicts({"sector": group})
        self.assertEqual(result["unscored"], [{"symbol": "N", "group": "sector"}])
        self.assertNotIn("N", verdicts(result))
        self.assertEqual(len(sum(result["tickers_by_verdict"].values(), [])), 3)

    def test_a_small_group_is_scored_on_its_own_range_alone_and_never_extreme(self):
        # Too few tickers to rank returns, so position is the only signal
        # and one signal is not enough for a discount or overpriced.
        pair = [fund("A", 20.0, -5.0), fund("B", 1.0, 30.0)]
        result = compute_ticker_verdicts({"pair": pair})
        self.assertEqual(verdicts(result), {"A": "fair", "B": "fair"})
        self.assertEqual(result["unscored"], [])
        self.assertIn("near its low", reasoning(result, "A"))
        self.assertIn("near its high", reasoning(result, "B"))
        self.assertEqual(result["groups"], [])

    def test_a_small_group_with_only_peer_relative_inputs_is_not_scored(self):
        pair = [
            {"symbol": "A", "pct_off_high": 20.0, "return_26w": -5.0},
            {"symbol": "B", "pct_off_high": 1.0, "return_26w": 30.0},
        ]
        result = compute_ticker_verdicts({"pair": pair})
        self.assertEqual({u["symbol"] for u in result["unscored"]}, {"A", "B"})

    def test_empty_group_is_left_out(self):
        result = compute_ticker_verdicts({"bonds": [], "x": [fund("A", 1.0, 1.0)] * 3})
        self.assertNotIn("bonds", result["scores"])
        self.assertIn("x", result["scores"])


class TestIndividualStocks(unittest.TestCase):
    def group(self):
        return [
            stock("S1", 25.0, -10.0, 0.7, 30.0, 25.0, 20.0, 40.0, 0.3),
            stock("S2", 12.0, 10.0, 1.5, 20.0, 15.0, 10.0, 20.0, 0.6),
            stock("S3", 8.0, 20.0, 2.5, 15.0, 10.0, 6.0, 10.0, 1.0),
            stock("S4", 4.0, 40.0, 4.0, 10.0, 5.0, 2.0, 5.0, 1.5),
        ]

    def test_cheap_good_quality_is_a_discount_and_dear_stretched_is_overpriced(self):
        got = verdicts(compute_ticker_verdicts({"individual": self.group()}))
        self.assertEqual(got["S1"], "discount")
        self.assertEqual(got["S4"], "overpriced")

    def test_cheap_but_worst_quality_is_a_value_trap(self):
        trap = stock("TRAP", 30.0, -10.0, 0.5, -10.0, -20.0, 1.0, None, 3.0, pe=None)
        result = compute_ticker_verdicts({"individual": [*self.group(), trap]})
        self.assertEqual(verdicts(result)["TRAP"], "fair")
        self.assertTrue(result["scores"]["individual"]["TRAP"]["value_trap"])
        self.assertIn("value trap", reasoning(result, "TRAP"))

    def test_negative_earnings_do_not_sink_an_otherwise_best_in_group_stock(self):
        group = self.group()
        losing = stock("LOSS", 30.0, -10.0, 0.5, 31.0, 26.0, 21.0, None, 0.2, pe=None)
        ranked = compute_ticker_verdicts({"individual": [*group, losing]})
        # Everything else about it is best-in-group: it only trips the
        # quality rank if the missing EPS growth is taken as the worst.
        with_eps = stock("LOSS", 30.0, -10.0, 0.5, 31.0, 26.0, 21.0, 45.0, 0.2)
        baseline = compute_ticker_verdicts({"individual": [*group, with_eps]})
        self.assertNotIn("weak quality", reasoning(baseline, "LOSS"))
        self.assertNotIn("weak quality", reasoning(ranked, "LOSS"))
        self.assertEqual(verdicts(ranked)["LOSS"], "discount")

    def test_a_non_positive_peg_is_not_ranked(self):
        group = self.group()
        group[0]["peg_ratio"] = -3.0
        result = compute_ticker_verdicts({"individual": group})
        self.assertIn("PEG not meaningful", reasoning(result, "S1"))
        self.assertNotIn("PEG -3", reasoning(result, "S1"))

    def test_a_positive_peg_with_too_few_peers_to_rank_says_so(self):
        group = [self.group()[0]]
        text = reasoning(compute_ticker_verdicts({"individual": group}), "S1")

        self.assertIn("too few peers with a PEG to rank it", text)

    def test_a_missing_peg_with_shrinking_earnings_says_why(self):
        group = self.group()
        group[0]["peg_ratio"] = None
        group[0]["eps_growth"] = -27.6

        text = reasoning(compute_ticker_verdicts({"individual": group}), "S1")

        self.assertIn("PEG not available (earnings are shrinking)", text)

    def test_a_mid_quality_stock_still_shows_the_figures_it_was_ranked_on(self):
        group = self.group()
        text = reasoning(compute_ticker_verdicts({"individual": group}), "S1")

        self.assertRegex(text, r"(weak|strong) quality|quality mid-pack")
        self.assertRegex(text, r"ROE [\d.n/a-]+%?, net margin .*, revenue growth .*, EPS growth .*, debt/equity ")

    def test_missing_fundamentals_are_skipped_not_assumed_weak(self):
        group = self.group()
        for key in ("roe", "net_margin", "revenue_growth", "debt_to_equity"):
            group[0][key] = None
        result = compute_ticker_verdicts({"individual": group})
        self.assertNotIn("weak quality", reasoning(result, "S1"))
        self.assertIn("quality not rated", reasoning(result, "S1"))
        self.assertIn("ROE n/a", reasoning(result, "S1"))

    def test_fundamentals_and_peg_apply_to_the_individual_group_only(self):
        funds = [dict(c) for c in self.group()]
        result = compute_ticker_verdicts({"stocks": funds})
        self.assertNotIn("PEG", reasoning(result, "S1"))
        self.assertNotIn("quality", reasoning(result, "S1"))

    def test_same_symbol_in_two_groups_is_scored_in_each(self):
        a = [fund("DUP", 20.0, -5.0), fund("X", 10.0, 5.0), fund("Y", 5.0, 30.0)]
        b = [fund("DUP", 1.0, 40.0), fund("P", 10.0, 5.0), fund("Q", 5.0, 30.0)]
        result = compute_ticker_verdicts({"one": a, "two": b})
        by_group = {
            (e["group"], e["symbol"]): v
            for v, es in result["tickers_by_verdict"].items()
            for e in es
        }
        self.assertEqual(by_group[("one", "DUP")], "discount")
        self.assertEqual(by_group[("two", "DUP")], "overpriced")


def ranged(symbol, position, off_high=10.0, r26=5.0):
    """A fund whose price sits at `position` of its 52-week range."""
    return {
        "symbol": symbol, "price": 100.0 + position * 50.0, "week52_low": 100.0,
        "week52_high": 150.0, "pct_off_high": off_high, "return_26w": r26,
    }


def three_groups():
    return {
        "high": [ranged("H1", 0.9), ranged("H2", 0.85), ranged("H3", 0.95)],
        "mid": [ranged("M1", 0.5), ranged("M2", 0.45), ranged("M3", 0.55)],
        "low": [ranged("L1", 0.1), ranged("L2", 0.2), ranged("L3", 0.05)],
    }


class TestGroups(unittest.TestCase):
    def test_each_group_is_judged_against_its_own_52_week_range(self):
        result = compute_ticker_verdicts(three_groups())
        self.assertEqual(
            [(g["group"], g["verdict"]) for g in result["groups"]],
            [("low", "discount"), ("mid", "fair"), ("high", "overpriced")],
        )

    def test_group_summary_is_plain_language_without_the_median_or_a_count(self):
        result = compute_ticker_verdicts(three_groups())
        low = next(g for g in result["groups"] if g["group"] == "low")
        self.assertIn("low end of its own 52-week ranges", low["summary"])
        self.assertNotIn("median", low["summary"].lower())
        self.assertNotIn("10%", low["summary"])

    def test_a_group_is_judged_even_when_it_is_the_only_one(self):
        result = compute_ticker_verdicts({"bonds": three_groups()["low"]})
        self.assertEqual([(g["group"], g["verdict"]) for g in result["groups"]], [("bonds", "discount")])

    def test_a_calm_group_is_not_cheaper_just_for_being_calm(self):
        # Both groups sit mid-range; one barely moved all year, the other
        # swung widely. Neither is called a discount against the other.
        calm = [
            {"symbol": s, "price": 100.5, "week52_low": 100.0, "week52_high": 101.0,
             "pct_off_high": 0.5, "return_26w": 0.1}
            for s in ("C1", "C2", "C3")
        ]
        wild = [ranged("W1", 0.5), ranged("W2", 0.5), ranged("W3", 0.5)]
        result = compute_ticker_verdicts({"calm": calm, "wild": wild})
        self.assertEqual({g["verdict"] for g in result["groups"]}, {"fair"})

    def test_a_group_whose_tickers_lack_a_range_is_not_judged(self):
        no_range = [
            {"symbol": s, "pct_off_high": o, "return_26w": r}
            for s, o, r in [("A", 20.0, -5.0), ("B", 10.0, 5.0), ("C", 5.0, 30.0)]
        ]
        result = compute_ticker_verdicts({"g": no_range})
        self.assertEqual(result["groups"], [])

    def test_a_group_too_small_to_judge_is_left_out(self):
        groups = three_groups()
        groups["tiny"] = [ranged("T1", 0.0), ranged("T2", 0.0)]
        result = compute_ticker_verdicts(groups)
        self.assertNotIn("tiny", [g["group"] for g in result["groups"]])

    def test_range_position_boundaries(self):
        pos = ticker_verdicts._range_position
        self.assertEqual(pos({"price": 150.0, "week52_low": 100.0, "week52_high": 150.0}), 1.0)
        self.assertEqual(pos({"price": 100.0, "week52_low": 100.0, "week52_high": 150.0}), 0.0)
        self.assertEqual(pos({"price": 160.0, "week52_low": 100.0, "week52_high": 150.0}), 1.0)
        self.assertIsNone(pos({"price": 100.0, "week52_low": 100.0, "week52_high": 100.0}))
        self.assertIsNone(pos({"price": None, "week52_low": 1.0, "week52_high": 2.0}))

    def test_buckets_keep_watchlist_order(self):
        mid = [fund("Z", 10.0, 5.0), fund("A", 10.0, 5.0), fund("M", 10.0, 5.0)]
        result = compute_ticker_verdicts({"g": mid})
        self.assertEqual([t["symbol"] for t in result["tickers_by_verdict"]["fair"]], ["Z", "A", "M"])

    def test_thresholds_are_named_constants(self):
        for name in ("MIN_PEERS", "PEER_TOP", "PEER_BOTTOM", "MIN_QUALITY_INPUTS",
                     "MIN_DISCOUNT_OFF_HIGH_PCT", "VERDICT_SCORE"):
            self.assertTrue(hasattr(ticker_verdicts, name))


class TestByTicker(unittest.TestCase):
    def setUp(self):
        self.computed = compute_ticker_verdicts(
            {
                "bonds": [ranged("B", 0.1), ranged("B2", 0.1), ranged("B3", 0.1)],
                "pair": [{"symbol": "P1"}, {"symbol": "P2"}],
            }
        )

    def test_tickers_are_keyed_by_group_and_symbol(self):
        result = by_ticker(self.computed)

        self.assertIn(("bonds", "B"), result["tickers"])
        self.assertIn(result["tickers"][("bonds", "B")]["verdict"], ("discount", "fair", "overpriced"))
        self.assertTrue(result["tickers"][("bonds", "B")]["reasoning"])

    def test_a_judged_group_carries_its_verdict_and_summary(self):
        result = by_ticker(self.computed)

        self.assertEqual(result["groups"]["bonds"]["verdict"], "discount")
        self.assertIn("52-week ranges", result["groups"]["bonds"]["summary"])
        self.assertNotIn("pair", result["groups"])

    def test_unscored_tickers_are_listed_and_have_no_verdict(self):
        result = by_ticker(self.computed)

        self.assertEqual(result["unscored"], {("pair", "P1"), ("pair", "P2")})
        self.assertNotIn(("pair", "P1"), result["tickers"])

    def test_the_same_symbol_in_two_groups_keeps_each_groups_own_verdict(self):
        computed = compute_ticker_verdicts(
            {
                "one": [fund("DUP", 20.0, -5.0), fund("X", 10.0, 5.0), fund("Y", 5.0, 30.0)],
                "two": [fund("DUP", 1.0, 40.0), fund("P", 10.0, 5.0), fund("Q", 5.0, 30.0)],
            }
        )
        result = by_ticker(computed)

        self.assertNotEqual(result["tickers"][("one", "DUP")], result["tickers"][("two", "DUP")])

    def test_none_gives_empty_maps(self):
        self.assertEqual(by_ticker(None), {"tickers": {}, "groups": {}, "unscored": set()})


if __name__ == "__main__":
    unittest.main()

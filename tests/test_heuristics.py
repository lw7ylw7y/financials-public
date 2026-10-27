import os
import sys
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

from heuristics import heuristic_for, sahm_rule_value


def readings(values):
    return [{"date": f"2026-{i + 1:02d}-01", "value": v} for i, v in enumerate(values)]


class TestSahmRuleValue(unittest.TestCase):
    def test_computes_against_known_sample_series(self):
        # 12 months, low of 3.5 in months 1-9, then a rise to 4.0/4.2/4.4.
        values = [3.5] * 9 + [4.0, 4.2, 4.4]
        result = sahm_rule_value(readings(values))

        # last-3 avg = (4.0+4.2+4.4)/3 = 4.2; 12-month low = 3.5
        self.assertEqual(result, round(4.2 - 3.5, 2))

    def test_returns_none_with_fewer_than_12_readings(self):
        result = sahm_rule_value(readings([3.5] * 11))
        self.assertIsNone(result)

    def test_zero_when_no_rise_above_low(self):
        result = sahm_rule_value(readings([3.5] * 12))
        self.assertEqual(result, 0.0)


class TestHeuristicFor(unittest.TestCase):
    def test_unemployment_gets_the_sahm_value(self):
        self.assertEqual(heuristic_for("unemployment_rate", readings([3.5] * 11 + [4.5])), {"sahm_rule_value": 0.33})

    def test_unemployment_with_too_little_history_has_none(self):
        self.assertIsNone(heuristic_for("unemployment_rate", readings([3.5] * 11)))

    def test_other_indicators_have_none(self):
        for key in ("yield_curve_spread", "initial_jobless_claims", "cpi"):
            self.assertIsNone(heuristic_for(key, readings([1.0] * 12)))


if __name__ == "__main__":
    unittest.main()

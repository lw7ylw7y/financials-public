import os
import sys
import unittest
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import scoring
import settings
from kv_store import KvStoreError


def form(**changes):
    result = settings.default_form()
    for name, entry in changes.items():
        result[name] = {**result[name], **entry}
    return result


class TestDefaults(unittest.TestCase):
    def test_the_default_form_matches_the_scoring_constants_with_every_switch_on(self):
        self.assertEqual(settings.to_settings(settings.default_form()), scoring.DEFAULT_SETTINGS)
        for name in settings.SWITCHABLE:
            self.assertTrue(settings.default_form()[name]["on"])

    @patch("settings.kv_store.hgetall_json", return_value={})
    def test_nothing_saved_means_the_defaults(self, mock_hgetall):
        self.assertEqual(settings.load_settings(), scoring.DEFAULT_SETTINGS)
        mock_hgetall.assert_called_once_with("screener_settings")

    @patch("settings.kv_store.hgetall_json", return_value={"max_debt_equity": {"value": 1.5, "on": True}})
    def test_a_field_never_saved_uses_its_default(self, _hgetall):
        loaded = settings.load_settings()

        self.assertEqual(loaded.max_debt_equity, 1.5)
        self.assertEqual(loaded.min_roi_pct, scoring.DEFAULT_SETTINGS.min_roi_pct)

    @patch("settings.kv_store.hgetall_json", return_value={"min_roi_pct": {"value": "lots", "on": True}})
    def test_a_stored_field_that_no_longer_validates_falls_back_to_its_default(self, _hgetall):
        self.assertEqual(settings.load_settings(), scoring.DEFAULT_SETTINGS)

    @patch("settings.kv_store.hgetall_json", side_effect=KvStoreError("down"))
    def test_a_redis_failure_propagates(self, _hgetall):
        with self.assertRaises(KvStoreError):
            settings.load_settings()


class TestValidation(unittest.TestCase):
    def test_the_default_form_is_valid(self):
        cleaned, errors = settings.validate_form(settings.default_form())

        self.assertEqual(errors, {})
        self.assertEqual(cleaned, settings.default_form())

    def test_a_missing_field_a_non_number_and_a_bool_are_rejected(self):
        bad = form(net_margin_min={"value": "5"}, fcf_min_m={"value": True})
        del bad["min_roi_pct"]

        _, errors = settings.validate_form(bad)

        self.assertEqual(set(errors), {"net_margin_min", "fcf_min_m", "min_roi_pct"})

    def test_a_value_outside_its_range_or_not_finite_is_rejected_with_a_message(self):
        for value in (-1.0, 1e9, float("nan"), float("inf")):
            with self.subTest(value=value):
                _, errors = settings.validate_form(form(max_debt_equity={"value": value}))
                self.assertIn("Enter a number between 0 and 100.", errors["max_debt_equity"])

    def test_the_market_cap_minimum_must_be_below_the_maximum(self):
        _, errors = settings.validate_form(form(market_cap_min_m={"value": 5000.0}, market_cap_max_m={"value": 5000.0}))

        self.assertEqual(errors, {"market_cap_min_m": "The minimum must be below the maximum."})

    def test_a_switch_must_be_a_bool(self):
        _, errors = settings.validate_form(form(min_roi_pct={"on": "yes"}))

        self.assertEqual(set(errors), {"min_roi_pct"})

    def test_a_switched_off_filters_number_is_still_checked(self):
        _, errors = settings.validate_form(form(min_roi_pct={"value": 99999.0, "on": False}))

        self.assertEqual(set(errors), {"min_roi_pct"})

    def test_a_body_that_is_not_an_object_is_all_errors(self):
        for raw in (None, [], "x", 5):
            _, errors = settings.validate_form(raw)
            self.assertEqual(set(errors), set(settings.FIELDS))


class TestSwitchesAndSaving(unittest.TestCase):
    def test_a_filter_switched_off_becomes_none_and_keeps_its_number_in_the_form(self):
        off = form(min_roi_pct={"value": 8.0, "on": False})

        self.assertIsNone(settings.to_settings(off).min_roi_pct)
        self.assertEqual(settings.validate_form(off)[0]["min_roi_pct"], {"value": 8.0, "on": False})

    def test_a_switched_off_filter_is_not_applied(self):
        record = {"market_cap": 3000.0, "flags": [], "metrics": {"roi": 1.0}, "ipo_date": None}
        loose = settings.to_settings(form(
            net_margin_min={"on": False}, fcf_min_m={"on": False}, max_debt_equity={"on": False},
            max_dilution_pct={"on": False}, min_roi_pct={"on": False}, stale_years={"on": False}))

        self.assertTrue(scoring.evaluate(record, loose)["passes"])
        self.assertFalse(scoring.evaluate(record, scoring.DEFAULT_SETTINGS)["passes"])

    @patch("settings.kv_store.hset_many_json")
    def test_save_is_one_multi_field_write_of_every_setting(self, mock_many):
        settings.save_form(settings.default_form())

        mock_many.assert_called_once()
        self.assertEqual(mock_many.call_args.args[0], "screener_settings")
        self.assertEqual(set(mock_many.call_args.args[1]), set(settings.FIELDS))

    @patch("settings.kv_store.hset_json")
    @patch("settings.kv_store.hset_many_json", side_effect=KvStoreError("down"))
    def test_a_failed_save_raises_and_writes_nothing_field_by_field(self, _many, mock_one):
        with self.assertRaises(KvStoreError):
            settings.save_form(settings.default_form())

        mock_one.assert_not_called()


class TestSymbolsToFetch(unittest.TestCase):
    def test_tech_symbols_inside_the_band_without_a_record_are_listed_sorted(self):
        def entry(stage="tech", cap=50000.0):
            return {"stage": stage, "market_cap": cap}

        universe = {"ZED": entry(), "ABC": entry(), "HAS": entry(), "SMALL": entry(cap=100.0), "NONE": entry(cap=None),
                    "BANK": entry(stage="non_tech"), "OUT": entry(cap=900000.0)}
        wider = scoring.ScreenSettings(market_cap_max_m=60000.0)

        self.assertEqual(scoring.symbols_to_fetch(universe, {"HAS": {}}, wider), ["ABC", "ZED"])
        self.assertEqual(scoring.symbols_to_fetch(universe, {"HAS": {}}), [])


if __name__ == "__main__":
    unittest.main()

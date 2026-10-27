import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import finnhub_client
import quotes
from kv_store import KvStoreError

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def cached(price, age_minutes):
    return {"price": price, "change": 0.1, "change_percent": 0.5,
            "quoted_at": (NOW - timedelta(minutes=age_minutes)).isoformat()}


def live(price):
    return {"price": price, "change": 0.2, "change_percent": 1.0}


@patch("quotes.page_store.save_quote")
@patch("quotes.page_store.load_quotes")
class TestGetQuotes(unittest.TestCase):
    def setUp(self):
        quotes._rate_limited_until = 0.0
        self.addCleanup(setattr, quotes, "_rate_limited_until", 0.0)

    def test_a_quote_under_five_minutes_old_is_reused_without_a_finnhub_call(self, load, save):
        load.return_value = {"AAA": cached(10.0, 4)}
        fetch = unittest.mock.Mock()

        result = quotes.get_quotes(["AAA"], NOW, fetch_quote=fetch)

        fetch.assert_not_called()
        save.assert_not_called()
        self.assertEqual(result["AAA"]["price"], 10.0)

    def test_a_missing_or_old_quote_is_fetched_and_saved_per_symbol(self, load, save):
        load.return_value = {"OLD": cached(9.0, 6)}
        prices = {"OLD": 9.5, "NEW": 20.0}

        result = quotes.get_quotes(["OLD", "NEW"], NOW, fetch_quote=lambda s: live(prices[s]))

        self.assertEqual(result["OLD"]["price"], 9.5)
        self.assertEqual(result["NEW"]["quoted_at"], NOW.isoformat())
        self.assertEqual(sorted(c.args[0] for c in save.call_args_list), ["NEW", "OLD"])

    def test_a_failed_fetch_falls_back_to_the_older_cached_quote(self, load, save):
        load.return_value = {"AAA": cached(10.0, 30)}

        def fail(symbol):
            raise finnhub_client.FinnhubApiError("boom")

        result = quotes.get_quotes(["AAA", "BBB"], NOW, fetch_quote=fail)

        self.assertEqual(result["AAA"]["price"], 10.0)
        self.assertIsNone(result["BBB"])
        save.assert_not_called()

    @patch("quotes.QUOTE_WORKERS", 1)
    def test_a_rate_limit_stops_further_fetches_and_is_not_retried(self, load, save):
        load.return_value = {}
        calls = []

        def fetch(symbol):
            calls.append(symbol)
            raise finnhub_client.FinnhubRateLimited("429")

        result = quotes.get_quotes(["A", "B", "C"], NOW, fetch_quote=fetch)

        self.assertEqual(calls, ["A"])
        self.assertEqual(result, {"A": None, "B": None, "C": None})

    def test_after_a_rate_limit_later_calls_do_not_fetch_until_the_cooldown_ends(self, load, save):
        load.return_value = {}

        def limited(symbol):
            raise finnhub_client.FinnhubRateLimited("429")

        quotes.get_quotes(["A"], NOW, fetch_quote=limited)
        fetch = unittest.mock.Mock(return_value=live(1.0))
        during = quotes.get_quotes(["B"], NOW, fetch_quote=fetch)
        quotes._rate_limited_until = 0.0
        after = quotes.get_quotes(["B"], NOW, fetch_quote=fetch)

        self.assertIsNone(during["B"])
        self.assertEqual(after["B"]["price"], 1.0)
        fetch.assert_called_once_with("B")

    def test_a_malformed_cached_entry_is_treated_as_missing(self, load, save):
        load.return_value = {"A": {"price": 1.0}, "B": {"quoted_at": "garbage", "price": 2.0}, "C": None}

        result = quotes.get_quotes(["A", "B", "C"], NOW, fetch_quote=lambda s: live(9.0))

        self.assertEqual([result[s]["price"] for s in "ABC"], [9.0, 9.0, 9.0])

    def test_results_stay_keyed_by_symbol_when_fetches_finish_out_of_order(self, load, save):
        load.return_value = {}

        def fetch(symbol):
            time.sleep(0.05 if symbol == "SLOW" else 0)
            return live({"SLOW": 1.0, "FAST": 2.0}[symbol])

        result = quotes.get_quotes(["SLOW", "FAST"], NOW, fetch_quote=fetch)

        self.assertEqual((result["SLOW"]["price"], result["FAST"]["price"]), (1.0, 2.0))
        self.assertEqual(list(result), ["SLOW", "FAST"])

    def test_a_failed_cache_write_still_returns_the_quote(self, load, save):
        load.return_value = {}
        save.side_effect = KvStoreError("down")

        result = quotes.get_quotes(["AAA"], NOW, fetch_quote=lambda s: live(5.0))

        self.assertEqual(result["AAA"]["price"], 5.0)

    def test_a_failed_cache_read_propagates(self, load, save):
        load.side_effect = KvStoreError("down")

        with self.assertRaises(KvStoreError):
            quotes.get_quotes(["AAA"], NOW, fetch_quote=lambda s: live(5.0))


if __name__ == "__main__":
    unittest.main()

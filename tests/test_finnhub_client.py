import os
import sys
import unittest
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from datetime import date

import requests
from finnhub_client import (
    FinnhubApiError,
    FinnhubRateLimited,
    fetch_company_industry,
    fetch_company_profile,
    fetch_next_earnings_date,
    fetch_market_news,
    fetch_quote,
    fetch_stock_metrics,
    fetch_us_common_stocks,
)


class TestFetchQuote(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_parses_price_and_change(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31, "d": 3.81, "dp": 0.85})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31, "change": 3.81, "change_percent": 0.85})

    @patch("finnhub_client._session.get")
    def test_missing_change_fields_degrade_to_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 452.31})

        result = fetch_quote("SPY", api_key="test-key")

        self.assertEqual(result, {"price": 452.31, "change": None, "change_percent": None})

    @patch("finnhub_client._session.get")
    def test_raises_on_zero_price(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"c": 0})

        with self.assertRaises(FinnhubApiError):
            fetch_quote("BADSYM", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_quote("SPY", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_quote("SPY", api_key=None)


class TestFetchStockMetrics(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_parses_range_market_cap_pe_and_peg(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 629.28,
                    "52WeekHigh": 779.37,
                    "marketCapitalization": 3500000.0,
                    "peTTM": 34.2,
                    "pegTTM": 2.1,
                }
            }
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertEqual(
            result,
            {
                "low": 629.28, "high": 779.37, "roi": None, "market_cap": 3500000.0,
                "pe_ratio": 34.2, "peg_ratio": 2.1,
                "revenue_growth": None, "eps_growth": None, "roe": None,
                "net_margin": None, "debt_to_equity": None, "dividend_yield": None,
                "return_13w": None, "return_26w": None, "return_ytd": None,
            },
        )

    @patch("finnhub_client._session.get")
    def test_parses_price_returns(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "13WeekPriceReturnDaily": 8.2446,
                    "26WeekPriceReturnDaily": 39.3513,
                    "yearToDatePriceReturnDaily": 33.4713,
                }
            }
        )

        result = fetch_stock_metrics("FTEC", api_key="test-key")

        self.assertEqual(result["return_13w"], 8.2446)
        self.assertEqual(result["return_26w"], 39.3513)
        self.assertEqual(result["return_ytd"], 33.4713)

    @patch("finnhub_client._session.get")
    def test_parses_growth_and_quality_fields(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "revenueGrowthTTMYoy": 14.24,
                    "epsGrowthTTMYoy": 32.61,
                    "roeTTM": 137.18,
                    "netProfitMarginTTM": 27.62,
                    "totalDebt/totalEquityAnnual": 1.3547,
                    "dividendYieldIndicatedAnnual": 0.505,
                }
            }
        )

        result = fetch_stock_metrics("AAPL", api_key="test-key")

        self.assertEqual(result["revenue_growth"], 14.24)
        self.assertEqual(result["eps_growth"], 32.61)
        self.assertEqual(result["roe"], 137.18)
        self.assertEqual(result["net_margin"], 27.62)
        self.assertEqual(result["debt_to_equity"], 1.3547)
        self.assertEqual(result["dividend_yield"], 0.505)

    @patch("finnhub_client._session.get")
    def test_missing_market_cap_pe_peg_and_growth_fields_degrade_to_none(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"metric": {"52WeekLow": 629.28, "52WeekHigh": 779.37}}
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertIsNone(result["market_cap"])
        self.assertIsNone(result["pe_ratio"])
        self.assertIsNone(result["peg_ratio"])
        self.assertIsNone(result["revenue_growth"])
        self.assertIsNone(result["eps_growth"])
        self.assertIsNone(result["roe"])
        self.assertIsNone(result["net_margin"])
        self.assertIsNone(result["debt_to_equity"])
        self.assertIsNone(result["dividend_yield"])

    @patch("finnhub_client._session.get")
    def test_pe_falls_back_through_alternate_fields(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "peBasicExclExtraTTM": 18.5,
                }
            }
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertEqual(result["pe_ratio"], 18.5)

    @patch("finnhub_client._session.get")
    def test_peg_falls_back_to_forward_peg(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "metric": {
                    "52WeekLow": 1.0,
                    "52WeekHigh": 2.0,
                    "forwardPEG": 1.8,
                }
            }
        )

        result = fetch_stock_metrics("SPY", api_key="test-key")

        self.assertEqual(result["peg_ratio"], 1.8)

    @patch("finnhub_client._session.get")
    def test_raises_on_missing_metric(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"metric": {}})

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("BADSYM", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("SPY", api_key="test-key")


class TestFetchMarketNews(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_filters_to_top_news_category(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": "Stocks rally", "url": "https://a", "datetime": 2, "source": "CNBC"},
                {"category": "business", "headline": "Unrelated world news", "url": "https://b", "datetime": 1, "source": "Reuters"},
            ]
        )

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["headline"], "Stocks rally")
        self.assertEqual(result[0]["source"], "CNBC")

    @patch("finnhub_client._session.get")
    def test_respects_limit(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": f"Headline {i}", "url": f"https://{i}", "datetime": i}
                for i in range(20)
            ]
        )

        result = fetch_market_news(api_key="test-key", limit=5)

        self.assertEqual(len(result), 5)

    @patch("finnhub_client._session.get")
    def test_skips_articles_missing_headline_or_url(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"category": "top news", "headline": "", "url": "https://a", "datetime": 1},
                {"category": "top news", "headline": "Fine", "url": "", "datetime": 2},
            ]
        )

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(result, [])

    @patch("finnhub_client._session.get")
    def test_empty_response_returns_empty_list(self, mock_get):
        mock_get.return_value = Mock(json=lambda: [])

        result = fetch_market_news(api_key="test-key")

        self.assertEqual(result, [])

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_market_news(api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_market_news(api_key=None)


class TestFetchCompanyIndustry(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_returns_finnhub_industry(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"finnhubIndustry": "Semiconductors"})

        result = fetch_company_industry("AMD", api_key="test-key")

        self.assertEqual(result, "Semiconductors")

    @patch("finnhub_client._session.get")
    def test_missing_industry_returns_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {})

        result = fetch_company_industry("SPY", api_key="test-key")

        self.assertIsNone(result)

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_company_industry("AMD", api_key="test-key")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_api_key(self):
        with self.assertRaises(FinnhubApiError):
            fetch_company_industry("AMD", api_key=None)


if __name__ == "__main__":
    unittest.main()


class TestFetchStockMetricsForScreener(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_parses_roi_from_roi_ttm(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"metric": {"52WeekLow": 1.0, "52WeekHigh": 2.0, "roiTTM": 11.4}})

        self.assertEqual(fetch_stock_metrics("DSP", api_key="test-key")["roi"], 11.4)

    @patch("finnhub_client._session.get")
    def test_missing_range_raises_by_default(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"metric": {"roiTTM": 11.4}})

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("DSP", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_missing_range_is_none_when_not_required(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"metric": {"roiTTM": 11.4, "marketCapitalization": 120.0}})

        result = fetch_stock_metrics("DSP", api_key="test-key", require_range=False)

        self.assertIsNone(result["low"])
        self.assertIsNone(result["high"])
        self.assertEqual(result["roi"], 11.4)
        self.assertEqual(result["market_cap"], 120.0)


class TestFetchCompanyProfile(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_parses_name_market_cap_and_ipo_date(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {"name": "Viant Technology Inc.", "marketCapitalization": 851.2, "ipo": "2021-02-18"}
        )

        result = fetch_company_profile("DSP", api_key="test-key")

        self.assertEqual(result, {"name": "Viant Technology Inc.", "market_cap": 851.2, "ipo_date": "2021-02-18"})

    @patch("finnhub_client._session.get")
    def test_empty_profile_is_all_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {})

        self.assertEqual(
            fetch_company_profile("ZZZZ", api_key="test-key"),
            {"name": None, "market_cap": None, "ipo_date": None},
        )

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_company_profile("DSP", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_a_profile_that_is_not_an_object_raises_a_finnhub_error(self, mock_get):
        mock_get.return_value = Mock(json=lambda: ["not", "an", "object"])

        with self.assertRaises(FinnhubApiError):
            fetch_company_profile("DSP", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_a_non_numeric_market_cap_raises_a_finnhub_error(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"name": "X", "marketCapitalization": "n/a"})

        with self.assertRaises(FinnhubApiError):
            fetch_company_profile("DSP", api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_a_non_json_body_raises_a_finnhub_error(self, mock_get):
        def bad_json():
            raise ValueError("not json")

        mock_get.return_value = Mock(json=bad_json)

        with self.assertRaises(FinnhubApiError):
            fetch_company_profile("DSP", api_key="test-key")


class TestFetchNextEarningsDate(unittest.TestCase):
    TODAY = date(2026, 10, 20)

    def fetch(self, entries, mock_get):
        mock_get.return_value = Mock(status_code=200, json=lambda: {"earningsCalendar": entries})
        return fetch_next_earnings_date("FN", self.TODAY, api_key="test-key")

    @patch("finnhub_client._session.get")
    def test_returns_the_earliest_listed_date(self, mock_get):
        entries = [{"date": "2027-02-01"}, {"date": "2026-11-09"}]

        self.assertEqual(self.fetch(entries, mock_get), "2026-11-09")

    @patch("finnhub_client._session.get")
    def test_none_when_nothing_is_listed_or_the_body_is_empty(self, mock_get):
        self.assertIsNone(self.fetch([], mock_get))
        mock_get.return_value = Mock(status_code=200, json=lambda: {})
        self.assertIsNone(fetch_next_earnings_date("FN", self.TODAY, api_key="k"))

    @patch("finnhub_client._session.get")
    def test_asks_for_the_120_days_after_today(self, mock_get):
        self.fetch([], mock_get)

        params = mock_get.call_args.kwargs["params"]
        self.assertEqual((params["symbol"], params["from"], params["to"]), ("FN", "2026-10-21", "2027-02-17"))

    @patch("finnhub_client._session.get")
    def test_a_bad_date_or_a_request_problem_is_a_finnhub_error(self, mock_get):
        with self.assertRaises(FinnhubApiError):
            self.fetch([{"date": "soon"}], mock_get)
        mock_get.side_effect = requests.ConnectionError("down")
        with self.assertRaises(FinnhubApiError):
            fetch_next_earnings_date("FN", self.TODAY, api_key="k")


class TestFetchUsCommonStocks(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_keeps_only_nasdaq_nyse_common_stock_sorted(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: [
                {"symbol": "MSFT", "type": "Common Stock", "mic": "XNAS"},
                {"symbol": "BRK.A", "type": "Common Stock", "mic": "XNYS"},
                {"symbol": "SPY", "type": "ETP", "mic": "ARCX"},
                {"symbol": "AAAA", "type": "Common Stock", "mic": "OOTC"},
                {"symbol": "WARR", "type": "Warrant", "mic": "XNAS"},
                {"symbol": "ADRX", "type": "ADR", "mic": "XNYS"},
            ]
        )

        self.assertEqual(fetch_us_common_stocks(api_key="test-key"), ["BRK.A", "MSFT"])

    @patch("finnhub_client._session.get")
    def test_raises_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(FinnhubApiError):
            fetch_us_common_stocks(api_key="test-key")


class TestRateLimited(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_a_429_raises_rate_limited_which_is_a_finnhub_error(self, mock_get):
        mock_get.return_value = Mock(status_code=429)

        for call in (
            lambda: fetch_company_profile("DSP", api_key="k"),
            lambda: fetch_stock_metrics("DSP", api_key="k"),
            lambda: fetch_us_common_stocks(api_key="k"),
            lambda: fetch_next_earnings_date("DSP", date(2026, 10, 20), api_key="k"),
        ):
            with self.assertRaises(FinnhubRateLimited) as ctx:
                call()
            self.assertIsInstance(ctx.exception, FinnhubApiError)

    @patch("finnhub_client._session.get")
    def test_a_429_is_not_retried(self, mock_get):
        mock_get.return_value = Mock(status_code=429)

        with self.assertRaises(FinnhubRateLimited):
            fetch_company_profile("DSP", api_key="k")

        self.assertEqual(mock_get.call_count, 1)


class TestTokenIsRedactedFromErrors(unittest.TestCase):
    @patch("finnhub_client._session.get")
    def test_a_failed_request_message_never_carries_the_api_key(self, mock_get):
        mock_get.side_effect = requests.ConnectionError(
            "Max retries exceeded with url: /api/v1/stock/profile2?symbol=X&token=SECRETKEY (Caused by x)"
        )

        for call in (
            lambda: fetch_company_profile("X", api_key="SECRETKEY"),
            lambda: fetch_stock_metrics("X", api_key="SECRETKEY"),
            lambda: fetch_us_common_stocks(api_key="SECRETKEY"),
            lambda: fetch_quote("X", api_key="SECRETKEY"),
            lambda: fetch_next_earnings_date("X", date(2026, 10, 20), api_key="SECRETKEY"),
        ):
            with self.assertRaises(FinnhubApiError) as ctx:
                call()
            self.assertNotIn("SECRETKEY", str(ctx.exception))

    @patch("finnhub_client._session.get")
    def test_a_non_json_metric_body_raises_a_finnhub_error(self, mock_get):
        def bad_json():
            raise ValueError("not json")

        mock_get.return_value = Mock(json=bad_json)

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("X", api_key="k")

    @patch("finnhub_client._session.get")
    def test_a_null_metric_body_raises_a_finnhub_error(self, mock_get):
        mock_get.return_value = Mock(json=lambda: None)

        with self.assertRaises(FinnhubApiError):
            fetch_stock_metrics("X", api_key="k")

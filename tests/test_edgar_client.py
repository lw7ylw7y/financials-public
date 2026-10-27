import os
import sys
import unittest
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener")):
    sys.path.insert(0, _p)

import requests
import edgar_client
from edgar_client import (
    EdgarApiError,
    EdgarRateLimited,
    fetch_company_facts,
    fetch_latest_report_date,
    fetch_submissions_summary,
    fetch_ticker_ciks,
    lookup_cik,
)

CONTACT = {"SEC_CONTACT": "Test Person test@example.com"}


def _response(status=200, body=None):
    return Mock(status_code=status, json=lambda: body)


@patch.dict(os.environ, CONTACT)
@patch("edgar_client._pace")
class TestRequests(unittest.TestCase):
    @patch("edgar_client._session.get")
    def test_sends_the_contact_as_user_agent(self, mock_get, _pace):
        mock_get.return_value = _response(body={})

        fetch_ticker_ciks()

        self.assertEqual(mock_get.call_args.kwargs["headers"], {"User-Agent": "Test Person test@example.com"})

    @patch("edgar_client._session.get")
    def test_refuses_to_call_edgar_without_a_contact(self, mock_get, _pace):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EdgarApiError):
                fetch_ticker_ciks()

        mock_get.assert_not_called()

    @patch("edgar_client._session.get")
    def test_429_and_403_raise_rate_limited_and_are_not_retried(self, mock_get, _pace):
        for status in (429, 403):
            mock_get.reset_mock()
            mock_get.return_value = _response(status)

            with self.assertRaises(EdgarRateLimited):
                fetch_company_facts(1)

            self.assertEqual(mock_get.call_count, 1)

    @patch("edgar_client._session.get")
    def test_other_errors_raise_a_plain_edgar_error(self, mock_get, _pace):
        mock_get.return_value = _response(500)

        with self.assertRaises(EdgarApiError) as ctx:
            fetch_company_facts(1)

        self.assertNotIsInstance(ctx.exception, EdgarRateLimited)

    @patch("edgar_client._session.get")
    def test_connection_errors_raise_an_edgar_error(self, mock_get, _pace):
        mock_get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(EdgarApiError):
            fetch_company_facts(1)

    @patch("edgar_client._session.get")
    def test_a_404_is_none_not_an_error(self, mock_get, _pace):
        mock_get.return_value = _response(404)

        self.assertIsNone(fetch_company_facts(1))
        self.assertIsNone(fetch_submissions_summary(1))

    @patch("edgar_client._session.get")
    def test_urls_pad_the_cik_to_ten_digits(self, mock_get, _pace):
        mock_get.return_value = _response(body={})

        fetch_company_facts(1851961)
        fetch_submissions_summary(1851961)

        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(urls[0], "https://data.sec.gov/api/xbrl/companyfacts/CIK0001851961.json")
        self.assertEqual(urls[1], "https://data.sec.gov/submissions/CIK0001851961.json")

    @patch("edgar_client._session.get")
    def test_parses_the_ticker_file(self, mock_get, _pace):
        mock_get.return_value = _response(
            body={"0": {"cik_str": 1851961, "ticker": "GCTS", "title": "GCT"}, "1": {"cik_str": 1067983, "ticker": "BRK-A", "title": "x"}}
        )

        self.assertEqual(fetch_ticker_ciks(), {"GCTS": 1851961, "BRK-A": 1067983})

    @patch("edgar_client._session.get")
    def test_a_malformed_ticker_file_raises_an_edgar_error(self, mock_get, _pace):
        for body in ({"0": {"ticker": "X"}}, {"0": "not a dict"}, {"0": {"cik_str": "abc", "ticker": "X"}}):
            mock_get.return_value = _response(body=body)

            with self.assertRaises(EdgarApiError):
                fetch_ticker_ciks()

    @patch("edgar_client._session.get")
    def test_parses_the_submissions_summary(self, mock_get, _pace):
        mock_get.return_value = _response(
            body={"name": "GCT Semiconductor", "sic": "3674", "sicDescription": "Semiconductors & Related Devices"}
        )

        self.assertEqual(
            fetch_submissions_summary(1851961),
            {"name": "GCT Semiconductor", "sic": 3674, "sic_description": "Semiconductors & Related Devices"},
        )

    @patch("edgar_client._session.get")
    def test_the_latest_report_date_is_the_newest_quarterly_or_annual_filing(self, mock_get, _pace):
        mock_get.return_value = _response(body={"filings": {"recent": {
            "form": ["8-K", "10-Q", "10-Q/A", "10-K", "4", "10-Q"],
            "filingDate": ["2026-09-30", "2026-08-06", "2026-09-01", "2026-02-20", "2026-10-01", "2025-11-07"],
        }}})

        self.assertEqual(fetch_latest_report_date(1), "2026-08-06")

    @patch("edgar_client._session.get")
    def test_a_foreign_filers_annual_report_counts_and_its_6ks_do_not(self, mock_get, _pace):
        mock_get.return_value = _response(body={"filings": {"recent": {
            "form": ["6-K", "20-F", "6-K"], "filingDate": ["2026-08-12", "2026-03-26", "2026-05-12"]}}})

        self.assertEqual(fetch_latest_report_date(1), "2026-03-26")

    @patch("edgar_client._session.get")
    def test_no_report_forms_or_an_unknown_company_is_none(self, mock_get, _pace):
        mock_get.return_value = _response(body={"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-09-30"]}}})
        self.assertIsNone(fetch_latest_report_date(1))
        mock_get.return_value = _response(status=404)
        self.assertIsNone(fetch_latest_report_date(1))

    @patch("edgar_client._session.get")
    def test_an_unexpected_submissions_shape_is_an_edgar_error(self, mock_get, _pace):
        mock_get.return_value = _response(body={"filings": {}})

        with self.assertRaises(EdgarApiError):
            fetch_latest_report_date(1)

    @patch("edgar_client._session.get")
    def test_a_missing_or_blank_sic_is_none(self, mock_get, _pace):
        for body in ({"name": "X"}, {"name": "X", "sic": ""}):
            mock_get.return_value = _response(body=body)

            self.assertIsNone(fetch_submissions_summary(1)["sic"])


class TestLookupCik(unittest.TestCase):
    CIKS = {"MSFT": 789019, "BRK-A": 1067983}

    def test_finds_a_plain_ticker(self):
        self.assertEqual(lookup_cik("MSFT", self.CIKS), 789019)

    def test_finds_a_dotted_class_share_by_its_hyphen_form(self):
        self.assertEqual(lookup_cik("BRK.A", self.CIKS), 1067983)

    def test_unknown_ticker_is_none(self):
        self.assertIsNone(lookup_cik("ZZZZ", self.CIKS))
        self.assertIsNone(lookup_cik("ZZ.Z", self.CIKS))


class TestPacing(unittest.TestCase):
    @patch("edgar_client.time.sleep")
    @patch("edgar_client.time.monotonic")
    def test_waits_to_keep_under_five_requests_a_second(self, mock_monotonic, mock_sleep):
        edgar_client._last_request_at = 100.0
        mock_monotonic.return_value = 100.05

        edgar_client._pace()

        self.assertAlmostEqual(mock_sleep.call_args.args[0], 0.15, places=2)

    @patch("edgar_client.time.sleep")
    @patch("edgar_client.time.monotonic")
    def test_does_not_wait_when_enough_time_has_passed(self, mock_monotonic, mock_sleep):
        edgar_client._last_request_at = 100.0
        mock_monotonic.return_value = 101.0

        edgar_client._pace()

        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

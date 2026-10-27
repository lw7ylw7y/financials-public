import os
import sys
import unittest
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

import app as app_module
import google_auth
import scoring
import settings as screener_settings
from kv_store import KvStoreError

NO_AUTH_ENV = {"GOOGLE_CLIENT_ID": ""}
AUTH_ENV = {
    "GOOGLE_CLIENT_ID": "client-id",
    "GOOGLE_CLIENT_SECRET": "client-secret",
    "ALLOWED_EMAIL": "Me@Example.com",
    "SECRET_KEY": "test-secret-key",
}


class TestDashboardAuth(unittest.TestCase):
    """Google sign-in gate in front of every route, on only when
    GOOGLE_CLIENT_ID is set. Data/network calls are mocked out -- this
    is testing the auth gate, not page content.
    """

    def setUp(self):
        self.client = app_module.app.test_client()
        for target, value in (
            ("app.get_initial_page_data", {"table": {}, "countdown": {"entries": []}, "ai_result": None}),
            ("app.get_initial_ticker_page_data", {}),
            ("app.get_initial_market_news", {"headlines": [], "pending": False}),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sign_in(self, email="me@example.com"):
        with self.client.session_transaction() as sess:
            sess["email"] = email

    def test_no_client_id_allows_request_without_signing_in(self):
        with mock.patch.dict(os.environ, NO_AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_page_redirects_to_login_when_signed_out(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_api_routes_return_401_not_a_redirect_when_signed_out(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            for path in (
                "/api/check",
                "/api/tickers/groups/stocks/check",
                "/api/market-news/check",
                "/api/reads/history",
                "/api/screener/quotes?symbols=AAA",
            ):
                self.assertEqual(self.client.get(path).status_code, 401, path)
            self.assertEqual(self.client.post("/api/tickers/add", json={}).status_code, 401)
            self.assertEqual(self.client.post("/api/tickers/remove", json={}).status_code, 401)
            self.assertEqual(self.client.post("/api/screener/status", json={}).status_code, 401)
            self.assertEqual(self.client.post("/api/screener/note", json={}).status_code, 401)

    def test_the_screener_page_redirects_to_login_when_signed_out(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/screener")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_signed_in_allowed_email_can_view_the_page(self):
        self.sign_in("me@example.com")
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_session_for_a_different_email_is_rejected(self):
        self.sign_in("someone-else@example.com")
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)

    def test_partial_config_fails_closed_instead_of_opening_the_dashboard(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "client-id", "GOOGLE_CLIENT_SECRET": "",
                                          "ALLOWED_EMAIL": "", "SECRET_KEY": ""}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("ALLOWED_EMAIL", response.get_data(as_text=True))

    def test_login_redirects_to_google_and_remembers_state(self):
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/login")
            with self.client.session_transaction() as sess:
                state = sess["oauth_state"]

        location = response.headers["Location"]
        self.assertTrue(location.startswith("https://accounts.google.com/"))
        self.assertIn(f"state={state}", location)
        self.assertIn("client_id=client-id", location)
        self.assertIn("auth%2Fcallback", location)

    def callback(self, email, state="abc", session_state="abc", code="the-code", error=None):
        with self.client.session_transaction() as sess:
            if session_state is not None:
                sess["oauth_state"] = session_state
        with mock.patch.dict(os.environ, AUTH_ENV), mock.patch(
            "app.google_auth.fetch_verified_email", return_value=email, side_effect=error
        ) as fetch:
            query = f"?state={state}" + (f"&code={code}" if code else "")
            return self.client.get("/auth/callback" + query), fetch

    def test_callback_signs_in_the_allowed_email(self):
        response, _ = self.callback("me@example.com")

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["email"], "me@example.com")
        with mock.patch.dict(os.environ, AUTH_ENV):
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_callback_rejects_a_different_google_account(self):
        response, _ = self.callback("stranger@example.com")

        self.assertEqual(response.status_code, 403)
        with self.client.session_transaction() as sess:
            self.assertNotIn("email", sess)

    def test_callback_rejects_an_unverified_email(self):
        response, _ = self.callback(None)

        self.assertEqual(response.status_code, 403)

    def test_callback_rejects_a_state_mismatch_without_calling_google(self):
        response, fetch = self.callback("me@example.com", state="forged", session_state="abc")

        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_callback_rejects_a_missing_session_state(self):
        response, fetch = self.callback("me@example.com", session_state=None)

        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_callback_rejects_a_missing_code(self):
        response, fetch = self.callback("me@example.com", code=None)

        self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    def test_callback_reports_a_google_failure(self):
        response, _ = self.callback("me@example.com", error=google_auth.GoogleAuthError("down"))

        self.assertEqual(response.status_code, 502)

    def test_state_cannot_be_replayed(self):
        self.callback("me@example.com")
        with self.client.session_transaction() as sess:
            sess.pop("email")
        with mock.patch.dict(os.environ, AUTH_ENV):
            response = self.client.get("/auth/callback?state=abc&code=the-code")

        self.assertEqual(response.status_code, 400)

    def test_logout_ends_the_session(self):
        self.sign_in()
        with mock.patch.dict(os.environ, AUTH_ENV):
            self.client.get("/logout")
            response = self.client.get("/")

        self.assertEqual(response.status_code, 302)


class TestApiCheckTickerGroup(unittest.TestCase):
    """The ticker page's background check hits one route per group
    instead of one combined /api/check-tickers, so a group with fewer
    tickers repaints before a slower one finishes."""

    def setUp(self):
        self.client = app_module.app.test_client()
        self.env_patcher = mock.patch.dict(os.environ, NO_AUTH_ENV)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_known_group_returns_only_that_groups_html(self):
        with (
            mock.patch("app.load_ticker_config", return_value={"stocks": ["SPY"], "bonds": ["VGIT"]}),
            mock.patch("app.check_for_ticker_updates") as mock_check,
        ):
            pending_fields = ("price", "change", "change_percent", "week52_low", "week52_high",
                              "pct_off_high", "market_cap", "pe_ratio")
            pending_card = {field: None for field in pending_fields}
            pending_card.update(symbol="SPY", group="stocks", pending=True, error=None)
            mock_check.return_value = {"stocks": [pending_card]}
            response = self.client.get("/api/tickers/groups/stocks/check")

        mock_check.assert_called_once_with(config={"stocks": ["SPY"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SPY", response.get_json()["group_html"])

    def test_the_group_check_carries_verdicts_for_the_scored_cards_only(self):
        def card(symbol, off_high, ret, **extra):
            return {"symbol": symbol, "group": "stocks", "price": 90.0, "change": 0.0, "change_percent": 0.0,
                    "week52_low": 80.0, "week52_high": 100.0, "pct_off_high": off_high, "market_cap": None,
                    "pe_ratio": None, "peg_ratio": None, "return_26w": ret, "error": None, "pending": False, **extra}
        cards = [card("AAA", 20.0, -5.0), card("BBB", 10.0, 5.0), card("CCC", 5.0, 30.0),
                 card("ERR", None, None, error="boom", price=None)]
        with mock.patch("app.load_ticker_config", return_value={"stocks": ["AAA", "BBB", "CCC", "ERR"]}), \
             mock.patch("app.check_for_ticker_updates", return_value={"stocks": cards}):
            html = self.client.get("/api/tickers/groups/stocks/check").get_json()["group_html"]

        self.assertIn('class="verdict-pill"', html)
        self.assertIn("verdict-tip-stocks-AAA", html)

    def test_a_group_with_no_scorable_card_still_renders(self):
        errored = {"symbol": "ERR", "group": "stocks", "price": None, "change": None, "change_percent": None,
                   "week52_low": None, "week52_high": None, "pct_off_high": None, "market_cap": None,
                   "pe_ratio": None, "peg_ratio": None, "error": "boom", "pending": False}
        with mock.patch("app.load_ticker_config", return_value={"stocks": ["ERR"]}), \
             mock.patch("app.check_for_ticker_updates", return_value={"stocks": [errored]}):
            response = self.client.get("/api/tickers/groups/stocks/check")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Not judged", response.get_json()["group_html"])

    def test_unknown_group_returns_404_without_fetching(self):
        with (
            mock.patch("app.load_ticker_config", return_value={"stocks": ["SPY"]}),
            mock.patch("app.check_for_ticker_updates") as mock_check,
        ):
            response = self.client.get("/api/tickers/groups/nonexistent/check")

        mock_check.assert_not_called()
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.get_json())


class TestReadsHistoryRoute(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)

    def entry(self):
        return {"groups": {g: {"read": "mixed", "score": 0.0, "scored": 3, "total": 3} for g in ("leading", "coincident", "lagging")},
                "stance": None, "source": "live", "saved_at": "2026-10-22T00:00:00+00:00"}

    def test_it_returns_the_card(self):
        with mock.patch("app.reads_history.load_reads", return_value={"2026-10": self.entry()}), \
             mock.patch("app.reads_history.load_recessions", return_value={}):
            response = self.client.get("/api/reads/history")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Reads over time", response.get_json()["history_html"])
        self.assertIn("history-pane", response.get_json()["history_html"])

    def test_redis_down_returns_the_unavailable_card_with_200(self):
        with mock.patch("app.reads_history.load_reads", side_effect=KvStoreError("down")):
            response = self.client.get("/api/reads/history")

        self.assertEqual(response.status_code, 200)
        self.assertIn("History is unavailable right now.", response.get_json()["history_html"])

    def test_unreadable_recession_flags_also_give_the_unavailable_card(self):
        with mock.patch("app.reads_history.load_reads", return_value={"2026-10": self.entry()}), \
             mock.patch("app.reads_history.load_recessions", side_effect=KvStoreError("down")):
            response = self.client.get("/api/reads/history")

        self.assertIn("History is unavailable right now.", response.get_json()["history_html"])

    def test_nothing_saved_yet_says_so(self):
        with mock.patch("app.reads_history.load_reads", return_value={}), \
             mock.patch("app.reads_history.load_recessions", return_value={}):
            response = self.client.get("/api/reads/history")

        self.assertIn("No reads have been saved yet", response.get_json()["history_html"])

    def test_the_digest_page_has_a_loading_placeholder_for_it(self):
        with mock.patch("app.get_initial_page_data", return_value={"table": {}, "countdown": {"entries": []}, "ai_result": None}):
            html = self.client.get("/").get_data(as_text=True)

        self.assertIn('id="history-section"', html)
        self.assertIn("Loading history", html)


class TestApiCheckMarketNews(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.env_patcher = mock.patch.dict(os.environ, NO_AUTH_ENV)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_returns_news_html(self):
        with mock.patch("app.check_for_market_news", return_value={"headlines": [], "pending": False}):
            response = self.client.get("/api/market-news/check")

        self.assertEqual(response.status_code, 200)
        self.assertIn("news_html", response.get_json())


CANDIDATE = {"name": "Acme", "week52_low": 8.0, "week52_high": 15.0, "market_cap": 3000.0}


class TestScreenerRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)

    def get_quotes(self, symbols, candidates=None, quotes=None):
        candidates = {"AAA": CANDIDATE, "BBB": CANDIDATE} if candidates is None else candidates
        with mock.patch("app.screener_store.load_candidates", return_value=candidates), \
             mock.patch("app.quotes.get_quotes", return_value=quotes if quotes is not None else {}) as get_quotes:
            return self.client.get(f"/api/screener/quotes?symbols={symbols}"), get_quotes

    def test_the_page_renders_the_view(self):
        with mock.patch("app.screener_page.load_view", return_value={"v": 1}) as load, \
             mock.patch("app.screener_page.render_screener_page", return_value="PAGE") as render:
            response = self.client.get("/screener?tab=shortlisted")

        self.assertEqual((response.status_code, response.get_data(as_text=True)), (200, "PAGE"))
        render.assert_called_once_with({"v": 1}, "shortlisted")

    def test_a_storage_failure_shows_the_error_page_with_a_503(self):
        with mock.patch("app.screener_page.load_view", side_effect=KvStoreError("down")):
            response = self.client.get("/screener")

        self.assertEqual(response.status_code, 503)
        self.assertIn("Couldn&#x27;t load the screener data", response.get_data(as_text=True))

    def test_quotes_returns_the_rendered_cells_and_the_computed_position_in_range(self):
        quote = {"price": 12.0, "change": 0.3, "change_percent": 2.5, "quoted_at": "2026-10-20T15:00:00+00:00"}
        response, get_quotes = self.get_quotes("AAA,BBB", quotes={"AAA": quote, "BBB": None})

        body = response.get_json()["quotes"]
        self.assertEqual(response.status_code, 200)
        self.assertIn("$12.00", body["AAA"]["html"])
        self.assertAlmostEqual(body["AAA"]["pct_in_range"], 4 / 7 * 100)
        self.assertEqual(body["AAA"]["change_percent"], 2.5)
        self.assertIsNone(body["BBB"]["pct_in_range"])
        self.assertIn("n/a", body["BBB"]["html"])
        self.assertEqual(get_quotes.call_args.args[0], ["AAA", "BBB"])

    def test_a_price_above_the_stored_high_comes_back_clamped_at_100(self):
        quote = {"price": 20.0, "change": 1.0, "change_percent": 5.0, "quoted_at": "2026-10-20T15:00:00+00:00"}
        response, _ = self.get_quotes("AAA", quotes={"AAA": quote})

        self.assertEqual(response.get_json()["quotes"]["AAA"]["pct_in_range"], 100.0)

    def test_quotes_rejects_a_missing_list_a_bad_symbol_and_a_batch_over_25(self):
        many = ",".join(f"S{i}" for i in range(26))
        for query in ("", "AAA,bad%20symbol", many):
            with self.subTest(query=query[:20]):
                response, get_quotes = self.get_quotes(query)
                self.assertEqual(response.status_code, 400)
                get_quotes.assert_not_called()

    def test_quotes_accepts_exactly_25_symbols_and_a_class_share(self):
        symbols = [f"S{i}" for i in range(24)] + ["MOG.A"]
        response, get_quotes = self.get_quotes(",".join(symbols), candidates={s: CANDIDATE for s in symbols})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(get_quotes.call_args.args[0]), 25)

    def test_quotes_fetches_a_repeated_symbol_once(self):
        _, get_quotes = self.get_quotes("AAA,AAA,BBB")

        self.assertEqual(get_quotes.call_args.args[0], ["AAA", "BBB"])

    def test_quotes_refuses_a_symbol_with_no_candidate_record_without_fetching(self):
        response, get_quotes = self.get_quotes("AAA,ZZZ")

        self.assertEqual(response.status_code, 400)
        get_quotes.assert_not_called()

    def test_quotes_storage_failure_is_a_503_not_an_empty_answer(self):
        with mock.patch("app.screener_store.load_candidates", side_effect=KvStoreError("down")):
            response = self.client.get("/api/screener/quotes?symbols=AAA")

        self.assertEqual(response.status_code, 503)


PASSING_CANDIDATE = {
    **CANDIDATE, "ipo_date": "2015-01-01", "revenue_growth": 15.0, "dilution_pct_per_year": 1.0, "flags": [],
    "fcf_by_year": {"2025-12-31": 54.0},
    "metrics": {"roi": 12.0, "net_margin": 10.0, "debt_to_equity": 0.1},
}


class TestScreenerTriageRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.candidates = {"AAA": CANDIDATE}

    def post_status(self, body, load=None, existing=None):
        with mock.patch("app.screener_store.load_candidates", return_value=self.candidates, side_effect=load), \
             mock.patch("app.screener_settings.load_settings", return_value=scoring.DEFAULT_SETTINGS), \
             mock.patch("app.page_store.load_status", return_value=existing), \
             mock.patch("app.page_store.save_status") as save, mock.patch("app.page_store.clear_status") as clear:
            response = self.client.post("/api/screener/status", json=body)
        return response, save, clear

    def post_note(self, body, candidate=CANDIDATE, **patches):
        with mock.patch("app.screener_store.load_candidate", return_value=candidate), \
             mock.patch("app.page_store.save_note", **patches.get("save", {})) as save, \
             mock.patch("app.page_store.clear_note", **patches.get("clear", {})) as clear:
            response = self.client.post("/api/screener/note", json=body)
        return response, save, clear

    def test_shortlisting_writes_one_status_entry(self):
        response, save, clear = self.post_status({"symbol": "AAA", "status": "shortlisted"})

        self.assertEqual(response.get_json(), {"ok": True, "status": "shortlisted", "lands": None})
        self.assertEqual(save.call_args.args[0], "AAA")
        self.assertEqual(save.call_args.args[1]["status"], "shortlisted")
        self.assertNotIn("score_at_dismissal", save.call_args.args[1])
        clear.assert_not_called()

    def test_setting_a_status_keeps_the_entrys_checked_at(self):
        response, save, _ = self.post_status({"symbol": "AAA", "status": "shortlisted"},
                                             existing={"status": "dismissed", "at": "x", "checked_at": "2026-10-20"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(save.call_args.args[1]["checked_at"], "2026-10-20")

    def test_a_first_status_has_no_checked_at(self):
        _, save, _ = self.post_status({"symbol": "AAA", "status": "shortlisted"})

        self.assertNotIn("checked_at", save.call_args.args[1])

    def test_dismissing_records_the_score_and_pass_state_computed_on_the_server(self):
        with mock.patch("app.scoring.dismissal_snapshot", return_value={"score_at_dismissal": 61.5, "passed_at_dismissal": True}) as snap:
            response, save, _ = self.post_status({"symbol": "AAA", "status": "dismissed", "score_at_dismissal": 99})

        entry = save.call_args.args[1]
        self.assertEqual((entry["status"], entry["score_at_dismissal"], entry["passed_at_dismissal"]), ("dismissed", 61.5, True))
        snap.assert_called_once()
        self.assertEqual(response.status_code, 200)

    def test_new_clears_the_status_and_says_where_the_name_now_shows(self):
        self.candidates = {"AAA": PASSING_CANDIDATE}

        response, save, clear = self.post_status({"symbol": "AAA", "status": "new"})

        clear.assert_called_once_with("AAA")
        save.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["lands"], "new")

    def test_a_cleared_name_that_fails_a_filter_lands_in_hidden_not_new(self):
        self.candidates = {"AAA": {**PASSING_CANDIDATE, "metrics": {**PASSING_CANDIDATE["metrics"], "net_margin": -5.0}}}

        response, _, _ = self.post_status({"symbol": "AAA", "status": "new"})

        self.assertEqual(response.get_json()["lands"], "hidden")

    def test_a_body_that_is_not_a_json_object_is_a_400_on_both_routes(self):
        for body in ([1], "x", 5, None):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/screener/status", json=body).status_code, 400)
                self.assertEqual(self.client.post("/api/screener/note", json=body).status_code, 400)

    def test_a_symbol_with_a_trailing_newline_is_refused(self):
        response, save, _ = self.post_status({"symbol": "AAA\n", "status": "shortlisted"})

        self.assertEqual(response.status_code, 400)
        save.assert_not_called()

    def test_a_bad_symbol_status_or_unknown_name_is_a_400_and_writes_nothing(self):
        for body in ({"symbol": "bad symbol", "status": "dismissed"}, {"symbol": "AAA", "status": "deleted"},
                     {"symbol": "ZZZ", "status": "dismissed"}, {"status": "dismissed"}, {"symbol": 5, "status": "new"}):
            with self.subTest(body=body):
                response, save, clear = self.post_status(body)
                self.assertEqual(response.status_code, 400)
                save.assert_not_called()
                clear.assert_not_called()

    def test_a_failed_read_fails_the_dismissal_with_a_503_and_writes_nothing(self):
        response, save, _ = self.post_status({"symbol": "AAA", "status": "dismissed"}, load=KvStoreError("down"))

        self.assertEqual(response.status_code, 503)
        save.assert_not_called()

    def test_a_failed_status_write_is_a_503(self):
        with mock.patch("app.screener_store.load_candidates", return_value=self.candidates), \
             mock.patch("app.page_store.save_status", side_effect=KvStoreError("down")):
            response = self.client.post("/api/screener/status", json={"symbol": "AAA", "status": "shortlisted"})

        self.assertEqual(response.status_code, 503)

    def test_a_class_share_symbol_is_accepted(self):
        self.candidates = {"MOG.A": CANDIDATE}

        response, save, _ = self.post_status({"symbol": "MOG.A", "status": "shortlisted"})

        self.assertEqual(response.status_code, 200)

    def test_a_note_is_saved_with_its_time(self):
        response, save, clear = self.post_note({"symbol": "AAA", "text": "check margins"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(save.call_args.args[1]["text"], "check margins")
        self.assertIn("at", save.call_args.args[1])
        clear.assert_not_called()

    def test_a_blank_note_clears_the_saved_one(self):
        response, save, clear = self.post_note({"symbol": "AAA", "text": "  \n "})

        clear.assert_called_once_with("AAA")
        save.assert_not_called()

    def test_a_note_of_exactly_2000_characters_saves_and_one_more_is_refused(self):
        ok, save, _ = self.post_note({"symbol": "AAA", "text": "x" * 2000})
        too_long, save_long, _ = self.post_note({"symbol": "AAA", "text": "x" * 2001})

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(too_long.get_json()["error"], "That note is too long (max 2,000 characters).")
        save_long.assert_not_called()

    def test_a_note_for_an_unknown_or_malformed_symbol_is_a_400(self):
        unknown, save, _ = self.post_note({"symbol": "ZZZ", "text": "t"}, candidate=None)
        malformed, _, _ = self.post_note({"symbol": "a b", "text": "t"})
        no_text, _, _ = self.post_note({"symbol": "AAA"})

        self.assertEqual((unknown.status_code, malformed.status_code, no_text.status_code), (400, 400, 400))
        save.assert_not_called()

    def test_markup_in_a_note_is_stored_as_given_and_escaped_only_on_render(self):
        _, save, _ = self.post_note({"symbol": "AAA", "text": "<b>x</b>"})

        self.assertEqual(save.call_args.args[1]["text"], "<b>x</b>")

    def test_the_note_text_never_reaches_a_log_even_when_the_write_fails(self):
        secret = "SECRET-NOTE-TEXT"
        with self.assertLogs("app", level="DEBUG") as logs:
            response, _, _ = self.post_note({"symbol": "AAA", "text": secret}, save={"side_effect": KvStoreError(f"down {secret}")})
            app_module.logger.error("sentinel so assertLogs has a record")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(secret, "\n".join(logs.output))


class TestScreenerSettingsRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.form = screener_settings.default_form()

    def patches(self, **overrides):
        passing = {**PASSING_CANDIDATE}
        stack = {
            "app.screener_store.load_candidates": {"return_value": {"AAA": passing, "BBB": {**passing, "metrics": {**passing["metrics"], "roi": 2.0}}}},
            "app.screener_store.load_universe": {"return_value": {"NEW": {"stage": "tech", "market_cap": 30000.0}}},
            "app.page_store.load_statuses": {"return_value": {}},
            "app.screener_settings.load_settings": {"return_value": scoring.DEFAULT_SETTINGS},
            "app.screener_settings.save_form": {},
            "app.page_store.save_status": {},
            "app.page_store.clear_status": {},
            "app.page_store.save_note": {},
            "app.page_store.clear_note": {},
        }
        for name, kwargs in overrides.items():
            stack[name.replace("__", ".")] = kwargs
        started = {}
        for target, kwargs in stack.items():
            patcher = mock.patch(target, **kwargs)
            started[target] = patcher.start()
            self.addCleanup(patcher.stop)
        return started

    def test_preview_counts_the_new_list_now_and_under_the_posted_filters_and_tonights_fetch(self):
        self.patches()
        self.form["min_roi_pct"] = {"value": 1.0, "on": True}
        self.form["market_cap_max_m"] = {"value": 40000.0}

        response = self.client.post("/api/screener/settings/preview", json={"settings": self.form})

        self.assertEqual(response.get_json(), {"would_show": 2, "now": 1, "fetch_tonight": 1})

    def test_preview_saves_nothing(self):
        started = self.patches()

        self.client.post("/api/screener/settings/preview", json={"settings": self.form})

        started["app.screener_settings.save_form"].assert_not_called()

    def test_an_invalid_value_is_a_400_with_a_message_for_the_field_and_nothing_is_saved(self):
        started = self.patches()
        self.form["max_debt_equity"] = {"value": -3.0, "on": True}

        for route in ("/api/screener/settings", "/api/screener/settings/preview"):
            with self.subTest(route=route):
                response = self.client.post(route, json={"settings": self.form})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(list(response.get_json()["errors"]), ["max_debt_equity"])
        started["app.screener_settings.save_form"].assert_not_called()

    def test_a_body_that_is_not_an_object_is_a_400(self):
        self.patches()

        for body in ([1], "x", None):
            self.assertEqual(self.client.post("/api/screener/settings", json=body).status_code, 400)

    def test_apply_saves_the_form_and_reports_the_new_list_size_without_touching_statuses_or_notes(self):
        started = self.patches()
        self.form["min_roi_pct"] = {"value": 1.0, "on": True}

        response = self.client.post("/api/screener/settings", json={"settings": self.form})

        self.assertEqual(response.get_json(), {"ok": True, "shown": 2})
        started["app.screener_settings.save_form"].assert_called_once()
        for untouched in ("save_status", "clear_status", "save_note", "clear_note"):
            started[f"app.page_store.{untouched}"].assert_not_called()

    def test_a_failed_save_is_a_503_and_reports_no_success(self):
        self.patches(app__screener_settings__save_form={"side_effect": KvStoreError("down")})

        response = self.client.post("/api/screener/settings", json={"settings": self.form})

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("ok", response.get_json())

    def test_a_save_that_worked_is_not_reported_as_failed_when_only_the_count_read_fails(self):
        started = self.patches(app__screener_store__load_candidates={"side_effect": KvStoreError("down")})

        response = self.client.post("/api/screener/settings", json={"settings": self.form})

        self.assertEqual((response.status_code, response.get_json()), (200, {"ok": True, "shown": None}))
        started["app.screener_settings.save_form"].assert_called_once()

    def test_a_failed_read_during_preview_is_a_503(self):
        self.patches(app__screener_store__load_candidates={"side_effect": KvStoreError("down")})

        response = self.client.post("/api/screener/settings/preview", json={"settings": self.form})

        self.assertEqual(response.status_code, 503)


class TestScreenerPromoteRoute(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)

    def post(self, body, candidate=CANDIDATE, **patches):
        with mock.patch("app.screener_store.load_candidate", return_value=candidate), \
             mock.patch("app.add_ticker_to_group", **patches) as add:
            response = self.client.post("/api/screener/promote", json=body)
        return response, add

    def test_promoting_adds_the_symbol_to_the_individual_group(self):
        response, add = self.post({"symbol": "AAA"})

        self.assertEqual((response.status_code, response.get_json()), (200, {"ok": True}))
        add.assert_called_once_with("AAA", "individual")

    def test_a_bad_symbol_or_a_body_that_is_not_an_object_is_a_400_and_adds_nothing(self):
        for body in ({"symbol": "AAA\n"}, {"symbol": ""}, {"symbol": 5}, {}, [1], "x", None):
            with self.subTest(body=body):
                response, add = self.post(body)
                self.assertEqual(response.status_code, 400)
                add.assert_not_called()

    def test_an_unknown_candidate_is_a_400_and_adds_nothing(self):
        response, add = self.post({"symbol": "ZZZ"}, candidate=None)

        self.assertEqual(response.status_code, 400)
        add.assert_not_called()

    def test_a_config_error_is_a_400_with_its_message(self):
        response, _ = self.post({"symbol": "AAA"}, side_effect=app_module.TickerConfigError("unknown group: 'individual'"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown group", response.get_json()["error"])

    def test_a_storage_failure_is_a_503(self):
        response, _ = self.post({"symbol": "AAA"}, side_effect=KvStoreError("down"))

        self.assertEqual(response.status_code, 503)

    def test_promoting_writes_no_status_and_no_note(self):
        with mock.patch("app.page_store.save_status") as save_status, mock.patch("app.page_store.save_note") as save_note:
            self.post({"symbol": "AAA"})

        save_status.assert_not_called()
        save_note.assert_not_called()

    def test_the_screener_page_passes_the_individual_group_to_the_view(self):
        view = mock.Mock(return_value={"state": {}})
        for known in (True, False):
            with self.subTest(known=known), \
                 mock.patch("app.load_ticker_config", return_value={"individual": ["AAA"], "stocks": ["SPY"]} if known else None,
                            side_effect=None if known else KvStoreError("down")), \
                 mock.patch("app.screener_page.load_view", view), mock.patch("app.screener_page.render_screener_page", return_value="ok"):
                self.client.get("/screener")
                kwargs = view.call_args.kwargs
                self.assertEqual((kwargs["watchlist"], kwargs["watchlist_known"]),
                                 (frozenset({"AAA"}), True) if known else (frozenset(), False))


class TestRemovingATickerClearsItsInvestedAmount(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)

    def remove(self, body, remove_side_effect=None, clear_side_effect=None):
        with mock.patch("app.remove_ticker_from_group", side_effect=remove_side_effect) as remove, \
             mock.patch("app.invested.set_amount", side_effect=clear_side_effect) as clear:
            response = self.client.post("/api/tickers/remove", json=body)
        return response, remove, clear

    def test_removing_from_the_individual_group_clears_the_amount(self):
        response, remove, clear = self.remove({"symbol": "aapl", "group": "individual"})

        self.assertEqual((response.status_code, response.get_json()), (200, {"ok": True}))
        remove.assert_called_once_with("aapl", "individual")
        clear.assert_called_once_with("AAPL", None)

    def test_removing_from_any_other_group_leaves_the_amounts_alone(self):
        _, _, clear = self.remove({"symbol": "SPY", "group": "stocks"})

        clear.assert_not_called()

    def test_a_refused_removal_clears_nothing(self):
        response, _, clear = self.remove({"symbol": "AAPL", "group": "nope"}, remove_side_effect=app_module.TickerConfigError("unknown group"))

        self.assertEqual(response.status_code, 400)
        clear.assert_not_called()

    def test_a_failed_clear_does_not_fail_the_removal_and_logs_only_the_error_class(self):
        with self.assertLogs("app", level="ERROR") as logs:
            response, _, _ = self.remove({"symbol": "AAPL", "group": "individual"}, clear_side_effect=KvStoreError("down 4242"))

        self.assertEqual((response.status_code, response.get_json()), (200, {"ok": True}))
        self.assertIn("KvStoreError", logs.output[0])
        self.assertNotIn("4242", "".join(logs.output))

    def test_a_blank_or_missing_symbol_clears_nothing(self):
        for body in ({"group": "individual"}, {"symbol": "  ", "group": "individual"}, {"symbol": 5, "group": "individual"}):
            with self.subTest(body=body):
                _, _, clear = self.remove(body)
                clear.assert_not_called()


class TestInvestedRoute(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)

    def post(self, body, **patches):
        with mock.patch("app.invested.set_amount", **patches) as set_amount:
            response = self.client.post("/api/invested", json=body)
        return response, set_amount

    def test_saving_an_amount_writes_one_symbol_and_returns_the_rendered_cell(self):
        response, set_amount = self.post({"symbol": "aapl", "amount": 1500.5})

        self.assertEqual(response.status_code, 200)
        set_amount.assert_called_once_with("AAPL", 1500.5)
        self.assertIn("$1,500.50", response.get_json()["cell_html"])
        self.assertIn('data-symbol="AAPL"', response.get_json()["cell_html"])

    def test_a_null_amount_clears_it_and_the_cell_shows_a_dash(self):
        response, set_amount = self.post({"symbol": "AAPL", "amount": None})

        set_amount.assert_called_once_with("AAPL", None)
        self.assertIn("&mdash;", response.get_json()["cell_html"])

    def test_zero_is_a_real_amount(self):
        response, set_amount = self.post({"symbol": "AAPL", "amount": 0})

        set_amount.assert_called_once_with("AAPL", 0)
        self.assertIn("$0", response.get_json()["cell_html"])

    def test_a_bad_symbol_is_a_400_and_writes_nothing(self):
        for body in ({"symbol": "AAPL\n", "amount": 1}, {"symbol": "", "amount": 1}, {"symbol": 5, "amount": 1}, {"amount": 1}, [1], "x", None):
            with self.subTest(body=body):
                response, set_amount = self.post(body)
                self.assertEqual(response.status_code, 400)
                set_amount.assert_not_called()

    def test_a_bad_amount_is_a_400_with_a_message_and_writes_nothing(self):
        for amount in (-1, "100", True, 1e12, float("nan"), [5], 10**400):
            with self.subTest(amount=amount):
                response, set_amount = self.post({"symbol": "AAPL", "amount": amount})
                self.assertEqual(response.status_code, 400)
                self.assertIn("Enter an amount", response.get_json()["error"])
                set_amount.assert_not_called()

    def test_a_failed_write_is_a_503_and_nothing_private_is_logged(self):
        with self.assertLogs("app", level="ERROR") as logs:
            response, _ = self.post({"symbol": "AAPL", "amount": 123456.78}, side_effect=KvStoreError("down 123456.78"))

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("123456", "".join(logs.output))

    def test_the_group_check_and_page_pass_the_amounts(self):
        card = {f: None for f in ("price", "change", "change_percent", "week52_low", "week52_high", "pct_off_high",
                                  "market_cap", "pe_ratio", "peg_ratio")}
        card.update(symbol="AAPL", group="individual", pending=True, error=None)
        for amounts, known in (({"AAPL": 250.0}, True), ({}, False)):
            with self.subTest(known=known), mock.patch("app.load_ticker_config", return_value={"individual": ["AAPL"]}), \
                 mock.patch("app.check_for_ticker_updates", return_value={"individual": [card]}), \
                 mock.patch("app.invested.load_amounts", return_value=(amounts, known)):
                body = self.client.get("/api/tickers/groups/individual/check").get_json()
                self.assertEqual(body["invested_known"], known)
                self.assertEqual("$250" in body["group_html"], known)


class TestFullPositionRoute(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        env = mock.patch.dict(os.environ, NO_AUTH_ENV)
        env.start()
        self.addCleanup(env.stop)

    def post(self, body, **patches):
        with mock.patch("app.full_position.set_mark", **patches) as set_mark:
            response = self.client.post("/api/full-position", json=body)
        return response, set_mark

    def test_ticking_and_unticking_each_write_one_symbol(self):
        ticked, set_mark = self.post({"symbol": "AAPL", "full": True})
        self.assertEqual((ticked.status_code, ticked.get_json()), (200, {"ok": True}))
        set_mark.assert_called_once_with("AAPL", True)

        _, set_mark = self.post({"symbol": "MOG.A", "full": False})
        set_mark.assert_called_once_with("MOG.A", False)

    def test_a_lowercase_symbol_is_stored_as_its_uppercase_form(self):
        _, set_mark = self.post({"symbol": "aapl", "full": True})

        set_mark.assert_called_once_with("AAPL", True)

    def test_a_bad_symbol_or_a_non_boolean_is_a_400_and_writes_nothing(self):
        for body in ({"symbol": "AAPL\n", "full": True}, {"symbol": "A B", "full": True}, {"symbol": "", "full": True},
                     {"symbol": 5, "full": True}, {"symbol": "AAPL", "full": "yes"}, {"symbol": "AAPL", "full": 1},
                     {"symbol": "AAPL"}, [1], "x", None):
            with self.subTest(body=body):
                response, set_mark = self.post(body)
                self.assertEqual(response.status_code, 400)
                set_mark.assert_not_called()

    def test_a_failed_write_is_a_503(self):
        response, _ = self.post({"symbol": "AAPL", "full": True}, side_effect=KvStoreError("down"))

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("ok", response.get_json())

    def test_the_group_check_keeps_the_marks_and_survives_an_unreadable_hash(self):
        config = {"stocks": ["SPY"]}
        card = {f: None for f in ("price", "change", "change_percent", "week52_low", "week52_high", "pct_off_high",
                                  "market_cap", "pe_ratio", "peg_ratio")}
        card.update(symbol="SPY", group="stocks", pending=True, error=None)
        for marks, expect in ((frozenset({"SPY"}), True), (frozenset(), False)):
            with self.subTest(marked=expect), mock.patch("app.load_ticker_config", return_value=config), \
                 mock.patch("app.check_for_ticker_updates", return_value={"stocks": [card]}), \
                 mock.patch("app.full_position.load_marks", return_value=(marks, expect)):
                body = self.client.get("/api/tickers/groups/stocks/check").get_json()
                self.assertEqual('data-full-position="1"' in body["group_html"], expect)
                self.assertEqual(body["marks_known"], expect)

    def test_the_tickers_page_passes_the_marks_and_shows_the_note_when_unreadable(self):
        for known, note in ((True, False), (False, True)):
            with self.subTest(known=known), mock.patch("app.load_ticker_config", return_value={"stocks": ["SPY"]}), \
                 mock.patch("app.load_ticker_state", return_value={}), mock.patch("app.get_initial_market_news", return_value={"headlines": [], "pending": False}), \
                 mock.patch("app.full_position.load_marks", return_value=(frozenset({"SPY"}) if known else frozenset(), known)):
                html = self.client.get("/tickers").get_data(as_text=True)
                self.assertEqual("Full-position marks couldn&#x27;t be loaded." in html, note)
                self.assertEqual('data-full-position="1"' in html, known)


if __name__ == "__main__":
    unittest.main()

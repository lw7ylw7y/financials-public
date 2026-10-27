"""Local Flask app for the v2 web dashboard: the Indicator Digest Page
("/"), the Small & Mid-Cap Screener ("/screener" and its quote route
"/api/screener/quotes") and the Ticker Dashboard ("/tickers", plus its inline watchlist
editor, "/api/tickers/add" and "/api/tickers/remove"). The ticker
page's background live check hits one route per group
("/api/tickers/groups/<name>/check") plus one for market news
("/api/market-news/check") rather than a single combined route,
so a group with fewer tickers repaints before a slower one finishes. The
local dev server binds to loopback only (127.0.0.1); the hosted
deployment runs under gunicorn.

`_require_auth` gates every route behind Google sign-in, and answers 503
on every route while any sign-in setting is missing.
"""

import logging
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer", "screener"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))
sys.path.insert(0, _SRC_DIR)
sys.path.insert(0, _WEB_DIR)

from flask import Flask, Response, jsonify, redirect, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import full_position
import google_auth
import invested
import page_store
import quotes
import reads_chart
import reads_history
import scoring
import screener_page
import settings as screener_settings
import store as screener_store

from kv_store import KvStoreError
from live_pull import check_for_updates, get_initial_page_data
from page_template import (
    pct_in_range,
    render_check_response,
    render_invested_cell,
    render_indicator_digest_page,
    render_market_news_check_response,
    render_ticker_dashboard_page,
    render_ticker_group_check_response,
)
from ticker_dashboard import (
    TickerConfigError,
    add_ticker_to_group,
    check_for_market_news,
    check_for_ticker_updates,
    compute_page_verdicts,
    get_initial_market_news,
    get_initial_ticker_page_data,
    load_ticker_config,
    load_ticker_state,
    remove_ticker_from_group,
)
from ticker_verdicts import compute_ticker_verdicts

logger = logging.getLogger(__name__)

# Class shares such as MOG.A are real symbols, so unlike the ticker editor's check this allows a dot.
_SCREENER_SYMBOL = re.compile(r"^[A-Za-z0-9.\-]{1,10}$")

app = Flask(__name__)
# Render terminates TLS in front of the app; without this, the redirect URI
# built for Google would be http:// and never match the registered one.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

_AUTH_ENDPOINTS = {"login", "auth_callback", "logout"}


def _page(message: str, status: int) -> Response:
    return Response(message, status, {"Content-Type": "text/plain; charset=utf-8"})


@app.before_request
def _require_auth():
    """Google sign-in in front of every route. A missing sign-in setting,
    `GOOGLE_CLIENT_ID` included, fails closed with a 503 instead of
    leaving the dashboard open. Only the session's own signed email
    counts, and it must match `ALLOWED_EMAIL`; an unauthenticated
    `/api/*` call gets a 401 rather than a redirect its fetch() couldn't
    follow usefully.
    """
    missing = google_auth.missing_config()
    if missing:
        return _page(f"Sign-in is misconfigured; missing: {', '.join(missing)}", 503)

    if request.endpoint in _AUTH_ENDPOINTS:
        return None

    email = session.get("email")
    if email and secrets.compare_digest(email, google_auth.allowed_email()):
        return None

    if request.path.startswith("/api/"):
        return jsonify({"error": "authentication required"}), 401
    return redirect(url_for("login"))


@app.route("/login")
def login():
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    redirect_uri = url_for("auth_callback", _external=True)
    return redirect(google_auth.build_authorize_url(redirect_uri, state))


@app.route("/auth/callback")
def auth_callback():
    expected_state = session.pop("oauth_state", None)
    state = request.args.get("state", "")
    code = request.args.get("code")
    if not expected_state or not secrets.compare_digest(state, expected_state) or not code:
        return _page("Sign-in failed: invalid or expired request. Go to /login to try again.", 400)

    try:
        email = google_auth.fetch_verified_email(code, url_for("auth_callback", _external=True))
    except google_auth.GoogleAuthError:
        return _page("Sign-in failed: could not verify your Google account. Go to /login to try again.", 502)

    if not email or not secrets.compare_digest(email, google_auth.allowed_email()):
        session.clear()
        return _page("This Google account is not allowed to view this dashboard.", 403)

    session.clear()
    session["email"] = email
    session.permanent = True
    return redirect(url_for("indicator_digest_page"))


@app.route("/logout")
def logout():
    session.clear()
    return _page("Signed out.", 200)


@app.route("/")
def indicator_digest_page():
    data = get_initial_page_data()
    return render_indicator_digest_page(data)


@app.route("/tickers")
def ticker_dashboard_page():
    config = load_ticker_config()
    stored = load_ticker_state()
    grouped_cards = get_initial_ticker_page_data(config, stored)
    market_news = get_initial_market_news()
    verdicts = compute_page_verdicts(config, stored)
    marks, marks_known = full_position.load_marks()
    amounts, amounts_known = invested.load_amounts()
    return render_ticker_dashboard_page(grouped_cards, market_news, verdicts, marks, marks_known, amounts, amounts_known)


def _individual_watchlist() -> tuple[frozenset, bool]:
    """The symbols in the Ticker Dashboard's `individual` group, and
    whether they could be read. The screener only reads it, to show a
    shortlisted row as promoted; an unreadable watchlist is not fatal."""
    try:
        return frozenset(load_ticker_config().get(_PROMOTE_GROUP, [])), True
    except KvStoreError as e:
        logger.error("screener page: watchlist unreadable: %s", type(e).__name__)
        return frozenset(), False


@app.route("/screener")
def screener():
    tab = request.args.get("tab", "new")
    try:
        watchlist, watchlist_known = _individual_watchlist()
        view = screener_page.load_view(watchlist=watchlist, watchlist_known=watchlist_known)
    except KvStoreError as e:
        logger.error("screener page: storage read failed: %s", type(e).__name__)
        return screener_page.render_error_page(tab), 503
    return screener_page.render_screener_page(view, tab)


@app.route("/api/screener/quotes")
def api_screener_quotes():
    """Live quotes for up to `quotes.MAX_SYMBOLS` candidates, called by
    the screener page's script in batches. Each entry carries the four
    price cells already rendered (see screener_page.render_quote_cells)
    so the browser only places them."""
    symbols = list(dict.fromkeys(s for s in request.args.get("symbols", "").split(",") if s))
    if not symbols or len(symbols) > quotes.MAX_SYMBOLS:
        return jsonify({"error": f"send 1 to {quotes.MAX_SYMBOLS} symbols"}), 400
    if not all(_SCREENER_SYMBOL.fullmatch(s) for s in symbols):
        return jsonify({"error": "invalid symbol"}), 400
    try:
        candidates = screener_store.load_candidates()
        unknown = [s for s in symbols if s not in candidates]
        if unknown:
            return jsonify({"error": "unknown symbol"}), 400
        now = datetime.now(timezone.utc)
        fetched = quotes.get_quotes(symbols, now)
    except KvStoreError as e:
        logger.error("screener quotes: storage read failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    result = {}
    for symbol, quote in fetched.items():
        record = candidates[symbol]
        result[symbol] = {
            "html": screener_page.render_quote_cells(symbol, record, quote, now),
            "pct_in_range": pct_in_range(quote["price"], record.get("week52_low"), record.get("week52_high")) if quote else None,
            "change_percent": quote.get("change_percent") if quote else None,
        }
    return jsonify({"quotes": result})


_SCREENER_STATUSES = ("new", "shortlisted", "dismissed")
_PROMOTE_GROUP = "individual"


def _json_object() -> dict:
    """The request's JSON body if it is an object, else {} (so a list or a
    string body fails validation with a 400 instead of raising)."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@app.route("/api/screener/status", methods=["POST"])
def api_screener_status():
    """Sets one candidate to shortlisted, dismissed, or New (which clears
    it): one atomic per-symbol write that keeps the entry's `checked_at`.
    A dismissal also records the score and pass state the name has now,
    computed here from the current candidates and settings rather than
    taken from the browser."""
    body = _json_object()
    symbol, wanted = body.get("symbol"), body.get("status")
    if not isinstance(symbol, str) or not _SCREENER_SYMBOL.fullmatch(symbol) or wanted not in _SCREENER_STATUSES:
        return jsonify({"error": "invalid symbol or status"}), 400
    try:
        candidates = screener_store.load_candidates()
        if symbol not in candidates:
            return jsonify({"error": "unknown symbol"}), 400
        now = datetime.now(timezone.utc)
        if wanted == "new":
            page_store.clear_status(symbol)
        else:
            entry = {"status": wanted, "at": now.isoformat()}
            checked_at = (page_store.load_status(symbol) or {}).get("checked_at")
            if checked_at:
                entry["checked_at"] = checked_at
            if wanted == "dismissed":
                entry.update(scoring.dismissal_snapshot(symbol, candidates, screener_settings.load_settings(), now.date()))
            page_store.save_status(symbol, entry)
    except KvStoreError as e:
        logger.error("screener status: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    lands = None
    if wanted == "new":
        lands = screener_page.list_for(scoring.evaluate(candidates[symbol], screener_settings.load_settings(), now.date()))
    return jsonify({"ok": True, "status": wanted, "lands": lands})


@app.route("/api/screener/promote", methods=["POST"])
def api_screener_promote():
    """Adds a candidate to the Ticker Dashboard's `individual` group, the
    same write as that page's add form (a no-op if it is already there).
    The shortlist page then shows the row as promoted."""
    body = _json_object()
    symbol = body.get("symbol")
    if not isinstance(symbol, str) or not _SCREENER_SYMBOL.fullmatch(symbol):
        return jsonify({"error": "invalid symbol"}), 400
    try:
        if screener_store.load_candidate(symbol) is None:
            return jsonify({"error": "unknown symbol"}), 400
        add_ticker_to_group(symbol, _PROMOTE_GROUP)
    except TickerConfigError as e:
        return jsonify({"error": str(e)}), 400
    except KvStoreError as e:
        logger.error("screener promote: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    return jsonify({"ok": True})


@app.route("/api/screener/note", methods=["POST"])
def api_screener_note():
    """Saves a candidate's note, or clears it when the text is blank. The
    note text is never logged, including when the write fails."""
    body = _json_object()
    symbol, text = body.get("symbol"), body.get("text")
    if not isinstance(symbol, str) or not _SCREENER_SYMBOL.fullmatch(symbol) or not isinstance(text, str):
        return jsonify({"error": "invalid symbol or text"}), 400
    if len(text) > page_store.MAX_NOTE_CHARS:
        return jsonify({"error": f"That note is too long (max {page_store.MAX_NOTE_CHARS:,} characters)."}), 400
    try:
        if screener_store.load_candidate(symbol) is None:
            return jsonify({"error": "unknown symbol"}), 400
        if text.strip():
            page_store.save_note(symbol, {"text": text, "at": datetime.now(timezone.utc).isoformat()})
        else:
            page_store.clear_note(symbol)
    except KvStoreError as e:
        logger.error("screener note: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    return jsonify({"ok": True})


def _settings_counts(form: dict, today) -> dict:
    """What the filters in `form` would show, against what is saved now:
    the New list's size under each, and how many tech symbols inside the
    new market cap range have no candidate record yet (tonight's fetch)."""
    candidates = screener_store.load_candidates()
    statuses = page_store.load_statuses()
    screen = screener_settings.to_settings(form)
    return {
        "would_show": screener_page.count_new(candidates, statuses, screen, today),
        "now": screener_page.count_new(candidates, statuses, screener_settings.load_settings(), today),
        "fetch_tonight": len(scoring.symbols_to_fetch(screener_store.load_universe(), candidates, screen)),
    }


@app.route("/api/screener/settings/preview", methods=["POST"])
def api_screener_settings_preview():
    """How many names the posted filters would show, without saving them."""
    form, errors = screener_settings.validate_form(_json_object().get("settings"))
    if errors:
        return jsonify({"errors": errors}), 400
    try:
        return jsonify(_settings_counts(form, datetime.now(timezone.utc).date()))
    except KvStoreError as e:
        logger.error("screener settings preview: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503


@app.route("/api/screener/settings", methods=["POST"])
def api_screener_settings():
    """Validates and saves the filters in one multi-field write. Nothing
    is saved when any field is invalid, and no status or note is
    touched. `shown` is the New list's size under the saved filters, or
    None if that count could not be read after the save succeeded."""
    form, errors = screener_settings.validate_form(_json_object().get("settings"))
    if errors:
        return jsonify({"errors": errors}), 400
    try:
        screener_settings.save_form(form)
    except KvStoreError as e:
        logger.error("screener settings: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    try:
        shown = _settings_counts(form, datetime.now(timezone.utc).date())["would_show"]
    except KvStoreError as e:
        logger.error("screener settings: count failed after save: %s", type(e).__name__)
        shown = None
    return jsonify({"ok": True, "shown": shown})


@app.route("/api/full-position", methods=["POST"])
def api_full_position():
    """Ticks or unticks one symbol's Full Position box: one atomic write
    to its own field, shared by the Ticker Dashboard and the screener."""
    body = _json_object()
    symbol, full = body.get("symbol"), body.get("full")
    if not isinstance(symbol, str) or not _SCREENER_SYMBOL.fullmatch(symbol) or not isinstance(full, bool):
        return jsonify({"error": "invalid symbol or full"}), 400
    try:
        full_position.set_mark(symbol.upper(), full)
    except KvStoreError as e:
        logger.error("full position: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    return jsonify({"ok": True})


@app.route("/api/invested", methods=["POST"])
def api_invested():
    """Sets the total invested in one `individual` ticker, or clears it
    when `amount` is null. One atomic write to the symbol's own field. The
    amount is never logged. The reply carries the rendered cell, so the
    browser shows exactly what was stored."""
    body = _json_object()
    symbol = body.get("symbol")
    amount = body.get("amount")
    if not isinstance(symbol, str) or not _SCREENER_SYMBOL.fullmatch(symbol):
        return jsonify({"error": "invalid symbol"}), 400
    if amount is not None and not invested.valid_amount(amount):
        return jsonify({"error": f"Enter an amount from 0 to {invested.MAX_AMOUNT:,.0f}."}), 400
    symbol = symbol.upper()
    try:
        invested.set_amount(symbol, amount)
    except KvStoreError as e:
        logger.error("invested: storage failed: %s", type(e).__name__)
        return jsonify({"error": "storage error"}), 503
    return jsonify({"ok": True, "cell_html": render_invested_cell(symbol, None if amount is None else round(float(amount), 2))})


@app.route("/api/check")
def api_check():
    """Called by the page's own background script after the fast
    initial render. See live_pull.check_for_updates."""
    result = check_for_updates()
    if not result["data_updated"]:
        return jsonify({"data_updated": False})
    fragments = render_check_response(result["content"])
    return jsonify({"data_updated": True, **fragments})


@app.route("/api/reads/history")
def api_reads_history():
    """The "Reads over time" card, fetched by the digest page after its
    first paint (about 600 small fields, so it is kept off the page's
    instant render). Redis unreadable gives the card's unavailable text."""
    try:
        reads, recessions = reads_history.load_reads(), reads_history.load_recessions()
    except KvStoreError as e:
        logger.error("reads history unreadable: %s", type(e).__name__)
        return jsonify({"history_html": reads_chart.render_unavailable()})
    fit = reads_history.fit_alignment(reads, recessions)
    return jsonify({"history_html": reads_chart.render_reads_history(reads, recessions, fit, datetime.now(timezone.utc).date())})


@app.route("/api/tickers/groups/<group_name>/check")
def api_check_ticker_group(group_name):
    """Called independently by each group's own block in the ticker
    page's background script, one small live fetch per group instead
    of one big one for the whole watchlist -- so a group with fewer
    tickers finishes and repaints before a slower one does. See
    ticker_dashboard.check_for_ticker_updates."""
    config = load_ticker_config()
    if group_name not in config:
        return jsonify({"error": f"unknown group: {group_name!r}"}), 404
    grouped_cards = check_for_ticker_updates(config={group_name: config[group_name]})
    marks, marks_known = full_position.load_marks()
    amounts, amounts_known = invested.load_amounts()
    # Live cards, not the cache: a pending or errored card has nothing to score.
    verdicts = compute_ticker_verdicts({group_name: [c for c in grouped_cards[group_name] if not c["pending"] and not c["error"]]})
    response = render_ticker_group_check_response(group_name, grouped_cards[group_name], marks, amounts, amounts_known, verdicts)
    return jsonify({**response, "marks_known": marks_known, "invested_known": amounts_known})


@app.route("/api/market-news/check")
def api_check_market_news():
    """Called independently of any ticker group's own check -- see
    api_check_ticker_group."""
    market_news = check_for_market_news()
    return jsonify(render_market_news_check_response(market_news))


@app.route("/api/tickers/add", methods=["POST"])
def api_add_ticker():
    """Called by the /tickers page's inline "add a ticker" form. Writes
    straight to config/tickers.json; on success the page inserts a
    pending row for the new ticker and re-checks just that one group
    (see render_ticker_dashboard_page's script) rather than reloading
    the whole page."""
    body = request.get_json(silent=True) or {}
    try:
        add_ticker_to_group(body.get("symbol", ""), body.get("group", ""))
    except TickerConfigError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/tickers/remove", methods=["POST"])
def api_remove_ticker():
    """Called by the /tickers page's inline "remove" button on each
    row. See api_add_ticker. Removing a ticker from the `individual`
    group also clears the amount invested in it, so a ticker added back
    later does not show a stale total; the removal has already succeeded
    by then, so a failed clear is logged (error class only) and does not
    fail the request."""
    body = request.get_json(silent=True) or {}
    symbol, group = body.get("symbol", ""), body.get("group", "")
    try:
        remove_ticker_from_group(symbol, group)
    except TickerConfigError as e:
        return jsonify({"error": str(e)}), 400
    if group == _PROMOTE_GROUP and isinstance(symbol, str) and symbol.strip():
        try:
            invested.set_amount(symbol.strip().upper(), None)
        except KvStoreError as e:
            logger.error("invested: clearing the amount of a removed ticker failed: %s", type(e).__name__)
    return jsonify({"ok": True})


if __name__ == "__main__":
    # threaded=True so the ticker page's concurrent per-group check
    # requests actually run concurrently in local dev too, instead of
    # queueing on Werkzeug's single-threaded default -- matching how
    # gunicorn already serves concurrent requests on a hosted deploy.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

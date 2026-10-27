import os
import re
import sys
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
    os.path.join(_SRC, "web"),
    os.path.dirname(__file__),
):
    sys.path.insert(0, _p)

from readfixtures import RESTRICTIVE, read_view
from page_template import (
    format_invested,
    render_check_response,
    render_indicator_digest_page,
    render_market_news_check_response,
    render_ticker_dashboard_page,
    render_ticker_group_check_response,
    render_verdict_pill,
)

_JS_DIR = os.path.join(_SRC, "web", "static", "js")


def _js(name):
    with open(os.path.join(_JS_DIR, name)) as f:
        return f.read()


TICKERS_JS = _js("tickers.js")
DIGEST_JS = _js("digest.js")

TABLE = {
    "leading": [],
    "coincident": [
        {
            "name": "Nonfarm Payrolls",
            "latest_value": 159075.0,
            "latest_date": "2026-08-01",
            "prior_value": 158000.0,
            "sparkline_cid": "spark-nonfarm_payrolls",
            "sparkline_values": [158000.0, 159075.0],
        }
    ],
    "lagging": [],
}

COUNTDOWN = {
    "entries": [
        {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-20", "days_until": 3}
    ],
    "soonest": {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-20", "days_until": 3},
}


def base_data(**overrides):
    data = {
        "table": TABLE,
        "countdown": COUNTDOWN,
        "ai_result": read_view("Payrolls ticked up.", leading="improving", coincident="mixed", lagging="weakening"),
    }
    data.update(overrides)
    return data


class TestRenderIndicatorDigestPage(unittest.TestCase):
    def test_renders_ai_summary_and_directional_label(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("Payrolls ticked up.", html)
        self.assertIn("Improving", html)

    def test_renders_one_tile_per_group_with_its_read_time_frame_and_count_and_no_overall_read(self):
        html = render_indicator_digest_page(base_data())
        tiles = html.split('<div class="read-groups">')[1].split("</section>")[0]

        self.assertEqual(tiles.count('class="read-group"'), 3)
        for read in ("Improving", "Mixed", "Weakening"):
            self.assertIn(read, tiles)
        for frame in ("Outlook: where the economy is heading", "Now: how the economy is doing today",
                      "Confirmation: the economy 6 to 12 months ago"):
            self.assertIn(frame, tiles)
        self.assertIn("3 of 3 indicators scored", tiles)
        self.assertIn("2 of 2 indicators scored", tiles)
        self.assertNotIn("Overall", html)
        self.assertNotIn("of 8 indicators", html)

    def test_shows_the_relationship_sentence_when_there_is_one(self):
        with_one = render_indicator_digest_page(
            base_data(ai_result=read_view("s", leading="weakening", coincident="mixed", relationship="Early warning.")))
        without = render_indicator_digest_page(base_data())

        self.assertIn('<p class="read-relationship">Early warning.</p>', with_one)
        self.assertNotIn("read-relationship", without)

    def test_each_group_label_has_an_info_button_with_the_explanation_in_the_read_and_the_table(self):
        html = render_indicator_digest_page(base_data())  # the fixture table has only the coincident group

        for group in ("leading", "coincident", "lagging"):
            self.assertIn(f'aria-controls="info-{group}-read"', html)
            self.assertRegex(html, rf'<span id="info-{group}-read" class="info-popup" role="note" hidden>')
        self.assertIn('aria-controls="info-coincident-table"', html)
        self.assertRegex(html, r'<span id="info-coincident-table" class="info-popup" role="note" hidden>')
        self.assertEqual(html.count('class="info-button"'), 4)
        self.assertIn("&#9432;", html)
        self.assertIn('aria-label="About lagging indicators"', html)
        self.assertEqual(html.count('aria-expanded="false"'), 4)

    def test_every_table_group_gets_a_label_with_info_and_its_time_frame(self):
        table = {"leading": TABLE["coincident"], "coincident": TABLE["coincident"], "lagging": TABLE["coincident"]}
        html = render_indicator_digest_page(base_data(table=table))

        for group, label in (("leading", "LEADING"), ("coincident", "COINCIDENT"), ("lagging", "LAGGING")):
            self.assertIn(f'<span class="group-label">{label}<button', html)
            self.assertIn(f'aria-controls="info-{group}-table"', html)
        self.assertEqual(html.count('<p class="muted group-frame">'), 3)
        self.assertIn('<p class="muted group-frame">Confirmation: the economy 6 to 12 months ago</p>', html)

    def test_the_info_popups_state_the_time_frames(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("so they confirm the past rather than predict", html)
        self.assertIn("typically 6 to 12 months later", html)
        self.assertIn("so they are an outlook, not a result", html)

    def test_the_script_toggles_the_popups(self):
        script = DIGEST_JS

        for text in ("info-button", "aria-expanded", "Escape", "closeInfo", "info-popup"):
            self.assertIn(text, script)

    def test_shows_the_policy_stance_as_context_under_the_tiles(self):
        html = render_indicator_digest_page(base_data(ai_result=read_view("s", leading="improving", policy=RESTRICTIVE)))

        self.assertIn('<p class="read-policy muted">Policy stance: Restrictive.', html)
        self.assertLess(html.index("read-groups"), html.index("read-policy"))
        self.assertLess(html.index("read-policy"), html.index('class="ai-summary"'))

    def test_says_when_the_stance_is_not_available(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("Policy stance: not available yet (no fed funds reading on file).", html)

    def test_renders_disclaimer_when_ai_present(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("not personalized financial advice", html)

    def test_renders_table_rows(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("Nonfarm Payrolls", html)
        self.assertIn("159075", html)
        self.assertIn("prior: 158000", html)

    def test_renders_countdown(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("CPI", html)
        self.assertIn("in 3 day(s)", html)

    def test_no_ai_response_on_file_renders_placeholder_not_crash(self):
        html = render_indicator_digest_page(base_data(ai_result=None))

        self.assertIn("No AI interpretation on file yet.", html)

    def test_html_escapes_indicator_names(self):
        table = {"leading": [], "coincident": [], "lagging": [
            {
                "name": "<script>alert(1)</script>",
                "latest_value": 1.0,
                "latest_date": "2026-09-01",
                "prior_value": None,
                "sparkline_cid": None,
                "sparkline_values": [1.0],
            }
        ]}
        html = render_indicator_digest_page(base_data(table=table))

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_renders_checking_indicator_and_script_hides_it_on_settle(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn('id="checking-indicator"', html + DIGEST_JS)
        self.assertIn("Checking for updates", html + DIGEST_JS)
        self.assertIn("hideCheckingIndicator", html + DIGEST_JS)

    def test_renders_sparkline_svg_for_row_with_history(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn('<svg class="sparkline"', html)
        self.assertIn("<polyline", html)

    def test_renders_dot_only_sparkline_for_single_point_history(self):
        table = {"leading": [], "coincident": [], "lagging": [
            {
                "name": "CPI",
                "latest_value": 334.1,
                "latest_date": "2026-09-01",
                "prior_value": None,
                "sparkline_cid": None,
                "sparkline_values": [334.1],
            }
        ]}
        html = render_indicator_digest_page(base_data(table=table))

        self.assertIn('<svg class="sparkline"', html)
        self.assertNotIn("<polyline", html)
        self.assertIn("<circle", html)

    def test_renders_nav_linking_to_ticker_dashboard(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn('class="site-nav"', html)
        self.assertIn('href="/tickers"', html)
        self.assertIn('href="/" class="active"', html)
        self.assertIn('href="/screener"', html)


class TestRenderCheckResponse(unittest.TestCase):
    def test_includes_table_and_countdown(self):
        content = {"table": TABLE, "countdown": COUNTDOWN, "read_view": None}

        fragments = render_check_response(content)

        self.assertIn("Nonfarm Payrolls", fragments["table_html"])
        self.assertIn("CPI", fragments["countdown_html"])
        self.assertIsNone(fragments["ai_html"])

    def test_ai_html_present_when_ai_result_given(self):
        content = {
            "table": TABLE,
            "countdown": COUNTDOWN,
            "read_view": read_view("Fresh read.", leading="improving"),
        }

        fragments = render_check_response(content)

        self.assertIsNotNone(fragments["ai_html"])
        self.assertIn("Fresh read.", fragments["ai_html"])


def make_card(**overrides):
    card = {
        "symbol": "SPY",
        "group": "stocks",
        "price": 452.31,
        "change": 3.81,
        "change_percent": 0.85,
        "week52_low": 400.0,
        "week52_high": 480.0,
        "pct_off_high": 5.8,
        "market_cap": 3500000.0,
        "pe_ratio": 34.2,
        "peg_ratio": 2.1,
        "error": None,
        "pending": False,
    }
    card.update(overrides)
    return card


def make_pending_card(**overrides):
    return make_card(
        price=None, change=None, change_percent=None, week52_low=None, week52_high=None,
        pct_off_high=None, market_cap=None, pe_ratio=None, peg_ratio=None,
        error=None, pending=True,
        **overrides,
    )


SAMPLE_VERDICTS = {
    "groups": [
        {"group": "bonds", "verdict": "discount", "summary": "Bonds sit well off their highs."},
        {"group": "stocks", "verdict": "overpriced", "summary": "Stocks sit near their highs."},
    ],
    "tickers_by_verdict": {
        "discount": [{"symbol": "NVDA", "group": "stocks", "reasoning": "far off its high"}],
        "fair": [],
        "overpriced": [{"symbol": "TSLA", "group": "stocks", "reasoning": "<b>near its high</b>"}],
    },
    "unscored": [],
    "scores": {},
}

NO_NEWS = {"headlines": [], "pending": False}
PENDING_NEWS = {"headlines": [], "pending": True}
SAMPLE_NEWS = {
    "headlines": [
        {"headline": "Stocks rally on rate-cut hopes", "url": "https://example.com/a", "source": "CNBC", "datetime": 1},
        {"headline": "Tech leads Monday gains", "url": "https://example.com/b", "source": "Reuters", "datetime": 2},
    ],
    "pending": False,
}


def row_for(html: str, symbol: str) -> str:
    """The full <tr>...</tr> markup for the row whose Ticker cell holds
    `symbol` -- the remove-ticker button lives in its own trailing
    cell, not the Ticker cell, so this matches on the plain `<td>` here."""
    cell_start = html.index(f"<td>{symbol}</td>")
    row_start = html.rfind("<tr", 0, cell_start)
    row_end = html.index("</tr>", cell_start) + len("</tr>")
    return html[row_start:row_end]


class TestStaleFlag(unittest.TestCase):
    @staticmethod
    def spy_row(html):
        start = html.index('<tr data-symbol="SPY"')
        return html[start:html.index("</tr>", start)]

    def test_a_saved_row_shows_a_flag_with_the_date_and_time_on_hover(self):
        card = make_card(stale_since="2026-10-20T14:35:00+00:00")
        html = render_ticker_dashboard_page({"stocks": [card]}, NO_NEWS)
        row = self.spy_row(html)

        self.assertIn("Saved", row)
        self.assertIn("20 Oct 2026, 14:35 UTC", row)
        self.assertIn('role="tooltip"', row)
        self.assertIn('tabindex="0"', row)

    def test_the_same_symbol_saved_in_two_groups_gets_two_different_tip_ids(self):
        cards = {"stocks": [make_card(stale_since="2026-10-20T14:35:00+00:00")],
                 "individual": [make_card(group="individual", stale_since="2026-10-20T14:35:00+00:00")]}
        html = render_ticker_dashboard_page(cards, NO_NEWS)
        ids = re.findall(r'id="(stale-tip-[^"]+)"', html)

        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        for tip_id in ids:
            self.assertIn(f'aria-describedby="{tip_id}"', html)

    def test_a_saved_row_that_is_also_marked_full_position_keeps_both(self):
        card = make_card(stale_since="2026-10-20T14:35:00+00:00")
        html = render_ticker_dashboard_page({"stocks": [card]}, NO_NEWS, None, frozenset({"SPY"}))
        row = self.spy_row(html)

        self.assertIn("data-full-position=\"1\"", row)
        self.assertIn("Saved", row)
        self.assertIn('role="tooltip"', row)

    def test_a_naive_time_is_shown_as_utc_and_a_garbled_one_as_not_recorded(self):
        naive = render_ticker_dashboard_page({"stocks": [make_card(stale_since="2026-10-20T14:35:00")]}, NO_NEWS)
        garbled = render_ticker_dashboard_page({"stocks": [make_card(stale_since="yesterday")]}, NO_NEWS)

        self.assertIn("20 Oct 2026, 14:35 UTC", self.spy_row(naive))
        self.assertIn("its time was not recorded", self.spy_row(garbled))

    def test_a_snapshot_with_no_recorded_time_says_so(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(stale_since=None)]}, NO_NEWS)

        self.assertIn("its time was not recorded", self.spy_row(html))

    def test_a_live_row_has_no_flag(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertNotIn("Saved", self.spy_row(html))


class TestPctInRange(unittest.TestCase):
    def test_position_and_degenerate_ranges(self):
        from page_template import pct_in_range
        self.assertEqual(pct_in_range(50.0, 0.0, 100.0), 50.0)
        self.assertIsNone(pct_in_range(50.0, 100.0, 100.0))
        self.assertIsNone(pct_in_range(50.0, 120.0, 100.0))
        self.assertIsNone(pct_in_range(50.0, None, 100.0))
        self.assertIsNone(pct_in_range(None, 0.0, 100.0))

    def test_only_the_ends_show_0_and_100(self):
        from page_template import render_pct_in_range_cell
        self.assertIn(">99%<", render_pct_in_range_cell(99.6))
        self.assertIn(">1%<", render_pct_in_range_cell(0.4))
        self.assertIn(">100%<", render_pct_in_range_cell(100.0))
        self.assertIn(">0%<", render_pct_in_range_cell(0.0))


class TestRenderTickerDashboardPage(unittest.TestCase):
    def test_renders_row_fields_as_a_table(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("<table", html)
        self.assertIn("SPY", html)
        self.assertIn("452.31", html)
        self.assertIn("400.00", html)
        self.assertIn("480.00", html)

    def test_renders_column_headers(self):
        html = render_ticker_dashboard_page({"individual": [make_card(group="individual")]}, NO_NEWS)

        self.assertIn('<th class="sortable" data-sort-key="symbol">Ticker</th>', html)
        self.assertIn(">Change<", html)
        self.assertIn("52-Week Range", html)
        self.assertIn("% in Range", html)
        self.assertIn("Market Cap", html)
        self.assertIn(">P/E<", html)
        self.assertIn(">PEG<", html)

    def test_renders_market_cap_formatted_with_suffix(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_card(group="individual", market_cap=3500000.0)]}, NO_NEWS
        )

        self.assertIn("$3.50T", html)

    def test_missing_market_cap_renders_not_available(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_card(group="individual", market_cap=None)]}, NO_NEWS
        )

        self.assertIn("n/a", html)

    def test_renders_pe_ratio(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_card(group="individual", pe_ratio=34.2)]}, NO_NEWS
        )

        self.assertIn("34.2", html)

    def test_missing_pe_ratio_renders_not_available(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_card(group="individual", pe_ratio=None)]}, NO_NEWS
        )

        self.assertIn("n/a", html)

    def test_renders_peg_ratio(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_card(group="individual", peg_ratio=2.1)]}, NO_NEWS
        )

        self.assertIn("2.10", html)

    def test_missing_peg_ratio_renders_not_available(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_card(group="individual", peg_ratio=None)]}, NO_NEWS
        )

        self.assertIn("n/a", html)

    def test_fund_group_omits_market_cap_pe_peg_columns_and_cells(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card(group="stocks", market_cap=3500000.0, pe_ratio=34.2, peg_ratio=2.1)]}, NO_NEWS
        )

        self.assertNotIn("Market Cap", html)
        self.assertNotIn(">P/E<", html)
        self.assertNotIn(">PEG<", html)
        self.assertNotIn("$3.50T", html)
        self.assertNotIn("34.2", html)
        self.assertNotIn("2.10", html)

    def test_fund_group_pending_row_colspan_excludes_dropped_columns(self):
        html = render_ticker_dashboard_page({"stocks": [make_pending_card(group="stocks")]}, NO_NEWS)

        self.assertIn('colspan="4"', html)

    def test_individual_group_pending_row_colspan_includes_company_columns(self):
        html = render_ticker_dashboard_page(
            {"individual": [make_pending_card(group="individual")]}, NO_NEWS
        )

        self.assertIn('colspan="7"', html)

    def test_remove_button_is_the_rows_trailing_cell(self):
        row = row_for(render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS), "SPY")

        self.assertTrue(row.rstrip().endswith("</tr>"))
        last_cell = row[row.rindex("<td>") :]
        self.assertIn("remove-ticker", last_cell)

    def test_no_per_ticker_news_list(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertNotIn("market-news-list", html)

    def test_renders_nav_linking_to_indicator_digest(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('class="site-nav"', html)
        self.assertIn('href="/" ', html)
        self.assertIn('href="/tickers" class="active"', html)
        self.assertIn('href="/screener"', html)

    def test_group_header_derived_from_config_key(self):
        html = render_ticker_dashboard_page({"sector_and_individual": [make_card()]}, NO_NEWS)

        self.assertIn("Sector And Individual", html)

    def test_new_group_key_renders_with_no_code_change(self):
        html = render_ticker_dashboard_page({"crypto": [make_card(symbol="BTC")]}, NO_NEWS)

        self.assertIn("Crypto", html)
        self.assertIn("BTC", html)

    def test_groups_render_in_file_order(self):
        html = render_ticker_dashboard_page(
            {"bonds": [make_card(symbol="VGIT")], "stocks": [make_card(symbol="SPY")]}, NO_NEWS
        )

        self.assertLess(html.index("Bonds"), html.index("Stocks"))

    def test_errored_row_shows_error_state_without_crashing(self):
        error_card = make_card(
            price=None,
            change=None,
            change_percent=None,
            week52_low=None,
            week52_high=None,
            pct_off_high=None,
            error="no quote data for SPY",
        )

        html = render_ticker_dashboard_page({"stocks": [error_card]}, NO_NEWS)

        self.assertIn("Unable to load data.", html)

    def test_one_row_erroring_does_not_affect_sibling_row(self):
        error_card = make_card(
            symbol="BADSYM",
            price=None,
            change=None,
            change_percent=None,
            week52_low=None,
            week52_high=None,
            pct_off_high=None,
            error="no quote data for BADSYM",
        )
        ok_card = make_card(symbol="SPY")

        html = render_ticker_dashboard_page({"stocks": [error_card, ok_card]}, NO_NEWS)

        self.assertIn("Unable to load data.", html)
        self.assertIn("452.31", html)

    def test_positive_change_colored_up(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(change=3.81, change_percent=0.85)]}, NO_NEWS)

        self.assertIn('class="ma-delta up"', html)
        self.assertIn("+3.81", html)
        self.assertIn("0.85%", html)

    def test_negative_change_colored_down(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(change=-2.08, change_percent=-0.27)]}, NO_NEWS)

        self.assertIn('class="ma-delta down"', html)
        self.assertIn("-2.08", html)

    def test_missing_change_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(change=None, change_percent=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_renders_where_the_price_sits_in_its_range(self):
        card = make_card(price=450.0, week52_low=400.0, week52_high=500.0)
        html = render_ticker_dashboard_page({"stocks": [card]}, NO_NEWS)

        self.assertIn('<td class="num">50%</td>', row_for(html, "SPY"))

    def test_a_price_outside_the_stored_range_is_clamped(self):
        above = render_ticker_dashboard_page({"stocks": [make_card(price=510.0, week52_low=400.0, week52_high=500.0)]}, NO_NEWS)
        below = render_ticker_dashboard_page({"stocks": [make_card(price=390.0, week52_low=400.0, week52_high=500.0)]}, NO_NEWS)

        self.assertIn('<td class="num">100%</td>', row_for(above, "SPY"))
        self.assertIn('<td class="num">0%</td>', row_for(below, "SPY"))

    def test_a_missing_range_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(week52_low=None, week52_high=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_renders_sort_data_attributes_on_rows(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(symbol="SPY", price=450.0, week52_low=400.0, week52_high=500.0)]}, NO_NEWS)

        row = row_for(html, "SPY")
        self.assertIn('data-symbol="SPY"', row)
        self.assertIn('data-pct-in-range="50.00"', row)

    def test_pending_and_errored_rows_have_empty_pct_in_range_attribute(self):
        cards = [
            make_pending_card(symbol="PENDING"),
            make_card(symbol="ERRORED", pct_off_high=None, price=None, error="boom"),
        ]

        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

        self.assertIn('data-pct-in-range=""', row_for(html, "PENDING"))
        self.assertIn('data-pct-in-range=""', row_for(html, "ERRORED"))

    def test_renders_sortable_headers_with_sort_keys(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('<th class="sortable" data-sort-key="symbol">Ticker</th>', html)
        self.assertIn('<th class="num sortable" data-sort-key="pctInRange">% in Range</th>', html)

    def test_renders_range_bar_gradient_and_marker(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('<svg class="range-bar"', html)
        self.assertIn("linearGradient", html)
        self.assertIn("<circle", html)

    def test_html_escapes_ticker_symbol(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(symbol="<script>alert(1)</script>")]}, NO_NEWS)

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_renders_remove_button_on_every_row_shape(self):
        cards = [make_card(symbol="SPY"), make_pending_card(symbol="NEWTICKER"), make_card(symbol="BADSYM", error="boom")]

        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

        for symbol in ("SPY", "NEWTICKER", "BADSYM"):
            row = row_for(html, symbol)
            self.assertIn('class="remove-ticker"', row)
            self.assertIn(f'data-symbol="{symbol}"', row)
            self.assertIn('data-group="stocks"', row)

    def test_renders_add_ticker_form_per_group(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card()], "bonds": [make_card(symbol="VGIT")]}, NO_NEWS
        )

        self.assertEqual(html.count('class="add-ticker-form"'), 2)
        self.assertIn('data-group="stocks"', html)
        self.assertIn('data-group="bonds"', html)

    def test_editor_actions_wired_up_in_script(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("/api/tickers/remove", html + TICKERS_JS)
        self.assertIn("/api/tickers/add", html + TICKERS_JS)
        self.assertIn("remove-ticker", html + TICKERS_JS)
        self.assertIn("add-ticker-form", html + TICKERS_JS)

    def test_add_ticker_does_not_reload_the_page(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertNotIn("location.reload", html + TICKERS_JS)
        self.assertIn("checkGroup", html + TICKERS_JS)

    def test_pending_row_shows_loading_placeholder(self):
        html = render_ticker_dashboard_page({"stocks": [make_pending_card()]}, NO_NEWS)

        self.assertIn("Loading&hellip;", html)
        self.assertNotIn("Unable to load data.", html)

    def test_pending_row_does_not_affect_sibling_row(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_pending_card(symbol="NEWTICKER"), make_card(symbol="SPY")]}, NO_NEWS
        )

        self.assertIn("Loading&hellip;", html)
        self.assertIn("452.31", html)

    def test_renders_ticker_groups_wrapper_and_checking_indicator(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('id="ticker-groups"', html + TICKERS_JS)
        self.assertIn('id="checking-indicator"', html + TICKERS_JS)
        self.assertIn("Checking for updates", html + TICKERS_JS)
        self.assertIn("/api/tickers/groups/", html + TICKERS_JS)
        self.assertIn("hideCheckingIndicator", html + TICKERS_JS)

    def test_renders_data_group_attribute_on_each_block(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card()], "bonds": [make_card(symbol="VGIT")]}, NO_NEWS
        )

        self.assertIn('data-group="stocks"', html)
        self.assertIn('data-group="bonds"', html)

    def test_renders_market_news_headlines_above_ticker_groups(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, SAMPLE_NEWS)

        self.assertIn('id="market-news"', html)
        self.assertIn("Stocks rally on rate-cut hopes", html)
        self.assertIn("https://example.com/a", html)
        self.assertIn("CNBC", html)
        self.assertLess(html.index('id="market-news"'), html.index('id="ticker-groups"'))

    def test_market_news_pending_shows_loading_placeholder(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, PENDING_NEWS)

        self.assertIn("Loading market news", html)

    def test_market_news_empty_shows_unavailable_message(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("Market news unavailable.", html)

    def test_market_news_html_escapes_headline(self):
        news = {
            "headlines": [{"headline": "<script>alert(1)</script>", "url": "https://example.com", "source": "X", "datetime": 1}],
            "pending": False,
        }
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, news)

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_market_news_patched_by_script(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("/api/market-news/check", html + TICKERS_JS)
        self.assertIn("data.news_html", html + TICKERS_JS)

    def test_there_is_no_ai_valuation_section_or_fetch(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS, SAMPLE_VERDICTS)

        self.assertNotIn("ticker-valuation", html)
        self.assertNotIn("/api/tickers/valuation/check", html + TICKERS_JS)

    def test_each_table_has_a_verdict_column_before_the_trailing_cells(self):
        cards = [make_card(symbol="NVDA"), make_card(symbol="TSLA")]
        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS, SAMPLE_VERDICTS)

        self.assertIn("<th>Verdict</th>", html)
        self.assertLess(html.index("<th>Verdict</th>"), html.index("<th>Full Position</th>"))
        nvda = row_for(html, "NVDA")
        self.assertIn(">Discount<", nvda)
        self.assertIn("Cheaper than its own past year and than its peers. far off its high", nvda)
        self.assertLess(nvda.index("verdict-cell"), nvda.index("full-position"))
        self.assertIn(">Overpriced<", row_for(html, "TSLA"))

    def test_the_group_pill_sits_by_the_group_label_with_the_summary_on_hover(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS, SAMPLE_VERDICTS)

        label = html[html.index('class="category-label"'):]
        label = label[:label.index("</p>")] if "</p>" in label else label
        self.assertIn(">Overpriced<", label)
        self.assertIn("Stocks sit near their highs.", label)
        self.assertNotIn("median", label.lower())

    def test_pill_colours_follow_the_verdict_and_the_word_is_always_shown(self):
        pills = {v: render_verdict_pill(v, "tip", "t-" + v) for v in ("discount", "fair", "overpriced")}

        self.assertEqual(len(set(pills.values())), 3)
        for verdict, word in (("discount", "Discount"), ("fair", "Fair"), ("overpriced", "Overpriced")):
            self.assertIn(f">{word}<", pills[verdict])
        self.assertIn('role="tooltip"', pills["fair"])
        self.assertIn('tabindex="0"', pills["fair"])
        self.assertIn('aria-describedby="t-fair"', pills["fair"])
        self.assertIn('id="t-fair"', pills["fair"])

    def test_every_pill_on_a_page_has_its_own_tip_id(self):
        cards = [make_card(symbol="NVDA"), make_card(symbol="TSLA")]
        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS, SAMPLE_VERDICTS)
        ids = re.findall(r'id="(verdict-tip-[^"]+)"', html)

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 3)

    def test_a_group_with_too_few_tickers_shows_not_judged(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS, {**SAMPLE_VERDICTS, "groups": []})

        self.assertIn("Not judged", html)
        self.assertIn("needs at least 3", html)

    def test_a_ticker_without_a_verdict_shows_not_scored(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(symbol="ZZZ")]}, NO_NEWS, SAMPLE_VERDICTS)

        self.assertIn("Not scored", row_for(html, "ZZZ"))

    def test_no_verdicts_at_all_leaves_every_row_not_scored(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("Not scored", row_for(html, "SPY"))
        self.assertIn("Not judged", html)

    def test_a_loading_row_shows_a_dash_in_the_verdict_column(self):
        html = render_ticker_dashboard_page({"stocks": [make_pending_card()]}, NO_NEWS, SAMPLE_VERDICTS)

        self.assertIn('<td class="verdict-cell muted">&mdash;</td>', html)

    def test_verdict_text_is_escaped(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(symbol="TSLA")]}, NO_NEWS, SAMPLE_VERDICTS)

        self.assertNotIn("<b>near its high</b>", html)
        self.assertIn("&lt;b&gt;near its high&lt;/b&gt;", html)

    def test_the_group_check_response_carries_the_verdicts(self):
        fragments = render_ticker_group_check_response("stocks", [make_card(symbol="NVDA")], verdicts=SAMPLE_VERDICTS)

        self.assertIn(">Discount<", fragments["group_html"])


class TestFullPositionColumn(unittest.TestCase):
    def page(self, cards, **kwargs):
        return render_ticker_dashboard_page({"stocks": cards}, NO_NEWS, **kwargs)

    def test_every_group_table_has_the_column_and_an_unticked_labelled_box_per_row(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card()], "individual": [make_card(symbol="AAPL", group="individual")]}, NO_NEWS)

        self.assertEqual(html.count("<th>Full Position</th>"), 2)
        self.assertIn('data-symbol="SPY" aria-label="Full position in SPY">', html)
        self.assertIn('aria-label="Full position in AAPL">', html)
        self.assertNotIn(" checked>", html.split("<main")[1].split("<script>")[0])

    def test_a_marked_symbol_has_a_ticked_box_and_a_greyed_row_and_others_do_not(self):
        html = self.page([make_card(), make_card(symbol="VGIT")], full_positions=frozenset({"SPY"}))

        self.assertRegex(html, r'<tr data-symbol="SPY" data-pct-in-range="[^"]*" data-full-position="1">')
        self.assertNotRegex(html, r'<tr data-symbol="VGIT"[^>]*data-full-position')
        self.assertIn('aria-label="Full position in SPY" checked>', html)
        self.assertNotIn('aria-label="Full position in VGIT" checked>', html)

    def test_pending_and_errored_rows_have_the_box_too(self):
        html = self.page([make_pending_card(), make_card(symbol="VGIT", error="boom")], full_positions=frozenset({"SPY"}))

        self.assertIn('aria-label="Full position in SPY" checked>', html)
        self.assertIn('aria-label="Full position in VGIT">', html)

    def test_the_group_check_response_keeps_the_ticked_state(self):
        fragment = render_ticker_group_check_response("stocks", [make_card()], frozenset({"SPY"}))["group_html"]

        self.assertIn('data-full-position="1"', fragment)
        self.assertIn(" checked>", fragment)

    def test_markup_in_a_symbol_is_escaped_in_the_label(self):
        html = self.page([make_card(symbol='A"B')])

        self.assertIn('aria-label="Full position in A&quot;B"', html)

    def test_unreadable_marks_add_a_note_and_readable_ones_add_none(self):
        unreadable = self.page([make_card()], full_positions_known=False)
        readable = self.page([make_card()])

        self.assertIn("Full-position marks couldn&#x27;t be loaded.", unreadable)
        self.assertNotIn("couldn&#x27;t be loaded", readable)

    def test_the_save_error_has_its_own_element_so_it_never_wipes_the_load_note(self):
        html = self.page([make_card()], full_positions_known=False)

        self.assertIn('id="full-position-note"', html + TICKERS_JS)
        self.assertIn('id="full-position-error"', html + TICKERS_JS)
        self.assertIn("document.getElementById('full-position-error')", html + TICKERS_JS)

    def test_the_group_swap_script_keeps_ticked_boxes_when_the_marks_could_not_be_read(self):
        html = self.page([make_card()])

        self.assertIn("data.marks_known === false", html + TICKERS_JS)

    def test_the_page_script_posts_the_change_and_restores_the_box_on_failure(self):
        html = self.page([make_card()])

        self.assertIn("/api/full-position", html + TICKERS_JS)
        self.assertIn("the box is back where it was", html + TICKERS_JS)


class TestInvestedColumn(unittest.TestCase):
    def page(self, groups, **kwargs):
        return render_ticker_dashboard_page(groups, NO_NEWS, **kwargs)

    def individual(self, **kwargs):
        return self.page({"individual": [make_card(symbol="AAPL", group="individual")]}, **kwargs)

    def test_only_the_individual_table_has_the_column(self):
        html = self.page({"individual": [make_card(symbol="AAPL", group="individual")], "stocks": [make_card()]})

        self.assertEqual(html.count("<th class=\"num invested-head\">Invested</th>"), 1)
        self.assertEqual(html.count('class="num invested-cell"'), 1)
        self.assertEqual(html.count('class="invested-edit"'), 1)

    def test_it_sits_between_the_data_columns_and_full_position(self):
        html = self.individual()

        self.assertLess(html.index(">PEG</th>"), html.index(">Invested</th>"))
        self.assertLess(html.index(">Invested</th>"), html.index("<th>Full Position</th>"))

    def test_an_amount_shows_in_dollars_with_a_pen_and_no_amount_shows_a_dash(self):
        with_amount = self.individual(amounts={"AAPL": 1500.0})
        without = self.individual()

        self.assertIn('<span class="invested-amount" data-amount="1500.00">$1,500</span>', with_amount)
        self.assertIn('aria-label="Edit invested amount for AAPL"', with_amount)
        self.assertIn('title="Edit the amount invested in AAPL"', with_amount)
        self.assertIn('<span class="muted">&mdash;</span>', without)
        self.assertNotIn("invested-amount", without)

    def test_cents_show_only_when_there_are_cents(self):
        self.assertEqual(format_invested(1500.0), "$1,500")
        self.assertEqual(format_invested(1500.5), "$1,500.50")
        self.assertEqual(format_invested(0.0), "$0")

    def test_pending_and_errored_individual_rows_have_the_cell_too(self):
        html = self.page({"individual": [make_pending_card(symbol="AAPL", group="individual"),
                                         make_card(symbol="MSFT", group="individual", error="boom")]},
                         amounts={"AAPL": 10.0})

        self.assertEqual(html.count('class="num invested-cell"'), 2)

    def test_unreadable_amounts_show_n_a_a_disabled_pen_and_a_note(self):
        html = self.individual(amounts={}, invested_known=False)

        self.assertIn("Invested amounts couldn&#x27;t be loaded.", html)
        self.assertIn('<span class="muted">n/a</span>', html)
        self.assertRegex(html, r'class="invested-edit"[^>]*aria-label="Edit invested amount for AAPL" disabled>')

    def test_the_group_check_keeps_the_amounts_and_reports_none_when_it_cannot_read_them(self):
        fragment = render_ticker_group_check_response("individual", [make_card(symbol="AAPL", group="individual")],
                                                      frozenset(), {"AAPL": 99.0})["group_html"]

        self.assertIn("$99", fragment)

    def test_a_symbol_with_markup_is_escaped_in_the_pen(self):
        html = self.page({"individual": [make_card(symbol='A"B', group="individual")]})

        self.assertIn('data-symbol="A&quot;B"', html.split("invested-edit")[1])

    def test_the_script_has_the_editor_wired_up(self):
        script = TICKERS_JS

        for text in ("/api/invested", "invested-edit", "Couldn't save the amount", "invested_known === false", "th.invested-head"):
            self.assertIn(text, script)
        self.assertIn('id="invested-error"', self.individual())


class TestRenderTickerGroupCheckResponse(unittest.TestCase):
    def test_returns_group_html_for_the_same_cards(self):
        fragments = render_ticker_group_check_response("stocks", [make_card()])

        self.assertIn("group_html", fragments)
        self.assertIn("SPY", fragments["group_html"])
        self.assertIn("452.31", fragments["group_html"])
        self.assertIn('data-group="stocks"', fragments["group_html"])

    def test_does_not_include_other_groups_or_the_full_page_shell(self):
        fragments = render_ticker_group_check_response("stocks", [make_card()])

        self.assertNotIn("<!doctype html>", fragments["group_html"])
        self.assertNotIn("<html", fragments["group_html"])
        self.assertNotIn('id="ticker-groups"', fragments["group_html"])


class TestRenderMarketNewsCheckResponse(unittest.TestCase):
    def test_returns_news_html(self):
        fragments = render_market_news_check_response(SAMPLE_NEWS)

        self.assertIn("news_html", fragments)
        self.assertIn("Stocks rally on rate-cut hopes", fragments["news_html"])

    def test_does_not_include_the_full_page_shell(self):
        fragments = render_market_news_check_response(NO_NEWS)

        self.assertNotIn("<!doctype html>", fragments["news_html"])


class TestRenderRangeBarMissingRange(unittest.TestCase):
    def test_a_missing_low_high_or_price_renders_na(self):
        from page_template import render_range_bar

        for args in ((None, 15.0, 10.0), (8.0, None, 10.0), (8.0, 15.0, None), (None, None, 10.0)):
            html = render_range_bar("TINY", *args)
            self.assertIn("n/a", html)
            self.assertNotIn("<svg", html)


if __name__ == "__main__":
    unittest.main()

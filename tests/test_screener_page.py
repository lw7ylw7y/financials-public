import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "screener"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import scoring
import screener_page
import settings
from kv_store import KvStoreError

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
RECENT = datetime(2026, 10, 19, 5, 30, tzinfo=timezone.utc).isoformat()
STATE = {"initial_pass_done": True, "universe_total": 4747, "universe_checked": 4747,
         "last_run_at": RECENT, "last_run_counts": {}}


def record(name="Acme Corp", market_cap=3000.0, roi=12.0, margin=10.0, debt=0.1, dilution=1.0, growth=15.0,
           flags=None, low=8.0, high=15.0, fcf=None, **extra):
    return {
        "name": name, "cik": 1234, "ipo_date": "2015-01-01", "week52_low": low, "week52_high": high,
        "market_cap": market_cap, "pe_ratio": 20.0, "peg_ratio": 1.5,
        "metrics": {"roi": roi, "roe": 5.0, "net_margin": margin, "debt_to_equity": debt, "eps_growth": 3.0},
        "revenue_growth": growth, "fcf_by_year": fcf or {"2023-12-31": 31.0, "2024-12-31": 30.0, "2025-12-31": 54.0},
        "shares_by_year": {"2023-12-31": 41.2, "2024-12-31": 41.6, "2025-12-31": 41.8},
        "dilution_pct_per_year": dilution, "flags": flags or [], "market_at": RECENT, "scored_at": RECENT,
        **extra,
    }


NAME_WITH_QUOTE = 'Acme "Big" & Sons Corp'


def _js(name):
    with open(os.path.join(_SRC, "web", "static", "js", name)) as f:
        return f.read()


def view_for(candidates, statuses=None, notes=None, state=STATE, earnings=None, watchlist=frozenset(), watchlist_known=True):
    with patch("screener_page.store.load_candidates", return_value=candidates), \
         patch("screener_page.store.load_earnings", return_value=earnings or {}), \
         patch("screener_page.store.load_state", return_value=state), \
         patch("screener_page.page_store.load_statuses", return_value=statuses or {}), \
         patch("screener_page.page_store.load_notes", return_value=notes or {}), \
         patch("screener_page.settings.load_form", return_value=settings.default_form()):
        return screener_page.load_view(NOW, watchlist, watchlist_known)


def symbols_in_order(html):
    return re.findall(r'<tr class="screener-row" data-symbol-row="([^"]+)"', html)


class TestLoadView(unittest.TestCase):
    def test_a_name_passing_every_filter_is_new_and_a_failing_one_is_hidden(self):
        view = view_for({"GOOD": record(), "BAD": record(margin=-5.0)})

        self.assertEqual([r["symbol"] for r in view["rows"]["new"]], ["GOOD"])
        self.assertEqual(view["hidden"], 1)

    def test_a_flagged_name_goes_under_data_check_not_new_or_hidden(self):
        view = view_for({"FLAG": record(flags=["Capex not reported"])})

        self.assertEqual([r["symbol"] for r in view["data_check"]], ["FLAG"])
        self.assertEqual((view["rows"]["new"], view["hidden"]), ([], 0))

    def test_a_name_outside_the_market_cap_band_is_not_shown_or_counted(self):
        view = view_for({"BIG": record(market_cap=90000.0)})

        self.assertEqual((view["rows"]["new"], view["data_check"], view["hidden"]), ([], [], 0))

    def test_a_shortlisted_name_outside_the_band_stays_shortlisted(self):
        view = view_for({"BIG": record(market_cap=90000.0)}, statuses={"BIG": {"status": "shortlisted", "at": RECENT}})

        self.assertEqual([r["symbol"] for r in view["rows"]["shortlisted"]], ["BIG"])
        self.assertIsNone(view["rows"]["shortlisted"][0]["score"])

    def test_a_dismissed_name_that_passes_stays_dismissed_and_does_not_change_other_scores(self):
        candidates = {"A": record(roi=12.0), "B": record(roi=30.0)}
        plain = view_for(candidates)
        dismissed = view_for(candidates, statuses={"B": {"status": "dismissed", "at": RECENT}})

        self.assertEqual([r["symbol"] for r in dismissed["rows"]["dismissed"]], ["B"])
        self.assertEqual(dismissed["rows"]["new"][0]["score"], plain["rows"]["new"][1]["score"])

    def test_rows_sort_by_score_highest_first(self):
        view = view_for({"LOW": record(roi=6.0), "HIGH": record(roi=40.0), "MID": record(roi=20.0)})

        self.assertEqual([r["symbol"] for r in view["rows"]["new"]], ["HIGH", "MID", "LOW"])

    def test_a_failed_read_of_each_key_raises_instead_of_looking_empty(self):
        loaders = ("screener_page.store.load_candidates", "screener_page.store.load_state",
                   "screener_page.page_store.load_statuses", "screener_page.page_store.load_notes",
                   "screener_page.settings.load_form")
        for failing in loaders:
            with self.subTest(failing=failing):
                with patch.multiple("screener_page.store", load_candidates=lambda: {}, load_state=lambda: STATE), \
                     patch.multiple("screener_page.page_store", load_statuses=lambda: {}, load_notes=lambda: {}), \
                     patch("screener_page.settings.load_form", lambda: settings.default_form()), \
                     patch(failing, side_effect=KvStoreError("down")):
                    with self.assertRaises(KvStoreError):
                        screener_page.load_view(NOW)

    def test_the_run_is_stale_after_two_days(self):
        old = {**STATE, "last_run_at": datetime(2026, 10, 14, 5, 30, tzinfo=timezone.utc).isoformat()}

        self.assertTrue(view_for({}, state=old)["run_is_stale"])
        self.assertFalse(view_for({})["run_is_stale"])


class TestRenderScreenerPage(unittest.TestCase):
    def render(self, candidates, tab="new", **kwargs):
        return screener_page.render_screener_page(view_for(candidates, **kwargs), tab)

    def test_rows_render_in_score_order_with_blank_scores_last(self):
        new = {"LOW": record(roi=6.0), "HIGH": record(roi=40.0)}
        shortlisted = {"NOSC": record(margin=-1.0), "SCORED": record(roi=50.0)}
        statuses = {s: {"status": "shortlisted", "at": RECENT} for s in shortlisted}

        self.assertEqual(symbols_in_order(self.render(new)), ["HIGH", "LOW"])
        self.assertEqual(symbols_in_order(self.render(shortlisted, "shortlisted", statuses=statuses)), ["SCORED", "NOSC"])

    def test_price_cells_show_loading_and_rows_are_marked_for_quotes(self):
        html = self.render({"AAA": record()})

        self.assertIn("Loading&hellip;", html)
        self.assertIn('data-quote-row="1"', html)

    def test_the_dismissed_tab_is_never_fetched_shows_dashes_and_the_date_in_the_detail(self):
        statuses = {"AAA": {"status": "dismissed", "at": "2026-10-01T10:00:00+00:00"}}
        html = self.render({"AAA": record()}, "dismissed", statuses=statuses)

        self.assertNotIn('data-quote-row="1"', html)
        self.assertEqual(html.count("&mdash;</td>"), 5)  # the four quote cells and the unknown next-earnings date
        self.assertNotIn("Date Dismissed", html)
        self.assertIn("<li>Dismissed <strong>1 Oct 2026</strong></li>", html)

    def test_price_and_range_headers_do_not_sort_but_the_rest_do(self):
        html = self.render({"AAA": record()})

        self.assertIn('<th class="num">Price</th>', html)
        self.assertIn("<th>52-Week Range</th>", html)
        for key in ("symbol", "change", "pctInRange", "marketCap", "pe", "peg", "nextEarnings"):
            self.assertIn(f'data-sort-key="{key}"', html)

    def test_company_names_and_flag_text_are_escaped(self):
        html = self.render({"AAA": record(name="<script>alert(1)</script> & Co")})

        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co", html)

    def test_a_candidate_without_a_range_shows_na_instead_of_failing(self):
        html = self.render({"AAA": record(low=None, high=None)})
        cells = screener_page.render_quote_cells(
            "AAA", record(low=None, high=None),
            {"price": 5.0, "change": 0.1, "change_percent": 1.0, "quoted_at": NOW.isoformat()}, NOW)

        self.assertIn("AAA", html)
        self.assertEqual(cells.count("n/a"), 2)

    def test_at_most_200_rows_render_and_the_page_says_how_many_were_left_out(self):
        candidates = {f"S{i:03d}": record(roi=5.0 + i / 100) for i in range(205)}
        html = self.render(candidates)

        self.assertEqual(len(symbols_in_order(html)), 200)
        self.assertIn("Showing the 200 highest scores of 205.", html)

    def test_the_detail_row_prints_the_values_on_the_bars_and_lists_filters_and_links(self):
        html = self.render({"AAA": record()})

        self.assertIn("$54M", html)
        self.assertIn("41.8M", html)
        self.assertIn("&#10003; Net margin", html)
        self.assertIn("sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=1234", html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("Figures refreshed 19 Oct 2026", html)

    def test_a_negative_free_cash_flow_bar_prints_its_sign(self):
        html = self.render({"AAA": record(fcf={"2024-12-31": -3.0, "2025-12-31": 10.0}, margin=1.0)})

        self.assertIn("-$3M", html)

    def test_a_saved_note_fills_the_note_field_and_shows_the_flag(self):
        with_note = self.render({"AAA": record()}, notes={"AAA": {"text": "look at margins", "at": RECENT}})
        without = self.render({"AAA": record()})

        self.assertIn(">look at margins</textarea>", with_note)
        self.assertIn('<span class="co note-flag">', with_note)
        self.assertIn('<span class="co note-flag" hidden>', without)

    def test_markup_in_a_note_renders_as_text(self):
        html = self.render({"AAA": record()}, notes={"AAA": {"text": "</textarea><script>x()</script>", "at": RECENT}})

        self.assertIn("&lt;/textarea&gt;&lt;script&gt;x()&lt;/script&gt;", html)
        self.assertNotIn("<script>x()", html)

    def test_the_new_tab_says_how_many_are_shown_and_hidden(self):
        html = self.render({"GOOD": record(), "BAD": record(margin=-5.0)})

        self.assertIn('<span id="shown-count">1</span> names shown &middot; 1 hidden by your filters', html)

    def test_an_empty_new_tab_blames_the_filters_only_when_they_hide_names(self):
        hidden = self.render({"BAD": record(margin=-5.0)})
        nothing = self.render({})

        self.assertIn("1 names are hidden by your filters.", hidden)
        self.assertNotIn('<p class="empty">Nothing left to review', hidden)
        self.assertIn('<p class="empty">Nothing left to review.</p>', nothing)

    def test_empty_shortlisted_and_dismissed_tabs_have_their_own_text(self):
        self.assertIn("Nothing shortlisted yet.", self.render({}, "shortlisted"))
        self.assertIn("Nothing dismissed.", self.render({}, "dismissed"))

    def test_tab_counts_and_the_selected_tab(self):
        statuses = {"S": {"status": "shortlisted", "at": RECENT}}
        html = self.render({"A": record(), "S": record()}, statuses=statuses)

        self.assertIn('aria-current="page">New (<span class="tab-count">1</span>)', html)
        self.assertIn('>Shortlisted (<span class="tab-count">1</span>)', html)
        self.assertIn('>Dismissed (<span class="tab-count">0</span>)', html)

    def test_an_unknown_tab_falls_back_to_new(self):
        self.assertIn('aria-current="page">New', self.render({"A": record()}, "bogus"))

    def test_data_check_rows_list_every_reason_collapsed_under_the_table(self):
        html = self.render({"F": record(flags=["Capex not reported", "IFRS filer, not scored yet"])})

        self.assertIn("Needs a data check (1)", html)
        self.assertIn("Capex not reported &middot; IFRS filer, not scored yet", html.replace(" · ", " &middot; "))

    def test_the_data_line_shows_the_last_run_and_the_pass_count(self):
        html = self.render({"A": record()})

        self.assertIn("Last nightly run 19 Oct 2026 &middot; 1 pass all filters &middot; ownership % is not screened", html)

    def test_a_stale_run_says_so(self):
        old = {**STATE, "last_run_at": datetime(2026, 10, 14, 5, 30, tzinfo=timezone.utc).isoformat()}
        html = self.render({}, state=old)

        self.assertIn("hasn&#x27;t completed since 14 Oct", html)

    def test_an_incomplete_initial_pass_shows_progress(self):
        running = {**STATE, "initial_pass_done": False, "universe_checked": 1240}
        html = self.render({}, state=running)

        self.assertIn("Initial screen in progress: 1,240 of 4,747 symbols checked.", html)

    def test_before_the_first_run_the_page_says_so(self):
        html = self.render({}, state={})

        self.assertIn("hasn&#x27;t run yet", html)
        self.assertNotIn("<table", html)

    def test_the_nav_has_a_third_active_pill(self):
        html = self.render({})

        self.assertIn('<a href="/screener" class="active">Small &amp; Mid-Cap Screener</a>', html)

    def test_the_error_page_shows_no_table_and_dashes_for_the_counts(self):
        html = screener_page.render_error_page()

        self.assertIn("Couldn&#x27;t load the screener data (storage error). Reload to try again.", html)
        self.assertNotIn("<table", html)
        self.assertIn("New (<span class=\"tab-count\">&mdash;</span>)", html)


class TestTriageMarkup(unittest.TestCase):
    def render(self, candidates, tab, statuses=None, **kwargs):
        return screener_page.render_screener_page(view_for(candidates, statuses=statuses, **kwargs), tab)

    def test_each_list_has_its_own_actions(self):
        statuses = {"S": {"status": "shortlisted", "at": RECENT}, "D": {"status": "dismissed", "at": RECENT}}
        candidates = {"N": record(), "S": record(), "D": record()}

        new = self.render(candidates, "new", statuses)
        shortlisted = self.render(candidates, "shortlisted", statuses)
        dismissed = self.render(candidates, "dismissed", statuses)

        self.assertIn('data-action="shortlisted"', new)
        self.assertIn('data-action="dismissed"', new)
        self.assertNotIn('data-action="new"', new)
        self.assertNotIn("Move to New", shortlisted)
        self.assertIn('data-action="promote" aria-label="Promote S"', shortlisted)
        self.assertIn('data-action="dismissed" aria-label="Dismiss S"', shortlisted)
        self.assertIn('data-action="new" aria-label="Restore D"', dismissed)
        self.assertNotIn('data-action="dismissed"', dismissed)

    def test_a_shortlisted_name_that_now_fails_a_filter_says_which(self):
        statuses = {"S": {"status": "shortlisted", "at": RECENT}}

        html = self.render({"S": record(debt=0.8)}, "shortlisted", statuses)

        self.assertIn("No longer passes: Debt/equity 0.8", html)
        self.assertEqual(symbols_in_order(html), ["S"])

    def test_a_shortlisted_name_that_still_passes_has_no_warning(self):
        statuses = {"S": {"status": "shortlisted", "at": RECENT}}

        self.assertNotIn("No longer passes", self.render({"S": record()}, "shortlisted", statuses))

    def test_a_dismissed_name_that_now_passes_is_flagged_and_counted_but_stays_dismissed(self):
        statuses = {"D": {"status": "dismissed", "at": RECENT, "passed_at_dismissal": False, "score_at_dismissal": None}}

        html = self.render({"D": record()}, "dismissed", statuses)

        self.assertIn("&#9650; Now passes your filters (score 50)", html)
        self.assertIn("1 dismissed name has improved since you dismissed it.", html)
        self.assertEqual(symbols_in_order(self.render({"D": record()}, "new", statuses)), [])

    def test_a_score_that_rose_by_the_delta_shows_both_scores(self):
        statuses = {"D": {"status": "dismissed", "at": RECENT, "passed_at_dismissal": True, "score_at_dismissal": 40.0}}

        html = self.render({"D": record()}, "dismissed", statuses)

        self.assertIn("Improved since you dismissed it (score 40 &rarr; 50)", html)

    def test_no_flag_or_line_when_nothing_improved(self):
        statuses = {"D": {"status": "dismissed", "at": RECENT, "passed_at_dismissal": True, "score_at_dismissal": 45.0}}

        html = self.render({"D": record()}, "dismissed", statuses)

        self.assertNotIn('class="improved-flag"', html)
        self.assertNotIn('id="improved-line"', html)

    def test_two_improved_names_use_the_plural_line(self):
        statuses = {s: {"status": "dismissed", "at": RECENT, "passed_at_dismissal": False} for s in ("A", "B")}

        html = self.render({"A": record(), "B": record()}, "dismissed", statuses)

        self.assertIn("2 dismissed names have improved since you dismissed them.", html)

    def test_the_page_has_the_toast_region_and_a_save_button_that_starts_disabled(self):
        html = self.render({"A": record()}, "new")

        self.assertIn('id="announce" class="sr-only" role="status" aria-live="polite"', html)
        self.assertIn('id="toast" class="toast" role="status" aria-live="polite" hidden', html)
        self.assertIn('data-action="save-note" disabled', html)


class TestListFor(unittest.TestCase):
    def test_where_a_name_with_no_status_shows(self):
        def landing(**kwargs):
            return screener_page.list_for(scoring.evaluate(record(**kwargs), scoring.DEFAULT_SETTINGS, NOW.date()))

        self.assertEqual(landing(), "new")
        self.assertEqual(landing(margin=-5.0), "hidden")
        self.assertEqual(landing(flags=["Capex not reported"]), "data_check")
        self.assertEqual(landing(market_cap=90000.0), "out_of_band")


class TestRenderQuoteCells(unittest.TestCase):
    def quote(self, quoted_at=NOW):
        return {"price": 12.0, "change": 0.3, "change_percent": 2.5, "quoted_at": quoted_at.isoformat()}

    def test_a_fresh_quote_fills_the_four_cells(self):
        cells = screener_page.render_quote_cells("AAA", record(high=15.0), self.quote(), NOW)

        self.assertEqual(cells.count("<td"), 4)
        self.assertIn("$12.00", cells)
        self.assertIn("57%", cells)
        self.assertNotIn("as of", cells)

    def test_an_old_cached_quote_shows_its_age(self):
        old = datetime(2026, 10, 20, 14, 2, tzinfo=timezone.utc)
        cells = screener_page.render_quote_cells("AAA", record(), self.quote(old), NOW)

        self.assertIn("as of 14:02 UTC", cells)

    def test_a_price_above_the_stored_high_shows_100_in_range(self):
        cells = screener_page.render_quote_cells("AAA", record(high=10.0), self.quote(), NOW)

        self.assertIn("100%", cells)

    def test_a_record_without_a_low_shows_na_in_range(self):
        cells = screener_page.render_quote_cells("AAA", record(low=None), self.quote(), NOW)

        self.assertIn('<td class="num muted">n/a</td>', cells)

    def test_every_sortable_header_has_a_matching_row_attribute(self):
        html = screener_page.render_screener_page(view_for({"AAA": record()}), "new")
        keys = re.findall(r'data-sort-key="(\w+)"', html)

        self.assertIn("pctInRange", keys)
        for key in keys:
            self.assertIn(f' data-{key.lower()}="', html.split('class="screener-row"')[1], key)

    def test_the_checking_indicator_shows_only_where_prices_are_loading(self):
        statuses = {"AAA": {"status": "dismissed", "at": RECENT}}
        with_rows = screener_page.render_screener_page(view_for({"AAA": record()}), "new")
        dismissed = screener_page.render_screener_page(view_for({"AAA": record()}, statuses=statuses), "dismissed")

        self.assertIn('id="checking-indicator"', with_rows)
        self.assertNotIn('id="checking-indicator"', dismissed)

    def test_no_quote_is_na_in_all_four_cells(self):
        cells = screener_page.render_quote_cells("AAA", record(), None, NOW)

        self.assertEqual((cells.count("<td"), cells.count("n/a")), (4, 4))


class TestColumnsMatchTheTickerDashboardIndividualTable(unittest.TestCase):
    def headers(self, tab, statuses=None):
        html = screener_page.render_screener_page(view_for({"AAA": record()}, statuses=statuses), tab)
        head = html.split("<thead>")[1].split("</thead>")[0]
        return [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>.*?</th>", head, re.S)]

    def test_the_new_and_dismissed_tabs_keep_the_individual_tables_data_columns_and_next_earnings(self):
        expected = ["Ticker", "Score", "Price", "Change", "52-Week Range", "% in Range", "Market Cap", "P/E", "PEG", "Next Earnings", ""]
        self.assertEqual(self.headers("new"), expected)
        self.assertEqual(self.headers("dismissed", {"AAA": {"status": "dismissed", "at": RECENT}}), expected)

    def test_all_three_tabs_have_the_same_columns(self):
        headers = self.headers("shortlisted", {"AAA": {"status": "shortlisted", "at": RECENT}})

        self.assertEqual(headers, self.headers("new"))
        self.assertEqual(len(headers), 11)

    def test_the_other_figures_are_in_the_detail_row(self):
        html = screener_page.render_screener_page(view_for({"AAA": record(roi=12.0, debt=0.1, dilution=1.0, growth=15.0)}), "new")
        detail = html.split('<h4>Key figures</h4>')[1].split("</ul>")[0]

        for label in ("ROI", "Debt/equity", "FCF", "Dilution", "Revenue growth"):
            self.assertIn(label, detail)
        self.assertIn("<strong>12%</strong>", detail)
        self.assertIn("<strong>+15%</strong>", detail)

    def test_missing_figures_say_n_a_in_the_detail(self):
        view = view_for({"AAA": record(flags=["Capex not reported"])}, statuses={"AAA": {"status": "shortlisted", "at": RECENT}})
        html = screener_page.render_screener_page(view, "shortlisted")

        self.assertIn("<td class=\"num\">n/a</td>", html)

    def test_the_score_is_a_sortable_column(self):
        html = screener_page.render_screener_page(view_for({"AAA": record()}), "new")

        self.assertRegex(html, r'<th class="num sortable" data-sort-key="score"')
        self.assertRegex(html, r'<td class="num">\d+</td>')


class TestLongCompanyName(unittest.TestCase):
    def test_the_name_has_its_own_class_and_the_full_text_as_a_tooltip(self):
        html = screener_page.render_screener_page(view_for({"AAA": record(name=NAME_WITH_QUOTE)}), "new")

        self.assertIn('class="co company-name" title="Acme &quot;Big&quot; &amp; Sons Corp">Acme &quot;Big&quot; &amp; Sons Corp</span>', html)

    def test_the_stylesheet_truncates_the_name_and_caps_the_column(self):
        with open(os.path.join(_SRC, "web", "static", "dashboard.css")) as f:
            css = f.read()

        rule = re.search(r"\.screener-table \.company-name \{([^}]*)\}", css).group(1)
        for declaration in ("overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
            self.assertIn(declaration, rule)
        self.assertRegex(css, r"\.screener-table td\.ticker-cell > span \{ max-width: 1\d\dpx; \}")


class TestPromote(unittest.TestCase):
    def render(self, tab, watchlist=frozenset({"AAA"}), known=True):
        statuses = {"AAA": {"status": "shortlisted", "at": RECENT}, "BBB": {"status": "shortlisted", "at": RECENT},
                    "DDD": {"status": "dismissed", "at": RECENT}}
        view = view_for({"AAA": record(), "BBB": record(), "CCC": record(), "DDD": record()}, statuses=statuses,
                        watchlist=watchlist, watchlist_known=known)
        return screener_page.render_screener_page(view, tab)

    def test_a_shortlisted_name_in_the_watchlist_is_greyed_with_a_disabled_promoted_button(self):
        html = self.render("shortlisted")

        self.assertRegex(html, r'<tr class="screener-row" data-symbol-row="AAA"[^>]*data-promoted="1">')
        self.assertIn('data-action="promote" disabled aria-label="AAA is promoted"', html)
        self.assertIn("Promoted &#10003;", html)

    def test_a_shortlisted_name_not_in_the_watchlist_is_normal_with_a_promote_button_and_a_tooltip(self):
        html = self.render("shortlisted")

        self.assertNotRegex(html, r'data-symbol-row="BBB"[^>]*data-promoted')
        self.assertIn('data-action="promote" aria-label="Promote BBB" title="Add BBB to the Individual table', html)
        self.assertRegex(html, r'aria-label="Promote BBB" title="[^"]*grey[^"]*"[^>]*>Promote</button>')

    def test_the_button_reads_just_promote_and_there_is_no_move_to_new_or_full_position(self):
        html = self.render("shortlisted")

        self.assertNotIn("Move to New", html)
        self.assertNotIn("Full Position", html)
        self.assertNotIn("full-position", html.split("<main")[1].split("<script")[0])

    def test_only_the_shortlisted_tab_has_promote(self):
        for tab in ("new", "dismissed"):
            html = self.render(tab)
            self.assertNotIn('data-action="promote"', html)
            self.assertNotIn("data-promoted", html.split("<main")[1].split("<script")[0])

    def test_a_dismissed_name_in_the_watchlist_is_not_greyed(self):
        html = self.render("dismissed", watchlist=frozenset({"DDD"}))

        self.assertNotIn("data-promoted", html.split("<main")[1].split("<script")[0])

    def test_an_unreadable_watchlist_still_renders_with_a_note_and_every_button_up(self):
        html = self.render("shortlisted", watchlist=frozenset(), known=False)

        self.assertIn("Couldn&#x27;t read your watchlist; Promote buttons may be out of date.", html)
        self.assertEqual(html.count('data-action="promote" aria-label="Promote'), 2)

    def test_the_watchlist_does_not_change_statuses_scores_or_notes(self):
        with_list = view_for({"AAA": record(), "BBB": record(roi=30.0)}, watchlist=frozenset({"AAA"}))
        without = view_for({"AAA": record(), "BBB": record(roi=30.0)})

        self.assertEqual([(r["symbol"], r["score"]) for r in with_list["rows"]["new"]],
                         [(r["symbol"], r["score"]) for r in without["rows"]["new"]])

    def test_the_script_posts_the_promotion_and_puts_the_button_back_on_failure(self):
        script = _js("screener.js")

        self.assertIn("/api/screener/promote", script)
        self.assertIn("Couldn't add", script)
        self.assertIn("button.disabled = promoted", script)

    def test_the_detail_row_spans_all_eleven_columns_on_every_tab(self):
        for tab in ("new", "shortlisted", "dismissed"):
            self.assertIn('<td colspan="11">', self.render(tab))

    def test_the_promote_button_carries_its_promoted_tooltip_for_the_script(self):
        html = self.render("shortlisted")

        self.assertIn('data-promoted-title="BBB is in the Individual table on the Ticker Dashboard.', html)

    def test_the_sticky_ticker_cell_sits_above_the_greyed_cells_of_a_promoted_row(self):
        with open(os.path.join(_SRC, "web", "static", "dashboard.css")) as f:
            css = f.read()

        self.assertRegex(css, r"\.screener-table td\.ticker-cell \{ position: sticky; left: 0; z-index: 1;")
        self.assertRegex(css, r"tr\[data-promoted\] td:not\(\.actions-cell\)")

    def test_the_row_action_handler_leaves_promote_to_its_own_handler(self):
        script = _js("screener.js")

        self.assertIn("button.dataset.action === 'promote'", script)

    def test_the_page_loads_its_scripts_from_versioned_files(self):
        html = self.render("shortlisted")

        self.assertRegex(html, r'<script src="/static/js/screener\.js\?v=\d+"></script><script src="/static/js/screener_filters\.js\?v=\d+"></script>')
        self.assertRegex(html, r'<link rel="stylesheet" href="/static/dashboard\.css\?v=\d+">')
        self.assertNotIn("<script>", html)


class TestReviewDue(unittest.TestCase):
    def status(self, kind="shortlisted", at="2026-09-01T10:00:00+00:00", **extra):
        return {"status": kind, "at": at, **extra}

    def dates(self, last=None, next_=None, fetched=RECENT):
        return {"last": last, "next": next_, "fetched_at": fetched}

    def row_for(self, status, dates, tab="shortlisted"):
        view = view_for({"AAA": record()}, statuses={"AAA": status}, earnings={"AAA": dates} if dates else {})
        return view["rows"][tab][0], view

    def test_due_when_the_company_reported_after_the_last_review(self):
        row, _ = self.row_for(self.status(), self.dates(last="2026-10-05"))

        self.assertTrue(row["review_due"])

    def test_not_due_when_the_last_review_is_after_the_last_report(self):
        row, _ = self.row_for(self.status(checked_at="2026-10-08"), self.dates(last="2026-10-05"))

        self.assertFalse(row["review_due"])

    def test_checked_at_wins_over_the_status_date_and_the_status_date_is_the_fallback(self):
        later, _ = self.row_for(self.status(at="2026-09-01T10:00:00+00:00", checked_at="2026-10-10"), self.dates(last="2026-10-05"))
        fallback, _ = self.row_for(self.status(at="2026-10-10T10:00:00+00:00"), self.dates(last="2026-10-05"))

        self.assertEqual((later["review_due"], later["checked_on"]), (False, "2026-10-10"))
        self.assertEqual((fallback["review_due"], fallback["checked_on"]), (False, "2026-10-10"))

    def test_with_no_dates_it_is_due_after_a_hundred_days_and_not_before(self):
        old, _ = self.row_for(self.status(at="2026-07-01T10:00:00+00:00"), None)  # 111 days before NOW
        recent, _ = self.row_for(self.status(at="2026-07-20T10:00:00+00:00"), None)  # 92 days
        no_last, _ = self.row_for(self.status(at="2026-07-01T10:00:00+00:00"), self.dates(next_="2026-11-05"))

        self.assertEqual((old["review_due"], recent["review_due"], no_last["review_due"]), (True, False, True))

    def test_a_dismissed_name_can_be_due_too(self):
        row, _ = self.row_for(self.status("dismissed"), self.dates(last="2026-10-05"), tab="dismissed")

        self.assertTrue(row["review_due"])

    def test_a_new_name_is_never_flagged_and_still_shows_its_date(self):
        view = view_for({"AAA": record()}, earnings={"AAA": self.dates(last="2026-10-05", next_="2027-01-05")})
        row = view["rows"]["new"][0]
        html = screener_page.render_screener_page(view, "new")

        self.assertFalse(row["review_due"])
        self.assertNotIn("Review due", html)
        self.assertIn("5 Jan 2027", html)

    def test_the_tab_headers_count_due_names_on_shortlisted_and_dismissed_only(self):
        statuses = {"S1": self.status(), "S2": self.status(checked_at="2026-10-10"), "D1": self.status("dismissed")}
        candidates = {s: record() for s in ("S1", "S2", "D1", "N")}
        earnings = {s: self.dates(last="2026-10-05") for s in candidates}
        view = view_for(candidates, statuses=statuses, earnings=earnings)
        html = screener_page.render_screener_page(view, "shortlisted")

        self.assertEqual(view["due"], {"new": 0, "shortlisted": 1, "dismissed": 1})
        self.assertRegex(html, r'Shortlisted \(<span class="tab-count">2</span>\)<span class="tab-due"> &middot; <span class="tab-due-count">1</span> due')
        self.assertNotRegex(html, r'New \(<span class="tab-count">\d+</span>\)<span class="tab-due"> &middot;')

    def test_a_due_row_has_words_a_marker_and_the_row_attribute_not_colour_alone(self):
        view = view_for({"AAA": record()}, statuses={"AAA": self.status()}, earnings={"AAA": self.dates(last="2026-10-05")})
        html = screener_page.render_screener_page(view, "shortlisted")

        self.assertIn("Review due", html)
        self.assertIn('data-review-due="1"', html)
        self.assertIn("&#9201;", html)

    def test_the_next_earnings_column_shows_the_date_dashes_when_unknown_and_sorts(self):
        view = view_for({"A": record(), "B": record()}, earnings={"A": self.dates(next_="2026-11-05")})
        html = screener_page.render_screener_page(view, "new")

        self.assertIn("Next Earnings", html)
        self.assertIn('title="Projected until the company announces"', html)
        self.assertIn("5 Nov 2026", html)
        self.assertIn('data-sort-key="nextEarnings"', html)
        self.assertRegex(html, r'data-symbol-row="A"[^>]*data-nextearnings="\d')
        self.assertRegex(html, r'data-symbol-row="B"[^>]*data-nextearnings=""')

    def test_dates_fetched_over_ten_days_ago_say_they_may_be_out_of_date(self):
        stale = (NOW - timedelta(days=11)).isoformat()
        fresh = (NOW - timedelta(days=9)).isoformat()
        old = view_for({"A": record()}, earnings={"A": self.dates(next_="2026-11-05", fetched=stale)})
        new = view_for({"A": record()}, earnings={"A": self.dates(next_="2026-11-05", fetched=fresh)})

        self.assertIn("(may be out of date)", screener_page.render_screener_page(old, "new"))
        self.assertNotIn("(may be out of date)", screener_page.render_screener_page(new, "new"))

    def test_a_next_date_already_in_the_past_says_it_may_be_out_of_date(self):
        view = view_for({"A": record()}, earnings={"A": self.dates(next_="2026-10-19", fetched=(NOW - timedelta(days=1)).isoformat())})

        self.assertIn("(may be out of date)", screener_page.render_screener_page(view, "new"))

    def test_one_malformed_stored_entry_is_treated_as_unknown_dates_not_a_server_error(self):
        statuses = {"A": self.status(at="2026-07-01T10:00:00+00:00"), "B": self.status()}
        earnings = {"A": {"next": "soon", "last": "2026-10-05", "fetched_at": RECENT}, "B": {"fetched_at": "bad"}}
        view = view_for({"A": record(), "B": record()}, statuses=statuses, earnings=earnings)
        rows = {r["symbol"]: r for r in view["rows"]["shortlisted"]}

        self.assertEqual((rows["A"]["next_earnings"], rows["A"]["last_earnings"]), (None, None))
        self.assertTrue(rows["A"]["review_due"])  # falls back to the 100-day rule: checked 111 days ago
        self.assertFalse(rows["B"]["review_due"])  # 50 days
        screener_page.render_screener_page(view, "shortlisted")

    def test_unreadable_dates_still_render_the_page_with_a_note_and_the_hundred_day_rule(self):
        with patch("screener_page.store.load_earnings", side_effect=KvStoreError("down")), \
             patch("screener_page.store.load_candidates", return_value={"AAA": record()}), \
             patch("screener_page.store.load_state", return_value=STATE), \
             patch("screener_page.page_store.load_statuses", return_value={"AAA": self.status(at="2026-07-01T10:00:00+00:00")}), \
             patch("screener_page.page_store.load_notes", return_value={}), \
             patch("screener_page.settings.load_form", return_value=settings.default_form()):
            view = screener_page.load_view(NOW)
        html = screener_page.render_screener_page(view, "shortlisted")

        self.assertFalse(view["dates_known"])
        self.assertTrue(view["rows"]["shortlisted"][0]["review_due"])
        self.assertIn("Earnings dates couldn&#x27;t be loaded", html)

    def test_a_failed_read_of_the_statuses_still_fails_loudly(self):
        with patch("screener_page.store.load_earnings", return_value={}), \
             patch("screener_page.store.load_candidates", return_value={}), \
             patch("screener_page.store.load_state", return_value=STATE), \
             patch("screener_page.page_store.load_statuses", side_effect=KvStoreError("down")), \
             patch("screener_page.page_store.load_notes", return_value={}), \
             patch("screener_page.settings.load_form", return_value=settings.default_form()):
            with self.assertRaises(KvStoreError):
                screener_page.load_view(NOW)

    def test_the_detail_row_shows_last_checked_and_last_reported(self):
        view = view_for({"AAA": record()}, statuses={"AAA": self.status(checked_at="2026-10-10")},
                        earnings={"AAA": self.dates(last="2026-10-05")})
        html = screener_page.render_screener_page(view, "shortlisted")

        self.assertIn("Last checked 10 Oct 2026 &middot; Last reported 5 Oct 2026", html)


class TestFilterSettingsEffect(unittest.TestCase):
    def view(self, candidates, statuses, form):
        with patch("screener_page.store.load_candidates", return_value=candidates), \
             patch("screener_page.store.load_earnings", return_value={}), \
             patch("screener_page.store.load_state", return_value=STATE), \
             patch("screener_page.page_store.load_statuses", return_value=statuses), \
             patch("screener_page.page_store.load_notes", return_value={}), \
             patch("screener_page.settings.load_form", return_value=form):
            return screener_page.load_view(NOW)

    def tight(self):
        form = settings.default_form()
        form["min_roi_pct"] = {"value": 50.0, "on": True}
        return form

    def test_a_shortlisted_name_that_now_fails_stays_shortlisted_and_shows_which_filter(self):
        view = self.view({"A": record(roi=12.0)}, {"A": {"status": "shortlisted", "at": RECENT}}, self.tight())

        self.assertEqual([r["symbol"] for r in view["rows"]["shortlisted"]], ["A"])
        self.assertEqual(view["rows"]["shortlisted"][0]["failing"], ["ROI 12%"])

    def test_a_dismissed_name_that_now_passes_stays_dismissed(self):
        loose = settings.default_form()
        loose["min_roi_pct"] = {"value": 5.0, "on": False}
        view = self.view({"A": record(roi=1.0)}, {"A": {"status": "dismissed", "at": RECENT, "passed_at_dismissal": False}}, loose)

        self.assertEqual([r["symbol"] for r in view["rows"]["dismissed"]], ["A"])
        self.assertEqual(view["rows"]["new"], [])

    def test_a_name_hidden_by_the_settings_has_no_state_and_returns_when_they_loosen(self):
        candidates = {"A": record(roi=12.0)}

        tight = self.view(candidates, {}, self.tight())
        loose = self.view(candidates, {}, settings.default_form())

        self.assertEqual((tight["hidden"], tight["rows"]["new"]), (1, []))
        self.assertEqual((loose["hidden"], [r["symbol"] for r in loose["rows"]["new"]]), (0, ["A"]))

    def test_the_score_is_recomputed_among_the_names_that_pass(self):
        candidates = {"A": record(roi=12.0), "B": record(roi=60.0), "C": record(roi=70.0)}
        before = self.view(candidates, {}, settings.default_form())
        after = self.view(candidates, {}, self.tight())

        self.assertEqual(len(before["rows"]["new"]), 3)
        self.assertEqual([r["symbol"] for r in after["rows"]["new"]], ["C", "B"])
        self.assertEqual({r["symbol"]: r["score"] for r in after["rows"]["new"]}, {"C": 60.0, "B": 40.0})
        self.assertNotEqual({r["symbol"]: r["score"] for r in before["rows"]["new"]}["B"], 40.0)

    def test_count_new_matches_the_new_tab_and_ignores_shortlisted_and_dismissed(self):
        candidates = {"A": record(), "B": record(), "C": record(), "D": record(roi=1.0)}
        statuses = {"B": {"status": "shortlisted", "at": RECENT}, "C": {"status": "dismissed", "at": RECENT}}

        count = screener_page.count_new(candidates, statuses, scoring.DEFAULT_SETTINGS, NOW.date())
        view = self.view(candidates, statuses, settings.default_form())

        self.assertEqual((count, len(view["rows"]["new"])), (1, 1))

    def test_the_filters_bar_has_the_button_on_every_tab_and_the_counts_on_new_only(self):
        view = self.view({"A": record(), "B": record(roi=1.0)}, {}, settings.default_form())

        new = screener_page.render_screener_page(view, "new")
        shortlisted = screener_page.render_screener_page(view, "shortlisted")

        for html in (new, shortlisted):
            self.assertIn('id="filters-toggle" aria-expanded="false"', html)
        self.assertIn('names shown &middot; 1 hidden by your filters', new)
        self.assertNotIn("hidden by your filters", shortlisted)

    def test_the_panel_lists_every_filter_with_its_value_and_a_switch(self):
        form = settings.default_form()
        form["max_debt_equity"] = {"value": 0.8, "on": False}
        html = screener_page.render_screener_page(self.view({"A": record()}, {}, form), "new")

        for field in settings.FIELDS:
            self.assertIn(f'data-field="{field}" data-part="value"', html)
        for field in settings.SWITCHABLE:
            self.assertIn(f'data-field="{field}" data-part="on"', html)
        self.assertIn('data-field="max_debt_equity" data-part="value" value="0.8"', html)
        self.assertEqual(html.count('data-part="on" checked'), len(settings.SWITCHABLE) - 1)
        self.assertIn('id="filters-panel"', html)

    def test_a_large_saved_value_is_rendered_in_full_not_in_exponent_form(self):
        form = settings.default_form()
        form["fcf_min_m"] = {"value": 1234567.0, "on": True}
        html = screener_page.render_screener_page(self.view({"A": record()}, {}, form), "new")

        self.assertIn('data-field="fcf_min_m" data-part="value" value="1234567"', html)

    def test_an_empty_new_tab_points_to_the_filters(self):
        html = screener_page.render_screener_page(self.view({"A": record(roi=1.0)}, {}, settings.default_form()), "new")

        self.assertIn("1 names are hidden by your filters. Open Filters to change them.", html)


if __name__ == "__main__":
    unittest.main()

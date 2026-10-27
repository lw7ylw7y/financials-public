import os
import re
import sys
import unittest
from datetime import date

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "web"), os.path.join(_SRC, "storage")):
    sys.path.insert(0, _p)

import reads_chart
import reads_history


def entry(lead=0.2, coin=0.0, lag=-0.3, source="replay", reads=("improving", "mixed", "weakening")):
    scores = {"leading": lead, "coincident": coin, "lagging": lag}
    return {"groups": {g: {"read": r, "score": scores[g], "scored": 3, "total": 3} for g, r in zip(reads_history.GROUPS, reads)},
            "stance": None, "source": source, "saved_at": "2026-10-22T00:00:00+00:00"}


def months(start_year, count):
    return [f"{start_year + i // 12}-{i % 12 + 1:02d}" for i in range(count)]


def history(count=200, live_from=None):
    reads = {m: entry(source="live" if live_from and m >= live_from else "replay") for m in months(2005, count)}
    return reads


NO_FIT = {g: {"shift": 0, "best": None, "gain": None, "halves": None, "applied": False, "reason": "not enough"} for g in reads_history.GROUPS}
LAG_FIT = {**NO_FIT, "lagging": {"shift": -7, "best": -7, "gain": 0.11, "halves": (-6, -8), "applied": True, "reason": ""}}


def path_of(html, group):
    return re.search(rf'class="history-line history-line-{group}" d="([^"]*)"', html).group(1)


class TestChart(unittest.TestCase):
    def render(self, reads=None, recessions=None, fit=NO_FIT, today=date(2026, 10, 22)):
        return reads_chart.render_reads_history(reads if reads is not None else history(), recessions if recessions is not None else {}, fit, today)

    def test_gaps_are_not_interpolated(self):
        reads = history()
        del reads["2012-03"]

        self.assertEqual(path_of(self.render(reads), "leading").count("M"), 2)

    def test_a_full_history_is_one_unbroken_line(self):
        self.assertEqual(path_of(self.render(), "leading").count("M"), 1)

    def test_each_line_has_a_different_dash_pattern_and_an_end_label_with_the_read(self):
        html = self.render()
        patterns = {g: re.search(rf'history-line-{g}" d="[^"]*" stroke-dasharray="([^"]*)"', html).group(1) for g in reads_history.GROUPS}

        self.assertEqual(len(set(patterns.values())), 3)
        self.assertIn("Leading: Improving", html)
        self.assertIn("Coincident: Mixed", html)
        self.assertIn("Lagging: Weakening", html)

    def test_labels_closer_than_the_gap_are_stacked_apart(self):
        reads = {m: entry(lead=0.0, coin=0.01, lag=0.02) for m in months(2005, 200)}
        html = self.render(reads)
        ys = sorted(float(v) for v in re.findall(r'class="history-label [^"]*" x="[\d.]+" y="([\d.]+)"', html[:html.index("</svg>")]))

        self.assertEqual(len(ys), 3)
        self.assertGreaterEqual(ys[1] - ys[0], reads_chart.LABEL_GAP - 0.2)
        self.assertGreaterEqual(ys[2] - ys[1], reads_chart.LABEL_GAP - 0.2)

    def test_the_toggles_use_aria_pressed_and_only_leading_is_shown_at_first(self):
        html = self.render()

        self.assertEqual(html.count('aria-pressed="true"'), 2)
        self.assertRegex(html, r'data-group="leading" aria-pressed="true"')
        self.assertRegex(html, r'data-group="coincident" aria-pressed="false"')
        self.assertRegex(html, r'data-group="lagging" aria-pressed="false"')
        self.assertRegex(html, r'data-range="10y" aria-pressed="true"')
        self.assertNotIn("data-view", html)

    def test_coincident_and_lagging_start_hidden_and_leading_does_not(self):
        html = self.render()
        card = re.search(r'<section class="card history-card([^"]*)"', html).group(1).split()

        self.assertEqual(sorted(card), ["history-hide-coincident", "history-hide-lagging"])

    def test_two_charts_are_rendered_and_only_the_default_range_is_visible(self):
        html = self.render()
        panes = re.findall(r'<div class="history-pane"([^>]*)>', html)

        self.assertEqual(len(panes), 2)
        self.assertEqual([p for p in panes if "hidden" not in p], [' data-range="10y"'])

    def test_every_curve_is_always_drawn_with_its_shift_whatever_is_shown(self):
        html = self.render(fit=LAG_FIT)

        self.assertEqual(html.count("history-line-lagging\" d"), 2)
        self.assertEqual(html.count("history-line-coincident\" d"), 2)
        self.assertIn("Lagging: Weakening (7 mo earlier)", html)

    def test_the_data_table_lists_the_latest_24_months_newest_first(self):
        html = self.render()
        rows = re.findall(r"<tr><td>(\d{4}-\d{2})", html)

        self.assertEqual(len(rows), 24)
        self.assertEqual(rows, sorted(rows, reverse=True))
        self.assertEqual(rows[0], max(history()))

    def test_the_current_live_month_is_marked_in_progress(self):
        reads = history(live_from="2021-01")
        last = max(reads)
        html = self.render(reads, today=date(int(last[:4]), int(last[5:]), 10))

        self.assertIn(f"{last} (in progress)", html)
        self.assertEqual(html.count("(in progress)"), 1)

    def test_missing_recession_flags_draw_no_shading_or_legend_entry(self):
        html = self.render(recessions={})

        self.assertNotIn("history-band", html)
        self.assertNotIn("Recession (NBER)", html)

    def test_recession_months_are_shaded_and_named_in_the_legend(self):
        html = self.render(recessions={"2008-01": 1, "2008-02": 1, "2008-03": 1})

        self.assertIn("Recession (NBER): 2008-01 to 2008-03", html)
        self.assertIn("Recession (NBER)</li>", html)

    def test_an_applied_shift_moves_only_that_line_and_says_so(self):
        plain = self.render(fit=NO_FIT)
        moved = self.render(fit=LAG_FIT)

        self.assertEqual(path_of(plain, "leading"), path_of(moved, "leading"))
        self.assertNotEqual(path_of(plain, "lagging"), path_of(moved, "lagging"))
        self.assertIn("Lagging: Weakening (7 mo earlier)", moved)
        self.assertNotIn("Lined up with recessions:", moved)  # the long explanation is not on the page
        self.assertNotIn("no reliable shift found", moved)

    def test_every_path_starts_with_a_move_under_a_negative_or_positive_shift(self):
        for shift in (-7, 0, 5):
            fit = {**NO_FIT, "lagging": {"shift": shift, "best": shift, "gain": 0.1, "halves": (shift, shift), "applied": shift != 0, "reason": ""}}
            html = self.render(fit=fit)
            for d in re.findall(r'class="history-line history-line-\w+" d="([^"]*)"', html):
                self.assertTrue(d.startswith("M"), (shift, d[:20]))

    def test_a_group_drawn_later_still_starts_at_the_left_edge(self):
        fit = {**NO_FIT, "lagging": {"shift": 5, "best": 5, "gain": 0.1, "halves": (5, 5), "applied": True, "reason": ""}}
        first_x = float(re.search(r'history-line-lagging" d="M([\d.]+),', self.render(fit=fit)).group(1))

        self.assertEqual(first_x, float(reads_chart.LEFT))

    def test_a_group_drawn_earlier_ends_before_the_right_edge(self):
        html = self.render(fit=LAG_FIT)
        right = float(reads_chart.WIDTH - reads_chart.RIGHT)
        last_x = float(re.findall(r"[ML]([\d.]+),", path_of(html, "lagging"))[-1])

        self.assertLess(last_x, right - 1)

    def test_the_note_names_the_first_live_month_and_the_replay(self):
        html = self.render(history(live_from="2021-01"))

        self.assertIn("Months before 2021-01 were replayed", html)

    def test_with_no_replay_it_says_earlier_months_are_not_loaded(self):
        reads = {m: entry(source="live") for m in months(2026, 6)}

        self.assertIn("Earlier months have not been loaded yet", self.render(reads))

    def test_nothing_saved_says_so(self):
        self.assertIn("No reads have been saved yet", self.render(reads={}))

    def test_a_group_with_no_score_is_left_off_the_chart(self):
        reads = history()
        for e in reads.values():
            e["groups"]["leading"]["score"] = None

        html = self.render(reads)

        self.assertNotIn("history-line-leading\" d", html.split("</svg>")[0])

    def test_the_other_states_are_plain_cards(self):
        self.assertIn("Loading history", reads_chart.render_loading())
        self.assertIn("History is unavailable right now.", reads_chart.render_unavailable())
        self.assertNotIn("<svg", reads_chart.render_unavailable())

    def test_the_zones_thresholds_and_floor_are_drawn_and_named(self):
        svg = self.render().split("</svg>")[0]

        self.assertEqual(svg.count("history-threshold"), 2)
        self.assertEqual(svg.count("history-floor"), 1)
        for word in ("Improving", "Mixed", "Weakening"):
            self.assertIn(f">{word}</text>", svg)
        self.assertNotIn("The faint lines", self.render())

    def test_the_threshold_is_the_one_the_reads_use(self):
        sys.path.insert(0, os.path.join(_SRC, "digest"))
        sys.path.insert(0, os.path.join(_SRC, "fred"))
        import market_read
        self.assertEqual(reads_chart.THRESHOLD, market_read.READ_THRESHOLD)

    def test_a_score_past_the_threshold_that_still_reads_mixed_is_labelled_held_with_the_reason_on_hover(self):
        reads = {m: entry(lead=0.33, reads=("mixed", "mixed", "weakening")) for m in months(2005, 200)}
        svg = self.render(reads).split("</svg>")[0]

        self.assertIn("Leading: Mixed (held)", svg)
        self.assertIn("<title>The score (+0.33) is past +0.25, but the read a month earlier did not agree, so the group stays Mixed.</title>", svg)
        self.assertNotIn("Coincident: Mixed (held)", svg)  # a score of 0.0 is just Mixed

    def test_a_negative_held_score_says_so_and_a_read_that_agrees_is_not_marked(self):
        held = {m: entry(lead=-0.5, reads=("mixed", "mixed", "weakening")) for m in months(2005, 200)}
        agreed = {m: entry(lead=0.5, reads=("improving", "mixed", "weakening")) for m in months(2005, 200)}

        self.assertIn("is past -0.25", self.render(held).split("</svg>")[0])
        self.assertNotIn("(held)", self.render(agreed).split("</svg>")[0])

    def test_the_plot_leaves_room_for_the_zone_names(self):
        self.assertGreaterEqual(reads_chart.LEFT, 90)

    def test_each_legend_entry_carries_the_class_the_hide_rule_uses(self):
        html = self.render()

        for group in reads_history.GROUPS:
            self.assertIn(f'<li class="history-legend-{group}">', html)

    def test_there_is_a_hint_for_the_case_where_every_group_is_hidden(self):
        self.assertRegex(self.render(), r'class="muted history-empty" role="status" hidden>Press a group above')

    def test_every_chart_has_a_title_and_description(self):
        html = self.render()

        self.assertEqual(html.count("<title id=\"hc-title-"), 2)
        self.assertEqual(html.count("<desc id=\"hc-desc-"), 2)


if __name__ == "__main__":
    unittest.main()

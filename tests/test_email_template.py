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
    os.path.dirname(__file__),
):
    sys.path.insert(0, _p)

from email_template import policy_line, render_html, render_subject, render_text
from readfixtures import NO_STANCE, RESTRICTIVE, read_view

TABLE = {
    "leading": [
        {
            "name": "Building Permits",
            "latest_value": 1433.0,
            "latest_date": "2026-07-01",
            "prior_value": 1374.0,
            "sparkline_cid": "spark-building_permits",
        }
    ],
    "coincident": [
        {
            "name": "Nonfarm Payrolls",
            "latest_value": 159075.0,
            "latest_date": "2026-08-01",
            "prior_value": 158913.0,
            "sparkline_cid": "spark-nonfarm_payrolls",
        }
    ],
    "lagging": [
        {
            "name": "CPI",
            "latest_value": 334.131,
            "latest_date": "2026-08-01",
            "prior_value": None,
            "sparkline_cid": "spark-cpi",
        }
    ],
}
COUNTDOWN = {
    "entries": [
        {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-11", "days_until": 0},
        {"key": "payrolls", "name": "Nonfarm Payrolls", "next_release_date": "2026-10-02", "days_until": 21},
    ],
    "soonest": {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-11", "days_until": 0},
}


class TestRenderSubject(unittest.TestCase):
    def test_names_all_updated_indicators(self):
        subject = render_subject(["CPI", "Unemployment Rate"])

        self.assertIn("2 update(s)", subject)
        self.assertIn("CPI", subject)
        self.assertIn("Unemployment Rate", subject)


class TestRenderText(unittest.TestCase):
    def test_includes_ai_section_and_disclaimer_when_present(self):
        ai_result = read_view("Modest changes.", leading="mixed", coincident="improving", lagging="weakening",
                              relationship="The outlook is weaker than the present: an early warning.")

        text = render_text(TABLE, COUNTDOWN, ai_result)

        self.assertIn("Modest changes.", text)
        self.assertIn("Leading (Outlook: where the economy is heading): Mixed, 3 of 3 indicators scored", text)
        self.assertIn("Coincident (Now: how the economy is doing today): Improving, 2 of 2 indicators scored", text)
        self.assertIn("Lagging (Confirmation: the economy 6 to 12 months ago): Weakening, 3 of 3 indicators scored", text)
        self.assertIn("The outlook is weaker than the present: an early warning.", text)
        self.assertNotIn("Overall", text)
        self.assertIn("not personalized financial advice", text)

    def test_omits_ai_section_when_none(self):
        text = render_text(TABLE, COUNTDOWN, None)

        self.assertNotIn("indicators scored", text)
        self.assertNotIn("not personalized financial advice", text)

    def test_includes_all_categories_and_countdown(self):
        text = render_text(TABLE, COUNTDOWN, None)

        self.assertIn("Building Permits", text)
        self.assertIn("Nonfarm Payrolls", text)
        self.assertIn("CPI", text)
        self.assertIn("Next up: CPI", text)

    def test_no_countdown_section_when_no_entries(self):
        empty_countdown = {"entries": [], "soonest": None}

        text = render_text(TABLE, empty_countdown, None)

        self.assertNotIn("Next releases", text)


class TestRenderHtml(unittest.TestCase):
    def test_embeds_sparkline_images_by_cid(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertIn('src="cid:spark-cpi"', html)
        self.assertIn('src="cid:spark-nonfarm_payrolls"', html)
        self.assertIn('src="cid:spark-building_permits"', html)

    def test_missing_sparkline_cid_falls_back_gracefully(self):
        table_without_cid = {
            "leading": [],
            "coincident": [],
            "lagging": [
                {"name": "CPI", "latest_value": 334.131, "latest_date": "2026-08-01", "prior_value": None}
            ],
        }

        html = render_html(table_without_cid, {"entries": [], "soonest": None}, None)

        self.assertNotIn("cid:None", html)

    def test_is_well_formed_html_document(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertTrue(html.lower().startswith("<!doctype html>"))
        self.assertIn("</html>", html.lower())

    def test_escapes_indicator_names_and_ai_summary(self):
        malicious_table = {
            "leading": [
                {
                    "name": "<script>alert(1)</script>",
                    "latest_value": 1.0,
                    "latest_date": "2026-08-01",
                    "prior_value": None,
                }
            ],
            "coincident": [],
            "lagging": [],
        }
        ai_result = read_view("<b>injected</b>", leading="mixed", relationship="<i>x</i>")

        html = render_html(malicious_table, {"entries": [], "soonest": None}, ai_result)

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>injected</b>", html)

    def test_directional_read_colors_are_distinct(self):
        improving_html = render_html(TABLE, COUNTDOWN, read_view("x", leading="improving"))
        weakening_html = render_html(TABLE, COUNTDOWN, read_view("x", leading="weakening"))

        self.assertIn("Improving", improving_html)
        self.assertIn("Weakening", weakening_html)
        self.assertNotEqual(improving_html, weakening_html)

    def test_each_group_has_its_own_tile_with_its_time_frame_and_count(self):
        html = render_html(TABLE, COUNTDOWN, read_view("x", leading="improving", coincident="mixed", lagging="weakening"))

        for frame in ("Outlook: where the economy is heading", "Now: how the economy is doing today",
                      "Confirmation: the economy 6 to 12 months ago"):
            self.assertIn(frame, html)
        badges = re.findall(r">\s*(Improving|Mixed|Weakening)\s*</span>", html)
        self.assertEqual(sorted(badges), ["Improving", "Mixed", "Weakening"])
        self.assertIn("3 of 3 indicators scored", html)
        self.assertIn("2 of 2 indicators scored", html)
        self.assertNotIn("Overall", html)

    def test_each_group_label_in_the_table_explains_the_group(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertIn("so they confirm the past rather than predict", html)
        self.assertIn("typically 6 to 12 months later", html)

    def test_the_policy_stance_is_one_sentence_of_context_with_the_numbers(self):
        line = policy_line(RESTRICTIVE)

        self.assertIn("Policy stance: Restrictive.", line)
        self.assertIn("fed funds rate is 4.50% (as of 19 Oct 2026)", line)
        self.assertIn("recent inflation is 2.5% (CPI to Sep 2026, six-month annualized)", line)
        self.assertIn("real rate is 2.0%, 1.0 points above a neutral real rate of about 1.0%", line)
        self.assertIn("not how the economy is doing", line)

    def test_below_neutral_says_below_and_an_unavailable_stance_says_why(self):
        accommodative = {**RESTRICTIVE, "stance": "accommodative", "gap": -0.8, "real_rate": 0.2}

        self.assertIn("0.8 points below a neutral real rate", policy_line(accommodative))
        self.assertEqual(policy_line(NO_STANCE), "Policy stance: not available yet (no fed funds reading on file).")

    def test_a_near_zero_rate_says_why_it_is_accommodative(self):
        near_zero = {**RESTRICTIVE, "stance": "accommodative", "fed_funds": 0.1, "real_rate": 1.9, "gap": 0.9,
                     "reason": "the fed funds rate is near zero"}
        no_inflation = {**near_zero, "inflation": None, "cpi_date": None, "real_rate": None, "gap": None}

        self.assertIn("It reads Accommodative because the fed funds rate is near zero, whatever recent inflation was.", policy_line(near_zero))
        line = policy_line(no_inflation)
        self.assertIn("Policy stance: Accommodative. The fed funds rate is 0.10%", line)
        self.assertIn("because the fed funds rate is near zero", line)
        self.assertNotIn("real rate", line)

    def test_a_gap_that_rounds_to_zero_says_at_the_neutral_rate(self):
        at_neutral = {**RESTRICTIVE, "stance": "near neutral", "gap": 0.0, "real_rate": 1.0}

        self.assertIn("so the real rate is 1.0%, at a neutral real rate of about 1.0%", policy_line(at_neutral))

    def test_the_stance_is_in_the_html_and_the_text_but_not_in_a_group_tile(self):
        view = read_view("x", leading="improving", policy=RESTRICTIVE)

        self.assertIn("Policy stance: Restrictive.", render_html(TABLE, COUNTDOWN, view))
        self.assertIn("Policy stance: Restrictive.", render_text(TABLE, COUNTDOWN, view))
        self.assertEqual(render_html(TABLE, COUNTDOWN, view).count("Restrictive"), 1)

    def test_the_relationship_sentence_is_shown_and_escaped(self):
        html = render_html(TABLE, COUNTDOWN, read_view("x", relationship="Early <warning>"))

        self.assertIn("Early &lt;warning&gt;", html)

    def test_soonest_release_is_marked_next_up(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertIn("Next up", html)


if __name__ == "__main__":
    unittest.main()

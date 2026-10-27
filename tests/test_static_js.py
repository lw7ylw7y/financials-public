import glob
import os
import re
import shutil
import subprocess
import sys
import unittest
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, *(os.path.join(_SRC, d) for d in ("fred", "storage", "digest", "mailer", "screener", "web"))):
    sys.path.insert(0, _p)

import app as app_module
import page_template
import screener_page
import settings

JS_DIR = os.path.join(_SRC, "web", "static", "js")
JS_FILES = sorted(glob.glob(os.path.join(JS_DIR, "*.js")))


class TestPageScriptFiles(unittest.TestCase):
    def test_the_page_scripts_exist(self):
        self.assertEqual([os.path.basename(p) for p in JS_FILES],
                         ["digest.js", "screener.js", "screener_filters.js", "tickers.js"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_every_script_is_valid_javascript(self):
        for path in JS_FILES:
            with self.subTest(script=os.path.basename(path)):
                result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_script_still_carries_python_string_escaping(self):
        for path in JS_FILES:
            with open(path) as f, self.subTest(script=os.path.basename(path)):
                self.assertNotIn("{{", f.read())

    def test_every_script_a_page_references_is_served_with_a_version_and_a_javascript_type(self):
        client = app_module.app.test_client()
        cards = {"stocks": []}
        pages = [
            page_template.render_ticker_dashboard_page(cards, {"headlines": [], "pending": False}),
            page_template.render_indicator_digest_page(
                {"table": {"leading": [], "coincident": [], "lagging": []}, "countdown": {"entries": [], "soonest": None},
                 "ai_result": None}),
            screener_page.render_screener_page({"state": {"x": 1}, "last_run": None, "run_is_stale": False,
                                                "rows": {"new": [], "shortlisted": [], "dismissed": []}, "data_check": [],
                                                "hidden": 0, "improved": 0, "passing": 0, "due": {"new": 0, "shortlisted": 0, "dismissed": 0},
                                                "dates_known": True, "watchlist_known": True, "form": settings.default_form()}),
        ]
        referenced = set()
        for html, expected in zip(pages, (["tickers.js"], ["digest.js"], ["screener.js", "screener_filters.js"])):
            self.assertNotIn("<script>", html)
            found = re.findall(r'src="(/static/js/([a-z_]+\.js)\?v=\d+)"', html)
            self.assertEqual([name for _, name in found], expected)
            referenced.update(url for url, _ in found)
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
            for url in sorted(referenced):
                with self.subTest(url=url):
                    with client.get(url) as response:
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("javascript", response.content_type)
                        self.assertGreater(len(response.data), 0)

    def test_the_static_url_version_is_the_files_modification_time_and_degrades_without_it(self):
        self.assertRegex(page_template.static_url("dashboard.css"), r"^/static/dashboard\.css\?v=\d+$")
        self.assertEqual(page_template.static_url("nope.css"), "/static/nope.css")

    def test_the_sort_arrows_follow_both_the_class_and_aria_sort(self):
        css = open(os.path.join(_SRC, "web", "static", "dashboard.css")).read()

        for state, arrow in (("ascending", "25B2"), ("descending", "25BC")):
            self.assertRegex(css, rf'th\.sortable\[aria-sort="{state}"\]::after \{{ content: "\\{arrow}"')

    def test_a_greyed_row_never_puts_a_filter_on_a_cell_that_holds_a_fixed_tip(self):
        css = open(os.path.join(_SRC, "web", "static", "dashboard.css")).read()
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        for selector, body in rules:
            if "filter" not in body:
                continue
            for part in (p.strip() for p in selector.split(",")):
                if "data-full-position" in part or "data-promoted" in part:
                    self.assertFalse(part.endswith("td:not(.full-cell)") or part.endswith("td:not(.actions-cell)"), part)
        self.assertRegex(css, r"> :not\(\.verdict-wrap\)")
        # Any filter or transform whose selector reaches a greyed row must end on the contents
        # (a pill, the Saved flag, or a child other than the tip wrapper), never on the row or a cell.
        for selector, body in rules:
            if "filter" not in body and "transform" not in body:
                continue
            for part in (p.strip() for p in selector.split(",")):
                if "data-full-position" in part or "data-promoted" in part:
                    self.assertTrue(part.endswith((".verdict-pill", ".stale-flag", "> :not(.verdict-wrap)")), part)


if __name__ == "__main__":
    unittest.main()

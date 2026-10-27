import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, *(os.path.join(_SRC, d) for d in ("fred", "storage", "digest", "mailer", "screener", "web")), os.path.dirname(__file__)):
    sys.path.insert(0, _p)

import page_template
import screener_page
import test_page_template as tp
from readfixtures import read_view
import test_screener_page as ts

HANDLERS = os.path.join(os.path.dirname(__file__), "js", "handlers.js")
JS_DIR = os.path.join(_SRC, "web", "static", "js")


def _jsdom_available() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('jsdom')"], capture_output=True).returncode == 0


def _inline_scripts(html: str) -> str:
    def inline(match):
        with open(os.path.join(JS_DIR, match.group(1))) as f:
            return "<script>" + f.read() + "</script>"
    return re.sub(r'<script src="/static/js/([a-z_]+\.js)\?v=\d+"></script>', inline, html)


@unittest.skipUnless(_jsdom_available(), "needs node and jsdom (npm install jsdom; set NODE_PATH to its node_modules)")
class TestPageScriptBehaviour(unittest.TestCase):
    """Runs the real page scripts against the real rendered pages in jsdom, a DOM emulator with
    no layout engine: click behaviour, rollbacks and focus, not how anything looks."""

    def test_promote_full_position_invested_info_popups_and_sorting_behave(self):
        statuses = {s: {"status": "shortlisted", "at": ts.RECENT} for s in ("AAA", "BBB", "CCC")}
        view = ts.view_for({"AAA": ts.record(), "BBB": ts.record(roi=20.0), "CCC": ts.record(roi=30.0)},
                           statuses=statuses, watchlist=frozenset({"CCC"}))
        tickers_page = page_template.render_ticker_dashboard_page(
            {"stocks": [tp.make_card(), tp.make_card(symbol="VGIT")]}, tp.NO_NEWS, None, frozenset({"VGIT"}))
        invested_page = page_template.render_ticker_dashboard_page(
            {"individual": [tp.make_card(symbol="AAPL", group="individual")]}, tp.NO_NEWS, None, frozenset(), True, {"AAPL": 100.0})
        digest_page = page_template.render_indicator_digest_page({
            "table": {"leading": tp.TABLE["coincident"], "coincident": tp.TABLE["coincident"], "lagging": tp.TABLE["coincident"]},
            "countdown": tp.COUNTDOWN, "ai_result": read_view("s", leading="improving", coincident="mixed", lagging="weakening")})
        import reads_chart
        import reads_history
        from test_reads_chart import LAG_FIT, history
        card = reads_chart.render_reads_history(history(), {"2008-01": 1}, LAG_FIT)
        self.assertIn("Lagging: Weakening (7 mo earlier)", card)
        many = ts.view_for({f"S{i:02d}": ts.record(roi=10.0 + i) for i in range(26)})
        score_statuses = {s: {"status": "shortlisted", "at": ts.RECENT} for s in ("AAA", "BBB", "CCC", "DDD", "BIG")}
        scores = ts.view_for({"AAA": ts.record(roi=9.0), "BBB": ts.record(roi=10.0), "CCC": ts.record(roi=100.0), "DDD": ts.record(roi=55.0),
                              "BIG": ts.record(market_cap=90000.0)}, statuses=score_statuses)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "history_card.html"), "w") as f:
                f.write(card)
            for name, html in (("many.html", screener_page.render_screener_page(many, "new")),
                               ("scores.html", screener_page.render_screener_page(scores, "shortlisted"))):
                with open(os.path.join(tmp, name), "w") as f:
                    f.write(_inline_scripts(html))
            for name, html in (("digest.html", digest_page), ("shortlist.html", screener_page.render_screener_page(view, "shortlisted")),
                               ("tickers.html", tickers_page), ("invested.html", invested_page)):
                with open(os.path.join(tmp, name), "w") as f:
                    f.write(_inline_scripts(html))
            result = subprocess.run(["node", HANDLERS, tmp], capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()

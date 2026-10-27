"""The computed read in the digest: what the AI may and may not change,
and what the page and email show when it is unavailable."""

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in ("", "fred", "storage", "digest", "mailer", "web"):
    sys.path.insert(0, os.path.join(_SRC, _p))
sys.path.insert(0, os.path.dirname(__file__))

from build_digest_content import (
    build_digest_content,
    build_indicators_context,
    build_read_view,
    stale_indicator_keys,
)
from email_template import render_html, render_text
from interpret import InterpretationError, build_user_prompt
from market_read import compute_market_read
from readfixtures import NO_STANCE
from page_template import render_check_response
from post_release import _digest_fingerprint, maybe_send_digest_email

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
START = date(2026, 1, 1)


def history(values):
    return [
        {
            "date": (START + timedelta(days=30 * i)).isoformat(),
            "value": v,
            "fetched_at": "2026-09-01T00:00:00+00:00",
        }
        for i, v in enumerate(values)
    ]


def indicator(name, category, values):
    return {"name": name, "category": category, "history": history(values)}


def make_state(direction="good", last_ai_response=None):
    up = [1.0 + 0.1 * i for i in range(12)]
    down = list(reversed(up))
    good, bad = (up, down) if direction == "good" else (down, up)
    state = {
        "indicators": {
            "building_permits": indicator("Building Permits", "leading", good),
            "initial_jobless_claims": indicator("Jobless Claims", "leading", bad),
            "yield_curve_spread": indicator("Spread", "leading", good),
            "unemployment_rate": indicator("Unemployment", "coincident", bad),
            "nonfarm_payrolls": indicator(
                "Payrolls", "coincident", [100000 * (1.002 if direction == "good" else 1.0) ** i for i in range(12)]
            ),
        }
    }
    # "bad": claims and unemployment rising, permits and spread falling.
    if direction == "good":
        state["indicators"]["initial_jobless_claims"]["history"] = history(down)
        state["indicators"]["unemployment_rate"]["history"] = history(down)
    else:
        state["indicators"]["initial_jobless_claims"]["history"] = history(up)
        state["indicators"]["unemployment_rate"]["history"] = history(up)
    if last_ai_response is not None:
        state["last_ai_response"] = last_ai_response
    return state


def reads(leading, coincident=None, lagging=None):
    return {"leading": leading, "coincident": coincident, "lagging": lagging}


def ai_that_says(read):
    """An AI that tries to push its own `directional_read`; only the summary is used."""
    def fn(indicators_context, updated_keys):
        return {"summary": "Explained.", "directional_read": read}

    return fn


def failing_ai(indicators_context, updated_keys):
    raise InterpretationError("every model failed")


class TestComputedReadIsAuthoritative(unittest.TestCase):
    def test_the_ai_cannot_override_the_computed_read(self):
        state = make_state("good")
        content = build_digest_content(state, ["cpi"], interpret_fn=ai_that_says("weakening"), now=NOW)

        self.assertEqual(content["market_read"]["groups"]["leading"]["read"], "improving")
        self.assertEqual(content["ai_result"]["computed_reads"], reads("improving", "improving"))
        self.assertEqual(state["last_ai_response"]["computed_reads"], reads("improving", "improving"))
        self.assertNotIn("directional_read", state["last_ai_response"])
        self.assertNotIn("directional_read", content["ai_result"])

    def test_every_model_failing_still_gives_the_computed_read(self):
        state = make_state("bad")
        content = build_digest_content(state, ["cpi"], interpret_fn=failing_ai, now=NOW)

        self.assertIsNone(content["ai_result"])
        self.assertEqual(content["read_view"]["groups"]["leading"]["read"], "weakening")
        self.assertIsNone(content["read_view"]["summary"])

    def test_stored_explanation_is_shown_while_it_matches_the_read(self):
        take = {"summary": "Old but still true.", "computed_reads": reads("improving", "improving")}
        view = build_read_view(compute_market_read(build_indicators_context(make_state("good"))), take)
        self.assertEqual(view["summary"], "Old but still true.")

    def test_stored_explanation_is_dropped_when_the_read_changed(self):
        take = {"summary": "Was improving.", "computed_reads": reads("improving")}
        state = make_state("bad", last_ai_response=take)
        content = build_digest_content(state, [], interpret_fn=failing_ai, now=NOW)

        self.assertEqual(content["read_view"]["groups"]["leading"]["read"], "weakening")
        self.assertIsNone(content["read_view"]["summary"])

    def test_take_for_a_different_read_is_stale_for_every_indicator(self):
        take = {
            "summary": "Was improving.",
            "computed_reads": reads("improving"),
            "as_of": {k: v["history"][-1]["date"] for k, v in make_state("bad")["indicators"].items()},
        }
        state = make_state("bad", last_ai_response=take)
        self.assertEqual(set(stale_indicator_keys(state)), set(state["indicators"]))

    def test_take_for_the_current_read_is_not_stale(self):
        state = make_state("good")
        build_digest_content(state, ["cpi"], interpret_fn=ai_that_says("improving"), now=NOW)
        self.assertEqual(stale_indicator_keys(state), [])


class TestPrompt(unittest.TestCase):
    def test_prompt_carries_the_policy_stance_as_context_only_when_it_can_be_judged(self):
        state = make_state("good")
        state["indicators"]["fed_funds_rate"] = indicator("Fed Funds Rate", "lagging", [4.0] * 12)
        state["indicators"]["cpi"] = indicator("CPI", "lagging", [100 * 1.002 ** i for i in range(12)])
        with_stance = build_user_prompt(build_indicators_context(state), [])
        without = build_user_prompt(build_indicators_context(make_state("good")), [])

        self.assertIn("Policy stance (context about what the Fed is doing, not one of the three reads", with_stance)
        self.assertIn("fed funds 4.0%", with_stance)
        self.assertNotIn("Policy stance", without)

    def test_the_prompt_explains_a_near_zero_rate_stance_without_an_inflation_figure(self):
        from market_read import ZERO_RATE_REASON
        state = make_state("good")
        state["indicators"]["fed_funds_rate"] = indicator("Fed Funds Rate", "lagging", [0.1] * 12)

        prompt = build_user_prompt(build_indicators_context(state), [])

        self.assertIn("accommodative (the fed funds rate is near zero, so it is accommodative whatever recent inflation was)", prompt)
        self.assertNotIn("None%", prompt)

    def test_prompt_carries_the_computed_reads_of_each_group_and_statistics(self):
        context = build_indicators_context(make_state("bad"))
        prompt = build_user_prompt(context, [])
        self.assertIn("Computed read, leading (an outlook: usually turns months before the economy does): weakening", prompt)
        self.assertIn("Computed read, coincident (how the economy is doing now): weakening", prompt)
        self.assertIn("Computed read, lagging (confirms the past: reflects the economy 6 to 12 months ago): none yet", prompt)
        self.assertNotIn("overall read: ", prompt)
        self.assertIn("Computed: unfavorable", prompt)
        self.assertIn("percentile in 12 months=", prompt)


def short_state(last_ai_response=None):
    """One indicator with a single reading: too little history for a read."""
    state = {
        "indicators": {
            "cpi": {"name": "CPI", "category": "lagging", "history": history([334.131])}
        }
    }
    if last_ai_response is not None:
        state["last_ai_response"] = last_ai_response
    return state


class TestRevisionRetriesTheTake(unittest.TestCase):
    def state_with_take(self):
        state = make_state("good")
        build_digest_content(state, [], interpret_fn=ai_that_says("improving"), now=NOW)
        return state

    def test_a_revision_that_flips_the_read_makes_the_take_stale(self):
        state = self.state_with_take()
        self.assertEqual(stale_indicator_keys(state), [])
        # Revise the stored readings so every indicator now points the other way.
        flipped = make_state("bad")
        state["indicators"] = flipped["indicators"]
        self.assertEqual(set(stale_indicator_keys(state)), set(state["indicators"]))

    def test_the_retry_after_a_failed_attempt_waits_out_the_cooldown(self):
        from build_digest_content import AI_RETRY_COOLDOWN, ai_retry_keys

        state = self.state_with_take()
        state["indicators"] = make_state("bad")["indicators"]

        self.assertTrue(ai_retry_keys(state, NOW))
        build_digest_content(state, ai_retry_keys(state, NOW), interpret_fn=failing_ai, now=NOW)
        self.assertEqual(ai_retry_keys(state, NOW + timedelta(minutes=5)), [])
        self.assertTrue(ai_retry_keys(state, NOW + AI_RETRY_COOLDOWN + timedelta(seconds=1)))

    def test_revised_since_only_counts_revisions_after_the_last_send(self):
        from post_release import indicators_revised_since

        state = make_state("good")
        state["indicators"]["building_permits"]["history"][-1]["revised_at"] = "2026-09-10T00:00:00+00:00"
        self.assertEqual(indicators_revised_since(state, "2026-09-01T00:00:00+00:00"), ["building_permits"])
        self.assertEqual(indicators_revised_since(state, "2026-09-11T00:00:00+00:00"), [])
        self.assertEqual(indicators_revised_since(state, None), [])

    def test_a_revised_value_is_named_in_the_email_subject(self):
        from post_release import build_digest_email

        state = make_state("good")
        state["indicators"]["building_permits"]["history"][-1]["revised_at"] = "2026-09-10T00:00:00+00:00"
        email = build_digest_email(
            state, build_indicators_context(state), [], None, revised_keys=["building_permits"]
        )
        self.assertIn("Building Permits (revised)", email["subject"])


class TestNoReadYet(unittest.TestCase):
    def test_a_view_exists_with_no_read_and_no_explanation(self):
        state = short_state()
        view = build_read_view(compute_market_read(build_indicators_context(state)), None)
        self.assertEqual(
            view,
            {"groups": {"leading": {"read": None, "score": None, "scored": 0, "total": 0},
                        "coincident": {"read": None, "score": None, "scored": 0, "total": 0},
                        "lagging": {"read": None, "score": None, "scored": 0, "total": 1}},
             "relationship": None, "policy": NO_STANCE, "summary": None},
        )

    def test_page_and_email_say_there_is_no_read_yet(self):
        view = build_read_view(compute_market_read(build_indicators_context(short_state())), None)
        table = {"leading": [], "coincident": [], "lagging": []}
        countdown = {"entries": [], "soonest": None}
        html = render_check_response({"table": {}, "countdown": countdown, "read_view": view})["ai_html"]
        self.assertEqual(html.count("No read yet"), 3)
        self.assertIn("Not enough history", html)
        self.assertEqual(render_html(table, countdown, view).count("No read yet"), 3)
        self.assertIn("Lagging (Confirmation: the economy 6 to 12 months ago): No read yet, 0 of 1 indicators scored",
                      render_text(table, countdown, view))

    def test_a_take_with_no_computed_read_key_is_stale_and_not_shown(self):
        legacy = {
            "summary": "Written by the model alone.",
            "computed_read": "improving",
            "as_of": {"cpi": "2026-01-01"},
        }
        state = short_state(legacy)
        self.assertEqual(stale_indicator_keys(state), ["cpi"])
        view = build_read_view(compute_market_read(build_indicators_context(state)), legacy)
        self.assertIsNone(view["summary"])

    def test_prompt_tells_the_model_not_to_offer_a_read(self):
        prompt = build_user_prompt(build_indicators_context(short_state()), [])
        self.assertIn("Computed read, lagging (confirms the past: reflects the economy 6 to 12 months ago): none yet", prompt)
        self.assertIn("Do not offer a read of your own for this group", prompt)
        self.assertNotIn("None", prompt)


class TestSurfaces(unittest.TestCase):
    def view(self, summary):
        weakening = {"read": "weakening", "score": -1.0, "scored": 3, "total": 3}
        silent = {"read": None, "score": None, "scored": 1, "total": 2}
        return {"groups": {"leading": weakening, "coincident": silent, "lagging": silent},
                "relationship": None, "policy": NO_STANCE, "summary": summary}

    def test_email_without_commentary_shows_the_computed_read(self):
        view = self.view(None)
        table = {"leading": [], "coincident": [], "lagging": []}
        countdown = {"entries": [], "soonest": None}
        text = render_text(table, countdown, view)
        html = render_html(table, countdown, view)

        for body in (text, html):
            self.assertIn("AI commentary is unavailable", body)
        self.assertIn("Leading (Outlook: where the economy is heading): Weakening, 3 of 3 indicators scored", text)
        self.assertNotIn("Overall", text)
        self.assertIn("Weakening", html)

    def test_page_repaints_the_read_without_commentary(self):
        content = {"table": {}, "countdown": {"entries": [], "soonest": None}, "read_view": self.view(None)}
        html = render_check_response(content)["ai_html"]
        self.assertIn("Weakening", html)
        self.assertIn("AI commentary is unavailable", html)


class TestFingerprint(unittest.TestCase):
    def test_reworded_summary_does_not_change_it(self):
        a = make_state("good", {"summary": "One wording.", "computed_reads": reads("improving")})
        b = make_state("good", {"summary": "Another wording.", "computed_reads": reads("improving")})
        self.assertEqual(_digest_fingerprint(a), _digest_fingerprint(b))

    def test_changed_read_changes_it(self):
        self.assertNotEqual(_digest_fingerprint(make_state("good")), _digest_fingerprint(make_state("bad")))

    def test_email_sends_the_computed_read_with_no_ai_take_on_file(self):
        sent = {}

        def send(subject, body, html_body=None, images=None):
            sent["body"] = body

        result = maybe_send_digest_email(make_state("bad"), send_fn=send, now=NOW)
        self.assertEqual(result["status"], "sent_without_ai")
        self.assertIn("Leading (Outlook: where the economy is heading): Weakening", sent["body"])


if __name__ == "__main__":
    unittest.main()

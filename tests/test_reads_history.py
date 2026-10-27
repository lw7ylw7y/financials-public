import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "storage"), os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import reads_history
from kv_store import KvStoreError

NOW = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
GROUPS = {g: {"read": "mixed", "score": 0.0, "scored": 3, "total": 3} for g in reads_history.GROUPS}


def month_name(i):
    return f"{1990 + i // 12}-{i % 12 + 1:02d}"


def synthetic(months, shifts, recession_blocks):
    """Reads whose weakness follows the recession flag `shifts[group]` months later (a negative shift
    in fit terms), plus the flags. Scores are -1 inside a (shifted) block and 0 elsewhere."""
    recessions = {month_name(i): 0 for i in range(months)}
    for start, length in recession_blocks:
        for i in range(start, start + length):
            recessions[month_name(i)] = 1
    reads = {}
    for i in range(months):
        groups = {}
        for g in reads_history.GROUPS:
            src = i - shifts[g]
            weak = 0 <= src < months and recessions[month_name(src)] == 1
            noise = ((i * 37 + len(g)) % 7 - 3) / 40
            groups[g] = {"read": "weakening" if weak else "mixed", "score": (-1.0 if weak else 0.0) + noise, "scored": 3, "total": 3}
        reads[month_name(i)] = {"groups": groups, "stance": None, "source": "replay", "saved_at": NOW.isoformat()}
    return reads, recessions


BLOCKS = [(30, 10), (90, 8), (150, 12), (230, 9), (290, 11), (350, 8)]


class TestSaveMonth(unittest.TestCase):
    def test_a_month_is_one_atomic_field_write_of_the_stored_shape(self):
        with mock.patch("reads_history.hset_json") as hset:
            reads_history.save_month("2026-10", reads_history.make_entry(GROUPS, "near neutral", "live", NOW))

        key, field, value = hset.call_args.args
        self.assertEqual((key, field), ("indicator_reads", "2026-10"))
        self.assertEqual(value["source"], "live")
        self.assertEqual(value["stance"], "near neutral")
        self.assertEqual(set(value["groups"]), {"leading", "coincident", "lagging"})
        self.assertEqual(set(value["groups"]["leading"]), {"read", "score", "scored", "total"})

    def test_a_later_run_writes_the_same_field_and_a_later_month_a_different_one(self):
        with mock.patch("reads_history.hset_json") as hset:
            reads_history.save_month("2026-10", reads_history.make_entry(GROUPS, None, "live", NOW))
            reads_history.save_month("2026-10", reads_history.make_entry(GROUPS, None, "live", NOW))
            reads_history.save_month("2026-11", reads_history.make_entry(GROUPS, None, "live", NOW))

        self.assertEqual([c.args[1] for c in hset.call_args_list], ["2026-10", "2026-10", "2026-11"])

    def test_month_of_is_the_year_and_month(self):
        self.assertEqual(reads_history.month_of(NOW), "2026-10")

    def test_a_redis_failure_is_raised_for_the_caller_to_decide(self):
        with mock.patch("reads_history.hset_json", side_effect=KvStoreError("down")):
            with self.assertRaises(KvStoreError):
                reads_history.save_month("2026-10", {})


class TestSaveMissing(unittest.TestCase):
    def test_only_months_not_already_stored_are_written(self):
        entries = {f"2000-{m:02d}": {"n": m} for m in range(1, 7)}
        with mock.patch("reads_history.hset_many_json") as many:
            written = reads_history.save_missing(entries, {"2000-02", "2000-05"})

        self.assertEqual(written, 4)
        self.assertEqual(sorted(many.call_args.args[1]), ["2000-01", "2000-03", "2000-04", "2000-06"])

    def test_nothing_missing_writes_nothing(self):
        with mock.patch("reads_history.hset_many_json") as many:
            self.assertEqual(reads_history.save_missing({"2000-01": {}}, {"2000-01"}), 0)

        many.assert_not_called()

    def test_a_long_history_is_written_in_chunks(self):
        entries = {month_name(i): {} for i in range(450)}
        with mock.patch("reads_history.hset_many_json") as many:
            reads_history.save_missing(entries, set())

        self.assertEqual([len(c.args[1]) for c in many.call_args_list], [200, 200, 50])

    def test_recession_flags_are_one_multi_field_write(self):
        with mock.patch("reads_history.hset_many_json") as many:
            reads_history.save_recessions({"2020-03": 1, "2020-04": 1.0})
            reads_history.save_recessions({})

        self.assertEqual(many.call_count, 1)
        self.assertEqual(many.call_args.args, ("nber_recessions", {"2020-03": 1, "2020-04": 1}))


class TestFit(unittest.TestCase):
    def test_a_clear_lag_is_found_and_applied(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 7}, BLOCKS)

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertTrue(fit["lagging"]["applied"])
        self.assertEqual(fit["lagging"]["shift"], -7)
        self.assertGreaterEqual(fit["lagging"]["gain"], reads_history.MIN_GAIN)
        self.assertEqual(fit["lagging"]["halves"], (-7, -7))

    def test_a_group_already_in_step_gets_no_shift(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 7}, BLOCKS)

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertFalse(fit["coincident"]["applied"])
        self.assertEqual(fit["coincident"]["shift"], 0)
        self.assertIn("only", fit["coincident"]["reason"])

    def test_a_flat_correlation_gets_no_shift(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 0}, BLOCKS)
        for i, month in enumerate(sorted(reads)):
            for g in reads[month]["groups"].values():
                g["score"] = ((i * 13) % 11) / 10  # no relation to the recessions

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertFalse(any(f["applied"] for f in fit.values()))

    def test_halves_that_disagree_get_no_shift(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 0}, BLOCKS)
        cut = sorted(reads).index(reads_history.SPLIT_MONTH) if reads_history.SPLIT_MONTH in reads else 132
        # the first half's lagging weakness trails by 3 months, the second half's by 12
        recs = sorted(reads)
        for i, m in enumerate(recs):
            shift = 3 if i < cut else 12
            src = i - shift
            weak = 0 <= src < len(recs) and recessions[recs[src]] == 1
            reads[m]["groups"]["lagging"]["score"] = -1.0 if weak else 0.0

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertFalse(fit["lagging"]["applied"])
        self.assertIn("disagree", fit["lagging"]["reason"])

    def test_a_short_history_gets_no_shift_for_every_group(self):
        reads, recessions = synthetic(60, {"leading": 0, "coincident": 0, "lagging": 5}, [(10, 6)])

        fit = reads_history.fit_alignment(reads, recessions)

        for group in reads_history.GROUPS:
            self.assertFalse(fit[group]["applied"])
            self.assertIn("years of history", fit[group]["reason"])

    def test_months_without_a_score_are_skipped_not_counted_as_zero(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 7}, BLOCKS)
        for m in sorted(reads)[:40]:
            reads[m]["groups"]["lagging"]["score"] = None

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertEqual(fit["lagging"]["shift"], -7)

    def test_a_gain_exactly_at_the_threshold_is_enough(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 7}, BLOCKS)
        gain = reads_history.fit_alignment(reads, recessions)["coincident"]["gain"]

        with mock.patch.object(reads_history, "MIN_GAIN", gain):
            fit = reads_history.fit_alignment(reads, recessions)

        self.assertTrue(fit["coincident"]["applied"])
        self.assertEqual(fit["coincident"]["gain"], gain)

    def test_holes_in_the_history_do_not_move_later_months(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 7}, BLOCKS)
        for m in sorted(reads)[100:106]:
            del reads[m]
        for m in sorted(recessions)[200:204]:
            del recessions[m]

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertEqual(fit["lagging"]["shift"], -7)

    def test_a_group_with_no_scores_at_all_reports_it(self):
        reads, recessions = synthetic(400, {"leading": 0, "coincident": 0, "lagging": 0}, BLOCKS)
        for entry in reads.values():
            entry["groups"]["leading"]["score"] = None

        fit = reads_history.fit_alignment(reads, recessions)

        self.assertFalse(fit["leading"]["applied"])
        self.assertEqual(fit["leading"]["reason"], "no usable scores")


if __name__ == "__main__":
    unittest.main()

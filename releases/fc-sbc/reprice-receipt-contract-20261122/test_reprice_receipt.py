from copy import deepcopy
import unittest

from reprice_receipt import (
    LegacyProjection,
    WriteSummary,
    project_legacy_receipt,
    summarize_evidence,
)


class LegacyReceiptTests(unittest.TestCase):
    def test_conflict_neither_mutates_receipt_nor_proves_price_outcome(self):
        receipt = {"ok": True, "steps": [
            {"name": "⑦ 用采集的金币价", "ok": True},
            {"name": "⑧ 改价", "ok": False, "detail": "完成"},
        ]}
        original = deepcopy(receipt)
        self.assertEqual(
            project_legacy_receipt(receipt),
            LegacyProjection("conflict", True, False, write_state="unknown"),
        )
        self.assertEqual(receipt, original)

    def test_success_flag_and_legacy_counts_do_not_prove_write_or_noop(self):
        for changed in (0, 12):
            with self.subTest(changed=changed):
                self.assertEqual(
                    project_legacy_receipt({"ok": True, "steps": [
                        {"name": "⑧ 改价", "ok": True, "changed": changed, "total": 12},
                    ]}),
                    LegacyProjection("reported", True, True),
                )

    def test_failed_run_without_step_is_not_evidence_no_write_occurred(self):
        self.assertEqual(
            project_legacy_receipt({"ok": False, "steps": [{"name": "前序", "ok": False}]}),
            LegacyProjection("insufficient", False, None),
        )

    def test_does_not_match_similar_names_or_use_list_position(self):
        self.assertEqual(
            project_legacy_receipt({"ok": True, "steps": [{"name": "改价预览", "ok": True}] * 8}),
            LegacyProjection("insufficient", True, None),
        )

    def test_duplicate_or_malformed_steps_are_not_trusted(self):
        step = {"name": "⑧ 改价", "ok": True}
        for steps in ([step, step], [None, step], {"8": step}):
            with self.subTest(steps=steps):
                self.assertEqual(
                    project_legacy_receipt({"ok": True, "steps": steps}),
                    LegacyProjection("insufficient", True, None),
                )

    def test_non_boolean_flags_are_unavailable(self):
        self.assertEqual(
            project_legacy_receipt({"ok": 1, "steps": [{"name": "⑧ 改价", "ok": "false"}]}),
            LegacyProjection("insufficient", None, None),
        )

    def test_reported_failure_does_not_prove_rejection(self):
        self.assertEqual(
            project_legacy_receipt({"ok": False, "steps": [{"name": "⑧ 改价", "ok": False}]}),
            LegacyProjection("reported", False, False),
        )


class EvidenceTests(unittest.TestCase):
    def test_verified_noop_and_empty_frozen_plan(self):
        self.assertEqual(summarize_evidence([], []), WriteSummary("no_op", 0, 0, 0, 0, 0, 0))
        self.assertEqual(
            summarize_evidence(["A"], [("A", "unchanged")]),
            WriteSummary("no_op", 1, 0, 1, 0, 0, 0),
        )

    def test_confirmed_changes_and_noops(self):
        self.assertEqual(
            summarize_evidence(["A", "B"], [("A", "changed"), ("B", "unchanged")]),
            WriteSummary("confirmed", 2, 1, 1, 0, 0, 0),
        )

    def test_partial_preserves_rejections_unknown_and_unattempted(self):
        self.assertEqual(
            summarize_evidence(
                ["A", "B", "C", "D", "E", "F"],
                [("A", "changed"), ("B", "rejected"), ("C", "not_attempted"),
                 ("D", "unknown"), ("E", "unchanged")],
            ),
            WriteSummary("partial", 6, 1, 1, 1, 1, 2),
        )

    def test_unknown_is_not_failed_or_noop(self):
        self.assertEqual(
            summarize_evidence(["A", "B"], [("B", "rejected")]),
            WriteSummary("unknown", 2, 0, 0, 1, 0, 1),
        )

    def test_rejected_and_not_attempted_are_distinct(self):
        self.assertEqual(summarize_evidence(["A"], [("A", "rejected")]).state, "rejected")
        self.assertEqual(
            summarize_evidence(["A"], [("A", "not_attempted")]).state, "not_completed"
        )

    def test_invalid_duplicate_and_out_of_plan_evidence_rejected(self):
        for plan, outcomes in (
            (["A", "A"], []), ([" "], []), ([True], []),
            (["A"], [("A", "changed"), ("A", "changed")]),
            (["A"], [("B", "changed")]),
            (["A"], [("A", True)]), (["A"], [("A", "accepted")]),
        ):
            with self.subTest(plan=plan, outcomes=outcomes):
                with self.assertRaises(ValueError):
                    summarize_evidence(plan, outcomes)


if __name__ == "__main__":
    unittest.main()

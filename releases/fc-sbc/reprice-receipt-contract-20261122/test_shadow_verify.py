from dataclasses import replace
from decimal import Decimal as D
import unittest

from shadow_verify import PriceState, RowScope, ShadowPlan, StageReceipt, verify_shadow


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.row = RowScope(45, 11, 87)
        self.before = PriceState(D("2.50"), D("150"), 2, D("7.50"))
        self.middle = PriceState(D("2.50"), D("100"), 2, D("5.00"))
        self.after = PriceState(D("3.00"), D("100"), 2, D("6.00"))
        self.plan = ShadowPlan("op-42", self.row, self.before, D("3.00"))
        self.discount = StageReceipt("op-42", self.row, "accepted", self.before, self.middle)
        self.unit = StageReceipt("op-42", self.row, "accepted", self.middle, self.after)

    def test_discount_then_unit_verifies_full_change(self):
        self.assertEqual(verify_shadow(self.plan, self.discount, self.unit).outcome, "changed")

    def test_configured_site_is_not_platform_or_template(self):
        for other in (RowScope(0, 11, 87), RowScope(11, 45, 87), RowScope(45, 11, 88)):
            with self.subTest(other=other):
                result = verify_shadow(self.plan, self.discount, replace(self.unit, scope=other))
                self.assertEqual((result.outcome, result.reason), ("unknown", "wrong_operation_or_row"))

    def test_matching_price_for_other_run_not_proof(self):
        result = verify_shadow(self.plan, self.discount, replace(self.unit, operation="op-43"))
        self.assertEqual(result.outcome, "unknown")

    def test_price_same_is_not_noop_when_discount_differs(self):
        plan = replace(self.plan, target_unit=self.before.unit_price)
        outcome = verify_shadow(plan, self.discount, None)
        self.assertEqual((outcome.outcome, outcome.reason), ("unknown", "discount_applied_unit_unverified"))

    def test_explicit_non_attempt_is_distinct_from_a_missing_receipt(self):
        not_attempted = StageReceipt("op-42", self.row, "not_attempted")
        outcome = verify_shadow(self.plan, self.discount, not_attempted)
        self.assertEqual((outcome.outcome, outcome.reason), ("partial", "discount_applied_unit_not_attempted"))
        with self.assertRaises(ValueError):
            replace(not_attempted, observed_after=self.after)

    def test_first_stage_applied_second_rejected_is_partial(self):
        rejected = replace(self.unit, disposition="rejected", observed_after=self.middle)
        result = verify_shadow(self.plan, self.discount, rejected)
        self.assertEqual((result.outcome, result.reason), ("partial", "discount_applied_unit_rejected"))

    def test_first_stage_applied_second_timeout_is_unverified(self):
        timed_out = replace(self.unit, disposition="unknown")
        result = verify_shadow(self.plan, self.discount, timed_out)
        self.assertEqual((result.outcome, result.reason), ("unknown", "discount_applied_unit_unverified"))

    def test_no_second_stage_credit_without_first_readback(self):
        failed = replace(self.discount, observed_after=None)
        self.assertEqual(verify_shadow(self.plan, failed, self.unit).reason, "discount_stage_unverified")

    def test_rejected_first_stage_needs_no_attempt_in_second(self):
        rejected = replace(self.discount, disposition="rejected", observed_after=self.before)
        not_attempted = StageReceipt("op-42", self.row, "not_attempted")
        self.assertEqual(verify_shadow(self.plan, rejected, not_attempted).outcome, "rejected")
        self.assertEqual(verify_shadow(self.plan, rejected, None).outcome, "unknown")
        self.assertEqual(verify_shadow(self.plan, rejected, self.unit).outcome, "unknown")

    def test_noop_requires_clean_discount_and_all_price_fields(self):
        clean = replace(self.plan, before=self.after)
        self.assertEqual(verify_shadow(clean, None, None).outcome, "unchanged")
        stale = replace(clean, before=replace(self.after, effective_price=D("4.00")))
        self.assertEqual(verify_shadow(stale, None, None).reason, "inconsistent_frozen_price_state")

    def test_already_clean_one_write_still_needs_full_readback(self):
        clean = replace(self.plan, before=self.middle)
        self.assertEqual(verify_shadow(clean, None, self.unit).outcome, "changed")
        self.assertEqual(verify_shadow(clean, None, replace(self.unit, observed_after=None)).outcome, "unknown")

    def test_changed_quantity_or_effective_price_are_not_success(self):
        for after in (replace(self.after, quantity=3), replace(self.after, effective_price=D("3.00"))):
            with self.subTest(after=after):
                self.assertEqual(verify_shadow(self.plan, self.discount, replace(self.unit, observed_after=after)).outcome,
                                 "unknown")

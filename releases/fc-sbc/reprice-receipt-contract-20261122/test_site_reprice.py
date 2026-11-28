from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import unittest

from reprice_plan import PricingRule, ProductRow
from shadow_verify import PriceState
from site_binding import AdminRow, BindingKey
from site_reprice import (
    ConfigReceipt, MmoexpReadback, ScopedInput, plan_all_config, verify_mmoexp,
)


class SiteRepriceTests(unittest.TestCase):
    def setUp(self):
        self.all = BindingKey(45, 0, 21587, 1327, 9971)
        self.mmoexp = replace(self.all, site_id=266)
        self.rule = {(0, "PS", "SBC"): PricingRule(1, 0, 0, ROUND_HALF_UP, True)}
        self.product = ProductRow(17, 266, "PS", "SBC", True, "5", "5", "100", 1,
                                  confirmed_target_usd="6")
        self.item = ScopedInput(self.all, [AdminRow(self.mmoexp, 17)], self.product)

    def plan(self, item=None, rule=None):
        result, = plan_all_config([self.item if item is None else item], {},
                                  self.rule if rule is None else rule)
        return result

    def test_all_target_main_site_input_no_concrete_write_id(self):
        result = self.plan()
        self.assertEqual((result.state, result.unit_price_usd), ("candidate", Decimal("6")))
        self.assertEqual(result.config_scope, self.all)
        self.assertFalse(hasattr(result, "goods_id"))

    def test_all_or_other_site_is_not_admitted_as_input(self):
        for key in (self.all, replace(self.mmoexp, site_id=411)):
            with self.subTest(key=key):
                item = replace(self.item, mmoexp_rows=[AdminRow(key, 17)])
                self.assertEqual(self.plan(item).reason, "scope_mismatch")

    def test_main_site_does_not_become_a_config_target_or_supply_policy(self):
        self.assertEqual(self.plan(replace(self.item, config_scope=self.mmoexp)).reason,
                         "config_must_target_all")
        main_rules = {(266, "PS", "SBC"): next(iter(self.rule.values()))}
        self.assertEqual(self.plan(rule=main_rules).reason, "pricing_rule_unconfirmed")

    def test_wrong_model_platform_ambiguous_or_unmatched_snapshot_refused(self):
        for item, reason in (
            (replace(self.item, mmoexp_rows=[AdminRow(replace(self.mmoexp, model_id=3), 17)]),
             "scope_mismatch"),
            (replace(self.item, mmoexp_rows=[AdminRow(self.mmoexp, 17), AdminRow(self.mmoexp, 18)]),
             "ambiguous"),
            (replace(self.item, product=replace(self.product, goods_id=21)), "mmoexp_snapshot_scope_mismatch"),
            (replace(self.item, product=replace(self.product, platform="PC")), "platform_scope_mismatch"),
            (replace(self.item, product=replace(self.product, kind="Packs")), "unsupported_game_or_category"),
        ):
            with self.subTest(reason=reason):
                self.assertEqual(self.plan(item).reason, reason)

    def test_duplicate_template_product_is_not_planned_twice(self):
        self.assertEqual(
            [p.reason for p in plan_all_config([self.item, self.item], {}, self.rule)],
            ["duplicate_config_scope", "duplicate_config_scope"],
        )

    def test_matching_mmoexp_price_is_not_proof_of_all_config(self):
        item = replace(self.item, product=replace(self.product, confirmed_target_usd="5"))
        self.assertEqual(self.plan(item).reason, "mmoexp_matches_all_config_unverified")

    def test_admin_save_alone_does_not_verify_mmoexp_and_other_scopes_do_not_count(self):
        proposal = self.plan()
        receipt = ConfigReceipt("op-99", self.all, True)
        observed = MmoexpReadback("op-99", self.mmoexp, PriceState(Decimal("6"), Decimal("100"), 1, Decimal("6")))
        self.assertEqual(verify_mmoexp(proposal, receipt, observed), "verified_mmoexp")
        self.assertEqual(verify_mmoexp(proposal, receipt, None), "unconfirmed_mmoexp")
        for wrong in (replace(observed, scope=self.all), replace(observed, operation="another"),
                      replace(observed, scope=replace(self.mmoexp, platform_id=21589))):
            with self.subTest(wrong=wrong):
                self.assertEqual(verify_mmoexp(proposal, receipt, wrong), "unconfirmed_mmoexp")
        self.assertEqual(verify_mmoexp(proposal, replace(receipt, scope=self.mmoexp), observed),
                         "unconfirmed_config")
        for wrong_price in (replace(observed.price, unit_price=Decimal("8")),
                            replace(observed.price, discount=Decimal("80")),
                            replace(observed.price, quantity=2),
                            replace(observed.price, effective_price=Decimal("8"))):
            with self.subTest(wrong_price=wrong_price):
                self.assertEqual(verify_mmoexp(proposal, receipt, replace(observed, price=wrong_price)),
                                 "mmoexp_price_mismatch")

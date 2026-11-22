from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import unittest

from reprice_plan import PricingRule, ProductRow
from site_binding import AdminRow, BindingKey
from site_reprice import ScopedInput, plan_site_reprice


class SiteRepriceTests(unittest.TestCase):
    def setUp(self):
        self.key = BindingKey(45, 911, 21587, 1327, 9971)
        self.rule = {(911, "PS", "SBC"): PricingRule(1, 0, 0, ROUND_HALF_UP, True)}
        self.product = ProductRow(17, 911, "PS", "SBC", True, "5", "5", "100", 1,
                                  confirmed_target_usd="6")
        self.item = ScopedInput(self.key, [AdminRow(self.key, 17)], self.product)

    def test_one_exact_configured_sbc_can_generate_only_a_candidate(self):
        result, = plan_site_reprice([self.item], {}, self.rule)
        self.assertEqual((result.state, result.target_unit_price_usd), ("candidate", Decimal("6")))

    def test_missing_mapping_wrong_scope_and_product_category_cannot_plan(self):
        for item, reason in (
            (replace(self.item, key=None), "not_configured"),
            (replace(self.item, candidates=[AdminRow(self.key, 18)]), "price_row_scope_mismatch"),
            (replace(self.item, product=replace(self.product, platform="PC")), "price_row_scope_mismatch"),
            (replace(self.item, product=replace(self.product, site_id=266)), "price_row_scope_mismatch"),
            (replace(self.item, product=replace(self.product, kind="Packs")), "unsupported_game_or_category"),
        ):
            with self.subTest(reason=reason):
                decision, = plan_site_reprice([item], {}, self.rule)
                self.assertEqual((decision.state, decision.reason), ("unconfirmed", reason))

    def test_old_template_scope_is_not_silently_migrated(self):
        template = replace(self.key, site_id=0)
        item = ScopedInput(template, [AdminRow(template, 18)], replace(self.product, site_id=0, goods_id=18))
        result, = plan_site_reprice([item], {}, self.rule)
        self.assertEqual((result.state, result.reason), ("unconfirmed", "template_not_migrated"))

    def test_duplicate_valid_targets_are_rejected_in_order(self):
        result = plan_site_reprice([self.item, replace(self.item, key=None), self.item], {}, self.rule)
        self.assertEqual([row.reason for row in result], ["duplicate_goods_id", "not_configured",
                                                        "duplicate_goods_id"])

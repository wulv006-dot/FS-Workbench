from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
import unittest

from reprice_plan import (
    FORMULA_V1,
    PLATFORMS,
    ROW_RATE_BASIS,
    TIER_BASIS,
    PricingRule,
    ProductRow,
    TrustedRate,
    plan_prices,
)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.row = ProductRow(71, 911, "PS", "SBC", True, "8.00", "8", "100", 1, 100_000)
        self.rates = {
            p: TrustedRate(p, TIER_BASIS, price, True, 266)
            for p, price in zip(("PS", "XBOX", "PC"), ("8.62", "7.00", "10.50"))
        }
        self.rules = {
            (911, p, kind): PricingRule("1.1", fee, "0", ROUND_HALF_UP, True, FORMULA_V1)
            for p in PLATFORMS for kind, fee in (("SBC", ".24"), ("Packs", 0))
        }

    def plan(self, row=None, *, rates=None, rules=None):
        return plan_prices(
            [self.row if row is None else row],
            self.rates if rates is None else rates,
            self.rules if rules is None else rules,
        )[0]

    def test_three_verified_tiers_and_packs_fee_scope(self):
        for platform, sbc, packs in (("PS", "9.75", "9.48"), ("XBOX", "7.96", "7.70"),
                                     ("PC", "11.81", "11.55")):
            with self.subTest(platform=platform):
                row = replace(self.row, platform=platform)
                self.assertEqual(self.plan(row).target_unit_price_usd, Decimal(sbc))
                pack = replace(row, kind="Packs", fee_override_usd="9.99")
                self.assertEqual(self.plan(pack).target_unit_price_usd, Decimal(packs))

    def test_row_rate_markup_and_zero_fee_override(self):
        row = replace(
            self.row, rate_override=TrustedRate("PS", ROW_RATE_BASIS, "0.00009", True, 911),
            markup_override="1.2", fee_override_usd=0,
        )
        self.assertEqual(self.plan(row, rates={}).target_unit_price_usd, Decimal("10.80"))
        self.assertEqual(self.plan(replace(row, fee_override_usd=None)).target_unit_price_usd,
                         Decimal("11.09"))

    def test_scope_not_guessed_reference_independent_of_product_site(self):
        for row in (replace(self.row, site_id=912), replace(self.row, site_id=0),
                    replace(self.row, kind="unknown"), replace(self.row, platform="Switch"),
                    replace(self.row, site_id=912, confirmed_target_usd="9")):
            with self.subTest(row=row):
                self.assertEqual(self.plan(row).state, "unconfirmed")
        self.assertEqual(self.plan().site_id, 911)
        self.assertEqual(self.plan(rates={
            "PS": replace(self.rates["PS"], source_site_id=911)
        }).reason, "coin_rate_unconfirmed")
        wrong_site_override = TrustedRate("PS", ROW_RATE_BASIS, "0.00009", True, 266)
        self.assertEqual(self.plan(replace(self.row, rate_override=wrong_site_override)).reason,
                         "coin_rate_unconfirmed")

    def test_rule_and_rate_not_guessed_or_fallen_back(self):
        key = (911, "PS", "SBC")
        self.assertEqual(self.plan(rules={}).reason, "pricing_rule_unconfirmed")
        for rule in (replace(self.rules[key], confirmed=False),
                     replace(self.rules[key], formula=None),
                     replace(self.rules[key], formula="markup_before_fee"),
                     replace(self.rules[key], rounding=ROUND_DOWN)):
            self.assertEqual(self.plan(rules={key: rule}).state, "unconfirmed")
        for rate in (None, replace(self.rates["PS"], basis="USD_PER_K"),
                     replace(self.rates["PS"], confirmed=False), self.rates["XBOX"]):
            with self.subTest(rate=rate):
                rates = {"XBOX": self.rates["XBOX"]}
                if rate is not None:
                    rates["PS"] = rate
                self.assertEqual(self.plan(rates=rates).reason, "coin_rate_unconfirmed")
        invalid_override = TrustedRate("PS", ROW_RATE_BASIS, "-1", True, 911)
        self.assertEqual(self.plan(replace(self.row, rate_override=invalid_override)).state,
                         "rejected")

    def test_confirmed_manual_target_is_neither_raw_rounding_nor_rate_fallback(self):
        result = self.plan(replace(self.row, coins=None, confirmed_target_usd="12.30"), rates={})
        self.assertEqual(result.target_unit_price_usd, Decimal("12.30"))
        self.assertEqual(self.plan(replace(self.row, confirmed_target_usd="12.305")).reason,
                         "invalid_confirmed_target")

    def test_cent_rounding_and_explicit_floor_do_not_use_ambient_context(self):
        rates = {"PS": replace(self.rates["PS"], usd="1.005")}
        key = (911, "PS", "SBC")
        rule = PricingRule("1", 0, 0, ROUND_HALF_UP, True, FORMULA_V1)
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = ROUND_DOWN
            self.assertEqual(self.plan(rates=rates, rules={key: rule}).target_unit_price_usd,
                             Decimal("1.01"))
        rule = replace(rule, floor_usd="1.20")
        self.assertEqual(self.plan(rates=rates, rules={key: rule}).target_unit_price_usd,
                         Decimal("1.20"))

    def test_equal_clean_skips_but_same_effective_with_discount_is_candidate(self):
        clean = replace(self.row, confirmed_target_usd="8")
        dirty = replace(clean, current_unit_price_usd=10, current_discount_pct=80)
        self.assertEqual(self.plan(clean).reason, "price_unchanged")
        result = self.plan(dirty)
        self.assertEqual(result.state, "candidate")
        self.assertEqual(result.target_unit_price_usd, Decimal("8.00"))
        self.assertTrue(result.normalize_discount)
        above_hundred = replace(clean, current_unit_price_usd=4, current_discount_pct=200)
        self.assertTrue(self.plan(above_hundred).normalize_discount)

    def test_raw_values_bad_or_missing_are_not_noops(self):
        for row, reason in (
            (replace(self.row, current_price_usd=None), "current_price_fields_missing"),
            (replace(self.row, current_price_usd="8.001"), "invalid_current_price_fields"),
            (replace(self.row, current_price_usd="7.99"), "inconsistent_current_price_fields"),
            (replace(self.row, current_unit_price_usd="Inf"), "invalid_current_price_fields"),
            (replace(self.row, current_quantity=2), "non_single_quantity"),
            (replace(self.row, current_discount_pct=0, current_price_usd=0), "zero_discount_review"),
            (replace(self.row, markup_override="0"), "invalid_pricing_inputs"),
            (replace(self.row, fee_override_usd="-1"), "invalid_pricing_inputs"),
            (replace(self.row, coins=None), "coin_quantity_missing"),
            (replace(self.row, coins="1000.5"), "invalid_pricing_inputs"),
            (replace(self.row, coins=100.0), "invalid_pricing_inputs"),
        ):
            with self.subTest(reason=reason):
                self.assertEqual(self.plan(row).reason, reason)

    def test_duplicate_identity_and_status(self):
        decisions = plan_prices(
            [self.row, replace(self.row, platform="PC"), replace(self.row, goods_id=0),
             replace(self.row, goods_id=89, live=False), replace(self.row, goods_id=90, live=None)],
            self.rates, self.rules,
        )
        self.assertEqual([out.reason for out in decisions],
                         ["duplicate_goods_id", "duplicate_goods_id", "invalid_goods_id",
                          "not_live", "live_status_missing"])

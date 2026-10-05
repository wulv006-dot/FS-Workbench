import unittest

from decimal import Decimal

from fc27_quote_engine import calculate, tiered_page_price as _tiered_page_price


def tiered_page_price(*args, **kwargs):
    quantities = {"lootbar_delivered_k": Decimal("100"),
                  "u4gm_delivered_k": Decimal("100"),
                  "iggm_delivered_k": Decimal("100")}
    return _tiered_page_price(*args, **{**quantities, **kwargs})


def evidence():
    offers = {}
    for platform in ("PS", "XBOX", "PC"):
        offers[platform] = {
            "Lootbar": {"usd_price": "15.38", "base_k": "100", "bonus_k": "5", "url": "https://www.lootbar.com/game-coins/fc27"},
            "U4GM": {"usd_price": "14.89", "base_k": "100", "bonus_k": "0", "url": "https://www.u4gm.com/fc-27/coins"},
            "IGGM": {"usd_price": "14.89", "base_k": "100", "bonus_k": "0", "url": "https://www.iggm.com/ea-sports-fc/fc-27-coins"},
            "U7Buy": {"usd_price": "14.00", "base_k": "100", "bonus_k": "5", "conditional": True,
                      "comparable": False, "url": "https://www.u7buy.com/fc27/coins"},
        }
    return {"fx": {"cny_per_usd": "6.7489"},
            "costs": {p: {"cny_per_1k": "0.75", "record_id": "1", "trade_at": "now"} for p in offers},
            "offers": offers}


class QuoteEngineTests(unittest.TestCase):
    def test_fc27_xbox_follows_ps_auto_price_without_changing_pc_or_cost(self):
        source = self.page_evidence(costs=("0.50", "0.70", "0.80"))
        independent = calculate(source)["rows"]
        source["game"] = "FC27"
        rows = calculate(source)["rows"]
        self.assertEqual(rows[1]["proposal"], rows[0]["auto_proposal"])
        self.assertEqual(rows[1]["auto_price_source"], "PS")
        self.assertEqual(rows[1]["cost_cny"], "0.70")
        self.assertEqual(rows[2], independent[2])
        self.assertNotEqual(rows[1]["independent_auto_proposal"], rows[1]["auto_proposal"])

    def test_xbox_cost_floor_blocks_ps_price_without_lifting_ps_price(self):
        source = self.page_evidence(costs=("0.50", "1.00", "0.80"))
        source["game"] = "FC27"
        rows = calculate(source)["rows"]
        self.assertEqual(rows[1]["proposal"], rows[0]["proposal"])
        self.assertTrue(rows[1]["margin_below_minimum"])
        self.assertFalse(rows[0]["margin_below_minimum"])
        self.assertIn("不执行自动改价", rows[1]["warning"])

    def test_manual_quotes_remain_independent_from_shared_auto_anchor(self):
        source = self.page_evidence()
        source["game"] = "FC27"
        rows = calculate(source, {"quotes": {"PS": "0.2000", "XBOX": "0.2100"}})["rows"]
        self.assertEqual(rows[0]["proposal"], "0.2000")
        self.assertEqual(rows[1]["proposal"], "0.2100")
        self.assertEqual(rows[1]["auto_proposal"], rows[0]["auto_proposal"])
        source["game"] = "MLB26"
        independent = calculate(source)["rows"]
        self.assertNotIn("auto_price_source", independent[1])

    def page_evidence(self, costs=("0.50", "0.70", "0.80"), bonus="5"):
        source = evidence()
        source["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": bonus, "package_usd": "15.00"}
            for p in ("PS", "XBOX", "PC")}}
        for platform, cost in zip(("PS", "XBOX", "PC"), costs):
            source["costs"][platform]["cny_per_1k"] = cost
        return source

    def test_page_price_uses_pre_change_margin_and_three_bands(self):
        rows = calculate(self.page_evidence(), {"minimum_gross_margin_pct": "20"})["rows"]
        high, middle, low = rows
        self.assertEqual(high["pricing_tier"], "at_least_40")
        self.assertTrue(-0.1 <= float(high["lootbar_reduction_pct"]) <= 10)
        self.assertGreater(float(high["gross_margin_pct"]), 30)
        self.assertEqual(middle["pricing_tier"], "20_to_30")
        self.assertLessEqual(float(middle["lootbar_reduction_pct"]), 5)
        self.assertTrue(20 <= float(middle["gross_margin_pct"]) <= 30)
        self.assertEqual(low["pricing_tier"], "below_20")
        self.assertIsNone(low["auto_blocked_reason"])
        self.assertGreaterEqual(float(low["gross_margin_pct"]), 20)
        self.assertIsNotNone(low["target_page_usd"])

    def test_pre_change_tier_does_not_switch_after_discount(self):
        row = calculate(self.page_evidence(costs=("0.63", "0.70", "0.80")),
                        {"minimum_gross_margin_pct": "20"})["rows"][0]
        self.assertGreater(float(row["pre_change_margin_pct"]), 30)
        self.assertEqual(row["pricing_tier"], "30_to_40")
        self.assertLess(float(row["gross_margin_pct"]), 35)
        self.assertGreaterEqual(float(row["gross_margin_pct"]), 20)

    def test_page_margin_counts_own_bonus_and_manual_quote_can_be_reviewed(self):
        with_bonus = calculate(self.page_evidence(costs=("0.70", "0.70", "0.70")),
                               {"minimum_gross_margin_pct": "20"})["rows"][0]
        without_bonus = calculate(self.page_evidence(costs=("0.70", "0.70", "0.70"), bonus="0"),
                                  {"minimum_gross_margin_pct": "20"})["rows"][0]
        self.assertGreater(float(with_bonus["floor_usd_per_1k"]),
                           float(without_bonus["floor_usd_per_1k"]))
        manual = calculate(self.page_evidence(), {"minimum_gross_margin_pct": "20",
                                                   "quotes": {"PC": "0.1000"}})["rows"][2]
        self.assertTrue(manual["quote_manual"])
        self.assertIsNone(manual["auto_blocked_reason"])
        self.assertTrue(manual["margin_below_minimum"])

    def test_floor_clamps_downward_following_and_extreme_values_terminate(self):
        clamped = calculate(self.page_evidence(costs=("0.77", "0.70", "0.80")),
                            {"minimum_gross_margin_pct": "20"})["rows"][0]
        self.assertIsNone(clamped["auto_blocked_reason"])
        self.assertGreaterEqual(float(clamped["gross_margin_pct"]), 20)
        self.assertEqual(tiered_page_price(
            Decimal("10"), Decimal("9"), Decimal("9"), Decimal("0.063"),
            Decimal("100"), Decimal("20"), Decimal("35"))["tier"], "30_to_40")
        huge = tiered_page_price(
            Decimal("100000000"), Decimal("90000000"), Decimal("90000000"),
            Decimal("500000"), Decimal("100"), Decimal("20"), Decimal("40"))
        self.assertEqual(huge["tier"], "at_least_40")

    def test_high_margin_uses_two_competitor_gaps_and_ten_percent_cap(self):
        args = (Decimal("0.04"), Decimal("100"), Decimal("10"), Decimal("40"))
        self.assertEqual(tiered_page_price(Decimal("10"), Decimal("8.50"),
                                           Decimal("8.80"), *args)["cents"], 900)
        self.assertEqual(tiered_page_price(Decimal("10"), Decimal("9.60"),
                                           Decimal("9.80"), *args)["cents"], 970)
        self.assertEqual(tiered_page_price(Decimal("10"), Decimal("8.00"),
                                           Decimal("9.80"), *args)["cents"], 900)
        self.assertEqual(tiered_page_price(Decimal("10"), Decimal("10.20"),
                                           Decimal("9.80"), *args)["cents"], 990)
        self.assertEqual(tiered_page_price(Decimal("10"), Decimal("8.50"),
                                           Decimal("8.80"), Decimal("0.04"),
                                           Decimal("100"), Decimal("60"), Decimal("40"))["cents"], 1000)

    def test_thirty_and_twenty_percent_bands_have_fixed_targets(self):
        base = (Decimal("10"), Decimal("9"), Decimal("9"),
                Decimal("0.04"), Decimal("100"), Decimal("10"))
        self.assertEqual(tiered_page_price(*base, Decimal("30"))["cents"], 925)
        self.assertEqual(tiered_page_price(*base, Decimal("29.99"))["cents"], 950)
        self.assertEqual(tiered_page_price(*base, Decimal("19.99"))["cents"], 1000)

    def test_competitor_bonus_changes_anchor_own_bonus_does_not_raise_price(self):
        args = (Decimal("10.50"), Decimal("9.00"), Decimal("9.00"),
                Decimal("0.04"), Decimal("100"), Decimal("10"), Decimal("35"))
        picked = tiered_page_price(*args, lootbar_delivered_k=Decimal("105"))
        self.assertEqual(picked["cents"], 925)
        self.assertLessEqual(picked["discount"], Decimal("7.5"))
        own_bonus = tiered_page_price(*args[:4], Decimal("110"), *args[5:],
                                      lootbar_delivered_k=Decimal("105"))
        self.assertEqual(own_bonus["cents"], 925)
        high = tiered_page_price(Decimal("10.50"), Decimal("9.00"), Decimal("9.00"),
                                 Decimal("0.04"), Decimal("100"), Decimal("10"), Decimal("40"),
                                 lootbar_delivered_k=Decimal("105"),
                                 u4gm_delivered_k=Decimal("100"),
                                 iggm_delivered_k=Decimal("100"))
        self.assertEqual(high["cents"], 900)

    def test_effective_gap_uses_each_competitor_bonus(self):
        source = self.page_evidence(costs=("0.40", "0.40", "0.40"), bonus="0")
        for platform in ("PS", "XBOX", "PC"):
            source["offers"][platform]["Lootbar"].update(usd_price="10.50", bonus_k="5")
            source["offers"][platform]["U4GM"].update(usd_price="9.90", bonus_k="10")
            source["offers"][platform]["IGGM"].update(usd_price="9.00", bonus_k="0")
        row = calculate(source)["rows"][0]
        self.assertEqual(row["pricing_tier"], "at_least_40")
        self.assertEqual(row["u4gm_gap_pct"], "10.00")
        self.assertEqual(row["iggm_gap_pct"], "10.00")
        self.assertEqual(row["target_page_usd"], "9.00")
        self.assertEqual(row["lootbar_reduction_pct"], "10.00")

    def test_missing_core_bonus_means_zero_bonus(self):
        source = self.page_evidence()
        del source["offers"]["PS"]["Lootbar"]["bonus_k"]
        row = calculate(source)["rows"][0]
        source["offers"]["PS"]["Lootbar"]["bonus_k"] = "0"
        explicit_zero = calculate(source)["rows"][0]
        self.assertEqual(row["proposal"], explicit_zero["proposal"])
        self.assertEqual(row["lootbar_usd_per_1k"], explicit_zero["lootbar_usd_per_1k"])

    def test_bonus_and_conditional_price(self):
        row = calculate(evidence())["rows"][0]
        self.assertEqual(row["lowest_site"], "Lootbar")
        self.assertEqual(row["proposal"], "0.1457")
        self.assertEqual(row["lootbar_reduction_pct"], "0.50")
        self.assertFalse(row["offers"][3]["comparable"])

    def test_manual_cost_recomputes_without_changing_source(self):
        original = evidence()
        row = calculate(original, {"costs": {"PS": "0.80"}})["rows"][0]
        self.assertEqual(row["cost_cny"], "0.80")
        self.assertEqual(row["raw_cost_cny"], "0.75")
        self.assertEqual(original["costs"]["PS"]["cny_per_1k"], "0.75")

    def test_missing_cost_keeps_competitor_table(self):
        source = evidence()
        source["costs"].pop("PS")
        row = calculate(source)["rows"][0]
        self.assertEqual(row["status"], "缺成本")
        self.assertEqual(len(row["offers"]), 4)
        self.assertIsNone(row["proposal"])

    def test_manual_price_below_margin_floor_is_warned(self):
        row = calculate(evidence(), {"quotes": {"PS": "0.10"}})["rows"][0]
        self.assertEqual(row["proposal"], "0.1000")
        self.assertTrue(row["margin_below_minimum"])
        self.assertEqual(row["pricing_mode"], "manual")
        self.assertIn("已按人工审核价", row["warning"])
        self.assertEqual(row["status"], "人工审核通过 · 待发布")

    def test_secondary_discount_stays_small_and_lootbar_is_anchor(self):
        source = evidence()
        source["offers"]["PS"]["U4GM"]["usd_price"] = "14.50"
        row = calculate(source, {"minimum_gross_margin_pct": "23"})["rows"][0]
        self.assertEqual(row["lowest_site"], "U4GM")
        self.assertEqual(row["pricing_mode"], "lootbar_anchor")
        self.assertEqual(row["proposal"], "0.1456")
        self.assertEqual(row["benchmark_site"], "Lootbar")
        self.assertEqual(row["lootbar_reduction_pct"], "0.55")
        self.assertFalse(row["margin_below_minimum"])
        self.assertEqual(row["warning"], "")

    def test_lootbar_target_below_margin_requires_review(self):
        source = evidence()
        source["offers"]["PS"]["U4GM"]["usd_price"] = "14.50"
        row = calculate(source, {"minimum_gross_margin_pct": "30"})["rows"][0]
        self.assertEqual(row["pricing_mode"], "margin_warning")
        self.assertEqual(row["proposal"], "0.1456")
        self.assertTrue(row["margin_below_minimum"])
        self.assertIn("Lootbar 基准下调", row["warning"])

    def test_secondary_gap_is_capped_and_never_raises_lootbar_anchor(self):
        source = evidence()
        for site in ("U4GM", "IGGM"):
            source["offers"]["PS"][site]["usd_price"] = "5.00"
        row = calculate(source)["rows"][0]
        self.assertEqual(row["lootbar_reduction_pct"], "8.00")
        self.assertEqual(row["benchmark_site"], "Lootbar")
        self.assertGreater(float(row["proposal"]), float(row["lowest_usd_per_1k"]))
        lootbar = 15.38 / 105
        self.assertGreaterEqual(float(row["proposal"]), lootbar * 0.92)

    def test_user_supplied_gap_maps_to_small_anchor_reduction(self):
        source = evidence()
        source["offers"]["PS"]["Lootbar"].update(usd_price="140", bonus_k="0")
        for site in ("U4GM", "IGGM"):
            source["offers"]["PS"][site]["usd_price"] = "120"
        row = calculate(source)["rows"][0]
        self.assertEqual(row["lootbar_reduction_pct"], "3.36")
        self.assertEqual(row["benchmark_site"], "Lootbar")

    def test_single_extreme_secondary_cannot_trigger_full_discount(self):
        source = evidence()
        source["offers"]["PS"]["U4GM"]["usd_price"] = "0.01"
        row = calculate(source)["rows"][0]
        self.assertLess(float(row["lootbar_reduction_pct"]), 8)

    def test_missing_comparable_anchor_blocks_quote(self):
        source = evidence()
        source["offers"]["PS"]["U4GM"]["comparable"] = False
        row = calculate(source)["rows"][0]
        self.assertEqual(row["status"], "核心竞品不可比")
        self.assertIsNone(row["proposal"])

    def test_invalid_margin_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate(evidence(), {"minimum_gross_margin_pct": "100"})

    def test_missing_competitor_blocks_numeric_proposal(self):
        source = evidence()
        source["offers"]["PS"].pop("U4GM")
        row = calculate(source)["rows"][0]
        self.assertIsNone(row["proposal"])
        self.assertEqual(row["missing"], ["U4GM"])


if __name__ == "__main__":
    unittest.main()

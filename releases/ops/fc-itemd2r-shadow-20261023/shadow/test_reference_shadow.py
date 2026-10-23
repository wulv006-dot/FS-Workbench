import ast
import copy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("reference_shadow", Path(__file__).parent/"source/reference_shadow.py")
shadow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shadow)
NOW = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)


def fixture(legacy=False):
    rows = [dict(platform=platform, source=site, run_id="synthetic-observation-1", game="FC27",
                 product="Game Coins", status="valid", currency="USD", gross_usd="20.00",
                 purchase_k="100", bonus_k="5", comparable=True, conditional=False, captured_at=NOW.isoformat())
            for platform in shadow.PLATFORMS for site in (shadow.LEGACY_SITES if legacy else shadow.SITES)]
    for row in rows:
        if row["source"] == "Lootbar": row["url"] = "https://www.lootbar.com/game-coins/fc27"
    return rows


def storefront():
    return dict(status="ok", currency="USD", collection_run_id="synthetic-observation-1",
                rows={p: dict(status="ok", platform=p, checked_at=NOW.isoformat(),
                              package_usd="21.00", base_k="100", bonus_k="5") for p in shadow.PLATFORMS})


class ReferenceShadow(unittest.TestCase):
    def test_five_sources_select_second_tier_and_keep_third_visible(self):
        result = shadow.simulate_reference_tiers(fixture())
        self.assertEqual(result["input_schema"], "five_site_15")
        self.assertTrue(result["shadow_core_comparable"])
        for platform in shadow.PLATFORMS:
            self.assertEqual(result["reference_sources"][platform], ["U7Buy", "ItemD2R"])
            self.assertEqual(set(result["observations"][platform]), set(shadow.SITES))

    def test_legacy_complete_twelve_rows_remain_supported(self):
        result = shadow.simulate_reference_tiers(fixture(legacy=True))
        self.assertEqual(result["input_schema"], "legacy_12")
        self.assertEqual(result["reference_sources"]["PS"], ["U7Buy"])

    def test_one_second_tier_is_not_mixed_with_third_as_equal_weight(self):
        rows = fixture()
        for row in rows:
            if row["source"] == "U7Buy": row["status"] = "missing"
        result = shadow.simulate_reference_tiers(rows)
        self.assertEqual(result["reference_sources"]["PS"], ["ItemD2R"])
        self.assertIsNone(result["weight_percentages"])

    def test_third_tier_is_used_only_without_comparable_second_tier(self):
        rows = fixture()
        for row in rows:
            if row["source"] in shadow.SOURCE_TIERS["second"]: row["status"] = "missing"
        result = shadow.simulate_reference_tiers(rows)
        self.assertEqual(result["reference_sources"]["PS"], ["IGGM", "U4GM"])
        self.assertEqual(result["selected_reference_tiers"]["PS"], "third")

    def test_all_references_missing_keeps_core_observation(self):
        rows = fixture()
        for row in rows:
            if row["source"] != "Lootbar": row["status"] = "missing"
        result = shadow.simulate_reference_tiers(rows)
        self.assertEqual(result["reference_sources"]["PS"], [])
        self.assertTrue(result["shadow_core_comparable"])

    def test_conditional_offer_is_never_selected_even_if_comparable_true(self):
        rows = fixture()
        for row in rows:
            if row["source"] == "ItemD2R": row["conditional"] = True
        result = shadow.simulate_reference_tiers(rows)
        self.assertEqual(result["reference_sources"]["PS"], ["U7Buy"])
        self.assertFalse(result["observations"]["PS"]["ItemD2R"]["comparable"])

    def test_normalization_includes_gifts_and_preserves_input(self):
        rows = fixture()
        original = copy.deepcopy(rows)
        result = shadow.simulate_reference_tiers(rows)
        self.assertEqual(rows, original)
        self.assertEqual(result["observations"]["PS"]["Lootbar"]["delivered_k"], "105")
        self.assertTrue(result["observations"]["PS"]["Lootbar"]["usd_per_k"].startswith("0.190476"))

    def test_incomplete_duplicate_and_wrong_site_are_not_mixed_into_coverage(self):
        cases = [fixture()[:-1], fixture()+[fixture()[0]], fixture()]
        cases[-1][-1] = copy.deepcopy(cases[-1][0])
        wrong = fixture(); wrong[0]["source"] = "Other"
        cases.append(wrong)
        for rows in cases:
            with self.assertRaisesRegex(ValueError, "coverage"):
                shadow.simulate_reference_tiers(rows)

    def test_mixed_original_runs_rejected(self):
        rows = fixture(); rows[-1]["run_id"] = "different-run"
        with self.assertRaisesRegex(ValueError, "same_original_run"):
            shadow.simulate_reference_tiers(rows)

    def test_malformed_run_and_source_have_explicit_errors(self):
        for key, value in (("run_id", {}), ("source", [])):
            rows = fixture(); rows[0][key] = value
            with self.assertRaises(ValueError):
                shadow.simulate_reference_tiers(rows)

    def test_itemd2r_never_uses_a_row_whose_url_is_iggm(self):
        rows = fixture()
        for row in rows:
            if row["source"] == "ItemD2R": row["url"] = "https://www.iggm.com/ea-sports-fc/fc-27-coins"
        result = shadow.simulate_reference_tiers(rows)
        self.assertEqual(result["reference_sources"]["PS"], ["U7Buy"])
        self.assertEqual(result["observations"]["PS"]["ItemD2R"]["reason"], "source_url_identity_mismatch")

    def test_actual_project_lootbar_url_is_used_not_an_assumed_domain(self):
        rows = fixture()
        result = shadow.experimental_scenarios(rows, now=NOW, storefront=storefront())
        self.assertTrue(result["shadow_core_comparable"])
        for row in rows:
            if row["source"] == "Lootbar": row["url"] = "https://lootbar.gg/game-coins/fc27"
        result = shadow.experimental_scenarios(rows, now=NOW, storefront=storefront())
        self.assertFalse(result["shadow_core_comparable"])
        self.assertIsNone(result["weighted_platforms"]["PS"]["scenarios"][0]["weighted_unit"])

    def test_wrong_game_or_product_rejected(self):
        for key, value in (("game", "FC26"), ("product", "Items")):
            rows = fixture(); rows[0][key] = value
            with self.assertRaisesRegex(ValueError, "identity"):
                shadow.simulate_reference_tiers(rows)

    def test_invalid_currency_price_and_package_are_not_selected(self):
        for key, value in (("currency", "EUR"), ("gross_usd", "NaN"), ("gross_usd", "-1"),
                           ("gross_usd", "1.001"), ("purchase_k", "10"), ("bonus_k", "101"), ("gross_usd", True)):
            rows = fixture()
            for row in rows:
                if row["source"] == "ItemD2R": row[key] = value
            result = shadow.simulate_reference_tiers(rows)
            self.assertEqual(result["reference_sources"]["PS"], ["U7Buy"])

    def test_shadow_has_no_io_or_production_pricing_imports_or_price_proposal(self):
        result = shadow.simulate_reference_tiers(fixture())
        self.assertTrue(result["simulation_only"])
        self.assertEqual(result["business_effect"], "none")
        self.assertFalse(result["production_strategy_changed"])
        self.assertNotIn("proposal", result)
        source = Path(__file__).parent/"source/reference_shadow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertEqual(imports, ["decimal", "datetime", "urllib.parse"])
        calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(calls & {"open", "write", "calculate", "check_write", "apply_decision", "send", "evaluate", "recommend", "model", "writer", "prove_catalog"})

    def test_three_weighted_experiments_have_explicit_nonproduction_parameters(self):
        rows, own = fixture(), storefront()
        original_rows, original_own = copy.deepcopy(rows), copy.deepcopy(own)
        result = shadow.experimental_scenarios(rows, now=NOW, storefront=own)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["price_recommendation"])
        self.assertEqual(rows, original_rows); self.assertEqual(own, original_own)
        self.assertIn("not_user_selected_or_production_rules", result["experimental_parameters"])
        scenario = result["weighted_platforms"]["PS"]["scenarios"]
        self.assertEqual([s["anchor_weight"] for s in scenario], ["0.6", "0.7", "0.8"])
        for item in scenario:
            weights = {site: Decimal(value) for site, value in item["reference_weights"].items()}
            self.assertAlmostEqual(Decimal(item["anchor_weight"])+sum(weights.values()), Decimal(1), places=25)
            self.assertAlmostEqual(weights["U7Buy"], weights["IGGM"]*2, places=25)
            self.assertEqual(item["margin_redlines"], "not_evaluated_requires_original_prove_catalog")
            self.assertAlmostEqual(Decimal(item["weighted_unit"]), Decimal("20")/105, places=25)
            self.assertLess(Decimal(item["delta_vs_storefront_pct"]), 0)

    def test_weighted_experiments_require_core_and_do_not_replace_it(self):
        for mutation in (dict(status="missing"), dict(currency="EUR"), dict(captured_at=(NOW+timedelta(seconds=1)).isoformat())):
            rows = fixture()
            for row in rows:
                if row["source"] == "Lootbar": row.update(mutation)
            result = shadow.experimental_scenarios(rows, now=NOW, storefront=storefront())
            self.assertEqual(result["status"], "partial")
            self.assertTrue(all(item["weighted_unit"] is None for item in result["weighted_platforms"]["PS"]["scenarios"]))

    def test_missing_iggm_is_partial_not_old_price_fallback(self):
        rows = fixture()
        for row in rows:
            if row["source"] == "IGGM": row["status"] = "missing"
        result = shadow.experimental_scenarios(rows, now=NOW, storefront=storefront())
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["observations"]["PS"]["IGGM"]["usd_per_k"])
        for item in result["weighted_platforms"]["PS"]["scenarios"]:
            self.assertNotIn("IGGM", item["reference_weights"])
            self.assertIsNotNone(item["weighted_unit"])

    def test_reference_stale_future_and_missing_timestamp_are_explicit_partial(self):
        for stamp, reason in (((NOW-timedelta(seconds=901)).isoformat(), "timestamp_stale"),
                              ((NOW+timedelta(seconds=1)).isoformat(), "timestamp_future"),
                              (None, "timestamp_invalid")):
            rows = fixture()
            for row in rows:
                if row["source"] == "ItemD2R": row["captured_at"] = stamp
            result = shadow.experimental_scenarios(rows, now=NOW, storefront=storefront())
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["observations"]["PS"]["ItemD2R"]["reason"], reason)
            self.assertNotIn("ItemD2R", result["weighted_platforms"]["PS"]["scenarios"][0]["reference_weights"])

    def test_storefront_must_match_original_run_platform_currency_and_time(self):
        for key, value in (("collection_run_id", "different-run"), ("currency", "EUR")):
            own = storefront(); own[key] = value
            result = shadow.experimental_scenarios(fixture(), now=NOW, storefront=own)
            self.assertEqual(result["status"], "partial")
            self.assertIsNone(result["weighted_platforms"]["PS"]["scenarios"][0]["delta_vs_storefront_pct"])
        for key, value in (("platform", "PC"), ("checked_at", (NOW-timedelta(seconds=901)).isoformat()), ("package_usd", "-1"), ("conditional", True)):
            own = storefront(); own["rows"]["PS"][key] = value
            result = shadow.experimental_scenarios(fixture(), now=NOW, storefront=own)
            self.assertIsNone(result["weighted_platforms"]["PS"]["storefront_unit"])

    def test_weighted_experiments_without_any_reference_do_not_invent_weights(self):
        rows = fixture()
        for row in rows:
            if row["source"] != "Lootbar": row["status"] = "missing"
        result = shadow.experimental_scenarios(rows, now=NOW, storefront=storefront())
        for item in result["weighted_platforms"]["PS"]["scenarios"]:
            self.assertIsNone(item["weighted_unit"])
            self.assertEqual(item["reference_weights"], {})

    def test_weighted_clock_and_age_limit_are_not_optional(self):
        for now, limit in ((NOW.replace(tzinfo=None), 900), (NOW, 901), (NOW, True)):
            with self.assertRaises(ValueError):
                shadow.experimental_scenarios(fixture(), now=now, maximum_age_seconds=limit)


if __name__ == "__main__":
    unittest.main()

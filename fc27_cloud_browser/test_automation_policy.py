"""Fail-closed contract tests for the FC27 automation control plane."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from automation_policy import initial_policy, normalize_policy, check_write, sale_floor
from automation_tick import due


def configured(mode="auto", margin="10"):
    raw = {key: value for key, value in initial_policy().items()
           if key not in {"revision", "updated_at", "updated_by"}}
    raw.update({"system_enabled": True, "mode": mode,
                "minimum_gross_margin_pct": margin})
    return {**normalize_policy(raw), "revision": 1, "updated_at": None, "updated_by": None}


def quote(prices=None, margin="10"):
    prices = prices or {"PS": "0.15", "XBOX": "0.15", "PC": "0.15"}
    return {"automation_policy_revision": 1, "edits": {},
            "evidence": {"fx": {"cny_per_usd": "8"}},
            "result": {"minimum_gross_margin_pct": margin,
                       "rows": [{"platform": platform, "proposal": prices[platform],
                                 "cost_cny": "1", "missing": []}
                                for platform in ("PS", "XBOX", "PC")]}}


class AutomationPolicyTest(unittest.TestCase):
    def test_shared_fc27_market_recomputes_ps_anchor_and_preserves_xbox_floor(self):
        from fc27_quote_engine import calculate
        from test_fc27_quote_engine import QuoteEngineTests
        source = QuoteEngineTests().page_evidence(costs=("0.50", "0.70", "0.80"))
        source["game"] = "FC27"
        proposal = {"automation_policy_revision": 1, "edits": {}, "evidence": source,
                    "result": calculate(source)}
        self.assertEqual(check_write(configured(), proposal, ["XBOX"], automatic=True), [])
        xbox = proposal["result"]["rows"][1]
        xbox["proposal"] = xbox["independent_auto_proposal"]
        xbox["target_page_usd"] = str(Decimal(xbox["proposal"]) * 100)
        with self.assertRaisesRegex(ValueError, "automatic_tier_rule:XBOX"):
            check_write(configured(), proposal, ["XBOX"], automatic=True)
        source["costs"]["XBOX"]["cny_per_1k"] = "1.00"
        proposal["result"] = calculate(source)
        self.assertEqual(check_write(configured(), proposal, ["PS"], automatic=True), [])
        with self.assertRaisesRegex(ValueError, "automatic_margin_floor:XBOX"):
            check_write(configured(), proposal, ["XBOX"], automatic=True)

    def test_disabled_initial_policy_defaults_to_ten_margin_and_no_sale_price(self):
        policy = initial_policy()
        self.assertFalse(policy["system_enabled"])
        self.assertNotIn("minimum_sale_usd_per_k", policy)
        self.assertEqual(policy["minimum_gross_margin_pct"], "10")

    def test_can_enable_with_default_margin_and_no_sale_price(self):
        raw = {key: value for key, value in initial_policy().items()
               if key not in {"revision", "updated_at", "updated_by"}}
        raw["system_enabled"] = True
        self.assertTrue(normalize_policy(raw)["system_enabled"])

    def test_margin_is_editable_and_interval_accepts_1_to_9999_minutes(self):
        raw = {key: value for key, value in configured().items()
               if key not in {"revision", "updated_at", "updated_by"}}
        raw["minimum_gross_margin_pct"] = "12.5"
        raw["interval_minutes"] = 9999
        self.assertEqual(normalize_policy(raw)["minimum_gross_margin_pct"], "12.5")
        raw["interval_minutes"] = 1
        self.assertEqual(normalize_policy(raw)["interval_minutes"], 1)
        raw["interval_minutes"] = 10000
        with self.assertRaisesRegex(ValueError, "automation_interval_invalid"):
            normalize_policy(raw)
        raw["interval_minutes"] = 60
        raw["minimum_gross_margin_pct"] = "100"
        with self.assertRaisesRegex(ValueError, "minimum_margin_invalid"):
            normalize_policy(raw)

    def test_dynamic_floor_rounds_up_and_exact_margin_is_allowed(self):
        self.assertEqual(str(sale_floor("1", "8", "10")), "0.1389")
        self.assertEqual(str(sale_floor("1", "8", "20")), "0.1563")
        exact = quote({"PS": "0.1000", "XBOX": "0.15", "PC": "0.15"})
        exact["result"]["rows"][0]["cost_cny"] = "0.9"
        exact["evidence"]["fx"]["cny_per_usd"] = "10"
        self.assertEqual(check_write(configured(), exact, ["PS"], automatic=True), [])

    def test_changed_margin_recomputes_each_platform_floor(self):
        with self.assertRaisesRegex(ValueError, "automatic_margin_floor:PS"):
            check_write(configured(margin="20"), quote(margin="20"), ["PS"], automatic=True)
        with self.assertRaisesRegex(ValueError, "automation_policy_changed_since_quote"):
            check_write(configured(margin="20"), quote(), ["PS"], automatic=True)

    def test_page_total_write_gate_counts_bonus_and_checks_margin_band(self):
        self.assertEqual(str(sale_floor("0.8", "8", "20", delivered_k=105)), "0.1313")
        page_quote = quote({p: "0.0905" for p in ("PS", "XBOX", "PC")}, margin="20")
        page_quote["evidence"]["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": "5", "package_usd": "10.00"}
            for p in ("PS", "XBOX", "PC")}}
        page_quote["evidence"]["offers"] = {p: {"Lootbar": {"usd_price": "10.00",
                                                          "base_k": "100", "bonus_k": "5"}}
                                              for p in ("PS", "XBOX", "PC")}
        row = page_quote["result"]["rows"][0]
        row.update(cost_cny="0.55", pricing_basis="page_total_100k",
                   target_page_usd="9.05", quote_manual=False)
        self.assertEqual(check_write(configured(margin="20"), page_quote,
                                     ["PS"], automatic=True), [])
        row["target_page_usd"] = "9.51"
        with self.assertRaisesRegex(ValueError, "automation_page_target_mismatch"):
            check_write(configured(margin="20"), page_quote, ["PS"], automatic=True)
        row["target_page_usd"] = "9.05"
        row["auto_blocked_reason"] = "no_feasible_margin_tier"
        with self.assertRaisesRegex(ValueError, "automatic_tier_unavailable"):
            check_write(configured(margin="20"), page_quote, ["PS"], automatic=True)
        row["auto_blocked_reason"] = None
        row["proposal"] = "0.0960"
        row["target_page_usd"] = "9.60"
        with self.assertRaisesRegex(ValueError, "automatic_tier_rule"):
            check_write(configured(margin="20"), page_quote, ["PS"], automatic=True)
        row["proposal"] = "0.1300"
        row["target_page_usd"] = "13.00"
        row["cost_cny"] = "0.8"
        with self.assertRaisesRegex(ValueError, "automatic_margin_floor"):
            check_write(configured(margin="20"), page_quote, ["PS"], automatic=True)

    def test_high_margin_write_gate_requires_exact_competitor_target(self):
        page_quote = quote({p: "0.0858" for p in ("PS", "XBOX", "PC")})
        page_quote["evidence"]["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": "5", "package_usd": "10.00"}
            for p in ("PS", "XBOX", "PC")}}
        page_quote["evidence"]["offers"] = {p: {
            "Lootbar": {"usd_price": "10.00", "base_k": "100", "bonus_k": "5"},
            "U4GM": {"usd_price": "8.50", "base_k": "100", "bonus_k": "5"},
            "IGGM": {"usd_price": "8.80", "base_k": "100", "bonus_k": "5"}}
            for p in ("PS", "XBOX", "PC")}
        row = page_quote["result"]["rows"][0]
        row.update(cost_cny="0.40", pricing_basis="page_total_100k",
                   target_page_usd="8.58", quote_manual=False)
        self.assertEqual(check_write(configured(), page_quote, ["PS"], automatic=True), [])
        row["proposal"] = "0.0899"
        row["target_page_usd"] = "8.99"
        with self.assertRaisesRegex(ValueError, "automatic_tier_rule"):
            check_write(configured(), page_quote, ["PS"], automatic=True)
        row["proposal"] = "0.0858"
        row["target_page_usd"] = "8.58"
        page_quote["evidence"]["offers"]["PS"]["U4GM"]["usd_price"] = "9.60"
        page_quote["evidence"]["offers"]["PS"]["IGGM"]["usd_price"] = "9.80"
        with self.assertRaisesRegex(ValueError, "automatic_tier_rule"):
            check_write(configured(), page_quote, ["PS"], automatic=True)

    def test_thirty_percent_write_gate_uses_seven_point_five(self):
        page_quote = quote({p: "0.0881" for p in ("PS", "XBOX", "PC")})
        page_quote["evidence"]["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": "5", "package_usd": "10.00"}
            for p in ("PS", "XBOX", "PC")}}
        page_quote["evidence"]["offers"] = {p: {
            "Lootbar": {"usd_price": "10.00", "base_k": "100", "bonus_k": "5"}}
            for p in ("PS", "XBOX", "PC")}
        row = page_quote["result"]["rows"][0]
        row.update(cost_cny="0.50", pricing_basis="page_total_100k",
                   target_page_usd="8.81", quote_manual=False)
        self.assertEqual(check_write(configured(), page_quote, ["PS"], automatic=True), [])
        row["proposal"] = "0.0924"
        row["target_page_usd"] = "9.24"
        with self.assertRaisesRegex(ValueError, "automatic_tier_rule"):
            check_write(configured(), page_quote, ["PS"], automatic=True)

    def test_write_gate_uses_lootbar_bonus_adjusted_unit_price(self):
        page_quote = quote({p: "0.0925" for p in ("PS", "XBOX", "PC")})
        page_quote["evidence"]["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": "0", "package_usd": "10.00"}
            for p in ("PS", "XBOX", "PC")}}
        page_quote["evidence"]["offers"] = {p: {
            "Lootbar": {"usd_price": "10.50", "base_k": "100", "bonus_k": "5"}}
            for p in ("PS", "XBOX", "PC")}
        row = page_quote["result"]["rows"][0]
        row.update(cost_cny="0.50", pricing_basis="page_total_100k",
                   target_page_usd="9.25", quote_manual=False)
        self.assertEqual(check_write(configured(), page_quote, ["PS"], automatic=True), [])
        row["proposal"] = "0.0972"
        row["target_page_usd"] = "9.72"
        with self.assertRaisesRegex(ValueError, "automatic_tier_rule"):
            check_write(configured(), page_quote, ["PS"], automatic=True)

    def test_write_gate_missing_bonus_means_zero(self):
        page_quote = quote({p: "0.0925" for p in ("PS", "XBOX", "PC")})
        page_quote["evidence"]["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": "0", "package_usd": "10.00"}
            for p in ("PS", "XBOX", "PC")}}
        page_quote["evidence"]["offers"] = {p: {
            "Lootbar": {"usd_price": "10.00", "base_k": "100"}}
            for p in ("PS", "XBOX", "PC")}
        page_quote["result"]["rows"][0].update(
            cost_cny="0.50", pricing_basis="page_total_100k",
            target_page_usd="9.25", quote_manual=False)
        self.assertEqual(check_write(configured(), page_quote, ["PS"], automatic=True), [])

    def test_below_twenty_follows_lootbar_but_stops_at_configured_floor(self):
        page_quote = quote({p: "0.0948" for p in ("PS", "XBOX", "PC")})
        page_quote["evidence"]["storefront"] = {"rows": {
            p: {"base_k": "100", "bonus_k": "5", "package_usd": "10.00"}
            for p in ("PS", "XBOX", "PC")}}
        page_quote["evidence"]["offers"] = {p: {
            "Lootbar": {"usd_price": "9.00", "base_k": "100", "bonus_k": "5"}}
            for p in ("PS", "XBOX", "PC")}
        row = page_quote["result"]["rows"][0]
        row.update(cost_cny="0.65", pricing_basis="page_total_100k",
                   target_page_usd="9.48", quote_manual=False)
        self.assertEqual(check_write(configured(), page_quote, ["PS"], automatic=True), [])
        page_quote["evidence"]["offers"]["PS"]["Lootbar"]["usd_price"] = "11.00"
        row["proposal"] = "0.1048"
        row["target_page_usd"] = "10.48"
        self.assertEqual(check_write(configured(), page_quote, ["PS"], automatic=True), [])

    def test_low_margin_auto_block_manual_reason_and_confirmation(self):
        prices = {"PS": "0.13", "XBOX": "0.15", "PC": "0.15"}
        with self.assertRaisesRegex(ValueError, "automatic_margin_floor:PS"):
            check_write(configured(), quote(prices), ["PS"], automatic=True)
        with self.assertRaisesRegex(ValueError, "manual_margin_confirmation_required"):
            check_write(configured("manual"), quote(prices), ["PS"], confirmed=["PS"])
        self.assertEqual(check_write(configured("manual"), quote(prices), ["PS"],
                                     confirmed=["PS"], reason="Reviewed by operator"), ["PS"])

    def test_quote_revision_and_scope_fail_closed(self):
        policy = configured()
        previous = quote()
        previous["automation_policy_revision"] = 0
        with self.assertRaisesRegex(ValueError, "automation_policy_changed_since_quote"):
            check_write(policy, previous, ["PS"], automatic=True)
        policy["platforms"] = ["PS"]
        with self.assertRaisesRegex(ValueError, "automation_platform_disabled"):
            check_write(policy, quote(), ["PC"], automatic=True)

    def test_all_platform_switches_can_be_off(self):
        policy = configured()
        policy["platforms"] = []
        self.assertEqual(normalize_policy({key: value for key, value in policy.items()
                                           if key not in {"revision", "updated_at", "updated_by"}})["platforms"], [])
        self.assertEqual(due(policy, None), "platforms_off")
        with self.assertRaisesRegex(ValueError, "automation_platform_disabled"):
            check_write(policy, quote(), ["PS"], automatic=True)

    def test_schedule_pauses_after_failure_until_config_revision_changes(self):
        policy = configured()
        now = datetime.now(timezone.utc)
        last = {"created_at": (now - timedelta(hours=4)).isoformat(),
                "completed_at": (now - timedelta(hours=3)).isoformat(),
                "status": "failed", "request": {"policy_revision": 1}}
        self.assertEqual(due(policy, last, now), "paused_after_failure")
        policy["revision"] = 2
        self.assertEqual(due(policy, last, now), "due")
        last["request"]["policy_revision"] = 2
        last["status"] = "ready"
        self.assertEqual(due(policy, last, now), "due")
        policy["system_enabled"] = False
        self.assertEqual(due(policy, last, now), "system_off")
        policy["system_enabled"] = True
        policy["mode"] = "manual"
        self.assertEqual(due(policy, last, now), "manual_mode")

    def test_schedule_uses_configured_minutes(self):
        now = datetime.now(timezone.utc)
        policy = configured()
        last = {"created_at": (now - timedelta(minutes=2)).isoformat(),
                "completed_at": (now - timedelta(seconds=90)).isoformat(),
                "status": "ready", "request": {"policy_revision": 1}}
        policy["interval_minutes"] = 1
        self.assertEqual(due(policy, last, now), "due")
        policy["interval_minutes"] = 2
        self.assertEqual(due(policy, last, now), "waiting")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""捆绑包定价工具离线测试（纯标准库，零网络）。

公式基准 = 腾讯文档《捆绑包》prices 表 ManCity11-PlayerBundle 行（2026-10-13 逆向）：
  球员实际售价 = 金币K × 单价 × 1.1；划线价 = 实际 / 0.9
  包售价 = Σ划线 × 0.8 = 20.77；包原价 = 售价 / 0.7 = 29.67
  PC 同链路（K=0.0979）→ 售价 13.74 / 原价 19.62
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pack_bundles_server.py"
spec = importlib.util.spec_from_file_location("pack_bundles_server", str(SRC))
mod = importlib.util.module_from_spec(spec)
sys.modules["pack_bundles_server"] = mod
spec.loader.exec_module(mod)


PS_COINS = [70000, 30000, 19000, 10000, 18000, 7000, 5500, 2500, 3000, 1000, 3000]
PC_COINS = [52000, 28000, 14000, 12000, 15000, 7500, 5000, 3000, 3000, 1000, 3000]
FUTBIN_IDS = [1, 67, 256, 594, 436, 224, 21975, 223, 439, 21982, 438]

MARKUPS = {
    "markup_player_actual": Decimal("1.1"),
    "player_strike_divisor": Decimal("0.9"),
    "bundle_sale_factor": Decimal("0.8"),
    "bundle_orig_divisor": Decimal("0.7"),
}


def make_players():
    players = {}
    for fid, ps, pc in zip(FUTBIN_IDS, PS_COINS, PC_COINS):
        players[fid] = {"futbin_id": fid, "name": "P%d" % fid, "rating": 85,
                        "position": "CB", "version": "Gold Rare", "image": "",
                        "ps_price": ps, "pc_price": pc, "xbox_price": None}
    return players


RATES = {"PS": {"usd_per_k": "0.1257"}, "XBOX": {"usd_per_k": "0.1257"},
         "PC": {"usd_per_k": "0.0979"}}


class FormulaTests(unittest.TestCase):
    def test_sale_factor_targets_one_percent_without_changing_display_ratio(self):
        markups = {**MARKUPS, "bundle_sale_factor": Decimal("0.891")}
        bundle = {"id": "mancity11", "players": [{"futbin_id": fid} for fid in FUTBIN_IDS]}
        out = mod.compute_bundle(bundle, make_players(), RATES, markups)
        for platform in ("ps", "xbox", "pc"):
            price = out[platform]
            self.assertEqual(price["discount_vs_actual_pct"], -1.0)
            self.assertAlmostEqual(price["orig"] * 0.7, price["sale"], delta=0.01)

    def test_three_platform_rates_have_separate_quotes_and_shared_market_provenance(self):
        rates = json.loads(json.dumps(RATES))
        rates['XBOX']['usd_per_k'] = '0.0900'
        bundle = {'id': 'split', 'players': [{'futbin_id': 1}]}
        out = mod.compute_bundle(bundle, make_players(), rates, MARKUPS)
        self.assertIn('xbox', out)
        self.assertNotEqual(out['ps']['orig'], out['xbox']['orig'])
        row = out['players'][0]
        self.assertEqual(row['xbox_coins'], row['ps_coins'])
        self.assertEqual(row['market_references']['XBOX'], {
            'field': 'ps_price', 'observed_platform': 'PS',
            'market': 'shared_console', 'shared_reference': True})
        self.assertEqual(out['xbox']['rate_platform'], 'XBOX')
        self.assertEqual(out['xbox']['usd_per_k'], '0.0900')

    def test_missing_xbox_dollar_rate_never_inherits_ps(self):
        rates = json.loads(json.dumps(RATES)); rates.pop('XBOX')
        out = mod.compute_bundle({'players': [{'futbin_id': 1}]}, make_players(), rates, MARKUPS)
        self.assertIsNotNone(out['ps'])
        self.assertIn('xbox', out)
        self.assertIsNone(out['xbox'])
        self.assertTrue(any('XBOX' in item for item in out['warnings']))

    def test_explicit_xbox_market_observation_retains_its_own_quantity(self):
        players = make_players(); players[1]['xbox_price'] = 90000
        out = mod.compute_bundle({'players': [{'futbin_id': 1}]}, players, RATES, MARKUPS)
        self.assertIn('xbox_coins', out['players'][0])
        self.assertEqual(out['players'][0]['xbox_coins'], 90000)
        self.assertEqual(out['players'][0]['market_references']['XBOX']['observed_platform'], 'XBOX')
        self.assertFalse(out['players'][0]['market_references']['XBOX']['shared_reference'])

    def test_player_ps_price_matches_sheet(self):
        """Haaland：70K × 0.1257 × 1.1 = 9.68；划线 10.75（表格 L2=10.75 / M2=9.68）"""
        d = mod.Decimal
        actual = d(70000) / 1000 * d("0.1257") * d("1.1")
        self.assertEqual(mod.money2(actual), d("9.68"))
        self.assertEqual(mod.money2(actual / d("0.9")), d("10.75"))

    def test_bundle_mancity_totals_match_sheet(self):
        bundle = {"id": "mancity11", "title": "ManCity11-PlayerBundle",
                  "players": [{"futbin_id": f, "position": "CB"} for f in FUTBIN_IDS]}
        out = mod.compute_bundle(bundle, make_players(), RATES, MARKUPS)
        self.assertAlmostEqual(out["ps"]["sale"], 20.77, places=2)
        self.assertAlmostEqual(out["ps"]["orig"], 29.67, places=2)
        self.assertAlmostEqual(out["pc"]["sale"], 13.74, places=2)
        self.assertAlmostEqual(out["pc"]["orig"], 19.62, places=2)
        # 球员行抽查：哈兰德 PS 划线 10.75 / 实际 9.68；PC 实际 52×0.0979×1.1=5.60
        h = out["players"][0]
        self.assertEqual(h["ps_strike"], 10.75)
        self.assertEqual(h["ps_actual"], 9.68)
        self.assertEqual(h["pc_actual"], 5.6)

    def test_missing_player_becomes_warning_not_crash(self):
        players = make_players()
        del players[21975]
        bundle = {"id": "x", "title": "X", "players": [
            {"futbin_id": 21975, "position": "CM"},
            {"futbin_id": 1, "position": "ST"},
                                        {"futbin_id": 2, "position": "CB"}]}
        out = mod.compute_bundle(bundle, players, RATES, MARKUPS)
        self.assertEqual(out["players"][0]["status"], "not_found")
        self.assertTrue(any("未收录" in w for w in out["warnings"]))
        self.assertIsNotNone(out["ps"])  # 其余球员仍可汇总

    def test_null_price_excluded(self):
        players = make_players()
        players[1]["ps_price"] = None
        players[1]["xbox_price"] = None
        bundle = {"id": "x", "title": "X",
                  "players": [{"futbin_id": 1, "position": "ST"},
                                        {"futbin_id": 2, "position": "CB"}]}
        out = mod.compute_bundle(bundle, players, RATES, MARKUPS)
        # PS 缺价只影响 PS 汇总；PC 仍在 → 行状态 ok，PS 汇总为 None
        self.assertIsNone(out["ps"])
        self.assertIsNotNone(out["pc"])
        self.assertEqual(out["players"][0]["status"], "ok")
        self.assertTrue(any("PS 价缺失" in w for w in out["warnings"]))

    def test_xbox_fallback_uses_ps_price(self):
        players = make_players()
        players[1]["ps_price"] = None
        players[1]["xbox_price"] = 12345
        bundle = {"id": "x", "title": "X",
                  "players": [{"futbin_id": 1, "position": "ST"},
                                        {"futbin_id": 2, "position": "CB"}]}
        out = mod.compute_bundle(bundle, players, RATES, MARKUPS)
        self.assertEqual(out["players"][0]["ps_coins"], 12345)


class ValidationTests(unittest.TestCase):
    def test_bundles_dup_id_rejected(self):
        with self.assertRaises(ValueError):
            mod.validate_bundles([
                {"id": "a", "title": "A", "players": [{"futbin_id": 1}]},
                {"id": "a", "title": "B", "players": [{"futbin_id": 2}]}])

    def test_bundles_bad_futbin_id(self):
        with self.assertRaises(ValueError):
            mod.validate_bundles([{"id": "a", "title": "A",
                                   "players": [{"futbin_id": "abc"}]}])

    def test_bundles_dup_player_rejected(self):
        with self.assertRaises(ValueError):
            mod.validate_bundles([{"id": "a", "title": "A",
                                   "players": [{"futbin_id": 1}, {"futbin_id": 1}]}])

    def test_settings_interval_range(self):
        base = dict(mod.DEFAULT_SETTINGS)
        out = mod.validate_settings({"interval_hours": 3}, base)
        self.assertEqual(out["interval_hours"], 3.0)
        with self.assertRaises(ValueError):
            mod.validate_settings({"interval_hours": 999}, base)

    def test_settings_markup_must_be_positive(self):
        base = dict(mod.DEFAULT_SETTINGS)
        with self.assertRaises(ValueError):
            mod.validate_settings({"markup_player_actual": "0"}, base)

    def test_futbin_base_whitelist(self):
        base = dict(mod.DEFAULT_SETTINGS)
        out = mod.validate_settings({"futbin_base": "http://139.28.18.234:8001"}, base)
        self.assertEqual(out["futbin_base"], "http://139.28.18.234:8001")
        with self.assertRaises(ValueError):
            mod.validate_settings({"futbin_base": "http://evil.host/x"}, base)


class StoreTests(unittest.TestCase):
    def test_state_identifies_loaded_three_platform_contract_without_triggering_a_write(self):
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            self.assertEqual(store.compute_state().get('price_scope_contract'), 'fc27_three_platform_v1')

    def test_large_package_gifts_are_not_spread_into_purchase_base_reference(self):
        """大档赠送是让利，引用购买基价时不能拿交付量摊薄；不增加硬线档位。"""
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "storefront.json"
            sf.write_text(json.dumps({"rows": {
                "PS": {"package_usd": "125.70", "base_k": "1000", "bonus_k": "30",
                       "usd_per_k": "0.122039", "status": "ok"},
                "XBOX": {"package_usd": "125.70", "base_k": "1000", "bonus_k": "30",
                         "usd_per_k": "0.122039", "status": "ok"},
                "PC": {"package_usd": "97.90", "base_k": "1000", "bonus_k": "30",
                       "usd_per_k": "0.095049", "status": "ok"}}}), "utf-8")
            store = mod.Store(Path(td))
            store.config["settings"]["storefront_path"] = str(sf)
            rates, _ = store.get_rates()
            self.assertEqual(rates["PS"]["usd_per_k"], "0.125700")
            self.assertEqual(rates["PC"]["usd_per_k"], "0.097900")
            self.assertEqual(rates["PS"]["basis"], "package/base_k")
            self.assertNotEqual(rates["PS"]["usd_per_k"], "0.122039")

    def test_legacy_delivered_unit_without_purchase_base_is_diagnostic_only(self):
        """缺购买数量证明的旧含赠单价不能冒充当前购买基价。"""
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "storefront.json"
            sf.write_text(json.dumps({"rows": {
                "PS": {"usd_per_k": "0.119714", "status": "ok"}}}), "utf-8")
            store = mod.Store(Path(td))
            store.config["settings"]["storefront_path"] = str(sf)
            rates, _ = store.get_rates()
            self.assertIsNone(rates["PS"]["usd_per_k"])
            self.assertEqual(rates["PS"]["observed_usd_per_k"], "0.119714")
            self.assertEqual(rates["PS"]["basis"], "purchase_base_unverified")
            (Path(td)/'order_rates.json').write_text(json.dumps({'XBOX':{
                'usd_per_k':'0.119714','basis':'storefront_usd_per_k(includes_bonus)'}}))
            cached=store.cached_rates()
            self.assertIsNone(cached['XBOX']['usd_per_k'])
            self.assertEqual(cached['XBOX']['observed_usd_per_k'],'0.119714')

    def test_store_roundtrip_and_revision(self):
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            rev0 = store.config["revision"]
            with self.assertRaises(ValueError):
                store.save_config({"expected_revision": 999,
                                   "bundles": store.config["bundles"]})
            rev1 = store.save_config({
                "expected_revision": rev0,
                "settings": {"interval_hours": 2},
                "bundles": [{"id": "t1", "title": "T1",
                             "players": [{"futbin_id": 1, "position": "ST"},
                                        {"futbin_id": 2, "position": "CB"}]}]})
            self.assertEqual(rev1, rev0 + 1)
            self.assertEqual(store.settings()["interval_hours"], 2.0)
            # 重开一个实例验证落盘
            store2 = mod.Store(Path(td))
            self.assertEqual(store2.config["bundles"][0]["id"], "t1")

    def test_default_config_preloaded_two_bundles(self):
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            ids = [b["id"] for b in store.config["bundles"]]
            self.assertEqual(ids, ["mancity11", "paris11"])
            self.assertEqual(len(store.config["bundles"][0]["players"]), 11)

    def test_compute_state_with_real_shape(self):
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            store.players = make_players()
            store.rates = json.loads(json.dumps(RATES))
            state = store.compute_state()
            self.assertTrue(state["pricing_formula_ok"])
            out = {b["id"]: b for b in state["bundles"]}
            self.assertAlmostEqual(out["mancity11"]["ps"]["sale"], 20.77, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

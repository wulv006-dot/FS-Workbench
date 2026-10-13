#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二期写价链路离线测试（假 transport 零网络）。"""
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

RATES = {"PS": {"usd_per_k": "0.125700", "basis": "order_b2c"},
         "XBOX": {"usd_per_k": "0.125700", "basis": "order_b2c"},
         "PC": {"usd_per_k": "0.099400", "basis": "order_b2c"}}


def make_players():
    return {1: {"futbin_id": 1, "name": "P1", "rating": 90, "position": "ST",
                "version": "", "ps_price": 100000, "pc_price": 80000,
                "xbox_price": None, "image": ""}}


class FakeWriter:
    """替身：记录调用，按脚本返回。"""

    def __init__(self, rows=None, fail_ids=()):
        self.rows = rows or {}
        self.fail_ids = set(fail_ids)
        self.calls = []

    def write_price(self, pid, unit, before_dir, dry_run,
                    *, expect_platform=None, expect_title=None):
        self.calls.append((pid, str(unit), dry_run))
        if pid in self.fail_ids:
            raise RuntimeError("boom-%s" % pid)
        row = self.rows.get(pid) or {"unit_price": "0", "price": "0",
                                     "discount": "70", "title": "T"}
        cur_u, cur_p = Decimal(row["unit_price"]), Decimal(row["price"])
        disc = Decimal(row["discount"])
        price = (unit * disc / 100).quantize(Decimal("0.001"),
                                             rounding="ROUND_HALF_UP")
        if abs(cur_u - unit) < mod.MIN_DELTA and abs(cur_p - price) < mod.MIN_DELTA:
            return {"product_id": pid, "action": "skip",
                    "discount": str(disc),
                    "target": {"unit_price": str(unit), "price": str(price)}}
        if dry_run:
            return {"product_id": pid, "action": "planned",
                    "target": {"unit_price": str(unit), "price": str(price)}}
        return {"product_id": pid, "action": "written",
                "target": {"unit_price": str(unit), "price": str(price)}}


class CodexReviewGuards(unittest.TestCase):
    """Codex review 各条防护的回归（2026-10-13）。"""

    def test_bool_gate_rejects_string(self):
        """#16: bool("false") 恒 True → 只收真 JSON bool"""
        base = dict(mod.DEFAULT_SETTINGS)
        for key in ("write_enabled", "write_dry_run", "write_auto"):
            with self.assertRaises(ValueError):
                mod.validate_settings({key: "false"}, base)
        out = mod.validate_settings({"write_auto": False}, base)
        self.assertIs(out["write_auto"], False)

    def test_sub_hour_interval_not_clamped(self):
        """#8: 0.5 小时必须真的生效，不能静默抬成 1 小时"""
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            store.config["settings"]["interval_hours"] = 0.5
            self.assertEqual(store.interval_seconds(), 1800.0)
            store.config["settings"]["interval_hours"] = 0.05  # 下限 0.1
            self.assertEqual(store.interval_seconds(), 360.0)

    def test_migration_keeps_intentionally_empty_products(self):
        """#9: 显式清空的 products:{} 不能被重启重填回默认 ID"""
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            rev = store.config["revision"]
            store.save_config({"expected_revision": rev, "bundles": [
                {"id": "mancity11", "title": "ManCity11-PlayerBundle",
                 "products": {}, "players": [{"futbin_id": 1, "position": "ST"}]}]})
            store2 = mod.Store(Path(td))   # 模拟重启
            b = store2.config["bundles"][0]
            self.assertEqual(b.get("products"), {})

    def test_state_returns_products_binding(self):
        """#6: /api/state 必须回传 products，否则前端保存会清空绑定"""
        with tempfile.TemporaryDirectory() as td:
            store = mod.Store(Path(td))
            store.players = make_players()
            store.rates = json.loads(json.dumps(RATES))
            state = store.compute_state()
            for b in state["bundles"]:
                self.assertIn("products", b)
                self.assertTrue(b["products"].get("ps"))

    def test_request_cannot_loosen_dry_run(self):
        """#4: 请求体 dry_run=false 不能放宽配置的 dry_run=true"""
        orig = mod.AdminWriter
        self.addCleanup(lambda: setattr(mod, "AdminWriter", orig))
        store = self._store()
        fake = FakeWriter()
        mod.AdminWriter = lambda cred: fake
        entry = mod.execute_write(store, dry_run=False, actor="test")  # 试图放宽
        self.assertTrue(entry["dry_run"])          # 仍是试运行
        self.assertTrue(all(c[2] is True for c in fake.calls))

    def test_incomplete_platform_skipped(self):
        """#2: 球员缺价 → 该平台拒绝写价（不得按少算的总价写）"""
        orig = mod.AdminWriter
        self.addCleanup(lambda: setattr(mod, "AdminWriter", orig))
        store = self._store()
        rev = store.config["revision"]
        store.save_config({"expected_revision": rev, "bundles": [
            {"id": "b1", "title": "B1", "products": {"ps": 111},
             "players": [{"futbin_id": 1, "position": "ST"},
                         {"futbin_id": 999999, "position": "ST"}]}]})
        fake = FakeWriter()
        mod.AdminWriter = lambda cred: fake
        entry = mod.execute_write(store, actor="test")
        recs = {r["product_id"]: r for r in entry["results"]}
        self.assertEqual(recs[111]["action"], "skipped_incomplete")
        self.assertEqual(fake.calls, [])   # 根本没去读/写后台

    def test_identity_rejects_wrong_product(self):
        """#1: 产品行 gid/cid/site_id/aid/标题 不匹配 → fail closed 不写"""
        w = mod.AdminWriter("/nonexistent-cred")

        class FakeApi:
            def __init__(self, row):
                self.row = row
                self.posts = []

            def _json(self, method, path, **kw):
                if method == "GET":
                    return {"data": {"row": dict(self.row)}}
                self.posts.append((method, path, kw))
                return {"code": 1}

        good = {"id": 111, "gid": 1327, "cid": 10255, "site_id": 0, "aid": 21587,
                "title": "B1", "discount": 70, "unit_price": "0", "price": "0"}
        bad = dict(good, gid=999)
        with tempfile.TemporaryDirectory() as td:
            bd = Path(td)
            api = FakeApi(bad)
            w._client = api
            rec = w.write_price(111, mod.Decimal("10"), bd, False,
                                expect_platform="ps", expect_title="B1")
            self.assertEqual(rec["action"], "rejected_identity")
            self.assertEqual(api.posts, [])          # 绝不发生写
            api2 = FakeApi(dict(good, aid=21589))    # PS 槽位填了 PC 的 aid
            w._client = api2
            rec2 = w.write_price(111, mod.Decimal("10"), bd, False,
                                 expect_platform="ps", expect_title="B1")
            self.assertEqual(rec2["action"], "rejected_identity")

    def test_order_b2c_rejects_foreign_gid_rows(self):
        """#7: 订单页面返回别的游戏行（gid 不符）→ 拒绝覆盖单价"""
        import sys as _sys
        import types

        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "sf.json"
            sf.write_text(json.dumps({"rows": {
                "PS": {"package_usd": "12.57", "base_k": "100", "status": "ok"}}}),
                "utf-8")
            cred = Path(td) / "cred.json"
            cred.write_text(json.dumps({"P2PAH_USERNAME": "u",
                                        "P2PAH_PASSWORD": "p"}), "utf-8")
            store = mod.Store(Path(td))
            store.config["settings"].update({
                "storefront_path": str(sf), "cred_path": str(cred),
                "order_price_enabled": True, "order_gid": 1322})
            fake_mod = types.ModuleType("p2pah_price")
            fake_mod.fetch_rows = lambda **kw: {"ok": True, "rows": [
                {"area": "PS", "gid": 922, "b2c": "0.0429"},   # 别的游戏（MLB）
                {"area": "XBOX", "gid": 922, "b2c": "0.0429"}]}
            _sys.modules["p2pah_price"] = fake_mod
            self.addCleanup(lambda: _sys.modules.pop("p2pah_price", None))
            rates, _ = store.get_rates()
            before = json.loads(json.dumps(rates))
            summary = {"errors": []}
            out = store._overlay_order_b2c(rates, summary)
            self.assertEqual(out, before)                 # 单价未被覆盖
            self.assertTrue(any("gid_mismatch" in e for e in summary["errors"]))

    def _store(self, **settings_over):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        store = mod.Store(Path(td.name))
        store.players = make_players()
        store.rates = json.loads(json.dumps(RATES))
        settings = dict(store.settings())
        settings.update({"write_enabled": True, "write_dry_run": True,
                         "write_auto": False})
        settings.update(settings_over)
        store.save_config({"expected_revision": store.config["revision"],
                           "settings": settings,
                           "bundles": [{"id": "b1", "title": "B1",
                                        "products": {"ps": 111, "xbox": 222,
                                                     "pc": 333},
                                        "players": [{"futbin_id": 1,
                                                     "position": "ST"}]}]})
        return store


class WriteFlowTests(unittest.TestCase):
    def setUp(self):
        self._orig = mod.AdminWriter

    def tearDown(self):
        mod.AdminWriter = self._orig

    def _store(self, **settings_over):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        store = mod.Store(Path(td.name))
        store.players = make_players()
        store.rates = json.loads(json.dumps(RATES))
        rev = store.config["revision"]
        settings = dict(store.settings())
        settings.update({"write_enabled": True, "write_dry_run": True,
                         "write_auto": False})
        settings.update(settings_over)
        store.save_config({"expected_revision": rev,
                           "settings": settings,
                           "bundles": [{"id": "b1", "title": "B1",
                                        "products": {"ps": 111, "xbox": 222,
                                                     "pc": 333},
                                        "players": [{"futbin_id": 1,
                                                     "position": "ST"}]}]})
        return store

    def test_dry_run_plans_without_writing(self):
        store = self._store()
        fake = FakeWriter(rows={"111": {"unit_price": "0", "price": "0",
                                        "discount": "70"}})
        mod.AdminWriter = lambda cred: fake
        entry = mod.execute_write(store, actor="test")  # dry_run 默认 True
        self.assertTrue(entry["dry_run"])
        actions = {r["product_id"]: r["action"] for r in entry["results"]}
        self.assertEqual(actions[111], "planned")
        self.assertIn(111, [c[0] for c in fake.calls])
        # 111（PS 槽位）目标 unit = 打包页面原价：
        # 100K×0.1257×1.1=13.827（球员实际）→ ÷0.9=15.363（划线）→ ×0.8/0.7=17.56（包原价）
        unit = Decimal(fake.calls[0][1])
        self.assertEqual(unit, Decimal("17.56"))
        # PC 槽位：80K×0.0994×1.1÷0.9×0.8÷0.7 = 11.11
        pc_unit = Decimal([c for c in fake.calls if c[0] == 333][0][1])
        self.assertEqual(pc_unit, Decimal("11.11"))

    def test_disabled_gate_blocks(self):
        store = self._store(write_enabled=False)
        with self.assertRaises(ValueError):
            mod.execute_write(store, actor="test")

    def test_xbox_shares_ps_target(self):
        store = self._store()
        fake = FakeWriter()
        mod.AdminWriter = lambda cred: fake
        entry = mod.execute_write(store, actor="test")
        by_plat = {r["platform"]: r for r in entry["results"]}
        self.assertEqual(by_plat["ps"]["target"]["unit_price"],
                         by_plat["xbox"]["target"]["unit_price"])
        self.assertNotEqual(by_plat["pc"]["target"]["unit_price"],
                            by_plat["ps"]["target"]["unit_price"])

    def test_write_log_persisted_and_capped(self):
        store = self._store()
        mod.AdminWriter = lambda cred: FakeWriter()
        for _ in range(3):
            mod.execute_write(store, actor="test")
        log = store.write_log()
        self.assertEqual(len(log), 3)
        self.assertEqual(log[-1]["actor"], "test")

    def test_failure_recorded_needs_review_not_raised(self):
        store = self._store()
        mod.AdminWriter = lambda cred: FakeWriter(fail_ids={111})
        entry = mod.execute_write(store, actor="test")
        rec = {r["product_id"]: r for r in entry["results"]}[111]
        self.assertEqual(rec["action"], "needs_review")

    def test_settings_write_flags_validation(self):
        base = dict(mod.DEFAULT_SETTINGS)
        out = mod.validate_settings({"write_enabled": True, "write_auto": True,
                                     "order_gid": 1322}, base)
        self.assertTrue(out["write_enabled"])
        self.assertEqual(out["order_gid"], 1322)
        with self.assertRaises(ValueError):
            mod.validate_settings({"order_gid": "abc"}, base)

    def test_bundle_products_validation(self):
        out = mod.validate_bundles([{"id": "a", "title": "A",
                                     "products": {"ps": 1, "xbox": "", "pc": 3},
                                     "players": [{"futbin_id": 5}]}])
        self.assertEqual(out[0]["products"], {"ps": 1, "pc": 3})
        with self.assertRaises(ValueError):
            mod.validate_bundles([{"id": "a", "title": "A",
                                   "products": {"ps": -1},
                                   "players": [{"futbin_id": 5}]}])


if __name__ == "__main__":
    unittest.main(verbosity=2)

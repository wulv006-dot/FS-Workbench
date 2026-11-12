"""Isolated configuration API tests. All data is fabricated in TemporaryDirectory."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from support import APP
from flask import Flask
import console_config as config_api


class ConfigurationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="console-config-test-")
        self.root = Path(self.temp.name)
        self.common = {
            "汇率": {"USDCNY": 6.65},
            "跟价": {"跟随策略": {"让价百分比": 2, "最低毛利率": .15}},
            "金币": {"定价策略": {"模式": "dd373_only", "利润率": .29, "利润率下限": .25}},
            "credentials": {"token": "FABRICATED_SECRET_NEVER_RETURN"},
        }
        self.wow = {"启用": True, "参数": {"成本采样金": 150, "薄区阈值金": 50,
                                                "常规利润率": .25, "薄区利润率": .30,
                                                "稀缺利润率": .35},
                    "private": "FABRICATED_WOW_SECRET"}
        self.aa = {"启用": True, "参数": {"常规利润率": .30, "薄区利润率": .50}}
        for name, value in (("config.json", self.common), ("wow_gold_config.json", self.wow),
                            ("aa_gold_config.json", self.aa)):
            (self.root / name).write_bytes(config_api._json_bytes(value))
        self.app = Flask(__name__)
        self.store = config_api.register_config(self.app, self.root, threading.RLock())
        self.client = self.app.test_client()
        self.headers = {"Origin": "http://localhost", "X-Authenticated-User": "test-operator"}

    def tearDown(self):
        self.temp.cleanup()

    def version(self, game="wow"):
        return self.client.get(f"/api/games/{game}/config").get_json()["data"]["version"]

    def post(self, fields, game="wow", version=None, headers=None):
        return self.client.post(f"/api/games/{game}/config", json={"version": version or self.version(game),
                                "patch": fields}, headers=self.headers if headers is None else headers)

    def read(self, name="wow_gold_config.json"):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def save(self, fields, game="wow"):
        response = self.post(fields, game)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_read_is_whitelisted_and_does_not_change_config(self):
        before = {p.name: p.read_bytes() for p in self.root.glob("*.json")}
        response = self.client.get("/api/games/wow/config")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("FABRICATED", response.get_data(as_text=True))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob("*.json")})
        self.assertFalse(self.store.history_dir.exists())

    def test_save_only_target_file_with_readback_and_safe_history(self):
        original_common = (self.root / "config.json").read_bytes()
        original_aa = (self.root / "aa_gold_config.json").read_bytes()
        result = self.save({"margin_full": .28})
        self.assertTrue(result["next_round"])
        self.assertEqual(self.read()["参数"]["常规利润率"], .28)
        self.assertEqual(self.read()["private"], "FABRICATED_WOW_SECRET")
        self.assertEqual((self.root / "config.json").read_bytes(), original_common)
        self.assertEqual((self.root / "aa_gold_config.json").read_bytes(), original_aa)
        history = self.client.get("/api/config/history?game=wow").get_json()["items"]
        self.assertEqual(history[0]["actor"], "test-operator")
        self.assertEqual(history[0]["changes"][0]["scale"], 100)
        for history_path in self.store.history_dir.glob("*.json"):
            self.assertNotIn("FABRICATED", history_path.read_text(encoding="utf-8"))

    def test_noop_does_not_create_history_or_rewrite_bytes(self):
        original = (self.root / "wow_gold_config.json").read_bytes()
        result = self.save({"margin_full": .25, "quote_ttl": 1200})
        self.assertFalse(result["next_round"])
        self.assertIsNone(result["history_id"])
        self.assertEqual(original, (self.root / "wow_gold_config.json").read_bytes())
        self.assertFalse(self.store.history_dir.exists())

    def test_numeric_and_unknown_field_rejections_are_atomic(self):
        original = (self.root / "wow_gold_config.json").read_bytes()
        for fields in ({"margin_full": True}, {"margin_full": "0.28"}, {"margin_full": 1},
                       {"margin_full": -1}, {"quote_ttl": 61.5}, {"private": "oops"},
                       {"margin_full": .28, "scarce_boundary": 200}):
            with self.subTest(fields=fields):
                self.assertEqual(self.post(fields).status_code, 400)
                self.assertEqual(original, (self.root / "wow_gold_config.json").read_bytes())
        for value in ("NaN", "Infinity", "-Infinity"):
            body = '{"version":"' + self.version() + '","patch":{"margin_full":' + value + '}}'
            response = self.client.post("/api/games/wow/config", data=body,
                                        content_type="application/json", headers=self.headers)
            self.assertEqual(response.status_code, 400)

    def test_missing_or_stale_version_fails(self):
        stale = self.version()
        self.save({"margin_full": .28})
        response = self.post({"margin_thin": .32}, version=stale)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "version_conflict")
        self.assertEqual(self.read()["参数"]["薄区利润率"], .30)
        response = self.client.post("/api/games/wow/config", json={"patch": {"margin_full": .27}}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_write_requires_auth_json_and_matching_origin(self):
        before = (self.root / "wow_gold_config.json").read_bytes()
        for headers, status in (({}, 401), ({"Origin": "http://localhost"}, 401),
                                ({"X-Authenticated-User": "test"}, 403),
                                ({"X-Authenticated-User": "test", "Origin": "https://evil.example"}, 403)):
            self.assertEqual(self.post({"margin_full": .28}, headers=headers).status_code, status)
        response = self.client.post("/api/games/wow/config", data="{}", content_type="text/plain", headers=self.headers)
        self.assertEqual(response.status_code, 415)
        self.assertEqual(before, (self.root / "wow_gold_config.json").read_bytes())

    def test_forwarded_https_and_default_port_are_same_origin(self):
        headers = {"X-Authenticated-User": "test", "X-Forwarded-Proto": "https", "Origin": "https://localhost:443"}
        self.assertEqual(self.post({"margin_full": .28}, headers=headers).status_code, 200)

    def test_actor_cannot_be_forged_in_body(self):
        response = self.client.post("/api/games/wow/config", json={"version": self.version(),
                                    "patch": {"margin_full": .28}, "actor": "administrator"}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_concurrent_shared_file_conflicts_then_merges_on_refresh(self):
        version = self.version("d4")
        barrier = threading.Barrier(2)
        def save_game(game):
            with self.app.test_client() as client:
                barrier.wait()
                return game, client.post(f"/api/games/{game}/config", json={"version": version,
                    "patch": {"item_discount": 3 if game == "d4" else 4}}, headers=self.headers).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(save_game, ("d4", "poe2")))
        self.assertEqual(sorted(status for _, status in outcomes), [200, 409])
        loser = next(game for game, status in outcomes if status == 409)
        self.save({"item_discount": 3 if loser == "d4" else 4}, loser)
        doc = self.read("config.json")
        self.assertEqual(doc["跟价"]["按游戏"]["暗黑破坏神4"]["跟随策略"]["让价百分比"], 3)
        self.assertEqual(doc["跟价"]["按游戏"]["流放之路2"]["跟随策略"]["让价百分比"], 4)

    def test_restore_changes_only_involved_fields(self):
        saved = self.save({"margin_full": .28})
        self.save({"margin_thin": .32})
        response = self.client.post("/api/config/restore", json={"id": saved["history_id"],
                                    "version": self.version()}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.read()["参数"]["常规利润率"], .25)
        self.assertEqual(self.read()["参数"]["薄区利润率"], .32)
        self.assertEqual(self.store.history("wow")["items"][0]["action"], "restore")

    def test_restore_conflicts_with_later_change_on_same_field(self):
        saved = self.save({"margin_full": .28})
        self.save({"margin_full": .29})
        response = self.client.post("/api/config/restore", json={"id": saved["history_id"],
                                    "version": self.version()}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "restore_conflict")
        self.assertEqual(self.read()["参数"]["常规利润率"], .29)

    def test_restore_preserves_original_absence_and_other_overrides(self):
        saved = self.save({"item_discount": 3}, "d4")
        self.save({"item_cost_markup": .2}, "d4")
        response = self.client.post("/api/config/restore", json={"id": saved["history_id"],
                                    "version": self.version("d4")}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        overrides = self.read("config.json")["跟价"]["按游戏"]["暗黑破坏神4"]["跟随策略"]
        self.assertNotIn("让价百分比", overrides)
        self.assertEqual(overrides["最低毛利率"], .2)

    def test_journal_failure_before_save_keeps_config_unchanged(self):
        original = (self.root / "wow_gold_config.json").read_bytes()
        with patch.object(config_api, "_atomic_write", side_effect=OSError("fabricated disk failure")):
            self.assertEqual(self.post({"margin_full": .28}).status_code, 500)
        self.assertEqual((self.root / "wow_gold_config.json").read_bytes(), original)

    def test_journal_confirm_failure_rolls_back_exact_bytes(self):
        original = (self.root / "wow_gold_config.json").read_bytes()
        real_write = config_api._atomic_write
        did_fail = False
        def fail_once(path, payload, *args, **kwargs):
            nonlocal did_fail
            if Path(path).parent == self.store.history_dir and b'"state": "committed"' in payload and not did_fail:
                did_fail = True
                raise OSError("fabricated journal confirm failure")
            return real_write(path, payload, *args, **kwargs)
        with patch.object(config_api, "_atomic_write", side_effect=fail_once):
            self.assertEqual(self.post({"margin_full": .28}).status_code, 500)
        self.assertTrue(did_fail)
        self.assertEqual((self.root / "wow_gold_config.json").read_bytes(), original)
        self.assertEqual(self.store.history()["items"], [])

    def test_prepared_journal_recovery_never_replays_config(self):
        saved = self.save({"margin_full": .28})
        event_path = self.store._event_path(saved["history_id"])
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event["state"] = "prepared"
        event_path.write_bytes(config_api._json_bytes(event))
        raw = (self.root / "wow_gold_config.json").read_bytes()
        self.assertEqual(len(self.store.history()["items"]), 1)
        self.assertEqual(raw, (self.root / "wow_gold_config.json").read_bytes())
        self.assertTrue(json.loads(event_path.read_text(encoding="utf-8"))["recovered"])

    def test_history_pagination_and_id_validation(self):
        for value in (.27, .28, .29):
            self.save({"margin_full": value})
        first = self.store.history("wow", limit=2)
        second = self.store.history("wow", cursor=first["next_cursor"], limit=2)
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 1)
        self.assertEqual(len({x["id"] for x in first["items"] + second["items"]}), 3)
        response = self.client.post("/api/config/restore", json={"id": "../../config.json",
                                    "version": self.version()}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/games/not-a-game/config").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Read-only monitoring keeps last-cycle storefront evidence and its capture time."""
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc27_cloud_api as api


class MonitorApiTest(unittest.TestCase):
    def test_publication_detects_confirmed_backend_public_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "executions").mkdir()
            execution_id = "00000000-0000-4000-8000-000000000010"
            audit = {"execution_id": execution_id, "status": "CONFIRMED",
                     "sync_confirmed": True, "created_at": "2026-09-29T12:00:00+00:00",
                     "after": {"rows": [{"platform": "PS", "b2c": "0.1239"},
                                        {"platform": "XBOX", "b2c": "0.124"},
                                        {"platform": "PC", "b2c": "0.1413"}]}}
            (root / "executions" / f"{execution_id}.json").write_text(
                json.dumps(audit), encoding="utf-8")
            storefront = {"rows": {platform: {"status": "ok", "package_usd": price,
                                             "checked_at": "2026-09-29T12:01:00+00:00"}
                                    for platform, price in (("PS", "13.11"), ("XBOX", "12.40"),
                                                            ("PC", "14.13"))}}
            with patch.object(api, "ROOT", root):
                result = api.publication_view(storefront)
                self.assertEqual(result["status"], "mismatch")
                self.assertEqual(result["platforms"][0]["backend_page_usd"], "12.39")
                self.assertEqual(result["platforms"][0]["public_page_usd"], "13.11")
                storefront["rows"]["PS"]["package_usd"] = "12.39"
                self.assertEqual(api.publication_view(storefront)["status"], "matched")

    def test_last_complete_collection_survives_newer_failed_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir()
            (root / "quotes").mkdir()
            good_id = "00000000-0000-4000-8000-000000000001"
            bad_id = "00000000-0000-4000-8000-000000000002"
            good = {"run_id": good_id, "created_at": "2026-09-28T14:00:00Z", "status": "ready_for_quote",
                    "competitors": [{"platform": platform, "source": site, "status": "valid"}
                                    for platform in ("PS", "XBOX", "PC")
                                    for site in ("Lootbar", "IGGM", "U4GM", "U7Buy")],
                    "costs": [{"platform": platform, "status": "valid"}
                              for platform in ("PS", "XBOX", "PC")]}
            good_path = root / "runs" / (good_id + ".json")
            good_path.write_text(json.dumps(good), encoding="utf-8")
            failed = {"run_id": bad_id, "created_at": "2026-09-28T14:01:00Z", "status": "incomplete",
                      "reason": "collector_failed"}
            bad_path = root / "runs" / (bad_id + ".json")
            bad_path.write_text(json.dumps(failed), encoding="utf-8")
            os.utime(good_path, (1000000000, 1000000000))
            os.utime(bad_path, (1000000100, 1000000100))
            with patch.object(api, "ROOT", root):
                attempt, collection = api.latest_complete_collection()
            self.assertEqual(attempt["run_id"], bad_id)
            self.assertEqual(collection["run_id"], good_id)
            self.assertEqual(len(collection["competitors"]), 12)

    def test_monitor_route_keeps_last_cycle_price_without_three_minute_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "monitor").mkdir()
            (root / "runs").mkdir()
            (root / "jobs").mkdir()
            (root / "queue").mkdir()
            (root / "player-sync").mkdir()
            old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            snapshot = {"status": "ok", "last_attempt_at": old,
                        "rows": {"PS": {"status": "ok", "package_usd": "13", "checked_at": old}}}
            (root / "monitor/storefront.json").write_text(json.dumps(snapshot), encoding="utf-8")
            sync_id = "00000000-0000-4000-8000-000000000003"
            (root / "jobs" / f"{sync_id}.json").write_text(json.dumps({
                "job_id": sync_id, "kind": "player_sync", "status": "ready",
                "created_at": old, "request": {"config_revision": 6},
                "result": {"status": "confirmed"}}), encoding="utf-8")
            (root / "player-sync" / f"{sync_id}.json").write_text(json.dumps({
                "status": "confirmed", "model_count": 654, "verified_count": 654}), encoding="utf-8")
            with (patch.object(api, "ROOT", root), patch.object(api, "health", return_value={"api": "ok"}),
                  patch.object(api, "automation_view", return_value={}),
                  patch.object(api, "load_policy", return_value={}),
                  patch.object(api, "load_player_sync_policy", return_value={
                      "enabled": True, "revision": 6, "updated_at": old, "updated_by": "tester"})):
                server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{server.server_port}/monitor"
                    request = urllib.request.Request(url, headers={"X-Authenticated-User": "tester"})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.load(response)
                    self.assertEqual(payload["storefront"]["rows"]["PS"]["status"], "last_collected")
                    self.assertEqual(payload["storefront"]["rows"]["XBOX"]["status"], "missing")
                    self.assertEqual(payload["health"]["storefront_collection"], "linked")
                    self.assertEqual(payload["player_sync"]["last_job"]["config_revision"], 6)
                    self.assertEqual(payload["player_sync"]["last_job"]["progress"]["verified_count"], 654)
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(url, timeout=5)
                    self.assertEqual(denied.exception.code, 401)
                    denied.exception.close()
                finally:
                    server.shutdown()
                    thread.join()
                    server.server_close()


if __name__ == "__main__":
    unittest.main()

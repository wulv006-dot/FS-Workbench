"""Check that team activity combines server audits without exposing job requests."""
import json
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc27_cloud_api as api


class ActivityFeedTest(unittest.TestCase):
    def test_cloud_and_legacy_actions_are_shared_with_readback_values(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("jobs", "queue", "executions"):
                (root / name).mkdir()
            execution_id = "add461ad-984d-4a0a-bbea-777356c885d6"
            (root / "jobs" / f"{execution_id}.json").write_text(json.dumps({
                "job_id": execution_id, "kind": "restore", "actor": "other_operator",
                "status": "ready", "created_at": "2026-09-27T17:11:00+00:00",
                "completed_at": "2026-09-27T17:12:00+00:00",
                "request": {"platforms": ["XBOX"], "source_execution_id": "source-id",
                            "private_note": "must_not_appear"},
            }), encoding="utf-8")
            (root / "executions" / f"{execution_id}.json").write_text(json.dumps({
                "execution_id": execution_id, "status": "RESTORED", "stage": "readback_confirmed",
                "selected": ["XBOX"], "source_execution_id": "source-id",
                "before": {"rows": [{"platform": "XBOX", "costPrice": "0.684684", "b2c": "0.1287"}]},
                "after": {"rows": [{"platform": "XBOX", "costPrice": "0.691068", "b2c": "0.1299"}]},
                "targets": [{"platform": "XBOX", "restore_cost": "0.691068", "restore_b2c": "0.1299"}],
            }), encoding="utf-8")
            legacy = [{"id": "1", "source": "legacy", "at": "2026-09-27T17:10:00+00:00",
                       "user": "older_operator", "kind": "collect", "status": "complete", "changes": []}]
            with (patch.object(api, "ROOT", root),
                  patch.object(api.activity_log_store, "DB_PATH", root / "activity-log/events.sqlite3"),
                  patch.object(api, "legacy_activity", return_value=legacy)):
                result = api.activity_feed("current_operator", 100,
                                           now=datetime(2026, 9, 28, 10, tzinfo=timezone.utc))
            self.assertEqual(result["current_user"], "current_operator")
            self.assertEqual([item["source"] for item in result["events"]], ["cloud", "legacy"])
            cloud = result["events"][0]
            self.assertEqual(cloud["user"], "other_operator")
            self.assertEqual(cloud["status"], "RESTORED")
            self.assertEqual(cloud["changes"][0]["after_b2c"], "0.1299")
            self.assertNotIn("must_not_appear", json.dumps(result))

    def test_recent_history_and_fourteen_day_cleanup_keep_source_audits(self):
        now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original-audit.json"
            original.write_text('{"status":"CONFIRMED"}', encoding="utf-8")
            with patch.object(api.activity_log_store, "DB_PATH", root / "copy/events.sqlite3"):
                events = [
                    {"id": "recent", "source": "cloud", "at": (now - timedelta(hours=2)).isoformat()},
                    {"id": "older", "source": "cloud", "at": (now - timedelta(days=13)).isoformat()},
                    {"id": "kept", "source": "cloud", "at": (now - timedelta(days=13, minutes=1)).isoformat()},
                ]
                api.activity_log_store.capture(events, now=now)
                self.assertEqual([row["id"] for row in api.activity_log_store.query(now=now)["events"]],
                                 ["recent"])
                day=(now - timedelta(days=13)).astimezone(api.activity_log_store.BEIJING).date().isoformat()
                self.assertEqual({row["id"] for row in api.activity_log_store.query(day=day, now=now)["events"]},
                                 {"older", "kept"})
                api.activity_log_store.set_retained("cloud", "kept", True, "operator", now=now)
                later = now + timedelta(days=2)
                api.activity_log_store.capture([], now=later)
                self.assertEqual([row["id"] for row in api.activity_log_store.query(day=day, now=later)["events"]],
                                 ["kept"])
                self.assertTrue(original.exists())
                api.activity_log_store.set_retained("cloud", "kept", False, "operator", now=later)
                self.assertEqual(api.activity_log_store.query(day=day, now=later)["events"], [])

    def test_api_defaults_to_24_hours_and_requires_https_to_mark_history(self):
        now = datetime.now(timezone.utc)
        recent = {"id": "recent", "source": "cloud", "at": (now - timedelta(hours=1)).isoformat()}
        older = {"id": "older", "source": "cloud", "at": (now - timedelta(days=2)).isoformat()}
        day = (now - timedelta(days=2)).astimezone(api.activity_log_store.BEIJING).date().isoformat()
        with TemporaryDirectory() as directory:
            with (patch.object(api.activity_log_store, "DB_PATH", Path(directory) / "events.sqlite3"),
                  patch.object(api, "cloud_activity", return_value=([recent, older], 0)),
                  patch.object(api, "automation_config_activity", return_value=[]),
                  patch.object(api, "legacy_activity", return_value=[])):
                server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_port}/activity"

                def get(path):
                    request = urllib.request.Request(base + path,
                                                     headers={"X-Authenticated-User": "tester"})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return json.load(response)

                try:
                    self.assertEqual([row["id"] for row in get("?limit=200")["events"]], ["recent"])
                    self.assertEqual([row["id"] for row in get("?date=" + day)["events"]], ["older"])
                    payload = json.dumps({"source": "cloud", "id": "older", "retained": True}).encode()
                    request = urllib.request.Request(base + "/retain", data=payload, method="POST",
                        headers={"X-Authenticated-User": "tester", "Content-Type": "application/json"})
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(denied.exception.code, 503)
                    denied.exception.close()
                    request.add_header("X-Forwarded-Proto", "https")
                    with urllib.request.urlopen(request, timeout=5) as response:
                        self.assertTrue(json.load(response)["retained"])
                    self.assertTrue(get("?date=" + day)["events"][0]["retained"])
                finally:
                    server.shutdown()
                    thread.join()
                    server.server_close()


if __name__ == "__main__":
    unittest.main()

"""Focused tests for the opt-in player follow-up and its separate switch."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc27_cloud_api as api
import fc27_cloud_worker as worker
import automation_tick as tick
from test_automation_policy import configured
from datetime import datetime, timezone


class PlayerSyncFlowTest(unittest.TestCase):
    def test_disabling_players_releases_deferred_cycle_without_waiting_interval(self):
        now = datetime.now(timezone.utc)
        last = {"status": "ready", "created_at": now.isoformat(),
                "completed_at": now.isoformat(), "request": {"policy_revision": 1},
                "result": {"status": "deferred_player_sync"}}
        with patch.object(tick, "load_player_sync_policy", return_value={"enabled": False}):
            self.assertEqual(tick.due(configured(), last, now), "due")
            last["status"] = "failed"
            self.assertEqual(tick.due(configured(), last, now), "paused_after_failure")
        last["status"] = "ready"
        with patch.object(tick, "load_player_sync_policy", return_value={"enabled": True}):
            self.assertEqual(tick.due(configured(), last, now), "waiting")

    def test_disabled_players_ignore_old_jobs_and_never_call_backend(self):
        with (patch.object(tick, "load_player_sync_policy", return_value={"enabled": False}),
              patch.object(tick, "ROOT", None)):
            self.assertEqual(tick.player_sync_gate(), "ready")
        job = {"kind": "player_sync", "request": {"config_revision": 6}}
        with (patch.object(worker, "load_player_sync_policy", return_value={"enabled": False, "revision": 7}),
              patch.object(worker, "run_writer_request") as writer):
            self.assertEqual(worker.handle(job), {"status": "skipped", "reason": "player_sync_disabled"})
            writer.assert_not_called()
            self.assertEqual(worker.enqueue_player_sync({}), {"status": "disabled"})

    def test_scheduler_enqueues_read_only_cycle_even_when_player_sync_needs_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "queue").mkdir()
            fake_lock = types.SimpleNamespace(LOCK_EX=2, flock=lambda *_: None)
            with (patch.object(tick, "ROOT", root),
                  patch.object(tick, "load_policy", return_value=configured()),
                  patch.object(tick, "latest_cycle", return_value=None),
                  patch.object(tick, "player_sync_gate", side_effect=AssertionError("gate moved to worker")),
                  patch.dict(sys.modules, {"fcntl": fake_lock})):
                result = tick.tick()
            self.assertEqual(result["status"], "queued")
            queued = json.loads((root / "queue" / (result["job_id"] + ".json")).read_text())
            self.assertEqual(queued["kind"], "auto_cycle")

    def test_failed_player_sync_pauses_next_automatic_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "queue").mkdir()
            (root / "jobs").mkdir()
            path = root / "jobs" / "sync.json"
            path.write_text(json.dumps({"kind": "player_sync", "status": "failed",
                                        "created_at": "2026-09-29T03:00:00+00:00",
                                        "request": {"config_revision": 2}}))
            with (patch.object(tick, "ROOT", root),
                  patch.object(tick, "load_player_sync_policy",
                               return_value={"enabled": True, "revision": 2})):
                self.assertEqual(tick.player_sync_gate(), "needs_reconcile")
            path.write_text(json.dumps({"kind": "player_sync", "status": "ready",
                                        "created_at": "2026-09-29T03:00:00+00:00",
                                        "request": {"config_revision": 2},
                                        "result": {"status": "confirmed"}}))
            with (patch.object(tick, "ROOT", root),
                  patch.object(tick, "load_player_sync_policy",
                               return_value={"enabled": True, "revision": 2})):
                self.assertEqual(tick.player_sync_gate(), "ready")

    def test_confirmed_coin_write_without_queued_followup_pauses_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "queue").mkdir()
            (root / "jobs").mkdir()
            path = root / "jobs" / "coin.json"
            coin = {"kind": "auto_cycle", "status": "ready", "result": {"status": "confirmed"},
                    "player_sync_intent": {"enabled": True, "revision": 2},
                    "player_sync": {"status": "enqueue_failed"}}
            path.write_text(json.dumps(coin))
            with (patch.object(tick, "ROOT", root),
                  patch.object(tick, "load_player_sync_policy",
                               return_value={"enabled": True, "revision": 2})):
                self.assertEqual(tick.player_sync_gate(), "needs_reconcile")
                coin["player_sync"] = {"status": "queued", "job_id": "followup"}
                path.write_text(json.dumps(coin))
                self.assertEqual(tick.player_sync_gate(), "ready")

    def test_only_confirmed_automatic_coin_job_enqueues_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, jobs = root / "queue", root / "jobs"
            queue.mkdir()
            jobs.mkdir()
            coin = {"job_id": "ca3b324e-37d2-46d3-adfb-454013986851",
                    "kind": "auto_cycle", "result": {"status": "confirmed"}}
            with (patch.object(worker, "QUEUE", queue), patch.object(worker, "JOBS", jobs),
                  patch.object(worker.os, "chown", create=True),
                  patch.object(worker, "load_player_sync_policy",
                               return_value={"enabled": True, "revision": 3})):
                first = worker.enqueue_player_sync(coin)
                second = worker.enqueue_player_sync(coin)
                self.assertEqual(first["status"], "queued")
                self.assertEqual(second, {"status": "already_queued", "job_id": first["job_id"]})
                record = json.loads((queue / (first["job_id"] + ".json")).read_text())
                self.assertEqual(record["request"], {"coin_execution_id": coin["job_id"],
                                                     "config_revision": 3})
                with self.assertRaisesRegex(ValueError, "player_sync_coin_not_confirmed"):
                    worker.enqueue_player_sync({**coin, "result": {"status": "all_platforms_blocked"}})
                self.assertEqual(len(list(queue.glob("*.json"))), 1)

    def test_switch_is_available_to_authenticated_non_writer_only_over_https(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        def post(path, *, https):
            headers = {"Content-Type": "application/json", "X-Authenticated-User": "reader"}
            if https:
                headers["X-Forwarded-Proto"] = "https"
            body = {"enabled": True, "expected_revision": 0} if path == "/player-sync" else {}
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}",
                                             json.dumps(body).encode(), headers)
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                with error:
                    return error.code, json.load(error)

        with (patch.object(api, "WRITERS", {"writer"}),
              patch.object(api, "save_player_sync_policy", return_value={
                  "enabled": True, "revision": 1, "updated_at": None, "updated_by": "reader"}) as save,
              patch.object(api, "player_sync_view", side_effect=lambda value: value)):
            status, payload = post("/player-sync", https=False)
            self.assertEqual((status, payload["error"]), (503, "https_required_for_player_sync"))
            save.assert_not_called()
            status, payload = post("/player-sync", https=True)
            self.assertEqual((status, payload["enabled"]), (200, True))
            save.assert_called_once_with(True, "reader", 0)
            status, payload = post("/automation", https=True)
            self.assertEqual((status, payload["error"]), (403, "write_role_required"))


if __name__ == "__main__":
    unittest.main()

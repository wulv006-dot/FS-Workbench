"""Isolated regression tests for the public-page readback retry.

Loads the live-source worker with its heavy imports stubbed, then exercises
verify_public_page against synthetic storefront/quote state. No network, no
production import, no writes outside a temporary directory.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from decimal import Decimal
from unittest import mock

SOURCE = pathlib.Path(__file__).with_name("fc27_cloud_worker.py")
ROOT_PKG = SOURCE.parent


def _stub_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def load_worker(root: pathlib.Path, platforms=("PS", "XBOX", "PC")):
    """Import the worker module with service-specific imports replaced by stubs."""
    _stub_module("snapshot_layer", ROOT=root, PLATFORMS=list(platforms),
                 SITES=["Lootbar", "U4GM", "IGGM", "U7Buy"],
                 atomic_json=lambda path, payload: pathlib.Path(path).write_text(
                     json.dumps(payload), encoding="utf-8"))
    _stub_module("server_quote_job", quote_for_run=lambda *a, **k: None,
                 age_ok=lambda *a, **k: True)
    _stub_module("automation_policy", load_policy=lambda: {}, check_write=lambda *a, **k: None)
    _stub_module("player_sync_policy", load_policy=lambda: {"enabled": False, "revision": 1})
    _stub_module("automation_tick",
                 player_sync_gate=lambda *a, **k: None,
                 queue_mutation=lambda: mock.MagicMock(),
                 QueueBusy=type("QueueBusy", (Exception,), {}),
                 sync_directory=lambda *a, **k: None,
                 superseded_basis=lambda: None,
                 supersession_bytes=lambda *a, **k: b"",
                 supersession_receipt=lambda *a, **k: {},
                 utc=lambda value: value)
    _stub_module("fc27_cloud_api", writer_status=lambda *a, **k: {})
    spec = importlib.util.spec_from_file_location("worker_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["worker_under_test"] = module
    spec.loader.exec_module(module)
    return module


class ReadbackRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "monitor").mkdir()
        (self.root / "quotes").mkdir()
        (self.root / "jobs").mkdir()
        self.worker = load_worker(self.root)
        self.job = {"job_id": "cycle-1", "kind": "auto_cycle",
                    "result": {"status": "confirmed", "platforms": ["PS", "XBOX"]}}
        (self.root / "quotes" / "cycle-1.json").write_text(json.dumps({
            "result": {"rows": [
                {"platform": "PS", "target_page_usd": "13.92"},
                {"platform": "XBOX", "target_page_usd": "13.92"},
                {"platform": "PC", "target_page_usd": "12.09"},
            ]}}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, prices, run_id="cycle-1", status="ok"):
        rows = {p: {"status": "ok", "package_usd": v} for p, v in prices.items()}
        (self.root / "monitor" / "storefront.json").write_text(json.dumps({
            "status": status, "collection_run_id": run_id,
            "last_attempt_at": "2026-10-09T09:00:50+00:00", "rows": rows}),
            encoding="utf-8")

    def test_retry_converges_after_stale_first_read(self):
        """The observed production case: stale edge cache on the first read, correct later."""
        self.write_state({"PS": "13.71", "XBOX": "13.71", "PC": "12.09"})

        def fake_refresh(job):
            self.write_state({"PS": "13.92", "XBOX": "13.92", "PC": "12.09"})
            return {"status": "ok", "last_attempt_at": "2026-10-09T09:01:10+00:00"}

        with mock.patch.object(self.worker, "refresh_storefront", side_effect=fake_refresh), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep") as slept:
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["platforms"], ["PS", "XBOX"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(slept.call_count, 1)

    def test_cache_failure_preserves_sanitized_diagnostics_without_replaying_writer(self):
        responses = [{"http_status": 200, "api_code": 302, "login_route": True}]
        with mock.patch.object(self.worker, "run", return_value=(2, {
                "status": "unconfirmed", "reason": "cache_session_expired", "responses": responses})) as run:
            result = self.worker.refresh_backend_cache(self.job)
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["responses"], responses)
        run.assert_called_once_with([str(self.worker.APP / "clear_cache_after_write.sh"),
                                     self.job["job_id"]], 175)

    def test_persistent_mismatch_stays_unconfirmed(self):
        self.write_state({"PS": "13.71", "XBOX": "13.71", "PC": "12.09"})
        with mock.patch.object(self.worker, "refresh_storefront",
                               return_value={"status": "ok"}), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["reason"], "public_page_readback_unconfirmed")

    def test_budget_is_bounded(self):
        self.write_state({"PS": "13.71", "XBOX": "13.71", "PC": "12.09"})
        calls = {"n": 0}

        def counting_refresh(job):
            calls["n"] += 1
            return {"status": "ok"}

        with mock.patch.object(self.worker, "refresh_storefront", side_effect=counting_refresh), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            self.worker.verify_public_page(self.job)
        self.assertEqual(calls["n"], self.worker.PUBLIC_READBACK_ATTEMPTS - 1)

    def test_unselected_platform_mismatch_is_ignored(self):
        """PC is not selected this cycle; its stale value must not block PS/XBOX."""
        self.write_state({"PS": "13.92", "XBOX": "13.92", "PC": "99.99"})
        with mock.patch.object(self.worker, "refresh_storefront") as refresh, \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "verified")
        refresh.assert_not_called()

    def test_wrong_run_id_cannot_be_verified(self):
        self.write_state({"PS": "13.92", "XBOX": "13.92", "PC": "12.09"}, run_id="other-run")
        with mock.patch.object(self.worker, "refresh_storefront",
                               return_value={"status": "ok"}), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")

    def test_not_ok_state_cannot_be_verified(self):
        self.write_state({"PS": "13.92", "XBOX": "13.92", "PC": "12.09"}, status="partial")
        with mock.patch.object(self.worker, "refresh_storefront",
                               return_value={"status": "ok"}), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")

    def test_empty_selected_platforms_is_not_verified(self):
        self.job["result"]["platforms"] = []
        self.write_state({"PS": "13.92", "XBOX": "13.92", "PC": "12.09"})
        with mock.patch.object(self.worker, "refresh_storefront",
                               return_value={"status": "ok"}), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")

    def test_cent_level_mismatch_is_still_rejected(self):
        """Decimal-exact comparison must not be loosened by the retry."""
        self.write_state({"PS": "13.91", "XBOX": "13.92", "PC": "12.09"})
        with mock.patch.object(self.worker, "refresh_storefront",
                               return_value={"status": "ok"}), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")

    def test_missing_platform_key_is_rejected(self):
        rows = {"PS": {"status": "ok", "package_usd": "13.92"}}
        (self.root / "monitor" / "storefront.json").write_text(json.dumps({
            "status": "ok", "collection_run_id": "cycle-1",
            "last_attempt_at": "x", "rows": rows}), encoding="utf-8")
        with mock.patch.object(self.worker, "refresh_storefront",
                               return_value={"status": "ok"}), \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")

    def test_read_error_is_unconfirmed_without_retry(self):
        (self.root / "monitor" / "storefront.json").write_text("{bad json", encoding="utf-8")
        with mock.patch.object(self.worker, "refresh_storefront") as refresh, \
             mock.patch.object(self.worker, "save_job"), \
             mock.patch.object(self.worker.time, "sleep"):
            result = self.worker.verify_public_page(self.job)
        self.assertEqual(result["status"], "unconfirmed")
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

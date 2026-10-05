"""Focused safety checks for a stopped Players write resuming without replay."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name("player_sync_job.py")
_original = sys.modules.get("p2pah_session_service")
sys.modules["p2pah_session_service"] = types.SimpleNamespace(
    HEADERS={}, SessionManager=object, read_private_config=lambda: {})
try:
    _spec = importlib.util.spec_from_file_location("player_sync_job_recovery_test", SOURCE)
    sync = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sync)
finally:
    if _original is None:
        del sys.modules["p2pah_session_service"]
    else:
        sys.modules["p2pah_session_service"] = _original


class RecoveryTest(unittest.TestCase):
    def test_only_matching_stopped_plan_may_resume(self):
        ledger = {"job_id": "job", "coin_execution_id": "coin",
                  "status": "needs_reconcile", "model_count": 654,
                  "model_ids_sha256": "digest", "verified_count": 356,
                  "next_index": 356}
        self.assertEqual(sync.recovery_start(ledger, job_id="job", coin_id="coin",
                                             count=654, digest="digest"), 356)
        for change in ({"status": "running"}, {"verified_count": 355},
                       {"model_ids_sha256": "different"}, {"next_index": 357}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,
                                                                    "recovery_state_invalid"):
                sync.recovery_start({**ledger, **change}, job_id="job", coin_id="coin",
                                    count=654, digest="digest")

    def test_get_may_retry_but_post_is_never_resent(self):
        class Manager:
            token = "test-token"

            def __init__(self):
                self.calls = 0

            def request(self, path, *, data, token):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("read timeout")
                return 200, json.dumps({"code": 1, "data": {"ok": True}}).encode()

        manager = Manager()
        with patch.object(sync.time, "sleep"):
            self.assertEqual(sync.api(manager, "/read"), {"ok": True})
        self.assertEqual(manager.calls, 2)
        manager = Manager()
        with self.assertRaises(TimeoutError):
            sync.api(manager, "/write", payload={"id": [1]})
        self.assertEqual(manager.calls, 1)


if __name__ == "__main__":
    unittest.main()

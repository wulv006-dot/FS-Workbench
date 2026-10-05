"""Check the confirmed-write gate and chenchao cache-clear response contract."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


stub = types.ModuleType("p2pah_session_service")
stub.SessionManager = object
stub.read_private_config = lambda: {}
with patch.dict(sys.modules, {"p2pah_session_service": stub}):
    spec = importlib.util.spec_from_file_location(
        "clear_cache_after_write", Path(__file__).with_name("clear_cache_after_write.py"))
    cache = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cache)


class Manager:
    token = "test-token"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def ensure(self):
        return True

    def request(self, path, *, data=None, token=None):
        self.calls.append((path, data, token))
        return self.responses.pop(0)


class CacheAfterWriteTest(unittest.TestCase):
    execution_id = "00000000-0000-4000-8000-000000000001"
    audit = {"execution_id": execution_id, "status": "CONFIRMED",
             "sync_confirmed": True, "changed": ["PS"]}
    identity = (200, json.dumps({"data": {"adminInfo": {"username": "chenchao"}}}).encode())

    def test_success_uses_authorized_account_and_admin_all_cache_contract(self):
        manager = Manager([self.identity, (200, b'{"code":1,"msg":"ok"}')])
        result = cache.clear_confirmed_write(self.execution_id, self.audit, manager)
        self.assertEqual(result["status"], "cleared")
        self.assertEqual(manager.calls[-1], ("/admin/tools.Caches/clear?server=1",
                                            {"type": "all", "file": ""}, "test-token"))

    def test_unconfirmed_write_and_wrong_identity_never_clear(self):
        manager = Manager([self.identity])
        with self.assertRaisesRegex(ValueError, "confirmed_write_required"):
            cache.clear_confirmed_write(self.execution_id,
                                        {**self.audit, "sync_confirmed": False}, manager)
        self.assertEqual(manager.calls, [])
        wrong = Manager([(200, b'{"data":{"adminInfo":{"username":"other"}}}')])
        with self.assertRaisesRegex(ValueError, "chenchao_identity_unconfirmed"):
            cache.clear_confirmed_write(self.execution_id, self.audit, wrong)
        self.assertEqual(len(wrong.calls), 1)

    def test_rate_limit_retries_once_and_permission_failure_stops(self):
        manager = Manager([self.identity,
                           (200, '{"code":0,"msg":"操作过于频繁"}'.encode()),
                           (200, b'{"code":1,"msg":"ok"}')])
        with patch.object(cache.time, "sleep") as pause:
            self.assertEqual(cache.clear_confirmed_write(
                self.execution_id, self.audit, manager)["status"], "cleared")
        pause.assert_called_once_with(31)
        denied = Manager([self.identity, (200, b'{"code":401,"msg":"denied"}')])
        with self.assertRaisesRegex(ValueError, "cache_permission_denied"):
            cache.clear_confirmed_write(self.execution_id, self.audit, denied)


if __name__ == "__main__":
    unittest.main()

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
        self.ensures = 0

    def ensure(self):
        self.ensures += 1
        return True

    def request(self, path, *, data=None, token=None):
        self.calls.append((path, data, token))
        return self.responses.pop(0)


class CacheAfterWriteTest(unittest.TestCase):
    execution_id = "00000000-0000-4000-8000-000000000001"
    audit = {"execution_id": execution_id, "status": "CONFIRMED",
             "sync_confirmed": True, "changed": ["PS"]}
    identity = (200, json.dumps({"code": 1, "data": {"adminInfo": {"username": "chenchao"}}}).encode())
    expired = (200, json.dumps({"code": 302, "msg": "Please login first",
                               "data": {"routePath": "/admin/login"}}).encode())

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
                           self.identity,
                           (200, b'{"code":1,"msg":"ok"}')])
        with patch.object(cache.time, "sleep") as pause:
            self.assertEqual(cache.clear_confirmed_write(
                self.execution_id, self.audit, manager)["status"], "cleared")
        pause.assert_called_once_with(31)
        denied = Manager([self.identity, (200, b'{"code":401,"msg":"denied"}')])
        with self.assertRaisesRegex(ValueError, "cache_permission_denied"):
            cache.clear_confirmed_write(self.execution_id, self.audit, denied)

    def test_confirmed_session_expiry_renews_once_without_price_replay(self):
        manager = Manager([self.identity, self.expired, self.expired,
                           self.identity, (200, b'{"code":1}')])
        result = cache.clear_confirmed_write(self.execution_id, self.audit, manager)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["recovered"], ["cache_session_expired"])
        self.assertEqual(manager.ensures, 2)
        self.assertTrue(all(path in {cache.CACHE_PATH, "/admin/index/index"}
                            for path, _, _ in manager.calls))

    def test_generic_rejection_requires_independent_expired_identity(self):
        reject = (200, b'{"code":0,"msg":"unknown"}')
        manager = Manager([self.identity, reject, self.identity])
        with self.assertRaisesRegex(cache.CacheClearError, "cache_clear_rejected"):
            cache.clear_confirmed_write(self.execution_id, self.audit, manager)
        self.assertEqual(manager.ensures, 1)
        self.assertEqual(sum(p == cache.CACHE_PATH for p, _, _ in manager.calls), 1)
        expired = Manager([self.identity, reject, self.expired,
                           self.identity, (200, b'{"code":1}')])
        self.assertEqual(cache.clear_confirmed_write(self.execution_id, self.audit,
                                                   expired)["attempts"], 2)

    def test_expiry_without_login_route_and_wrong_renewed_identity_stop(self):
        ambiguous = (200, b'{"code":302,"msg":"unknown"}')
        manager = Manager([self.identity, ambiguous, ambiguous])
        with self.assertRaisesRegex(cache.CacheClearError, "cache_clear_rejected"):
            cache.clear_confirmed_write(self.execution_id, self.audit, manager)
        self.assertEqual(manager.ensures, 1)
        wrong = Manager([self.identity, self.expired, self.expired,
                         (200, b'{"code":1,"data":{"adminInfo":{"username":"other"}}}')])
        with self.assertRaisesRegex(cache.CacheClearError, "chenchao_identity_unconfirmed"):
            cache.clear_confirmed_write(self.execution_id, self.audit, wrong)
        self.assertEqual(sum(p == cache.CACHE_PATH for p, _, _ in wrong.calls), 1)

    def test_retry_budget_and_repeated_expiry_stop(self):
        rate = (200, '{"code":0,"msg":"操作过于频繁"}'.encode())
        manager = Manager([self.identity, rate, self.identity, self.expired,
                           self.expired, self.identity, self.expired])
        with patch.object(cache.time, "sleep") as pause:
            with self.assertRaisesRegex(cache.CacheClearError, "cache_session_expired") as error:
                cache.clear_confirmed_write(self.execution_id, self.audit, manager)
        pause.assert_called_once_with(31)
        self.assertEqual(manager.ensures, 2)
        self.assertEqual(sum(p == cache.CACHE_PATH for p, _, _ in manager.calls), 3)
        self.assertEqual(len(error.exception.responses), 6)

    def test_malformed_permission_and_unknown_write_are_never_retried(self):
        for response in [(200, b'bad'), (403, b'{"code":403}'),
                         (200, b'{"code":"1"}'), (200, b'{"code":true}')]:
            with self.subTest(response=response):
                manager = Manager([self.identity, response, self.identity])
                with self.assertRaises(cache.CacheClearError):
                    cache.clear_confirmed_write(self.execution_id, self.audit, manager)
                self.assertEqual(manager.ensures, 1)
                self.assertEqual(sum(p == cache.CACHE_PATH for p, _, _ in manager.calls), 1)
        for status in ["UNKNOWN", "UNCERTAIN", "PARTIAL", "RUNNING", "FAILED"]:
            manager = Manager([])
            with self.assertRaisesRegex(ValueError, "confirmed_write_required"):
                cache.clear_confirmed_write(self.execution_id, {**self.audit, "status": status}, manager)
            self.assertEqual(manager.ensures, 0)

    def test_diagnostic_redacts_secrets_and_keeps_response_identity(self):
        raw = b'{"code":0,"msg":"token=private-secret","data":{"token":"secret"}}'
        details = cache.response_details(200, raw)
        self.assertEqual(details["api_code"], 0)
        self.assertEqual(details["message"], "redacted_or_nontext")
        self.assertEqual(len(details["body_sha256"]), 64)
        self.assertNotIn("secret", json.dumps(details))
        for message in ["请先登录", "权限不足", "清理失败"]:
            self.assertEqual(cache.response_details(200, json.dumps(
                {"code":0,"msg":message}).encode())["message"], message)


if __name__ == "__main__":
    unittest.main()

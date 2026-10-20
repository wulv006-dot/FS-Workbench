import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location(
    "health_candidate", Path(__file__).resolve().parents[1] / "source/hooks.py")
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class HealthContract(unittest.TestCase):
    def report(self, payload=None, raw=None, error=None, issues=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        with patch.object(hooks, "dashboard_probe", return_value={"codes": []}), \
             patch.object(hooks, "unknown_operations", return_value=[]), \
             patch.object(hooks, "urlopen", side_effect=error,
                          return_value=io.BytesIO(body)) as request:
            result = hooks.extend_report({"issues": copy.deepcopy(issues or [])})
            request.assert_called_once_with("http://127.0.0.1:8931/health", timeout=3)
        return result

    def good(self):
        return {"ok": True, "service": "fs-business-range", "readonly": True}

    def test_legacy_health(self):
        self.assertEqual(self.report(self.good())["status"], "healthy")

    def test_live_additive_field(self):
        result = self.report(dict(self.good(), active_customer_reports=0))
        self.assertEqual(result["exact_range"]["status"], "read_path_verified")
        self.assertFalse(result["exact_range"]["semantic_queries_verified"])

    def test_future_additive_fields(self):
        self.assertEqual(self.report(dict(self.good(), version="v2", details={}))["status"], "healthy")

    def test_missing_required_fields(self):
        for key in self.good():
            value = self.good()
            del value[key]
            with self.subTest(key=key):
                self.assertEqual(self.report(value)["status"], "critical")

    def test_false_flags(self):
        for key in ("ok", "readonly"):
            self.assertEqual(self.report(dict(self.good(), **{key: False}))["status"], "critical")

    def test_truthy_values_rejected(self):
        for key in ("ok", "readonly"):
            for value in (1, "true", [], None):
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.report(dict(self.good(), **{key: value}))["status"], "critical")

    def test_wrong_service(self):
        self.assertEqual(self.report(dict(self.good(), service="other"))["status"], "critical")

    def test_non_objects(self):
        for value in ([], True, None, "ok", 1):
            self.assertEqual(self.report(value)["status"], "critical")

    def test_malformed_json(self):
        self.assertEqual(self.report(raw=b"{")["status"], "critical")

    def test_oversized_truncated_response(self):
        self.assertEqual(self.report(raw=b" " * 4096 + json.dumps(self.good()).encode())["status"], "critical")

    def test_http_error(self):
        self.assertEqual(self.report(error=HTTPError("local", 503, "unavailable", {}, None))["status"], "critical")

    def test_timeout(self):
        self.assertEqual(self.report(error=TimeoutError())["status"], "critical")

    def test_unrelated_alarm_preserved(self):
        issue = {"level": "critical", "code": "other_failure"}
        result = self.report(self.good(), issues=[issue])
        self.assertEqual(result["status"], "critical")
        self.assertIn(issue, result["issues"])

    def test_unknown_operation_gate_unchanged(self):
        value = {"issues": [], "coin": {"config": {"system_enabled": True, "mode": "auto", "revision": 38}},
                 "publication": {"platforms": [{"platform": p, "status": "matched"} for p in hooks.PLATFORMS]},
                 "unknown_operations": [{"operation_id": "test", "platforms": ["PS"]}]}
        with patch.object(hooks, "bot_ready", return_value=False):
            result = hooks.controls(value)
        self.assertIn("unknown_operation:test", result["platforms"]["PS"]["reasons"])


if __name__ == "__main__":
    unittest.main()

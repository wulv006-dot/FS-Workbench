"""Local HTTP tests for automation settings authorization and HTTPS gate."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc27_cloud_api as api
from automation_policy import initial_policy


class AutomationApiTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.roles = patch.object(api, "WRITERS", {"tester"})
        self.roles.start()
        self.addCleanup(self.roles.stop)

    def post(self, settings, https=False):
        body = json.dumps({"expected_revision": 0, "settings": settings}).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Authenticated-User": "tester"}
        if https:
            headers["X-Forwarded-Proto"] = "https"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/automation", body, headers)
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def settings(self, mode="manual"):
        return {key: value for key, value in {**initial_policy(), "mode": mode}.items()
                if key not in {"revision", "updated_at", "updated_by", "pricing_rules"}}

    def test_http_cannot_change_automation_settings(self):
        with patch.object(api, "save_policy") as save:
            status, payload = self.post(self.settings())
        self.assertEqual((status, payload["error"]), (503, "https_required_for_automation_config"))
        save.assert_not_called()

    def test_auto_mode_requires_ready_writer(self):
        settings = self.settings("auto")
        settings["system_enabled"] = True
        with (patch.object(api, "writer_status", return_value="certificate_unhealthy"),
              patch.object(api, "save_policy") as save):
            status, payload = self.post(settings, https=True)
        self.assertEqual((status, payload["error"]), (503, "automation_writer_unavailable"))
        save.assert_not_called()

    def test_https_manual_settings_reach_versioned_save(self):
        settings = self.settings()
        with (patch.object(api, "save_policy", return_value=initial_policy()) as save,
              patch.object(api, "automation_view", side_effect=lambda policy, actor=None: policy)):
            status, payload = self.post(settings, https=True)
        self.assertEqual(status, 200)
        self.assertFalse(payload["system_enabled"])
        save.assert_called_once_with(settings, "tester", 0)

    def test_automation_storage_error_is_not_reported_as_queue_failure(self):
        settings = self.settings()
        with patch.object(api, "save_policy", side_effect=PermissionError("audit not writable")):
            status, payload = self.post(settings, https=True)
        self.assertEqual((status, payload["error"]), (503, "automation_storage_unavailable"))

    def test_automatic_activity_includes_target_price(self):
        audit = {"selected": ["PS"],
                 "before": {"rows": [{"platform": "PS", "costPrice": "1", "b2c": "2"}]},
                 "targets": [{"platform": "PS", "targetCost": "1.1", "quote": "2.1"}],
                 "after": {"rows": [{"platform": "PS", "costPrice": "1.1", "b2c": "2.1"}]}}
        changes = api.activity_changes({"kind": "auto_cycle", "request": {}}, audit)
        self.assertEqual((changes[0]["target_cost"], changes[0]["target_b2c"]),
                         ("1.1", "2.1"))


if __name__ == "__main__":
    unittest.main()

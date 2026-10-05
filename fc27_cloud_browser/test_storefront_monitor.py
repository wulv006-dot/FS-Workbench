"""Contract checks for read-only MMOEXP 100K monitoring."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import storefront_monitor as monitor


PAGE = ("<h1>Buy FC 27 Coins</h1><div id='container' data-cid='9623'></div>"
        "<li data-code='ps' data-id='21587' data-gid='1327' data-sign='$'></li>"
        "<li data-code='xbox' data-id='21585' data-gid='1327' data-sign='$'></li>"
        "<li data-code='pc' data-id='21589' data-gid='1327' data-sign='$'></li>"
        "<script>const site_id = `266`;</script>")


def response(price):
    return json.dumps({"goods": {"index": {"list": [{"id": 101, "unit": "K",
        "goods_list": {"a": {"num": 100, "price_discount": price, "give": 0}}}]}}})


class StorefrontMonitorTest(unittest.TestCase):
    def test_page_mapping_accepts_json_encoded_public_html(self):
        expected = monitor.page_mapping(PAGE)
        self.assertEqual(monitor.page_mapping(json.dumps(PAGE)), expected)

    def test_page_mapping_rejects_invalid_encoded_html(self):
        with self.assertRaisesRegex(ValueError, "product_page_invalid"):
            monitor.page_mapping('"broken\\q"')

    def test_page_mapping_rejects_missing_platform(self):
        with self.assertRaisesRegex(ValueError, "product_mapping_changed"):
            monitor.page_mapping(PAGE.replace("data-code='pc'", "data-code='other'"))

    def test_effective_price_uses_received_quantity(self):
        payload = json.loads(response("13.25"))
        payload["goods"]["index"]["list"][0]["goods_list"]["a"]["give"] = 5
        self.assertEqual(monitor.offer_from_response(payload)["usd_per_k"], "0.126190")

    def test_public_requests_reuse_one_temporary_session_and_bypass_local_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            jar = Path(directory) / "cookies.txt"
            result = SimpleNamespace(returncode=0, stdout=b"ok")
            with patch.object(monitor.subprocess, "run", return_value=result) as run:
                monitor.fetch(monitor.PAGE_URL, cookie_jar=jar)
                first = run.call_args.args[0]
                self.assertIn("--cookie-jar", first)
                self.assertNotIn("--cookie", first)
                self.assertIn("Cache-Control: no-cache", first)
                jar.touch()
                monitor.fetch(monitor.GOODS_URL, form={"aid": "123"}, cookie_jar=jar)
                second = run.call_args.args[0]
                self.assertEqual(second[second.index("--cookie") + 1], str(jar))

    def test_failed_refresh_keeps_last_value_but_marks_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "storefront.json"
            with patch.object(monitor, "STATE_FILE", state):
                def first(url, form=None, limit=2000000, cookie_jar=None):
                    self.assertIsNotNone(cookie_jar)
                    return PAGE if form is None else response("13.25")
                with patch.object(monitor, "fetch", side_effect=first):
                    complete = monitor.collect("test-run")
                self.assertEqual(complete["status"], "ok")
                self.assertEqual(complete["collection_run_id"], "test-run")
                old = complete["rows"]["PS"]["checked_at"]
                with patch.object(monitor, "fetch", side_effect=ValueError("unavailable")):
                    failed = monitor.collect()
                self.assertEqual(failed["status"], "unavailable")
                self.assertEqual(failed["rows"]["PS"]["checked_at"], old)
                self.assertEqual(failed["rows"]["PS"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()

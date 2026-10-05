"""Verify the category-wide admin call and bounded sample readback."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.request

SOURCE = Path(__file__).with_name("player_sync_job.py")
original = sys.modules.get("p2pah_session_service")
sys.modules["p2pah_session_service"] = types.SimpleNamespace(
    HEADERS={"Origin": "https://admin.p2pah.cn"},
    SessionManager=object, read_private_config=lambda: {})
try:
    spec = importlib.util.spec_from_file_location("player_sync_job_bulk_test", SOURCE)
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
finally:
    if original is None:
        del sys.modules["p2pah_session_service"]
    else:
        sys.modules["p2pah_session_service"] = original


class BulkPlayerSyncTest(unittest.TestCase):
    def test_one_category_write_then_five_sampled_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, audit, policy = [root / name for name in ("request.json", "audit.json", "policy.json")]
            request.write_text(json.dumps({"job_id": "bulk-job", "coin_execution_id": "coin-job",
                                           "config_revision": 3}), encoding="utf-8")
            audit.write_text(json.dumps({"execution_id": "coin-job", "status": "CONFIRMED",
                                         "automatic": True, "after": {"rows": [
                                             {"platform": name, "b2c": "0.1"}
                                             for name in ("PS", "XBOX", "PC")]}}), encoding="utf-8")
            policy.write_text(json.dumps({"enabled": True, "revision": 3}), encoding="utf-8")
            models = [{"id": model_id, "gid": 1327, "cid": 9627, "status": 1,
                       "title": f"Player {model_id}/Gold Non Rare",
                       "more": {"extend": [{"key": "ps_price", "value": "100000"},
                                           {"key": "pc_price", "value": "100000"},
                                           {"key": "coefficient", "value": "1.1"}]}}
                      for model_id in range(101, 106)]

            class Manager:
                token = "test-token"

                def __init__(self, config):
                    pass

                def ensure(self):
                    return True

            writes = []

            def recalculate_category(manager):
                writes.append({"gid": 1327, "cid": 9627, "id": []})
                return {}

            def api(manager, path, *, payload=None):
                if path == "/admin/index/index":
                    return {"adminInfo": {"username": "chenchao"}}
                if path.startswith("/admin/goods.GoodsMould/edit?id="):
                    model_id = int(path.rsplit("=", 1)[1])
                    return {"row": next(row for row in models if row["id"] == model_id)}
                raise AssertionError(path)

            def products(manager, model_id):
                return [{"id": model_id * 10 + index, "gid": 1327, "cid": 9627,
                         "mid": model_id, "site_id": 266, "status": 1, "total": 1,
                         "gameArea": {"title": area}, "unit_price": "11.0"}
                        for index, area in enumerate(("PlayStation", "Xbox", "PC"), 1)]

            def public_formula_status(sample, linked, rates):
                return [{"platform": platform, "backend_match": True, "public_match": True,
                         "our_price_coins": "100000", "target_usd": "11.0"}
                        for platform in ("PS", "XBOX", "PC")]

            output = io.StringIO()
            with (patch.object(sync, "ROOT", root), patch.object(sync, "REQUEST", request),
                  patch.object(sync, "EXECUTION", audit), patch.object(sync, "POLICY", policy),
                  patch.object(sync, "SessionManager", Manager),
                  patch.object(sync, "read_private_config", return_value={}),
                  patch.object(sync, "list_models", return_value=models),
                  patch.object(sync, "products", side_effect=products),
                  patch.object(sync, "public_formula_status", side_effect=public_formula_status),
                  patch.object(sync, "recalculate_category", side_effect=recalculate_category),
                  patch.object(sync, "api", side_effect=api), redirect_stdout(output)):
                sync.bulk_main()
            result = json.loads(output.getvalue().splitlines()[-1])
            ledger = json.loads((root / "bulk-job.json").read_text(encoding="utf-8"))
            self.assertEqual(writes, [{"gid": 1327, "cid": 9627, "id": []}])
            self.assertEqual(result["status"], "confirmed")
            self.assertEqual((ledger["mode"], ledger["sample_count"],
                              ledger["sample_verified_count"]), ("category_all", 5, 5))
            self.assertEqual(set(ledger["sample_model_ids"]), {101, 102, 103, 104, 105})
            self.assertEqual(set(ledger["sample_verified_model_ids"]), {101, 102, 103, 104, 105})
            self.assertEqual(ledger["sample_source"],
                             "MMOEXP Players Our Price by exact product ID")

    def test_public_formula_uses_live_our_price_instead_of_model_coin_field(self):
        sample = {"id": 123, "title": "Sample Player", "product_ids": [1, 2, 3]}
        products = [{"id": product_id, "site_id": 266, "status": 1, "total": 1,
                     "gameArea": {"title": area}, "unit_price": "5.5"}
                    for product_id, area in ((1, "PlayStation"), (2, "Xbox"), (3, "PC"))]
        def offer(product_id, model_id, platform, player_name):
            self.assertEqual((model_id, player_name), (123, "Sample Player"))
            return {"product_id": product_id, "our_price_coins": sync.Decimal("50000"),
                    "coefficient": sync.Decimal("1.1"), "usd": sync.Decimal("5.5"),
                    "checked_at": "now"}
        with patch.object(sync, "public_offer", side_effect=offer):
            details = sync.public_formula_status(sample, products, {
                platform: sync.Decimal("0.1") for platform in ("PS", "XBOX", "PC")})
        self.assertTrue(all(sync.Decimal(part["target_usd"]) == sync.Decimal("5.5")
                            for part in details))
        self.assertTrue(all(part["backend_match"] and part["public_match"] for part in details))

    def test_public_offer_requires_exact_product_and_model_id(self):
        def response(mid):
            rows = [{"id": 456, "mid": mid, "gid": 1327, "cid": 9627,
                     "site_id": 266, "aid": 21587, "status": 1, "total": 1,
                     "unit_price": "5.5000", "more_extend_fromat": {
                         "ps_price": 50000, "coefficient": 1.1}}]
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({
                "goods": {"index": {"list": rows, "total": 1}}}).encode())
        with patch.object(sync.subprocess, "run", return_value=response(123)) as fetch:
            value = sync.public_offer(456, 123, "PS", "Sample Player")
        self.assertEqual((value["our_price_coins"], value["usd"]),
                         (sync.Decimal("50000"), sync.Decimal("5.5000")))
        command = fetch.call_args.args[0]
        self.assertIn("keyword=Sample+Player", command[-2])
        self.assertIn("aid=21587", command[-2])
        with patch.object(sync.subprocess, "run", return_value=response(999)):
            with self.assertRaisesRegex(ValueError, "public_player_product_mismatch"):
                sync.public_offer(456, 123, "PS", "Sample Player")

    def test_public_offer_searches_later_page_by_exact_product_id(self):
        first = [{"id": number} for number in range(100, 112)]
        second = [{"id": 456, "mid": 123, "gid": 1327, "cid": 9627,
                   "site_id": 266, "aid": 21589, "status": 1, "total": 1,
                   "unit_price": "7.777", "more_extend_fromat": {
                       "pc_price": 50000, "coefficient": "1.1"}}]
        def payload(rows):
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({
                "goods": {"index": {"list": rows, "total": 13}}}).encode())
        with patch.object(sync.subprocess, "run", side_effect=[payload(first), payload(second)]) as fetch:
            offer = sync.public_offer(456, 123, "PC", "Sample Player")
        self.assertEqual(offer["our_price_coins"], sync.Decimal("50000"))
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("page=2", fetch.call_args.args[0][-2])

    def test_legacy_resume_cannot_use_old_model_coin_calculation(self):
        with patch.object(sync, "read", return_value={"resume": True}), \
                patch.object(sync, "bulk_main") as bulk:
            with self.assertRaisesRegex(ValueError, "manual_reconciliation"):
                sync.run_selected()
        bulk.assert_not_called()

    def test_bulk_request_uses_empty_selection_and_long_timeout(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"code":1,"data":{}}'

        requests = []

        def urlopen(request, timeout):
            requests.append((request, timeout))
            return Response()

        manager = types.SimpleNamespace(
            config={"P2PAH_API_BASE": "https://admin-api.p2pah.cn"}, token="test-token")
        with patch.object(urllib.request, "urlopen", side_effect=urlopen):
            sync.recalculate_category(manager)
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        self.assertEqual(timeout, 300)
        self.assertTrue(request.full_url.endswith("/admin/goods.GoodsMould/recalcFc27Price"))
        self.assertEqual(json.loads(request.data), {"gid": 1327, "cid": 9627, "id": []})


if __name__ == "__main__":
    unittest.main()

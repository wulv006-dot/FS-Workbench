from copy import deepcopy
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openpyxl import Workbook

HERE = Path(__file__).resolve()
BASE = next(parent / "fc27_players_cloud" for parent in HERE.parents
            if (parent / "fc27_players_cloud/player_web/repository.py").is_file())
sys.path.insert(0, str(BASE))
from player_web.repository import Repository, StateError, digest
from 球员维护工具.admin_adapter import extract_futbin_id
from 球员维护工具.admin_client import AdminContractError
from 球员维护工具.transformer import EN_HEADERS
from test_payload import source_row, form, DEFAULTS


def load(name):
    spec = importlib.util.spec_from_file_location("player_web." + name, HERE.parents[1] / "source" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("direct_model_payload")
direct = load("direct_model_import")


@contextmanager
def free_lock():
    yield True


@contextmanager
def busy_lock():
    yield False


class Backend:
    authenticated = True

    def __init__(self, case):
        self.case = case
        self.rows, self.products, self.calls = {}, {}, []
        self.reject, self.lost_add, self.lost_sync = set(), set(), set()
        self.bad_six = False
        self.on_add = None
        self.list_reads = 0
        self.missing_sync_value = 0
        self.fallback_lost = set()
        self.lock_active = None
        self.shelves_placeholder = 0
        self.sync_pending = False

    def intent(self, phase, fid):
        events = self.case.repo.get_execution(self.case.execution, "operator")["events"]
        matching = [event for event in events if event["step"] == "direct_" + phase
                    and event["detail"].get("futbin_id") == fid]
        self.case.assertTrue(matching)
        self.case.assertEqual(matching[-1]["status"], "intent")

    def list_models(self, **kwargs):
        self.list_reads += 1
        values = list(self.rows.values())
        page, limit = kwargs["page"], kwargs["limit"]
        return SimpleNamespace(total=len(values), rows=deepcopy(values[(page - 1) * limit:page * limit]))

    def get_model(self, mid):
        return deepcopy(self.rows[mid])

    def get_products(self, mid):
        return deepcopy(self.products.get(mid, []))

    def add_model(self, payload):
        fid = extract_futbin_id(payload)
        self.intent("add", fid)
        self.calls.append(("add", fid))
        if self.on_add:
            callback, self.on_add = self.on_add, None
            callback()
        if fid in self.reject:
            raise AdminContractError("not persisted", diagnostic={"method": "POST", "endpoint": "/admin/goods.GoodsMould/add",
                                                                   "response_code": 401, "response_msg": "rejected"})
        mid = 600000 + int(fid)
        self.rows[mid] = {**deepcopy(payload), "id": mid, "futbin_id": fid, "status": 1, "is_put": 0}
        if fid in self.lost_add:
            raise TimeoutError("lost add response")
        return {"code": 1, "data": {"id": mid}}

    def shelves_models(self, ids, *, gid, cid, payload):
        self.case.assertEqual((gid, cid), (1327, 9627))
        self.case.assertEqual(payload["status"], "0")
        self.case.assertEqual(payload["site_ids"], [266])
        mid = ids[0]
        fid = self.rows[mid]["futbin_id"]
        self.intent("shelves", fid)
        self.calls.append(("shelves", fid))
        self.rows[mid]["is_put"] = 1
        self.products[mid] = [
            {"id": mid * 10 + index + 1, "mid": mid, "gid": 1327, "cid": 9627,
             "site_id": site, "aid": aid, "status": 0, "unit_price": self.shelves_placeholder,
             "num": 1, "discount": 100, "price": 9999, "total": 0, "auto_off": 0}
            for index, (site, aid) in enumerate((site, aid) for site in (0, 266) for aid in (21587, 21585, 21589))]
        if self.bad_six:
            self.products[mid].pop()
        return {"code": 1}

    def single_edit(self, payload):
        mid = payload["id"][0]
        fid = self.rows[mid]["futbin_id"]
        phase = "tags" if "tid" in payload else "recommend"
        if fid in self.case.frozen.get("existing_model_map", {}):
            phase = "extra_" + phase
        self.intent(phase, fid)
        self.calls.append((phase, fid))
        self.rows[mid].update({key: value for key, value in payload.items() if key != "id"})
        return {"code": 1}

    def recalc_fc27_price(self, *, model_ids, gid, cid):
        mid = model_ids[0]
        fid = self.rows[mid]["futbin_id"]
        self.intent("sync", fid)
        if self.lock_active is not None:
            self.case.assertTrue(self.lock_active)
        self.calls.append(("sync", fid))
        if self.sync_pending:
            return {"code": 1}
        for row in self.products[mid]:
            missing = {entry["key"]: entry["value"] for entry in self.rows[mid]["more"]["extend"]}
            field = "pc_price" if row["aid"] == 21589 else "ps_price"
            row["unit_price"] = self.missing_sync_value if missing[field] in (None, "") else 10
            row["price"] = 9999
        if fid in self.lost_sync:
            raise TimeoutError("lost sync response")
        return {"code": 1}

    def set_product_fallback_price(self, mid, pid):
        fid = self.rows[mid]["futbin_id"]
        self.intent("fallback_price_" + str(pid), fid)
        if self.lock_active is not None:
            self.case.assertTrue(self.lock_active)
        self.calls.append(("fallback", fid, pid))
        for row in self.products[mid]:
            if row["id"] == pid:
                row["unit_price"] = 9999
        if pid in self.fallback_lost:
            raise TimeoutError("fallback response lost")
        return {"code": 1}

    def set_product_status(self, mid, pid, status):
        fid = self.rows[mid]["futbin_id"]
        self.intent("product_status_" + str(pid), fid)
        self.calls.append(("product_status", fid, pid, status))
        for row in self.products[mid]:
            if row["id"] == pid:
                row["status"] = status
        return {"code": 1}


class DirectImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root / "db/control.sqlite3")
        self.repo.initialize()
        self.settings = SimpleNamespace(new_card_write_enabled=True, data_root=self.root)
        self.backend = Backend(self)
        self.lock = patch.object(direct, "shared_price_lock", free_lock)
        self.lock.start()

    def tearDown(self):
        self.lock.stop()
        self.temp.cleanup()

    def plan(self, count=1, *, missing_pc=False, missing_ps=False, missing_policy="reject", existing=False, wrong_existing=False):
        artifact = self.root / "selected.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(EN_HEADERS)
        context_workbook = Workbook()
        context_sheet = context_workbook.active
        context_sheet.append(EN_HEADERS)
        candidates = []
        for offset in range(count):
            row = source_row()
            row["FUTBIN ID"] = 23700 + offset
            row["name"] = "Player " + str(offset)
            if missing_pc and offset == 0:
                row["PC"] = None
            if missing_ps and offset == 0:
                row["PS"] = None
            sheet.append([row[column] for column in EN_HEADERS])
            context_sheet.append([row[column] for column in EN_HEADERS])
            signature = {**row, "FUTBIN ID": 33700 + offset, "IS": row["IS"] * 2}
            context_sheet.append([signature[column] for column in EN_HEADERS])
            candidates.append({"futbin_id": str(row["FUTBIN ID"]), "rating": row["Rating"]})
        workbook.save(artifact)
        workbook.close()
        context = self.root / "transformed.xlsx"
        context_workbook.save(context)
        context_workbook.close()
        items = direct.prepare_direct_items(artifact, candidates, form(),
                    business_defaults={**DEFAULTS, "missing_price_policy": missing_policy},
                    context_artifact_path=context)
        ids = [item["futbin_id"] for item in items]
        extra = {}
        if existing:
            known = deepcopy(items[0]["payload"])
            for entry in known["more"]["extend"]:
                if entry["key"] == "player_id":
                    entry["value"] = "23999"
            self.backend.rows[777] = {**known, "id": 777, "futbin_id": "23999", "is_rec": 0, "status": 1, "is_put": 1}
            extra = {"23998" if wrong_existing else "23999": 777}
        scope = ids + list(extra)
        self.frozen = self.repo.save_plan("operator", {"kind": "new_cards", "import_mode": "direct_json_v1",
            "scope_ids": scope, "upload_futbin_ids": ids, "tag_futbin_ids": scope,
            "recommend_futbin_ids": list(extra), "existing_model_map": extra,
            "selected_tag_ids": [12307, 12411], "blockers": [], "direct_items": items,
            "artifact_path": str(artifact), "artifact_sha256": items[0]["source_sha256"],
            "context_artifact_path": str(context), "context_sha256": items[0]["context_sha256"]})
        self.execution, _ = self.repo.confirm(self.frozen["plan_id"], "operator", self.frozen["plan_digest"], write_enabled=True)
        return self.frozen

    def run_plan(self, **kwargs):
        return direct.execute_direct_plan(self.settings, self.repo, self.backend, self.execution, self.frozen, **kwargs)

    def scopes(self):
        with self.repo.connection() as db:
            return [row[0] for row in db.execute("SELECT futbin_id FROM active_scope ORDER BY futbin_id")]

    def test_success_per_person_receipts_six_products_and_rerun_zero_posts(self):
        self.plan(2)
        result = self.run_plan()
        self.assertEqual(result["completed_futbin_ids"], ["23700", "23701"])
        self.assertEqual(self.scopes(), [])
        for mid, rows in self.backend.products.items():
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row["status"] == 1 and row["unit_price"] == 10 and row["price"] == 9999 for row in rows))
            self.assertEqual(set(self.backend.rows[mid]["tid"]), {12307, 12411})
        before = list(self.backend.calls)
        reads = self.backend.list_reads
        self.run_plan()
        self.assertEqual(self.backend.calls, before)
        self.assertEqual(self.backend.list_reads, reads)
        self.assertEqual(reads, 2, "only initial duplicate checks need full model pages")

    def test_pilot_subselection_then_same_execution_full_plan(self):
        self.plan(2)
        result = self.run_plan(only_futbin_ids=["23700"])
        self.assertEqual(result["pending_futbin_ids"], ["23701"])
        self.assertEqual(self.scopes(), ["23701"])
        self.assertEqual(self.repo.get_execution(self.execution, "operator")["status"], "partial_readback")
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("add", "23700")), 1)
        self.assertEqual(self.scopes(), [])

    def test_lost_add_response_reconciles_by_get_without_second_add(self):
        self.plan()
        self.backend.lost_add.add("23700")
        self.assertEqual(self.run_plan()["unresolved_futbin_ids"], ["23700"])
        self.assertEqual(self.scopes(), ["23700"])
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("add", "23700")), 1)
        self.assertEqual(self.scopes(), [])

    def test_sync_unknown_is_not_reposted_or_claimed_confirmed_from_price(self):
        self.plan()
        self.backend.lost_sync.add("23700")
        self.run_plan()
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("sync", "23700")), 1)
        self.assertEqual(self.scopes(), ["23700"])
        self.assertFalse(any(call[0] == "product_status" for call in self.backend.calls))

    def test_accepted_sync_readback_failure_keeps_receipt_and_resumes_readonly(self):
        self.plan()
        original = direct._products
        failed = []

        def fail_once_after_sync(client, mid):
            if ("sync", "23700") in self.backend.calls and not failed:
                failed.append(True)
                raise OSError("readback unavailable")
            return original(client, mid)

        with patch.object(direct, "_products", side_effect=fail_once_after_sync):
            self.run_plan()
        execution = self.repo.get_execution(self.execution, "operator")
        receipt = [event for event in execution["events"] if event["step"] == "direct_sync"][-1]
        self.assertEqual(receipt["status"], "accepted")
        self.assertIn("last_readback_error", receipt["detail"])
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("sync", "23700")), 1)
        self.assertEqual(self.scopes(), [])

    def test_rejected_person_does_not_block_other_person_or_retry(self):
        self.plan(2)
        self.backend.reject.add("23700")
        result = self.run_plan()
        self.assertEqual(result["completed_futbin_ids"], ["23701"])
        self.assertEqual(self.scopes(), ["23700"])
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("add", "23700")), 1)

    def test_busy_sync_resumes_without_repeating_prior_steps(self):
        self.plan()
        with patch.object(direct, "shared_price_lock", busy_lock):
            result = self.run_plan()
        self.assertEqual(result["waiting_futbin_ids"], ["23700"])
        self.assertEqual(self.repo.get_execution(self.execution, "operator")["status"], "waiting_price_lock")
        self.run_plan()
        for phase in ("add", "shelves", "tags", "sync"):
            self.assertEqual(self.backend.calls.count((phase, "23700")), 1)

    def test_incomplete_six_scope_never_reshelves_or_syncs(self):
        self.plan()
        self.backend.bad_six = True
        self.run_plan()
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("shelves", "23700")), 1)
        self.assertFalse(any(call[0] == "sync" for call in self.backend.calls))
        self.assertEqual(self.scopes(), ["23700"])

    def test_source_tamper_blocks_before_any_post(self):
        self.plan()
        with open(self.frozen["artifact_path"], "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaisesRegex(StateError, "ARTIFACT_CHANGED"):
            self.run_plan()
        self.assertEqual(self.backend.calls, [])

    def test_context_tamper_blocks_before_any_post(self):
        self.plan()
        with open(self.frozen["context_artifact_path"], "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaisesRegex(StateError, "DIRECT_CONTEXT_CHANGED"):
            self.run_plan()
        self.assertEqual(self.backend.calls, [])

    def test_selected_single_player_uses_full_context_not_a_fixed_type(self):
        self.plan()
        item = self.frozen["direct_items"][0]
        self.assertEqual(item["players_type"], "normal")
        self.assertFalse(item["blocked_error"])
        candidates = [{"futbin_id": "23700", "rating": 92}]
        isolated = direct.prepare_direct_items(self.frozen["artifact_path"], candidates, form(), business_defaults=DEFAULTS)
        self.assertIsNone(isolated[0]["blocked_error"])
        self.assertEqual(isolated[0]["players_type"], "normal")
        signature = direct._source_rows(self.frozen["context_artifact_path"])[1]
        selected = self.root / "selected-signature.xlsx"
        workbook = Workbook()
        workbook.active.append(EN_HEADERS)
        workbook.active.append([signature[column] for column in EN_HEADERS])
        workbook.save(selected)
        workbook.close()
        schema = form()
        prop = next(p for p in schema["row"]["more"]["baseprop"] if p["name"] == "PlayersType")
        prop["pvs"].append({"id": 9999, "name": "Signature", "checked": False})
        items = direct.prepare_direct_items(selected, [{"futbin_id": "33700"}], schema,
                    business_defaults=DEFAULTS, context_artifact_path=self.frozen["context_artifact_path"])
        self.assertEqual(items[0]["players_type"], "Signature")
        self.assertIsNone(items[0]["blocked_error"])

    def test_concurrent_reentry_cannot_reclaim_inflight_add(self):
        self.plan()
        self.backend.on_add = lambda: self.run_plan()
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("add", "23700")), 1)
        self.assertEqual(self.scopes(), [])

    def test_missing_price_explicit_policy_leaves_only_that_platform_disabled(self):
        self.plan(missing_pc=True, missing_policy="preserve_unknown")
        self.run_plan()
        rows = next(iter(self.backend.products.values()))
        self.assertTrue(all(row["status"] == int(row["aid"] != 21589) for row in rows))
        self.assertEqual(len([call for call in self.backend.calls if call[0] == "product_status"]), 4)

    def test_fallback_sets_only_missing_platform_unit_price_and_leaves_model_unknown(self):
        self.plan(missing_pc=True, missing_policy="fallback_9999")
        @contextmanager
        def tracked_lock():
            self.backend.lock_active = True
            try:
                yield True
            finally:
                self.backend.lock_active = False
        with patch.object(direct, "shared_price_lock", tracked_lock):
            self.run_plan()
        mid = next(iter(self.backend.rows))
        market = {entry["key"]: entry["value"] for entry in self.backend.rows[mid]["more"]["extend"]}
        self.assertEqual(market["pc_price"], "")
        self.assertEqual(market["ps_price"], "200000")
        for row in self.backend.products[mid]:
            self.assertEqual(row["status"], 1)
            self.assertEqual(row["unit_price"], 9999 if row["aid"] == 21589 else 10)
        self.assertEqual(len([call for call in self.backend.calls if call[0] == "fallback"]), 2)
        before = list(self.backend.calls)
        # Later background repricing is preserved on same-plan resume of a closed person.
        for row in self.backend.products[mid]:
            row["unit_price"] = 11
        self.run_plan()
        self.assertEqual(before, self.backend.calls)

    def test_fallback_accepts_empty_sync_values_without_reposting_sync(self):
        self.plan(missing_pc=True, missing_policy="fallback_9999")
        self.backend.missing_sync_value = ""
        self.run_plan()
        self.assertEqual(self.scopes(), [])
        self.assertEqual(self.backend.calls.count(("sync", "23700")), 1)
        self.assertEqual(len([call for call in self.backend.calls if call[0] == "fallback"]), 2)

    def test_both_market_prices_unknown_keep_model_empty_and_all_six_goods_9999(self):
        self.plan(missing_pc=True, missing_ps=True, missing_policy="fallback_9999")
        self.backend.missing_sync_value = None
        self.run_plan()
        mid = next(iter(self.backend.rows))
        market = {entry["key"]: entry["value"] for entry in self.backend.rows[mid]["more"]["extend"]}
        self.assertEqual(market["pc_price"], "")
        self.assertEqual(market["ps_price"], "")
        self.assertTrue(all(row["unit_price"] == 9999 and row["status"] == 1 for row in self.backend.products[mid]))
        self.assertEqual(len([call for call in self.backend.calls if call[0] == "fallback"]), 6)
        self.assertEqual(self.scopes(), [])

    def test_lost_fallback_response_reconciles_without_resync_or_reprice(self):
        self.plan(missing_pc=True, missing_policy="fallback_9999")
        first_pc_pid = (600000 + 23700) * 10 + 3
        self.backend.fallback_lost.add(first_pc_pid)
        self.assertEqual(self.run_plan()["unresolved_futbin_ids"], ["23700"])
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("sync", "23700")), 1)
        self.assertEqual(self.backend.calls.count(("fallback", "23700", first_pc_pid)), 1)
        self.assertEqual(self.scopes(), [])

    def check_pending_placeholder(self, missing):
        self.plan(missing_pc=missing, missing_policy="fallback_9999")
        self.backend.shelves_placeholder = 9999
        self.backend.sync_pending = True
        result = self.run_plan()
        self.assertEqual(result["unresolved_futbin_ids"], ["23700"])
        self.assertNotEqual(self.repo.get_execution(self.execution, "operator")["status"], "completed_readback")
        self.assertFalse(any(call[0] == "product_status" for call in self.backend.calls))
        self.assertFalse(any(call[0] == "fallback" for call in self.backend.calls))
        events = self.repo.get_execution(self.execution, "operator")["events"]
        receipt = [event for event in events if event["step"] == "direct_sync"][-1]
        self.assertEqual(receipt["status"], "accepted")
        mid = next(iter(self.backend.rows))
        # Complete the already accepted backend job without sending another sync.
        for row in self.backend.products[mid]:
            if not missing or row["aid"] != 21589:
                row["unit_price"] = 12
        self.run_plan()
        self.assertEqual(self.backend.calls.count(("sync", "23700")), 1)
        self.assertEqual(self.scopes(), [])
        self.assertTrue(all(row["status"] == 1 for row in self.backend.products[mid]))

    def test_known_placeholder_is_pending_until_backend_finishes_same_sync(self):
        self.check_pending_placeholder(False)

    def test_known_placeholder_blocks_even_when_other_platform_has_fallback(self):
        self.check_pending_placeholder(True)

    def test_blocked_source_person_does_not_block_valid_person(self):
        self.plan(2, missing_pc=True)
        result = self.run_plan()
        self.assertEqual(result["completed_futbin_ids"], ["23701"])
        self.assertFalse(any(call[0] == "add" and call[1] == "23700" for call in self.backend.calls))

    def test_subset_outside_plan_and_unproved_migration_are_rejected(self):
        self.plan()
        with self.assertRaisesRegex(StateError, "DIRECT_EXECUTION_SUBSET_INVALID"):
            self.run_plan(only_futbin_ids=["99999"])
        self.frozen = {**self.frozen, "origin_plan_digest": self.frozen["plan_digest"]}
        with self.assertRaisesRegex(StateError, "DIRECT_MIGRATION_PROOF_REQUIRED"):
            self.run_plan()
        self.assertEqual(self.backend.calls, [])

    def test_old_multipart_plan_cannot_enter_legacy_upload_again(self):
        self.plan()
        service = load("new_card_service")
        legacy = {**self.frozen, "import_mode": "legacy_multipart"}
        with self.assertRaisesRegex(StateError, "DIRECT_PLAN_REQUIRED"):
            service.execute_confirmed_plan(self.settings, self.repo, self.backend, self.execution, legacy)
        self.assertEqual(self.backend.calls, [])

    def test_root_controlled_migration_requires_exact_plan_and_evidence(self):
        self.plan()
        self.frozen = {**self.frozen, "origin_plan_digest": self.frozen["plan_digest"]}
        self.repo.set_execution(self.execution, "needs_reconcile", "direct_plan_migration", {
            "root_controlled": True,
            "original_request_no_enqueue_evidence": {"path": "offline-fixture", "sha256": "a" * 64},
            "direct_plan": self.frozen, "direct_plan_sha256": digest(self.frozen)})
        self.assertEqual(self.run_plan()["completed_futbin_ids"], ["23700"])
        self.assertEqual(self.scopes(), [])

    def test_mixed_plan_retains_existing_tags_recommendation_without_shelves_or_sync(self):
        self.plan(existing=True)
        result = self.run_plan()
        self.assertEqual(result["completed_futbin_ids"], ["23700", "23999"])
        self.assertEqual(set(self.backend.rows[777]["tid"]), {12307, 12411})
        self.assertEqual(self.backend.rows[777]["is_rec"], 1)
        self.assertFalse(any(call[0] in {"add", "shelves", "sync"} and call[1] == "23999" for call in self.backend.calls))
        self.assertEqual(self.scopes(), [])
        before = list(self.backend.calls)
        self.run_plan()
        self.assertEqual(before, self.backend.calls)

    def test_wrong_existing_map_blocks_whole_mixed_plan_before_new_add(self):
        self.plan(existing=True, wrong_existing=True)
        with self.assertRaisesRegex(StateError, "EXISTING_MODEL_MAP_CHANGED"):
            self.run_plan()
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.scopes(), ["23700", "23998"])


if __name__ == "__main__":
    unittest.main()

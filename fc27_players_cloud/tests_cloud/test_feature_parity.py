from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from player_web.collection import collect_only
from player_web.existing_action_service import execute_existing_action, prepare_existing_action, prepare_unlist_preview
from player_web.model_service import export_selected_futbin_ids, intersect_database_properties, query_models, refresh_models
from player_web.repository import Repository, StateError
from player_web.settings import Settings


def configuration(root: Path, writable: bool = False) -> Settings:
    return Settings(root, "http://isolated.invalid", "https://isolated.invalid", "https://isolated.invalid",
                    "/", writable, True, 3, 5000, 3.0)


class Source:
    def __init__(self, count: int):
        self.rows = [{"resource_id": 100000 + index, "futbin_id": 200000 + index,
                      "name": f"Player {index}", "rating": 84 + index % 5} for index in range(count)]
        self.calls: list[tuple[int, int]] = []

    def get_status(self):
        return {"state": "ready"}

    def list_players(self, filters, *, page, per_page):
        days = filters.criteria.get("days_new")
        self.calls.append((int(days) if days is not None else None, page))
        start = (page - 1) * per_page
        return SimpleNamespace(total=len(self.rows), page=page, per_page=per_page,
                               items=tuple(self.rows[start:start + per_page]))


class Backend:
    authenticated = True

    def __init__(self, count: int = 431):
        self.rows = {300000 + index: {"id": 300000 + index, "gid": 1327, "cid": 9627,
                                      "futbin_id": str(400000 + index), "title": f"Player {index}",
                                      "tid": [7, 8] if index % 2 else [7], "is_rec": index % 2,
                                      "status": 1, "auto_off": 0,
                                      "more": {"extend": [{"key": "untradeable", "value": "0"}]}}
                     for index in range(count)}
        self.pages: list[int] = []
        self.writes: list[dict] = []
        self.fail_model: int | None = None

    def list_models(self, *, page, limit, search):
        assert search == [{"field": "gid", "operator": "=", "val": "1327"},
                          {"field": "cid", "operator": "=", "val": "9627"}]
        self.pages.append(page)
        values = list(self.rows.values())
        return SimpleNamespace(total=len(values), rows=tuple(dict(item) for item in values[(page - 1) * limit:page * limit]))

    def list_tags(self, *, gid, cid):
        assert (gid, cid) == (1327, 9627)
        return ({"id": 7, "name": "Core"}, {"id": 8, "name": "Promo"}, {"id": 9, "name": "Special"})

    def get_model(self, model_id):
        return dict(self.rows[model_id])

    def get_products(self, model_id):
        return ({"id": model_id + 600000, "mid": model_id, "gid": 1327, "cid": 9627,
                 "total": 4, "auto_off": 1},)

    def single_edit(self, payload):
        model_id = payload["id"][0]
        if self.fail_model == model_id:
            raise OSError("synthetic response lost")
        self.writes.append(dict(payload))
        if "tid" in payload:
            self.rows[model_id]["tid"] = list(payload["tid"])
        if "is_rec" in payload:
            self.rows[model_id]["is_rec"] = payload["is_rec"]
        return {"code": 1}


class FeatureParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root / "db" / "control.sqlite3")
        self.repo.initialize()
        self.backend = Backend()

    def tearDown(self):
        self.temp.cleanup()

    def test_manual_days_each_page_and_complete_snapshot(self):
        for days in (1, 3, 7, 14, 30):
            source = Source(437)
            result = collect_only(configuration(self.root), self.repo, client=source, days_new=days)
            self.assertEqual(source.calls, [(days, 1), (days, 2), (days, 3)])
            self.assertEqual((result["total"], result["read_count"]), (437, 437))
            self.assertEqual(len(self.repo.candidates(result["collection_id"])), 437)
            self.assertEqual(self.repo.get_collection(result["collection_id"])["filters"]["days_new"], str(days))
        with self.assertRaisesRegex(ValueError, "INVALID_DAYS_NEW"):
            collect_only(configuration(self.root), self.repo, client=Source(1), days_new=2)

    def test_large_window_is_not_truncated_at_old_5000_limit(self):
        large = replace(configuration(self.root), max_candidates=50000)
        result = collect_only(large, self.repo, client=Source(5201), days_new=30)
        self.assertEqual((result["total"], result["read_count"]), (5201, 5201))
        self.assertEqual(len(self.repo.candidates(result["collection_id"])), 5201)

    def test_incomplete_source_keeps_prior_snapshot_and_multiple_resource_versions_mark_ambiguous(self):
        good = collect_only(configuration(self.root), self.repo, client=Source(2), days_new=3)
        source = Source(201)
        source.rows[1]["futbin_id"] = source.rows[0]["futbin_id"]
        result = collect_only(configuration(self.root), self.repo, client=source, days_new=14)
        rows = self.repo.candidates(result["collection_id"])
        self.assertEqual(sum(item["identity_status"] == "ambiguous_futbin_id" for item in rows), 2)
        class Short(Source):
            def list_players(self, filters, *, page, per_page):
                response = super().list_players(filters, page=page, per_page=per_page)
                if page == 2:
                    response.items = response.items[:-1]
                return response
        with self.assertRaisesRegex(ValueError, "SOURCE_PAGE_INCOMPLETE"):
            collect_only(configuration(self.root), self.repo, client=Short(201), days_new=30)
        self.assertEqual(self.repo.last_successful_collection()["id"], result["collection_id"])
        self.assertNotEqual(good["collection_id"], result["collection_id"])

    def test_full_backend_pagination_filters_selection_and_txt(self):
        self.backend = Backend(681)
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        self.assertEqual(self.backend.pages, [1, 2, 3, 4])
        self.assertEqual((snap["total"], snap["read_count"]), (681, 681))
        first = query_models(self.repo, "operator", snap["snapshot_id"], {}, page=1)
        third = query_models(self.repo, "operator", snap["snapshot_id"], {}, page=3)
        self.assertEqual((first["total"], first["filtered_total"]), (681, 681))
        ids = [first["items"][0]["model_id"], third["items"][0]["model_id"]]
        self.assertEqual(export_selected_futbin_ids(self.repo, "operator", snap["snapshot_id"], ids),
                         b"400000\n400040\n")
        filtered = query_models(self.repo, "operator", snap["snapshot_id"],
                                {"is_rec": "1", "tag_id": "8", "tag_name": "Promo", "keyword": "Player"})
        self.assertEqual(filtered["filtered_total"], 340)
        self.assertEqual(len(filtered["filtered_model_ids"]), 340)

    def test_backend_incomplete_page_never_publishes_snapshot(self):
        original = self.backend.list_models
        def broken(*, page, limit, search):
            result = original(page=page, limit=limit, search=search)
            if page == 2:
                result.rows = result.rows[:-1]
            return result
        self.backend.list_models = broken
        with self.assertRaises(Exception):
            refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        self.assertIsNone(self.repo.latest_model_snapshot("operator"))

    def test_existing_add_tags_plan_and_execution_are_per_model(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        plan = prepare_existing_action(configuration(self.root), self.repo, self.backend, "operator",
                                       snap["snapshot_id"], [300000, 300001], "add_tags", [9])
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["items"][0]["after"]["tag_ids"], [7, 9])
        self.assertEqual(plan["items"][1]["after"]["tag_ids"], [7, 8, 9])
        self.assertEqual(self.backend.writes, [])
        execution_id, created = self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        self.assertTrue(created)
        execute_existing_action(configuration(self.root, True), self.repo, self.backend, execution_id, plan)
        result = self.repo.get_execution(execution_id, "operator")
        self.assertEqual(result["status"], "completed_readback")
        self.assertEqual([item["status"] for item in result["items"]], ["verified", "verified"])
        self.assertEqual(self.backend.writes, [{"tid": [7, 9], "id": [300000]},
                                               {"tid": [7, 8, 9], "id": [300001]}])
        self.assertEqual(self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True),
                         (execution_id, False))

    def test_remove_last_tag_blocked_before_any_write(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        plan = prepare_existing_action(configuration(self.root), self.repo, self.backend, "operator",
                                       snap["snapshot_id"], [300000, 300001], "remove_tags", [7])
        self.assertEqual(plan["blockers"], ["EMPTY_TAG_SET"])
        with self.assertRaisesRegex(StateError, "PLAN_BLOCKED"):
            self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        self.assertEqual(self.backend.writes, [])

    def test_recommend_action_ignores_unrelated_source_and_price_locks(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        plan = prepare_existing_action(configuration(self.root), self.repo, self.backend, "operator",
                                       snap["snapshot_id"], [300000], "recommend_enable", [])
        self.assertEqual(plan["blockers"], [])
        execution_id, _ = self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        execute_existing_action(configuration(self.root, True), self.repo, self.backend, execution_id, plan)
        self.assertEqual(self.backend.writes, [{"is_rec": 1, "id": [300000]}])
        self.assertEqual(self.repo.get_execution(execution_id, "operator")["status"], "completed_readback")

    def test_advanced_intersection_has_no_implicit_days_and_marks_ambiguous_cards(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        source = Source(4)
        source.rows[0]["futbin_id"] = 400000
        source.rows[1]["futbin_id"] = 400001
        source.rows[2]["futbin_id"] = 400000
        source.rows[3]["futbin_id"] = 999999
        result = intersect_database_properties(configuration(self.root), self.repo, "operator",
                                               snap["snapshot_id"], {"rating_min": "84"}, source_client=source)
        self.assertEqual(result["criteria"], {"rating_min": "84"})
        self.assertEqual(result["matched_model_ids"], [300001])
        self.assertEqual((result["unlisted_count"], result["ambiguous_count"]), (1, 2))
        self.assertEqual(source.calls, [(None, 1)])

    def test_unlist_is_readonly_preflight_with_permanent_plan_blocker(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        model = self.backend.get_model(300001)
        fake = SimpleNamespace(models={300001: model}, to_dict=lambda: {
            "product_count_by_model": {"300001": 2}, "product_ids_by_model": {"300001": [901, 902]},
            "steps": ["products.total=0", "model.status=0"],
        })
        with patch("player_web.existing_action_service._adapter", return_value=SimpleNamespace(
            plan_unlist=lambda ids: fake)):
            plan = prepare_unlist_preview(configuration(self.root), self.repo, self.backend, "operator",
                                          snap["snapshot_id"], [300001])
        self.assertEqual(plan["product_ids_by_model"], {"300001": [901, 902]})
        self.assertEqual(plan["blockers"], ["UNLIST_SEPARATE_APPROVAL_REQUIRED"])
        with self.assertRaisesRegex(StateError, "PLAN_BLOCKED"):
            self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        self.assertEqual(self.backend.writes, [])

    def test_unknown_response_keeps_scope_and_restart_does_not_replay(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        plan = prepare_existing_action(configuration(self.root), self.repo, self.backend, "operator",
                                       snap["snapshot_id"], [300000, 300001], "recommend_enable", [])
        execution_id, _ = self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        self.backend.fail_model = 300000
        with self.assertRaises(Exception):
            execute_existing_action(configuration(self.root, True), self.repo, self.backend, execution_id, plan)
        result = self.repo.get_execution(execution_id, "operator")
        self.assertEqual(result["status"], "needs_reconcile")
        self.assertEqual([item["status"] for item in result["items"]], ["unknown", "not_started"])
        self.assertEqual(self.repo.interrupted_jobs(), 0)
        self.assertEqual(self.backend.writes, [])
        next_plan = self.repo.save_plan("operator", {"scope_ids": ["400000"], "blockers": []})
        with self.assertRaisesRegex(StateError, "UNRESOLVED_IMPORT"):
            self.repo.confirm(next_plan["plan_id"], "operator", next_plan["plan_digest"], write_enabled=True)

    def test_twelfth_model_failure_persists_verified_unknown_and_not_started(self):
        snap = refresh_models(configuration(self.root), self.repo, self.backend, "operator")
        model_ids = list(range(300000, 300013))
        plan = prepare_existing_action(configuration(self.root), self.repo, self.backend, "operator",
                                       snap["snapshot_id"], model_ids, "recommend_disable", [])
        execution_id, _ = self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        self.backend.fail_model = 300011
        with self.assertRaises(Exception):
            execute_existing_action(configuration(self.root, True), self.repo, self.backend, execution_id, plan)
        statuses = [item["status"] for item in self.repo.get_execution(execution_id, "operator")["items"]]
        self.assertTrue(all(item in {"verified", "verified_no_change"} for item in statuses[:11]))
        self.assertEqual(statuses[11:], ["unknown", "not_started"])
        self.assertEqual(self.repo.interrupted_jobs(), 0)


if __name__ == "__main__":
    unittest.main()

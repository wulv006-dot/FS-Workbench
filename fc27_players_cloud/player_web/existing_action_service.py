"""已有模型标签/推荐的只读计划与逐模型持久执行；复用原 AdminAdapter。"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from 球员维护工具.admin_adapter import AdminAdapter
from 球员维护工具.existing_model_domain import ExistingModelRow

from .repository import Repository, StateError
from .settings import Settings

ACTIONS = {"add_tags", "remove_tags", "recommend_enable", "recommend_disable"}


def _adapter(settings: Settings, client: Any, stop_event: Any = None) -> AdminAdapter:
    return AdminAdapter(client, state_root=settings.data_root / "admin_state" / "shared",
                        write_enabled=False, stop_event=stop_event)


def _ids(values: Sequence[Any], label: str) -> list[int]:
    if not isinstance(values, list) or not values or len(values) > 5000:
        raise StateError(label + " 为空或超限")
    result: list[int] = []
    for value in values:
        if isinstance(value, bool) or not str(value).isascii() or not str(value).isdecimal() or int(value) < 1:
            raise StateError(label + " 含无效 ID")
        parsed = int(value)
        if parsed in result:
            raise StateError(label + " 含重复 ID")
        result.append(parsed)
    return result


def _state(row: ExistingModelRow) -> dict[str, Any]:
    return {"model_id": row.model_id, "futbin_id": row.futbin_id,
            "tag_ids": sorted(row.tag_ids), "is_rec": row.is_rec}


def prepare_existing_action(settings: Settings, repository: Repository, client: Any, owner: str,
                            snapshot_id: str, selected_model_ids: Sequence[Any],
                            action: str, selected_tag_ids: Sequence[Any]) -> dict[str, Any]:
    if not getattr(client, "authenticated", False):
        raise StateError("AUTH_REQUIRED")
    if action not in ACTIONS:
        raise StateError("动作不在白名单")
    snapshot = repository.model_snapshot(snapshot_id, owner)
    frozen = {int(row["model_id"]): row for row in repository.model_rows(snapshot_id, owner)}
    model_ids = _ids(selected_model_ids, "模型选择")
    if set(model_ids) - set(frozen):
        raise StateError("所选模型不属于完整后台快照")
    tag_ids = _ids(selected_tag_ids, "标签选择") if action in {"add_tags", "remove_tags"} else []
    if action.startswith("recommend") and selected_tag_ids:
        raise StateError("推荐动作不得附加标签变更")
    tag_catalog: dict[int, str] = {}
    if tag_ids:
        catalog_rows = client.list_tags(gid=1327, cid=9627)
        tag_catalog = {int(row["id"]): str(row.get("name") or "").strip()
                       for row in catalog_rows if row.get("id") is not None}
        if set(tag_ids) - set(tag_catalog):
            raise StateError("标签 ID 不属于当前 FC27 Players 目录")
    items: list[dict[str, Any]] = []
    futbin_ids: list[str] = []
    empty_after_remove: list[int] = []
    for model_id in model_ids:
        live = ExistingModelRow.from_mapping(client.get_model(model_id))
        cached = frozen[model_id]
        if live.model_id != model_id or live.futbin_id != str(cached.get("futbin_id") or ""):
            raise StateError("后台模型身份与快照不一致，请刷新模型")
        futbin_id = live.futbin_id
        if not futbin_id.isascii() or not futbin_id.isdecimal() or int(futbin_id) < 1:
            raise StateError("后台模型 FUTBIN ID 无法核实")
        futbin_ids.append(futbin_id)
        before = _state(live)
        after = dict(before)
        if action == "add_tags":
            after["tag_ids"] = sorted(set(before["tag_ids"]) | set(tag_ids))
        elif action == "remove_tags":
            after["tag_ids"] = sorted(set(before["tag_ids"]) - set(tag_ids))
            if set(before["tag_ids"]) & set(tag_ids) and not after["tag_ids"]:
                empty_after_remove.append(model_id)
        else:
            if before["is_rec"] not in {0, 1}:
                raise StateError("推荐状态未知，不能生成写入计划")
            after["is_rec"] = 1 if action == "recommend_enable" else 0
        items.append({"model_id": model_id, "futbin_id": futbin_id,
                      "title": live.title, "before": before, "after": after,
                      "requires_write": before != after})
    if len(futbin_ids) != len(set(futbin_ids)):
        raise StateError("后台存在重复 FUTBIN ID，拒绝生成共享写入范围")
    blockers = []
    if empty_after_remove:
        blockers.append("EMPTY_TAG_SET")
    legacy = repository.legacy_blocks(futbin_ids)
    if legacy:
        blockers.append("LEGACY_UNRESOLVED")
    payload = {"kind": "existing_action", "snapshot_id": snapshot_id,
               "snapshot_digest": snapshot["snapshot_digest"],
               "action": action, "selected_model_ids": model_ids,
               "scope_ids": futbin_ids, "tag_ids": tag_ids,
               "tag_names": {str(tag): tag_catalog[tag] for tag in tag_ids},
               "items": items, "actual_change_count": sum(item["requires_write"] for item in items),
               "no_change_count": sum(not item["requires_write"] for item in items),
               "empty_tag_model_ids": empty_after_remove,
               "legacy_unresolved_ids": legacy, "blockers": blockers}
    plan = repository.save_plan(owner, payload)
    repository.audit(owner, "existing_action_plan_created", plan["plan_id"],
                     {"action": action, "model_ids": model_ids, "tag_ids": tag_ids,
                      "blockers": blockers})
    return plan


def _verify_model(client: Any, item: Mapping[str, Any]) -> ExistingModelRow:
    row = ExistingModelRow.from_mapping(client.get_model(int(item["model_id"])))
    if _state(row) != item["before"]:
        raise StateError("PLAN_STALE")
    return row


def execute_existing_action(settings: Settings, repository: Repository, client: Any,
                            execution_id: str, plan: Mapping[str, Any], stop_event: Any = None) -> None:
    if not settings.write_enabled or (settings.data_root / "STOP_WRITES").exists():
        raise StateError("WRITE_DISABLED")
    if plan.get("kind") != "existing_action" or plan.get("action") not in ACTIONS or plan.get("blockers"):
        raise StateError("PLAN_BLOCKED")
    items = list(plan["items"])
    if repository.legacy_blocks([str(item["futbin_id"]) for item in items]):
        raise StateError("LEGACY_UNRESOLVED")
    if repository.model_snapshot(str(plan["snapshot_id"]), str(plan["owner"]))["snapshot_digest"] != plan["snapshot_digest"]:
        raise StateError("PLAN_STALE")
    # 整批预检完成前绝不触发商品 POST。
    try:
        for item in items:
            _verify_model(client, item)
    except Exception:
        repository.set_execution(execution_id, "blocked_stale", "preflight", release_scope=True)
        raise
    repository.set_execution(execution_id, "running", "preflight_complete",
                             {"total": len(items), "action": plan["action"]})
    adapter = _adapter(settings, client, stop_event)
    active_model: int | None = None
    try:
        with adapter.temporary_write_access():
            for item in items:
                model_id = int(item["model_id"])
                if stop_event is not None and callable(stop_event) and stop_event():
                    repository.set_execution(execution_id, "stopped_partial", "before_next_model",
                                             {"next_model_id": model_id})
                    return
                _verify_model(client, item)
                if not item["requires_write"]:
                    repository.set_execution_item(execution_id, model_id, "verified_no_change",
                                                  before=item["before"], after=item["before"])
                    continue
                active_model = model_id
                repository.set_execution_item(execution_id, model_id, "dispatch_intent",
                                              before=item["before"])
                action = plan["action"]
                if action == "add_tags":
                    result = adapter.add_tags([model_id], plan["tag_ids"])
                elif action == "remove_tags":
                    result = adapter.remove_tags([model_id], plan["tag_ids"])
                else:
                    result = adapter.set_recommendation([model_id], action == "recommend_enable")
                if result.get("verified") is not True:
                    raise StateError("MODEL_READBACK_INCOMPLETE")
                after = ExistingModelRow.from_mapping(client.get_model(model_id))
                if _state(after) != item["after"]:
                    raise StateError("MODEL_READBACK_CHANGED")
                repository.set_execution_item(execution_id, model_id, "verified",
                                              before=item["before"], after=_state(after))
                active_model = None
        repository.set_execution(execution_id, "completed_readback", "done",
                                 {"total": len(items), "verified": len(items)}, release_scope=True)
    except Exception as exc:
        if active_model is not None:
            repository.set_execution_item(execution_id, active_model, "unknown")
        completed = {item["model_id"] for item in repository.get_execution(execution_id, str(plan["owner"]))["items"]
                     if item["status"] in {"verified", "verified_no_change", "unknown"}}
        for item in items:
            if int(item["model_id"]) not in completed:
                repository.set_execution_item(execution_id, int(item["model_id"]), "not_started")
        repository.set_execution(execution_id, "needs_reconcile", "unknown",
                                 {"error_type": type(exc).__name__})
        raise


def prepare_unlist_preview(settings: Settings, repository: Repository, client: Any, owner: str,
                           snapshot_id: str, selected_model_ids: Sequence[Any]) -> dict[str, Any]:
    """独立下架只读预检入口；无对应写入分派路径。"""
    if not getattr(client, "authenticated", False):
        raise StateError("AUTH_REQUIRED")
    repository.model_snapshot(snapshot_id, owner)
    frozen = {int(row["model_id"]): row for row in repository.model_rows(snapshot_id, owner)}
    model_ids = _ids(selected_model_ids, "下架模型选择")
    if set(model_ids) - set(frozen):
        raise StateError("下架模型不属于完整后台快照")
    live = _adapter(settings, client).plan_unlist(model_ids)
    detail = live.to_dict()
    futbin_ids = []
    for model_id in model_ids:
        live_row = ExistingModelRow.from_mapping(live.models[model_id])
        if live_row.model_id != model_id or live_row.futbin_id != str(frozen[model_id]["futbin_id"]):
            raise StateError("下架模型身份与快照不一致")
        futbin_ids.append(live_row.futbin_id)
    payload = {"kind": "unlist_preview", "snapshot_id": snapshot_id,
               "scope_ids": futbin_ids, "selected_model_ids": model_ids,
               "product_count_by_model": detail["product_count_by_model"],
               "product_ids_by_model": detail["product_ids_by_model"],
               "steps": detail["steps"],
               "blockers": ["UNLIST_SEPARATE_APPROVAL_REQUIRED"]}
    plan = repository.save_plan(owner, payload)
    repository.audit(owner, "unlist_readonly_preflight", plan["plan_id"],
                     {"model_ids": model_ids, "product_count_by_model": detail["product_count_by_model"]})
    return plan

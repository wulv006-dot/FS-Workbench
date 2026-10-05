"""无界面的 FC27 Players 新卡计划与受控编排。"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from 球员维护工具.admin_adapter import AdminAdapter, build_existing_model_map, extract_futbin_id, extract_model_id
from 球员维护工具.models import ExportFilters
from 球员维护工具.new_card_selection import filter_rows_by_ids, validate_intent_scope
from 球员维护工具.player_database import read_futbin_ids, validate_xlsx
from 球员维护工具.rating_rules import is_low_rating_player
from 球员维护工具.transformer import convert_workbook

from .client_factory import player_client
from .repository import Repository, StateError
from .price_lock import shared_price_lock
from .settings import Settings


def _unique_ids(values: Sequence[Any], label: str) -> tuple[str, ...]:
    items = tuple(str(value).strip() for value in values)
    if not items or any(not item or not item.isascii() or not item.isdigit() or int(item) < 1 for item in items):
        raise StateError(label + " 为空或含无效 ID")
    if len(items) != len(set(items)):
        raise StateError(label + " 含重复 ID")
    return items


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _adapter(settings: Settings, admin_client: Any, stop_event: Any = None) -> AdminAdapter:
    return AdminAdapter(
        admin_client, state_root=settings.data_root / "admin_state" / "shared",
        write_enabled=False, stop_event=stop_event,
    )


def verify_manual_new_card_scope(settings: Settings, plan: Mapping[str, Any]) -> None:
    """The narrow manual switch never grants existing-model maintenance writes."""
    if settings.manual_new_cards_enabled and not settings.write_enabled:
        upload = {str(item) for item in plan.get("upload_futbin_ids") or ()}
        scope = {str(item) for item in plan.get("scope_ids") or ()}
        if not upload or scope != upload or any(
            {str(item) for item in plan.get(key) or ()} - upload
            for key in ("tag_futbin_ids", "recommend_futbin_ids")
        ):
            raise StateError("NEW_CARD_SCOPE_REQUIRED")


def verify_source_policy(settings: Settings, plan: Mapping[str, Any]) -> None:
    """A recorded HTTP exception must still match the current explicit approval."""
    if settings.player_db_base_url.startswith("http://") or plan.get("source_transport") == "http_explicitly_approved":
        expected_source = hashlib.sha256(settings.player_db_base_url.encode("utf-8")).hexdigest()[:16]
        if (not settings.http_source_approved
                or plan.get("source_transport") != "http_explicitly_approved"
                or plan.get("approved_public_http_source") != settings.approved_public_http_source
                or plan.get("source_id") != expected_source):
            raise StateError("SOURCE_TRANSPORT_UNVERIFIED")


def prepare_plan(
    settings: Settings,
    repository: Repository,
    admin_client: Any,
    owner: str,
    collection_id: str,
    upload_futbin_ids: Sequence[Any],
    tag_futbin_ids: Sequence[Any],
    recommend_futbin_ids: Sequence[Any],
    selected_tag_ids: Sequence[Any],
    *,
    source_client: Any = None,
    rating_threshold: int = 85,
) -> dict[str, Any]:
    """只读准备；选择集合、导入文件和已有模型映射都冻结进计划。"""
    if not getattr(admin_client, "authenticated", False):
        raise StateError("AUTH_REQUIRED")
    if isinstance(rating_threshold, bool) or not isinstance(rating_threshold, int) or not 40 <= rating_threshold <= 99:
        raise StateError("评分阈值必须为 40–99")
    collection = repository.get_collection(collection_id)
    if settings.http_source_approved:
        expected_source = hashlib.sha256(settings.player_db_base_url.encode("utf-8")).hexdigest()[:16]
        if collection["source_id"] != expected_source:
            raise StateError("SOURCE_CONFIG_CHANGED")
    candidates = repository.candidates(collection_id)
    candidate_by_id = {str(row["futbin_id"]): row for row in candidates
                       if row.get("identity_status", "valid") == "valid"}
    upload = _unique_ids(upload_futbin_ids, "上架范围") if upload_futbin_ids else ()
    tags = _unique_ids(tag_futbin_ids, "标签范围") if tag_futbin_ids else ()
    recommend = _unique_ids(recommend_futbin_ids, "推荐范围") if recommend_futbin_ids else ()
    scope = tuple(dict.fromkeys((*upload, *tags, *recommend)))
    if not scope or set(scope) - set(candidate_by_id):
        raise StateError("选择范围为空、身份有歧义或不属于冻结候选快照")
    tag_ids = tuple(int(item) for item in selected_tag_ids)
    if tags and (not tag_ids or any(item < 1 for item in tag_ids) or len(tag_ids) != len(set(tag_ids))):
        raise StateError("标签动作缺少有效标签 ID")
    adapter = _adapter(settings, admin_client)
    model_map = build_existing_model_map(adapter.list_all_models())
    if any(item in model_map for item in upload):
        raise StateError("上架范围中已有后台模型，必须先重新选择")
    new_tags = tuple(item for item in tags if item not in model_map)
    new_recommend = tuple(item for item in recommend if item not in model_map)
    validate_intent_scope(upload, new_tags, new_recommend)
    existing_map = {item: model_map[item] for item in scope if item in model_map}
    if tags:
        catalog = admin_client.list_tags(gid=1327, cid=9627)
        valid = {int(row.get("id")) for row in catalog if row.get("id") is not None}
        if set(tag_ids) - valid:
            raise StateError("标签 ID 不属于当前 FC27 Players 标签目录")
    artifact_path = ""
    artifact_hash = ""
    if upload:
        source = source_client or player_client(settings)
        run_dir = settings.data_root / "runs" / uuid.uuid4().hex
        run_dir.mkdir(parents=True, exist_ok=False)
        exported = run_dir / "source.xlsx"
        source.export_players(ExportFilters(collection["filters"]), exported, overwrite=False)
        transformed = convert_workbook(exported, run_dir / "transformed.xlsx")
        selected = filter_rows_by_ids(Path(transformed.output_path), run_dir / "selected_upload.xlsx", upload)
        validation = validate_xlsx(selected)
        if set(validation.futbin_ids) != set(upload) or len(validation.futbin_ids) != len(upload):
            raise StateError("上传文件 ID 与勾选范围不一致")
        core_plan = adapter.plan_import(selected)
        if set(core_plan.upload_futbin_ids) != set(upload):
            raise StateError("后台导入计划与勾选新卡不一致")
        artifact_path, artifact_hash = str(selected), _sha(selected)
    low = [item for item in scope if is_low_rating_player(candidate_by_id[item], rating_threshold)]
    missing_rating = [item for item in scope if candidate_by_id[item].get("rating") in {None, ""}]
    blockers: list[str] = []
    if missing_rating:
        blockers.append("MISSING_RATING")
    if repository.legacy_blocks(scope):
        blockers.append("LEGACY_UNRESOLVED")
    if settings.player_db_base_url.startswith("http://") and not settings.http_source_approved:
        blockers.append("SOURCE_TRANSPORT_UNVERIFIED")
    payload = {
        "kind": "new_cards", "collection_id": collection_id,
        "query_hash": collection["query_hash"], "days_new": int(collection["filters"]["days_new"]),
        "snapshot_digest": collection["snapshot_digest"],
        "source_id": collection["source_id"], "source_freshness": "unknown",
        "source_transport": settings.source_transport,
        "approved_public_http_source": settings.approved_public_http_source if settings.http_source_approved else "",
        "scope_ids": list(scope), "upload_futbin_ids": list(upload),
        "tag_futbin_ids": list(tags), "recommend_futbin_ids": list(recommend),
        "selected_tag_ids": list(tag_ids), "existing_model_map": existing_map,
        "artifact_path": artifact_path, "artifact_sha256": artifact_hash,
        "low_rating_ids": low, "missing_rating_ids": missing_rating,
        "rating_threshold": rating_threshold,
        "blockers": blockers,
        "actions": ["import"] * bool(upload) + ["tags"] * bool(tags) +
                   ["recommend"] * bool(recommend) + ["sync"] * bool(upload),
    }
    verify_manual_new_card_scope(settings, payload)
    result = repository.save_plan(owner, payload)
    repository.audit(owner, "plan_created", result["plan_id"],
                     {"scope_ids": scope, "actions": payload["actions"], "blockers": blockers})
    return result


def verify_frozen_scope(settings: Settings, admin_client: Any, plan: Mapping[str, Any]) -> None:
    """写前重新确认文件、模型与 FUTBIN 映射，状态漂移则阻断。"""
    if plan.get("gid") != 1327 or plan.get("cid") != 9627 or plan.get("blockers"):
        raise StateError("PLAN_BLOCKED")
    verify_source_policy(settings, plan)
    verify_manual_new_card_scope(settings, plan)
    upload = tuple(str(item) for item in plan.get("upload_futbin_ids") or ())
    if upload:
        artifact = Path(str(plan["artifact_path"]))
        if not artifact.is_file() or _sha(artifact) != plan["artifact_sha256"]:
            raise StateError("ARTIFACT_CHANGED")
        if set(read_futbin_ids(artifact)) != set(upload):
            raise StateError("ARTIFACT_SCOPE_CHANGED")
    adapter = _adapter(settings, admin_client)
    current = build_existing_model_map(adapter.list_all_models())
    if any(item in current for item in upload):
        raise StateError("NEW_CARD_ALREADY_EXISTS")
    for futbin_id, model_id in dict(plan.get("existing_model_map") or {}).items():
        if current.get(str(futbin_id)) != int(model_id):
            raise StateError("EXISTING_MODEL_MAP_CHANGED")


def execute_confirmed_plan(
    settings: Settings, repository: Repository, admin_client: Any,
    execution_id: str, plan: Mapping[str, Any], stop_event: Any = None,
) -> None:
    """只供已确认的单写执行器调用；任何不确定结果均留锁待人工核查。"""
    if not settings.new_card_write_enabled:
        raise StateError("WRITE_DISABLED")
    try:
        if repository.legacy_blocks(tuple(str(item) for item in plan["scope_ids"])):
            raise StateError("LEGACY_UNRESOLVED")
        verify_frozen_scope(settings, admin_client, plan)
        adapter = _adapter(settings, admin_client, stop_event)
        upload = tuple(str(item) for item in plan["upload_futbin_ids"])
        model_map = {str(key): int(value) for key, value in plan["existing_model_map"].items()}
        with adapter.temporary_write_access():
            if upload:
                repository.set_execution(execution_id, "running", "import_intent", {"futbin_ids": upload})
                outcome = adapter.import_players(Path(plan["artifact_path"]))
                if not outcome.verified or set(outcome.futbin_model_map) != set(upload):
                    raise StateError("IMPORT_READBACK_INCOMPLETE")
                model_map.update({str(key): int(value) for key, value in outcome.futbin_model_map.items()})
                repository.set_execution(execution_id, "running", "import_readback",
                                         {"model_map": model_map}, job_id=outcome.job_id)
            for action, ids in (
                ("tags", plan["tag_futbin_ids"]),
                ("recommend", plan["recommend_futbin_ids"]),
            ):
                if not ids:
                    continue
                target = [model_map[str(item)] for item in ids]
                repository.set_execution(execution_id, "running", action + "_intent", {"model_ids": target})
                result = (adapter.add_tags(target, plan["selected_tag_ids"]) if action == "tags"
                          else adapter.set_recommendation(target, True))
                if result.get("verified") is not True:
                    raise StateError(action.upper() + "_READBACK_INCOMPLETE")
                repository.set_execution(execution_id, "running", action + "_readback", {"model_ids": target})
            if upload:
                sync_ids = [model_map[item] for item in upload]
                with shared_price_lock() as acquired:
                    if not acquired:
                        repository.set_execution(execution_id, "waiting_price_lock", "sync_pending",
                                                 {"model_ids": sync_ids})
                        return
                    repository.set_execution(execution_id, "running", "sync_intent",
                                             {"model_ids": sync_ids})
                    result = adapter.sync_prices(sync_ids)
                    if result.get("verified") is not True:
                        raise StateError("SYNC_READBACK_INCOMPLETE")
                    repository.set_execution(execution_id, "running", "sync_readback",
                                             {"model_ids": sync_ids, "formula_verified": False})
            repository.set_execution(execution_id, "completed_readback", "done", {"model_map": model_map},
                                     release_scope=True)
    except Exception as exc:
        repository.set_execution(execution_id, "needs_reconcile", "unknown",
                                 {"error_type": type(exc).__name__})
        raise

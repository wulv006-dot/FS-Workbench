"""FC27 Players 后台全部模型的快照、筛选与精确 TXT 导出。"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from 球员维护工具.admin_adapter import AdminAdapter, build_existing_model_map
from 球员维护工具.player_database import PLAYER_FILTER_KEYS
from 球员维护工具.selection import extract_player_futbin_id
from 球员维护工具.existing_model_domain import (
    ExistingModelFilter, ExistingModelRow, filter_model_rows,
    format_futbin_id_export, normalize_model_rows,
)

from .repository import Repository, StateError
from .settings import Settings
from .collection import read_all_candidate_pages
from .client_factory import player_client


def _adapter(settings: Settings, client: Any) -> AdminAdapter:
    return AdminAdapter(client, state_root=settings.data_root / "admin_state" / "shared",
                        write_enabled=False)


def refresh_models(settings: Settings, repository: Repository, client: Any, owner: str) -> dict[str, Any]:
    if not getattr(client, "authenticated", False):
        raise StateError("AUTH_REQUIRED")
    raw = _adapter(settings, client).list_all_models()
    normalized = normalize_model_rows(raw)
    tag_rows = client.list_tags(gid=1327, cid=9627)
    catalog = {int(row["id"]): str(row.get("name") or "").strip()
               for row in tag_rows if row.get("id") is not None}
    safe = [{"model_id": row.model_id, "futbin_id": row.futbin_id,
             "title": row.title, "is_rec": row.is_rec, "tag_ids": list(row.tag_ids),
             "tag_names": list(row.tag_names), "status": row.status,
             "auto_off": row.auto_off} for row in normalized]
    result = repository.save_model_snapshot(owner, safe, catalog)
    repository.audit(owner, "model_snapshot_complete", result["snapshot_id"],
                     {"total": result["total"]})
    return {**result, "items": safe, "tag_catalog": catalog}


def query_models(repository: Repository, owner: str, snapshot_id: str,
                 criteria: Mapping[str, Any], *, page: int = 1, per_page: int = 20) -> dict[str, Any]:
    if not 1 <= page <= 10000 or not 1 <= per_page <= 200:
        raise StateError("模型页码或页大小无效")
    snapshot = repository.model_snapshot(snapshot_id, owner)
    rows = normalize_model_rows(repository.model_rows(snapshot_id, owner))
    allowed = {"is_rec", "tag_id", "tag_name", "keyword", "status"}
    if set(criteria) - allowed:
        raise StateError("模型筛选字段不在白名单")
    tag_catalog = {int(key): str(value) for key, value in snapshot["tag_catalog"].items()}
    matched = filter_model_rows(rows, ExistingModelFilter(**criteria), tag_catalog=tag_catalog)
    start = (page - 1) * per_page
    visible = matched[start:start + per_page]
    def item(row: ExistingModelRow) -> dict[str, Any]:
        names = tuple(dict.fromkeys((*row.tag_names,
                                     *(tag_catalog.get(tag_id, "") for tag_id in row.tag_ids))))
        return {"model_id": row.model_id, "futbin_id": row.futbin_id, "title": row.title,
                "is_rec": row.is_rec, "tag_ids": list(row.tag_ids),
                "tag_names": [name for name in names if name],
                "status": row.status, "auto_off": row.auto_off}
    return {**{key: value for key, value in snapshot.items() if key != "tag_catalog"},
            "page": page, "per_page": per_page, "filtered_total": len(matched),
            "filtered_model_ids": [row.model_id for row in matched],
            "items": [item(row) for row in visible], "tag_catalog": snapshot["tag_catalog"]}


def export_selected_futbin_ids(repository: Repository, owner: str, snapshot_id: str,
                               selected_model_ids: Sequence[Any]) -> bytes:
    rows = normalize_model_rows(repository.model_rows(snapshot_id, owner))
    by_id = {row.model_id: row for row in rows}
    if not isinstance(selected_model_ids, list) or not selected_model_ids or len(selected_model_ids) > 5000:
        raise StateError("导出选择为空或超限")
    ids: list[int] = []
    for raw in selected_model_ids:
        if isinstance(raw, bool) or not str(raw).isascii() or not str(raw).isdecimal():
            raise StateError("导出模型 ID 无效")
        value = int(raw)
        if value not in by_id or value in ids:
            raise StateError("导出模型 ID 不属于快照或重复")
        ids.append(value)
    return format_futbin_id_export([by_id[item] for item in ids]).encode("utf-8")


def intersect_database_properties(settings: Settings, repository: Repository, owner: str,
                                  snapshot_id: str, criteria: Mapping[str, Any],
                                  *, source_client: Any = None) -> dict[str, Any]:
    """独立只读高级筛选；不带默认 days_new，按明确 FUTBIN ID 求交集。"""
    if not isinstance(criteria, Mapping) or not criteria:
        raise StateError("高级筛选条件不能为空")
    if set(criteria) - set(PLAYER_FILTER_KEYS):
        raise StateError("高级筛选字段不在球员库白名单")
    clean = {key: value for key, value in criteria.items() if value is not None and str(value).strip()}
    if not clean:
        raise StateError("高级筛选条件不能为空")
    repository.model_snapshot(snapshot_id, owner)
    model_map = build_existing_model_map(repository.model_rows(snapshot_id, owner))
    source = source_client or player_client(settings)
    if not isinstance(source.get_status(), Mapping):
        raise StateError("球员库状态不可核实")
    total, rows = read_all_candidate_pages(source, clean, settings.max_candidates)
    ids = [extract_player_futbin_id(row) for row in rows]
    counts = Counter(ids)
    ambiguous = {item for item, count in counts.items() if count > 1}
    matched: list[int] = []
    matched_ids: set[int] = set()
    unlisted = 0
    for futbin_id in ids:
        if futbin_id in ambiguous:
            continue
        model_id = model_map.get(str(futbin_id))
        if model_id is None:
            unlisted += 1
        elif model_id not in matched_ids:
            matched.append(model_id)
            matched_ids.add(model_id)
    return {"snapshot_id": snapshot_id, "criteria": clean, "source_total": total,
            "read_count": len(rows), "matched_model_count": len(matched),
            "matched_model_ids": matched, "unlisted_count": unlisted,
            "ambiguous_count": sum(counts[item] for item in ambiguous),
            "ambiguous_futbin_ids": sorted(ambiguous),
            "source_freshness": "unknown"}

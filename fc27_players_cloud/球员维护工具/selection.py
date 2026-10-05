"""按数据库筛选结果生成后台已有球员模型 ID 名单。

这个模块只负责读取筛选结果、完整校验分页并计算与后台模型的交集。
它不包含任何后台写入动作；GUI 需要在用户确认后才把结果放入模型 ID 文本框。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .admin_adapter import build_existing_model_map
from .models import ExportFilters


DEFAULT_SELECTION_PAGE_SIZE = 200
DEFAULT_SELECTION_LIMIT = 2000
_FUTBIN_ID_KEYS = ("futbin_id", "futbinId", "FUTBIN ID")


class SelectionError(ValueError):
    """筛选结果无法安全转换成后台模型 ID 名单。"""


class SelectionLimitExceeded(SelectionError):
    """筛选命中超过有界候选上限，拒绝截断后继续。"""


@dataclass(frozen=True)
class ExistingModelSelection:
    """筛选球员和后台已有模型的交集。"""

    total: int
    items: tuple[Mapping[str, Any], ...]
    existing_futbin_ids: tuple[str, ...]
    missing_futbin_ids: tuple[str, ...]
    model_ids: tuple[int, ...]
    model_id_by_futbin: Mapping[str, int]
    backend_model_count: int

    @property
    def filtered_count(self) -> int:
        return self.total

    @property
    def existing_count(self) -> int:
        return len(self.existing_futbin_ids)

    @property
    def missing_count(self) -> int:
        return len(self.missing_futbin_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "filtered_count": self.filtered_count,
            "existing_futbin_ids": list(self.existing_futbin_ids),
            "missing_futbin_ids": list(self.missing_futbin_ids),
            "model_ids": list(self.model_ids),
            "model_id_by_futbin": dict(self.model_id_by_futbin),
            "backend_model_count": self.backend_model_count,
            "existing_count": self.existing_count,
            "missing_count": self.missing_count,
        }


def _filter_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return bool(value)
    return True


def filter_criteria(filters: ExportFilters | Mapping[str, Any] | None) -> dict[str, Any]:
    """取得筛选条件，并要求至少有一项非空条件。"""

    if filters is None:
        criteria: Mapping[str, Any] = {}
    elif isinstance(filters, ExportFilters):
        criteria = filters.criteria
    elif isinstance(filters, Mapping):
        raw = filters.get("criteria", filters)
        if not isinstance(raw, Mapping):
            raise SelectionError("筛选条件必须是对象")
        criteria = raw
    else:
        raise SelectionError("筛选条件必须是 ExportFilters 或对象")
    result = {str(key): value for key, value in criteria.items() if _filter_value_present(value)}
    if not result:
        raise SelectionError("生成后台已有模型 ID 前，数据库筛选至少填写一项")
    return result


def extract_player_futbin_id(item: Mapping[str, Any]) -> str | None:
    """只从明确的 FUTBIN ID 字段读取，不从名称等字段推断。"""

    values: list[str] = []
    for key in _FUTBIN_ID_KEYS:
        if key in item and item[key] is not None and str(item[key]).strip():
            values.append(str(item[key]).strip())
    if not values:
        return None
    if len(set(values)) != 1:
        raise SelectionError("数据库筛选结果同一行含冲突 FUTBIN ID")
    return values[0]


def collect_filtered_players(
    client: Any,
    filters: ExportFilters | Mapping[str, Any] | None,
    *,
    per_page: int = DEFAULT_SELECTION_PAGE_SIZE,
    max_candidates: int = DEFAULT_SELECTION_LIMIT,
) -> tuple[int, tuple[Mapping[str, Any], ...]]:
    """调用只读球员接口并完整收集分页结果。"""

    if per_page < 1 or per_page > DEFAULT_SELECTION_PAGE_SIZE:
        raise ValueError(f"per_page 必须在 1 到 {DEFAULT_SELECTION_PAGE_SIZE} 之间")
    if max_candidates < 1:
        raise ValueError("max_candidates 必须大于 0")
    criteria = filter_criteria(filters)
    page = 1
    expected_total: int | None = None
    rows: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    while True:
        result = client.list_players(ExportFilters(dict(criteria)), page=page, per_page=per_page)
        total = getattr(result, "total", None)
        if not isinstance(total, int) or total < 0:
            raise SelectionError("数据库筛选结果缺少有效 total，已停止")
        if expected_total is None:
            expected_total = total
            if total > max_candidates:
                raise SelectionLimitExceeded(
                    f"数据库筛选命中 {total} 个球员，超过安全上限 {max_candidates}；请缩小筛选条件后重新生成"
                )
        elif total != expected_total:
            raise SelectionError("数据库筛选分页 total 不一致，已停止")

        returned_page = getattr(result, "page", None)
        returned_per_page = getattr(result, "per_page", None)
        if returned_page != page or returned_per_page != per_page:
            raise SelectionError(
                f"数据库筛选分页回显不一致：要求 page={page}, per_page={per_page}，"
                f"实际 page={returned_page}, per_page={returned_per_page}"
            )
        items = getattr(result, "items", None)
        if not isinstance(items, (tuple, list)):
            raise SelectionError("数据库筛选结果 items 不是列表，已停止")
        if len(items) > per_page:
            raise SelectionError("数据库筛选单页返回行数超过 per_page，已停止")
        if len(rows) + len(items) > expected_total:
            raise SelectionError("数据库筛选返回行数超过 total，已停止")
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise SelectionError(f"数据库筛选结果第 {len(rows) + index + 1} 行不是对象")
            futbin_id = extract_player_futbin_id(item)
            if not futbin_id:
                raise SelectionError(f"数据库筛选结果第 {len(rows) + index + 1} 行缺少明确 FUTBIN ID")
            if futbin_id in seen_ids:
                raise SelectionError(f"数据库筛选结果含重复 FUTBIN ID：{futbin_id}")
            seen_ids.add(futbin_id)
            rows.append(item)

        if expected_total == len(rows):
            break
        if not items:
            raise SelectionError("数据库筛选分页提前结束，未达到 total")
        if len(items) < per_page:
            raise SelectionError("数据库筛选分页提前结束，未达到 total")
        page += 1

    return expected_total or 0, tuple(rows)


def intersect_existing_models(
    total: int,
    items: Sequence[Mapping[str, Any]],
    model_rows: Sequence[Mapping[str, Any]],
) -> ExistingModelSelection:
    """纯函数：把数据库球员与后台模型映射按 FUTBIN ID 求交集。"""

    if total != len(items):
        raise SelectionError(f"筛选 total 与收集行数不一致：{total} != {len(items)}")
    existing_map = build_existing_model_map(model_rows)
    existing: list[str] = []
    missing: list[str] = []
    model_ids: list[int] = []
    selected_mapping: dict[str, int] = {}
    for index, item in enumerate(items):
        futbin_id = extract_player_futbin_id(item)
        if not futbin_id:
            raise SelectionError(f"数据库筛选结果第 {index + 1} 行缺少明确 FUTBIN ID")
        model_id = existing_map.get(futbin_id)
        if model_id is None:
            missing.append(futbin_id)
            continue
        existing.append(futbin_id)
        model_ids.append(model_id)
        selected_mapping[futbin_id] = model_id
    return ExistingModelSelection(
        total=total,
        items=tuple(items),
        existing_futbin_ids=tuple(existing),
        missing_futbin_ids=tuple(missing),
        model_ids=tuple(model_ids),
        model_id_by_futbin=selected_mapping,
        backend_model_count=len(model_rows),
    )


def generate_existing_model_selection(
    player_client: Any,
    admin_adapter: Any,
    filters: ExportFilters | Mapping[str, Any] | None,
    *,
    per_page: int = DEFAULT_SELECTION_PAGE_SIZE,
    max_candidates: int = DEFAULT_SELECTION_LIMIT,
) -> ExistingModelSelection:
    """完整生成名单：数据库只读分页 + 后台只读全量模型交集。"""

    total, items = collect_filtered_players(
        player_client,
        filters,
        per_page=per_page,
        max_candidates=max_candidates,
    )
    model_rows = admin_adapter.list_all_models()
    return intersect_existing_models(total, items, model_rows)


__all__ = [
    "DEFAULT_SELECTION_LIMIT",
    "DEFAULT_SELECTION_PAGE_SIZE",
    "ExistingModelSelection",
    "SelectionError",
    "SelectionLimitExceeded",
    "collect_filtered_players",
    "extract_player_futbin_id",
    "filter_criteria",
    "generate_existing_model_selection",
    "intersect_existing_models",
]

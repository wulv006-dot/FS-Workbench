"""新卡导入后的安全断点恢复。

这个模块只处理本地 journal 的读取、校验和范围计算。它不会读取配置文件、
不会从旧的手动模型 ID 推断范围，也不会调用任何后台写入接口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


RECOVERABLE_STEPS = ("tags", "recommend", "sync")
_TERMINAL_OR_UNSAFE = {"success", "running", "failed", "unknown", "partial_or_unknown"}
_RECOVERABLE_STATUSES = {"pending", "skipped_after_failure"}


class BatchRecoveryBlocked(ValueError):
    """历史批次缺少可证明安全边界，拒绝后续写入。"""


def _clean_ids(values: Any, label: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise BatchRecoveryBlocked(f"{label} 缺少冻结 ID 列表")
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        if item in result:
            raise BatchRecoveryBlocked(f"{label} 含重复 ID：{item}")
        result.append(item)
    return tuple(result)


def _model_map(value: Any, expected: Sequence[str]) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise BatchRecoveryBlocked("历史批次没有已核验的 futbin_model_map")
    result: dict[str, int] = {}
    for key, raw_model_id in value.items():
        futbin_id = str(key).strip()
        if not futbin_id:
            raise BatchRecoveryBlocked("futbin_model_map 含空 FUTBIN ID")
        try:
            model_id = int(raw_model_id)
        except (TypeError, ValueError) as exc:
            raise BatchRecoveryBlocked(f"FUTBIN {futbin_id} 的模型 ID 无效") from exc
        if model_id < 1:
            raise BatchRecoveryBlocked(f"FUTBIN {futbin_id} 的模型 ID 必须大于 0")
        if futbin_id in result or model_id in result.values():
            raise BatchRecoveryBlocked("futbin_model_map 含重复 FUTBIN ID 或模型 ID")
        result[futbin_id] = model_id
    if not expected:
        if result:
            raise BatchRecoveryBlocked("没有冻结上架 FUTBIN ID 却存在导入模型映射")
        return {}
    if set(result) != set(expected):
        raise BatchRecoveryBlocked("导入成功映射与冻结上架 FUTBIN ID 不一致，需只读复核")
    return result


def _read_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


@dataclass(frozen=True)
class NewCardBatch:
    """一个可被恢复入口展示的、只读校验后的新卡批次。"""

    journal_path: Path
    run_id: str
    started_at: str
    status: str
    steps: Mapping[str, str]
    expected_upload_futbin_ids: tuple[str, ...]
    selected_tag_futbin_ids: tuple[str, ...]
    selected_recommend_futbin_ids: tuple[str, ...]
    futbin_model_map: Mapping[str, int]
    existing_model_map: Mapping[str, int]
    selected_tag_ids: tuple[int, ...]
    recommend_enabled: bool | None

    @property
    def run_dir(self) -> Path:
        return self.journal_path.parent

    @property
    def display_name(self) -> str:
        stamp = self.started_at.replace("T", " ")[:19] if self.started_at else "无时间"
        import_state = self.steps.get("import", "unknown")
        return f"{self.run_id}｜导入{('成功' if import_state == 'success' else '跳过')} {len(self.futbin_model_map)} 条｜{stamp}"


def load_new_card_batch(journal_path: str | Path) -> NewCardBatch:
    path = Path(journal_path).expanduser()
    raw = _read_mapping(path)
    if raw is None:
        raise BatchRecoveryBlocked(f"无法读取批次 journal：{path}")
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, Mapping) or str(steps_raw.get("import") or "") not in {"success", "skipped"}:
        raise BatchRecoveryBlocked("该批次导入没有 success/skipped 状态，禁止后续操作")
    expected = _clean_ids(raw.get("expected_upload_futbin_ids"), "expected_upload_futbin_ids")
    model_map = _model_map(raw.get("futbin_model_map"), expected)
    selected_tags = _clean_ids(raw.get("selected_tag_futbin_ids", []), "selected_tag_futbin_ids")
    selected_recommend = _clean_ids(raw.get("selected_recommend_futbin_ids", []), "selected_recommend_futbin_ids")
    existing_action_ids = tuple(
        dict.fromkeys(
            item
            for item in (*selected_tags, *selected_recommend)
            if item not in set(expected)
        )
    )
    existing_model_map = _existing_model_map(raw.get("existing_model_map", {}), existing_action_ids)
    if not expected and not existing_model_map:
        raise BatchRecoveryBlocked("批次没有导入模型或已有模型动作范围，禁止后续操作")
    if set(model_map.values()) & set(existing_model_map.values()):
        raise BatchRecoveryBlocked("导入模型映射与已有模型映射含重复模型 ID")

    raw_tag_ids = raw.get("selected_tag_ids")
    if raw_tag_ids is None:
        selected_tag_ids: tuple[int, ...] = ()
    elif isinstance(raw_tag_ids, (list, tuple)):
        tag_values: list[int] = []
        for value in raw_tag_ids:
            try:
                tag_id = int(value)
            except (TypeError, ValueError) as exc:
                raise BatchRecoveryBlocked("历史批次的冻结标签 ID 无效") from exc
            if tag_id < 1 or tag_id in tag_values:
                raise BatchRecoveryBlocked("历史批次的冻结标签 ID 无效或重复")
            tag_values.append(tag_id)
        selected_tag_ids = tuple(tag_values)
    else:
        raise BatchRecoveryBlocked("历史批次的冻结标签 ID 格式无效")

    recommend_enabled = raw.get("recommend_enabled")
    if recommend_enabled is not None and not isinstance(recommend_enabled, bool):
        raise BatchRecoveryBlocked("历史批次的冻结推荐动作无效")
    steps = {str(key): str(value) for key, value in steps_raw.items()}
    return NewCardBatch(
        journal_path=path,
        run_id=path.parent.name,
        started_at=str(raw.get("started_at") or ""),
        status=str(raw.get("status") or "unknown"),
        steps=steps,
        expected_upload_futbin_ids=expected,
        selected_tag_futbin_ids=selected_tags,
        selected_recommend_futbin_ids=selected_recommend,
        futbin_model_map=model_map,
        existing_model_map=existing_model_map,
        selected_tag_ids=selected_tag_ids,
        recommend_enabled=recommend_enabled,
    )


def _existing_model_map(value: Any, expected: Sequence[str]) -> dict[str, int]:
    """解析批次创建时冻结的已有卡映射。

    已有卡映射只允许覆盖标签/推荐动作中、且不属于本次导入集合的
    FUTBIN ID。缺失或多余条目都阻断恢复，避免把动作静默缩小或扩大。
    """

    if not expected:
        if value in (None, {}):
            return {}
        if not isinstance(value, Mapping) or value:
            raise BatchRecoveryBlocked("历史批次含无动作范围的已有模型映射")
        return {}
    if not isinstance(value, Mapping):
        raise BatchRecoveryBlocked("历史批次没有有效的 existing_model_map")
    result: dict[str, int] = {}
    for key, raw_model_id in value.items():
        futbin_id = str(key).strip()
        if not futbin_id:
            raise BatchRecoveryBlocked("existing_model_map 含空 FUTBIN ID")
        try:
            model_id = int(raw_model_id)
        except (TypeError, ValueError) as exc:
            raise BatchRecoveryBlocked(f"已有 FUTBIN {futbin_id} 的模型 ID 无效") from exc
        if model_id < 1:
            raise BatchRecoveryBlocked(f"已有 FUTBIN {futbin_id} 的模型 ID 必须大于 0")
        if futbin_id in result or model_id in result.values():
            raise BatchRecoveryBlocked("existing_model_map 含重复 FUTBIN ID 或模型 ID")
        result[futbin_id] = model_id
    expected_set = set(expected)
    if set(result) != expected_set:
        missing = sorted(expected_set - set(result))
        extra = sorted(set(result) - expected_set)
        detail = []
        if missing:
            detail.append(f"缺少 {', '.join(missing)}")
        if extra:
            detail.append(f"多出 {', '.join(extra)}")
        raise BatchRecoveryBlocked("冻结已有卡映射与动作范围不一致：" + "；".join(detail))
    return result


def _candidate_ids(batch: NewCardBatch, step: str) -> tuple[str, ...]:
    if step == "tags":
        frozen = batch.selected_tag_futbin_ids
    elif step == "recommend":
        frozen = batch.selected_recommend_futbin_ids
    elif step == "sync":
        frozen = batch.expected_upload_futbin_ids
    else:
        raise BatchRecoveryBlocked(f"不可恢复的步骤：{step}")
    expected = set(batch.expected_upload_futbin_ids)
    mapped = set(batch.futbin_model_map) | set(batch.existing_model_map)
    allowed = expected | set(batch.existing_model_map)
    invalid = [item for item in frozen if item not in allowed]
    if invalid:
        raise BatchRecoveryBlocked(
            f"步骤 {step} 的冻结 FUTBIN ID 没有本批已核验映射：{', '.join(invalid)}"
        )
    missing = [item for item in frozen if item not in mapped]
    if missing:
        raise BatchRecoveryBlocked(
            f"步骤 {step} 的冻结 FUTBIN ID 映射缺失：{', '.join(missing)}"
        )
    return tuple(frozen)


def resolve_recovery_scope(batch: NewCardBatch, step: str) -> tuple[str, tuple[int, ...]]:
    """返回冻结 FUTBIN ID 和对应模型 ID；绝不扩大到其它 ID。"""

    step = str(step).strip().lower()
    if step not in RECOVERABLE_STEPS:
        raise BatchRecoveryBlocked(f"不可恢复的步骤：{step}")
    status = str(batch.steps.get(step) or "unknown")
    if status not in _RECOVERABLE_STATUSES:
        if status in _TERMINAL_OR_UNSAFE:
            raise BatchRecoveryBlocked(f"步骤 {step} 当前状态为 {status}，为避免重复写入已阻断；请只读复核或手工处理")
        raise BatchRecoveryBlocked(f"步骤 {step} 状态未知：{status}，已阻断")
    futbin_ids = _candidate_ids(batch, step)
    if not futbin_ids:
        raise BatchRecoveryBlocked(f"步骤 {step} 的冻结范围与已核验模型映射交集为空")
    all_model_map = {**batch.futbin_model_map, **batch.existing_model_map}
    model_ids: list[int] = []
    for futbin_id in futbin_ids:
        model_id = int(all_model_map[futbin_id])
        if model_id not in model_ids:
            model_ids.append(model_id)
    if not model_ids:
        raise BatchRecoveryBlocked(f"步骤 {step} 没有可核验模型 ID")
    if step == "tags" and not batch.selected_tag_ids:
        raise BatchRecoveryBlocked("历史批次没有冻结标签 ID，不能从旧配置或手工输入补范围")
    if step == "recommend" and batch.recommend_enabled is None:
        raise BatchRecoveryBlocked("历史批次没有冻结推荐动作，不能从旧配置补动作")
    return futbin_ids, tuple(model_ids)


def find_new_card_batches(app_dir: str | Path) -> tuple[NewCardBatch, ...]:
    """只读扫描工具自己的 runs/new_card_flow 目录，损坏批次会被跳过。"""

    root = Path(app_dir).expanduser()
    base = root / "runs" / "new_card_flow"
    if not base.is_dir():
        return ()
    result: list[NewCardBatch] = []
    for path in sorted(base.glob("run_*/new_card_journal.json"), reverse=True):
        try:
            result.append(load_new_card_batch(path))
        except BatchRecoveryBlocked:
            continue
    return tuple(result)


def safe_result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """把后台动作结果缩成可写入 journal 的非原始响应摘要。"""

    allowed = {"verified", "status", "formula_verified", "is_rec", "price_source"}
    summary = {key: result[key] for key in allowed if key in result}
    model_ids = result.get("model_ids")
    if isinstance(model_ids, (list, tuple)):
        summary["model_ids"] = [int(value) for value in model_ids]
    return summary


__all__ = [
    "BatchRecoveryBlocked",
    "NewCardBatch",
    "RECOVERABLE_STEPS",
    "find_new_card_batches",
    "load_new_card_batch",
    "resolve_recovery_scope",
    "safe_result_summary",
]

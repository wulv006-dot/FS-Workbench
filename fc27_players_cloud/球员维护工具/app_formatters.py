"""模块级格式化与汇总函数。"""

from __future__ import annotations

from typing import Any
from typing import Mapping
from typing import Optional
from 球员维护工具.new_card_recovery import NewCardBatch
from 球员维护工具.new_card_recovery import RECOVERABLE_STEPS
from 球员维护工具.storage import redact_text
import sys
from pathlib import Path

if __package__:
    from .app_constants import STEP_LABELS
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 球员维护工具.app_constants import STEP_LABELS

def _new_card_status_label(status: Any) -> str:
    labels = {
        "success": "成功",
        "verified": "成功（已核验）",
        "completed_readback": "成功（已回读）",
        "skipped": "跳过",
        "pending": "待执行",
        "skipped_after_failure": "失败后跳过",
        "failed": "失败",
        "running": "执行中",
    }
    value = str(status or "unknown")
    return labels.get(value, value)


def _new_card_action_status(result: Mapping[str, Any], action: str) -> str:
    value = result.get(action)
    if isinstance(value, Mapping):
        raw_status = value.get("status")
        if raw_status:
            return _new_card_status_label(raw_status)
        if value.get("verified") is True:
            return "成功（已核验）"
    if action in {"tags", "recommend"}:
        return "跳过（未勾选）"
    return "未知"


def _model_ids_text(values: Any) -> str:
    if not isinstance(values, (list, tuple)):
        return "无"
    result: list[str] = []
    for value in values:
        try:
            model_id = int(value)
        except (TypeError, ValueError):
            continue
        if model_id > 0 and str(model_id) not in result:
            result.append(str(model_id))
    return ", ".join(result) if result else "无"


def _safe_existing_model_action_error(action: str, model_ids: Any, exc: BaseException) -> dict[str, Any]:
    """构造已有模型动作错误摘要；只保留模型数量和脱敏批次状态。"""

    selected = model_ids if isinstance(model_ids, (list, tuple)) else ()
    payload: dict[str, Any] = {
        "action": str(action),
        "model_count": len(selected),
        "error_type": type(exc).__name__,
        "message": redact_text(exc),
    }
    raw_report = getattr(exc, "report", None)
    if not isinstance(raw_report, Mapping):
        return payload

    report: dict[str, Any] = {}
    for key in ("status", "operation", "completed_count", "total_count", "failed_model_id"):
        value = raw_report.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            report[key] = value
    for key in ("completed_model_ids", "pending_model_ids"):
        value = raw_report.get(key)
        if isinstance(value, (list, tuple)):
            ids: list[int] = []
            for item in value:
                try:
                    model_id = int(item)
                except (TypeError, ValueError):
                    continue
                if model_id > 0 and model_id not in ids:
                    ids.append(model_id)
            report[key] = ids
    readback = raw_report.get("failed_model_readback")
    if isinstance(readback, Mapping):
        safe_readback: dict[str, Any] = {}
        for key in ("status", "error_type", "tag_count"):
            value = readback.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_readback[key] = value
        if safe_readback:
            report["failed_model_readback"] = safe_readback
    diagnostic = raw_report.get("diagnostic")
    if isinstance(diagnostic, Mapping):
        safe_diagnostic: dict[str, Any] = {}
        for key in ("method", "endpoint", "http_status", "response_code", "response_msg"):
            value = diagnostic.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_diagnostic[key] = redact_text(value) if isinstance(value, str) else value
        if safe_diagnostic:
            report["diagnostic"] = safe_diagnostic
    if report:
        payload["report"] = report
    return payload


def _format_existing_model_action_error(payload: Any) -> str:
    """生成可直接显示的已有模型动作错误提示。"""

    if not isinstance(payload, Mapping):
        return redact_text(payload)
    action = str(payload.get("action") or "后台模型动作")
    count = payload.get("model_count")
    error_type = str(payload.get("error_type") or "未知异常")
    lines = [f"动作：{action}；选择模型：{count if count is not None else '缺数据'} 个；异常类型：{error_type}"]
    report = payload.get("report")
    if isinstance(report, Mapping):
        status = report.get("status")
        if status:
            lines.append(f"状态：{status}")
        if report.get("completed_count") is not None and report.get("total_count") is not None:
            lines.append(f"已完成：{report['completed_count']}/{report['total_count']} 个")
        if report.get("failed_model_id") is not None:
            lines.append(f"失败模型 ID：{report['failed_model_id']}")
        readback = report.get("failed_model_readback")
        if isinstance(readback, Mapping) and readback.get("status"):
            lines.append(f"失败模型只读回查：{readback['status']}")
    message = str(payload.get("message") or "")
    if message:
        lines.append(f"安全消息：{redact_text(message)}")
    if isinstance(report, Mapping) and report.get("status") in {"partial_or_unknown", "unknown"}:
        lines.append("已停止后续写入；请先只读回查，禁止盲目重试。")
    return "\n".join(lines)


def format_new_card_completion(result: Mapping[str, Any]) -> str:
    """为新卡完整流程生成与实际步骤一致的完成摘要。"""

    imported_ids = result.get("model_ids") if isinstance(result, Mapping) else ()
    imported_count = len(imported_ids) if isinstance(imported_ids, (list, tuple)) else 0
    existing_map = result.get("existing_model_map") if isinstance(result, Mapping) else {}
    existing_count = len(existing_map) if isinstance(existing_map, Mapping) else 0
    import_status = _new_card_action_status(result, "import")
    sync_status = _new_card_action_status(result, "sync")
    tag_ids = result.get("tag_model_ids") if isinstance(result, Mapping) else ()
    recommend_ids = result.get("recommend_model_ids") if isinstance(result, Mapping) else ()
    lines = [
        "本批次新卡动作已完成并按结果记录：",
        f"导入：{import_status}；新建模型 {imported_count} 条；模型 ID：{_model_ids_text(imported_ids)}",
        f"加标签：{_new_card_action_status(result, 'tags')}；模型 ID：{_model_ids_text(tag_ids)}",
        f"开推荐：{_new_card_action_status(result, 'recommend')}；模型 ID：{_model_ids_text(recommend_ids)}",
        f"金币价同步：{sync_status}",
        f"已有模型冻结并处理：{existing_count} 条",
    ]
    if import_status == "跳过":
        lines.append("本批没有新卡上架选择，导入已跳过。")
    if sync_status == "跳过":
        lines.append("本批没有新导入模型，金币价同步已跳过。")
    lines.append("研发采价/补图等后台外部动作仍以后台实际状态为准。")
    return "\n".join(lines)


def format_new_card_batch_summary(batch: NewCardBatch) -> str:
    """为恢复下拉框生成不把已有模型误报成新导入的摘要。"""

    model_map = {**dict(batch.futbin_model_map), **dict(batch.existing_model_map)}
    tag_model_ids = [model_map[item] for item in batch.selected_tag_futbin_ids if item in model_map]
    recommend_model_ids = [model_map[item] for item in batch.selected_recommend_futbin_ids if item in model_map]
    tag_scope = f"{len(batch.selected_tag_futbin_ids)} 条 / 模型 ID：{_model_ids_text(tag_model_ids)}"
    recommend_scope = f"{len(batch.selected_recommend_futbin_ids)} 条 / 模型 ID：{_model_ids_text(recommend_model_ids)}"
    steps = "; ".join(
        f"{STEP_LABELS.get(step, step)}={_new_card_status_label(batch.steps.get(step, 'unknown'))}"
        for step in ("import", *RECOVERABLE_STEPS)
    )
    return (
        f"批次 {batch.run_id}：新建模型 {len(batch.futbin_model_map)} 条；"
        f"已有模型 {len(batch.existing_model_map)} 条；{steps}；"
        f"标签范围 {tag_scope}；推荐范围 {recommend_scope}；"
        "选择单步后仍需逐项确认；范围由历史批次冻结"
    )




def parse_player_rating(value: Any) -> Optional[int]:
    """把数据库/Excel 的评分字段解析为整数；无法解析时返回 None。

    覆盖 int/float/纯数字字符串/"84.0" 这类小数字符串；布尔值与其他
    内容一律返回 None，交给调用方决定是否需要人工评估。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def is_low_rating_player(player: Optional[Mapping[str, Any]], threshold: int) -> bool:
    """评分低于阈值视为低分卡；评分缺失/无法解析时不判为低分，留给人工评估。"""
    if player is None:
        return False
    rating = parse_player_rating(player.get("rating"))
    return rating is not None and rating < threshold


def new_card_rating_threshold(raw: Any, default: int = 85) -> int:
    """读取界面阈值输入；非法值回落默认 85，范围 40–99。"""
    value = parse_player_rating(raw)
    if value is None:
        return default
    return max(40, min(99, value))

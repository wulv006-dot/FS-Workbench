"""公共数据模型。

这些模型刻意不包含价格、评分或未知球员字段，避免基础设施层产生业务
假设。所有模型都可以安全地序列化到 JSON。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional


def utc_now_iso() -> str:
    """返回带时区的 UTC 时间，便于日志排序和跨机器查看。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StepName(str, Enum):
    EXPORT = "export"
    TRANSFORM = "transform"
    IMPORT = "import"
    TAGS = "tags"
    RECOMMEND = "recommend"
    SYNC = "sync"

    @classmethod
    def values(cls) -> List[str]:
        return [item.value for item in cls]


class StepStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"
    STOPPED = "stopped"


@dataclass
class ExportFilters:
    """GUI 可保存的导出筛选。

    ``criteria`` 只保存用户提供的结构，不在基础设施层推断字段含义。
    """

    criteria: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"criteria": dict(self.criteria)}


@dataclass
class PipelineConfig:
    schema_version: int = 1
    source_path: str = ""
    output_root: str = "runs"
    export_filters: ExportFilters = field(default_factory=ExportFilters)
    manual_player_ids: List[str] = field(default_factory=list)
    manual_model_ids: List[str] = field(default_factory=list)
    manual_tags: List[str] = field(default_factory=list)
    manual_tag_ids: List[str] = field(default_factory=list)
    # 兼容旧配置的布尔字段；新 GUI 使用 recommend_mode，默认不触发推荐写入。
    recommend_enabled: Optional[bool] = None
    recommend_mode: str = "unchanged"
    tag_scope: str = "manual_ids"
    recommend_scope: str = "manual_ids"
    sync_scope: str = "current_batch"
    existing_player_policy: str = "new_only"
    selected_steps: List[str] = field(default_factory=lambda: StepName.values())

    def normalized(self) -> "PipelineConfig":
        """返回副本并去除空白值；不添加任何业务默认阈值。"""

        ids = _clean_lines(self.manual_player_ids)
        tags = _clean_lines(self.manual_tags)
        steps: List[str] = []
        for item in self.selected_steps:
            value = str(item).strip().lower()
            if value in StepName.values() and value not in steps:
                steps.append(value)
        mode = str(self.recommend_mode or "unchanged").strip().lower()
        if mode not in {"unchanged", "enable", "disable"}:
            raise ValueError("recommend_mode 必须是 unchanged、enable 或 disable")
        # 旧调用方传入 bool 时转换为三态；新配置的 None 表示不变。
        if mode == "unchanged" and self.recommend_enabled is not None:
            mode = "enable" if bool(self.recommend_enabled) else "disable"
        tag_scope = str(self.tag_scope or "manual_ids").strip().lower()
        recommend_scope = str(self.recommend_scope or "manual_ids").strip().lower()
        sync_scope = str(self.sync_scope or "current_batch").strip().lower()
        allowed_scopes = {"manual_ids", "current_batch"}
        if tag_scope not in allowed_scopes or recommend_scope not in allowed_scopes or sync_scope not in allowed_scopes:
            raise ValueError("标签/推荐范围必须是 manual_ids 或 current_batch")
        policy = str(self.existing_player_policy or "new_only").strip().lower()
        if policy != "new_only":
            raise ValueError("当前只允许新增，不允许覆盖已有球员")
        return PipelineConfig(
            schema_version=int(self.schema_version or 1),
            source_path=str(self.source_path or "").strip(),
            output_root=str(self.output_root or "runs").strip() or "runs",
            export_filters=ExportFilters(dict(self.export_filters.criteria)),
            manual_player_ids=ids,
            manual_model_ids=_clean_lines(self.manual_model_ids),
            manual_tags=tags,
            manual_tag_ids=_clean_lines(self.manual_tag_ids),
            recommend_enabled=None if mode == "unchanged" else mode == "enable",
            recommend_mode=mode,
            tag_scope=tag_scope,
            recommend_scope=recommend_scope,
            sync_scope=sync_scope,
            existing_player_policy=policy,
            selected_steps=steps,
        )

    def to_dict(self) -> Dict[str, Any]:
        config = self.normalized()
        return {
            "schema_version": config.schema_version,
            "source_path": config.source_path,
            "output_root": config.output_root,
            "export_filters": config.export_filters.to_dict(),
            "manual_player_ids": config.manual_player_ids,
            "manual_model_ids": config.manual_model_ids,
            "manual_tags": config.manual_tags,
            "manual_tag_ids": config.manual_tag_ids,
            "recommend_enabled": config.recommend_enabled,
            "recommend_mode": config.recommend_mode,
            "tag_scope": config.tag_scope,
            "recommend_scope": config.recommend_scope,
            "sync_scope": config.sync_scope,
            "existing_player_policy": config.existing_player_policy,
            "selected_steps": config.selected_steps,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PipelineConfig":
        raw_filters = value.get("export_filters", {})
        if isinstance(raw_filters, Mapping) and "criteria" in raw_filters:
            criteria = raw_filters.get("criteria", {})
        else:
            criteria = raw_filters
        if not isinstance(criteria, Mapping):
            raise ValueError("export_filters 必须是对象")

        raw_steps = value.get("selected_steps", StepName.values())
        if isinstance(raw_steps, str):
            raw_steps = [raw_steps]
        if not isinstance(raw_steps, Iterable):
            raise ValueError("selected_steps 必须是列表")
        raw_mode = value.get("recommend_mode")
        if raw_mode is None:
            old_enabled = value.get("recommend_enabled", None)
            raw_mode = "unchanged" if old_enabled is None else ("enable" if bool(old_enabled) else "disable")
        return cls(
            schema_version=int(value.get("schema_version", 1)),
            source_path=str(value.get("source_path", "")),
            output_root=str(value.get("output_root", "runs")),
            export_filters=ExportFilters(dict(criteria)),
            manual_player_ids=_as_string_list(value.get("manual_player_ids", [])),
            manual_model_ids=_as_string_list(value.get("manual_model_ids", [])),
            manual_tags=_as_string_list(value.get("manual_tags", [])),
            manual_tag_ids=_as_string_list(value.get("manual_tag_ids", [])),
            recommend_enabled=(None if value.get("recommend_enabled", None) is None else bool(value.get("recommend_enabled"))),
            recommend_mode=str(raw_mode),
            tag_scope=str(value.get("tag_scope", "manual_ids")),
            recommend_scope=str(value.get("recommend_scope", "manual_ids")),
            sync_scope=str(value.get("sync_scope", "current_batch")),
            existing_player_policy=str(value.get("existing_player_policy", "new_only")),
            selected_steps=_as_string_list(raw_steps),
        ).normalized()


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Iterable):
        raise ValueError("列表字段必须是列表或字符串")
    return [str(item) for item in value]


def _clean_lines(value: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for item in value:
        for line in str(item).replace(",", "\n").splitlines():
            text = line.strip()
            if text and text not in result:
                result.append(text)
    return result


@dataclass
class StepResult:
    step: str
    status: str
    started_at: str
    finished_at: str
    message: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunRecord:
    run_id: str
    run_dir: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    steps: List[StepResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data

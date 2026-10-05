"""流水线步骤适配器。

业务字段和后台请求都通过这里接入。当前实现只完成安全的本地文件暂存、
人工标签方案暂存和推荐开关状态；任何未接入的后台动作都会返回
``blocked``，绝不伪造成功。
"""

from __future__ import annotations

import json
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol

from .models import PipelineConfig, StepName, StepResult, StepStatus, utc_now_iso
from .storage import JsonlLogger, redact


class AdapterBlocked(Exception):
    """适配器因未就绪或缺少输入而不能安全执行。"""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class AdapterSkipped(Exception):
    """步骤按配置跳过，不代表执行成功。"""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class LoginRequest:
    """后台登录请求，仅存在于内存；禁止放入 PipelineConfig 或日志。"""

    username: str
    password: str
    captcha: str = ""
    captcha_id: str = ""


class BackendLoginAdapter(Protocol):
    """由后台模块注入的真实登录机制；GUI 不保存请求或会话。"""

    def login(self, request: LoginRequest) -> object:
        ...


@dataclass
class AdapterContext:
    config: PipelineConfig
    run_dir: Path
    logger: JsonlLogger
    stop_event: Event
    previous_results: Mapping[str, StepResult] = field(default_factory=dict)
    backend: object = None

    def ensure_running(self) -> None:
        if self.stop_event.is_set():
            raise AdapterBlocked("STOP_REQUESTED", "用户已请求停止，未发起新的动作")


class StepAdapter(ABC):
    step: StepName

    @abstractmethod
    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        """执行一个步骤并返回可 JSON 序列化的脱敏结果。"""


class FileExportAdapter(StepAdapter):
    """将本地源文件安全复制到独立运行目录。

    这一步不猜测球员数据字段。只要设置了筛选条件，就生成筛选请求
    清单并返回 ``blocked``（由编排器负责转译），等待正式导出适配器接入。
    """

    step = StepName.EXPORT

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        source = Path(context.config.source_path).expanduser()
        if not context.config.source_path:
            raise AdapterBlocked("MISSING_SOURCE", "未选择导出源文件或目录")
        if not source.exists():
            raise AdapterBlocked("SOURCE_NOT_FOUND", "导出源不存在", source=str(source))

        criteria = context.config.export_filters.criteria
        if criteria:
            manifest = context.run_dir / "export_request.json"
            manifest.write_text(
                json.dumps(
                    {
                        "source_path": str(source),
                        "filters": redact(criteria),
                        "status": "pending_backend_adapter",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            raise AdapterBlocked(
                "EXPORT_ADAPTER_NOT_READY",
                "已保存导出筛选请求，但正式数据导出适配器尚未接入",
                request_file=str(manifest),
            )

        target = context.run_dir / "exported"
        target.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            destination = target / source.name
            shutil.copy2(source, destination)
            copied = [str(destination)]
        else:
            copied = []
            for item in sorted(source.rglob("*")):
                context.ensure_running()
                if item.is_file():
                    relative = item.relative_to(source)
                    destination = target / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination)
                    copied.append(str(destination))
        return {
            "mode": "local_copy",
            "source_kind": "file" if source.is_file() else "directory",
            "files_copied": len(copied),
            "outputs": copied,
            "filters_applied": False,
        }


class DatabaseExportAdapter(StepAdapter):
    """调用已核实的只读球员数据库导出端点。"""

    step = StepName.EXPORT

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        if context.config.source_path:
            return FileExportAdapter().execute(context)
        try:
            from .player_database import PlayerDatabaseClient

            target = context.run_dir / "exported" / "players.xlsx"
            target.parent.mkdir(parents=True, exist_ok=True)
            validation = PlayerDatabaseClient().export_players(
                context.config.export_filters,
                target,
                overwrite=False,
            )
        except Exception as exc:
            # 让流水线将数据库网络/响应/校验错误记为 failed；异常文本会在
            # pipeline 中再次脱敏，不把 URL 中的潜在凭据写入日志。
            raise AdapterBlocked("DATABASE_EXPORT_FAILED", "数据库导出未完成", reason=str(exc)) from exc
        return {
            "mode": "database_read_only",
            "endpoint": "/api/export/players",
            "filters": dict(context.config.export_filters.criteria),
            "output": str(target),
            "row_count": validation.row_count,
            "sheet_names": list(validation.sheet_names),
            "duplicate_futbin_ids": list(validation.duplicate_futbin_ids),
        }


class WorkbookTransformAdapter(StepAdapter):
    """把导出/用户选择的 xlsx 或 xlsm 转成单一 ``球员`` sheet。"""

    step = StepName.TRANSFORM

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        source = context.config.source_path
        if not source:
            previous = context.previous_results.get(StepName.EXPORT.value)
            previous_data = previous.result if previous else {}
            source = str(previous_data.get("output") or "")
            if not source:
                outputs = previous_data.get("outputs") or []
                source = str(outputs[0]) if outputs else ""
        if not source:
            raise AdapterBlocked("TRANSFORM_SOURCE_MISSING", "没有 Excel 源文件或上一阶段导出文件")
        try:
            from .transformer import TransformationError, convert_workbook

            target = context.run_dir / "transformed" / "players.xlsx"
            result = convert_workbook(source, target)
        except TransformationError as exc:
            raise AdapterBlocked(
                "TRANSFORM_VALIDATION_BLOCKED",
                "Excel 转换校验未通过，未生成可上传文件",
                validation_code=exc.code,
                report_path=exc.report_path,
            ) from exc
        except Exception as exc:
            raise AdapterBlocked("TRANSFORM_FAILED", "Excel 转换未完成", reason=str(exc)) from exc
        return result.to_dict()


class BackendImportAdapter(StepAdapter):
    """调用注入的真实后台导入客户端并等待任务终态。"""

    step = StepName.IMPORT

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        backend = context.backend
        if backend is None or not hasattr(backend, "import_players"):
            raise AdapterBlocked("IMPORT_BACKEND_NOT_READY", "后台导入适配器尚未登录或未注入")
        previous = context.previous_results.get(StepName.TRANSFORM.value)
        source = str((previous.result if previous else {}).get("output_path") or "")
        if not source and context.config.source_path:
            source = str(context.config.source_path)
        if not source:
            raise AdapterBlocked("IMPORT_SOURCE_MISSING", "没有成功的 Excel 转换文件，未上传")
        context.ensure_running()
        try:
            outcome = backend.import_players(source)
        except Exception as exc:
            try:
                from .admin_adapter import NoNewPlayers
            except ImportError:
                NoNewPlayers = ()
            if NoNewPlayers and isinstance(exc, NoNewPlayers):
                raise AdapterBlocked("IMPORT_NO_NEW_PLAYERS", "本次没有新增球员，未发起后台导入；后续本批写入已停止") from exc
            raise AdapterBlocked("IMPORT_REQUEST_FAILED", "后台导入请求未完成", reason=str(exc)) from exc
        data = outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)
        if data.get("verified") is not True:
            raise AdapterBlocked("IMPORT_UNVERIFIED", "后台导入未通过任务终态核验", outcome=data)
        backend_map = data.get("futbin_model_map")
        if isinstance(backend_map, Mapping):
            data["batch_futbin_ids"] = [str(item).strip() for item in backend_map if str(item).strip()]
            data["batch_model_ids"] = [int(value) for value in backend_map.values()]
        return data


class AdminTagsAdapter(StepAdapter):
    """使用 AdminAdapter 做标签并集写入并回读核验。"""

    step = StepName.TAGS

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        config = context.config
        backend = context.backend
        if not config.manual_model_ids and not config.manual_tag_ids:
            raise AdapterSkipped("TAGS_SCOPE_EMPTY", "未配置后台模型 ID 或标签 ID，未发起写入")
        if not hasattr(backend, "add_tags"):
            raise AdapterBlocked("TAGS_BACKEND_NOT_READY", "后台标签适配器尚未登录或未注入")
        model_ids = _resolve_model_ids(context, config.tag_scope, "标签")
        tag_ids = _positive_ints(config.manual_tag_ids, "标签 ID")
        if not model_ids or not tag_ids:
            raise AdapterBlocked("TAGS_IDS_MISSING", "标签写入需要明确的后台模型 ID 和标签 ID")
        try:
            result = backend.add_tags(model_ids, tag_ids)
        except Exception as exc:
            raise AdapterBlocked("TAGS_WRITE_FAILED", "标签写入或回读核验失败", reason=str(exc)) from exc
        if result.get("verified") is not True:
            raise AdapterBlocked("TAGS_UNVERIFIED", "标签结果未通过后台回读核验", result=result)
        return dict(result)


class AdminRecommendationAdapter(StepAdapter):
    step = StepName.RECOMMEND

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        if context.config.recommend_mode == "unchanged" or context.config.recommend_enabled is None:
            raise AdapterSkipped("RECOMMEND_UNCHANGED", "推荐设置为不变，未发起推荐写入")
        backend = context.backend
        if not hasattr(backend, "set_recommendation"):
            raise AdapterBlocked("RECOMMEND_BACKEND_NOT_READY", "后台推荐适配器尚未登录或未注入")
        model_ids = _resolve_model_ids(context, context.config.recommend_scope, "推荐")
        if not model_ids:
            raise AdapterBlocked("RECOMMEND_IDS_MISSING", "推荐写入需要明确的后台模型 ID")
        try:
            result = backend.set_recommendation(model_ids, context.config.recommend_mode == "enable")
        except Exception as exc:
            raise AdapterBlocked("RECOMMEND_WRITE_FAILED", "推荐写入或回读核验失败", reason=str(exc)) from exc
        if result.get("verified") is not True:
            raise AdapterBlocked("RECOMMEND_UNVERIFIED", "推荐结果未通过后台回读核验", result=result)
        return dict(result)


class AdminPriceSyncAdapter(StepAdapter):
    step = StepName.SYNC

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        backend = context.backend
        if not hasattr(backend, "sync_prices"):
            raise AdapterBlocked("PRICE_SYNC_BACKEND_NOT_READY", "后台价格同步适配器尚未登录或未注入")
        model_ids = _resolve_model_ids(context, context.config.sync_scope, "价格同步")
        if not model_ids:
            raise AdapterBlocked("PRICE_SYNC_IDS_MISSING", "价格同步需要明确的后台模型 ID")
        try:
            result = backend.sync_prices(model_ids)
        except Exception as exc:
            raise AdapterBlocked("PRICE_SYNC_FAILED", "价格同步请求失败", reason=str(exc)) from exc
        if result.get("verified") is not True:
            raise AdapterBlocked("PRICE_SYNC_UNVERIFIED", "已提交待核验：实际产品售价尚未完成回读核验", result=result)
        return dict(result)


class ManualTagsAdapter(StepAdapter):
    """只保存人工输入的标签方案，不向后台写入。"""

    step = StepName.TAGS

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        config = context.config
        if not config.manual_player_ids and not config.manual_tags:
            raise AdapterSkipped("TAGS_SCOPE_EMPTY", "标签范围为空，未生成或写入任何标签")
        if config.tag_scope == "manual_ids" and not config.manual_player_ids:
            raise AdapterBlocked("TAGS_SCOPE_MISSING", "标签范围选择了手动球员 ID，但未填写球员 ID")
        if config.tag_scope == "current_batch":
            previous = context.previous_results.get(StepName.EXPORT.value)
            if not previous or previous.status != StepStatus.SUCCESS.value:
                raise AdapterBlocked("TAGS_BATCH_MISSING", "标签范围选择了本次导出批次，但没有成功的导出步骤")
        manifest = context.run_dir / "tags_plan.json"
        payload = {
            "mode": "manual_plan",
            "scope": config.tag_scope,
            "player_ids": list(config.manual_player_ids),
            "tags": list(config.manual_tags),
            "rules": [],
            "score_threshold": None,
            "applied_to_backend": False,
        }
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "mode": "manual_plan",
            "status": "staged_only",
            "manifest": str(manifest),
            "player_count": len(config.manual_player_ids),
            "tag_count": len(config.manual_tags),
            "applied_to_backend": False,
        }


class DisabledRecommendationAdapter(StepAdapter):
    """推荐关闭时可正常跳过，开启时明确阻断。"""

    step = StepName.RECOMMEND

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        mode = context.config.recommend_mode
        if mode == "unchanged" or context.config.recommend_enabled is None:
            raise AdapterSkipped("RECOMMEND_UNCHANGED", "推荐设置为不变，未发起推荐写入")
        raise AdapterBlocked(
            "RECOMMEND_ADAPTER_NOT_READY",
            f"推荐设置为 {mode}，但推荐适配器尚未接入；未使用任何默认评分阈值",
        )


class NotReadyAdapter(StepAdapter):
    """后台/字段未知步骤的安全占位实现。"""

    def __init__(self, step: StepName, message: str) -> None:
        self.step = step
        self.message = message

    def execute(self, context: AdapterContext) -> Dict[str, Any]:
        context.ensure_running()
        raise AdapterBlocked(f"{self.step.value.upper()}_ADAPTER_NOT_READY", self.message)


def default_adapters() -> Dict[StepName, StepAdapter]:
    return {
        StepName.EXPORT: DatabaseExportAdapter(),
        StepName.TRANSFORM: WorkbookTransformAdapter(),
        StepName.IMPORT: BackendImportAdapter(),
        StepName.TAGS: AdminTagsAdapter(),
        StepName.RECOMMEND: AdminRecommendationAdapter(),
        StepName.SYNC: AdminPriceSyncAdapter(),
    }


def _extract_job_id(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    for key in ("job_id", "jobId"):
        if value.get(key):
            return str(value[key]).strip()
    data = value.get("data")
    if isinstance(data, Mapping):
        for key in ("job_id", "jobId"):
            if data.get(key):
                return str(data[key]).strip()
    return ""


def _positive_ints(values: Iterable[Any], label: str) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise AdapterBlocked(f"{label.upper().replace(' ', '_')}_INVALID", f"{label}必须是整数") from exc
        if number < 1:
            raise AdapterBlocked(f"{label.upper().replace(' ', '_')}_INVALID", f"{label}必须大于 0")
        if number not in result:
            result.append(number)
    return result


def _product_verifier(model_id: int, phase: str, products: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """验证实际产品列表存在且由 AdminAdapter 进行范围核验，不重算价格。"""

    return {
        "verified": bool(products),
        "baseline_captured": phase == "before",
        "formula_verified": False,
        "note": "仅核验实际产品行；未独立重算或假设价格变化",
    }


def _read_source_futbin_ids(source: str) -> list[str]:
    try:
        from .player_database import read_futbin_ids

        return list(read_futbin_ids(source))
    except Exception:
        return []


def _resolve_model_ids(context: AdapterContext, scope: str, label: str) -> list[int]:
    """按明确 FUTBIN ID 映射后台模型 ID，不以标题或旧批次猜测。"""

    if scope == "manual_ids":
        return _positive_ints(context.config.manual_model_ids, "后台模型 ID")
    backend = context.backend
    if not hasattr(backend, "list_all_models"):
        raise AdapterBlocked(f"{label.upper()}_BATCH_UNRESOLVED", f"{label}本次批次尚未建立模型 ID 映射")
    batch_ids: list[str] = []
    # 优先使用本次导入回读明确标记的新增 ID，再读取本次转换/导出结果。
    for step in (StepName.IMPORT.value, StepName.TRANSFORM.value, StepName.EXPORT.value):
        previous = context.previous_results.get(step)
        if not previous or previous.status != StepStatus.SUCCESS.value:
            continue
        data = previous.result or {}
        model_map = data.get("futbin_model_map")
        if step == StepName.IMPORT.value and isinstance(model_map, Mapping):
            batch_ids.extend(str(item).strip() for item in model_map if str(item).strip())
            if batch_ids:
                break
        for key in ("batch_futbin_ids", "new_futbin_ids"):
            values = data.get(key)
            if isinstance(values, (list, tuple)):
                batch_ids.extend(str(item).strip() for item in values if str(item).strip())
        if batch_ids:
            break
        source = str(data.get("output_path") or data.get("output") or "")
        if not source and data.get("outputs"):
            source = str(data["outputs"][0])
        if source:
            batch_ids.extend(_read_source_futbin_ids(source))
            if batch_ids:
                break
    batch_ids = list(dict.fromkeys(batch_ids))
    if not batch_ids:
        raise AdapterBlocked(f"{label.upper()}_BATCH_IDS_MISSING", f"{label}本次批次没有可核验的 FUTBIN ID")
    try:
        from .admin_adapter import build_existing_model_map

        mapping = build_existing_model_map(backend.list_all_models())
    except Exception as exc:
        raise AdapterBlocked(f"{label.upper()}_BATCH_UNRESOLVED", f"{label}批次模型映射未通过核验", reason=str(exc)) from exc
    missing = [item for item in batch_ids if item not in mapping]
    if missing:
        raise AdapterBlocked(f"{label.upper()}_BATCH_UNRESOLVED", f"{label}批次存在未映射 FUTBIN ID", missing_futbin_ids=missing)
    return _positive_ints([mapping[item] for item in batch_ids], "后台模型 ID")

"""FC27 球员模型后台适配器（默认 fail closed）。

本模块把本地 FUTBIN ID 与后台商品模型 ID 明确分开。默认
``write_enabled=False``，因此登录后也只能读取模型、标签、产品与任务状态；
导入、标签、推荐、价格同步和下架必须由 GUI 在用户明确操作后显式开启。

适配器不会重名去重、不会把标题当作 FUTBIN ID、不会在导入超时后重传，也不会
把模型默认 ``price`` 当成实际产品售价。未核实的响应结构直接阻断并保留任务
状态，避免把后台不确定状态展示为成功。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .admin_client import (
    AdminClient,
    AdminClientError,
    AdminContractError,
    AdminHttpError,
    SUPPORTED_CID,
    SUPPORTED_GID,
)
from .player_database import WorkbookValidationError, read_futbin_ids, validate_xlsx
from .storage import atomic_write_json, read_json


_MISSING = object()


class AdminAdapterError(RuntimeError):
    """后台适配器错误基类。"""


class AdapterBlocked(AdminAdapterError):
    """安全边界阻止了操作。"""


class WriteDisabled(AdapterBlocked):
    """默认只读模式不允许后台写入。"""


class BackendVerificationError(AdapterBlocked):
    """后台响应或写入结果无法按证据核验。"""


class ImportUnknown(AdapterBlocked):
    """上传请求超时/网络中断，任务状态未知，禁止重传。"""


class NoNewPlayers(AdapterBlocked):
    """输入中没有需要导入的新球员。"""


class UnlistPartialFailure(AdapterBlocked):
    """下架写入已开始，但有步骤失败或无法完成读回核验。"""

    def __init__(self, message: str, *, report: Mapping[str, Any], cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.report = dict(report)
        self.cause = cause


class BatchWriteUnknown(AdapterBlocked):
    """批量写入已开始但未完成，部分模型状态需先只读复核，禁止盲目重试。"""

    def __init__(self, message: str, *, report: Mapping[str, Any], cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.report = dict(report)
        self.cause = cause


@dataclass(frozen=True)
class ImportPlan:
    source_path: str
    source_sha256: str
    upload_source_path: str
    upload_source_sha256: str
    all_futbin_ids: tuple[str, ...]
    existing_futbin_ids: tuple[str, ...]
    upload_futbin_ids: tuple[str, ...]
    existing_model_ids: Mapping[str, int]

    @property
    def expected_count(self) -> int:
        return len(self.upload_futbin_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "upload_source_path": self.upload_source_path,
            "upload_source_sha256": self.upload_source_sha256,
            "all_count": len(self.all_futbin_ids),
            "existing_count": len(self.existing_futbin_ids),
            "upload_count": len(self.upload_futbin_ids),
            "existing_model_count": len(self.existing_model_ids),
            "status": "ready" if self.upload_futbin_ids else "no_new_players",
        }


@dataclass(frozen=True)
class ImportOutcome:
    job_id: str
    expected_count: int
    progress: Mapping[str, Any]
    verified: bool
    verification_mode: str
    futbin_model_map: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "expected_count": self.expected_count,
            "progress": dict(self.progress),
            "verified": self.verified,
            "verification_mode": self.verification_mode,
            "futbin_model_map": {str(key): int(value) for key, value in self.futbin_model_map.items()},
        }


@dataclass(frozen=True)
class UnlistPlan:
    """一次模型下架的只读预检快照。

    ``models`` 和 ``products_by_model`` 只用于本地计划/界面展示；执行时仍会
    重新读取并核验范围，避免把过期计划直接变成写入授权。
    """

    model_ids: tuple[int, ...]
    models: Mapping[int, Mapping[str, Any]]
    products_by_model: Mapping[int, tuple[Mapping[str, Any], ...]]
    steps: tuple[str, ...] = (
        "model.more.extend.untradeable=1",
        "products.total=0",
        "model.status=0",
        "model.auto_off=1",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_ids": list(self.model_ids),
            "model_count": len(self.model_ids),
            "product_count_by_model": {
                str(model_id): len(rows) for model_id, rows in self.products_by_model.items()
            },
            "product_ids_by_model": {
                str(model_id): [_product_id(row) for row in rows]
                for model_id, rows in self.products_by_model.items()
            },
            "products_by_model": {
                str(model_id): [
                    {
                        "id": _product_id(row),
                        "mid": row.get("mid"),
                        "gid": row.get("gid"),
                        "cid": row.get("cid"),
                        "total": row.get("total"),
                        "auto_off": row.get("auto_off"),
                    }
                    for row in rows
                ]
                for model_id, rows in self.products_by_model.items()
            },
            "steps": list(self.steps),
            "status": "ready",
        }


@dataclass(frozen=True)
class UnlistOutcome:
    """字段读回已完成的下架结果；不宣称前台实际下架效果。"""

    model_ids: tuple[int, ...]
    completed_steps: tuple[str, ...]
    verified: bool
    effective_unlisted: bool = False
    status: str = "completed_readback"
    report: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_ids": list(self.model_ids),
            "completed_steps": list(self.completed_steps),
            "verified": self.verified,
            "effective_unlisted": self.effective_unlisted,
            "status": self.status,
            "report": dict(self.report),
        }


class TaskStateStore:
    """仅保存任务/文件摘要，不保存密码、token、验证码或客户数据。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.upload_dir = self.root / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "admin_tasks.json"

    def load(self) -> list[Mapping[str, Any]]:
        if not self.state_path.exists():
            return []
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AdminAdapterError("后台任务状态文件损坏或不可读，已阻断导入防止重复上传") from exc
        if not isinstance(value, list):
            raise AdminAdapterError("后台任务状态文件根节点不是列表，已阻断导入")
        return [item for item in value if isinstance(item, Mapping)]

    def save(self, record: Mapping[str, Any]) -> None:
        records = [dict(item) for item in self.load() if isinstance(item, Mapping)]
        records.insert(0, dict(record))
        # 最近历史可限量，但未决/unknown 任务永不因轮询或多任务而被淘汰。
        unresolved = {"uploading", "unknown", "unknown_response", "unknown_timeout", "unknown_status", "queued", "pending", "parsing", "importing", "processing", "done_unverified"}
        retained = records[:100]
        known = {_record_operation_key(item) for item in retained}
        for item in records[100:]:
            key = _record_operation_key(item)
            if str(item.get("status") or "") in unresolved and key not in known:
                retained.append(item)
                known.add(key)
        atomic_write_json(self.state_path, retained)

    def latest_for_source(self, source_sha256: str) -> Optional[Mapping[str, Any]]:
        for record in self.load():
            if str(record.get("source_sha256") or "") == source_sha256:
                return record
        return None

    def latest_for_job(self, job_id: str) -> Optional[Mapping[str, Any]]:
        for record in self.load():
            if str(record.get("job_id") or "") == str(job_id):
                return record
        return None

    def pending_for_ids(self, futbin_ids: Sequence[str]) -> Optional[Mapping[str, Any]]:
        wanted = {str(item).strip() for item in futbin_ids if str(item).strip()}
        unresolved = {"uploading", "unknown", "unknown_response", "unknown_timeout", "unknown_status", "queued", "pending", "parsing", "importing", "processing", "done_unverified"}
        latest: dict[tuple[str, str], Mapping[str, Any]] = {}
        for record in self.load():
            # 上传前记录没有 job_id，后台返回 job_id 后必须仍归于同一操作生命周期。
            key = _record_operation_key(record)
            latest.setdefault(key, record)
        for record in latest.values():
            if str(record.get("status") or "") not in unresolved:
                continue
            expected = {str(item).strip() for item in (record.get("expected_futbin_ids") or []) if str(item).strip()}
            if wanted & expected:
                return record
        return None

    def update_job(self, job_id: str, status: str, progress: Mapping[str, Any], **updates: Any) -> None:
        """更新同一任务而不是丢掉 source/hash/expected IDs 断点信息。"""

        previous = dict(self.latest_for_job(job_id) or {})
        previous.update(updates)
        previous.update({"job_id": str(job_id), "status": status, "progress": dict(progress), "updated_at": _now()})
        self.save(previous)

    def stage_upload(self, source: Path, sha256: str) -> Path:
        # 文件名不含敏感信息之外的内容；原始文件名只保留 basename。
        safe_name = source.name.replace("/", "_").replace("\\", "_")
        target = self.upload_dir / f"{sha256[:16]}_{safe_name}"
        if target.exists():
            if _sha256(target) != sha256:
                raise AdminAdapterError("已有 staged 文件摘要不匹配，拒绝覆盖")
            return target
        partial = target.with_name(f".{target.name}.part")
        shutil.copy2(source, partial)
        if _sha256(partial) != sha256:
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            raise AdminAdapterError("staged 文件摘要不匹配")
        os.replace(partial, target)
        return target


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_operation_key(record: Mapping[str, Any]) -> tuple[str, str]:
    """按稳定操作标识合并 upload-before-job 与 queued/done 记录。"""

    operation_id = str(record.get("operation_id") or "").strip()
    if operation_id:
        return ("operation", operation_id)
    source_sha256 = str(record.get("source_sha256") or "").strip()
    if source_sha256:
        return ("source", source_sha256)
    job_id = str(record.get("job_id") or "").strip()
    if job_id:
        return ("job", job_id)
    return ("record", str(id(record)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normal_key(key: Any) -> str:
    return "".join(char for char in str(key).casefold() if char.isalnum())


def _explicit_value(row: Mapping[str, Any], names: set[str]) -> Any:
    wanted = {_normal_key(name) for name in names}
    for key, value in row.items():
        if _normal_key(key) in wanted:
            return value
    return None


def _extend_player_id_candidates(row: Mapping[str, Any]) -> tuple[tuple[str, ...], bool]:
    """返回 player_id 候选及结构错误标记。"""

    more = row.get("more")
    if not isinstance(more, Mapping) or "extend" not in more:
        return (), False
    extend = more.get("extend")
    if not isinstance(extend, list):
        return (), True
    matches: list[str] = []
    for item in extend:
        if not isinstance(item, Mapping):
            continue
        if _normal_key(item.get("key")) != _normal_key("player_id"):
            continue
        value = item.get("value")
        if value is None or not str(value).strip():
            return (), True
        matches.append(str(value).strip())
    invalid = bool(matches) and len(matches) != 1
    return tuple(matches), invalid


def _extend_player_id(row: Mapping[str, Any]) -> Optional[str]:
    """读取已核实的 ``more.extend`` player_id 条目。

    后台详情实测结构是 ``more`` 映射下的 ``extend`` 列表，列表元素形如
    ``{"key": "player_id", "value": "846"}``。只接受这个明确结构；
    对未知的 ``more``/``extend`` 形状保持阻断，不能把标题或其他扩展值
    当成 FUTBIN ID。
    """

    matches, invalid = _extend_player_id_candidates(row)
    return matches[0] if len(matches) == 1 and not invalid else None


def extract_futbin_id(row: Mapping[str, Any]) -> Optional[str]:
    """从明确的 FUTBIN ID 字段或已核实的 ``more.extend.player_id`` 读取。

    ``player_id`` 仅作为后台扩展列表中的明确键处理，不从标题/名称猜测。
    """

    explicit_values: list[str] = []
    for container in (row, row.get("more") if isinstance(row.get("more"), Mapping) else {}, row.get("extend") if isinstance(row.get("extend"), Mapping) else {}):
        value = _explicit_value(container, {"futbin_id", "FUTBIN ID", "futbinId"})
        if value is not None and str(value).strip():
            explicit_values.append(str(value).strip())
    if len(set(explicit_values)) > 1:
        return None
    player_ids, player_id_invalid = _extend_player_id_candidates(row)
    if player_id_invalid:
        return None
    if player_ids:
        if explicit_values and explicit_values[0] != player_ids[0]:
            return None
        return player_ids[0]
    return explicit_values[0] if explicit_values else None


def extract_model_id(row: Mapping[str, Any]) -> Optional[int]:
    value = _explicit_value(row, {"id", "model_id", "modelId"})
    if value is None or str(value).strip() == "":
        return None
    try:
        model_id = int(value)
    except (TypeError, ValueError):
        return None
    return model_id if model_id > 0 else None


def build_existing_model_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """构建 FUTBIN ID -> 后台模型 ID 映射；缺字段/重复时整体阻断。"""

    result: dict[str, int] = {}
    for index, row in enumerate(rows):
        futbin_id = extract_futbin_id(row)
        model_id = extract_model_id(row)
        if not futbin_id or model_id is None:
            raise BackendVerificationError(f"模型列表第 {index + 1} 行缺少明确 FUTBIN ID 或模型 ID")
        if futbin_id in result:
            raise BackendVerificationError(f"后台存在重复 FUTBIN ID，拒绝重名去重: {futbin_id}")
        result[futbin_id] = model_id
    return result


def _tag_ids(row: Mapping[str, Any]) -> list[int]:
    value = _explicit_value(row, {"tid", "tag_ids", "tagIds"})
    if value is None:
        raise BackendVerificationError("模型详情缺少 tid，无法安全做标签并集")
    if isinstance(value, str):
        values = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = list(value)
    else:
        values = [value]
    result: list[int] = []
    for item in values:
        try:
            parsed = int(item)
        except (TypeError, ValueError) as exc:
            raise BackendVerificationError("模型详情含无法解析的 tid") from exc
        if parsed < 1:
            continue
        if parsed not in result:
            result.append(parsed)
    return result


def merge_tag_ids(existing: Sequence[int], requested: Sequence[int]) -> list[int]:
    result: list[int] = []
    for value in [*existing, *requested]:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("标签 ID 必须是整数") from exc
        if parsed < 1:
            raise ValueError("标签 ID 必须大于 0")
        if parsed not in result:
            result.append(parsed)
    return result


class AdminAdapter:
    """绑定 FC27（gid=1327/cid=9627）的后台动作。"""

    def __init__(
        self,
        client: AdminClient,
        *,
        state_root: str | Path = "admin_state",
        write_enabled: bool = False,
        sleep_fn: Callable[[float], None] = time.sleep,
        workbook_filter: Optional[Callable[[Path, Sequence[str], Path], str | Path]] = None,
        stop_event: Any = None,
    ) -> None:
        self.client = client
        self.store = TaskStateStore(state_root)
        self.write_enabled = bool(write_enabled)
        self.sleep_fn = sleep_fn
        # core 可注入 transformer.filter_existing_players(source, existing_ids, target)；
        # 本模块不猜模板格式，函数返回的新文件仍会再次核验 FUTBIN ID。
        self.workbook_filter = workbook_filter
        self.stop_event = stop_event

    def _require_write(self) -> None:
        if not self.write_enabled:
            raise WriteDisabled("当前为只读模式；需要 GUI 的明确写入授权")

    @contextmanager
    def temporary_write_access(self):
        """为一个已经确认的 GUI 动作临时打开写入门槛。

        登录和所有只读入口始终保持 ``write_enabled=False``。GUI 只有在
        展示完整范围并得到确认后才进入这个上下文；无论动作成功、失败或
        抛出未知状态，退出上下文都会强制恢复只读，避免一次确认变成会话级
        写入权限。
        """

        self.write_enabled = True
        try:
            yield self
        finally:
            self.write_enabled = False

    def _ensure_before_write(self) -> None:
        self._require_write()
        event = self.stop_event
        stopped = bool(event() if callable(event) and not hasattr(event, "is_set") else event.is_set()) if event is not None else False
        if stopped:
            raise AdapterBlocked("停止信号已设置，未发起新的后台写入")

    @staticmethod
    def _verify_model_scope(row: Mapping[str, Any], model_id: int) -> None:
        actual_id = extract_model_id(row)
        gid = _explicit_value(row, {"gid", "game_id", "gameId"})
        cid = _explicit_value(row, {"cid", "category_id", "categoryId"})
        if actual_id != model_id or str(gid) != str(SUPPORTED_GID) or str(cid) != str(SUPPORTED_CID):
            raise BackendVerificationError(
                f"模型 {model_id} 详情范围不一致，要求 gid={SUPPORTED_GID}, cid={SUPPORTED_CID}, id={model_id}"
            )

    def list_all_models(self) -> tuple[Mapping[str, Any], ...]:
        rows: list[Mapping[str, Any]] = []
        page = 1
        total: Optional[int] = None
        while True:
            result = self.client.list_models(
                page=page,
                limit=200,
                search=[
                    {"field": "gid", "operator": "=", "val": str(SUPPORTED_GID)},
                    {"field": "cid", "operator": "=", "val": str(SUPPORTED_CID)},
                ],
            )
            if result.total is None:
                raise BackendVerificationError("模型列表缺少 total，无法核验分页范围")
            if total is None:
                total = result.total
            elif total != result.total:
                raise BackendVerificationError("模型列表分页 total 不一致")
            if not result.rows:
                if result.total != 0 or len(rows) != 0:
                    raise BackendVerificationError("模型首页为空但 total 非零，拒绝把已有球员当成新增")
                break
            for row in result.rows:
                model_id = extract_model_id(row)
                if model_id is None:
                    raise BackendVerificationError("模型列表含缺少明确 id 的行")
                self._verify_model_scope(row, model_id)
            rows.extend(result.rows)
            if len(rows) > total:
                raise BackendVerificationError("模型列表返回行数超过 total")
            if len(rows) == total:
                break
            if len(result.rows) < 200:
                raise BackendVerificationError("模型列表提前结束，未达到 data.total")
            page += 1
            if page > 10000:
                raise BackendVerificationError("模型分页超过安全上限")
        ids = [extract_model_id(row) for row in rows]
        if len(ids) != len(set(ids)):
            raise BackendVerificationError("模型列表含重复模型 ID，拒绝继续")
        if total is not None and len(rows) != total:
            raise BackendVerificationError("模型列表总数与实际行数不一致")
        return tuple(rows)

    def plan_import(self, source_path: str | Path) -> ImportPlan:
        source = Path(source_path).expanduser()
        try:
            validation = validate_xlsx(source)
        except WorkbookValidationError:
            raise
        if validation.duplicate_futbin_ids:
            raise BackendVerificationError("输入 XLSX 有重复 FUTBIN ID，拒绝上传")
        all_ids = validation.futbin_ids or read_futbin_ids(source)
        if not all_ids:
            raise NoNewPlayers("输入 XLSX 没有球员行")
        existing_map = build_existing_model_map(self.list_all_models())
        existing = tuple(item for item in all_ids if item in existing_map)
        upload = tuple(item for item in all_ids if item not in existing_map)
        upload_source = source
        if existing and upload:
            if self.workbook_filter is None:
                raise AdapterBlocked("输入含已有 FUTBIN ID，但未注入仅保留新增行的 workbook_filter；原文件未上传")
            filtered_target = self.store.root / "filtered" / f"{source.stem}_new_only.xlsx"
            filtered_target.parent.mkdir(parents=True, exist_ok=True)
            returned = self.workbook_filter(source, existing, filtered_target)
            upload_source = Path(returned).expanduser()
            if not upload_source.is_file():
                raise BackendVerificationError("workbook_filter 未返回存在的过滤文件")
            filtered_validation = validate_xlsx(upload_source)
            filtered_ids = tuple(filtered_validation.futbin_ids)
            if filtered_validation.duplicate_futbin_ids or set(filtered_ids) != set(upload) or len(filtered_ids) != len(upload):
                raise BackendVerificationError("过滤文件 FUTBIN ID 与新增集合不一致，拒绝上传")
        return ImportPlan(
            source_path=str(source),
            source_sha256=_sha256(source),
            upload_source_path=str(upload_source),
            upload_source_sha256=_sha256(upload_source),
            all_futbin_ids=tuple(all_ids),
            existing_futbin_ids=existing,
            upload_futbin_ids=upload,
            existing_model_ids={item: existing_map[item] for item in existing},
        )

    def import_players(self, source_path: str | Path, *, poll_timeout: float = 900.0, poll_interval: float = 2.5) -> ImportOutcome:
        source = Path(source_path).expanduser()
        source_hash = _sha256(source)
        source_ids = read_futbin_ids(source)
        overlapping = self.store.pending_for_ids(source_ids)
        if overlapping:
            prior_job = str(overlapping.get("job_id") or "").strip()
            expected_ids = tuple(str(item).strip() for item in (overlapping.get("expected_futbin_ids") or []) if str(item).strip())
            exact_batch = len(expected_ids) == len(source_ids) and set(expected_ids) == set(source_ids)
            if not prior_job:
                raise ImportUnknown("输入 FUTBIN ID 命中未决/unknown 任务，且无 job_id，禁止重传")
            old_outcome = self.track_import(prior_job, expected_count=int(overlapping.get("expected_count") or 0), expected_futbin_ids=expected_ids, timeout=poll_timeout, interval=poll_interval)
            if exact_batch:
                return old_outcome
            raise AdapterBlocked("当前输入仅部分命中已有导入任务；旧任务已追踪完成，请重新运行以规划未覆盖 FUTBIN ID")
        prior = self.store.latest_for_source(source_hash)
        if prior and str(prior.get("status") or "") in {
            "uploading",
            "unknown",
            "unknown_response",
            "unknown_status",
            "queued",
            "pending",
            "parsing",
            "importing",
            "processing",
            "unknown_timeout",
            "done_unverified",
        }:
            prior_job = str(prior.get("job_id") or "").strip()
            if not prior_job:
                raise ImportUnknown("已有未决上传状态但没有 job_id，禁止重传")
            expected_ids = tuple(str(item) for item in (prior.get("expected_futbin_ids") or []))
            return self.track_import(prior_job, expected_count=int(prior.get("expected_count") or 0), expected_futbin_ids=expected_ids, timeout=poll_timeout, interval=poll_interval)
        if prior and str(prior.get("status") or "").startswith("done"):
            raise AdapterBlocked("该源文件已有终态任务记录，禁止重复上传")
        plan = self.plan_import(source_path)
        if not plan.upload_futbin_ids:
            raise NoNewPlayers("输入球员均已存在，未创建导入任务")
        self._ensure_before_write()
        staged = self.store.stage_upload(Path(plan.upload_source_path), plan.upload_source_sha256)
        pending = {
            "created_at": _now(),
            "updated_at": _now(),
            "status": "uploading",
            "operation_id": plan.source_sha256,
            "source_sha256": plan.source_sha256,
            "upload_source_path": plan.upload_source_path,
            "upload_source_sha256": plan.upload_source_sha256,
            "staged_file": str(staged),
            "expected_count": plan.expected_count,
            "expected_futbin_ids": list(plan.upload_futbin_ids),
            "gid": SUPPORTED_GID,
            "cid": SUPPORTED_CID,
        }
        # 断点必须先落盘，再让请求离开进程；超时才能明确禁止重传。
        self.store.save(pending)
        self._ensure_before_write()
        try:
            envelope = self.client.upload_players(staged, gid=SUPPORTED_GID, cid=SUPPORTED_CID)
        except (AdminHttpError, TimeoutError) as exc:
            pending["status"] = "unknown"
            pending["error"] = type(exc).__name__
            self.store.save(pending)
            raise ImportUnknown("导入上传状态未知，禁止自动重传") from exc
        data = envelope.get("data")
        if not isinstance(data, Mapping) or not str(data.get("job_id") or "").strip():
            pending["status"] = "unknown_response"
            self.store.save(pending)
            raise BackendVerificationError("导入响应缺少 data.job_id，未宣称成功")
        job_id = str(data["job_id"]).strip()
        pending.update({"job_id": job_id, "status": "queued"})
        self.store.save(pending)
        return self.track_import(job_id, expected_count=plan.expected_count, expected_futbin_ids=plan.upload_futbin_ids, timeout=poll_timeout, interval=poll_interval)

    def track_import(self, job_id: str, *, expected_count: int, expected_futbin_ids: Sequence[str] = (), timeout: float = 900.0, interval: float = 2.5) -> ImportOutcome:
        if expected_count < 1 or timeout <= 0 or interval <= 0:
            raise ValueError("expected_count/timeout/interval 必须大于 0")
        deadline = time.monotonic() + timeout
        last: Mapping[str, Any] | None = None
        terminal = {"done", "failed"}
        # 2026-09-24 生产实据（run_20260924_135513）：后台进度返回
        # status="running" + phase="importing"。进行中判定：status 或 phase
        # 任一非空命中即可；两者都为空沿用旧行为继续轮询直到超时；
        # 出现非空且不在词汇表的状态仍然 fail-closed。
        in_progress = {"pending", "queued", "parsing", "importing", "processing", "running"}
        while True:
            progress = self.client.get_import_progress(job_id)
            last = progress
            raw_status = str(progress.get("status") or "").strip().casefold()
            phase = str(progress.get("phase") or "").strip().casefold()
            status = raw_status or phase
            if status in terminal:
                if status == "failed":
                    self._save_task(job_id, "failed", progress)
                    raise BackendVerificationError("导入任务终态 failed")
                created = _required_count(progress, "created")
                skipped = _required_count(progress, "skipped")
                failed = _required_count(progress, "failed")
                processed = _required_count(progress, "processed")
                if failed != 0 or created + skipped != expected_count or processed < expected_count:
                    self._save_task(job_id, "done_unverified", progress)
                    raise BackendVerificationError("导入 done 但 created/skipped/failed/processed 未通过计数验收")
                ids = tuple(str(item).strip() for item in expected_futbin_ids if str(item).strip())
                if len(ids) != expected_count:
                    self._save_task(job_id, "done_unverified", progress)
                    raise BackendVerificationError("导入 done 但缺少完整 expected FUTBIN ID 集合")
                mapping = self._verify_imported_futbin_ids(ids)
                self._save_task(job_id, "done_verified", progress, verified_futbin_ids=mapping)
                return ImportOutcome(job_id, expected_count, progress, True, "counts_and_futbin_ids", mapping)
            known_in_progress = raw_status in in_progress or phase in in_progress
            both_blank = not raw_status and not phase
            if not known_in_progress and not both_blank:
                self._save_task(job_id, "unknown_status", progress)
                raise BackendVerificationError(f"导入进度出现未核实状态: {status or phase}")
            if time.monotonic() >= deadline:
                self._save_task(job_id, "unknown_timeout", last or {})
                raise ImportUnknown("导入任务超时，状态未知，禁止重传")
            self.sleep_fn(min(interval, max(0.01, deadline - time.monotonic())))

    def _verify_imported_futbin_ids(self, expected_ids: Sequence[str]) -> dict[str, int]:
        current = build_existing_model_map(self.list_all_models())
        missing = [item for item in expected_ids if item not in current]
        if missing:
            raise BackendVerificationError(f"导入终态回读缺少 FUTBIN ID: {len(missing)} 条")
        return {item: current[item] for item in expected_ids}

    def _notify_progress(self, progress: Optional[Callable[[str, int, int], None]], stage: str, done: int, total: int) -> None:
        """向 GUI 上报进度；回调异常绝不影响后台写入本身。"""

        if progress is None:
            return
        try:
            progress(stage, done, total)
        except Exception:
            pass

    def add_tags(
        self,
        model_ids: Sequence[int],
        tag_ids: Sequence[int],
        *,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> Mapping[str, Any]:
        self._require_write()
        ids = _unique_positive(model_ids, "模型 ID")
        requested = merge_tag_ids([], tag_ids)
        if not requested:
            raise ValueError("tag_ids 不能为空")
        responses: dict[int, Any] = {}
        merged_by_model: dict[int, list[int]] = {}
        total = len(ids)

        # 所有模型先完成只读范围核验，避免第二个模型才发现范围不一致而留下
        # 第一模型已写、第二模型未写的半批次状态。
        for index, model_id in enumerate(ids, start=1):
            current = self.client.get_model(model_id)
            self._verify_model_scope(current, model_id)
            merged = merge_tag_ids(_tag_ids(current), requested)
            merged_by_model[model_id] = merged
            self._notify_progress(progress, "核验范围", index, total)

        completed: list[int] = []
        started = False
        for index, model_id in enumerate(ids, start=1):
            self._ensure_before_write()
            try:
                started = True
                # 每个模型单独提交，防止 A 的旧标签被复制给 B。
                responses[model_id] = self.client.single_edit({"tid": merged_by_model[model_id], "id": [model_id]})
                reread = self.client.get_model(model_id)
                actual = _tag_ids(reread)
                if not set(merged_by_model[model_id]).issubset(actual):
                    raise BackendVerificationError(f"模型 {model_id} 标签回读缺少并集成员")
                self._verify_model_scope(reread, model_id)
                completed.append(model_id)
                self._notify_progress(progress, "写入并回读", index, total)
            except Exception as exc:
                if not started:
                    raise
                readback = _safe_tag_readback(self, model_id, requested, mode="add", expected=merged_by_model[model_id])
                raise _batch_write_unknown(
                    "add_tags",
                    ids,
                    completed,
                    model_id,
                    exc,
                    readback=readback,
                ) from exc
        return {"responses": responses, "model_ids": ids, "tag_ids_by_model": merged_by_model, "verified": True}

    def remove_tags(
        self,
        model_ids: Sequence[int],
        tag_ids: Sequence[int],
        *,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> Mapping[str, Any]:
        """逐模型移除指定标签，保留该模型的其它标签。

        2026-09-28 生产实据：移除模型**最后一个**标签会得到业务失败
        ``msg=请选择标签``。后台的批量标签接口与模型编辑接口都不接受空标签
        （前端 ``popupSingleEdit`` 里同样是 ``if(!a.tid.length) return
        "请选择标签"``）。网页能清空标签走的是另一套编辑表单流程，不是
        ``singleEdit``/``edit_model``；因此本方法对这类模型**在写入前整体
        阻断**，避免出现可预见的部分完成。
        """

        self._require_write()
        ids = _unique_positive(model_ids, "模型 ID")
        requested = merge_tag_ids([], tag_ids)
        if not requested:
            raise ValueError("tag_ids 不能为空")
        responses: dict[int, Any] = {}
        remaining_by_model: dict[int, list[int]] = {}
        removed_by_model: dict[int, list[int]] = {}
        total = len(ids)

        # 先只读核验整个批次。移除后会让模型标签变空的，后台会以
        # ``msg=请选择标签`` 拒绝（2026-09-28 生产实据；网页同样校验），
        # 因此这类模型必须在任何写入之前整体阻断，而不是写到一半才失败。
        empty_tid_model_ids: list[int] = []
        for index, model_id in enumerate(ids, start=1):
            current = self.client.get_model(model_id)
            self._verify_model_scope(current, model_id)
            existing = _tag_ids(current)
            remaining = [tag_id for tag_id in existing if tag_id not in set(requested)]
            remaining_by_model[model_id] = remaining
            removed_by_model[model_id] = [tag_id for tag_id in existing if tag_id in set(requested)]
            if removed_by_model[model_id] and not remaining:
                empty_tid_model_ids.append(model_id)
            self._notify_progress(progress, "核验范围", index, total)

        if empty_tid_model_ids:
            ids_text = ", ".join(str(item) for item in empty_tid_model_ids)
            raise BackendVerificationError(
                f"批量移除标签已阻断：{len(empty_tid_model_ids)} 个模型移除后会变成没有任何标签，"
                "而后台不接受空标签（会返回「请选择标签」）。未写入任何模型。"
                f"请在后台网页编辑页逐个清空这几张，或用「替换标签」方式改为先加别的标签再移除。模型 ID：{ids_text}"
            )

        completed: list[int] = []
        started = False
        for index, model_id in enumerate(ids, start=1):
            self._ensure_before_write()
            try:
                # 目标标签已经不存在时不发写请求；重新读取确认范围和标签状态。
                if not removed_by_model[model_id]:
                    reread = self.client.get_model(model_id)
                    self._verify_model_scope(reread, model_id)
                    if any(tag_id in _tag_ids(reread) for tag_id in requested):
                        raise BackendVerificationError(f"模型 {model_id} 标签状态在复核时发生变化")
                    responses[model_id] = {"status": "already_absent"}
                    completed.append(model_id)
                    self._notify_progress(progress, "写入并回读", index, total)
                    continue

                started = True
                # 移除是「保留其它标签」语义：提交剩余标签集合。上面已确认
                # 剩余标签非空，因此不会触发后台的空标签校验。
                responses[model_id] = self.client.single_edit({"tid": remaining_by_model[model_id], "id": [model_id]})
                reread = self.client.get_model(model_id)
                actual = _tag_ids(reread)
                if any(tag_id in actual for tag_id in requested):
                    raise BackendVerificationError(f"模型 {model_id} 标签移除回读仍含指定标签")
                if set(remaining_by_model[model_id]) - set(actual):
                    raise BackendVerificationError(f"模型 {model_id} 标签移除回读丢失未指定标签")
                self._verify_model_scope(reread, model_id)
                completed.append(model_id)
                self._notify_progress(progress, "写入并回读", index, total)
            except BatchWriteUnknown:
                raise
            except Exception as exc:
                if not started:
                    raise
                readback = _safe_tag_readback(self, model_id, requested, mode="remove", expected=remaining_by_model[model_id])
                raise _batch_write_unknown(
                    "remove_tags",
                    ids,
                    completed,
                    model_id,
                    exc,
                    readback=readback,
                ) from exc
        return {
            "responses": responses,
            "model_ids": ids,
            "removed_tag_ids_by_model": removed_by_model,
            "tag_ids_by_model": remaining_by_model,
            "verified": True,
        }

    def set_recommendation(
        self,
        model_ids: Sequence[int],
        enabled: bool,
        *,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> Mapping[str, Any]:
        self._require_write()
        ids = _unique_positive(model_ids, "模型 ID")
        responses: dict[int, Any] = {}
        total = len(ids)
        for index, model_id in enumerate(ids, start=1):
            current = self.client.get_model(model_id)
            self._verify_model_scope(current, model_id)
            self._ensure_before_write()
            responses[model_id] = self.client.single_edit({"is_rec": 1 if enabled else 0, "id": [model_id]})
            reread = self.client.get_model(model_id)
            self._verify_model_scope(reread, model_id)
            value = _explicit_value(reread, {"is_rec", "isRec"})
            try:
                actual = int(value)
            except (TypeError, ValueError) as exc:
                raise BackendVerificationError(f"模型 {model_id} 回读缺少 is_rec") from exc
            if actual != (1 if enabled else 0):
                raise BackendVerificationError(f"模型 {model_id} 推荐状态回读不一致")
            self._notify_progress(progress, "写入并回读", index, total)
        return {"responses": responses, "model_ids": ids, "is_rec": 1 if enabled else 0, "verified": True}

    def plan_unlist(
        self,
        model_ids: Sequence[int],
        *,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> UnlistPlan:
        """只读预检：读取所有模型和关联产品，完成范围/结构核验。"""

        ids = tuple(_unique_positive(model_ids, "模型 ID"))
        models: dict[int, Mapping[str, Any]] = {}
        products_by_model: dict[int, tuple[Mapping[str, Any], ...]] = {}
        total = len(ids)
        for index, model_id in enumerate(ids, start=1):
            model = self.client.get_model(model_id)
            self._verify_model_scope(model, model_id)
            _prepare_untradeable_more(model)
            products = self.client.get_products(model_id)
            _verify_product_scope(products, model_id)
            _verify_unlist_product_rows(products, model_id, require_auto_off=True)
            models[model_id] = copy.deepcopy(dict(model))
            products_by_model[model_id] = tuple(copy.deepcopy(dict(row)) for row in products)
            self._notify_progress(progress, "只读预检", index, total)
        return UnlistPlan(
            model_ids=ids,
            models=models,
            products_by_model=products_by_model,
        )

    # UI 可调用的语义化别名；两者都只生成同一份只读计划。
    build_unlist_plan = plan_unlist

    def execute_unlist(
        self,
        selection: UnlistPlan | Sequence[int],
        *,
        progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> UnlistOutcome:
        """按预检范围逐模型下架，并在每个写入步骤后读回。

        即使传入了旧的 ``UnlistPlan``，也会重新生成计划；旧快照只用于界面
        展示，不能绕过写入前的全量产品分页和范围核验。
        """

        if isinstance(selection, UnlistPlan):
            ids = selection.model_ids
        else:
            ids = tuple(_unique_positive(selection, "模型 ID"))
        plan = self.plan_unlist(ids)
        report: dict[str, Any] = {
            "status": "in_progress",
            "model_ids": list(plan.model_ids),
            "models": {},
            "product_auto_off_changed": False,
            "effective_unlisted": False,
        }
        started = False
        completed_steps: list[str] = []
        plan_total = len(plan.model_ids)
        try:
            for plan_index, model_id in enumerate(plan.model_ids, start=1):
                before_model = copy.deepcopy(dict(plan.models[model_id]))
                before_products = tuple(plan.products_by_model[model_id])
                model_report: dict[str, Any] = {
                    "product_ids": [_product_id(row) for row in before_products],
                    "steps": {},
                }
                report["models"][str(model_id)] = model_report

                # 1. 模型 more.extend.untradeable=1
                expected_more = _prepare_untradeable_more(before_model)[1]
                if before_model.get("more") == expected_more:
                    current_model = before_model
                    model_report["steps"]["model.more.extend.untradeable=1"] = "already_verified"
                else:
                    self._ensure_before_write()
                    started = True
                    model_report["steps"]["model.more.extend.untradeable=1"] = "write_started"
                    try:
                        self.client.edit_model({"id": model_id, "more": expected_more})
                        reread = self.client.get_model(model_id)
                        self._verify_model_scope(reread, model_id)
                        _verify_model_unchanged_except(before_model, reread, {"more"})
                        _verify_model_more(reread, expected_more, model_id)
                    except Exception:
                        model_report["steps"]["model.more.extend.untradeable=1"] = "unknown"
                        raise
                    current_model = copy.deepcopy(dict(reread))
                    model_report["steps"]["model.more.extend.untradeable=1"] = "verified"
                completed_steps.append(f"{model_id}:model.more.extend.untradeable=1")

                # 2. 所有关联产品 total=0；payload 只允许包含 total。
                product_ids = {_product_id(row) for row in before_products}
                original_auto_off = {
                    _product_id(row): _normalise_flag(row["auto_off"], f"产品 {_product_id(row)} auto_off")
                    for row in before_products
                }
                zeroed_ids: set[int] = set()
                product_writes = 0
                for product in before_products:
                    product_id = _product_id(product)
                    if _normalise_nonnegative_int(product.get("total"), f"产品 {product_id} total") == 0:
                        zeroed_ids.add(product_id)
                        continue
                    self._ensure_before_write()
                    started = True
                    product_writes += 1
                    model_report["steps"].setdefault("products.total=0", {"written": [], "verified": []})
                    model_report["steps"]["products.total=0"]["written"].append(product_id)
                    try:
                        self.client.edit_product({"id": product_id, "total": 0})
                        reread_products = self.client.get_products(model_id)
                        _verify_product_scope(reread_products, model_id)
                        _verify_unlist_product_rows(reread_products, model_id, require_auto_off=True)
                        _verify_product_readback(
                            reread_products,
                            model_id,
                            product_ids,
                            original_auto_off,
                            zero_ids=zeroed_ids | {product_id},
                        )
                    except Exception:
                        model_report["steps"]["products.total=0"]["unknown_product_id"] = product_id
                        raise
                    zeroed_ids.add(product_id)
                    model_report["steps"]["products.total=0"]["verified"].append(product_id)

                final_products = self.client.get_products(model_id)
                _verify_product_scope(final_products, model_id)
                _verify_unlist_product_rows(final_products, model_id, require_auto_off=True)
                _verify_product_readback(
                    final_products,
                    model_id,
                    product_ids,
                    original_auto_off,
                    zero_ids=product_ids,
                )
                if not product_writes:
                    model_report["steps"]["products.total=0"] = "already_verified"
                else:
                    model_report["steps"]["products.total=0"]["status"] = "verified"
                completed_steps.append(f"{model_id}:products.total=0")

                # 3. 模型 status=0
                if _normalise_flag(current_model.get("status"), f"模型 {model_id} status") != 0:
                    self._ensure_before_write()
                    started = True
                    model_report["steps"]["model.status=0"] = "write_started"
                    try:
                        self.client.edit_model({"id": model_id, "status": 0})
                        reread = self.client.get_model(model_id)
                        self._verify_model_scope(reread, model_id)
                        _verify_model_unchanged_except(current_model, reread, {"status"})
                        _verify_model_field(reread, "status", 0, model_id)
                    except Exception:
                        model_report["steps"]["model.status=0"] = "unknown"
                        raise
                    current_model = copy.deepcopy(dict(reread))
                    model_report["steps"]["model.status=0"] = "verified"
                else:
                    model_report["steps"]["model.status=0"] = "already_verified"
                completed_steps.append(f"{model_id}:model.status=0")

                # 4. 仅模型级 auto_off=1；绝不写产品 auto_off。
                if _normalise_flag(current_model.get("auto_off"), f"模型 {model_id} auto_off") != 1:
                    self._ensure_before_write()
                    started = True
                    model_report["steps"]["model.auto_off=1"] = "write_started"
                    try:
                        self.client.edit_model({"id": model_id, "auto_off": 1})
                        reread = self.client.get_model(model_id)
                        self._verify_model_scope(reread, model_id)
                        _verify_model_unchanged_except(current_model, reread, {"auto_off"})
                        _verify_model_field(reread, "auto_off", 1, model_id)
                    except Exception:
                        model_report["steps"]["model.auto_off=1"] = "unknown"
                        raise
                    current_model = copy.deepcopy(dict(reread))
                    model_report["steps"]["model.auto_off=1"] = "verified"
                else:
                    model_report["steps"]["model.auto_off=1"] = "already_verified"
                completed_steps.append(f"{model_id}:model.auto_off=1")

                final_model = self.client.get_model(model_id)
                self._verify_model_scope(final_model, model_id)
                _verify_model_field(final_model, "status", 0, model_id)
                _verify_model_field(final_model, "auto_off", 1, model_id)
                _verify_model_more(final_model, expected_more, model_id)
                report["effective_unlisted"] = False
                self._notify_progress(progress, "下架并回读", plan_index, plan_total)

            report["status"] = "completed_readback"
            report["completed_steps"] = list(completed_steps)
            return UnlistOutcome(
                model_ids=plan.model_ids,
                completed_steps=tuple(completed_steps),
                verified=True,
                effective_unlisted=False,
                status="completed_readback",
                report=report,
            )
        except Exception as exc:
            report["status"] = "partial_or_unknown" if started else "blocked_before_write"
            report["completed_steps"] = list(completed_steps)
            report["error_type"] = type(exc).__name__
            if started:
                raise UnlistPartialFailure(
                    "下架已开始但未完成；部分写入状态需按报告逐项复核，未宣称成功",
                    report=report,
                    cause=exc,
                ) from exc
            raise

    def unlist_models(self, model_ids: Sequence[int]) -> UnlistOutcome:
        """兼容 UI 的批量下架入口。"""

        return self.execute_unlist(model_ids)

    def sync_prices(
        self,
        model_ids: Sequence[int],
        *,
        product_verifier: Optional[Callable[[int, str, Sequence[Mapping[str, Any]]], Mapping[str, Any]]] = None,
    ) -> Mapping[str, Any]:
        self._require_write()
        ids = _unique_positive(model_ids, "模型 ID")
        before: dict[int, Sequence[Mapping[str, Any]]] = {}
        before_product_ids: dict[int, tuple[int, ...]] = {}
        for model_id in ids:
            current = self.client.get_model(model_id)
            self._verify_model_scope(current, model_id)
            products = self.client.get_products(model_id)
            _verify_product_scope(products, model_id)
            _verify_product_values(products, model_id)
            before[model_id] = products
            before_product_ids[model_id] = _product_ids(products)
            before_result = _builtin_product_result(products, baseline=True)
            if product_verifier is not None:
                try:
                    before_result = product_verifier(model_id, "before", products)
                except Exception as exc:
                    raise BackendVerificationError(f"模型 {model_id} 产品售价 before 核验器失败") from exc
            _require_verifier_result(before_result, phase="before")
        responses: dict[int, Any] = {}
        for model_id in ids:
            self._ensure_before_write()
            responses[model_id] = self.client.recalc_fc27_price(model_ids=[model_id], gid=SUPPORTED_GID, cid=SUPPORTED_CID)
        after_results: dict[int, Mapping[str, Any]] = {}
        for model_id in ids:
            after_products = self.client.get_products(model_id)
            _verify_product_scope(after_products, model_id)
            _verify_product_values(after_products, model_id)
            if _product_ids(after_products) != before_product_ids[model_id]:
                raise BackendVerificationError(f"模型 {model_id} 产品前后回读范围不一致")
            after_result = _builtin_product_result(after_products, baseline=False)
            if product_verifier is not None:
                try:
                    after_result = product_verifier(model_id, "after", after_products)
                except Exception as exc:
                    raise BackendVerificationError(f"模型 {model_id} 产品售价 after 核验器失败") from exc
            _require_verifier_result(after_result, phase="after")
            after_results[model_id] = after_result
        if any(result.get("formula_verified") is not True for result in after_results.values()):
            return {
                "status": "completed_readback",
                "responses": responses,
                "model_ids": ids,
                "verified": True,
                "formula_verified": False,
                "price_source": "actual_products_before_after",
                "verification": {str(model_id): dict(result) for model_id, result in after_results.items()},
            }
        return {
            "status": "verified",
            "responses": responses,
            "model_ids": ids,
            "verified": True,
            "formula_verified": True,
            "price_source": "actual_products_before_after",
            "verification": {str(model_id): dict(result) for model_id, result in after_results.items()},
        }

    def _save_task(self, job_id: str, status: str, progress: Mapping[str, Any], **updates: Any) -> None:
        self.store.update_job(job_id, status, progress, **updates)


def _unique_positive(values: Sequence[int], label: str) -> list[int]:
    result: list[int] = []
    for value in values:
        if isinstance(value, (bool, float)):
            raise ValueError(f"{label} 必须是整数")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} 必须是整数") from exc
        if parsed < 1:
            raise ValueError(f"{label} 必须大于 0")
        if parsed not in result:
            result.append(parsed)
    if not result:
        raise ValueError(f"{label} 不能为空")
    return result


def _product_id(row: Mapping[str, Any]) -> int:
    value = _explicit_value(row, {"id", "product_id", "productId"})
    if isinstance(value, bool):
        raise BackendVerificationError("产品 ID 不能是布尔值")
    try:
        product_id = int(value)
    except (TypeError, ValueError) as exc:
        raise BackendVerificationError("产品 ID 不是合法整数") from exc
    if product_id < 1:
        raise BackendVerificationError("产品 ID 必须大于 0")
    return product_id


def _normalise_flag(value: Any, label: str) -> int:
    if value is None or isinstance(value, bool) or isinstance(value, float):
        raise BackendVerificationError(f"{label} 不是合法整数")
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BackendVerificationError(f"{label} 不是合法整数") from exc
    if str(value).strip() != str(result):
        raise BackendVerificationError(f"{label} 不是规范整数")
    return result


def _normalise_nonnegative_int(value: Any, label: str) -> int:
    result = _normalise_flag(value, label)
    if result < 0:
        raise BackendVerificationError(f"{label} 不得为负数")
    return result


def _prepare_untradeable_more(row: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """只更新 more.extend 中唯一的 untradeable 条目并保留其它内容。"""

    more = row.get("more")
    if not isinstance(more, Mapping):
        raise BackendVerificationError("模型详情缺少可核验的 more 对象")
    extend = more.get("extend")
    if not isinstance(extend, list):
        raise BackendVerificationError("模型详情 more.extend 不是列表，拒绝覆盖扩展属性")
    matches: list[int] = []
    for index, item in enumerate(extend):
        if not isinstance(item, Mapping) or "key" not in item or "value" not in item:
            raise BackendVerificationError(f"模型 more.extend 第 {index + 1} 项结构不完整")
        if _normal_key(item.get("key")) == _normal_key("untradeable"):
            matches.append(index)
    if not matches:
        raise BackendVerificationError("模型 more.extend 缺少 untradeable，拒绝猜测追加属性的写入语义")
    if len(matches) > 1:
        raise BackendVerificationError("模型 more.extend 含多个 untradeable 条目，拒绝猜测覆盖")
    updated = copy.deepcopy(dict(more))
    updated_extend = copy.deepcopy(extend)
    item = dict(updated_extend[matches[0]])
    # 实测扩展属性值是字符串，保持同一写入形状。
    item["value"] = "1"
    updated_extend[matches[0]] = item
    updated["extend"] = updated_extend
    return more, updated


def _verify_model_more(row: Mapping[str, Any], expected_more: Mapping[str, Any], model_id: int) -> None:
    if row.get("more") != expected_more:
        raise BackendVerificationError(f"模型 {model_id} more.extend 回读与预期不一致")


def _verify_model_field(row: Mapping[str, Any], field: str, expected: int, model_id: int) -> None:
    actual = _normalise_flag(row.get(field), f"模型 {model_id} {field}")
    if actual != expected:
        raise BackendVerificationError(f"模型 {model_id} {field} 回读不一致")


def _verify_model_unchanged_except(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    allowed_fields: set[str],
) -> None:
    keys = set(before) | set(after)
    for key in keys - set(allowed_fields):
        before_value = before.get(key, _MISSING)
        after_value = after.get(key, _MISSING)
        if before_value != after_value:
            raise BackendVerificationError(f"模型字段 {key} 在下架写入后发生未授权变化")


def _verify_unlist_product_rows(
    rows: Sequence[Mapping[str, Any]],
    model_id: int,
    *,
    require_auto_off: bool = False,
) -> None:
    """验证下架所需的产品字段；产品集合是否为空由范围核验层处理。"""

    for index, row in enumerate(rows):
        product_id = _product_id(row)
        if "total" not in row:
            raise BackendVerificationError(f"模型 {model_id} 产品第 {index + 1} 行缺少 total")
        _normalise_nonnegative_int(row.get("total"), f"产品 {product_id} total")
        if "auto_off" not in row:
            raise BackendVerificationError(f"模型 {model_id} 产品 {product_id} 缺少 auto_off，无法保证不修改产品开关")
        auto_off = _normalise_flag(row.get("auto_off"), f"产品 {product_id} auto_off")
        if require_auto_off and auto_off != 1:
            raise BackendVerificationError(
                f"模型 {model_id} 产品 {product_id} auto_off=0；仅开启模型级 auto_off 无法证明库存归零会实际下架，拒绝写入"
            )


def _verify_product_readback(
    rows: Sequence[Mapping[str, Any]],
    model_id: int,
    expected_product_ids: set[int],
    original_auto_off: Mapping[int, int],
    *,
    zero_ids: set[int],
) -> None:
    actual_ids = {_product_id(row) for row in rows}
    if actual_ids != expected_product_ids:
        raise BackendVerificationError(f"模型 {model_id} 产品前后回读范围不一致")
    for row in rows:
        product_id = _product_id(row)
        auto_off = _normalise_flag(row.get("auto_off"), f"产品 {product_id} auto_off")
        if auto_off != original_auto_off[product_id]:
            raise BackendVerificationError(f"产品 {product_id} auto_off 发生变化；下架流程不允许修改产品开关")
        total = _normalise_nonnegative_int(row.get("total"), f"产品 {product_id} total")
        if product_id in zero_ids and total != 0:
            raise BackendVerificationError(f"产品 {product_id} total 回读不是 0")


def _verify_product_scope(rows: Sequence[Mapping[str, Any]], model_id: int, *, allow_empty: bool = False) -> None:
    """核验实际产品行的 ID/范围，绝不拿模型行的 price 代替。"""

    if not rows and not allow_empty:
        raise BackendVerificationError(f"模型 {model_id} 没有可核验的实际产品行")
    product_ids: list[int] = []
    for index, row in enumerate(rows):
        product_id = _explicit_value(row, {"id", "product_id", "productId"})
        mid = _explicit_value(row, {"mid", "model_id", "modelId"})
        gid = _explicit_value(row, {"gid", "game_id", "gameId"})
        cid = _explicit_value(row, {"cid", "category_id", "categoryId"})
        try:
            product_id = int(product_id)
            mid = int(mid)
            gid = int(gid)
            cid = int(cid)
        except (TypeError, ValueError) as exc:
            raise BackendVerificationError(f"产品第 {index + 1} 行缺少可核验的 id/mid/gid/cid") from exc
        if product_id < 1 or mid != model_id or gid != SUPPORTED_GID or cid != SUPPORTED_CID:
            raise BackendVerificationError(f"产品第 {index + 1} 行超出模型或 FC27 范围")
        product_ids.append(product_id)
    if len(product_ids) != len(set(product_ids)):
        raise BackendVerificationError("产品列表含重复产品 ID")


def _product_ids(rows: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    values = []
    for row in rows:
        value = _explicit_value(row, {"id", "product_id", "productId"})
        try:
            values.append(int(value))
        except (TypeError, ValueError) as exc:
            raise BackendVerificationError("产品 ID 不是合法整数") from exc
    return tuple(sorted(values))


def _verify_product_values(rows: Sequence[Mapping[str, Any]], model_id: int) -> None:
    """内置核验实际产品售价字段的存在性和数值合法性，不重算后台定价公式。"""

    numeric_fields = ("unit_price", "num", "discount", "price")
    for index, row in enumerate(rows):
        for field in numeric_fields:
            value = row.get(field)
            if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
                raise BackendVerificationError(f"模型 {model_id} 产品第 {index + 1} 行缺少合法 {field}")
            try:
                number = Decimal(str(value).strip())
            except (InvalidOperation, ValueError) as exc:
                raise BackendVerificationError(f"模型 {model_id} 产品第 {index + 1} 行 {field} 不是合法数值") from exc
            if not number.is_finite() or number < 0:
                raise BackendVerificationError(f"模型 {model_id} 产品第 {index + 1} 行 {field} 数值非法")


def _builtin_product_result(rows: Sequence[Mapping[str, Any]], *, baseline: bool) -> Mapping[str, Any]:
    return {
        "verified": True,
        "baseline_captured": bool(baseline),
        "formula_verified": False,
        "product_count": len(rows),
        "verification_mode": "actual_products_structure_and_values",
    }


def _require_verifier_result(value: Any, *, phase: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("verified") is not True:
        raise BackendVerificationError(f"产品售价 {phase} 核验器必须返回 verified=true 的结构化结果")
    if phase == "before" and value.get("baseline_captured") is not True:
        raise BackendVerificationError("产品售价 before 核验缺少 baseline_captured=true")
    return value


def _required_count(payload: Mapping[str, Any], key: str) -> int:
    if key not in payload or payload[key] is None:
        raise BackendVerificationError(f"导入进度缺少 {key}")
    try:
        value = int(payload[key])
    except (TypeError, ValueError) as exc:
        raise BackendVerificationError(f"导入进度 {key} 不是整数") from exc
    if value < 0:
        raise BackendVerificationError(f"导入进度 {key} 不得为负数")
    return value


def _batch_write_unknown(
    operation: str,
    model_ids: Sequence[int],
    completed_model_ids: Sequence[int],
    failed_model_id: int,
    cause: BaseException,
    *,
    readback: Optional[Mapping[str, Any]] = None,
) -> BatchWriteUnknown:
    """把一次批量写入的未知终态压缩成可显示且不含凭据的报告。"""

    target_ids = [int(item) for item in model_ids]
    completed = [int(item) for item in completed_model_ids]
    report: dict[str, Any] = {
        "operation": operation,
        "status": "partial_or_unknown",
        "model_ids": target_ids,
        "completed_model_ids": completed,
        "completed_count": len(completed),
        "total_count": len(target_ids),
        "failed_model_id": int(failed_model_id),
        "pending_model_ids": [item for item in target_ids if item not in completed and item != int(failed_model_id)],
        "error_type": type(cause).__name__,
    }
    if isinstance(readback, Mapping):
        report["failed_model_readback"] = dict(readback)
    diagnostic = getattr(cause, "diagnostic", None)
    if isinstance(diagnostic, Mapping):
        # AdminClient 只提供脱敏摘要；复制白名单字段，防止未来异常对象携带原始响应。
        safe_diagnostic: dict[str, Any] = {}
        for key in ("method", "endpoint", "http_status", "response_code", "response_msg"):
            if key in diagnostic and isinstance(diagnostic[key], (str, int, float, bool, type(None))):
                safe_diagnostic[key] = diagnostic[key]
        if safe_diagnostic:
            report["diagnostic"] = safe_diagnostic

    message = (
        f"{operation} 已开始但未完成；目标模型 {int(failed_model_id)}；"
        f"已完成 {len(completed)}/{len(target_ids)} 个；已停止后续写入，"
        "状态未知，禁止盲目重试，请先只读回查。"
    )
    if isinstance(diagnostic, Mapping):
        endpoint = diagnostic.get("endpoint")
        response_msg = diagnostic.get("response_msg")
        if isinstance(endpoint, str) and endpoint:
            message += f" endpoint={str(diagnostic.get('method') or 'POST').upper()} {endpoint}"
        if isinstance(response_msg, str) and response_msg:
            message += f"；msg={response_msg}"
    if isinstance(readback, Mapping) and readback.get("status"):
        message += f"；失败模型只读回查={readback['status']}"
    return BatchWriteUnknown(message, report=report, cause=cause)


def _safe_tag_readback(
    adapter: AdminAdapter,
    model_id: int,
    requested: Sequence[int],
    *,
    mode: str,
    expected: Sequence[int],
) -> Mapping[str, Any]:
    """失败后仅做一次当前模型只读回查，返回不含原始响应的状态摘要。"""

    try:
        row = adapter.client.get_model(model_id)
        adapter._verify_model_scope(row, model_id)
        actual = _tag_ids(row)
        requested_set = set(requested)
        if mode == "remove":
            if requested_set.intersection(actual):
                status = "target_still_present"
            elif set(expected).difference(actual):
                status = "preserved_tags_missing"
            else:
                status = "target_absent"
        else:
            status = "requested_present" if requested_set.issubset(actual) else "requested_missing"
        return {"status": status, "tag_count": len(actual)}
    except Exception as exc:
        return {"status": "unknown", "error_type": type(exc).__name__}


__all__ = [
    "AdminAdapter",
    "AdminAdapterError",
    "AdapterBlocked",
    "BatchWriteUnknown",
    "BackendVerificationError",
    "ImportOutcome",
    "ImportPlan",
    "ImportUnknown",
    "NoNewPlayers",
    "UnlistOutcome",
    "UnlistPartialFailure",
    "UnlistPlan",
    "TaskStateStore",
    "WriteDisabled",
    "build_existing_model_map",
    "extract_futbin_id",
    "extract_model_id",
    "merge_tag_ids",
]

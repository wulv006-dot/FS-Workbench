"""FC27 FUTBIN 球员数据库的只读客户端。

这个模块只允许访问文档中已核实的只读端点：

* ``GET /api/players``
* ``GET /api/export/players``
* ``GET /api/status``

不会调用采集、回填、设置、代理或其他写入接口。导出采用临时文件加
``os.replace`` 的原子提交方式，并在提交前检查 XLSX 是有效 ZIP、包含
工作表、存在 ``FUTBIN ID`` 列、数据行非空且 ID 不重复。验证失败时目标
文件保持原状。

实现使用 Python 标准库，避免 GUI 或 CLI 必须额外安装 requests/openpyxl。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Mapping, Optional, Sequence
from xml.etree import ElementTree as ET

from .models import ExportFilters


DEFAULT_BASE_URL = "http://139.28.18.234:8001"

# 这是接口边界，不是业务字段的推断。未知字段会在本地被拒绝，避免把
# 拼写错误或 GUI 中的内部字段意外发送到后台。
PLAYER_FILTER_KEYS = (
    "q",
    "rating_min",
    "rating_max",
    "position",
    "league",
    "club",
    "nation",
    "days_new",
    "price_platform",
    "price_min",
    "price_max",
    "playstyle",
    "ps_type",
)
PLAYER_QUERY_KEYS = PLAYER_FILTER_KEYS + ("sort", "order", "page", "per_page", "all")
READ_ONLY_PATHS = frozenset({"/api/players", "/api/export/players", "/api/status"})


class PlayerDatabaseError(RuntimeError):
    """球员数据库客户端错误基类。"""


class ReadOnlyViolation(PlayerDatabaseError):
    """尝试访问未列入只读白名单的路径。"""


class PlayerDatabaseHttpError(PlayerDatabaseError):
    """HTTP、网络或响应格式错误。"""

    def __init__(self, message: str, *, status: Optional[int] = None, url: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.url = url


class WorkbookValidationError(PlayerDatabaseError):
    """导出的 XLSX 没有通过安全提交前验证。"""

    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


@dataclass(frozen=True)
class WorkbookValidation:
    """XLSX 结构与 FUTBIN ID 检查结果。"""

    path: str
    byte_size: int
    sheet_names: tuple[str, ...]
    headers: tuple[str, ...]
    row_count: int
    futbin_id_count: int
    unique_futbin_id_count: int
    duplicate_futbin_ids: tuple[str, ...]
    # 供导入前建立 FUTBIN ID -> 后台模型 ID 映射；to_dict 不展开，避免把
    # 可能很大的 ID 列写入运行日志。
    futbin_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "byte_size": self.byte_size,
            "sheet_names": list(self.sheet_names),
            "headers": list(self.headers),
            "row_count": self.row_count,
            "futbin_id_count": self.futbin_id_count,
            "unique_futbin_id_count": self.unique_futbin_id_count,
            "duplicate_futbin_ids": list(self.duplicate_futbin_ids),
            "valid": not self.duplicate_futbin_ids,
        }


@dataclass(frozen=True)
class PlayerQueryResult:
    """``/api/players`` 的最小稳定返回模型。"""

    total: Optional[int]
    items: tuple[Mapping[str, Any], ...]
    page: Optional[int] = None
    per_page: Optional[int] = None
    raw: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"total": self.total, "items": list(self.items)}
        if self.page is not None:
            result["page"] = self.page
        if self.per_page is not None:
            result["per_page"] = self.per_page
        return result


def _normalise_base_url(base_url: str) -> str:
    value = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url 必须是带 http/https 和主机名的 URL")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url 不得包含 query 或 fragment")
    return value


def _normalise_filters(filters: ExportFilters | Mapping[str, Any] | None) -> dict[str, Any]:
    if filters is None:
        return {}
    if isinstance(filters, ExportFilters):
        criteria = filters.criteria
    elif isinstance(filters, Mapping):
        # 兼容保存到 config.json 的 {"criteria": {...}} 形态。
        criteria = filters.get("criteria", filters)
    else:
        raise TypeError("filters 必须是 ExportFilters、映射或 None")
    if not isinstance(criteria, Mapping):
        raise TypeError("filters.criteria 必须是对象")
    unknown = sorted(str(key) for key in criteria if str(key) not in PLAYER_FILTER_KEYS)
    if unknown:
        raise ValueError(f"不支持的球员筛选字段: {', '.join(unknown)}")
    result: dict[str, Any] = {}
    for key in PLAYER_FILTER_KEYS:
        if key not in criteria or criteria[key] is None:
            continue
        value = criteria[key]
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        elif isinstance(value, (list, tuple, set)):
            value = ",".join(str(item).strip() for item in value if str(item).strip())
            if not value:
                continue
        result[key] = value
    return result


def _query_string(params: Mapping[str, Any]) -> str:
    # doseq=False 是刻意的：price_platform 等 API 参数的逗号分隔语义由
    # 服务端定义，客户端不把它改写成多次同名参数。
    return urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})


def _safe_url_path(path: str) -> str:
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ReadOnlyViolation(f"只允许传入相对 API 路径: {path}")
    normalized = "/" + parsed.path.lstrip("/")
    if normalized not in READ_ONLY_PATHS:
        raise ReadOnlyViolation(f"路径不在只读白名单中: {normalized}")
    return normalized


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PlayerDatabaseClient:
    """FC27 球员数据库只读客户端。

    ``opener`` 只用于测试注入，生产环境默认使用标准库 URL opener。
    ``timeout`` 是每个请求的秒数；不会自动重试，也不会并发请求。
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        opener: Optional[Callable[..., Any]] = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        self.base_url = _normalise_base_url(base_url)
        self.timeout = float(timeout)
        # A database host must never redirect the collector to an unapproved host.
        self._opener = opener or urllib.request.build_opener(_NoRedirect()).open

    def build_url(self, path: str, params: Optional[Mapping[str, Any]] = None) -> str:
        safe_path = _safe_url_path(path)
        query = _query_string(params or {})
        return f"{self.base_url}{safe_path}" + (f"?{query}" if query else "")

    def get_status(self) -> Mapping[str, Any]:
        payload = self._request_json("/api/status")
        if not isinstance(payload, Mapping):
            raise PlayerDatabaseHttpError("/api/status 返回的 JSON 根节点不是对象")
        return payload

    def list_players(
        self,
        filters: ExportFilters | Mapping[str, Any] | None = None,
        *,
        page: int = 1,
        per_page: int = 50,
        sort: str = "rating",
        order: str = "desc",
        all: bool = False,
    ) -> PlayerQueryResult:
        if page < 1:
            raise ValueError("page 必须大于等于 1")
        if per_page < 1 or per_page > 200:
            raise ValueError("per_page 必须在 1 到 200 之间")
        params = _normalise_filters(filters)
        params.update({"sort": sort, "order": order, "page": page, "per_page": per_page, "all": str(bool(all)).lower()})
        payload = self._request_json("/api/players", params)
        if not isinstance(payload, Mapping):
            raise PlayerDatabaseHttpError("/api/players 返回的 JSON 根节点不是对象")
        if "items" not in payload:
            raise PlayerDatabaseHttpError("/api/players 返回缺少 items")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise PlayerDatabaseHttpError("/api/players 返回的 items 不是列表")
        items: list[Mapping[str, Any]] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, Mapping):
                raise PlayerDatabaseHttpError(f"/api/players 返回的 items[{index}] 不是对象")
            items.append(item)
        if "total" not in payload:
            raise PlayerDatabaseHttpError("/api/players 返回缺少 total")
        total = payload.get("total")
        if not isinstance(total, int):
            try:
                total = int(total)
            except (TypeError, ValueError) as exc:
                raise PlayerDatabaseHttpError("/api/players 返回的 total 不是整数") from exc
        if total < 0:
            raise PlayerDatabaseHttpError("/api/players 返回的 total 不得为负数")
        returned_page = payload.get("page")
        returned_per_page = payload.get("per_page")
        return PlayerQueryResult(
            total=total,
            items=tuple(items),
            page=int(returned_page) if returned_page is not None else None,
            per_page=int(returned_per_page) if returned_per_page is not None else None,
            raw=payload,
        )

    def export_players(
        self,
        filters: ExportFilters | Mapping[str, Any] | None,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> WorkbookValidation:
        """下载并验证球员 XLSX，验证成功后原子提交到 ``destination``。

        目标存在且未传 ``overwrite=True`` 时直接失败。无论下载还是验证失败，
        都不会改变目标文件，也不会推进任何本地状态。
        """

        target = Path(destination).expanduser()
        if target.exists() and not overwrite:
            raise FileExistsError(f"目标文件已存在，未覆盖: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        params = _normalise_filters(filters)
        temp_name: Optional[str] = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=str(target.parent))
            os.close(fd)
            url = self.build_url("/api/export/players", params)
            with self._open(url) as response, open(temp_name, "wb") as handle:
                _copy_response(response, handle)
                handle.flush()
                os.fsync(handle.fileno())
            validation = validate_xlsx(Path(temp_name))
            if validation.duplicate_futbin_ids:
                raise WorkbookValidationError(
                    "导出 XLSX 含重复 FUTBIN ID，未提交目标文件",
                    details=validation.to_dict(),
                )
            if validation.row_count < 1:
                raise WorkbookValidationError("导出 XLSX 没有数据行，未提交目标文件", details=validation.to_dict())
            os.replace(temp_name, target)
            temp_name = None
            return WorkbookValidation(
                path=str(target),
                byte_size=target.stat().st_size,
                sheet_names=validation.sheet_names,
                headers=validation.headers,
                row_count=validation.row_count,
                futbin_id_count=validation.futbin_id_count,
                unique_futbin_id_count=validation.unique_futbin_id_count,
                duplicate_futbin_ids=validation.duplicate_futbin_ids,
                futbin_ids=validation.futbin_ids,
            )
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass

    def _open(self, url: str) -> Any:
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        try:
            return self._opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise PlayerDatabaseHttpError(f"GET 请求失败: HTTP {exc.code}", status=exc.code, url=url) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PlayerDatabaseHttpError(f"GET 请求失败: {exc}", url=url) from exc

    def _request_json(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        url = self.build_url(path, params)
        try:
            with self._open(url) as response:
                body = response.read()
        except PlayerDatabaseError:
            raise
        except Exception as exc:
            raise PlayerDatabaseHttpError(f"读取 JSON 响应失败: {exc}", url=url) from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlayerDatabaseHttpError("响应不是有效 UTF-8 JSON", url=url) from exc


def _copy_response(response: Any, target: BinaryIO, *, chunk_size: int = 1024 * 1024) -> int:
    total = 0
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise PlayerDatabaseHttpError("导出响应包含非二进制内容")
        target.write(chunk)
        total += len(chunk)
    if total == 0:
        raise PlayerDatabaseHttpError("导出响应为空")
    return total


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def _column_number(reference: str) -> int:
    match = _CELL_RE.match(reference.upper())
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def _shared_strings(root: ET.Element) -> list[str]:
    result: list[str] = []
    for item in root.findall(f"{_NS}si"):
        result.append("".join(text.text or "" for text in item.iter(f"{_NS}t")))
    return result


def _cell_value(cell: ET.Element, shared: Sequence[str]) -> str:
    kind = cell.attrib.get("t", "")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{_NS}t"))
    value = cell.find(f"{_NS}v")
    raw = value.text if value is not None and value.text is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            raise WorkbookValidationError("XLSX 的 shared string 索引无效")
    return raw


def _worksheet_rows(root: ET.Element, shared: Sequence[str]) -> list[dict[int, str]]:
    rows: list[dict[int, str]] = []
    sheet_data = root.find(f"{_NS}sheetData")
    if sheet_data is None:
        return rows
    for row in sheet_data.findall(f"{_NS}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{_NS}c"):
            column = _column_number(cell.attrib.get("r", ""))
            if column:
                values[column] = _cell_value(cell, shared)
        rows.append(values)
    return rows


def validate_xlsx(path: str | Path) -> WorkbookValidation:
    """检查一个球员导出 XLSX，不改变文件。"""

    source = Path(path)
    if not source.is_file():
        raise WorkbookValidationError(f"XLSX 文件不存在: {source}")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise WorkbookValidationError(f"XLSX ZIP 校验失败: {bad_member}")
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise WorkbookValidationError("XLSX ZIP 含重复成员")
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise WorkbookValidationError("XLSX 缺少必需的 Office Open XML 部件")
            try:
                workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
            except ET.ParseError as exc:
                raise WorkbookValidationError("XLSX workbook.xml 不是有效 XML") from exc
            rels = {element.attrib.get("Id"): element.attrib.get("Target", "") for element in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")).iter() if element.tag.endswith("}Relationship")}
            sheet_names: list[str] = []
            all_rows: list[dict[int, str]] = []
            sheets = workbook_root.find(f"{_NS}sheets")
            if sheets is None:
                raise WorkbookValidationError("XLSX 没有工作表")
            for sheet in sheets.findall(f"{_NS}sheet"):
                name = sheet.attrib.get("name", "")
                sheet_names.append(name)
                target = rels.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "")
                target = target.lstrip("/")
                if target.startswith("xl/"):
                    member = target
                else:
                    member = "xl/" + target
                if member not in names:
                    raise WorkbookValidationError(f"XLSX 工作表部件不存在: {member}")
                try:
                    sheet_root = ET.fromstring(archive.read(member))
                except ET.ParseError as exc:
                    raise WorkbookValidationError(f"XLSX 工作表 XML 无效: {member}") from exc
                shared: list[str] = []
                if "xl/sharedStrings.xml" in names:
                    shared = _shared_strings(ET.fromstring(archive.read("xl/sharedStrings.xml")))
                rows = _worksheet_rows(sheet_root, shared)
                if not all_rows:
                    all_rows = rows
            if not sheet_names:
                raise WorkbookValidationError("XLSX 没有工作表")
    except zipfile.BadZipFile as exc:
        raise WorkbookValidationError("文件不是有效 XLSX ZIP") from exc
    except KeyError as exc:
        raise WorkbookValidationError(f"XLSX 缺少必需部件: {exc}") from exc

    if not all_rows:
        raise WorkbookValidationError("XLSX 工作表没有行")
    header_row = all_rows[0]
    max_column = max(header_row, default=0)
    headers = tuple(header_row.get(index, "").strip() for index in range(1, max_column + 1))
    id_index = next((index for index, value in enumerate(headers, start=1) if value.casefold() == "futbin id"), None)
    if id_index is None:
        raise WorkbookValidationError("XLSX 缺少 FUTBIN ID 列", details={"headers": list(headers)})
    ids: list[str] = []
    for row_number, row in enumerate(all_rows[1:], start=2):
        raw_id = str(row.get(id_index, "")).strip()
        if not raw_id:
            raise WorkbookValidationError(f"XLSX 第 {row_number} 行 FUTBIN ID 为空")
        ids.append(raw_id)
    duplicates = tuple(sorted(value for value, count in Counter(ids).items() if count > 1))
    return WorkbookValidation(
        path=str(source),
        byte_size=source.stat().st_size,
        sheet_names=tuple(sheet_names),
        headers=headers,
        row_count=len(ids),
        futbin_id_count=len(ids),
        unique_futbin_id_count=len(set(ids)),
        duplicate_futbin_ids=duplicates,
        futbin_ids=tuple(ids),
    )


def read_futbin_ids(path: str | Path) -> tuple[str, ...]:
    """读取已通过 XLSX 验证的 FUTBIN ID，供导入前去重映射使用。"""

    return validate_xlsx(path).futbin_ids


__all__ = [
    "DEFAULT_BASE_URL",
    "PLAYER_FILTER_KEYS",
    "PLAYER_QUERY_KEYS",
    "READ_ONLY_PATHS",
    "PlayerDatabaseClient",
    "PlayerDatabaseError",
    "PlayerDatabaseHttpError",
    "PlayerQueryResult",
    "ReadOnlyViolation",
    "WorkbookValidation",
    "WorkbookValidationError",
    "validate_xlsx",
    "read_futbin_ids",
]

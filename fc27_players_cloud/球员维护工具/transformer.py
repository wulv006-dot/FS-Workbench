"""离线球员工作簿转换。

这个模块只读 ``.xlsx``/``.xlsm``，不会运行宏，也不会修改输入文件。输入表
可以是后台导出的中文 30 列格式，也可以是已经符合模板的英文 25 列格式。
转换后的文件使用标准库直接写成只含一个 ``球员`` sheet 的数据型 xlsx；读取
阶段使用 openpyxl 的只读模式，是为了兼容 xlsm 中的共享字符串、日期和隐藏
工作表，而不是为了复用或保存原工作簿。

设计边界：模块只校验结构、唯一 ID、卡片评分存在性以及 Excel 公式注入，
不对球员评分、价格、位置范围等业务值自行猜测。缺失价格保持为空，不能用
零补齐。
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import zipfile
import argparse
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from xml.sax.saxutils import escape, quoteattr


SHEET_NAME = "球员"

# 权威模板原先是一份放在开发者桌面上的 .xlsm 文件，仅用于提供下面 25 个
# 表头（转换本身手写 XML 生成 xlsx，从不复制模板样式，见 _write_xlsx）。
# 2026-09-26：改为内置常量，彻底去掉对本地模板文件的依赖，解压即可用。
# 根因记录：模板文件只被 validate_template 读取表头，输出内容与之无关，
# 因此内置等价、零效果损失。如需外部覆盖，用 set_template_override()。
DEFAULT_TEMPLATE_PATH: Optional[Path] = None
_TEMPLATE_OVERRIDE: Optional[Path] = None
# 内置表头哨兵：语义上代表「权威模板」，实际是代码内常量而非文件。
BUILTIN_TEMPLATE = "<builtin:25-column-headers>"

EN_HEADERS: tuple[str, ...] = (
    "name",
    "Version",
    "Club",
    "League",
    "Nation",
    "AlternativePositions",
    "Position",
    "untradeable",
    "Rating",
    "IS",
    "Player_Height",
    "Foot",
    "Skills",
    "WeakFoot",
    "PAC",
    "SHO",
    "PAS",
    "DRI",
    "DEF",
    "PHY",
    "PC",
    "PS",
    "PlayStyle",
    "PlayStyle+",
    "FUTBIN ID",
)

RAW_HEADERS: tuple[str, ...] = (
    "球员名",
    "卡版本",
    "俱乐部",
    "联赛",
    "国家",
    "位置",
    "角色",
    "可交易",
    "总评",
    "卡片评分",
    "身高",
    "体重",
    "惯用脚",
    "攻跑位",
    "防跑位",
    "加速类型",
    "花式",
    "逆足",
    "PAC",
    "SHO",
    "PAS",
    "DRI",
    "DEF",
    "PHY",
    "PC价",
    "PS价",
    "XBOX价",
    "PlayStyle",
    "PlayStyle+",
    "FUTBIN ID",
)

# This mapping is deliberately explicit. In particular, 可交易 keeps its source
# 是/否 meaning even though the target field is named untradeable.
RAW_TO_EN: dict[str, str] = {
    "球员名": "name",
    "卡版本": "Version",
    "俱乐部": "Club",
    "联赛": "League",
    "国家": "Nation",
    "位置": "AlternativePositions",
    "角色": "Position",
    "可交易": "untradeable",
    "总评": "Rating",
    "卡片评分": "IS",
    "身高": "Player_Height",
    "惯用脚": "Foot",
    "花式": "Skills",
    "逆足": "WeakFoot",
    "PAC": "PAC",
    "SHO": "SHO",
    "PAS": "PAS",
    "DRI": "DRI",
    "DEF": "DEF",
    "PHY": "PHY",
    "PC价": "PC",
    "PS价": "PS",
    "PlayStyle": "PlayStyle",
    "PlayStyle+": "PlayStyle+",
    "FUTBIN ID": "FUTBIN ID",
}

REMOVED_RAW_HEADERS: tuple[str, ...] = ("体重", "攻跑位", "防跑位", "加速类型", "XBOX价")


class TransformationError(ValueError):
    """转换被安全阻断；``report`` 中包含逐行或结构校验结果。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        report: Optional[Mapping[str, Any]] = None,
        report_path: Optional[Path] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.report = dict(report or {})
        self.report_path = str(report_path) if report_path else ""


# Short aliases make the exception convenient for the pipeline adapter without
# forcing it to depend on an implementation-specific class name.
TransformError = TransformationError
WorkbookTransformError = TransformationError


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    column: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class RowReport:
    row_number: int
    status: str
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "status": self.status,
            "issues": [item.to_dict() for item in self.issues],
        }


@dataclass
class ConversionResult:
    status: str
    input_path: str
    output_path: str
    report_path: str
    source_sheet: str
    schema: str
    rows_converted: int
    row_reports: list[RowReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["row_reports"] = [item.to_dict() for item in self.row_reports]
        return data


@dataclass
class NewPlayersResult:
    """按 FUTBIN ID 排除已有球员后的离线结果。

    ``status`` 沿用后台 ``ImportPlan`` 的 ``ready``/``no_new_players`` 语义；
    ``code`` 在零新增时明确为 ``NoNewPlayers``，便于 GUI 在没有上传文件时
    直接结束流程。
    """

    status: str
    code: str
    input_path: str
    output_path: str
    report_path: str
    source_sheet: str
    schema: str
    all_count: int
    existing_count: int
    new_count: int
    upload_count: int
    existing_futbin_ids: tuple[str, ...] = ()
    new_futbin_ids: tuple[str, ...] = ()
    no_upload: bool = False
    row_reports: list[RowReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "report_path": self.report_path,
            "source_sheet": self.source_sheet,
            "schema": self.schema,
            "all_count": self.all_count,
            "existing_count": self.existing_count,
            "new_count": self.new_count,
            "upload_count": self.upload_count,
            "existing_futbin_ids": list(self.existing_futbin_ids),
            "new_futbin_ids": list(self.new_futbin_ids),
            "no_upload": self.no_upload,
            "row_reports": [item.to_dict() for item in self.row_reports],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass
class _SheetMatch:
    title: str
    schema: str
    headers: tuple[str, ...]


def _text(value: Any) -> str:
    """Return a header/display string without changing data values."""

    if value is None:
        return ""
    return str(value).strip()


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical_id(value: Any) -> str:
    """Canonical key only for duplicate detection; output keeps original value."""

    if _blank(value):
        return ""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _valid_id(value: Any) -> bool:
    """Validate the ID shape without changing the value written to xlsx."""

    if _blank(value) or isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value) and value.is_integer()
    if isinstance(value, str):
        return bool(re.fullmatch(r"\d+", value.strip()))
    return False


def _formula_issue(value: Any, cell: Any = None) -> bool:
    """Excel formula or formula-like string that must never reach output xlsx."""

    if cell is not None and getattr(cell, "data_type", None) == "f":
        return True
    if not isinstance(value, str):
        return False
    stripped = value.lstrip()
    return bool(stripped) and stripped[0] in "=+-@"


def _require_openpyxl() -> Any:
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:  # pragma: no cover - bundled runtime includes it
        raise TransformationError(
            "OPENPYXL_REQUIRED",
            "读取 xlsx/xlsm 需要 openpyxl；未写入任何输出文件",
        ) from exc
    return openpyxl


def _check_workbook_path(path: Path, *, label: str) -> Path:
    path = Path(path).expanduser()
    if not path.exists():
        raise TransformationError(f"{label.upper()}_NOT_FOUND", f"{label}不存在：{path}")
    if not path.is_file():
        raise TransformationError(f"{label.upper()}_NOT_FILE", f"{label}不是文件：{path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise TransformationError(
            f"{label.upper()}_EXTENSION",
            f"{label}必须是 .xlsx 或 .xlsm：{path.name}",
        )
    return path.resolve()


def _load_workbook(path: Path) -> Any:
    openpyxl = _require_openpyxl()
    try:
        # data_only=False is intentional: formulas are a hard validation error,
        # not cached values to be silently copied.
        return openpyxl.load_workbook(path, read_only=True, data_only=False, keep_vba=False)
    except Exception as exc:
        raise TransformationError("WORKBOOK_READ_FAILED", f"无法读取工作簿：{path.name}；{exc}") from exc


def _header_values(ws: Any) -> tuple[str, ...]:
    if ws.max_row < 1 or ws.max_column < 1:
        return ()
    return tuple(_text(cell.value) for cell in next(ws.iter_rows(min_row=1, max_row=1)))


def _matching_sheets(wb: Any, expected: Sequence[str]) -> list[tuple[Any, tuple[str, ...]]]:
    matches: list[tuple[Any, tuple[str, ...]]] = []
    expected_tuple = tuple(expected)
    for ws in wb.worksheets:
        headers = _header_values(ws)
        if headers == expected_tuple:
            matches.append((ws, headers))
    return matches


def _candidate_diagnostics(wb: Any) -> str:
    values: list[str] = []
    for ws in wb.worksheets:
        headers = _header_values(ws)
        if headers:
            preview = ",".join(headers[:6])
            suffix = "..." if len(headers) > 6 else ""
            values.append(f"{ws.title}[{preview}{suffix}]")
    return "; ".join(values[:12])


def _find_input_sheet(wb: Any) -> _SheetMatch:
    raw = _matching_sheets(wb, RAW_HEADERS)
    english = _matching_sheets(wb, EN_HEADERS)
    total = len(raw) + len(english)
    if total == 0:
        diagnostics = _candidate_diagnostics(wb)
        missing_hint = ""
        for ws in wb.worksheets:
            headers = _header_values(ws)
            if headers and "卡片评分" not in headers and "球员名" in headers:
                missing_hint = "；候选中文表头缺少 卡片评分，不能补 0"
                break
        raise TransformationError(
            "NO_MATCHING_SHEET",
            f"未找到精准匹配的中文 30 列或英文 25 列表头{missing_hint}。候选：{diagnostics or '无表头'}",
        )
    if total > 1:
        names = [ws.title for ws, _ in raw] + [ws.title for ws, _ in english]
        raise TransformationError("AMBIGUOUS_SHEET", f"匹配表头的工作表不唯一：{', '.join(names)}")
    if raw:
        ws, headers = raw[0]
        return _SheetMatch(ws.title, "raw_zh", headers)
    ws, headers = english[0]
    return _SheetMatch(ws.title, "template_en", headers)


def set_template_override(template_path: str | os.PathLike[str] | None) -> None:
    """可选：用外部模板文件覆盖内置表头。传 None 恢复内置常量。

    多数场景不需要——内置表头即权威 25 列。仅当后台改了导入列序、需要临时
    以某份新模板为准时才用。设置后仍会做严格校验，不合法即报错。
    """

    global _TEMPLATE_OVERRIDE
    _TEMPLATE_OVERRIDE = None if template_path is None else Path(template_path).expanduser()


def validate_template(template_path: str | os.PathLike[str] | None = None) -> tuple[str, ...]:
    """返回球员 sheet 的 25 个精准表头。

    默认走内置常量（无外部文件依赖）；仅当显式传入路径、或调用过
    :func:`set_template_override` 时，才读外部模板并严格校验。
    """

    candidate = template_path if template_path is not None else _TEMPLATE_OVERRIDE
    if candidate is None:
        return EN_HEADERS
    path = _check_workbook_path(Path(candidate), label="模板")
    wb = _load_workbook(path)
    try:
        matches = _matching_sheets(wb, EN_HEADERS)
        if len(matches) != 1:
            raise TransformationError(
                "INVALID_TEMPLATE",
                f"模板必须恰好有一张精准匹配 25 列表头的 sheet，实际为 {len(matches)} 张",
            )
        ws, headers = matches[0]
        if ws.title != SHEET_NAME:
            raise TransformationError(
                "INVALID_TEMPLATE_SHEET",
                f"模板精准表头所在 sheet 必须名为 {SHEET_NAME}，实际为 {ws.title}",
            )
        return headers
    finally:
        wb.close()


def _read_rows(path: Path, match: _SheetMatch) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """Read selected sheet and retain source row numbers for row reports."""

    wb = _load_workbook(path)
    try:
        ws = wb[match.title]
        rows: list[list[Any]] = []
        metadata: list[dict[str, Any]] = []
        width = len(match.headers)
        for row_number, row in enumerate(ws.iter_rows(min_row=2), start=2):
            values = [cell.value for cell in row[:width]]
            extras = [cell for cell in row[width:] if not _blank(cell.value)]
            if all(_blank(value) for value in values) and not extras:
                continue
            rows.append(values)
            metadata.append(
                {
                    "row_number": row_number,
                    "extra_cells": extras,
                    "cells": list(row[:width]),
                }
            )
        return rows, metadata
    finally:
        wb.close()


def _map_row(values: Sequence[Any], schema: str) -> dict[str, Any]:
    if schema == "template_en":
        return {header: values[index] if index < len(values) else None for index, header in enumerate(EN_HEADERS)}
    source = {header: values[index] if index < len(values) else None for index, header in enumerate(RAW_HEADERS)}
    return {target: source.get(raw) for raw, target in RAW_TO_EN.items()}


def _validate_rows(
    rows: Sequence[Sequence[Any]], metadata: Sequence[Mapping[str, Any]], schema: str
) -> tuple[list[dict[str, Any]], list[RowReport], list[str]]:
    mapped: list[dict[str, Any]] = []
    reports: list[RowReport] = []
    errors: list[str] = []
    id_rows: dict[str, list[int]] = {}
    for values, info in zip(rows, metadata):
        mapped_row = _map_row(values, schema)
        mapped.append(mapped_row)
        row_no = int(info["row_number"])
        issues: list[Issue] = []
        for index, value in enumerate(values):
            cell = info["cells"][index] if index < len(info["cells"]) else None
            if _formula_issue(value, cell):
                column = (RAW_HEADERS if schema == "raw_zh" else EN_HEADERS)[index]
                issues.append(Issue("FORMULA_INPUT", "error", "输入含公式或公式样式字符串，已阻断", column))
        for cell in info.get("extra_cells", []):
            if _formula_issue(cell.value, cell):
                issues.append(Issue("FORMULA_INPUT", "error", "额外单元格含公式或公式样式字符串，已阻断"))
            else:
                issues.append(Issue("EXTRA_DATA", "error", "表头之外存在非空数据，已阻断"))
        if _blank(mapped_row.get("name")):
            issues.append(Issue("MISSING_NAME", "error", "球员名不能为空", "name"))
        if _blank(mapped_row.get("FUTBIN ID")):
            issues.append(Issue("MISSING_FUTBIN_ID", "error", "FUTBIN ID 不能为空", "FUTBIN ID"))
        elif not _valid_id(mapped_row["FUTBIN ID"]):
            issues.append(Issue("INVALID_FUTBIN_ID", "error", "FUTBIN ID 必须是整数或数字文本", "FUTBIN ID"))
        else:
            id_rows.setdefault(_canonical_id(mapped_row["FUTBIN ID"]), []).append(row_no)
        if _blank(mapped_row.get("IS")):
            issues.append(Issue("MISSING_CARD_SCORE", "error", "卡片评分映射到 IS 后不能为空，不能补 0", "IS"))
        report = RowReport(row_no, "error" if issues else "ok", issues)
        reports.append(report)
    reports_by_row = {report.row_number: report for report in reports}
    for row_numbers in id_rows.values():
        if len(row_numbers) <= 1:
            continue
        for row_number in row_numbers:
            report = reports_by_row[row_number]
            report.issues.append(
                Issue("DUPLICATE_FUTBIN_ID", "error", f"FUTBIN ID 重复（涉及行：{', '.join(map(str, row_numbers))}）", "FUTBIN ID")
            )
            report.status = "error"
    for report in reports:
        for issue in report.issues:
            if issue.severity == "error":
                errors.append(f"第 {report.row_number} 行 {issue.column + '：' if issue.column else ''}{issue.message}")
    return mapped, reports, errors


def _safe_candidate(path: Path) -> Path:
    """Choose a new path without overwriting any existing file."""

    path = path.resolve()
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise TransformationError("OUTPUT_PATH_EXHAUSTED", f"无法为输出文件找到未占用路径：{path}")


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_converted.xlsx")


def _default_report_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.report.json")


def _xml_cell_ref(column_index: int, row_index: int) -> str:
    letters = ""
    value = column_index
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index}"


def _serializable_value(value: Any) -> tuple[str, str] | None:
    """Return OOXML cell type and escaped value; ``None`` means blank."""

    if _blank(value):
        return None
    if isinstance(value, bool):
        return "b", "1" if value else "0"
    if isinstance(value, int):
        return "n", str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Excel 不支持非有限数字")
        return "n", repr(value)
    if isinstance(value, (datetime, date, time)):
        return "inlineStr", escape(value.isoformat())
    return "inlineStr", escape(str(value))


def _write_xlsx(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write a minimal data-only xlsx with one worksheet, atomically."""

    sheet_rows: list[str] = []
    all_rows: list[Sequence[Any]] = [EN_HEADERS]
    all_rows.extend([[row.get(header) for header in EN_HEADERS] for row in rows])
    for row_number, values in enumerate(all_rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(values, start=1):
            serial = _serializable_value(value)
            if serial is None:
                continue
            cell_type, text_value = serial
            ref = _xml_cell_ref(column_index, row_number)
            if cell_type == "inlineStr":
                cells.append(f'<c r={quoteattr(ref)} t="inlineStr"><is><t>{text_value}</t></is></c>')
            else:
                cells.append(f'<c r={quoteattr(ref)} t={quoteattr(cell_type)}><v>{text_value}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<dimension ref="A1:Y%d"/><sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetData>%s</sheetData></worksheet>' % (len(all_rows), "".join(sheet_rows))
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="球员" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="0"/><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types.encode("utf-8"))
            archive.writestr("_rels/.rels", root_rels.encode("utf-8"))
            archive.writestr("xl/workbook.xml", workbook_xml.encode("utf-8"))
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels.encode("utf-8"))
            archive.writestr("xl/worksheets/sheet1.xml", worksheet.encode("utf-8"))
            archive.writestr("xl/styles.xml", styles.encode("utf-8"))
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _template_label(template: Optional[Path]) -> str:
    """报告的模板来源标注：未用外部模板时明确写出「内置表头」。"""

    return "（内置 25 列表头，无外部模板）" if template is None else str(template)


def _publish_blocked_report(
    report_path: Path,
    *,
    source: Path,
    template: Optional[Path],
    error: TransformationError,
    source_sheet: str = "",
    schema: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "blocked",
        "input_path": str(source),
        "template_path": _template_label(template),
        "source_sheet": source_sheet,
        "schema": schema,
        "headers": list(EN_HEADERS),
        "output_path": "",
        "report_path": str(report_path),
        "rows_seen": 0,
        "rows_converted": 0,
        "errors": [f"{error.code}: {error.message}"],
        "warnings": [],
        "row_reports": [],
    }
    _write_json(report_path, payload)
    error.report = payload
    error.report_path = str(report_path)
    return payload


def convert_workbook(
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    *,
    template_path: str | os.PathLike[str] | None = None,
    report_path: str | os.PathLike[str] | None = None,
) -> ConversionResult:
    """Convert one raw or English workbook into a pure-data xlsx.

    Existing paths are never overwritten. If a requested output/report path is
    occupied, a `` (1)``, `` (2)`` ... sibling is selected and returned in the
    result. Validation errors still produce a report and raise
    :class:`TransformationError`; no output workbook is produced on failure.

    ``template_path`` 默认 None：使用内置 25 列表头，不读任何本地模板文件。
    """

    source = _check_workbook_path(Path(input_path), label="输入")
    template = None if (template_path is None and _TEMPLATE_OVERRIDE is None) else Path(template_path if template_path is not None else _TEMPLATE_OVERRIDE)
    if template is not None:
        template = _check_workbook_path(template, label="模板")
    if output_path is None:
        desired_output = _default_output_path(source)
    else:
        desired_output = Path(output_path).expanduser().resolve()
    if desired_output.suffix.lower() != ".xlsx":
        raise TransformationError("OUTPUT_EXTENSION", "输出必须是真正的 .xlsx 文件")
    if template is not None and desired_output in {source, template}:
        raise TransformationError("OUTPUT_SOURCE_CONFLICT", "输出路径不能覆盖输入文件或权威模板")
    actual_output = _safe_candidate(desired_output)
    if report_path is None:
        desired_report = _default_report_path(actual_output)
    else:
        desired_report = Path(report_path).expanduser().resolve()
    conflicts = {source, actual_output} | ({template} if template is not None else set())
    if desired_report in conflicts:
        raise TransformationError("REPORT_PATH_CONFLICT", "校验报告路径不能覆盖输入、模板或输出文件")
    actual_report = _safe_candidate(desired_report)

    # Verify the template before touching the input. This ensures a stale or
    # incorrectly chosen players_export workbook cannot silently define schema.
    try:
        template_headers = validate_template(template)
        wb = _load_workbook(source)
        try:
            match = _find_input_sheet(wb)
        finally:
            wb.close()
    except TransformationError as exc:
        _publish_blocked_report(actual_report, source=source, template=template, error=exc)
        raise

    try:
        rows, metadata = _read_rows(source, match)
    except TransformationError as exc:
        _publish_blocked_report(
            actual_report,
            source=source,
            template=template,
            error=exc,
            source_sheet=match.title,
            schema=match.schema,
        )
        raise
    row_reports: list[RowReport] = []
    mapped: list[dict[str, Any]] = []
    errors: list[str] = []
    if not rows:
        errors.append("未找到任何非空球员数据行")
    else:
        mapped, row_reports, errors = _validate_rows(rows, metadata, match.schema)
    report_payload: dict[str, Any] = {
        "status": "blocked" if errors else "writing",
        "input_path": str(source),
        "template_path": _template_label(template),
        "source_sheet": match.title,
        "schema": match.schema,
        "headers": list(template_headers),
        "output_path": str(actual_output) if not errors else "",
        "report_path": str(actual_report),
        "rows_seen": len(rows),
        "rows_converted": 0 if errors else len(mapped),
        "errors": errors,
        "warnings": [],
        "row_reports": [item.to_dict() for item in row_reports],
    }
    _write_json(actual_report, report_payload)
    if errors:
        error_summary = "；".join(errors[:3])
        raise TransformationError(
            "VALIDATION_BLOCKED",
            f"转换已阻断：{len(errors)} 个校验错误（{error_summary}）；详见 {actual_report}",
            report=report_payload,
            report_path=actual_report,
        )
    try:
        _write_xlsx(actual_output, mapped)
    except Exception as exc:
        failed_payload = dict(report_payload)
        failed_payload["status"] = "failed"
        failed_payload["errors"] = [f"OUTPUT_WRITE_FAILED: {exc}"]
        try:
            _write_json(actual_report, failed_payload)
        finally:
            raise TransformationError(
                "OUTPUT_WRITE_FAILED",
                f"输出 xlsx 写入失败，未完成转换：{exc}；详见 {actual_report}",
                report=failed_payload,
                report_path=actual_report,
            ) from exc
    result = ConversionResult(
        status="success",
        input_path=str(source),
        output_path=str(actual_output),
        report_path=str(actual_report),
        source_sheet=match.title,
        schema=match.schema,
        rows_converted=len(mapped),
        row_reports=row_reports,
    )
    # The report is intentionally rewritten after the output exists so it is a
    # truthful completion record even if a future writer implementation changes.
    report_payload.update(result.to_dict())
    _write_json(actual_report, report_payload)
    return result


def _normalize_existing_ids(existing_futbin_ids: Iterable[Any] | str | None) -> tuple[set[str], tuple[str, ...]]:
    """Normalize the caller's existing-ID list without treating blanks as IDs."""

    if existing_futbin_ids is None:
        values: Iterable[Any] = ()
    elif isinstance(existing_futbin_ids, str):
        values = (item for line in existing_futbin_ids.splitlines() for item in line.replace(",", "\n").splitlines())
    else:
        try:
            values = iter(existing_futbin_ids)
        except TypeError as exc:
            raise TransformationError("INVALID_EXISTING_IDS", "已有 FUTBIN ID 必须是可迭代列表或文本") from exc
    keys: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if _blank(value):
            continue
        if not _valid_id(value):
            raise TransformationError("INVALID_EXISTING_ID", f"已有 FUTBIN ID 无效：{value!r}")
        key = _canonical_id(value)
        if key not in keys:
            keys.add(key)
            ordered.append(key)
    return keys, tuple(ordered)


def filter_existing_players(
    input_path: str | os.PathLike[str],
    existing_futbin_ids: Iterable[Any] | str | None,
    output_path: str | os.PathLike[str] | None = None,
    *,
    template_path: str | os.PathLike[str] | None = None,
    report_path: str | os.PathLike[str] | None = None,
) -> NewPlayersResult:
    """Create an xlsx containing only rows whose FUTBIN ID is not existing.

    The source may use either the raw Chinese 30-column schema or the validated
    English 25-column schema. Existing rows are excluded by FUTBIN ID only;
    player names are never used as a key. A missing source ID is a validation
    error and therefore cannot be classified as a new player. If every valid
    row already exists, no output workbook is written and the returned result
    has ``status='no_new_players'``, ``code='NoNewPlayers'``, ``new_count=0``
    and ``no_upload=True``.

    ``template_path`` 默认 None：使用内置 25 列表头，不读任何本地模板文件。
    """

    source = _check_workbook_path(Path(input_path), label="输入")
    template = None if (template_path is None and _TEMPLATE_OVERRIDE is None) else Path(template_path if template_path is not None else _TEMPLATE_OVERRIDE)
    if template is not None:
        template = _check_workbook_path(template, label="模板")
    desired_output = _default_output_path(source).with_name(f"{source.stem}_new_only.xlsx") if output_path is None else Path(output_path).expanduser().resolve()
    if desired_output.suffix.lower() != ".xlsx":
        raise TransformationError("OUTPUT_EXTENSION", "输出必须是真正的 .xlsx 文件")
    if template is not None and desired_output in {source, template}:
        raise TransformationError("OUTPUT_SOURCE_CONFLICT", "输出路径不能覆盖输入文件或权威模板")
    actual_output = _safe_candidate(desired_output)
    desired_report = _default_report_path(actual_output) if report_path is None else Path(report_path).expanduser().resolve()
    conflicts = {source, actual_output} | ({template} if template is not None else set())
    if desired_report in conflicts:
        raise TransformationError("REPORT_PATH_CONFLICT", "校验报告路径不能覆盖输入、模板或输出文件")
    actual_report = _safe_candidate(desired_report)

    try:
        existing_keys, existing_ordered = _normalize_existing_ids(existing_futbin_ids)
        template_headers = validate_template(template)
        wb = _load_workbook(source)
        try:
            match = _find_input_sheet(wb)
        finally:
            wb.close()
        rows, metadata = _read_rows(source, match)
    except TransformationError as exc:
        _publish_blocked_report(actual_report, source=source, template=template, error=exc)
        raise

    if not rows:
        errors = ["未找到任何非空球员数据行"]
        payload = {
            "status": "blocked",
            "code": "VALIDATION_BLOCKED",
            "input_path": str(source),
            "template_path": _template_label(template),
            "source_sheet": match.title,
            "schema": match.schema,
            "headers": list(template_headers),
            "output_path": "",
            "report_path": str(actual_report),
            "all_count": 0,
            "existing_count": 0,
            "new_count": 0,
            "upload_count": 0,
            "existing_futbin_ids": [],
            "new_futbin_ids": [],
            "no_upload": True,
            "errors": errors,
            "warnings": [],
            "row_reports": [],
        }
        _write_json(actual_report, payload)
        raise TransformationError("VALIDATION_BLOCKED", f"转换已阻断：{errors[0]}；详见 {actual_report}", report=payload, report_path=actual_report)

    mapped, row_reports, errors = _validate_rows(rows, metadata, match.schema)
    if errors:
        payload = {
            "status": "blocked",
            "code": "VALIDATION_BLOCKED",
            "input_path": str(source),
            "template_path": _template_label(template),
            "source_sheet": match.title,
            "schema": match.schema,
            "headers": list(template_headers),
            "output_path": "",
            "report_path": str(actual_report),
            "all_count": len(mapped),
            "existing_count": 0,
            "new_count": 0,
            "upload_count": 0,
            "existing_futbin_ids": [],
            "new_futbin_ids": [],
            "no_upload": True,
            "errors": errors,
            "warnings": [],
            "row_reports": [item.to_dict() for item in row_reports],
        }
        _write_json(actual_report, payload)
        error_summary = "；".join(errors[:3])
        raise TransformationError(
            "VALIDATION_BLOCKED",
            f"转换已阻断：{len(errors)} 个校验错误（{error_summary}）；详见 {actual_report}",
            report=payload,
            report_path=actual_report,
        )

    new_rows: list[dict[str, Any]] = []
    existing_source_ids: list[str] = []
    new_source_ids: list[str] = []
    seen_existing: set[str] = set()
    for row, row_report in zip(mapped, row_reports):
        key = _canonical_id(row["FUTBIN ID"])
        if key in existing_keys:
            if key not in seen_existing:
                seen_existing.add(key)
                existing_source_ids.append(key)
            row_report.status = "excluded"
            row_report.issues.append(Issue("EXISTING_FUTBIN_ID", "info", "FUTBIN ID 已存在，未写入新增文件", "FUTBIN ID"))
        else:
            new_rows.append(row)
            new_source_ids.append(key)
            row_report.status = "new"

    all_count = len(mapped)
    existing_count = len(existing_source_ids)
    new_count = len(new_rows)
    status = "ready" if new_count else "no_new_players"
    code = "Ready" if new_count else "NoNewPlayers"
    payload: dict[str, Any] = {
        "status": "writing" if new_count else status,
        "code": code,
        "input_path": str(source),
        "template_path": _template_label(template),
        "source_sheet": match.title,
        "schema": match.schema,
        "headers": list(template_headers),
        "output_path": str(actual_output) if new_count else "",
        "report_path": str(actual_report),
        "all_count": all_count,
        "existing_count": existing_count,
        "new_count": new_count,
        "upload_count": new_count,
        "existing_futbin_ids": existing_source_ids,
        "new_futbin_ids": new_source_ids,
        "no_upload": not new_count,
        "errors": [],
        "warnings": [],
        "row_reports": [item.to_dict() for item in row_reports],
    }
    _write_json(actual_report, payload)
    if not new_count:
        payload["status"] = status
        _write_json(actual_report, payload)
        return NewPlayersResult(
            status=status,
            code=code,
            input_path=str(source),
            output_path="",
            report_path=str(actual_report),
            source_sheet=match.title,
            schema=match.schema,
            all_count=all_count,
            existing_count=existing_count,
            new_count=0,
            upload_count=0,
            existing_futbin_ids=tuple(existing_source_ids),
            new_futbin_ids=(),
            no_upload=True,
            row_reports=row_reports,
        )
    try:
        _write_xlsx(actual_output, new_rows)
    except Exception as exc:
        failed_payload = dict(payload)
        failed_payload["status"] = "failed"
        failed_payload["errors"] = [f"OUTPUT_WRITE_FAILED: {exc}"]
        try:
            _write_json(actual_report, failed_payload)
        finally:
            raise TransformationError(
                "OUTPUT_WRITE_FAILED",
                f"新增球员文件写入失败，未完成转换：{exc}；详见 {actual_report}",
                report=failed_payload,
                report_path=actual_report,
            ) from exc
    result = NewPlayersResult(
        status="ready",
        code="Ready",
        input_path=str(source),
        output_path=str(actual_output),
        report_path=str(actual_report),
        source_sheet=match.title,
        schema=match.schema,
        all_count=all_count,
        existing_count=existing_count,
        new_count=new_count,
        upload_count=new_count,
        existing_futbin_ids=tuple(existing_source_ids),
        new_futbin_ids=tuple(new_source_ids),
        no_upload=False,
        row_reports=row_reports,
    )
    payload.update(result.to_dict())
    _write_json(actual_report, payload)
    return result


def exclude_existing_players(*args: Any, **kwargs: Any) -> NewPlayersResult:
    """Alias matching the wording used by import adapters."""

    return filter_existing_players(*args, **kwargs)


def filter_new_players(*args: Any, **kwargs: Any) -> NewPlayersResult:
    """Alias for callers that describe the result as a new-player batch."""

    return filter_existing_players(*args, **kwargs)


def transform_workbook(*args: Any, **kwargs: Any) -> ConversionResult:
    """Compatibility alias for callers that use ``transform_workbook``."""

    return convert_workbook(*args, **kwargs)


def convert_file(*args: Any, **kwargs: Any) -> ConversionResult:
    """Compatibility alias for GUI/core adapters."""

    return convert_workbook(*args, **kwargs)


class PlayerWorkbookTransformer:
    """Small stateful wrapper suitable for a GUI adapter."""

    def __init__(self, template_path: str | os.PathLike[str] | None = None) -> None:
        self.template_path = None if template_path is None else Path(template_path)

    def transform(
        self,
        input_path: str | os.PathLike[str],
        output_path: str | os.PathLike[str] | None = None,
        *,
        report_path: str | os.PathLike[str] | None = None,
    ) -> ConversionResult:
        return convert_workbook(
            input_path,
            output_path,
            template_path=self.template_path,
            report_path=report_path,
        )


Transformer = PlayerWorkbookTransformer


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口，便于下次直接重复执行本地转换。"""

    parser = argparse.ArgumentParser(description="FC27 离线球员 Excel 转换")
    parser.add_argument("input", help="输入 .xlsx 或 .xlsm")
    parser.add_argument("--output", help="输出 .xlsx；已存在时自动选择新文件名")
    parser.add_argument("--template", default=None, help="可选：外部权威模板路径；不传则用内置 25 列表头")
    parser.add_argument("--report", help="逐行校验报告 JSON 路径")
    args = parser.parse_args(argv)
    try:
        result = convert_workbook(
            args.input,
            args.output,
            template_path=args.template,
            report_path=args.report,
        )
    except TransformationError as exc:
        print(json.dumps({"status": "blocked", "code": exc.code, "message": str(exc), "report_path": exc.report_path}, ensure_ascii=False))
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0


__all__ = [
    "DEFAULT_TEMPLATE_PATH",
    "EN_HEADERS",
    "RAW_HEADERS",
    "RAW_TO_EN",
    "REMOVED_RAW_HEADERS",
    "TransformationError",
    "TransformError",
    "WorkbookTransformError",
    "Issue",
    "RowReport",
    "ConversionResult",
    "NewPlayersResult",
    "validate_template",
    "convert_workbook",
    "filter_existing_players",
    "exclude_existing_players",
    "filter_new_players",
    "transform_workbook",
    "convert_file",
    "PlayerWorkbookTransformer",
    "Transformer",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())

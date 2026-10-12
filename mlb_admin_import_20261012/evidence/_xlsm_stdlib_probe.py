# -*- coding: utf-8 -*-
"""验证：纯 stdlib（zipfile+xml）解析 xlsm 能否得到与 openpyxl 相同的结果。

用于给 CI 提供一个零第三方依赖的等效解析路径。
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

HEADERS = ["游戏", "服务区", "产品分类", "产品名称", "图标地址", "单价", "折扣",
           "最小购买量", "收货价格(¥)", "是否推荐", "是否热门", "是否启用",
           "产品摘要", "产品描述", "扩展属性", "分类ID（勿改）"]

_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n  # 1-based


def _shared_strings(z: zipfile.ZipFile):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("m:si", NS):
        out.append("".join(t.text or "" for t in si.iter(
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    return out


def read_rows_stdlib(path):
    """纯标准库读出「第 4 列有值」的行（与 read_xlsm_rows 语义一致）。"""
    p = Path(path)
    with zipfile.ZipFile(p) as z:
        shared = _shared_strings(z)

        # 找到哪个 sheet 的表头 == HEADERS
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid2target = {rel.get("Id"): rel.get("Target")
                      for rel in rels.findall("{http://schemas.openxmlformats.org/"
                                              "package/2006/relationships}Relationship")}

        target_sheet = None
        sheets_el = wb.find("m:sheets", NS)
        if sheets_el is None:
            raise SystemExit("[X] workbook.xml 缺 sheets 节点")
        for sh in sheets_el:
            rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/"
                         "relationships}id")
            tgt = rid2target.get(rid, "")
            if tgt.startswith("/"):
                tgt = tgt.lstrip("/")
            elif not tgt.startswith("xl/"):
                tgt = "xl/" + tgt
            if tgt not in z.namelist():
                continue

            xml = ET.fromstring(z.read(tgt))
            cells = {}
            for c in xml.iter("{http://schemas.openxmlformats.org/spreadsheetml/"
                              "2006/main}c"):
                ref = c.get("r") or ""
                m = _CELL_RE.match(ref)
                if not m:
                    continue
                col, row = _col_index(m.group(1)), int(m.group(2))
                t = c.get("t")
                v = c.find("m:v", NS)
                if t == "inlineStr":
                    isn = c.find("m:is", NS)
                    val = "".join(x.text or "" for x in isn.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")) if isn is not None else ""
                elif t == "s" and v is not None:
                    val = shared[int(v.text)]
                else:
                    val = v.text if v is not None else None
                cells[(row, col)] = val

            row1 = [str(cells.get((1, i + 1)) or "").strip() for i in range(len(HEADERS))]
            if row1 == HEADERS:
                target_sheet = (tgt, cells)
                break

        if target_sheet is None:
            raise SystemExit("[X] 找不到 16 列表头匹配的工作表")

        _, cells = target_sheet
        max_row = max((r for r, _ in cells), default=1)
        rows = []
        for r in range(2, max_row + 1):
            name = cells.get((r, 4))
            if not name:
                continue
            rows.append({
                "row": r,
                "product_name": str(name).strip(),
                "price": cells.get((r, 6)),
                "enabled": cells.get((r, 12)),
                "hash": str(cells.get((r, 15)) or ""),
                "category_id": cells.get((r, 16)),
            })
        return rows


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else \
        r"E:\WorkBuddy\大超服务器\docs\planning\mlb-admin-api-feasibility-20261012\out_20261012.xlsm"
    rows = read_rows_stdlib(path)
    print("stdlib 解析行数 =", len(rows))
    for r in rows[:3]:
        print("  ", r)
    print("全部 category_id = 8233 ?",
          all(str(r["category_id"]) == "8233" for r in rows))

    # 与 openpyxl 对照
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, keep_vba=True, data_only=True)
        tgt = None
        for ws in wb.worksheets:
            row1 = [str(ws.cell(row=1, column=i + 1).value or "").strip()
                    for i in range(len(HEADERS))]
            if row1 == HEADERS:
                tgt = ws
                break
        rows2 = []
        for rr in range(2, tgt.max_row + 1):
            nm = tgt.cell(row=rr, column=4).value
            if not nm:
                continue
            rows2.append({
                "row": rr, "product_name": str(nm).strip(),
                "price": tgt.cell(row=rr, column=6).value,
                "enabled": tgt.cell(row=rr, column=12).value,
                "hash": str(tgt.cell(row=rr, column=15).value or ""),
                "category_id": tgt.cell(row=rr, column=16).value,
            })
        print("openpyxl 解析行数 =", len(rows2))
        same = len(rows) == len(rows2) and all(
            a["product_name"] == b["product_name"]
            and str(a["category_id"]) == str(b["category_id"])
            for a, b in zip(rows, rows2))
        print("两者一致 ?", same)
        if not same:
            for a, b in zip(rows, rows2):
                if a != b:
                    print("  差异:", a, "|", b)
    except ImportError:
        print("（本机无 openpyxl，跳过对照）")

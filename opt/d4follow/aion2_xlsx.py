# -*- coding: utf-8 -*-
"""把 AION2 金币价导出成 Excel（.xlsx）。

为什么要走「Excel + 下载链接」而不是直接把大表格塞进钉钉消息：
  ① 钉钉自定义机器人**不支持发附件**（只支持 text / markdown / actionCard 等），
     没有「发送 xlsx」这种消息类型；
  ② 34 个小服 × 6 列塞进markdown，手机端要横向滚动、消息极长很难读
     （用户明确反馈过「不要发一大串话」）。
⇒ 折中：钉钉只发**一行极简摘要 + 下载链接**，明细在 Excel 里看/排序/筛选。

依赖：openpyxl（已装进 /opt/d4follow/venv）。
"""
from __future__ import annotations

import os
import time

OUT_DIR = "/var/www/dashboard/aion2-gold"
COLS = [
    ("大区", 14),
    ("服务区", 22),
    ("基准价", 11),
    ("我方价", 11),
    ("毛利率", 10),
    ("较上轮", 16),
    ("G2G", 10),
    ("ELD", 10),
    ("IGGM", 10),
    ("基准来源", 14),
]


def _short(name: str) -> str:
    s = str(name or "")
    if " · " in s:
        s = s.split(" · ", 1)[1]
    return s.replace(" - ", "-").strip()


def _src_note(r) -> str:
    if r.get("兜底"):
        return "%s 兜底" % r["兜底"]
    v, src = r.get("基准"), r.get("基准来源") or ""
    for tag in ("G2G", "ELD", "IGGM"):
        if tag in src:
            return tag
    if v is not None:
        return "其他"
    return "—"


def build_xlsx(cur_rows, prev_rows, round_no, out_path=None, warns=None):
    """生成 xlsx。返回 (文件路径, 摘要dict)。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    prev = {r["key"]: r for r in (prev_rows or [])}
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    path = out_path or os.path.join(OUT_DIR, "AION2金币价-%s.xlsx" % stamp)

    wb = Workbook()
    ws = wb.active
    ws.title = "金币价明细"

    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")

    # ---- 标题行
    ws.cell(1, 1, "AION2 金币价全量小服明细")
    ws.cell(1, 1).font = Font(bold=True, size=14, color="1F3864")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLS))
    ws.cell(2, 1, "基准 = min(G2G, ELD)，IGGM 更低则取 IGGM，两站皆无则同大区均价兜底；"
                  "单价 $/M；毛利率 = (我方 − 基准) / 我方")
    ws.cell(2, 1).font = Font(size=9, color="808080")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(COLS))
    ws.cell(3, 1, "第 %d 轮 · 生成于 %s"
            % (round_no, time.strftime("%Y-%m-%d %H:%M:%S")))
    ws.cell(3, 1).font = Font(size=9, color="808080")
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(COLS))

    # ---- 表头
    HR = 5
    for i, (name, w) in enumerate(COLS, start=1):
        c = ws.cell(HR, i, name)
        c.fill = head_fill
        c.font = head_font
        c.alignment = center
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(HR + 1, 1)

    # ---- 数据行（按大区分组，组内按名称排序——与推送顺序一致）
    groups = {}
    for r in cur_rows:
        groups.setdefault(r.get("大区") or "-", []).append(r)
    order = sorted(groups, key=lambda k: (-len(groups[k]), k))

    band = PatternFill("solid", fgColor="F2F5FA")   # 隔行浅底
    sub_fill = PatternFill("solid", fgColor="DDE5F2")
    red = Font(color="C00000")
    green = Font(color="1E7B34")
    row_no = HR
    for reg in order:
        rows = sorted(groups[reg],
                      key=lambda z: str(z.get("名称") or z.get("key") or ""))
        # 分组小计行
        row_no += 1
        bases = [r["基准"] for r in rows if r.get("基准") not in (None, 0)]
        ours = [r["我方价"] for r in rows if r.get("我方价") not in (None, 0)]
        ab = sum(bases) / len(bases) if bases else None
        ao = sum(ours) / len(ours) if ours else None
        mg = ((ao - ab) / ao) if (ab and ao) else None
        vals = [reg + " 小计", "%d 个小服" % len(rows), ab, ao, mg, None,
                None, None, None, "有基准 %d/%d" % (len(bases), len(rows))]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row_no, i, v)
            c.fill = sub_fill
            c.font = Font(bold=True, size=10)
            c.border = border
        for i in (3, 4):
            ws.cell(row_no, i).number_format = "0.0000"
        if mg is not None:
            ws.cell(row_no, 5).number_format = "0.0%"

        for r in rows:
            row_no += 1
            p = prev.get(r["key"]) or {}
            b, o = r.get("基准"), r.get("我方价")
            m = ((o - b) / o) if (b and o) else None
            chg = []
            for lbl, cur_v, prev_v in (("基准", b, p.get("基准")),
                                       ("我方", o, p.get("我方价"))):
                if cur_v is not None and prev_v is not None:
                    d = cur_v - prev_v
                    if abs(d) > 0.0005:
                        chg.append("%s %s%.4f" % (lbl, "↑" if d > 0 else "↓", abs(d)))
            vals = [reg, _short(r.get("名称") or r.get("key")), b, o, m,
                    "；".join(chg) if chg else "持平",
                    r.get("G2G"), r.get("ELD"), r.get("IGGM"), _src_note(r)]
            for i, v in enumerate(vals, start=1):
                c = ws.cell(row_no, i, v)
                c.border = border
                if (row_no - HR) % 2 == 0:
                    c.fill = band
            for i in (3, 4, 7, 8, 9):
                ws.cell(row_no, i).number_format = "0.0000"
            if m is not None:
                ws.cell(row_no, 5).number_format = "0.0%"
                # 负毛利标红（我方售价低于竞品基准 → 值得盯）
                ws.cell(row_no, 5).font = red if m < 0 else green
            if chg:
                ws.cell(row_no, 6).font = red if chg[0].split()[1][0] == "↓" else green

    # ---- 汇总页
    ws2 = wb.create_sheet("全局概览")
    ws2.column_dimensions["A"].width = 22
    ws2.column_dimensions["B"].width = 14
    ws2.column_dimensions["C"].width = 14
    ws2.column_dimensions["D"].width = 12
    ws2.cell(1, 1, "大区")
    ws2.cell(1, 2, "基准均价")
    ws2.cell(1, 3, "我方均价")
    ws2.cell(1, 4, "毛利率")
    for i in range(1, 5):
        c = ws2.cell(1, i)
        c.fill = head_fill
        c.font = head_font
        c.alignment = center
        c.border = border
    n = 1
    for reg in order:
        rows = groups[reg]
        n += 1
        bases = [r["基准"] for r in rows if r.get("基准") not in (None, 0)]
        ours = [r["我方价"] for r in rows if r.get("我方价") not in (None, 0)]
        ab = sum(bases) / len(bases) if bases else None
        ao = sum(ours) / len(ours) if ours else None
        mg = ((ao - ab) / ao) if (ab and ao) else None
        ws2.cell(n, 1, "%s（%d 区）" % (reg, len(rows)))
        ws2.cell(n, 2, ab).number_format = "0.0000"
        ws2.cell(n, 3, ao).number_format = "0.0000"
        if mg is not None:
            ws2.cell(n, 4, mg).number_format = "0.0%"
            ws2.cell(n, 4).font = red if mg < 0 else green
        for i in range(1, 5):
            ws2.cell(n, i).border = border

    # ---- 告警页
    if warns:
        ws3 = wb.create_sheet("采集告警")
        ws3.column_dimensions["A"].width = 8
        ws3.column_dimensions["B"].width = 110
        ws3.cell(1, 1, "#")
        ws3.cell(1, 2, "告警内容")
        for i in (1, 2):
            ws3.cell(1, i).fill = PatternFill("solid", fgColor="C00000")
            ws3.cell(1, i).font = Font(color="FFFFFF", bold=True)
        for idx, w in enumerate(warns, start=1):
            ws3.cell(idx + 1, 1, idx)
            ws3.cell(idx + 1, 2, w)

    wb.save(path)

    all_b = [r["基准"] for r in cur_rows if r.get("基准") not in (None, 0)]
    all_o = [r["我方价"] for r in cur_rows if r.get("我方价") not in (None, 0)]
    summary = {
        "path": path,
        "name": os.path.basename(path),
        "servers": len(cur_rows),
        "regions": len(order),
        "avg_base": sum(all_b) / len(all_b) if all_b else None,
        "avg_our": sum(all_o) / len(all_o) if all_o else None,
        "warns": len(warns or []),
    }
    return path, summary


def render_brief(summary, download_url, total_rounds=4, round_no=0):
    """钉钉消息正文：**一行摘要 + 一个链接**，不贴大表格。"""
    mg = None
    if summary.get("avg_base") and summary.get("avg_our"):
        mg = (summary["avg_our"] - summary["avg_base"]) / summary["avg_our"]
    lines = [
        "## AION2 金币价 · 第 %d 轮" % round_no,
        "",
        "%d 个小服 / %d 大区 · 基准均价 %s · 我方均价 %s · 毛利率 %s%s" % (
            summary["servers"], summary["regions"],
            ("%.4f" % summary["avg_base"]) if summary.get("avg_base") else "—",
            ("%.4f" % summary["avg_our"]) if summary.get("avg_our") else "—",
            ("%.1f%%" % (mg * 100)) if mg is not None else "—",
            " · ⚠%d 条告警" % summary["warns"] if summary.get("warns") else ""),
        "",
        "[📊 下载 Excel 明细（%d 个小服全量）](%s)" % (summary["servers"], download_url),
        "",
        "> 每 15 分钟采集，每 %d 轮（约 1 小时）更新一次链接" % total_rounds,
    ]
    return "\n".join(lines)

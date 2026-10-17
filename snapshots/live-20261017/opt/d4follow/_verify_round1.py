# -*- coding: utf-8 -*-
"""首轮 g2g_cheapold 生效核对：模式行 / 四类基准来源统计 / 工单明细 / 执行结果。"""
import glob
import io
import json
import os
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:8900"
LOG = "/opt/d4follow/logs/task_ba33f41c1be0.log"

lines = io.open(LOG, encoding="utf-8", errors="replace").read().splitlines()

print("=" * 20, "1) 模式/口径 日志行", "=" * 20)
for i, ln in enumerate(lines):
    if ("定价模式" in ln or "模式" in ln and "金币" in ln) and "跟价" in ln:
        print(i + 1, ln)
for i, ln in enumerate(lines):
    if "金币/定价" in ln:
        print(i + 1, ln)

print()
print("=" * 20, "2) [金币] 逐行动作统计", "=" * 20)
gold = [ln for ln in lines if ln.strip().startswith("[") and "[金币]" in ln and "·" in ln
        and "-" in ln and "→" in ln]
# 只取 AION2 的（排除 MSCW 的 IGGM真价 行）
aion = [ln for ln in gold if "IGGM真价" not in ln]
print("AION2 定价行数：", len(aion))

src = Counter()
act = Counter()
for ln in aion:
    tail = ln.split("｜", 1)[-1].strip()
    act[tail.split()[0]] += 1
    seg = ln.split("（天族）")[-1].split("（魔族）")[-1]
    for key in ("无货兜底", "G2G·cheapold→成本价", "G2G·cheapold", "G2G·推荐前二"):
        if key in seg:
            src[key] += 1
            break
    else:
        src["?" + seg[:40]] += 1

print("基准来源：", dict(src))
print("动作：", dict(act))

print()
print("--- 非 hold 的行（会出单的）---")
for ln in aion:
    if "｜ hold" not in ln:
        print(ln)

print()
print("=" * 20, "3) 工单 JSON", "=" * 20)
for p in sorted(glob.glob("/opt/d4follow/output/金币工单_AION2_20261009_1747*.json")):
    d = json.load(io.open(p, encoding="utf-8"))
    print("文件：", p)
    if isinstance(d, dict):
        print("顶层键：", list(d.keys()))
        rows = d.get("items") or d.get("明细") or d.get("rows") or []
    else:
        rows = d
    print("条数：", len(rows))
    for r in rows[:60]:
        print("  ", json.dumps(r, ensure_ascii=False)[:220])

print()
print("=" * 20, "4) 执行器结果", "=" * 20)
print(io.open("/opt/d4follow/data/srv_exec.json", encoding="utf-8").read())

print("=" * 20, "5) /api/gold 里 AION2 前 5 条", "=" * 20)
with urllib.request.urlopen(BASE + "/api/gold", timeout=30) as r:
    g = json.loads(r.read().decode("utf-8"))
items = g.get("items") or g.get("data") or []
a2 = [x for x in items if str(x.get("key", x.get("id", ""))).startswith("AION2")]
print("AION2 条数：", len(a2))
for x in a2[:5]:
    print(json.dumps(x, ensure_ascii=False, indent=1))

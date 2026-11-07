# -*- coding: utf-8 -*-
"""对比台账里「现b2c」vs「目标b2c」，确认换数据源是否能改变展示价。"""
import glob
import json

f = [x for x in sorted(glob.glob("/opt/d4follow/output/*台账_*.json")) if "魔兽" in x][-1]
d = json.load(open(f, encoding="utf-8"))
plan = d["plan"]
print("台账:", f)
print("ts:", d.get("ts"), "| 行数:", len(plan))
print()
print("%-26s %-6s %-9s %-4s %10s %10s %9s %8s" % (
    "后台名", "区", "类型", "阵营", "现b2c", "目标b2c", "变动%", "动作"))
diff = 0
for r in plan:
    a, b = r.get("现b2c"), r.get("目标b2c")
    if a is not None and b is not None and abs(a - b) > 1e-9:
        diff += 1
    print("%-26s %-6s %-9s %-4s %10s %10s %9s %8s" % (
        str(r.get("后台名"))[:24], r.get("区"), r.get("类型"), r.get("阵营"),
        a, b, r.get("变动pct"), r.get("动作")))
print()
print("现b2c 与 目标b2c 不同的行数 =", diff, "/", len(plan))
vals = sorted({r.get("目标b2c") for r in plan if r.get("目标b2c")})
print("目标b2c 取值范围:", vals[:3], "...", vals[-3:])
print("均价元每金 样例:", [(r.get("后台名"), r.get("均价元每金")) for r in plan[:4]])

# -*- coding: utf-8 -*-
"""看台账 plan 里的字段，定位「目标价 / 写入成本 / 后台行ID」。"""
import glob
import json

f = [x for x in sorted(glob.glob("/opt/d4follow/output/*台账_*.json")) if "魔兽" in x][-1]
d = json.load(open(f, encoding="utf-8"))
print("文件:", f)
print("ts:", d.get("ts"), "| gid:", d.get("gid"), "| 汇率:", d.get("汇率"))
print("IGGM采集时间:", d.get("IGGM采集时间"), "| 锚定:", d.get("IGGM锚定"))
plan = d.get("plan")
print("plan 类型:", type(plan).__name__, "| 行数:", len(plan) if hasattr(plan, "__len__") else "?")

if isinstance(plan, dict):
    print("plan 键:", list(plan)[:10])
    for k, v in list(plan.items())[:1]:
        print("  样例[%s]:" % k, json.dumps(v, ensure_ascii=False)[:400])
elif isinstance(plan, list) and plan:
    print("\n第一行全部字段:")
    for k, v in plan[0].items():
        print("  %-24s %s" % (k, str(v)[:70]))
    print("\nUS/Normal 相关行:")
    for r in plan:
        s = json.dumps(r, ensure_ascii=False)
        if ("美服" in s and "Normal" in s) or ("US" in s and "NORMAL" in s.upper()):
            print("  ", json.dumps(r, ensure_ascii=False)[:300])

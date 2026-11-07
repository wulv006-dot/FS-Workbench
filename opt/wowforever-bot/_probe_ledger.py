# -*- coding: utf-8 -*-
"""在 183 上看魔兽金币台账结构，找出「目标价」字段。"""
import glob
import json

files = sorted(glob.glob("/opt/d4follow/output/*\u53f0\u8d26_*.json"))
wow = [f for f in files if "\u9b54\u517d" in f]
print("台账文件数:", len(files), "| 魔兽相关:", len(wow))
f = wow[-1]
print("最新魔兽台账:", f)

d = json.load(open(f, encoding="utf-8"))
print("顶层类型:", type(d).__name__)
if isinstance(d, dict):
    print("顶层键:", list(d)[:20])
    rows = None
    for k in ("明细", "rows", "行", "data", "items"):
        if isinstance(d.get(k), list):
            rows = d[k]
            print("明细键 =", k)
            break
else:
    rows = d
    print("顶层就是列表")

print("行数:", len(rows or []))
if rows:
    r0 = rows[0]
    print("\n第一行全部字段:")
    for k, v in r0.items():
        s = str(v)
        print("  %-28s %s" % (k, s[:70]))

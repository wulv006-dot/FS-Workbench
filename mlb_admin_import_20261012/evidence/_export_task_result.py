# -*- coding: utf-8 -*-
"""服务器侧只读：导出最新批次任务结果，落盘为可直接喂给 mlb_write_cards.py 的 --result。

用法：/opt/python39/bin/python3 /tmp/export_task_result.py <输出路径>
"""
import datetime
import json
import sqlite3
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "/opt/mlb-admin-write/evidence/_result.json"
DB = "/opt/mlb-online/data/mlb.db"

con = sqlite3.connect(DB)
cols = [c[1] for c in con.execute("pragma table_info(tasks)")]
rows = list(con.execute("select * from tasks order by created_at desc limit 5"))

picked = None
for r in rows:
    d = dict(zip(cols, r))
    res = d.get("result")
    if not res:
        continue
    try:
        j = json.loads(res)
    except Exception:
        continue
    if j.get("cards"):
        picked = (d, j)
        break

if not picked:
    print("[X] 没找到含 cards 的任务结果")
    sys.exit(1)

d, j = picked
ts = d.get("created_at")
print("=" * 62)
print("task id    =", d.get("id"))
print("created    =", datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?")
print("submitter  =", d.get("submitter"), "| kind =", d.get("kind"))
print("title      =", d.get("title"))
print("file_name  =", j.get("file_name"))
print("cards      =", len(j.get("cards", [])))
inc = [c for c in j.get("cards", []) if c.get("include")]
print("include=1  =", len(inc))
for c in j.get("cards", []):
    print("   %-56s include=%-5s price=%-7s hash=%s" % (
        c.get("product_name"), c.get("include"), c.get("sale_price"),
        (c.get("hash") or "")[:12]))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(j, f, ensure_ascii=False, indent=2)
print("\n已写出:", OUT)

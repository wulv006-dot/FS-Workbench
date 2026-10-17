# -*- coding: utf-8 -*-
"""核对：41 个「无货兜底」区当前前端价是否已 = $19.9（否则应为 follow_up 而非 hold）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8900"
with urllib.request.urlopen(BASE + "/api/gold", timeout=30) as r:
    g = json.loads(r.read().decode("utf-8"))
items = g.get("items") or g.get("data") or []
a2 = [x for x in items if str(x.get("key", "")).startswith("AION2")]
print("AION2 总数：", len(a2))

park = [x for x in a2 if x.get("src_base") == "无货兜底"]
print("无货兜底区：", len(park))
print()
bad = []
for x in park:
    our = x.get("our_per_m")
    if our is None or abs(float(our) - 19.9) > 0.02:
        bad.append((x["key"], our, x.get("action"), x.get("cost_old"),
                    x.get("cost_target"), x.get("price_mode")))
print("前端价 != 19.9 的「无货兜底」区：", len(bad))
for b in bad:
    print("   ", b)

print()
print("--- 各类 src_base 计数 ---")
from collections import Counter
print(Counter(x.get("src_base") for x in a2))
print("--- 各类 action 计数 ---")
print(Counter(x.get("action") for x in a2))
print("--- price_mode 计数 ---")
print(Counter(x.get("price_mode") for x in a2))

print()
print("--- 41 个无货兜底区清单（key / 前端每M / 目标成本 / 动作）---")
for x in park:
    print("   %-26s our=%-8s tgt_cost=%-10s %s"
          % (x["key"], x.get("our_per_m"), x.get("cost_target"), x.get("action")))

print()
print("--- 抽查：无货兜底区的 reason 文案（3 条）---")
for x in park[:3]:
    print(x["key"], "::", x.get("reason"))

# -*- coding: utf-8 -*-
"""探查：当前采集周期、最近采集时间、以及待采集到期情况。"""
import io
import json
import urllib.request

BASE = "http://127.0.0.1:8900"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


st = get("/api/state")
print("state keys:", sorted(st.keys()))
print()
print("=== /api/state 里的关键块 ===")
for k in ("schedule", "周期", "switches", "switches_state", "gold", "tasks", "follow"):
    if k in st:
        print("---", k, "---")
        print(json.dumps(st[k], ensure_ascii=False, indent=1)[:3000])
        print()

print("=== config 运行.采集周期小时 ===")
cfg = json.load(io.open("/opt/d4follow/config.json", encoding="utf-8"))
print(json.dumps(cfg.get("运行", {}).get("采集周期小时", {}),
                 ensure_ascii=False, indent=1))

print()
print("=== collect_schedule.json ===")
print(json.dumps(json.load(io.open("/opt/d4follow/data/collect_schedule.json",
                                   encoding="utf-8")),
                 ensure_ascii=False, indent=1))
print()
print("=== 金币定价策略（当前）===")
g = cfg.get("金币", {})
print(json.dumps(g.get("定价策略", {}), ensure_ascii=False, indent=1)[:3000])

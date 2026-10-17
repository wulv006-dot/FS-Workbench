#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MSCW 让价持平（0.1 -> 0.0）+ 采集周期 0.25h 上线后验证。

做两件事（均只读 DB + 触发一次与页面「立即采集」完全同路径的任务）：
  1) 打印 运行.采集周期小时.MSCW 与 schedule 到期判定（读 collect_schedule.json）
  2) 触发一轮真实采集，轮询 iggm_follow.db:gold_price，看 MSCW 新一轮的目标价/我方价

不改任何文件；触发的采集任务由 app 自身完成（与服务 timer 同一条代码路径）。
"""
import json
import os
import sqlite3
import time
import urllib.request

ROOT = "/opt/d4follow"
DB = "file:%s/data/iggm_follow.db?mode=ro" % ROOT


def q(sql):
    c = sqlite3.connect(DB, uri=True)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql)]
    finally:
        c.close()


def latest_mscw():
    r = q("select ts, action, iggm_raw, iggm_per_m, our_per_m, cost_old, cost_target, "
          "price_mode, ratio, reason from gold_price where key='GOLD_MSCW_GLOBAL' "
          "order by rowid desc limit 1")
    return r[0] if r else None


# ---- 1) 调度侧：周期与到期判定 ----
cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
cyc = ((cfg.get("运行") or {}).get("采集周期小时") or {}).get("MapleStory Classic World")
print("[调度] 运行.采集周期小时.MSCW = %s h（%d 分钟）" % (cyc, round(float(cyc) * 60)))
sched = json.load(open(os.path.join(ROOT, "data", "collect_schedule.json"), encoding="utf-8"))
print("[调度] MSCW 上次采完 = %s" % sched.get("MapleStory Classic World"))
print("[调度] 心跳 d4follow-collect.timer = 15 分钟（systemd）")

# ---- 2) 定价侧：触发一轮真实采集 ----
b = latest_mscw()
print("[触发前] MSCW 最新行 ts=%s action=%s IGGM真价=%s 我方=%s"
      % (b["ts"], b["action"], b["iggm_per_m"], b["our_per_m"]))

req = urllib.request.Request(
    "http://127.0.0.1:8900/api/task",
    data=json.dumps({"kind": "collect"}).encode(),
    headers={"Content-Type": "application/json"})
try:
    print("[触发]", urllib.request.urlopen(req, timeout=30).read().decode())
except Exception as e:
    print("[触发] ERR %s" % e)

deadline = time.time() + 480
new = None
while time.time() < deadline:
    time.sleep(15)
    r = latest_mscw()
    if r and r["ts"] != b["ts"]:
        new = r
        break

if not new:
    print("[结果] 超时 8 分钟未出现新一轮 MSCW 记录（任务可能仍在跑，稍后再看）")
else:
    print("[结果] 新一轮 ts=%s" % new["ts"])
    print("       定价模式=%s  action=%s  ratio=%s" % (new["price_mode"], new["action"], new["ratio"]))
    print("       IGGM 真价 $%s/K  ->  我方 $%s/K" % (new["iggm_per_m"], new["our_per_m"]))
    print("       reason: %s" % new["reason"])

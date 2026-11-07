# -*- coding: utf-8 -*-
"""抽奖概率统计验证：跑 N 次抽样，对比配置概率。"""
import json
import sys
from collections import Counter

sys.path.insert(0, "/opt/wowforever-bot")
from modules.giveaway import weighted_pick  # noqa: E402

cfg = json.load(open("/opt/wowforever-bot/config.json", encoding="utf-8"))
prizes = cfg["features"]["giveaway"]["prizes"]

N = 100000
cnt = Counter()
for _ in range(N):
    p = weighted_pick(prizes)
    cnt[p["key"]] += 1

print("抽 %d 次\n" % N)
print("%-10s %8s %10s %10s" % ("prize", "config", "actual", "diff"))
bad = 0
for p in prizes:
    want = float(p["chance"])
    got = cnt[p["key"]] * 100.0 / N
    diff = got - want
    flag = "" if abs(diff) < max(0.5, want * 0.06) else "  <-- 偏差过大"
    if flag:
        bad += 1
    print("%-10s %7.1f%% %9.2f%% %+9.2f%s" % (p["key"], want, got, diff, flag))
print("\n总抽样 =", sum(cnt.values()), "| 偏差异常项 =", bad)
print("DIST TEST " + ("OK" if bad == 0 else "FAILED"))

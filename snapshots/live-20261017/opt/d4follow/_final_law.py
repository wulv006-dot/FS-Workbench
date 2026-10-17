# -*- coding: utf-8 -*-
"""终局判定：前台售价 = b2c × disc/100  （经验定律）
   还是 前台售价 = b2c × 1.0526        （代码库沿用约定）？
   用已知 b2c 的 D4/AION2 行做算术核对，只读。
"""
import json
import sys

sys.path.insert(0, "/opt/d4follow")
import core_gold as CG  # noqa: E402

cfg = json.load(open("/opt/d4follow/config.json", encoding="utf-8"))
TIER = int(CG.tier_of(cfg))
print("金币.对标档位 =", TIER)

# (名称, 游戏, aid, 后台 b2c, 后台采购成本)
CASES = [
    ("D4 永恒专家", "暗黑破坏神4", 15403, 0.006762, 0.035976),
    ("D4 永恒普通", "暗黑破坏神4", 11916, 0.000253, 0.001346),
    ("D4 赛季专家", "暗黑破坏神4", 15945, 0.000160, 0.000851),
    ("D4 赛季普通", "暗黑破坏神4", 15943, 0.000004, 0.000023),
    ("MSCW Windia", "MapleStory Classic World", 21627, 0.449100, 2.090561),
    ("MSCW 雪吉拉", "MapleStory Classic World", 21619, 1.288937, 6.000000),
]
print()
print("%-14s %-14s %-10s %-14s | %-13s %-13s %-13s %-10s" % (
    "服务区", "对标档位价", "disc", "b2c", "实测/期望A", "实测/期望B", "实测单价", "判定"))
for nm, gm, aid, b2c, cost in CASES:
    try:
        t = CG.fetch_front_gold(cfg, aid, game=gm)
    except Exception as e:  # noqa: BLE001
        print("%-14s 抓取失败 %r" % (nm, e))
        continue
    if not t:
        print("%-14s 空" % nm)
        continue
    n, per = CG.per_m(t, TIER)          # 引擎口径：取最接近对标档位的档
    disc = None
    for x in t:
        if int(x.get("num") or 0) == n:
            disc = x.get("discount")
    A = b2c * (float(disc) / 100.0) if disc else None       # 定律 A
    B = b2c * 1.052631579                                    # 约定 B
    ratioA = (per / A) if A else None
    ratioB = (per / B) if B else None
    verdict = ""
    if ratioA is not None and abs(ratioA - 1) < 0.03:
        verdict = "✅A(disc/100)"
    elif ratioB is not None and abs(ratioB - 1) < 0.03:
        verdict = "✅B(1/0.95)"
    else:
        verdict = "❓"
    print("%-14s 档%-10s %-10s %-14s | %-13s %-13s %-13s %-10s" % (
        nm, "%s%s" % (n, (t[0].get("unit") if t else "")), disc, b2c,
        ("%.3f" % ratioA) if ratioA else "-",
        ("%.3f" % ratioB) if ratioB else "-",
        "%.9f" % per, verdict))

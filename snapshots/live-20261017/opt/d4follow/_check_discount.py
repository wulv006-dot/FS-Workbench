# -*- coding: utf-8 -*-
"""验证前台 `discount` 字段 == 前台折扣率（决定 前台系数）。
   D4 已独立实测前台系数 = 1.0526；若其 discount = 105 ⇒ 理论成立。
"""
import json
import sys

sys.path.insert(0, "/opt/d4follow")
import core_gold as CG  # noqa: E402

cfg = json.load(open("/opt/d4follow/config.json", encoding="utf-8"))

CASES = [
    ("D4 赛季普通", "暗黑破坏神4", 15943),
    ("MSCW Windia", "MapleStory Classic World", 21627),
    ("MSCW 雪吉拉", "MapleStory Classic World", 21619),
    ("MSCW 菇菇寶貝", "MapleStory Classic World", 21621),
    ("AION2 EU Siel", "AION2", 22043),
    ("AION2 EU Nezekan", "AION2", 22044),
]
print("D4   前台系数(front_factor_of) =", CG.front_factor_of(cfg, "暗黑破坏神4"))
print("AION2 前台系数                =", CG.front_factor_of(cfg, "AION2"))
print("MSCW 前台系数                =", CG.front_factor_of(cfg, "MapleStory Classic World"))
print()
print("%-18s %-8s %-14s %-10s %s" % ("服务区", "档位数", "discount取值", "最大档", "$/单位"))
for nm, gm, aid in CASES:
    try:
        t = CG.fetch_front_gold(cfg, aid, game=gm)
    except Exception as e:  # noqa: BLE001
        print("%-18s 抓取失败 %r" % (nm, e))
        continue
    if not t:
        print("%-18s 空" % nm)
        continue
    ds = sorted(set(x.get("discount") for x in t))
    big = max(t, key=lambda x: x.get("num") or 0)
    per = (big.get("price_discount") or 0) / float(big.get("num") or 1)
    print("%-18s %-8s %-14s %-10s %s" % (
        nm, len(t), ds, "%s%s" % (big.get("num"), big.get("unit")), round(per, 9)))

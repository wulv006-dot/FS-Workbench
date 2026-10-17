# -*- coding: utf-8 -*-
"""判定 `discount` 是否参与前台定价（零风险，只读）。
   取 D4 赛季普通（已知除数 5.054）+ MSCW Windia，逐档算 单价 × 除数 = 反推的采购成本；
   若各档基本恒定 ⇒ 除数固定、discount 只是展示标签；
   若与 discount 成比例变化 ⇒ discount 真驱动价格（则除数要乘 discount/100）。
"""
import json
import sys

sys.path.insert(0, "/opt/d4follow")
import core_gold as CG  # noqa: E402

cfg = json.load(open("/opt/d4follow/config.json", encoding="utf-8"))

CASES = [
    ("D4 赛季普通 gid456 行15711", "暗黑破坏神4", 15943, 5.0540),
    ("MSCW Windia 行21754", "MapleStory Classic World", 21627, 4.655),
    ("MSCW 雪吉拉 行21746", "MapleStory Classic World", 21619, 4.655),
]
for nm, gm, aid, div in CASES:
    print("=" * 92)
    print("%s  （假定除数 = %.4f）" % (nm, div))
    try:
        t = CG.fetch_front_gold(cfg, aid, game=gm)
    except Exception as e:  # noqa: BLE001
        print("  抓取失败 %r" % e)
        continue
    if not t:
        print("  空")
        continue
    print("  %8s %6s %6s %14s %14s %14s %10s" % (
        "档位", "disc", "折扣比", "档位总价$", "单价$", "反推采购成本", "×disc/100"))
    rows = []
    for x in t:
        n = int(x.get("num") or 0)
        d = x.get("discount")
        p = x.get("price_discount")
        if not n or p is None:
            continue
        per = p / n
        implied = per * div
        implied_d = implied * (100.0 / float(d)) if d else None
        rows.append((n, d, per, implied, implied_d))
        print("  %8s %6s %6s %14.4f %14.9f %14.6f %10s" % (
            n, d, ("%.2f" % (float(d) / 100.0)) if d else "-", p, per, implied,
            ("%.6f" % implied_d) if implied_d else "-"))
    if rows:
        big = [r for r in rows if r[0] >= 200]
        imp = [r[3] for r in big] or [r[3] for r in rows]
        print("  → 大档 反推采购成本 min=%.6f max=%.6f 波动=%.2f%%" % (
            min(imp), max(imp), (max(imp) / min(imp) - 1) * 100 if min(imp) else 0))
        impd = [r[4] for r in (big or rows) if r[4]]
        if impd:
            print("  → 大档 ×100/disc 后 min=%.6f max=%.6f 波动=%.2f%%" % (
                min(impd), max(impd), (max(impd) / min(impd) - 1) * 100 if min(impd) else 0))

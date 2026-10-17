# -*- coding: utf-8 -*-
"""AION2 切回 g2g_cheapold —— 离线自检（只读 config + 纯函数，不写库、不联网）。

    /opt/d4follow/venv/bin/python _t_g2g.py
"""
import json
import os
import sys

D4 = "/opt/d4follow"
sys.path.insert(0, D4)
os.chdir(D4)
import core_gold as CG          # noqa: E402
import core_dd373_cost as CD    # noqa: E402

P = {"n": 0}
F = {"n": 0}


def ck(name, cond, extra=""):
    if cond:
        P["n"] += 1
        print("  [PASS] %s" % name)
    else:
        F["n"] += 1
        print("  [FAIL] %s   %s" % (name, extra))


cfg = json.load(open("config.json", encoding="utf-8"))

print("== 1. pricing_policy(AION2) ==")
p = CG.pricing_policy(cfg, "AION2")
ck("模式 = g2g_cheapold", bool(p) and p.get("模式") == "g2g_cheapold", p)
ck("下浮比例 = 0.01", abs(float(p["下浮比例"]) - 0.01) < 1e-12, p.get("下浮比例"))
ck("乘数 = 0.99", abs(float(p["乘数"]) - 0.99) < 1e-12, p.get("乘数"))
ck("无货兜底售价_USD每M = 19.9", float(p["无货兜底售价_USD每M"]) == 19.9)
ck("无货最小可买万基纳 = 10000", float(p["无货最小可买万基纳"]) == 10000)
ck("利润率下限 = -0.1", abs(float(p["利润率下限"]) + 0.1) < 1e-12)
ck("成本源 = DD373", p.get("成本源") == "DD373")
ck("口径含「DD373 货源闸」", "DD373 货源闸" in (p.get("口径") or ""))
ck("口径含「成本兜底」（保本闸保留）", "成本兜底" in (p.get("口径") or ""))
ck("g2g_cheapold 无「加价比例」键（乘性时段加价天然不适用）", "加价比例" not in p)

print("== 2. 其它游戏不受影响 ==")
m = CG.pricing_policy(cfg, "MapleStory Classic World")
ck("MSCW 仍是 iggm_undercut", bool(m) and m.get("模式") == "iggm_undercut", m)
ck("MSCW 让价比例 = 0.1", abs(float(m.get("让价比例") or 0.1) - 0.1) < 1e-9)
ck("D4 返回 None（走默认口径）", CG.pricing_policy(cfg, "暗黑破坏神4") is None)

print("== 3. 时段加价已关闭 ==")
tk = (cfg["金币"]["定价策略"].get("时段加价") or {})
ck("时段加价.启用 = False", tk.get("启用") is False, tk.get("启用"))
ck("若误开也不会作用于 g2g_cheapold（无加价比例 ⇒ _time_markup 直接跳过）",
   CG._time_markup({"时段加价": {"启用": True, "适用游戏": ["AION2"],
                                "区间": [{"起": "00:00", "止": "23:59", "加价比例": 0.35}]}},
                   "AION2", {"模式": "g2g_cheapold", "加价比例": None}).get("加价比例") is None)

print("== 4. SKIP_LOWEST_QUOTES = 0（前两条照抓）==")
ck("常量为 0", CD.SKIP_LOWEST_QUOTES == 0, CD.SKIP_LOWEST_QUOTES)
q = [(100.0, 0.03, "散单"), (200.0, 0.04, "散单"), (10000.0, 0.50, "散单")]
ob = CD.orderbook_avg(q)
ck("跳过条数 = 0", ob["跳过条数"] == 0, ob.get("跳过明细"))
ck("原始条数 = 3", ob["原始条数"] == 3)
ck("报价条数 = 3（全部参与）", ob["报价条数"] == 3)
exp = (100 * 0.03 + 200 * 0.04 + 9700 * 0.50) / 10000
ck("加权均价 = 含最低条 0.03 那条", abs(ob["均价"] - exp) < 1e-9,
   "%r vs %r" % (ob["均价"], exp))
ck("够量 = True（可供量 10300 万 ≥ 1 亿）", ob["够量"] is True)

print("== 5. skip_lowest 入参机制保留（日后可重启）==")
ob2 = CD.orderbook_avg(q, skip_lowest=2)
ck("显式传 2 时跳过 2 条", ob2["跳过条数"] == 2, ob2.get("跳过明细"))
ck("显式传 2 时报价条数 = 1", ob2["报价条数"] == 1)

print("== 6. 薄区（不足 1 亿）判据 ==")
q3 = [(500.0, 0.10, "散单"), (600.0, 0.11, "散单")]
ob3 = CD.orderbook_avg(q3)
ck("可供量 1100 万 < 1 亿 ⇒ 够量 False", ob3["够量"] is False)
ck("缺口 = 8900 万", abs(ob3["缺口"] - 8900.0) < 1e-6, ob3["缺口"])

print("\n结果：%d PASS / %d FAIL" % (P["n"], F["n"]))
sys.exit(1 if F["n"] else 0)

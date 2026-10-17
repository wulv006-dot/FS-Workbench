# -*- coding: utf-8 -*-
"""MSCW 部署后验收（服务端跑，只算不改）。
   ① 用真 config + 真 DD373 成本快照 + 真 IGGM 抓取，跑 core_gold.build_plan(MSCW)；
   ② 打印目标价 / 采购成本 / 成本除数 / 让价 / 利润率兜底；
   ③ 读后台行 21754 现行采购成本（gold_state）；
   ④ 读我方前台现行每 K 价。
"""
import io
import json
import os
import sys

sys.path.insert(0, "/opt/d4follow")
import core_gold as CG          # noqa: E402
import store                    # noqa: E402

CFG = json.load(io.open("/opt/d4follow/config.json", encoding="utf-8"))
GAME = "MapleStory Classic World"
print("=" * 78)
print("MSCW 部署后验收（只算不改）")
print("=" * 78)

print("\n[0] 策略与换算")
print("   pricing_policy     =", json.dumps(CG.pricing_policy(CFG, GAME), ensure_ascii=False))
print("   IGGM折算系数        =", CG.factor_of(CFG, GAME))
print("   成本除数            =", CG.cost_divisor_for_game(CFG, GAME))
print("   展示单位            =", CG.unit_label(CG.display_mult_of(CFG, GAME),
                                                (CG.game_param(CFG, GAME) or {}).get("展示单位名")))
print("   AION2 成本除数(对照) =", CG.cost_divisor_for_game(CFG, "AION2"))
print("   D4    成本除数(对照) =", CG.cost_divisor_for_game(CFG, "暗黑破坏神4"))

svs = [s for s in CG.servers_of(CFG) if CG.server_game(CFG, s) == GAME]
print("\n[1] MSCW 服务区：", [(s.get("key"), s.get("中文名"), s.get("后台行ID")) for s in svs])

con = store.connect("/opt/d4follow/data")
costs = {}
try:
    for r in store.gold_cost_latest(con, game=GAME):
        costs[r.get("key")] = {
            "ok": r.get("ok"), "cny_per_wan": r.get("cny_per_wan"),
            "usd_per_m": r.get("usd_per_m"), "n_items": r.get("n_items"),
            "dd_zone": r.get("dd_zone"), "basis": r.get("basis"),
            "note": r.get("note"), "stock": r.get("stock")}
except Exception as e:
    print("   ⚠ 读 gold_cost 失败:", repr(e))
print("\n[2] DD373 成本快照：", json.dumps(costs, ensure_ascii=False))

# 后台现行采购成本真值（执行器回传）
try:
    st = store.gold_state_rows(con)
    print("\n[2b] gold_state 后台采购成本真值：",
          json.dumps({k: v for k, v in st.items() if "MSCW" in k}, ensure_ascii=False))
except Exception as e:
    print("   ⚠ 读 gold_state 失败:", repr(e))

print("\n[3] build_plan（真抓 IGGM + 真前台）…")
plan = CG.build_plan(CFG, log=print, servers=svs, dd373_costs=costs)
for it in plan.get("items", []):
    print("\n  ── %s ──" % it.get("中文名"))
    for k in ("key", "后台行ID", "定价模式", "利润率", "展示单位",
              "IGGM每M", "IGGM每M_跟价用", "IGGM折算系数", "IGGM最大档", "IGGM最大档总价",
              "我方前端每M", "我方最大档", "我方最大档总价",
              "让价比例", "让价系数", "目标前端每M", "目标前端每M_口径",
              "DD373成本_USD每M", "DD373成本_元每万基纳", "DD373可买", "DD373可买_万基纳",
              "DD373挂单数", "DD373依据",
              "利润率_兜底前", "利润率下限", "利润率下限触发", "利润率下限_说明",
              "成本除数", "采购成本_新", "动作", "说明", "错误"):
        if k in it and it[k] is not None:
            print("     %-22s = %s" % (k, it[k]))
print("\n" + "=" * 78)

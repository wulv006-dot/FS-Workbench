# -*- coding: utf-8 -*-
"""只采 MSCW 的 DD373 进货成本并落库（等同 collect_gold_cost 的核心路径）。
   目的：让 MSCW 的 gold_cost 快照就位 ⇒ 15% 利润率兜底生效。
   不写 gold_price、不改价。
"""
import io
import json
import sys

sys.path.insert(0, "/opt/d4follow")
import core_dd373_cost as CD  # noqa: E402
import core_gold as CG        # noqa: E402
import store                  # noqa: E402

GAME = "MapleStory Classic World"
cfg = json.load(io.open("/opt/d4follow/config.json", encoding="utf-8"))
svs = [s for s in CG.servers_of(cfg) if CG.server_game(cfg, s) == GAME]
rate = CG.rate_of(cfg)
print("MSCW 服务区:", [s.get("key") for s in svs], "汇率:", rate)

costs = CD.fetch_costs(svs, rate, log=print, gap=1.3, game=GAME)
print("\n抓取结果:", json.dumps(costs, ensure_ascii=False, indent=1))

con = store.connect("/opt/d4follow/data")
try:
    import datetime as dt
    ts = dt.datetime.now().isoformat(timespec="seconds")
    n = store.save_gold_cost(con, ts, costs, {}, game=GAME)
    print("\n已落库 %d 条（ts=%s）" % (n, ts))
    for r in store.gold_cost_latest(con, game=GAME):
        print("  读回:", json.dumps({k: r.get(k) for k in (
            "key", "ok", "cny_per_wan", "usd_per_m", "n_items", "dd_zone",
            "stock", "basis", "note")}, ensure_ascii=False))
finally:
    con.close()

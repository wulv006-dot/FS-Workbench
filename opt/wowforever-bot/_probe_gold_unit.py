# -*- coding: utf-8 -*-
"""查后台金币商品的「单位/数量」定义，确认 b2c 到底是每 1 金还是每 N 金。"""
import json
import re
import sys

sys.path.insert(0, "/opt/d4follow")
sys.path.insert(0, "/opt/fs-order-session")
from core_p2pah import P2PAHClient  # noqa: E402

cfg = json.load(open("/opt/d4follow/config.json", encoding="utf-8"))
c = P2PAHClient(cfg, log=lambda *a, **k: None)

CAND = [
    "/game/admin_game_price/type/gold.html?gid=1364",
    "/game/admin_game_price/type/gold.html",
    "/game/admin_game_price/itemEdit?ids=22716",
    "/game/admin_goods/index.html?gid=1364",
]
for path in CAND:
    try:
        r = c.request(path, headers={"Accept": "text/html,application/json"})
    except Exception as e:                                    # noqa: BLE001
        print("%-48s ERR %s" % (path, str(e)[:60]))
        continue
    print("\n=== %s  (len=%d) ===" % (path, len(r or "")))
    if not r:
        continue
    # 单位相关关键词
    for kw in ("单位", "每", "数量", "quantity", "unit", "gold", "金"):
        n = r.count(kw)
        if n:
            print("   %-8s x%d" % (kw, n))
    for m in re.findall(r".{0,40}(?:单位|数量|quantity|unit|每[0-9])[^<>]{0,50}", r)[:6]:
        print("   >", re.sub(r"\s+", " ", m)[:120])

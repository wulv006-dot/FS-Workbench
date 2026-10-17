# -*- coding: utf-8 -*-
"""实测：新版 core_dd373_cost 的 MSCW 扁平专区采集（只读，不落库、不改任何文件）。"""
import json
import sys

sys.path.insert(0, "/opt/d4follow/_p2pah_srv")
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "cdnew", "/opt/d4follow/_p2pah_srv/_new_core_dd373_cost.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

svs = [{"key": "GOLD_MSCW_GLOBAL", "游戏": "MapleStory Classic World",
        "大区": "Global", "中文名": "Global World (Windia)"}]
print("### fetch_costs(game=MapleStory Classic World) ###")
res = m.fetch_costs(svs, 6.65, log=print, gap=1.5,
                    game="MapleStory Classic World")
print(json.dumps(res, ensure_ascii=False, indent=1))

print("\n### summarize ###")
print(json.dumps(m.summarize(res, {}), ensure_ascii=False, indent=1))

print("\n### AION2 回归：只跑 1 个区确认分发器没走错分支 ###")
_a1 = [{"key": "AION2_EU_SIEL_E", "游戏": "AION2", "大区": "EU",
        "g2g_服务区": "Siel - Elyos", "中文名": "EU · Siel - Elyos（天族）"}]
print(json.dumps(m.fetch_costs(_a1, 6.65, log=print, gap=1.0, game="AION2"),
                 ensure_ascii=False, indent=1)[:1500])

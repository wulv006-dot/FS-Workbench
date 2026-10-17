# -*- coding: utf-8 -*-
"""只读：列出 config.json 里挂在 D4(gid=456) 名下的登记键 → 后台商品ID。

纯 JSON 逻辑复刻 p2pah_local.game_of / game_gid_of（不 import playwright），
这样宿主机 python3 也能跑。
"""
import collections
import io
import json
import os

BASE = "/srv" if os.path.isdir("/srv/_p2pah_srv") else "/opt/d4follow"
cfg = json.load(io.open(BASE + "/config.json", encoding="utf-8"))
p = cfg.get("p2pah") or {}
m = p.get("商品ID映射") or {}

# ── 复刻 game_of：对照项 {key, 游戏} → 游戏名，查不到默认暗黑破坏神4 ──
DEFAULT_GAME = "暗黑破坏神4"
key2game = {}
for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
    k = it.get("key")
    if k:
        key2game[k] = it.get("游戏") or DEFAULT_GAME


def game_of(key):
    return key2game.get(key, DEFAULT_GAME)


# ── 复刻 game_gid_of：游戏名 → 别名 → gid，三重兼容 ──
games = p.get("游戏") or {}
alias = p.get("游戏别名") or {}


def game_gid_of(key):
    gname = game_of(key)
    gm = games.get(gname) if isinstance(games.get(gname), dict) else None
    if gm is None:
        code = alias.get(gname)
        if code and isinstance(games.get(code), dict):
            gm = games[code]
    if gm is None:
        for _k, v in games.items():
            if isinstance(v, dict) and gname in (v.get("我方名"), v.get("中文名")):
                gm = v
                break
    if isinstance(gm, dict) and gm.get("game_id"):
        return str(gm["game_id"])
    return str((games.get("D4") or {}).get("game_id") or "456")


by_gid = collections.defaultdict(dict)
for k, v in m.items():
    if str(k).startswith("_"):
        continue
    by_gid[game_gid_of(k)][k] = str(v or "").strip()

print("对照项条目数 = %d ／ 商品ID映射 keys = %d" % (len(key2game), len(by_gid and m)))
print("按 gid 分布：")
for g in sorted(by_gid, key=lambda x: -len(by_gid[x])):
    print("   gid=%-6s %4d 个" % (g, len(by_gid[g])))

d4 = by_gid.get("456") or {}
print("")
print("=== D4(gid=456) 登记键 %d 个 ===" % len(d4))
for k in sorted(d4):
    print("  %-46s %s" % (k, d4[k]))

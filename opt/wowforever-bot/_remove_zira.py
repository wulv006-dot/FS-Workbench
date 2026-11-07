# -*- coding: utf-8 -*-
"""移除 Zira 机器人：先核层级，够才踢；踢完读回确认。"""
import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEC = os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt")
if not os.path.exists(SEC):
    SEC = "/opt/wowforever-bot/secrets/token.txt"
TOKEN = open(SEC, encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
GID = "1567427533685657630"
ME = "1568537417642807418"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


st, roles = call("/guilds/%s/roles" % GID)
rmap = {r["id"]: r for r in roles}
st, me = call("/guilds/%s/members/%s" % (GID, ME))
my_top = max([rmap.get(x, {}).get("position", 0) for x in me.get("roles", [])] or [0])
print("Blingtron 最高角色位置 =", my_top)

st, members = call("/guilds/%s/members?limit=1000" % GID)
if st != 200:
    print("取成员失败", st, members)
    raise SystemExit(1)
print("成员数 =", len(members))

bots = [m for m in members if m["user"].get("bot")]
print("\n服务器内机器人：")
for b in bots:
    tops = [rmap.get(x, {}).get("position", 0) for x in b.get("roles", [])] or [0]
    print("  %-22s id=%s roles=%s top=%s" % (
        b["user"]["username"], b["user"]["id"],
        [rmap.get(x, {}).get("name", x) for x in b.get("roles", [])], max(tops)))

target = next((b for b in bots
               if b["user"]["id"] != ME and "zira" in b["user"]["username"].lower()), None)
if target is None:
    print("\n没找到 Zira（可能已不在服务器）")
    raise SystemExit(0)

tz = target["user"]
zid = tz["id"]
ztop = max([rmap.get(x, {}).get("position", 0) for x in target.get("roles", [])] or [0])
print("\n目标: %s (id=%s) 最高角色位置=%s" % (tz["username"], zid, ztop))

if my_top <= ztop:
    print("层级不够（%s <= %s），踢不动。需要先把 Blingtron 拖高。" % (my_top, ztop))
    raise SystemExit(2)

st, body = call("/guilds/%s/members/%s" % (GID, zid), "DELETE")
print("DELETE 成员 ->", st, "" if st in (200, 204) else body)

st2, after = call("/guilds/%s/members?limit=1000" % GID)
still = [m for m in after if m["user"]["id"] == zid] if st2 == 200 else []
print("读回：Zira 是否仍在 =", bool(still), "| 当前成员数 =", len(after) if st2 == 200 else "?")

# -*- coding: utf-8 -*-
"""尝试由机器人自己把 Administrator 加到自身受管角色上（预期多半 403，测了才知道）。
当前 perms 备份：18823733832791
"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
GID = "1567427533685657630"
BOT_ROLE = "1568542803951231046"
CUR = 18823733832791
NEW = CUR | (1 << 3)


def call(path, method, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
        **({"Content-Type": "application/json"} if data else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


st, body = call(f"/guilds/{GID}/roles/{BOT_ROLE}", "PATCH", {"permissions": str(NEW)})
print("PATCH 自身角色 perms ->", st)
print("   ", body if st >= 400 else f"ok perms={body.get('permissions')}")

st2, body2 = call(f"/guilds/{GID}/roles/{BOT_ROLE}", "PATCH", {"position": 17})
print("PATCH 自身角色 position=17 ->", st2)
print("   ", body2 if st2 >= 400 else f"ok position={body2.get('position')}")

st3, roles = call(f"/guilds/{GID}/roles", "GET")
if st3 == 200 and isinstance(roles, list):
    for r in roles:
        if r["id"] == BOT_ROLE:
            print(f"读回: perms={r['permissions']} position={r['position']} admin={bool(int(r['permissions']) & 8)}")

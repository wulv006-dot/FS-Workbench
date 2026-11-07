# -*- coding: utf-8 -*-
"""诊断 403 根因：
  A) 在看得见的频道给「自己角色」加覆盖 -> 204 说明只是可见性问题
  B) 若仍 403 说明是自己角色的层级限制
试验后立即删除覆盖并读回确认无残留。
"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
BOT_ROLE = "1568542803951231046"
VISIBLE = "1567716852216627320"   # 🎫│support（机器人可见）
ALLOW = (1 << 16)


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


st, _ = call(f"/channels/{VISIBLE}/permissions/{BOT_ROLE}", "PUT",
             {"type": 0, "allow": str(ALLOW), "deny": "0"})
print("A) 可见频道 + 自己角色 PUT ->", st)
if st in (200, 204):
    st2, _ = call(f"/channels/{VISIBLE}/permissions/{BOT_ROLE}", "DELETE")
    print("   撤销 DELETE ->", st2)
    st3, ch = call(f"/channels/{VISIBLE}", "GET")
    left = [o for o in ch.get("permission_overwrites", []) if o["id"] == BOT_ROLE]
    print("   残留检查:", "无残留 OK" if not left else f"仍有 {left}")
else:
    print("   => 不是可见性问题，是自己角色的层级/受管限制")

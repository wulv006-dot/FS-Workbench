# -*- coding: utf-8 -*-
"""给 Blingtron-9000 在 MODERATION 分类授 VIEW_CHANNEL + READ_MESSAGE_HISTORY，并读回验证。

回滚：删掉该覆盖 -> DELETE /channels/{cid}/permissions/{role}
改前快照：_backup_overwrites_<ts>.json
"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
CAT = "1567715811995418686"      # MODERATION
BOT_ROLE = "1568542803951231046"
ALLOW = (1 << 10) | (1 << 16)    # VIEW_CHANNEL | READ_MESSAGE_HISTORY = 66560


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
        return e.code, e.read().decode("utf-8", "replace")[:400]


print(f"授予 MODERATION 分类 -> Blingtron-9000  allow={ALLOW} (VIEW|READ_HIST)")
st, body = call(f"/channels/{CAT}/permissions/{BOT_ROLE}", "PUT",
                {"type": 0, "allow": str(ALLOW), "deny": "0"})
print("PUT ->", st, body if st >= 400 else "ok")

st, ch = call(f"/channels/{CAT}", "GET")
if st == 200:
    for o in ch.get("permission_overwrites", []):
        if o["id"] == BOT_ROLE:
            print(f"读回: type={o['type']} allow={o['allow']} deny={o['deny']}")

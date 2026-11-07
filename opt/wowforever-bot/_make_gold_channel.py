# -*- coding: utf-8 -*-
"""建金币查价频道（@everyone 只读），并输出 id 供 config 引用。"""
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
GID = "1567427533685657630"
COMMUNITY = "1567715790235500654"
NAME = "🪙｜gold-price"
TOPIC = ("WoW Forever gold prices · USD per 1,000 gold · synced from the shop backend "
         "every 30 minutes · read-only: pick a region below.")
ALLOW = 66560                    # VIEW_CHANNEL | READ_MESSAGE_HISTORY
DENY = 377957124160              # SEND | ADD_REACTIONS | threads


def api(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
        **({"Content-Type": "application/json"} if data else {})})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception as e:                                # noqa: BLE001
            if i == 2:
                return -1, repr(e)
            time.sleep(2)


st, chans = api("/guilds/%s/channels" % GID)
existing = next((c for c in chans if c["name"] == NAME), None) if st == 200 else None
if existing:
    print("频道已存在 id=%s" % existing["id"])
    raise SystemExit(0)

st, body = api("/guilds/%s/channels" % GID, "POST", {
    "name": NAME,
    "type": 0,
    "parent_id": COMMUNITY,
    "topic": TOPIC,
    "permission_overwrites": [{"id": GID, "type": 0,
                               "allow": str(ALLOW), "deny": str(DENY)}],
})
print("POST ->", st)
if st in (200, 201):
    print("新建频道 id=%s name=%s parent=%s" % (body["id"], body["name"], body.get("parent_id")))
    print("READONLY: allow=%s deny=%s" % (ALLOW, DENY))
else:
    print(body)

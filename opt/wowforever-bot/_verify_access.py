# -*- coding: utf-8 -*-
"""用真实读操作证明 4 个 MODERATION 频道的访问已通（读 1 条历史，不发消息）。"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
GID = "1567427533685657630"
BOT_ID = "1568537417642807418"

TARGETS = {
    "1567716781819170826": "🔒│moderator-only",
    "1567716904288784475": "🧾│order-logs",
    "1567437714339405894": "📝│mod-log",
    "1567442375033233418": "🛠️│admin",
    "1567715811995418686": "MODERATION (category)",
}


def call(path, method="GET", body=None):
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
        return e.code, e.read().decode("utf-8", "replace")[:200]


print("== 有效权限 ==")
st, member = call(f"/guilds/{GID}/members/{BOT_ID}")
st2, roles = call(f"/guilds/{GID}/roles")
rmap = {r["id"]: r for r in roles}
merged = 0
for rid in member["roles"]:
    merged |= int(rmap[rid]["permissions"])
print("   roles:", [(rmap[r]["name"], rmap[r]["position"]) for r in member["roles"]])
print(f"   合并权限位 = {merged}  ADMIN = {bool(merged & 8)} (8={merged & 8})")

print("\n== 实测读权限（GET 1 条历史） ==")
for cid, label in TARGETS.items():
    st, body = call(f"/channels/{cid}/messages?limit=1")
    ok = "OK 可读" if st == 200 else f"失败 {st} {body if isinstance(body, str) else ''}"
    print(f"   {label:<24} -> {ok}")

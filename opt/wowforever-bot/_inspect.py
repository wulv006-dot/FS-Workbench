# -*- coding: utf-8 -*-
"""深入核验：机器人成员 / 全量角色位置 / 机器人在关键频道的实际权限。"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
BOT_ID = "1568537417642807418"
GID = "1567427533685657630"

NAMES = {
    1 << 0: "CREATE_INSTANT_INVITE", 1 << 1: "KICK_MEMBERS", 1 << 2: "BAN_MEMBERS",
    1 << 3: "ADMIN", 1 << 4: "MANAGE_CHANNELS", 1 << 5: "MANAGE_GUILD",
    1 << 6: "ADD_REACTIONS", 1 << 7: "VIEW_AUDIT_LOG", 1 << 8: "PRIORITY_SPEAKER",
    1 << 10: "VIEW_CHANNEL", 1 << 11: "SEND_MESSAGES", 1 << 12: "SEND_TTS",
    1 << 13: "MANAGE_MESSAGES", 1 << 14: "EMBED_LINKS", 1 << 15: "ATTACH_FILES",
    1 << 16: "READ_HISTORY", 1 << 17: "MENTION_EVERYONE", 1 << 18: "EXT_EMOJIS",
    1 << 19: "VIEW_GUILD_INSIGHTS", 1 << 20: "CONNECT", 1 << 21: "SPEAK",
    1 << 22: "MUTE_MEMBERS", 1 << 23: "DEAFEN_MEMBERS", 1 << 24: "MOVE_MEMBERS",
    1 << 25: "USE_VAD", 1 << 26: "CHANGE_NICKNAME", 1 << 27: "MANAGE_NICKNAMES",
    1 << 28: "MANAGE_ROLES", 1 << 29: "MANAGE_WEBHOOKS", 1 << 30: "MANAGE_EMOJIS",
    1 << 31: "USE_APP_CMDS", 1 << 32: "REQUEST_TO_SPEAK", 1 << 33: "MANAGE_EVENTS",
    1 << 34: "MANAGE_THREADS", 1 << 35: "PUBLIC_THREADS", 1 << 36: "PRIVATE_THREADS",
    1 << 37: "EXT_STICKERS", 1 << 38: "SEND_MSG_IN_THREADS",
    1 << 39: "USE_EMBEDDED_ACTIVITIES", 1 << 40: "MODERATE_MEMBERS",
    1 << 44: "CREATE_EVENTS", 1 << 46: "CREATE_POLLS", 1 << 49: "USE_EXT_APPS",
}


def api(path, method="GET", body=None):
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


def bits(v):
    return [NAMES[b] for b in NAMES if v & b] or ["(none)"]


st, me = api(f"/guilds/{GID}/members/{BOT_ID}")
print("== bot member ->", st)
if st == 200:
    print("   nick   :", me.get("nick"))
    print("   roles  :", me.get("roles"))
    print("   joined :", me.get("joined_at"))
else:
    print("   body:", me)

st, roles = api(f"/guilds/{GID}/roles")
roles = roles if isinstance(roles, list) else []
by_id = {r["id"]: r for r in roles}
print(f"\n== 全量角色 ({len(roles)})，按位置高→低 ==")
for r in sorted(roles, key=lambda r: -r["position"]):
    tag = ""
    if r.get("managed"):
        tag = "  <BOT/MANAGED>"
    print(f"   pos={r['position']:>3}  {r['name']!r:<26} id={r['id']}{tag}")
    if r["permissions"] != "0":
        print(f"                perms={r['permissions']} -> {', '.join(bits(int(r['permissions'])))}")

bot_role_id = me["roles"][0] if st == 200 and me.get("roles") else None
print("\n== 机器人角色 ==")
if bot_role_id and bot_role_id in by_id:
    br = by_id[bot_role_id]
    print(f"   name={br['name']!r} pos={br['position']} perms={br['permissions']}")
    print(f"   bits: {', '.join(bits(int(br['permissions'])))}")
    higher = [r for r in roles if r["position"] > br["position"] and not r.get("managed")]
    print(f"   在它之上的角色 {len(higher)} 个: {[r['name'] for r in higher]}")
else:
    print("   (未找到机器人自身角色)")

everyone = by_id.get(GID)
if everyone:
    print(f"\n== @everyone perms={everyone['permissions']} ==")
    print("   bits:", ", ".join(bits(int(everyone["permissions"]))))

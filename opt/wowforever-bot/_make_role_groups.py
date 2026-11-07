# -*- coding: utf-8 -*-
"""建 4 级身份组所需的组：阵容（Alliance/Horde）+ 职业（9 个经典职业）。

幂等：同名组已存在就跳过，不重复建、不改已有组。
"""
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

NEW_ROLES = [
    ("Alliance", 0x3B82F6),
    ("Horde", 0xEF4444),
    ("Warrior", 0xC79C6E),
    ("Paladin", 0xF58CBA),
    ("Hunter", 0xABD473),
    ("Rogue", 0xFFF569),
    ("Priest", 0xE8E8E8),
    ("Shaman", 0x0070DE),
    ("Mage", 0x69CCF0),
    ("Warlock", 0x9482C9),
    ("Druid", 0xFF7D0A),
]


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


st, roles = api("/guilds/%s/roles" % GID)
if st != 200:
    print("取角色失败", st, roles)
    raise SystemExit(1)
existing = {r["name"]: r for r in roles}
print("现有角色 %d 个" % len(roles))

out = {}
for name, colour in NEW_ROLES:
    if name in existing:
        rid = existing[name]["id"]
        print("  已存在  %-10s %s" % (name, rid))
        out[name] = rid
        continue
    st, body = api("/guilds/%s/roles" % GID, "POST", {
        "name": name, "color": colour, "hoist": False,
        "mentionable": False, "permissions": "0"})
    if st in (200, 201):
        print("  已创建  %-10s %s  #%06X" % (name, body["id"], colour))
        out[name] = body["id"]
    else:
        print("  失败    %-10s %s %s" % (name, st, body))
    time.sleep(0.3)

print("\n=== 新/复用组 id ===")
print(json.dumps(out, ensure_ascii=False, indent=1))
with open(os.path.join(HERE, "_new_roles.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("\nwritten -> _new_roles.json")

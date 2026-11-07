# -*- coding: utf-8 -*-
"""查看 4 个 MODERATION 频道及其分类的权限覆盖来源，并备份全部覆盖。"""
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
GID = "1567427533685657630"
VIEW = 1 << 10
READ_HIST = 1 << 16

TARGETS = {
    "1567715811995418686": "MODERATION (category)",
    "1567716781819170826": "moderator-only",
    "1567716904288784475": "order-logs",
    "1567437714339405894": "mod-log",
    "1567442375033233418": "admin",
}


def api(path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


roles = {r["id"]: r for r in api(f"/guilds/{GID}/roles")}
chans = {c["id"]: c for c in api(f"/guilds/{GID}/channels")}

# ---- 备份全部频道覆盖（回滚点）----
ts = time.strftime("%Y%m%d-%H%M%S")
bak = os.path.join(HERE, f"_backup_overwrites_{ts}.json")
with open(bak, "w", encoding="utf-8") as f:
    json.dump([{k: c[k] for k in ("id", "name", "type", "parent_id",
                                  "permission_overwrites")} for c in chans.values()],
              f, ensure_ascii=False, indent=2)
print(f"[backup] {bak}\n")

for cid, label in TARGETS.items():
    c = chans[cid]
    parent = chans.get(c.get("parent_id"))
    print(f"== {label}  id={cid}  parent={parent['name'] if parent else None}")
    ows = c.get("permission_overwrites", [])
    if not ows:
        print("   覆盖: (空 — 继承分类)")
    for o in ows:
        who = "@everyone" if o["id"] == GID else roles.get(o["id"], {}).get("name", o["id"])
        a, d = int(o["allow"]), int(o["deny"])
        flags = []
        if a & VIEW: flags.append("allow:VIEW")
        if d & VIEW: flags.append("deny:VIEW")
        if a & READ_HIST: flags.append("allow:READ_HIST")
        print(f"   - {o['type']}({who}) allow={a} deny={d}  {' '.join(flags)}")
    print()

# -*- coding: utf-8 -*-
"""机器人入服后核验：身份 / 服务器 / 机器人成员权限 / 频道清单。不输出令牌。"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
KEYWORDS = ("WOW FOREVER", "WOWFOREVER", "WOW")


def api(path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:  # noqa
        return -1, repr(e)


st, guilds = api("/users/@me/guilds")
print("== guilds ->", st)
if st != 200:
    print(guilds)
    sys.exit(1)
if not guilds:
    print("   机器人仍不在任何服务器 —— 授权页还没点完。")
    sys.exit(2)

for g in guilds:
    print(f"   {g['id']}  {g['name']}  perms={g.get('permissions')}  owner={g.get('owner')}")

target = None
for g in guilds:
    if any(k in g["name"].upper() for k in KEYWORDS):
        target = g
        break
if target is None:
    print("\n[!] 没有名字匹配 WOW 的服务器，列出的都在上面。")
    sys.exit(3)

gid = target["id"]
print(f"\n== 目标服务器 ==  {target['name']}  ({gid})")

st, guild = api(f"/guilds/{gid}?with_counts=true")
print("== guild ->", st)
if st == 200:
    print("   name    :", guild.get("name"))
    print("   owner   :", guild.get("owner_id"))
    print("   members :", guild.get("approximate_member_count"),
          "| online:", guild.get("approximate_presence_count"))
    print("   features:", guild.get("features"))
else:
    print("   body:", guild)

st, me = api(f"/guilds/{gid}/members/@me")
print("== bot member ->", st)
if st == 200:
    print("   nick   :", me.get("nick"))
    print("   roles  :", me.get("roles"))
    print("   joined :", me.get("joined_at"))
else:
    print("   body:", me)

st, roles = api(f"/guilds/{gid}/roles")
if st == 200:
    roles_sorted = sorted(roles, key=lambda r: r["position"], reverse=True)
    print(f"== roles ({len(roles)}) 从上到下前 12 ==")
    for r in roles_sorted[:12]:
        print(f"   pos={r['position']:>3}  {r['name']!r:<28} perms={r['permissions']}"
              f"{'  [managed/bot]' if r.get('managed') else ''}")
else:
    print("== roles ->", st, roles)

st, chans = api(f"/guilds/{gid}/channels")
if st == 200:
    cats = [c for c in chans if c["type"] == 4]
    print(f"== channels ({len(chans)}) ==")
    for c in sorted(chans, key=lambda x: (x.get("position", 0), x["id"])):
        t = {0: "text", 2: "voice", 4: "category", 5: "news", 13: "stage",
             15: "forum", 16: "media"}.get(c["type"], c["type"])
        print(f"   [{t:<8}] {c['id']}  {c['name']}")
    print(f"   categories: {len(cats)} | text: {sum(1 for c in chans if c['type']==0)}")
else:
    print("== channels ->", st, chans)

# 权限自检：把 perms 位翻译成人话
st, member = api(f"/guilds/{gid}/members/@me")
print("\n== 建议核对（权限值不具备时到服务器设置里调） ==")
print("   1) Blingtron-9000 的角色是否已拖到「仅次于管理员」的位置（影响管角色/管频道）")
print("   2) 机器人是否能看到目标频道（分类级 @everyone 拒绝会盖住）")

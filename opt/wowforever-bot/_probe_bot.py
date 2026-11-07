# -*- coding: utf-8 -*-
"""只读探测：机器人身份 / 已加入的服务器。不输出令牌。"""
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"


def get(path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:  # noqa
        return -1, repr(e)


st, me = get("/users/@me")
print("== /users/@me ->", st)
if st == 200:
    print("   id       :", me.get("id"))
    print("   username :", me.get("username"))
    print("   global   :", me.get("global_name"))
    print("   bot      :", me.get("bot"))
    print("   verified :", me.get("verified"))
    print("   flags    :", me.get("flags"))
else:
    print("   body:", me)
    sys.exit(1)

st2, guilds = get("/users/@me/guilds")
print("== /users/@me/guilds ->", st2)
if st2 == 200:
    if not guilds:
        print("   (机器人还没加入任何服务器)")
    for g in guilds:
        print(f"   {g['id']}  {g['name']}   owner={g.get('owner')}  perms={g.get('permissions')}")
else:
    print("   body:", guilds)

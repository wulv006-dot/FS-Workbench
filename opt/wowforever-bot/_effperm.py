# -*- coding: utf-8 -*-
"""按 Discord 覆盖规则计算机器人在每个文字频道的有效 VIEW_CHANNEL / SEND_MESSAGES。

规则（官方）：
  base = @everyone 角色权限
  -> 应用 @everyone 在频道上的 overwrite（deny 掩码 ^ allow 掩码）
  -> 机器人自身角色若在频道上有 overwrite，再叠加 allow |= a, deny |= d
  -> final = allow | (base & ~deny) 且 allow 优先于 deny
"""
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
BOT_ID = "1568537417642807418"
GID = "1567427533685657630"
BOT_ROLE = "1568542803951231046"
ADMIN = 1 << 3
VIEW = 1 << 10
SEND = 1 << 11
READ_HIST = 1 << 16

TYPE = {0: "text", 2: "voice", 4: "category", 5: "news", 15: "forum"}


def api(path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


roles = {r["id"]: r for r in api(f"/guilds/{GID}/roles")}
everyone = roles[GID]
chans = api(f"/guilds/{GID}/channels")
cats = {c["id"]: c for c in chans if c["type"] == 4}


def compute(perms, chan, parent):
    ow = {o["id"]: int(o["allow"]) for o in chan.get("permission_overwrites", [])}
    dw = {o["id"]: int(o["deny"]) for o in chan.get("permission_overwrites", [])}
    allow = ow.get(GID, 0)
    deny = dw.get(GID, 0)
    p = (perms & ~deny) | allow
    if BOT_ROLE in ow or BOT_ROLE in dw:
        p |= ow.get(BOT_ROLE, 0)
        p &= ~dw.get(BOT_ROLE, 0)
    return p


base = int(everyone["permissions"])
botrole = int(roles[BOT_ROLE]["permissions"])
# 有效角色权限 = @everyone | 机器人角色
role_perms = base | botrole
is_admin = bool(role_perms & ADMIN) or bool(base & ADMIN)

print(f"@everyone={base}   bot_role={botrole}   合并={role_perms}   admin={is_admin}")
print()
print(f"{'频道':<28} {'类型':<7} {'可见':<5} {'发消息':<6} 备注")
print("-" * 78)

issues = []
for c in sorted(chans, key=lambda x: (x["type"] != 4, x.get("parent_id") or "", x.get("position", 0))):
    if c["type"] not in (0, 5, 15):
        continue
    parent = cats.get(c.get("parent_id"))
    p = compute(role_perms, c, parent)
    if parent:  # 分类覆盖也生效
        p = compute(p, parent, None)
    can_view = is_admin or bool(p & VIEW)
    can_send = is_admin or bool(p & SEND)
    note = ""
    if not can_view:
        note = "<-- 看不到"
        issues.append((c["name"], "no view"))
    elif not can_send:
        note = "<-- 只读"
    print(f"{c['name']:<28} {TYPE.get(c['type'], c['type']):<7} "
          f"{'Y' if can_view else 'N':<5} {'Y' if can_send else 'N':<6} {note}")

print("\n== 汇总 ==")
text = [c for c in chans if c["type"] in (0, 5, 15)]
print(f"文字类频道 {len(text)} 个；不可见 {len([i for i in issues if i[1]=='no view'])} 个")
if issues:
    print("需要处理后才能发消息的:", issues)
else:
    print("全部可见 —— 无需调整频道覆盖。")

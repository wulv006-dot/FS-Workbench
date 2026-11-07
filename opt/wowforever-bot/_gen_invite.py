# -*- coding: utf-8 -*-
"""生成 Blingtron-9000 的 OAuth2 邀请链接（不输出令牌）。

权限口径
--------
MANAGER  = 频道/角色/审核/消息管理全给，**不给 Administrator(8)**，也不给 MANAGE_GUILD(32)
           —— 与 D4 Concierge 先例一致：能干活，但改不了服务器名/删不了整个服。
ADMIN    = 8，仅在用户明确要求「完全托管」时使用。
"""
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ID = "1568537417642807418"

P = {
    "CREATE_INSTANT_INVITE": 1 << 0,
    "KICK_MEMBERS": 1 << 1,
    "BAN_MEMBERS": 1 << 2,
    "MANAGE_CHANNELS": 1 << 4,
    "MANAGE_GUILD": 1 << 5,
    "ADD_REACTIONS": 1 << 6,
    "VIEW_AUDIT_LOG": 1 << 7,
    "VIEW_CHANNEL": 1 << 10,
    "SEND_MESSAGES": 1 << 11,
    "MANAGE_MESSAGES": 1 << 13,
    "EMBED_LINKS": 1 << 14,
    "ATTACH_FILES": 1 << 15,
    "READ_MESSAGE_HISTORY": 1 << 16,
    "MENTION_EVERYONE": 1 << 17,
    "USE_EXTERNAL_EMOJIS": 1 << 18,
    "CONNECT": 1 << 20,
    "SPEAK": 1 << 21,
    "MUTE_MEMBERS": 1 << 22,
    "DEAFEN_MEMBERS": 1 << 23,
    "MOVE_MEMBERS": 1 << 24,
    "CHANGE_NICKNAME": 1 << 26,
    "MANAGE_NICKNAMES": 1 << 27,
    "MANAGE_ROLES": 1 << 28,
    "MANAGE_WEBHOOKS": 1 << 29,
    "USE_APPLICATION_COMMANDS": 1 << 31,
    "MANAGE_EVENTS": 1 << 33,
    "MANAGE_THREADS": 1 << 34,
    "CREATE_PUBLIC_THREADS": 1 << 35,
    "CREATE_PRIVATE_THREADS": 1 << 36,
    "MODERATE_MEMBERS": 1 << 40,
    "CREATE_EVENTS": 1 << 44,
}

MANAGER = [
    "CREATE_INSTANT_INVITE", "KICK_MEMBERS", "BAN_MEMBERS", "MODERATE_MEMBERS",
    "MANAGE_CHANNELS", "MANAGE_ROLES", "MANAGE_WEBHOOKS", "MANAGE_NICKNAMES",
    "MANAGE_THREADS", "CREATE_PUBLIC_THREADS", "CREATE_PRIVATE_THREADS",
    "MANAGE_EVENTS", "CREATE_EVENTS",
    "VIEW_CHANNEL", "SEND_MESSAGES", "MANAGE_MESSAGES", "EMBED_LINKS",
    "ATTACH_FILES", "READ_MESSAGE_HISTORY", "ADD_REACTIONS",
    "USE_EXTERNAL_EMOJIS", "MENTION_EVERYONE", "USE_APPLICATION_COMMANDS",
    "CONNECT", "SPEAK", "MUTE_MEMBERS", "DEAFEN_MEMBERS", "MOVE_MEMBERS",
    "CHANGE_NICKNAME",
]


def bits(names):
    v = 0
    for n in names:
        v |= P[n]
    return v


def link(perm: int, guild_id: str | None = None) -> str:
    q = {
        "client_id": APP_ID,
        "scope": "bot applications.commands",
        "permissions": str(perm),
    }
    if guild_id:
        q["guild_id"] = guild_id
        q["disable_guild_select"] = "true"
    return "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(q)


mgr = bits(MANAGER)
admin = 8

print("=== 权限集合 ===")
print(f"MANAGER  共 {len(MANAGER)} 项  -> permissions={mgr}")
print(f"ADMIN                      -> permissions={admin}")
print()
print("=== 邀请链接（推荐：管理权限，无 Administrator）===")
print(link(mgr))
print()
print("=== 备用：Administrator 完全托管 ===")
print(link(admin))
print()

# 落盘一份，便于后续复用
out = {
    "app_id": APP_ID,
    "bot_name": "Blingtron-9000",
    "permissions_manager": mgr,
    "permissions_admin": admin,
    "manager_scopes": MANAGER,
    "invite_manager": link(mgr),
    "invite_admin": link(admin),
}
with open(os.path.join(HERE, "invite_links.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("written -> invite_links.json")

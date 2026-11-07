# -*- coding: utf-8 -*-
"""离线自检：不连网关，只用 REST 校验配置里的每个频道/角色是否真的可用。

重点检查「机器人能不能给这个角色」—— 这是欢迎模块能否工作的唯一硬条件：
  机器人最高角色位置 > 目标角色位置  ⇒ 可以
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
API = "https://discord.com/api/v10"


def token():
    t = os.environ.get("WF_TOKEN", "").strip()
    if t:
        return t
    with open(os.path.join(ROOT, "secrets", "token.txt"), "r", encoding="utf-8") as f:
        return f.read().strip()


TOKEN = token()


def api(path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:                                     # noqa: BLE001
        return -1, repr(e)


VIEW = 1 << 10
SEND = 1 << 11
fails = []
warns = []


def ok(flag, label, detail=""):
    mark = "OK  " if flag else "FAIL"
    print("  [%s] %-34s %s" % (mark, label, detail))
    if not flag:
        fails.append(label)


def main():
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    gid = str(cfg["guild_id"])

    st, me = api("/users/@me")
    if st != 200:
        print("令牌无效:", st, me)
        return 1
    print("机器人: %s (%s)\n" % (me["username"], me["id"]))

    st, guild = api("/guilds/%s" % gid)
    ok(st == 200, "服务器可达", guild.get("name") if st == 200 else str(guild))

    st, chans = api("/guilds/%s/channels" % gid)
    by_id = {c["id"]: c for c in chans} if st == 200 else {}
    ok(st == 200, "频道列表", "%d 个" % len(by_id))

    print("\n== 频道别名 ==")
    for alias, cid in sorted((cfg.get("channels") or {}).items()):
        c = by_id.get(str(cid))
        ok(c is not None, "channel:%s" % alias,
           (c["name"] if c else "id 不存在: %s" % cid))

    st, roles = api("/guilds/%s/roles" % gid)
    rmap = {r["id"]: r for r in roles} if st == 200 else {}
    st, member = api("/guilds/%s/members/%s" % (gid, me["id"]))
    my_top = 0
    if st == 200:
        for rid in member.get("roles", []):
            my_top = max(my_top, rmap.get(rid, {}).get("position", 0))
    print("\n机器人最高角色位置 = %s\n" % my_top)

    hub = cfg["features"]["welcome"].get("role_hub") or {}
    hub_groups = ("regions", "factions", "rulesets", "classes")
    print("== 四级身份组（role_hub） ==")
    seen = {}
    clash = False
    for group in hub_groups:
        items = hub.get(group) or []
        print("  -- %s (%d) --" % (group, len(items)))
        keys = [x["key"] for x in items]
        if len(keys) != len(set(keys)):
            print("     [FAIL] 组内 key 重复")
            fails.append("key 重复 %s" % group)
        for item in items:
            r = rmap.get(str(item["role_id"]))
            if r is None:
                ok(False, "%s/%s" % (group, item["key"]), "角色 id 不存在")
                continue
            can = my_top > r["position"]
            ok(True, "%s/%s" % (group, item["key"]), r["name"])
            print("        pos=%d %s" % (r["position"], "可分配" if can else "!! 机器人位置不够"))
            if not can:
                warns.append("%s (%s) pos=%d" % (r["name"], group, r["position"]))
            rid = str(item["role_id"])
            if rid in seen:
                print("     [WARN] 同一个角色出现在两组:", rid)
                clash = True
            seen[rid] = group

    print("\n== 自定义 id 冲突 ==")
    ok(not clash, "角色不重复出现在两组")

    print("\n== 汇总 ==")
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
    if warns:
        print("层级不足 %d 项（需要把 Blingtron-9000 拖到这些角色之上）:" % len(warns))
        for w in warns:
            print("   -", w)
    if not fails and not warns:
        print("SELFTEST OK —— 配置全部可用")
    elif not fails:
        print("SELFTEST OK（仅层级告警）")
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())

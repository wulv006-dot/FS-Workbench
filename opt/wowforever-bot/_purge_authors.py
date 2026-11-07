# -*- coding: utf-8 -*-
"""按作者 id 批量清理消息（跨频道、幂等）。

用法: python _purge_authors.py 235148962103951360 275813801792634880
不动自己发的消息（PANEL 显式排除）。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
GID = "1567427533685657630"
KEEP = {"1568549337145942168"}
AUTHORS = set(sys.argv[1:]) or {"235148962103951360", "275813801792634880"}


def api(path, method="GET"):
    for i in range(3):
        try:
            req = urllib.request.Request(API + path, method=method, headers={
                "Authorization": "Bot " + TOKEN,
                "User-Agent": "DiscordBot (mmoexp-ops, 1.0)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:200]
        except Exception as e:                                # noqa: BLE001
            if i == 2:
                return -1, repr(e)
            time.sleep(2)


st, chans = api("/guilds/%s/channels" % GID)
if st != 200:
    print("取频道失败", st, chans)
    raise SystemExit(1)
text = [c for c in chans if c["type"] in (0, 5, 15)]

total_ok = total_fail = 0
per_channel = []
for c in text:
    ids, before = [], None
    for _ in range(4):
        q = "/channels/%s/messages?limit=100" % c["id"] + ("&before=" + before if before else "")
        s, msgs = api(q)
        if s != 200 or not isinstance(msgs, list) or not msgs:
            break
        for m in msgs:
            if m["author"]["id"] in AUTHORS and m["id"] not in KEEP:
                ids.append(m["id"])
        before = msgs[-1]["id"]
        if len(msgs) < 100:
            break
    if not ids:
        continue
    ok = fail = 0
    for mid in ids:
        s, body = api("/channels/%s/messages/%s" % (c["id"], mid), "DELETE")
        if s in (200, 204):
            ok += 1
        else:
            fail += 1
            print("   失败", mid, s, body)
        time.sleep(0.25)
    per_channel.append((c["name"], ok, fail))
    total_ok += ok
    total_fail += fail

print("\n=== 删除明细 ===")
for name, ok, fail in per_channel:
    print("  %-26s 删除 %2d  失败 %d" % (name, ok, fail))
print("合计: 删除 %d  失败 %d" % (total_ok, total_fail))

print("\n=== 复查 ===")
left = 0
for c in text:
    s, msgs = api("/channels/%s/messages?limit=100" % c["id"])
    if s != 200 or not isinstance(msgs, list):
        continue
    n = sum(1 for m in msgs if m["author"]["id"] in AUTHORS)
    if n:
        print("  仍残留 %s: %d 条" % (c["name"], n))
        left += n
print("残留合计 =", left)

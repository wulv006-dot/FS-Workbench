# -*- coding: utf-8 -*-
"""删除 Zira 在 👋│welcome 留下的全部消息（不动自己的面板）。

幂等：跑几次都只删 Zira 的；面板消息 id 显式排除。
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
CH = "1567439472151494747"          # 👋│welcome
ZIRA = "275813801792634880"
PANEL = "1568549337145942168"


def call(path, method="GET"):
    req = urllib.request.Request(API + path, method=method, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]


# 收集全部 Zira 消息（分页，最多 5 页）
targets, before = [], None
for _ in range(5):
    q = "/channels/%s/messages?limit=100" % CH + ("&before=" + before if before else "")
    st, msgs = call(q)
    if st != 200 or not isinstance(msgs, list) or not msgs:
        break
    for m in msgs:
        if m["author"]["id"] == ZIRA and m["id"] != PANEL:
            targets.append(m["id"])
    before = msgs[-1]["id"]
    if len(msgs) < 100:
        break

print("待删除 Zira 消息 =", len(targets))
ok = fail = 0
for mid in targets:
    st, body = call("/channels/%s/messages/%s" % (CH, mid), "DELETE")
    if st in (200, 204):
        ok += 1
    else:
        fail += 1
        print("  失败", mid, st, body)
    time.sleep(0.25)

print("删除成功 = %d  失败 = %d" % (ok, fail))

st, msgs = call("/channels/%s/messages?limit=100" % CH)
if st == 200:
    left_z = [m for m in msgs if m["author"]["id"] == ZIRA]
    panel = [m for m in msgs if m["id"] == PANEL]
    print("读回：频道消息 %d 条 | Zira 残留 %d | 面板在 = %s"
          % (len(msgs), len(left_z), bool(panel)))

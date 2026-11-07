# -*- coding: utf-8 -*-
"""复核：所有用户可见文案是否含中文字符（CI 化用，随时可跑）。

口径：扫描四个常驻面板消息的 content / embeds / components。
注意 `日本語` 这类日语汉字会落在同一个 Unicode 区段里，是**误报**，
脚本会把命中字符原样打出来，人工判断即可。
用法：python _check_no_cjk.py
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff01-\uff60]")

CHANNELS = [
    ("rules", "1567714666891976817"),
    ("welcome", "1567439472151494747"),
    ("gold-price", "1568557228733104129"),
    ("giveaway", "1567716869429796865"),
]


def api(path):
    for i in range(3):
        try:
            req = urllib.request.Request(API + path, headers={
                "Authorization": "Bot " + TOKEN,
                "User-Agent": "DiscordBot (mmoexp-ops, 1.0)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:200]
        except Exception as e:                                # noqa: BLE001
            if i == 2:
                return -1, repr(e)
            time.sleep(2)


def main():
    total = 0
    for name, cid in CHANNELS:
        st, msgs = api("/channels/%s/messages?limit=10" % cid)
        if st != 200:
            print("%-12s ERR %s" % (name, st))
            continue
        for m in msgs:
            blob = json.dumps({"content": m.get("content"),
                               "embeds": m.get("embeds"),
                               "components": m.get("components")},
                              ensure_ascii=False)
            hits = CJK.findall(blob)
            total += len(hits)
            if hits:
                print("%-12s %s CJK=%d %r" % (name, m["id"], len(hits),
                                              "".join(sorted(set(hits)))))
            else:
                print("%-12s %s clean" % (name, m["id"]))
    print("\n合计命中字符 =", total)
    return 0 if total == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

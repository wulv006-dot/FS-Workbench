# -*- coding: utf-8 -*-
"""把两个特权意图打开，并重启服务；连接失败则自动回滚到 false。"""
import json
import subprocess
import sys

CFG = "/opt/wowforever-bot/config.json"


def write(members, msg):
    with open(CFG, "r", encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("intents", {})["members"] = members
    d["intents"]["message_content"] = msg
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("config intents -> members=%s message_content=%s" % (members, msg))


write(True, True)
subprocess.call(["systemctl", "restart", "wowforever-bot"])
out = subprocess.run("sleep 12; journalctl -u wowforever-bot -n 40 --no-pager",
                     shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
text = out.stdout.decode("utf-8", "replace")
if "PrivilegedIntentsRequired" in text:
    print("!! 仍被拒，回滚到 false")
    write(False, False)
    subprocess.call(["systemctl", "restart", "wowforever-bot"])
    sys.exit(2)
tail = [l for l in text.splitlines() if any(k in l for k in
        ("特权意图", "已登录", "面板", "connected to Gateway", "ERROR", "Traceback"))]
print("\n".join(tail[-10:]))
st = subprocess.run(["systemctl", "is-active", "wowforever-bot"],
                    stdout=subprocess.PIPE).stdout.decode().strip()
print("is-active =", st)

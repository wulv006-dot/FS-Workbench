# -*- coding: utf-8 -*-
"""【跑在 183】把最新一份「魔兽金币台账」原样打到 stdout。

为什么要这个中转脚本：台账文件名带中文，直接在 ssh 命令行里 glob 会因为
本地/远端 shell 双重解析出乱码。让远端 Python 自己找文件，命令行里就没有中文。
"""
import glob
import json
import sys

files = [f for f in glob.glob("/opt/d4follow/output/*\u53f0\u8d26_*.json")
         if "\u9b54\u517d" in f]
if not files:
    sys.stderr.write("no wow ledger found\n")
    sys.exit(3)

files.sort(key=lambda p: p.split("_")[-2:])
newest = files[-1]
d = json.load(open(newest, encoding="utf-8"))
out = {
    "ledger": newest.rsplit("/", 1)[-1],
    "ts": d.get("ts"),
    "gid": d.get("gid"),
    "fx": d.get("汇率"),
    "plan": d.get("plan") or [],
}
sys.stdout.write(json.dumps(out, ensure_ascii=False))

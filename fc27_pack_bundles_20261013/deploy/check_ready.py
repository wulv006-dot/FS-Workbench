#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看各包的写价就绪状态（只读）。"""
import json
import urllib.request

d = json.loads(urllib.request.urlopen("http://127.0.0.1:8904/api/state").read())
print("revision:", d["revision"])
for b in d["bundles"]:
    ps = b.get("ps") or {}
    pc = b.get("pc") or {}
    prods = b.get("products") or {}
    print("%-32s 球员 %2d | 绑定 %d 平台 | PS %s/%s PC %s/%s" % (
        b["id"], len(b["players"]), len(prods),
        ps.get("players_counted"), ps.get("players_expected"),
        pc.get("players_counted"), pc.get("players_expected")))

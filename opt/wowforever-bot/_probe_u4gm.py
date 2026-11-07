# -*- coding: utf-8 -*-
"""单例排查：U4GM2026 为什么没命中。"""
import json
import re
import sys

sys.path.insert(0, "/opt/wowforever-bot")
from modules.guard import classify, norm, squash  # noqa: E402

cfg = json.load(open("/opt/wowforever-bot/config.json", encoding="utf-8"))
brands = cfg["features"]["guard"]["brandList"]
u = next(b for b in brands if b["label"] == "U4GM")

name = "U4GM2026"
sq = squash(norm(name))
core_s = squash(norm(u["core"]))
pat = u.get("pattern") or ("^(?:the)?(?:%s)([a-z0-9]*)$" % re.escape(core_s))
print("brand     :", {k: v for k, v in u.items() if not k.startswith("_")})
print("norm(name):", repr(norm(name)))
print("squash    :", repr(sq))
print("core_s    :", repr(core_s))
print("pattern   :", pat)
print("re.match  :", re.match(pat, sq, re.I))
print("classify  :", classify(name, brands))
print()
for probe in ["U4GM2026", "U4GM", "u4gm88", "IGGM2026", "LOOTBAR2026"]:
    print("  %-12s -> %s" % (probe, classify(probe, brands)))

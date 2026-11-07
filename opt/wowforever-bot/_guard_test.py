# -*- coding: utf-8 -*-
"""守卫分类器交叉验证：拿原有 112 条语料跑一遍 Python 移植版。"""
import json
import sys

sys.path.insert(0, "/opt/wowforever-bot")
from modules.guard import classify  # noqa: E402

cfg = json.load(open("/opt/wowforever-bot/config.json", encoding="utf-8"))
brands = cfg["features"]["guard"]["brandList"]
names = json.load(open("/tmp/guard_corpus.json", encoding="utf-8"))

hits, miss = [], []
for n in names:
    h = classify(n, brands)
    (hits if h else miss).append((n, h))

print("语料 %d 条 → 命中 %d / 放行 %d\n" % (len(names), len(hits), len(miss)))
print("=== 命中（会被 ban）===")
for n, h in hits:
    print("  %-28s %-9s %-12s tail=%r" % (n, h["brand"], h["via"], h.get("tail", "")))
print("\n=== 放行 ===")
for n, _ in miss:
    print("  %s" % n)

# 必须命中的硬断言（冒充形态）
MUST_HIT = ["MMOEXP", "mmoexp", "MmoExp", "MMOEXP Support", "MMOEXP_Official",
            "MMOEXP-CS", "nick.mmoexp", "service_mmoex", "MM0EXP",
            "\u041c\u041c\u041e\u0415\u0425\u0420", "\uff2d\uff2d\uff2f\uff25\uff38\uff30",
            "U4GM", "iggm", "LootBar"]
# 必须放行的（正常玩家名）
MUST_PASS = ["Bob", "Thrall", "ShadowMage", "wowplayer2026", "Gandalf", "xX_Arthas_Xx"]

print("\n=== 硬断言 ===")
bad = 0
for n in MUST_HIT:
    if not classify(n, brands):
        print("  [FAIL] 应命中却放行:", repr(n))
        bad += 1
for n in MUST_PASS:
    h = classify(n, brands)
    if h:
        print("  [FAIL] 应放行却命中:", repr(n), "->", h)
        bad += 1
print("断言失败 %d 项" % bad)
print("GUARD TEST " + ("OK" if bad == 0 else "FAILED"))

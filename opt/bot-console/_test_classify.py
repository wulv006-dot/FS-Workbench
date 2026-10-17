#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交叉验证：Python 版 classify 是否与 Node 版 index.js 行为一致。
   用例与 D:\\...\\_test_match.js 完全相同（37 条）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import classify, canon, squash, DEFAULT_BRAND_PATTERN  # noqa: E402

CFG = {"matchMode": "strict", "brandPattern": DEFAULT_BRAND_PATTERN, "extraStartsWith": []}

POSITIVE = [
    "MMOEXP", "mmoexp", "MmoExp",
    "MMOEXP Support", "MMOEXP_Official", "MMOEXP-CS", "MMOEXP | Store",
    "MMOEXP01", "mmoexp_88", "mmoEXP.team",
    "MM0EXP", "MMOOEXP", "mmo0exp",
    "\uFF2D\uFF2D\uFF2F\uFF25\uFF38\uFF30",          # ＭＭＯＥＸＰ 全角
    "\u041C\u041C\u041E\u0415\u0425\u0420",          # ММОЕХР 西里尔
    "MMO E X P", "m.m.o.e.x.p",
    "The MMOEXP", "mmoexpbot", "MMOEXP-gift", "mmoexp official",
    "MMO\u200BEXP",
]

NEGATIVE = [
    "mmoexpert", "mmoexpo", "mmoex", "moexp",
    "John", "Support", "Mike", "Nicholas",
    "MMO Player", "WoW Gold Seller", "Cheap Diablo 4 Gold",
    "official support", "mmo exp lover",
    "MMOEXPfan2026_play",
]

pass_n = fail_n = 0
print("配置：matchMode=%s\n" % CFG["matchMode"])
print("===== 应该命中（冒充） =====")
for n in POSITIVE:
    r = classify(n, CFG)
    ok = bool(r) and not (r or {}).get("error")
    pass_n += 1 if ok else 0
    fail_n += 0 if ok else 1
    shown = json.dumps(n, ensure_ascii=False) if False else repr(n)
    print("%s  %-28s -> %s" % (
        "PASS" if ok else "FAIL", shown,
        ('命中 tail="%s" via=%s' % (r["tail"], r["via"])) if ok else "未命中 ❌",
    ))

print("\n===== 不应命中（正常） =====")
for n in NEGATIVE:
    r = classify(n, CFG)
    ok = not r
    pass_n += 1 if ok else 0
    fail_n += 0 if ok else 1
    print("%s  %-28s -> %s" % (
        "PASS" if ok else "FAIL", repr(n),
        "放行" if ok else '误伤 ❌ tail="%s" via=%s' % (r.get("tail"), r.get("via")),
    ))

print("\n===== 归一化抽查 =====")
for raw in ["MMO\u200BEXP", "\u041C\u041C\u041E\u0415\u0425\u0420", "\uFF2D\uFF2D\uFF2F\uFF25\uFF38\uFF30",
            "M.m.O e X-p"]:
    print("  %-30s -> canon=%-14s squash=%s" % (repr(raw), canon(raw), squash(canon(raw))))

print("\n===== 汇总：通过 %d / 失败 %d =====" % (pass_n, fail_n))
sys.exit(0 if fail_n == 0 else 1)

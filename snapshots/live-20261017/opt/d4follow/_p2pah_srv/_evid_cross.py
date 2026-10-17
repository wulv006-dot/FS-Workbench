# -*- coding: utf-8 -*-
"""取证 3：D4 全量「多向装量交叉校验」。只读。

五向：
  K = key 名后缀数字（如 _X10 → 10；无后缀 → None）
  C = 对照项.装量
  B = 后台商品名 title 的装量前缀（如 (100) Lair Key → 100）
  I = iggm.title 里的数量（如 "Lair Key * 10" → 10）
  Q = 千岛.刻度
"""
import io
import json
import re

CFG = "/opt/d4follow/config.json"
ITEMS = "/opt/d4follow/data/backend_items.json"
D4 = "暗黑破坏神4"


def qty_of(s):
    """从任意字符串里抽装量：'(100) X' / 'X * 100' / 'X ✕100' / 'X100'。"""
    s = str(s or "").strip()
    if not s:
        return None
    m = re.match(r"^\s*\(\s*(\d{1,7})\s*\)", s)
    if m:
        return int(m.group(1))
    m = re.search(r"[*✕✖xX×]\s*(\d{1,7})\s*$", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,7})\s*$", s)
    if m:
        return int(m.group(1))
    return None


def ksuf(k):
    m = re.search(r"[_xX](\d{1,7})$", str(k or ""))
    return int(m.group(1)) if m else None


def main():
    cfg = json.load(io.open(CFG, encoding="utf-8"))
    p = cfg.get("p2pah") or {}
    idmap = p.get("商品ID映射") or {}
    items = (cfg.get("商品映射") or {}).get("对照项") or []
    b = json.load(io.open(ITEMS, encoding="utf-8"))
    byid = {str(r.get("id")): r for r in (b.get("rows") or [])}

    print("=== D4 多向装量交叉校验 ===")
    print("%-32s %-5s %-5s %-5s %-6s %-5s %s" % (
        "KEY", "K", "C装量", "B后台", "I_IGGM", "Q千岛", "判定"))
    nbad = 0
    bads = []
    for it in items:
        if it.get("游戏") != D4:
            continue
        k = str(it.get("key") or "")
        pid = str(idmap.get(k) or "").strip()
        r = byid.get(pid) or {}
        K = ksuf(k)
        C = it.get("装量") or (it.get("p2pah") or {}).get("装量")
        try:
            C = int(C) if C not in (None, "") else None
        except (TypeError, ValueError):
            C = None
        B = qty_of(r.get("title")) if r else None
        I = qty_of((it.get("iggm") or {}).get("title"))
        Q = (it.get("千岛") or {}).get("刻度")
        try:
            Q = int(Q) if Q not in (None, "") else None
        except (TypeError, ValueError):
            Q = None

        # 判定：以「引擎实际会写价的后台产品装量 B」为基准
        # 若 I（竞品价来源的装量）与 B 不同 ⇒ 价格必然错位（拿 A 装的价写 B 装的行）
        flags = []
        if B is not None and I is not None and B != I:
            flags.append("❗IGGM装量%s≠后台%s(价错位)" % (I, B))
        if C is not None and B is not None and C != B:
            flags.append("⚠配置装量%s≠后台%s" % (C, B))
        if K is not None and B is not None and K != B:
            flags.append("✳key后缀%s≠后台%s" % (K, B))
        if Q is not None and B is not None and Q != B:
            flags.append("·千岛刻度%s≠后台%s" % (Q, B))
        if flags:
            nbad += 1
            bads.append((k, K, C, B, I, Q, flags, r.get("title"), (it.get("iggm") or {}).get("title")))
            print("%-32s %-5s %-5s %-5s %-6s %-5s %s" % (
                k, K, C, B, I, Q, " ｜ ".join(flags)))
    print()
    print("有疑点 %d 项 / D4 共 %d 项" % (nbad, sum(1 for it in items if it.get("游戏") == D4)))

    print()
    print("=== 疑点明细 ===")
    for (k, K, C, B, I, Q, flags, bt, it_t) in bads:
        print("-" * 70)
        print("KEY=%s" % k)
        print("   key后缀=%s 配置装量=%s 后台装量=%s" % (K, C, B))
        print("   后台 title = %s" % bt)
        print("   IGGM title = %s" % it_t)
        print("   千岛刻度   = %s" % Q)
        print("   判定: %s" % " ｜ ".join(flags))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""取证：D4 登记项 key 名 vs 配置装量 vs 后台真实装量 vs 后台价格。

用户反馈要点：
  1) 平台现在卖的钥匙是 100 / 1000 装的，系统没跟上
  2) x10 的前端已下架
  3) key 名带 X10/X100 不代表产品装量 —— 之前把 x10 改成了 x100/x1000，
     产品 ID 没变、只是名字变了，但后台 key 名还写 x10 ⇒ 价格错位

本脚本只读。输出：
  A. 对照项字段全集
  B. 全部 D4 项：key / 中文名 / 装量 / 商品名关键词 / 后台ID / 后台title / 后台qty / 单价
  C. 错位清单：key 名后缀(Q) vs 配置装量(C) vs 后台装量(B) 三者不一致
"""
import io
import json
import re
import sys

CFG = "/opt/d4follow/config.json"
ITEMS = "/opt/d4follow/data/backend_items.json"
D4 = "暗黑破坏神4"


def main():
    cfg = json.load(io.open(CFG, encoding="utf-8"))
    p = cfg.get("p2pah") or {}
    idmap = p.get("商品ID映射") or {}
    items = (cfg.get("商品映射") or {}).get("对照项") or []
    b = json.load(io.open(ITEMS, encoding="utf-8"))
    byid = {str(r.get("id")): r for r in (b.get("rows") or [])}

    d4 = [it for it in items if it.get("游戏") == D4]

    # ── A. 字段全集 + 样本 ────────────────────────────────────────────
    fs = set()
    for it in d4:
        fs |= set(it.keys())
    print("=== A. D4 对照项字段全集 ===")
    print(sorted(fs))
    print()
    print("=== A2. 一个完整样本 ===")
    print(json.dumps(d4[0], ensure_ascii=False, indent=1))
    print()

    # ── B. 全量清单 ──────────────────────────────────────────────────
    print("=== B. D4 全部 %d 项（key 后缀 / 配置装量 / 后台装量 / 单价）===" % len(d4))
    print("%-34s %-8s %-6s %-6s %-10s %-10s %s" % (
        "KEY", "中文名", "CfgQty", "BkQty", "单价字段?", "后台单价", "后台title"))
    rows = []
    for it in d4:
        k = str(it.get("key") or "")
        pid = str(idmap.get(k) or "").strip()
        r = byid.get(pid) or {}
        t = str(r.get("title") or "")
        m = re.match(r"^\s*\(\s*(\d+)\s*\)", t)
        bq = int(m.group(1)) if m else None
        cq = it.get("装量")
        up = r.get("unit_price")
        sp = r.get("sale_price")
        rows.append((k, it, pid, r, cq, bq))
        print("%-34s %-8s %-6s %-6s %-10s %-10s %s" % (
            k, str(it.get("中文名") or "")[:8], cq, bq, "",
            up if up is not None else sp, t[:60]))

    # ── C. 错位分析 ──────────────────────────────────────────────────
    print()
    print("=== C. 错位：key 名后缀 vs 配置装量 vs 后台装量 ===")

    def ksuf(k):
        m = re.search(r"[_xX](\d{1,6})$", k)
        return int(m.group(1)) if m else None

    bad = []
    for (k, it, pid, r, cq, bq) in rows:
        q = ksuf(k)
        # 三项里至少两项有值才判
        vals = [x for x in (q, cq, bq) if x not in (None, "")]
        try:
            cq_i = int(cq) if cq not in (None, "") else None
        except (TypeError, ValueError):
            cq_i = None
        if q is None and cq_i is None:
            continue
        # 不一致判定：key 后缀 与 后台装量 不同（且都已知）
        flag = []
        if q is not None and bq is not None and q != bq:
            flag.append("key后缀%s≠后台%s" % (q, bq))
        if cq_i is not None and bq is not None and cq_i != bq:
            flag.append("配置装量%s≠后台%s" % (cq_i, bq))
        if q is not None and cq_i is not None and q != cq_i:
            flag.append("key后缀%s≠配置装量%s" % (q, cq_i))
        if flag:
            bad.append((k, pid, r.get("title"), flag))

    print("错位 %d 项：" % len(bad))
    for k, pid, t, f in bad:
        print("  · %-34s id=%-11s %s" % (k, pid, " ｜ ".join(f)))
        print("      后台: %s" % t)

    # ── D. 按 key 基名分组，看同族装量分布 ────────────────────────────
    print()
    print("=== D. 同族（去掉 _X\d+ / _X\d+后缀）装量分布 ===")
    groups = {}
    for (k, it, pid, r, cq, bq) in rows:
        base = re.sub(r"[_xX]\d{1,6}$", "", k)
        groups.setdefault(base, []).append((k, cq, bq, r.get("title")))
    for base in sorted(groups):
        g = groups[base]
        if len(g) == 1 and g[0][2] is None:
            continue
        print("  %-32s" % base)
        for k, cq, bq, t in g:
            print("       %-34s 配置=%-5s 后台=%-5s %s" % (k, cq, bq, (t or "")[:52]))


if __name__ == "__main__":
    main()

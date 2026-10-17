# -*- coding: utf-8 -*-
"""取证 2：钥匙族完整登记 + 价格来源 + 引擎定价链路。只读。"""
import io
import json

CFG = "/opt/d4follow/config.json"
ITEMS = "/opt/d4follow/data/backend_items.json"
D4 = "暗黑破坏神4"

FAM = ("LAIR_KEY", "GREATER_LAIR_KEY", "SUPERIOR_LAIR_KEY", "CRUX",
       "CORRUPTED_ROOTS")


def main():
    cfg = json.load(io.open(CFG, encoding="utf-8"))
    p = cfg.get("p2pah") or {}
    idmap = p.get("商品ID映射") or {}
    items = (cfg.get("商品映射") or {}).get("对照项") or []
    b = json.load(io.open(ITEMS, encoding="utf-8"))
    byid = {str(r.get("id")): r for r in (b.get("rows") or [])}

    print("=== 1. 钥匙族完整登记 ===")
    for it in items:
        if it.get("游戏") != D4:
            continue
        k = str(it.get("key") or "")
        if not any(k.startswith(f) for f in FAM):
            continue
        pid = str(idmap.get(k) or "")
        r = byid.get(pid) or {}
        print("-" * 78)
        print("KEY = %s    后台ID = %s" % (k, pid))
        print(json.dumps(it, ensure_ascii=False, indent=1)[:1500])
        print("  后台行: %s" % json.dumps(
            {kk: r.get(kk) for kk in sorted(r.keys())}, ensure_ascii=False)[:600])

    print()
    print("=== 2. 后台行的完整字段（一行样本）===")
    if byid:
        any_r = list(byid.values())[0]
        print(json.dumps(any_r, ensure_ascii=False, indent=1)[:2000])

    print()
    print("=== 3. config 顶层结构 ===")
    print("顶层键:", list(cfg.keys()))
    for k in cfg:
        v = cfg[k]
        if isinstance(v, dict):
            print("  %-12s dict keys=%s" % (k, list(v.keys())[:14]))
        elif isinstance(v, list):
            print("  %-12s list len=%d" % (k, len(v)))
        else:
            print("  %-12s %r" % (k, v))

    print()
    print("=== 4. 跟价 配置 ===")
    print(json.dumps(cfg.get("跟价"), ensure_ascii=False, indent=1)[:4000])

    print()
    print("=== 5. p2pah 顶层（除映射/游戏）===")
    for k in p:
        if k in ("商品ID映射", "游戏"):
            continue
        print("  %s = %s" % (k, json.dumps(p[k], ensure_ascii=False)[:900]))


if __name__ == "__main__":
    main()

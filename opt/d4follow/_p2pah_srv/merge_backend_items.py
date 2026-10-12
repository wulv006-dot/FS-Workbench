# -*- coding: utf-8 -*-
"""合并后台清单：保留旧的非 D4 行 + 用按类目新抓的 D4 行整体替换，并做**闸一预演**。

背景（2026-10-08）
-----------------
D4 物品改价 359 档连续 3 天全量报「后台已找不到 ID 169xxxxxx（可能被你删了）」。
真因不是商品被删/重建，而是**清单抓取被分页上限截断**：
  · 本机 `fetch_backend_items_pw3.py --pages 30`
  · 容器 `p2pah_local.read_all_pages(max_pages=40)`
D4 后台实际 333~335 页 ≈ 6.7 万件，登记的老 ID（169xxxxxx / 170xxxxxx / 180374xxx）
散在第 31~335 页 ⇒ 旧清单只含最新约 10%（1843/1844 段）⇒ 闸一判 id_gone。

本脚本把旧清单里 D4 那 5956 行整体换成按类目抓到的 436 行（覆盖全部 359 个登记键，
命中率 100%），其余游戏（POE2 / ARC Raiders / Aion 2 / Dark and Darker / WARDOGS /
WoW Forever）原样保留。

字段映射（dump → backend_items.json）
------------------------------------
  id          ← id
  title       ← name
  qty         ← per
  game        ← 固定 "Diablo 4"
  zone        ← area
  category    ← ptype
  unit_price  ← unit_price
  discount    ← discount
  sale_price  ← unit_price × discount/100（旧清单里折扣 100 时与 unit_price 相等）
  retail_price← None（新抓的列表页面不带原价列）
  _idx        ← 4（旧格式固定值，title 所在列序号）
  _orig_name  ← "Diablo 4"
  cid / cat   ← 新增，便于写价路径按类目定位

用法
----
  python3 merge_backend_items.py \
      --old /opt/d4follow/data/backend_items.json \
      --d4  /opt/d4follow/_p2pah_srv/_d4_sel.json \
      --dst /tmp/backend_items.new.json \
      [--cfg /opt/d4follow/config.json] [--apply-gate]
"""
import argparse
import collections
import io
import json
import os
import sys

D4_NAMES = ("Diablo 4", "D4")


def load(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="/opt/d4follow/data/backend_items.json")
    ap.add_argument("--d4", default="/opt/d4follow/_p2pah_srv/_d4_sel.json")
    ap.add_argument("--dst", default="/tmp/backend_items.new.json")
    ap.add_argument("--cfg", default="/opt/d4follow/config.json")
    ap.add_argument("--apply-gate", action="store_true",
                    help="合并后跑一遍闸一 detect_binding_drift 做验收")
    a = ap.parse_args()

    old = load(a.old)
    dump = load(a.d4)

    old_rows = old["rows"] if isinstance(old, dict) else old
    keep = [r for r in old_rows if str(r.get("game") or "") not in D4_NAMES]
    old_d4 = [r for r in old_rows if str(r.get("game") or "") in D4_NAMES]

    new_d4 = []
    for r in dump["rows"]:
        up = r.get("unit_price")
        disc = r.get("discount")
        sp = up
        try:
            if up is not None and disc is not None:
                sp = round(float(up) * float(disc) / 100.0, 5)
        except (TypeError, ValueError):
            sp = up
        new_d4.append({
            "id": str(r.get("id") or "").strip(),
            "title": (r.get("name") or "").strip(),
            "qty": str(r.get("per") or "1"),
            "game": "Diablo 4",
            "zone": (r.get("area") or "").strip(),
            "category": (r.get("ptype") or "").strip(),
            "unit_price": up,
            "discount": disc,
            "sale_price": sp,
            "retail_price": None,
            "_idx": 4,
            "_orig_name": "Diablo 4",
            "cid": str(r.get("cid") or ""),
            "cat": r.get("cat") or "",
        })

    rows = keep + new_d4
    games = sorted(set([str(r.get("game") or "") for r in rows if r.get("game")]))
    out = {
        "saved_at": dump.get("saved_at"),
        "source": ("_dump_by_cat.py 按类目抓 D4（gid=456/aid=15711，只抓登记类目）"
                   " + merge_backend_items.py 合并"),
        "count": len(rows),
        "games": games,
        "rows": rows,
    }
    if isinstance(old, dict):
        out["merged_from"] = old.get("source")

    with io.open(a.dst, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False))

    print("旧清单：总 %d 行 ｜ D4 %d 行 ｜ 非D4 %d 行"
          % (len(old_rows), len(old_d4), len(keep)))
    print("新清单：总 %d 行 ｜ D4 %d 行（替换）｜ 非D4 %d 行（保留）"
          % (len(rows), len(new_d4), len(keep)))
    print("D4 新行按类目：%s"
          % collections.Counter(r["cid"] for r in new_d4).most_common())
    print("已写 %s（%.1f KB）" % (a.dst, os.path.getsize(a.dst) / 1024.0))

    # ── 登记键命中率（对全部 1042 个键，不只 D4）──
    try:
        cfg = load(a.cfg)
        idmap = ((cfg.get("p2pah") or {}).get("商品ID映射") or {})
        want = {k: str(v or "").strip() for k, v in idmap.items()
                if not str(k).startswith("_")}
        have = set(str(r.get("id") or "").strip() for r in rows)
        miss = [k for k, i in want.items() if i and i not in have]
        print("商品ID映射 %d 个键：命中 %d ｜ 未命中 %d"
              % (len(want), len(want) - len(miss), len(miss)))
        if miss:
            for k in miss[:30]:
                print("   · %-40s id=%s" % (k, want[k]))

        # ── 闸一预演（最硬验收）──
        if a.apply_gate:
            sys.path.insert(0, os.path.dirname(os.path.abspath(a.cfg)))
            import gates                                    # noqa: E402
            drifts, checked = gates.detect_binding_drift(cfg, rows)
            print("")
            print("🔒 闸一预演：核对 %d 档，漂移 %d 处" % (checked, len(drifts)))
            lv = collections.Counter(d["level"] for d in drifts)
            for k, n in lv.most_common():
                print("     %-14s %d" % (k, n))
            d4keys = set()
            for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
                k = it.get("key")
                if not k:
                    continue
                if str(it.get("游戏") or "") == "暗黑破坏神4":
                    d4keys.add(k)
            d4_drifts = [d for d in drifts if d["key"] in d4keys]
            print("     其中 D4（游戏=暗黑破坏神4）漂移：%d 处" % len(d4_drifts))
            for d in drifts[:25]:
                print("        · [%s] %s" % (d["key"], d["msg"]))
    except Exception as e:                                  # noqa: BLE001
        print("⚠ 命中率/闸一预演失败：%r" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())

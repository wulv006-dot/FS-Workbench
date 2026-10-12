# -*- coding: utf-8 -*-
"""从后台清单生成「后台商品ID → 产品类目 cid」映射，供写价路径按类目定位。

为什么需要（2026-10-08）
-----------------------
D4 赛季普通（gid=456）全量列表 335 页 ≈ 6.7 万件。写价时 `fetch_all_needed` 对
「> KEYWORD_SEARCH_MAX(40) 个 key」的 gid 跳过逐条关键词搜索、直接翻全量兜底，
而全量兜底被 `max_pages=40` 封顶 ⇒ 登记在第 31~335 页的深页档位永远找不到 ⇒
「写后复核」判不一致、工单失败。按类目读（每个类目 1~2 页）就绕开了。

产物格式（p2pah_local.load_cid_map 读这个）
------------------------------------------
  {
    "saved_at": "...",
    "source": "...",
    "games": {
      "456": {"aid": "15711", "id2cid": {"169686015": "2371", ...}}
    }
  }

用法
----
  python3 build_cid_map.py \
      --items /opt/d4follow/data/backend_items.json \
      --dst   /opt/d4follow/_p2pah_srv/item_cid.json \
      [--gid 456] [--aid 15711]
"""
import argparse
import io
import json
import os
import time

GAME_GID = {"Diablo 4": "456", "D4": "456"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="/opt/d4follow/data/backend_items.json")
    ap.add_argument("--dst", default="/opt/d4follow/_p2pah_srv/item_cid.json")
    ap.add_argument("--gid", default="456")
    ap.add_argument("--aid", default="15711")
    a = ap.parse_args()

    with io.open(a.items, encoding="utf-8") as f:
        j = json.load(f)
    rows = j.get("rows") if isinstance(j, dict) else j
    rows = rows or []

    id2cid = {}
    skipped = 0
    for r in rows:
        if str(r.get("game") or "") not in GAME_GID:
            continue
        if str(GAME_GID[str(r.get("game"))]) != str(a.gid):
            continue
        rid = str(r.get("id") or "").strip()
        cid = str(r.get("cid") or "").strip()
        if rid and cid:
            id2cid[rid] = cid
        elif rid:
            skipped += 1

    out = {
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "build_cid_map.py ← backend_items.json（cid 来自 _dump_by_cat.py）",
        "games": {str(a.gid): {"aid": str(a.aid), "id2cid": id2cid}},
    }
    tmp = a.dst + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=1))
    os.replace(tmp, a.dst)

    print("gid=%s aid=%s：id→cid %d 条 ｜ 无 cid 被跳过 %d 条" % (a.gid, a.aid, len(id2cid), skipped))
    per = {}
    for _i, c in id2cid.items():
        per[c] = per.get(c, 0) + 1
    print("按类目分布：%s" % sorted(per.items(), key=lambda kv: -kv[1]))
    print("已写 %s（%.1f KB）" % (a.dst, os.path.getsize(a.dst) / 1024.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

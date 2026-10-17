# -*- coding: utf-8 -*-
"""只读对照探针：模型 ↔ 关联产品 的关系。

目的：回答"add 建的模型 0 关联产品，是否正常"。
方法：抽样对比 FC27 / MLB26 已有模型，看它们的 /admin/goods.Goods/index?search[mid]=
      是否真的挂得上产品；并测 FC 导入产生的模型是否有产品。

⛔ 全程只读（GET），不发任何 POST。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient  # noqa: E402

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

out = {}


def products_of(mid):
    """按 mid 查关联产品（分页全取）。"""
    rows = []
    page = 1
    total = None
    while True:
        d = c._json("GET", "/admin/goods.Goods/index",
                    params={"page": page, "limit": 100, "order": "id,desc",
                            "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
        data = d.get("data") or {}
        lst = data.get("list") or []
        total = data.get("total")
        rows.extend(lst)
        if not lst or len(rows) >= int(total or 0) or page > 5:
            break
        page += 1
    return total, rows


def sample_models(gid, cid, n=6):
    d = c.list_models(gid=gid, cid=cid, page=1, limit=n)
    return d.get("total"), (d.get("list") or [])[:n]


for tag, gid, cid in [("MLB26", 927, 8233), ("FC27", 1327, 9627)]:
    print("\n" + "=" * 60, flush=True)
    print("[%s] gid=%s cid=%s" % (tag, gid, cid), flush=True)
    total, rows = sample_models(gid, cid, 6)
    print("  模型总数:", total, flush=True)
    rec = {"gid": gid, "cid": cid, "model_total": total, "samples": []}
    for r in rows:
        mid = r.get("id")
        ptotal, prows = products_of(mid)
        sites = sorted({str(p.get("site_id")) for p in prows})
        print("   mid=%s  产品数=%s  site_ids=%s  title=%s"
              % (mid, ptotal, sites, (r.get("title") or "")[:52]), flush=True)
        rec["samples"].append({
            "mid": mid, "title": r.get("title"),
            "price": r.get("price"), "is_put": r.get("is_put"),
            "product_total": ptotal,
            "site_ids": sites,
            "products": [{k: p.get(k) for k in ("id", "site_id", "aid", "price", "status", "title")}
                         for p in prows[:12]],
        })
    out[tag] = rec

# 特别关注：刚写的 Dennis Eckersley
print("\n" + "=" * 60, flush=True)
print("[NEW] Dennis Eckersley mid=44638327", flush=True)
pt, prs = products_of(44638327)
print("  产品数:", pt, flush=True)
out["new_card"] = {"mid": 44638327, "product_total": pt,
                   "products": [{k: p.get(k) for k in ("id", "site_id", "aid", "price", "status")}
                                for p in prs[:12]]}

(HERE / "_probe_product_parity.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写入 _probe_product_parity.json", flush=True)

# -*- coding: utf-8 -*-
"""只读探针：拿 shelves 所需的 site_ids / aids 全量清单。

来源：GET /admin/goods.GoodsMould/add 的 data.siteConfig / gameAreaConfig
     （popupForm 里 oe(1)=all_site_ids、oe(2)=all_aids 就是从这里取）
另外：GET /edit?id=<MLB模型> 的 form.extend 也带这两份配置。

⛔ 全程 GET，不发 POST。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient  # noqa: E402

cred = json.loads((_cred := (HERE / "_cred.json")).read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

out = {}

print("=== GET /admin/goods.GoodsMould/add ===", flush=True)
form = c._json("GET", "/admin/goods.GoodsMould/add")
data = form.get("data") or {}
print("  data 顶层键:", sorted(data.keys()), flush=True)
for k in ("siteConfig", "gameAreaConfig", "displayDuration"):
    v = data.get(k)
    if isinstance(v, list):
        print("  %s: list[%d]" % (k, len(v)), flush=True)
        for item in v[:20]:
            print("     ", item, flush=True)
    else:
        print("  %s: %r" % (k, v), flush=True)
out["add_defaults"] = {k: data.get(k) for k in ("siteConfig", "gameAreaConfig", "displayDuration", "topCid")}

print("\n=== GET /admin/goods.GoodsMould/edit?id=44234597 (MLB 样板) ===", flush=True)
ed = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": 44234597})
edata = ed.get("data") or {}
print("  data 顶层键:", sorted(edata.keys()), flush=True)
for k in ("siteConfig", "gameAreaConfig", "displayDuration", "shelveGoods"):
    v = edata.get(k)
    if isinstance(v, list):
        print("  %s: list[%d]" % (k, len(v)), flush=True)
        for item in v[:25]:
            print("     ", item, flush=True)
    else:
        print("  %s: %r" % (k, str(v)[:200]), flush=True)
row = edata.get("row") or {}
print("\n  row._extend =", json.dumps(row.get("_extend"), ensure_ascii=False)[:800], flush=True)
print("  row.is_put =", row.get("is_put"), " status =", row.get("status"), flush=True)
out["edit_sample"] = {
    "siteConfig": edata.get("siteConfig"),
    "gameAreaConfig": edata.get("gameAreaConfig"),
    "shelveGoods": edata.get("shelveGoods"),
    "row_extend": row.get("_extend"),
    "row_is_put": row.get("is_put"),
}

(HERE / "_probe_shelves_contract.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写入 _probe_shelves_contract.json", flush=True)

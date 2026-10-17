# -*- coding: utf-8 -*-
"""给已有模型补产品：POST /admin/goods.GoodsMould/shelves。

参数来源：GET /edit?id=<mid> 的 data.row._extend（all_site_ids / all_aids）+ 模型当前 price/status。
body 结构照抄 popupForm.vue 的 xo() 函数。

⛔ 写操作只发一次，绝不自动重试；结果未知 → 立即停止人工核对。
⛔ 幂等前置：先查该 mid 已有产品数，>0 则跳过（避免重复建）。
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient, AdminUnknownResult  # noqa: E402

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

MID = 44638327
EXPECTED = 48
log = []


def products_of(mid):
    d = c._json("GET", "/admin/goods.Goods/index",
                params={"page": 1, "limit": 100, "order": "id,desc",
                        "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
    data = d.get("data") or {}
    return data.get("total"), (data.get("list") or [])


print("=== 0. 幂等检查：该模型现有产品 ===", flush=True)
before_total, before_rows = products_of(MID)
print("  mid=%s 现有产品数=%s" % (MID, before_total), flush=True)
log.append({"step": "before", "mid": MID, "products": before_total})
if int(before_total or 0) > 0:
    print("  ⚠️ 已有产品，跳过（幂等保护）", flush=True)
    (HERE / "_shelves_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0)

print("\n=== 1. GET /edit 取 site_ids / aids ===", flush=True)
ed = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": MID})
edata = ed.get("data") or {}
row = edata.get("row") or {}
ext = row.get("_extend") or {}
site_ids = ext.get("all_site_ids") or []
aids = ext.get("all_aids") or []
print("  site_ids(%d): %s" % (len(site_ids), site_ids), flush=True)
print("  aids(%d): %s" % (len(aids), aids), flush=True)
log.append({"step": "config", "site_ids": site_ids, "aids": aids})
if not site_ids or not aids:
    print("  [X] site_ids/aids 为空，中止", flush=True)
    raise SystemExit(1)

# ---- 2. 构造 shelves body（照抄 popupForm.vue 的 xo()）----
body = {
    "num": ext.get("num", 1),
    "min_qty": ext.get("min_qty", row.get("min_qty", 1)),
    "total": ext.get("total", 0),
    "discount": row.get("discount", 100),
    "price": row.get("price"),
    "status": str(row.get("status", 1)),
    "is_rec": str(row.get("is_rec", 0)),
    "duration": str(row.get("duration", 0)),
    "open_watermark": str(ext.get("open_watermark", 0)),
    "site_ids": site_ids,
    "aids": aids,
    "search": {"mids": MID},
}
print("\n=== 2. shelves body ===", flush=True)
print(" ", json.dumps(body, ensure_ascii=False), flush=True)
(HERE / "_shelves_body.json").write_text(
    json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n=== 3. POST /admin/goods.GoodsMould/shelves （写操作，仅一次）===", flush=True)
try:
    res = c._json("POST", "/admin/goods.GoodsMould/shelves", json_body=body)
    print("  返回:", json.dumps(res, ensure_ascii=False)[:500], flush=True)
    log.append({"step": "shelves", "result": res})
except AdminUnknownResult as e:
    print("  [X] 结果未知，停止，禁止重试:", e, flush=True)
    log.append({"step": "shelves", "unknown": str(e)})
    (HERE / "_shelves_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(2)
except Exception as e:
    print("  [X] 被拒/异常:", repr(e), flush=True)
    log.append({"step": "shelves", "error": repr(e)})
    (HERE / "_shelves_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(1)

time.sleep(4)
print("\n=== 4. 回读产品 ===", flush=True)
after_total, after_rows = products_of(MID)
print("  mid=%s 产品数=%s （预期 %s）" % (MID, after_total, EXPECTED), flush=True)
sites = sorted({str(r.get("site_id")) for r in after_rows})
aidset = sorted({str(r.get("aid")) for r in after_rows})
print("  site_ids(%d): %s" % (len(sites), sites), flush=True)
print("  aids(%d): %s" % (len(aidset), aidset), flush=True)
log.append({"step": "after", "products": after_total,
            "site_ids": sites, "aids": aidset,
            "sample": [{k: r.get(k) for k in ("id", "site_id", "aid", "price", "status")}
                       for r in after_rows[:6]]})

ok = int(after_total or 0) == EXPECTED
print("\n  结论:", "✅ 达标" if ok else "⚠️ 数量不符，需核对", flush=True)
log.append({"step": "verdict", "ok": ok})

(HERE / "_shelves_result.json").write_text(
    json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("已写入 _shelves_result.json", flush=True)

# -*- coding: utf-8 -*-
"""单卡试写：POST /admin/goods.GoodsMould/add（Dennis Eckersley）。

流程（严格按项目铁律）：
  1. 先 GET /add 拿表单默认结构
  2. 先 GET /edit?id=<一条已有MLB模型> 拿真实字段样板
  3. 构造 body（只含新增所需字段，gid=927/cid=8233）
  4. POST /add —— 写操作，只发一次，绝不自动重试
  5. 立即回读 /index 确认模型是否生成 + 是否带 3 平台关联产品
  6. 全量落盘证据

⛔ 若返回"未知结果"（网络异常）→ 立刻停止，人工核对，不重试。
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from admin_api_client import AdminApiClient, AdminUnknownResult, AdminHttpError

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

GID, CID = 927, 8233
TITLE = "Dennis Eckersley/99/CP/Athletics/Awards"
PRICE = 1.49
log = []


def snap(tag):
    """回读当前 MLB scope 模型总数 + 是否已含目标 title。"""
    found = None
    total = None
    page = 1
    while True:
        d = c.list_models(gid=GID, cid=CID, page=page, limit=200)
        total = d.get("total")
        for row in d.get("list") or []:
            if (row.get("title") or "").strip() == TITLE:
                found = row
        if not (d.get("list") or []) or page * 200 >= int(total or 0):
            break
        page += 1
        if page > 10:
            break
    print("  [%s] total=%s  found=%s" % (tag, total, bool(found)), flush=True)
    return total, found


print("=== 0. 写前基线 ===", flush=True)
before_total, before_found = snap("before")
log.append({"step": "before", "total": before_total, "found": bool(before_found)})

print("\n=== 1. GET /add 表单默认结构 ===", flush=True)
form = c._json("GET", "/admin/goods.GoodsMould/add")
default_row = (form.get("data") or {}).get("row") or {}
print("  默认字段:", sorted(default_row.keys()), flush=True)

print("\n=== 2. 取一条已有 MLB 模型做样板 ===", flush=True)
sample = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": 44234597})
srow = (sample.get("data") or {}).get("row") or {}
print("  样板字段:", sorted(srow.keys()), flush=True)

# ---- 3. 构造 body：只取新增必须的最小字段集 ----
body = {
    "gid": GID,
    "cid": CID,
    "top_cid": srow.get("top_cid", 0),
    "sid": srow.get("sid", 0),
    "aid": srow.get("aid", 0),
    "title": TITLE,
    "icon": 0,
    "pic": "",
    "price": PRICE,
    "discount": 100,
    "min_qty": 1,
    "receiving_price": 0,
    "sort": 1000,
    "status": "1",
    "is_put": "0",
    "is_hot": "0",
    "is_rec": "0",
    "is_code": "0",
    "auto_off": "0",
    "buy_status": 0,
    "attr_switch": "0",
    "sku_switch": "0",
    "partner": "",
    "summary": "",
    "desc": "",
    "duration": "0",
    "shelf_time": "0",
    "tid": "0",
    "more": {"extend": []},
    "_extend": {"site_ids": [], "aids": [], "duration": "0"},
}
(HERE / "_add_body.json").write_text(
    json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n=== 3. 待提交 body ===", flush=True)
print(json.dumps(body, ensure_ascii=False), flush=True)

print("\n=== 4. POST /add （写操作，仅一次）===", flush=True)
try:
    res = c._json("POST", "/admin/goods.GoodsMould/add", json_body=body)
    print("  返回:", json.dumps(res, ensure_ascii=False)[:600], flush=True)
    log.append({"step": "add", "result": res})
except AdminUnknownResult as e:
    print("  [X] 结果未知，停止，禁止重试:", e, flush=True)
    log.append({"step": "add", "unknown": str(e)})
    (HERE / "_add_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(2)
except Exception as e:
    print("  [X] 被拒/异常:", repr(e), flush=True)
    log.append({"step": "add", "error": repr(e)})
    (HERE / "_add_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(1)

time.sleep(3)
print("\n=== 5. 写后回读 ===", flush=True)
after_total, after_found = snap("after")
log.append({"step": "after", "total": after_total,
            "found": bool(after_found),
            "row": ({k: after_found.get(k) for k in
                     ("id", "title", "gid", "cid", "price", "is_put", "status")}
                    if after_found else None)})

if after_found:
    mid = after_found.get("id")
    print("\n=== 6. 查该模型的关联产品 ===", flush=True)
    try:
        prods = c._json("GET", "/admin/goods.Goods/index",
                        params={"page": 1, "limit": 50, "order": "id,desc",
                                "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
        plist = (prods.get("data") or {}).get("list") or []
        print("  关联产品数:", len(plist), flush=True)
        for p in plist[:8]:
            print("    ", {k: p.get(k) for k in ("id", "mid", "site_id", "aid", "price", "total", "status")}, flush=True)
        log.append({"step": "products", "count": len(plist),
                    "rows": [{k: p.get(k) for k in ("id", "site_id", "aid", "price", "status")} for p in plist]})
    except Exception as e:
        print("  查询失败:", repr(e), flush=True)

(HERE / "_add_result.json").write_text(
    json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n结果已写入 _add_result.json", flush=True)

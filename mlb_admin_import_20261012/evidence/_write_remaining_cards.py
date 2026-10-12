# -*- coding: utf-8 -*-
"""写入剩余 3 张 MLB 卡：add（建模型）→ shelves（建产品）→ 回读校验。

卡片：
  Ivan Rodriguez/99/C/Marlins/Awards            $1.32
  George Springer/99/CF/Astros/The Show Classics $1.23
  Andy Pettitte/99/SP/Yankees/Awards            $1.14

⛔ 铁律：
  - 每张卡：先幂等检查（已存在且产品齐全 → 跳过）
  - add 只发一次，失败即停（不自动重试）
  - add 响应不含 mid → 回读 /index 用 title 精确定位
  - shelves 只发一次
  - 每张卡完成立即回读校验产品数 = 48
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

GID, CID = 927, 8233
EXPECTED_PRODUCTS = 48

CARDS = [
    ("Ivan Rodriguez/99/C/Marlins/Awards", 1.32),
    ("George Springer/99/CF/Astros/The Show Classics", 1.23),
    ("Andy Pettitte/99/SP/Yankees/Awards", 1.14),
]

report = []


def find_model(title):
    """按 title 在 MLB scope 内精确定位模型（分页全取）。"""
    page = 1
    while page <= 10:
        d = c.list_models(gid=GID, cid=CID, page=page, limit=200)
        for row in d.get("list") or []:
            if (row.get("title") or "").strip() == title:
                return row
        total = int(d.get("total") or 0)
        if page * 200 >= total:
            break
        page += 1
    return None


def products_of(mid):
    d = c._json("GET", "/admin/goods.Goods/index",
                params={"page": 1, "limit": 100, "order": "id,desc",
                        "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
    data = d.get("data") or {}
    return int(data.get("total") or 0), (data.get("list") or [])


def build_add_body(title, price, sample_row):
    """按已有 MLB 模型字段构造新增 body。"""
    return {
        "gid": GID, "cid": CID,
        "top_cid": sample_row.get("top_cid", 0),
        "sid": sample_row.get("sid", 0),
        "aid": sample_row.get("aid", 0),
        "title": title, "icon": 0, "pic": "",
        "price": price, "discount": 100, "min_qty": 1,
        "receiving_price": 0, "sort": 1000,
        "status": "1", "is_put": "0",
        "is_hot": "0", "is_rec": "0", "is_code": "0", "auto_off": "0",
        "buy_status": 0, "attr_switch": "0", "sku_switch": "0",
        "partner": "", "summary": "", "desc": "",
        "duration": "0", "shelf_time": "0", "tid": "0",
        "more": {"extend": []},
        "_extend": {"site_ids": [], "aids": [], "duration": "0"},
    }


# ---- 取一条已有 MLB 模型作字段样板 ----
print("=== 取样板模型 ===", flush=True)
ed = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": 44234597})
sample = (ed.get("data") or {}).get("row") or {}
print("  样板: %s (top_cid=%s sid=%s)" % (
    (sample.get("title") or "")[:40], sample.get("top_cid"), sample.get("sid")), flush=True)

for idx, (title, price) in enumerate(CARDS, 1):
    print("\n" + "=" * 62, flush=True)
    print("[%d/3] %s   $%s" % (idx, title, price), flush=True)
    rec = {"title": title, "price": price}
    report.append(rec)

    # ---- 幂等：模型是否已存在 ----
    exist = find_model(title)
    if exist:
        mid = exist.get("id")
        pt, _ = products_of(mid)
        print("  ⚠️ 模型已存在 mid=%s 产品数=%s" % (mid, pt), flush=True)
        rec.update({"existed": True, "mid": mid, "products_before": pt})
        if pt >= EXPECTED_PRODUCTS:
            print("     产品齐全，跳过", flush=True)
            rec["verdict"] = "skipped(complete)"
            continue
        # 模型在但产品缺 → 直接补 shelves
        ext = (exist.get("_extend") or {})
        need_shelves = True
    else:
        # ---- 步骤1：add 建模型 ----
        body = build_add_body(title, price, sample)
        print("  → POST /add 建模型 …", flush=True)
        try:
            res = c._json("POST", "/admin/goods.GoodsMould/add", json_body=body)
            print("     返回:", json.dumps(res, ensure_ascii=False)[:300], flush=True)
            rec["add"] = res.get("msg")
        except AdminUnknownResult as e:
            print("     [X] 结果未知，停止本卡:", e, flush=True)
            rec["verdict"] = "unknown(no-retry)"
            report[-1] = rec
            break
        except Exception as e:
            print("     [X] 被拒:", repr(e), flush=True)
            rec["verdict"] = "add-failed: %r" % e
            continue

        time.sleep(2)
        m = find_model(title)
        if not m:
            print("     [X] 回读找不到新模型，停止本卡", flush=True)
            rec["verdict"] = "readback-missing"
            continue
        mid = m.get("id")
        print("     ✅ 模型已建 mid=%s" % mid, flush=True)
        rec["mid"] = mid
        need_shelves = True

    # ---- 步骤2：shelves 建产品 ----
    if need_shelves:
        ed2 = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": mid})
        r2 = (ed2.get("data") or {}).get("row") or {}
        ext = r2.get("_extend") or {}
        site_ids = ext.get("all_site_ids") or []
        aids = ext.get("all_aids") or []
        if not site_ids or not aids:
            print("     [X] site_ids/aids 为空，跳过 shelves", flush=True)
            rec["verdict"] = "no-config"
            continue
        sbody = {
            "num": ext.get("num", 1), "min_qty": r2.get("min_qty", 1),
            "total": ext.get("total", 0), "discount": r2.get("discount", 100),
            "price": r2.get("price"), "status": str(r2.get("status", 1)),
            "is_rec": str(r2.get("is_rec", 0)),
            "duration": str(r2.get("duration", 0)),
            "open_watermark": str(ext.get("open_watermark", 0)),
            "site_ids": site_ids, "aids": aids, "search": {"mids": mid},
        }
        print("  → POST /shelves 建产品（%d 站 × %d 区）…" % (len(site_ids), len(aids)), flush=True)
        try:
            sres = c._json("POST", "/admin/goods.GoodsMould/shelves", json_body=sbody)
            print("     返回:", json.dumps(sres, ensure_ascii=False)[:200], flush=True)
            rec["shelves"] = sres.get("msg")
        except AdminUnknownResult as e:
            print("     [X] shelves 结果未知，停止:", e, flush=True)
            rec["verdict"] = "shelves-unknown(no-retry)"
            break
        except Exception as e:
            print("     [X] shelves 被拒:", repr(e), flush=True)
            rec["verdict"] = "shelves-failed: %r" % e
            continue

        time.sleep(4)
        pt, _ = products_of(mid)
        ok = pt >= EXPECTED_PRODUCTS
        print("  ✅ 校验：产品数=%s（预期 %s）%s" % (pt, EXPECTED_PRODUCTS, "" if ok else " ⚠️"), flush=True)
        rec["products_after"] = pt
        rec["verdict"] = "ok" if ok else "product-count-mismatch"

(HERE / "_write_cards_result.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n" + "=" * 62, flush=True)
print("汇总:", flush=True)
for r in report:
    print("  %-52s %s" % (r["title"][:50], r.get("verdict")), flush=True)
print("\n已写入 _write_cards_result.json", flush=True)

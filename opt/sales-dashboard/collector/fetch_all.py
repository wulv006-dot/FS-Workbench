# -*- coding: utf-8 -*-
"""采集器：Admin 订单 + 折扣码配置 + 会员身份 + Order 发货记录 → data/*.json

口径说明
--------
* Admin 订单：  /admin/order.Order/index  gid=891(Aion 2)  paytime RANGE
* 折扣码配置：  /admin/market.Discount/index   （含归属后台账号 admins.nickname 与归属会员 uid）
* 会员身份：    /admin/user.Member/index     按 uid 精确查（usname 脱敏邮箱 / 姓名 / discount_code）
* 发货记录：    order.p2pah.cn /order/admin_delivery/index.html  gid=826(Aion 2) genre=1(订单发货)
                —— 每行给 ￥采购单价 / ￥采购总价 / ￥销售价 / 利润率，按「商户订单号」与订单 join
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2pah_auth as A
from lxml import html as LH

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)

ADMIN_GID = 891      # Admin 侧 Aion 2
ORDER_GID = 826      # Order   侧 Aion 2
PAGE_SIZE = 100
GENRE_ORDER_SHIP = "1"
WORKERS = 4          # 并发抓取线程数（服务端每页约 2.8s，并发后总耗时降为 1/3 左右）


def _dump(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print("   写盘 %s (%d 条)" % (name, len(obj) if hasattr(obj, "__len__") else 1))


# --------------------------------------------------------------- 1) 订单
def _order_page(s, page, start, end):
    st, js = s.get_admin("/admin/order.Order/index", **{
        "page": page, "limit": PAGE_SIZE, "order": "id,desc",
        "search[0][field]": "gid", "search[0][val]": str(ADMIN_GID),
        "search[0][operator]": "=",
        "search[1][field]": "paytime",
        "search[1][val]": "%s 00:00:00,%s 23:59:59" % (start, end),
        "search[1][operator]": "RANGE", "search[1][render]": "datetime",
    })
    if st != 200 or js.get("code") != 1:
        raise RuntimeError("订单接口失败 HTTP=%s code=%s msg=%s" % (st, js.get("code"), js.get("msg")))
    d = js.get("data") or {}
    return d.get("list") or [], int(d.get("total") or 0)


def fetch_orders(s, start, end):
    first, total = _order_page(s, 1, start, end)
    rows = list(first)
    npages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print("   订单 第1/%d 页，累计 %d/%d" % (npages, len(rows), total), flush=True)
    if npages <= 1:
        return rows
    got = {1: first}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_order_page, s, p, start, end): p for p in range(2, npages + 1)}
        for f in as_completed(futs):
            p = futs[f]
            try:
                lst, _ = f.result()
            except Exception as e:
                print("   ⚠ 订单第%d页失败：%r" % (p, e))
                continue
            got[p] = lst
            n = sum(len(v) for v in got.values())
            if len(got) % 5 == 0 or len(got) == npages:
                print("   订单 %d/%d 页，累计 %d/%d" % (len(got), npages, n, total), flush=True)
    for p in range(1, npages + 1):
        rows.extend(got.get(p, []) if p > 1 else [])
    # 去重（按 id）+ 稳定排序
    seen, dedup = set(), []
    for r in sorted(rows, key=lambda x: int(x.get("id") or 0), reverse=True):
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        dedup.append(r)
    return dedup


# --------------------------------------------------------------- 2) 折扣码
def fetch_discounts(s):
    rows, page, total = [], 1, None
    while True:
        st, js = s.get_admin("/admin/market.Discount/index", page=page, limit=200)
        if st != 200 or js.get("code") != 1:
            raise RuntimeError("折扣码接口失败 HTTP=%s code=%s" % (st, js.get("code")))
        d = js.get("data") or {}
        batch = d.get("list") or []
        if total is None:
            total = int(d.get("total") or 0)
        rows.extend(batch)
        if not batch or len(rows) >= total:
            break
        page += 1
        time.sleep(0.1)
    print("   折扣码 %d 个" % len(rows))
    return rows


# --------------------------------------------------------------- 3) 会员
def _member_one(s, uid):
    st, js = s.get_admin("/admin/user.Member/index", **{
        "page": 1, "limit": 3,
        "search[0][field]": "uid", "search[0][val]": str(uid),
        "search[0][operator]": "=",
    })
    lst = ((js.get("data") or {}).get("list") or [])
    return str(uid), (lst[0] if lst else None)


def fetch_members(s, uids):
    out = {}
    uids = sorted({int(u) for u in uids if u and int(u) > 0})
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_member_one, s, u): u for u in uids}
        done = 0
        for f in as_completed(futs):
            try:
                uid, rec = f.result()
                if rec:
                    out[uid] = rec
            except Exception as e:
                print("   会员 uid=%s 查询失败 %r" % (futs[f], e))
            done += 1
            if done % 50 == 0:
                print("   会员 %d/%d" % (done, len(uids)), flush=True)
    print("   会员身份 %d/%d 命中" % (len(out), len(uids)))
    return out


# --------------------------------------------------------------- 4) 发货记录
_DELIV_HEAD = ["", "delivery_id", "genre_text", "source", "sn", "trade_at", "game",
               "qty", "gift", "cost_unit", "cost_total", "sale_total", "margin_pct",
               "supplier", "payee", "operator", "note", "settle_status", "action"]


def _parse_delivery(txt, page):
    doc = LH.fromstring(txt)
    if lxml_login(doc):
        raise RuntimeError("发货记录需要重新登录（返回了登录页）")
    tbls = doc.xpath('//table[contains(@class,"table-list")]')
    if not tbls:
        return [], None
    trs = tbls[0].xpath('.//tbody/tr')
    out = []
    for tr in trs:
        tds = ["".join(td.itertext()).strip() for td in tr.xpath('./td')]
        if len(tds) < 16:
            continue
        rec = {}
        for i, k in enumerate(_DELIV_HEAD):
            rec[k] = tds[i] if i < len(tds) else ""
        # 交货类型那一格混入了下拉里的全部选项文本，只取开头的中文词
        rec["genre_text"] = re.sub(r"\s+", " ", rec["genre_text"]).strip()
        rec["genre"] = rec["genre_text"].split(" ")[0] if rec["genre_text"] else ""
        out.append(rec)
    pg_txt = " ".join(doc.xpath('//*[contains(@class,"pagination")]//text()'))
    nums = [int(x) for x in re.findall(r"\d+", pg_txt)]
    return out, (max(nums) if nums else page)


def lxml_login(doc):
    try:
        return bool(doc.xpath('//input[@name="password"]'))
    except Exception:
        return False


def _delivery_page(s, page, start, end, gid, genre):
    st, txt = s.get_order("/order/admin_delivery/index.html", **{
        "gid": str(gid), "aid": "0", "cid": "1", "genre": genre, "status": "-1",
        "op_id": "0", "show_ccy": "-1", "is_stock": "", "keyword": "", "sn": "",
        "start": "%s 00:00" % start, "end": "%s 23:59" % end, "page": str(page)})
    if st != 200:
        raise RuntimeError("发货记录 HTTP=%s page=%d" % (st, page))
    return _parse_delivery(txt, page)


def fetch_deliveries(s, start, end, gid=ORDER_GID, genre=GENRE_ORDER_SHIP):
    first, maxpage = _delivery_page(s, 1, start, end, gid, genre)
    rows = list(first)
    maxpage = maxpage or 1
    print("   发货 第1/%d 页，累计 %d" % (maxpage, len(rows)), flush=True)
    if maxpage <= 1:
        return rows
    got = {1: first}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_delivery_page, s, p, start, end, gid, genre): p
                for p in range(2, maxpage + 1)}
        for f in as_completed(futs):
            p = futs[f]
            try:
                batch, _ = f.result()
            except Exception as e:
                print("   ⚠ 发货第%d页失败：%r" % (p, e))
                continue
            got[p] = batch
            if len(got) % 20 == 0 or len(got) == maxpage:
                print("   发货 %d/%d 页，累计 %d"
                      % (len(got), maxpage, sum(len(v) for v in got.values())), flush=True)
    for p in range(2, maxpage + 1):
        rows.extend(got.get(p, []))
    return rows


# --------------------------------------------------------------- 主流程
def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2026-09-17"
    end = sys.argv[2] if len(sys.argv) > 2 else time.strftime("%Y-%m-%d")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=== 采集区间 %s → %s ===" % (start, end))
    s = A.bootstrap()

    print("[1/4] Admin 订单（gid=%d Aion 2）" % ADMIN_GID)
    orders = fetch_orders(s, start, end)
    _dump("orders.json", orders)

    print("[2/4] 折扣码配置")
    discounts = fetch_discounts(s)
    _dump("discounts.json", discounts)

    print("[3/4] 会员身份（订单里出现过的 uid）")
    code2uid = {}
    for r in discounts:
        c = (r.get("code") or "").strip()
        if c and r.get("uid"):
            code2uid[c] = int(r["uid"])
    uids = set()
    for o in orders:
        for k in ("recommend_uid", "uid"):
            try:
                if int(o.get(k) or 0) > 0:
                    uids.add(int(o[k]))
            except Exception:
                pass
        c = (o.get("discount_code") or "").strip()
        if c in code2uid:
            uids.add(code2uid[c])
    members = fetch_members(s, uids)
    _dump("members.json", members)

    print("[4/4] 发货记录（gid=%d Aion 2，仅「订单发货」）" % ORDER_GID)
    deliveries = fetch_deliveries(s, start, end)
    _dump("deliveries.json", deliveries)

    (DATA / "_meta.json").write_text(json.dumps({
        "start": start, "end": end,
        "admin_gid": ADMIN_GID, "order_gid": ORDER_GID,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "orders": len(orders), "discounts": len(discounts),
        "members": len(members), "deliveries": len(deliveries),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== 完成：订单 %d / 折扣码 %d / 会员 %d / 发货 %d ==="
          % (len(orders), len(discounts), len(members), len(deliveries)))


if __name__ == "__main__":
    main()

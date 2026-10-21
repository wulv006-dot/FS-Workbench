# -*- coding: utf-8 -*-
"""采集器（服务器版）：Admin 订单 + 折扣码配置 + 会员身份 + Order 发货记录 → data/*.json

三个要点
--------
1. **接口限制「查询跨度 ≤ 1 个月」**：一次性传 2026-09-17→今天，2026-10-18 起必报
   `code=0 下单时间查询范围不能超过一个月`。→ 用 `windows()` 按 28 天切片。
2. **分段缓存**：每轮只重抓「最近 RECENT_DAYS 天所在的窗口」，更早的窗口直接读
   `data/segments/<kind>_<start>_<end>.json`；每满 `FULL_REFRESH_HOURS` 小时（或 `--full`）
   全量重抓一次，覆盖退款/状态变更这类历史变动。
   —— 不这么做的话，177+ 页发货 × 5s/页 会超过 30 分钟的调度周期。
3. 订单按 id、发货按 delivery_id 去重合并。

口径说明
--------
* Admin 订单：  /admin/order.Order/index  gid=891(Aion 2)  paytime RANGE
* 折扣码配置：  /admin/market.Discount/index（含归属后台账号 admins.nickname 与归属会员 uid）
* 会员身份：    /admin/user.Member/index  按 uid IN 批量查
* 发货记录：    order.p2pah.cn /order/admin_delivery/index.html  gid=826(Aion 2) genre=1
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2pah_auth as A  # noqa: E402
from lxml import html as LH  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)
SEGMENTS = DATA / "segments"
CACHE_F = DATA / "_cache.json"

ADMIN_GID = 891      # Admin 侧 Aion 2
ORDER_GID = 826      # Order   侧 Aion 2
PAGE_SIZE = 100
GENRE_ORDER_SHIP = "1"
MEM_BATCH = 100
SLICE_DAYS = 28      # 接口限制「不超过一个月」，用 28 天窗口最稳
RECENT_DAYS = 4      # 最近这段总重抓
FULL_REFRESH_HOURS = 24

DEFAULT_START = "2026-09-17"


def _dump(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print("   写盘 %s (%d 条)" % (name, len(obj) if hasattr(obj, "__len__") else 1), flush=True)


def windows(start: str, end: str, days: int = SLICE_DAYS):
    """把 [start, end] 切成每段 ≤ days 天的窗口（含首尾）。"""
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    if d1 < d0:
        raise SystemExit("结束日期早于开始日期：%s > %s" % (start, end))
    out, cur = [], d0
    while cur <= d1:
        nxt = min(cur + timedelta(days=days - 1), d1)
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt + timedelta(days=1)
    return out


# --------------------------------------------------------------- 缓存
def _cache_get() -> dict:
    try:
        return json.loads(CACHE_F.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_put(d: dict) -> None:
    try:
        CACHE_F.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _seg_file(kind: str, a: str, b: str) -> Path:
    return SEGMENTS / ("%s_%s_%s.json" % (kind, a, b))


def _seg_load(kind: str, a: str, b: str):
    p = _seg_file(kind, a, b)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _seg_save(kind: str, a: str, b: str, rows) -> None:
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    p = _seg_file(kind, a, b)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def use_cache_for(a: str, b: str, today, full: bool) -> bool:
    """这个窗口能不能直接吃缓存。"""
    if full:
        return False
    cut = today - timedelta(days=RECENT_DAYS)
    return datetime.strptime(b, "%Y-%m-%d").date() <= cut


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
    if st != 200 or not isinstance(js, dict) or js.get("code") != 1:
        raise RuntimeError("订单接口失败 HTTP=%s code=%s msg=%s"
                           % (st, (js or {}).get("code"), (js or {}).get("msg")))
    d = js.get("data") or {}
    return d.get("list") or [], int(d.get("total") or 0)


def fetch_orders_range(s, start, end):
    first, total = _order_page(s, 1, start, end)
    rows = list(first)
    npages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print("   %s→%s 订单 %d 页 / %d 单" % (start, end, npages, total), flush=True)
    bad = 0
    for p in range(2, npages + 1):
        try:
            lst, _ = _order_page(s, p, start, end)
        except Exception as e:
            bad += 1
            print("   ⚠ 订单第%d页失败：%r" % (p, e), flush=True)
            if bad >= 3:
                raise RuntimeError("订单分页连续失败 %d 页（停在 p=%d），中止以免推出残数据" % (bad, p))
            time.sleep(1.5)
            continue
        bad = 0
        rows.extend(lst)
        if p % 5 == 0 or p == npages:
            print("   订单 %d/%d 页，累计 %d/%d" % (p, npages, len(rows), total), flush=True)
    return rows


def fetch_orders(s, start, end, full=False):
    today = datetime.strptime(end, "%Y-%m-%d").date()
    rows, hit = [], 0
    for a, b in windows(start, end):
        if use_cache_for(a, b, today, full):
            cached = _seg_load("orders", a, b)
            if cached is not None:
                rows.extend(cached)
                hit += 1
                continue
        batch = fetch_orders_range(s, a, b)
        _seg_save("orders", a, b, batch)
        rows.extend(batch)
    if hit:
        print("   （%d 个窗口命中缓存）" % hit, flush=True)
    seen, dedup = set(), []
    for r in sorted(rows, key=lambda x: int(x.get("id") or 0), reverse=True):
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        dedup.append(r)
    print("   订单合计 %d 条，去重后 %d 条" % (len(rows), len(dedup)), flush=True)
    return dedup


# --------------------------------------------------------------- 2) 折扣码
def fetch_discounts(s):
    rows, page, total = [], 1, None
    while True:
        st, js = s.get_admin("/admin/market.Discount/index", page=page, limit=200)
        if st != 200 or not isinstance(js, dict) or js.get("code") != 1:
            raise RuntimeError("折扣码接口失败 HTTP=%s code=%s"
                               % (st, (js or {}).get("code")))
        d = js.get("data") or {}
        batch = d.get("list") or []
        if total is None:
            total = int(d.get("total") or 0)
        rows.extend(batch)
        if not batch or len(rows) >= total:
            break
        page += 1
        time.sleep(0.1)
    print("   折扣码 %d 个" % len(rows), flush=True)
    return rows


# --------------------------------------------------------------- 3) 会员
def _members_batch(s, uids):
    st, js = s.get_admin("/admin/user.Member/index", **{
        "page": 1, "limit": len(uids) + 20,
        "search[0][field]": "uid",
        "search[0][val]": ",".join(str(u) for u in uids),
        "search[0][operator]": "IN",
    })
    if st != 200 or not isinstance(js, dict) or js.get("code") != 1:
        raise RuntimeError("会员批量失败 HTTP=%s code=%s"
                           % (st, (js or {}).get("code")))
    out = {}
    for r in ((js.get("data") or {}).get("list") or []):
        u = str(r.get("uid") or "")
        if u:
            out[u] = r
    return out


def fetch_members(s, uids):
    out = {}
    uids = sorted({int(u) for u in uids if str(u).isdigit() and int(u) > 0})
    if not uids:
        print("   会员身份 0/0（无 uid 可查）", flush=True)
        return out
    n = 0
    for i in range(0, len(uids), MEM_BATCH):
        chunk = uids[i:i + MEM_BATCH]
        try:
            out.update(_members_batch(s, chunk))
        except Exception as e:
            print("   ⚠ 会员批次 %d 失败：%r" % (i // MEM_BATCH + 1, e), flush=True)
        n += len(chunk)
    print("   会员身份 %d/%d 命中" % (len(out), len(uids)), flush=True)
    return out


# --------------------------------------------------------------- 4) 发货记录
_DELIV_HEAD = ["", "delivery_id", "genre_text", "source", "sn", "trade_at", "game",
               "qty", "gift", "cost_unit", "cost_total", "sale_total", "margin_pct",
               "supplier", "payee", "operator", "note", "settle_status", "action"]


def lxml_login(doc):
    try:
        return bool(doc.xpath('//input[@name="password"]'))
    except Exception:
        return False


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
        rec["genre_text"] = re.sub(r"\s+", " ", rec["genre_text"]).strip()
        rec["genre"] = rec["genre_text"].split(" ")[0] if rec["genre_text"] else ""
        out.append(rec)
    pg_txt = " ".join(doc.xpath('//*[contains(@class,"pagination")]//text()'))
    nums = [int(x) for x in re.findall(r"\d+", pg_txt)]
    return out, (max(nums) if nums else page)


def _delivery_page(s, page, start, end, gid, genre):
    st, txt = s.get_order("/order/admin_delivery/index.html", **{
        "gid": str(gid), "aid": "0", "cid": "1", "genre": genre, "status": "-1",
        "op_id": "0", "show_ccy": "-1", "is_stock": "", "keyword": "", "sn": "",
        "start": "%s 00:00" % start, "end": "%s 23:59" % end, "page": str(page)})
    if st != 200:
        raise RuntimeError("发货记录 HTTP=%s page=%d" % (st, page))
    return _parse_delivery(txt, page)


def fetch_deliveries_range(s, start, end, gid=ORDER_GID, genre=GENRE_ORDER_SHIP):
    rows = []
    maxpage = None
    page = 1
    t0 = time.time()
    while maxpage is None or page <= maxpage:
        for attempt in range(3):
            try:
                batch, reported_max = _delivery_page(s, page, start, end, gid, genre)
            except Exception as exc:
                if attempt == 2:
                    raise RuntimeError('delivery_page_incomplete: page=%d; no_publish' % page) from exc
                delay = 25 if str(exc) == 'global_order_unavailable' else 2 * (attempt + 1)
                print('   delivery page %d unavailable; retry same page after %ds' % (page, delay), flush=True)
                time.sleep(delay)
            else:
                break
        if maxpage is None:
            maxpage = reported_max or 1
            print('   %s->%s delivery %d pages' % (start, end, maxpage), flush=True)
        rows.extend(batch)
        if page % 20 == 0 or page == maxpage:
            elapsed = time.time() - t0
            print('   delivery %d/%d pages, rows=%d (%.1f min)' % (page, maxpage, len(rows), elapsed / 60), flush=True)
        page += 1
    return rows


def fetch_deliveries(s, start, end, full=False, gid=ORDER_GID, genre=GENRE_ORDER_SHIP):
    today = datetime.strptime(end, "%Y-%m-%d").date()
    rows, hit = [], 0
    for a, b in windows(start, end):
        if use_cache_for(a, b, today, full):
            cached = _seg_load("deliveries", a, b)
            if cached is not None:
                rows.extend(cached)
                hit += 1
                continue
        batch = fetch_deliveries_range(s, a, b, gid, genre)
        _seg_save("deliveries", a, b, batch)
        rows.extend(batch)
    if hit:
        print("   （%d 个窗口命中缓存）" % hit, flush=True)
    seen, dedup = set(), []
    for r in rows:
        k = (r.get("delivery_id") or "").strip() or tuple(sorted(r.items()))
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    print("   发货合计 %d 条，去重后 %d 条" % (len(rows), len(dedup)), flush=True)
    return dedup


# --------------------------------------------------------------- 主流程
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv
    start = args[0] if len(args) > 0 else DEFAULT_START
    end = args[1] if len(args) > 1 else time.strftime("%Y-%m-%d")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cache = _cache_get()
    last_full = cache.get("last_full_at") or ""
    if not full:
        try:
            age_h = (time.time() - time.mktime(time.strptime(last_full, "%Y-%m-%d %H:%M:%S"))) / 3600
            if age_h >= FULL_REFRESH_HOURS:
                full = True
                print("距上次全量 %.1f 小时，本轮改为全量重抓" % age_h, flush=True)
        except Exception:
            full = True

    print("=== 采集区间 %s → %s（%d 天一段，%s）==="
          % (start, end, SLICE_DAYS, "全量" if full else "增量"), flush=True)
    t_all = time.time()
    s = A.bootstrap()
    try:
        print("[1/4] Admin 订单（gid=%d Aion 2）" % ADMIN_GID, flush=True)
        orders = fetch_orders(s, start, end, full)
        _dump("orders.json", orders)

        print("[2/4] 折扣码配置", flush=True)
        discounts = fetch_discounts(s)
        _dump("discounts.json", discounts)

        print("[3/4] 发货记录（gid=%d Aion 2，仅「订单发货」）" % ORDER_GID, flush=True)
        deliveries = fetch_deliveries(s, start, end, full)
        _dump("deliveries.json", deliveries)

        print("[4/4] 会员身份（订单里出现过的 uid）", flush=True)
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

        if full:
            cache["last_full_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cache["last_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _cache_put(cache)

        (DATA / "_meta.json").write_text(json.dumps({
            "start": start, "end": end,
            "admin_gid": ADMIN_GID, "order_gid": ORDER_GID,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "full": full,
            "orders": len(orders), "discounts": len(discounts),
            "members": len(members), "deliveries": len(deliveries),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print("=== 完成：订单 %d / 折扣码 %d / 会员 %d / 发货 %d（耗时 %.1f 分钟）==="
              % (len(orders), len(discounts), len(members), len(deliveries),
                 (time.time() - t_all) / 60), flush=True)
    finally:
        s.close()


if __name__ == "__main__":
    main()

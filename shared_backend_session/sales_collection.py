# -*- coding: utf-8 -*-
"""采集器（服务器版）：Admin 订单 + 折扣码配置 + 会员身份 + Order 发货记录 → data/*.json

三个要点
--------
1. **接口限制「查询跨度 ≤ 1 个月」**：一次性传 2026-09-17→今天，2026-10-18 起必报
   `code=0 下单时间查询范围不能超过一个月`。→ 回填时用 `windows()` 按 7 天切片。
2. **历史库（2026-10-29 起）**：明细落 `data/history.db`（SQLite），每轮只抓
   「水位之后」的增量（订单回看 48 小时、发货重叠 12 小时），每周做一次 7 天重扫
   覆盖退款/状态变更；库空时才全区间回填（优先直接吃旧的 orders.json/deliveries.json，
   不为建库重翻 600 多页）。看板仍由库里的全量明细聚合，产物格式不变。
   —— 改造前每轮从 page=1 翻到 total，近 7 天实测 36,098 页请求；改造后单轮 3 页左右。
3. 订单按 id、发货按 delivery_id 去重合并（库主键即幂等键）。

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
import history_db as HDB  # noqa: E402
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
SLICE_DAYS = 7       # 回填切片：接口允许 ≤1 个月，但窗口越短越好翻（2026-10-29 由 28 改 7）
RECENT_DAYS = 1      # 分段缓存的"最近一段"（仅回填路径使用）
FULL_REFRESH_HOURS = 168   # 每 168 小时做一次「7 天重扫」，覆盖退款/状态变更

ORDER_LOOKBACK_HOURS = 48    # 相对付款水位回看；完整读取窗口，覆盖已有订单状态变更
DELIVERY_OVERLAP_HOURS = 12  # 发货增量重叠（相对水位）
DEEP_DAYS = 7                # 每周重扫窗口
MAX_ORDER_PAGES = 200        # 翻页失控保护（正常 1–3 页，burst 十几页）
MAX_DELIVERY_PAGES = 400

DEFAULT_START = "2026-09-17"

_DB = None


def db():
    """惰性打开历史库（同进程复用）。"""
    global _DB
    if _DB is None:
        _DB = HDB.open_db()
        print("   历史库 %s（订单 %d / 发货 %d）"
              % (HDB.DEFAULT_PATH, HDB.count(_DB, "orders"), HDB.count(_DB, "deliveries")),
              flush=True)
    return _DB


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
def _order_page(s, page, lo, hi):
    """lo/hi 是完整时间串 'YYYY-MM-DD HH:MM:SS'（接口支持到秒）。"""
    st, js = s.get_admin("/admin/order.Order/index", **{
        "page": page, "limit": PAGE_SIZE, "order": "id,desc",
        "search[0][field]": "gid", "search[0][val]": str(ADMIN_GID),
        "search[0][operator]": "=",
        "search[1][field]": "paytime",
        "search[1][val]": "%s,%s" % (lo, hi),
        "search[1][operator]": "RANGE", "search[1][render]": "datetime",
    })
    if st != 200 or not isinstance(js, dict) or js.get("code") != 1:
        raise RuntimeError("订单接口失败 HTTP=%s code=%s msg=%s"
                           % (st, (js or {}).get("code"), (js or {}).get("msg")))
    d = js.get("data") or {}
    return d.get("list") or [], int(d.get("total") or 0)


def _crawl_orders(s, start, end):
    """老路径：按窗口整段翻页。只在回填 / --full 时走。"""
    today = datetime.strptime(end, "%Y-%m-%d").date()
    rows, hit = [], 0
    for a, b in windows(start, end):
        if use_cache_for(a, b, today, False):
            cached = _seg_load("orders", a, b)
            if cached is not None:
                rows.extend(cached)
                hit += 1
                continue
        batch = fetch_orders_range(s, a + " 00:00:00", b + " 23:59:59")
        _seg_save("orders", a, b, batch)
        rows.extend(batch)
    if hit:
        print("   （%d 个窗口命中分段缓存）" % hit, flush=True)
    return rows


def _today_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _deep_due(conn, kind):
    """距上次「重扫」是否已满 FULL_REFRESH_HOURS。"""
    st = HDB.get_state(conn, kind)
    last = st.get("last_deep") or st.get("last_full") or ""
    if not last:
        return True
    try:
        age = (time.time() - time.mktime(time.strptime(last, "%Y-%m-%d %H:%M:%S"))) / 3600
    except Exception:
        return True
    return age >= FULL_REFRESH_HOURS


def _delta_lo(conn, kind, lookback_hours):
    """增量窗口起点 = 水位时刻 - 回看小时数（不早于建库起点）。

    两个坑：
    * 回看要相对**水位时刻**，不能相对"今天"，否则每轮都重翻最近一整天；
    * 水位要按**完整时间**减，只保留日期再减 6 小时会跨到前一天。
    """
    st = HDB.get_state(conn, kind)
    try:
        base = datetime.strptime(str(st.get("high_time") or "")[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        base = datetime.now()
    lo = base - timedelta(hours=lookback_hours)
    floor = datetime.strptime(DEFAULT_START, "%Y-%m-%d")
    return lo if lo > floor else floor


def _fmt(dt_obj):
    return dt_obj.strftime("%Y-%m-%d %H:%M:%S")


def _should_stop(batch, id_key, known):
    """翻页终止判断，实现在 history_db（那边无外部依赖，可离线单测）。"""
    return HDB.should_stop(batch, id_key, known)


def fetch_orders_range(s, lo, hi, known=None):
    """翻 [lo, hi] 区间的订单，直到空页 / 整页已知 / 不足一页 / 触到页上限。

    注意：任何一页失败都直接抛，不再"跳过这一页继续" —— 增量模式下跳过一页
    会连同水位一起推进，那页数据就永久丢了（只有周重扫能补回来）。
    """
    rows, page = [], 1
    while page <= MAX_ORDER_PAGES:
        try:
            lst, total = _order_page(s, page, lo, hi)
        except Exception as e:
            raise RuntimeError("订单第 %d 页失败，整轮中止（不推进水位）：%r" % (page, e))
        if not lst:
            break
        rows.extend(lst)
        if _should_stop(lst, "id", known):
            print("   订单第 %d 页全是已入库数据，停止翻页" % page, flush=True)
            break
        if len(lst) < PAGE_SIZE:
            break
        page += 1
    else:
        raise RuntimeError("订单翻页超过 %d 页上限，整轮中止（疑似后台异常）" % MAX_ORDER_PAGES)
    print("   %s→%s 订单翻 %d 页 / %d 条" % (lo, hi, page, len(rows)), flush=True)
    return rows


def fetch_orders(s, start, end, full=False):
    conn = db()
    st = HDB.get_state(conn, "orders")
    have = HDB.count(conn, "orders")
    if full:
        print("   订单：全区间重抓 %s → %s" % (start, end), flush=True)
        rows = _crawl_orders(s, start, end)
        n = HDB.upsert_orders(conn, rows)
        HDB.bump_watermark(conn, "orders", rows)
        HDB.set_state(conn, "orders", last_full=_today_str())
        print("   订单：翻到 %d 条，写入 %d，库内共 %d" % (len(rows), n, HDB.count(conn, "orders")), flush=True)
    elif not have:
        n = HDB.import_json(conn, DATA / "orders.json", "orders")
        if n:
            print("   订单：直接导入历史 orders.json %d 条（建库 0 次翻页）" % n, flush=True)
        else:
            rows = _crawl_orders(s, start, end)
            n = HDB.upsert_orders(conn, rows)
            HDB.bump_watermark(conn, "orders", rows)
            print("   订单：全区间回填，写入 %d 条" % n, flush=True)
    else:
        deep = _deep_due(conn, "orders")
        lo = _delta_lo(conn, "orders", DEEP_DAYS * 24 if deep else ORDER_LOOKBACK_HOURS)
        hi = datetime.now()
        before = have
        lo_s, hi_s = _fmt(lo), _fmt(hi)
        known = HDB.ids_in_range(conn, "orders", lo_s, hi_s)
        rows = fetch_orders_range(s, lo_s, hi_s)
        HDB.upsert_orders(conn, rows)
        HDB.bump_watermark(conn, "orders", rows)
        if deep:
            HDB.set_state(conn, "orders", last_deep=_today_str())
        print("   订单增量 %s→%s：取 %d 条%s，库内 %d（+%d）"
              % (lo_s, hi_s, len(rows), "（7 天重扫）" if deep else "",
                 HDB.count(conn, "orders"), HDB.count(conn, "orders") - before), flush=True)
    HDB.set_state(conn, "orders", last_run=_today_str(), rows=HDB.count(conn, "orders"))
    out = HDB.load_orders(conn, start, end)
    print("   订单合计 %d 条（来自历史库）" % len(out), flush=True)
    return out


# --------------------------------------------------------------- 2) 折扣码
def fetch_discounts(s, max_age_hours=6):
    """折扣码变化很慢：6 小时内直接吃上次落盘的 discounts.json，不再翻 8 页。

    返回 (rows, fresh)；fresh=False 时调用方不要重写文件，否则 mtime 被刷新、
    缓存永远不会过期。
    """
    f = DATA / "discounts.json"
    if max_age_hours and f.exists():
        try:
            age_h = (time.time() - f.stat().st_mtime) / 3600
            if age_h < max_age_hours:
                rows = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(rows, list) and rows:
                    print("   折扣码 %d 个（缓存 %.1f 小时，本轮不翻页）" % (len(rows), age_h), flush=True)
                    return rows, False
        except Exception:
            pass
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
    print("   折扣码 %d 个（重新拉取）" % len(rows), flush=True)
    return rows, True


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


def _delivery_page(s, page, lo, hi, gid, genre):
    """lo/hi 是完整时间串，页面参数只认到分钟。"""
    st, txt = s.get_order("/order/admin_delivery/index.html", **{
        "gid": str(gid), "aid": "0", "cid": "1", "genre": genre, "status": "-1",
        "op_id": "0", "show_ccy": "-1", "is_stock": "", "keyword": "", "sn": "",
        "start": str(lo)[:16], "end": str(hi)[:16], "page": str(page)})
    if st != 200:
        raise RuntimeError("发货记录 HTTP=%s page=%d" % (st, page))
    return _parse_delivery(txt, page)


def fetch_deliveries_range(s, lo, hi, gid=ORDER_GID, genre=GENRE_ORDER_SHIP, known=None):
    """翻 [lo, hi] 区间的发货记录，直到空页 / 整页已知 / 触到页上限。

    不再用「分页控件报的最大页码」当终止条件：那个数字既可能只显示前几页
    （少翻 → 漏），也可能把"共 N 条"当成页码（多翻几百页 → 就是同事看到的
    600 多页）。改由实际数据判断，页数只用于日志。
    """
    rows, page, declared = [], 1, None
    t0 = time.time()
    while page <= MAX_DELIVERY_PAGES:
        batch = None
        for attempt in range(3):
            try:
                batch, reported_max = _delivery_page(s, page, lo, hi, gid, genre)
            except Exception as exc:
                if attempt == 2:
                    raise RuntimeError('delivery_page_incomplete: page=%d; no_publish' % page) from exc
                delay = 25 if str(exc) == 'global_order_unavailable' else 2 * (attempt + 1)
                print('   delivery page %d unavailable; retry same page after %ds' % (page, delay), flush=True)
                time.sleep(delay)
            else:
                if declared is None:
                    declared = reported_max or 1
                    print('   %s->%s delivery 控件报 %d 页' % (lo, hi, declared), flush=True)
                break
        if not batch:
            break
        rows.extend(batch)
        if _should_stop(batch, "delivery_id", known):
            print("   delivery 第 %d 页全是已入库数据，停止翻页" % page, flush=True)
            break
        if page % 20 == 0:
            print('   delivery %d pages, rows=%d (%.1f min)' % (page, len(rows), (time.time() - t0) / 60), flush=True)
        page += 1
    else:
        raise RuntimeError("发货翻页超过 %d 页上限，整轮中止（疑似后台异常）" % MAX_DELIVERY_PAGES)
    print("   %s→%s 发货翻 %d 页 / %d 条" % (lo, hi, page, len(rows)), flush=True)
    return rows


def _crawl_deliveries(s, start, end, gid=ORDER_GID, genre=GENRE_ORDER_SHIP):
    """老路径：按窗口整段翻页。只在回填 / --full 时走。"""
    today = datetime.strptime(end, "%Y-%m-%d").date()
    rows, hit = [], 0
    for a, b in windows(start, end):
        if use_cache_for(a, b, today, False):
            cached = _seg_load("deliveries", a, b)
            if cached is not None:
                rows.extend(cached)
                hit += 1
                continue
        batch = fetch_deliveries_range(s, a + " 00:00:00", b + " 23:59:59", gid, genre)
        _seg_save("deliveries", a, b, batch)
        rows.extend(batch)
    if hit:
        print("   （%d 个窗口命中分段缓存）" % hit, flush=True)
    return rows


def fetch_deliveries(s, start, end, full=False, gid=ORDER_GID, genre=GENRE_ORDER_SHIP):
    conn = db()
    have = HDB.count(conn, "deliveries")
    if full:
        print("   发货：全区间重抓 %s → %s" % (start, end), flush=True)
        rows = _crawl_deliveries(s, start, end, gid, genre)
        n = HDB.upsert_deliveries(conn, rows, gid)
        HDB.bump_watermark(conn, "deliveries", rows)
        HDB.set_state(conn, "deliveries", last_full=_today_str())
        print("   发货：翻到 %d 条，写入 %d，库内共 %d" % (len(rows), n, HDB.count(conn, "deliveries")), flush=True)
    elif not have:
        n = HDB.import_json(conn, DATA / "deliveries.json", "deliveries", gid)
        if n:
            print("   发货：直接导入历史 deliveries.json %d 条（建库 0 次翻页）" % n, flush=True)
        else:
            rows = _crawl_deliveries(s, start, end, gid, genre)
            n = HDB.upsert_deliveries(conn, rows, gid)
            HDB.bump_watermark(conn, "deliveries", rows)
            print("   发货：全区间回填，写入 %d 条" % n, flush=True)
    else:
        deep = _deep_due(conn, "deliveries")
        lo = _delta_lo(conn, "deliveries", DEEP_DAYS * 24 if deep else DELIVERY_OVERLAP_HOURS)
        hi = datetime.now()
        before = have
        lo_s, hi_s = _fmt(lo), _fmt(hi)
        known = HDB.ids_in_range(conn, "deliveries", lo_s, hi_s)
        rows = fetch_deliveries_range(s, lo_s, hi_s, gid, genre)
        HDB.upsert_deliveries(conn, rows, gid)
        HDB.bump_watermark(conn, "deliveries", rows)
        if deep:
            HDB.set_state(conn, "deliveries", last_deep=_today_str())
        print("   发货增量 %s→%s：取 %d 条%s，库内 %d（+%d）"
              % (lo_s, hi_s, len(rows), "（7 天重扫）" if deep else "",
                 HDB.count(conn, "deliveries"), HDB.count(conn, "deliveries") - before), flush=True)
    HDB.set_state(conn, "deliveries", last_run=_today_str(), rows=HDB.count(conn, "deliveries"))
    out = HDB.load_deliveries(conn, start, end)
    print("   发货合计 %d 条（来自历史库）" % len(out), flush=True)
    return out


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
    # 2026-10-29：不再"每 24 小时自动全量重抓"。历史明细已在库里，
    # 状态变更/退款由 fetch_* 内部的 7 天重扫（FULL_REFRESH_HOURS）覆盖；
    # 真正的全区间重抓只在人工传 --full 时执行（用于修库/补洞）。
    print("=== 采集区间 %s → %s（增量 %s，每周 7 天重扫）==="
          % (start, end, "· 全量重抓" if full else ""), flush=True)
    t_all = time.time()
    s = A.bootstrap()
    try:
        print("[1/4] Admin 订单（gid=%d Aion 2）" % ADMIN_GID, flush=True)
        orders = fetch_orders(s, start, end, full)
        _dump("orders.json", orders)

        print("[2/4] 折扣码配置", flush=True)
        discounts, d_fresh = fetch_discounts(s)
        if d_fresh:
            _dump("discounts.json", discounts)

        print("[3/4] 发货记录（gid=%d Aion 2，仅「订单发货」）" % ORDER_GID, flush=True)
        deliveries = fetch_deliveries(s, start, end, full)
        _dump("deliveries.json", deliveries)

        import sales_regions
        from aggregate import parse_content
        region_stats = sales_regions.resolve_regions(s, db(), orders, deliveries, parse_content)
        print("大区历史补查：%s" % json.dumps(region_stats, ensure_ascii=False), flush=True)

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

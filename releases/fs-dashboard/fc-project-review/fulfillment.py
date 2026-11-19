"""Measure a bounded, stratified sample from historical Order FC27 Coins records."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from statistics import median
from time import monotonic
from urllib.parse import urlencode, urlsplit

ORIGIN = "https://order.p2pah.cn"
LIST = "/order/admin_order/index.html"
DETAIL = re.compile(r"^/order/admin_order/look/id/[0-9]{1,12}[.]html$")
CN = timezone(timedelta(hours=8))
HEADERS = ["", "ID", "来源/ 商户订单号", "游戏/ 服务器", "产品", "角色名", "金额", "总量/已交量",
           "状态历时", "提单时间", "管理员/绑定下家/分组", "状态"]
LIST_DOM = r"""() => {
  const table = [...document.querySelectorAll('table')].find(t => t.querySelectorAll('thead th')[1]?.textContent.trim() === 'ID');
  const filters = Object.fromEntries([...document.querySelectorAll('form select')]
    .filter(e => ['status','gid[]','source[]','had_issue','cid'].includes(e.name))
    .map(e => [e.name,[...e.selectedOptions].map(o => o.value).join(',')]));
  const fields = Object.fromEntries([...document.querySelectorAll('form input[name=start],form input[name=end]')].map(e => [e.name,e.value]));
  const rows = [...(table?.querySelectorAll('tbody tr') || [])].map(tr => [...tr.cells]).filter(c => c.length === 13).map(c => ({
    id:c[1].textContent.trim(),
    main:/(?:^|\s)www[.]mmoexp[.]com(?:\s|$)/.test(c[2].textContent),
    platform:c[3].textContent.trim().match(/^FC\s*27\s*▶\s*(PS|XBOX|PC)$/i)?.[1]?.toUpperCase(),
    merchant:c[2].textContent,
    quantity:c[7].textContent.match(/^\s*([\d,.]+)\s*\/\s*([\d,.]+)\s*$/)?.slice(1),
    status:c[11].textContent.trim(),
    detail:[...c[12].querySelectorAll('a')].map(a => (a.getAttribute('href') || a.getAttribute('onclick') || '')
      .match(/\/order\/admin_order\/look\/id\/\d+[.]html/)?.[0]).find(Boolean)
  }));
  const page = Number(new URL(location.href).searchParams.get('page') || 1);
  const shownPages = [...document.querySelectorAll('.pagination a')].map(a => Number(a.textContent.trim())).filter(n => n > 0);
  return {origin:location.origin,path:location.pathname,login:!!document.querySelector('input[type=password]'),
          filters,fields,page,headers:[...(table?.querySelectorAll('thead th') || [])].map(t => t.textContent.trim()),rows,
          hasNext:shownPages.some(n => n > page), lastPageSeen:Math.max(page, ...shownPages)};
}"""
DETAIL_DOM = r"""() => {
  const table = [...document.querySelectorAll('table')].find(t =>
    [...t.querySelectorAll('th')].map(x => x.textContent.trim()).join('|') === '日志ID|生成时间|操作人|订单状态|内容');
  const logs = [...(table?.querySelectorAll('tr.log-item') || [])];
  const parsed = [...document.scripts].map(s => s.textContent.match(/^\s*var\s+orderDeliveryData\s*=\s*(\{[^\n]*\});\s*$/m)?.[1]).find(Boolean);
  const goods = [...document.querySelectorAll('table.look-goods-table tbody tr[data-pid]')].map(r => ({
    pid:r.dataset.pid, gid:r.dataset.gid, cid:r.dataset.cid, unit:r.dataset.unit, qty:r.dataset.qty, used:r.dataset.used,
    base:[...r.cells].flatMap(c => [c.textContent, ...[...c.querySelectorAll('[title]')].map(t => t.getAttribute('title'))])
      .map(text => text.trim().match(/^([\d,]+)\s*K\s*(?:coins?\b|金币)/i)?.[1]).find(Boolean)
  }));
  const deliveries = parsed ? Object.values(JSON.parse(parsed)).map(d => ({
    id:d.id,pid:d.pid,qty:d.qty,gift:d.give,timestamp:d.timestamp,status:d.status
  })) : [];
  return {
    origin:location.origin,path:location.pathname,login:!!document.querySelector('input[type=password]'),
    found:!!table,eventCount:logs.length,deliveryCount:deliveries.length,
    events:logs.slice(0,100).map(r => ({id:r.cells[0]?.textContent.trim(),time:r.cells[1]?.textContent.trim(),
      status:r.cells[3]?.className.match(/(?:^|\s)order-status-(\d+)(?:\s|$)/)?.[1]})),
    goods,deliveries:deliveries.slice(0,100)
  };
}"""


def number(value):
    try:
        result = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def log_time(value):
    for format_ in ("%Y-%m-%d %H:%M:%S", "%y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, format_).replace(tzinfo=CN)
        except (ValueError, TypeError):
            continue
    return None


def evidence(detail, row, start, end):
    goods = detail["goods"]
    if not goods or any((g["gid"], g["cid"], g["unit"]) != ("1322", "1", "K") for g in goods):
        return "unverified_coins", None
    amounts = {g["pid"]: (number(g.get("base")), number(g.get("qty")), number(g.get("used"))) for g in goods}
    if (len(amounts) != len(goods) or any(base is None or qty is None or used is None or not 0 < base <= qty
                                          for base, qty, used in amounts.values())):
        return "unverified_purchased_quantity", None
    purchased = sum(value[0] for value in amounts.values())
    band = "atLeast1000" if purchased >= 1000 else "under1000"
    sample = {"platform": row["platform"], "band": band, "status": "unknown", "minutes": None}
    events = detail["events"]
    if not events or detail["eventCount"] != len(events):
        return "incomplete_log", sample
    sequenced = [(log_time(log.get("time")), str(log.get("id") or ""), log.get("status")) for log in events]
    if any(stamp is None or not log_id.isdigit() or status is None for stamp, log_id, status in sequenced):
        return "invalid_log_event", sample
    ordered = sorted(sequenced, key=lambda log: (log[0], int(log[1])))
    if ordered[0][2] != "1":
        return "unverified_queue_entry", sample
    opened = ordered[0][0]
    if not start <= opened.date() <= end:
        return "queue_entry_outside_requested_period", None
    sample["opened_date"] = opened.date().isoformat()
    first_issue = next((log[0] for log in ordered if log[2] == "6"), None)
    issue = first_issue is not None
    if issue != row["had_issue"]:
        return "issue_flag_log_conflict", sample
    sample["status"] = "problem" if issue else "smooth"
    if ordered[-1][2] != "3" or any(qty != used for _, qty, used in amounts.values()):
        return "unverified_completion", sample
    if not detail["deliveries"] or detail["deliveryCount"] != len(detail["deliveries"]):
        return "incomplete_deliveries", sample
    seen = set()
    delivered = defaultdict(Decimal)
    timestamps = []
    for shipment in detail["deliveries"]:
        pid, ident = str(shipment["pid"]), str(shipment["id"])
        qty, gift = number(shipment["qty"]), number(shipment["gift"])
        if (str(shipment["status"]) not in ("0", "1") or not ident.isdigit() or ident in seen
                or pid not in amounts or qty is None or gift is None):
            return "unverified_delivery_record", sample
        seen.add(ident)
        delivered[pid] += qty + gift
        try:
            timestamps.append(datetime.fromtimestamp(int(shipment["timestamp"]), CN))
        except (ValueError, OverflowError, OSError, TypeError):
            return "invalid_delivery_time", sample
    if any(delivered[pid] != qty for pid, (_, qty, _) in amounts.items()):
        return "delivery_quantity_not_reconciled", sample
    final_shipment = max(timestamps)
    if min(timestamps) < opened or final_shipment > ordered[-1][0] + timedelta(minutes=1):
        return "delivery_timeline_conflict", sample
    sample["minutes"] = (final_shipment - opened).total_seconds() / 60
    if first_issue is not None and first_issue <= final_shipment:
        sample["problem_minutes"] = (final_shipment - first_issue).total_seconds() / 60
    return "timed", sample


def sample_days(start, end):
    count = (end - start).days
    return sorted({start, start + timedelta(days=count // 2), end})


def candidate_rows(page, day, issue, deadline):
    possible = {}
    clean_filters = {"gid[]": "1322", "status": "3", "cid": "1", "had_issue": str(int(issue)),
                     "source[]": "www.mmoexp.com"}
    fields = {"start": day.isoformat() + " 00:00", "end": (day + timedelta(days=1)).isoformat() + " 00:00"}
    proof = {"date": day.isoformat(), "hadIssue": issue, "pagesRead": 0, "lastPageSeen": None,
             "eligibleRowsListed": 0, "hasMore": None, "status": "available"}
    for n in (1, 2):
        if monotonic() >= deadline:
            proof["status"] = "read_budget"
            break
        response = page.goto(ORIGIN + LIST + "?" + urlencode(dict(clean_filters, **fields, page=n)),
                             wait_until="domcontentloaded", timeout=8000)
        raw = page.evaluate(LIST_DOM)
        if (not response or response.status != 200 or raw["origin"] != ORIGIN or raw["path"] != LIST or raw["login"]):
            raise ValueError("order_list_session_unavailable")
        if (raw["headers"][:-1] != HEADERS or raw["headers"][-1] not in ("操作", "Actions")
                or raw["filters"] != clean_filters or raw["fields"] != fields or raw["page"] != n):
            raise ValueError("order_list_scope_unverified")
        proof.update(pagesRead=proof["pagesRead"] + 1, lastPageSeen=raw["lastPageSeen"], hasMore=raw["hasNext"])
        for row in raw["rows"]:
            if (not row["main"] or row["status"] != "已完成" or not row.get("platform")
                    or not re.fullmatch(r"\d{1,12}", row["id"]) or not DETAIL.fullmatch(row.get("detail") or "")
                    or row["detail"] != "/order/admin_order/look/id/" + row["id"] + ".html"):
                raise ValueError("order_list_row_scope_unverified")
            qty = number((row.get("quantity") or [None])[0])
            if qty:
                possible[row["id"]] = dict(row, had_issue=issue, day=day.isoformat(), quantity_hint=qty)
        if not raw["hasNext"]:
            break
    proof["eligibleRowsListed"] = len(possible)
    return possible, proof


def select_sample(candidates, start):
    groups = defaultdict(list)
    for order in candidates.values():
        hint = order["quantity_hint"] >= 1000
        groups[(order["platform"], hint, order["had_issue"])].append(order)
    result = []
    for group in sorted(groups):
        rows = groups[group]
        # Stable within each platform/size/problem group, spread the two slots over distinct dates when possible.
        rows.sort(key=lambda row: hashlib.sha256((start.isoformat() + "/" + row["id"]).encode()).hexdigest())
        result.append(rows[0])
        if len(rows) > 1:
            result.append(next((row for row in rows[1:] if row["day"] != rows[0]["day"]), rows[1]))
    return result


def time_summary(timed):
    if not timed:
        return {"orders": 0, "meanMinutes": None, "medianMinutes": None, "p90Minutes": None}
    ordered = sorted(timed)
    return {"orders": len(ordered), "meanMinutes": round(sum(ordered) / len(ordered), 2),
            "medianMinutes": round(median(ordered), 2),
            "p90Minutes": round(ordered[math.ceil(len(ordered) * 0.9) - 1], 2)}


def duration_summary(rows):
    totals = time_summary([row["minutes"] for row in rows if row["minutes"] is not None])
    timed = totals.pop("orders")
    problems = time_summary([row["problem_minutes"] for row in rows if row.get("problem_minutes") is not None])
    return {"orders": len(rows), "timedOrders": timed, **totals,
            "problemToCompleteMinutes": problems if problems["orders"] else None}


def summarize(samples, *, by_day=False):
    groups = defaultdict(list)
    for item in samples:
        if by_day and not item.get("opened_date"):
            continue
        key = (item["platform"], item["band"], item["status"])
        groups[(item["opened_date"], *key) if by_day else key].append(item)
    rows = []
    for key, members in sorted(groups.items()):
        platform, band, status = key[-3:]
        rows.append({"game": "FC27", "platform": platform, "category": "Coins", "quantityBand": band,
                     "deliveryStatus": status, **({"date": key[0]} if by_day else {}), **duration_summary(members)})
    return rows


def daily_totals(samples):
    groups = defaultdict(list)
    for row in samples:
        if row.get("opened_date"):
            groups[row["opened_date"]].append(row)
    return [{"date": day, **duration_summary(rows)} for day, rows in sorted(groups.items())]


def readonly(route):
    req = route.request
    parsed = urlsplit(req.url)
    if (req.method in ("GET", "HEAD") and parsed.scheme == "https" and parsed.netloc == "order.p2pah.cn"
            and (parsed.path == LIST or DETAIL.fullmatch(parsed.path))):
        route.continue_()
    else:
        route.abort()


def collect(start, end, *, deadline=None):
    from playwright.sync_api import Error, sync_playwright
    deadline = deadline if deadline is not None else monotonic() + 105
    candidates = {}
    proofs = []
    samples = []
    outcomes = Counter()
    selected = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9226", timeout=8000, no_defaults=True)
        page = browser.contexts[0].new_page()

        page.route("**/*", readonly)
        try:
            for day in sample_days(start, end):
                for issue in (False, True):
                    try:
                        listed, proof = candidate_rows(page, day, issue, deadline)
                    except (ValueError, Error) as exc:
                        reason = str(exc) if isinstance(exc, ValueError) else "browser_read_failed"
                        proofs.append({"date": day.isoformat(), "hadIssue": issue, "status": reason})
                        if reason == "order_list_session_unavailable":
                            break
                        continue
                    candidates.update(listed)
                    proofs.append(proof)
            selected = select_sample(candidates, start)
            for row in selected:
                if monotonic() >= deadline:
                    outcomes["read_budget"] += 1
                    continue
                try:
                    response = page.goto(ORIGIN + row["detail"], wait_until="domcontentloaded", timeout=8000)
                    detail = page.evaluate(DETAIL_DOM)
                    if (not response or response.status != 200 or detail["origin"] != ORIGIN
                            or detail["path"] != row["detail"] or detail["login"] or not detail["found"]):
                        outcomes["order_detail_unavailable"] += 1
                        continue
                    outcome, sample = evidence(detail, row, start, end)
                    outcomes[outcome] += 1
                    if sample is not None:
                        samples.append(sample)
                except (ValueError, TypeError, KeyError, Error):
                    outcomes["order_detail_read_failed"] += 1
        finally:
            page.close()
    return {
        "start": start.isoformat(), "end": end.isoformat(), "status": "partial" if samples else "unavailable",
        "asOf": datetime.now(CN).isoformat(),
        "source": "Order · FC 27 / www.mmoexp.com / Game Coins / 已完成 / 曾为问题单 / 订单明细",
        "reason": "已完成订单分层样本。按 Order 付款日读取候选，再要求首条入队日志处于本期。末次实际发货以发货记录时间和逐项数量对齐；样本配额不代表问题率。",
        "coverage": {"candidates": len(candidates), "selected": len(selected), "retained": len(samples),
                     "timed": outcomes["timed"], "payments": proofs, "outcomes": dict(outcomes),
                     "timeZone": "Asia/Shanghai", "selection": "每期最多三日，各读曾问题及非曾问题前两页，按平台和数量等额选最多两笔"},
        "rows": summarize(samples), "daily": summarize(samples, by_day=True), "dailyTotals": daily_totals(samples),
    }



ACTIVE = {"新订单", "交易中", "再次发货", "已暂停", "问题单"}
QUEUE_FILTERS = {"all": ACTIVE, "3": {"已完成"}, "5": {"已取消"}}


def queue_partition(page, fields, order_status, issue, deadline):
    filters = {"gid[]": "1322", "status": order_status, "cid": "1",
               "had_issue": str(int(issue)), "source[]": "www.mmoexp.com"}
    rows = []
    n, last_page = 0, 1
    status = "complete"
    while n < last_page:
        if monotonic() >= deadline:
            status = "read_budget"
            break
        n += 1
        response = page.goto(ORIGIN + LIST + "?" + urlencode(dict(filters, **fields, page=n)),
                             wait_until="domcontentloaded", timeout=8000)
        raw = page.evaluate(LIST_DOM)
        if (not response or response.status != 200 or raw["origin"] != ORIGIN or raw["path"] != LIST or raw["login"]):
            raise ValueError("order_queue_session_unavailable")
        if (raw["headers"][:-1] != HEADERS or raw["headers"][-1] not in ("操作", "Actions")
                or raw["filters"] != filters or raw["fields"] != fields or raw["page"] != n):
            raise ValueError("order_queue_list_scope_unverified")
        if any(not row["main"] or row["status"] not in QUEUE_FILTERS[order_status] or not row.get("platform")
               or not re.fullmatch(r"\d{1,12}", row["id"]) for row in raw["rows"]):
            raise ValueError("order_queue_row_scope_unverified")
        last_page = raw["lastPageSeen"]
        rows.extend(dict(row, had_issue=issue) for row in raw["rows"])
        if raw["hasNext"] and not raw["rows"]:
            raise ValueError("order_queue_unexpected_empty_page")
    proof = {"stateFilter": order_status, "hadIssueFilter": issue, "pages": n,
             "lastPageSeen": last_page, "ordersRead": len(rows), "status": status}
    return rows, proof


def queue_summary(rows, purchases, complete):
    order_groups = defaultdict(list)
    source_ids = set()
    conflicts = 0
    for row in rows:
        if row["id"] in source_ids:
            conflicts += 1
            continue
        source_ids.add(row["id"])
        text = row["merchant"].replace("www.mmoexp.com", "")
        tokens = set(re.findall(r"[A-Za-z0-9_-]{3,100}", text))
        matches = tokens & purchases.keys()
        merchant = next(iter(matches)) if len(matches) == 1 else next(iter(tokens)) if len(tokens) == 1 else None
        order_groups[("merchant", merchant) if merchant else ("order", row["id"])].append(row)
    groups = defaultdict(Counter)
    one_merchant = sum(key[0] == "merchant" for key in order_groups)
    for key, parts in order_groups.items():
        platforms = {row["platform"] for row in parts}
        platform = next(iter(platforms)) if len(platforms) == 1 else "unknown"
        purchase = purchases.get(key[1]) if key[0] == "merchant" else None
        tier = ("atLeast1000" if float(purchase["purchase_k"]) >= 1000 else "under1000") if purchase and (
            purchase["platform"].upper() == platform) else "unknown"
        state = ("completed" if all(row["status"] == "已完成" for row in parts)
                 else "open" if any(row["status"] in ACTIVE for row in parts) else "canceled")
        issue = "problem" if any(row["had_issue"] for row in parts) else "smooth"
        groups[(platform, tier, issue)][state] += 1

    def summary(counts):
        orders = sum(counts.values())
        return {"orders": orders, "completed": counts["completed"], "open": counts["open"],
                "canceled": counts["canceled"], "completionRate": counts["completed"] / orders
                if complete and not conflicts and orders else None}

    aggregated = [{"game": "FC27", "platform": platform, "quantityBand": band, "deliveryStatus": issue, **summary(counts)}
                  for (platform, band, issue), counts in sorted(groups.items())]
    total = sum(groups.values(), Counter())
    orders_of_known_size = sum(row["orders"] for row in aggregated if row["quantityBand"] != "unknown")
    return {"rows": aggregated, "totals": summary(total), "coverage": {
        "uniqueNativeOrderIds": len(source_ids), "merchantOrdersResolved": one_merchant,
        "quantityLinked": orders_of_known_size, "duplicateNativeRows": conflicts}}


def collect_queue(start, end, purchases, publication, *, deadline=None):
    from playwright.sync_api import Error, sync_playwright
    fields = {"start": start.isoformat() + " 00:00", "end": end.isoformat() + " 23:59:59"}
    proofs, rows = [], []
    deadline = deadline if deadline is not None else monotonic() + 100
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9226", timeout=8000, no_defaults=True)
        page = browser.contexts[0].new_page()
        page.route("**/*", readonly)
        try:
            for state in QUEUE_FILTERS:
                for issue in (False, True):
                    try:
                        part, proof = queue_partition(page, fields, state, issue, deadline)
                        rows.extend(part)
                        proofs.append(proof)
                    except (Error, ValueError) as exc:
                        proofs.append({"stateFilter": state, "hadIssueFilter": issue,
                                       "status": str(exc) if isinstance(exc, ValueError) else "browser_read_failed"})
        finally:
            page.close()
    complete = len(proofs) == 6 and all(p["status"] == "complete" for p in proofs)
    result = queue_summary(rows, purchases, complete)
    result["coverage"].update(partitions=proofs, purchasedQuantityPublication=publication, timeZone="Asia/Shanghai")
    result.update(start=start.isoformat(), end=end.isoformat(), asOf=datetime.now(CN).isoformat(),
                  source="Order · FC27 主站 Game Coins 付款队列 × 已发布共享 ES 商品购买量",
                  reason="截至读取时点已完成／全部付款队列，分母含在途及已取消。按商户单去重；未核购买量留在未知档。",
                  status="complete" if complete and result["coverage"]["duplicateNativeRows"] == 0
                  and result["coverage"]["quantityLinked"] == result["totals"]["orders"] else "partial" if rows else "unavailable")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if not args.start <= args.end < datetime.now(CN).date():
        parser.error("expected a closed date window")
    print(json.dumps(collect(args.start, args.end), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

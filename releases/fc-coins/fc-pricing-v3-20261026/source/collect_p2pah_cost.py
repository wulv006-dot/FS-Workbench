"""Read current FC27 Game Coins procurement records in server Chrome."""
from __future__ import annotations
from isolated_backend import open_backend, close_backend

import sys as _order_sys
from pathlib import Path as _OrderPath
for _order_root in ('/opt/fs-order-session', '/opt/fc27-collector', '/opt/madden-workbench', '/srv'):
    if _OrderPath(_order_root, 'fs_order_client.py').is_file():
        _order_sys.path.insert(0, _order_root)
        break
import fs_order_client as _global_order

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
import traceback
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

def login(page, config=None):
    _global_order.apply(page.context)
    return 'global_order'

from p2pah_session_service import read_private_config


BASE = "https://order.p2pah.cn/order/admin_delivery/index.html"
PLATFORMS = ("PS", "XBOX", "PC")
SHANGHAI = ZoneInfo("Asia/Shanghai")
CONSOLE_COST_CONTRACT = 'ps_latest_six_valid_order_delivery_max_v1'


def cost_url(page: int, window=None) -> str:
    today = datetime.now(SHANGHAI).date()
    query = {"gid": "1322", "aid": "0", "cid": "1",
             "start": str(today - timedelta(days=7)) + " 00:00",
             "end": str(today + timedelta(days=1)) + " 00:00",
             "show_ccy": "-1", "genre": "1", "status": "-1", "op_id": "0",
             "is_stock": "", "keyword": "", "sn": "", "page": str(page)}
    if window is not None:
        query.update(aid=window.get('area', '21942'), start=window['start'].strftime('%Y-%m-%d %H:%M:%S'),
                     end=window['end'].strftime('%Y-%m-%d %H:%M:%S'))
    return BASE + "?" + urlencode(query)


READ_ROWS = r"""() => ({
  login:location.pathname.includes('login.html'),
  ready:document.readyState,
  page:new URLSearchParams(location.search).get('page'),
  game:document.querySelector('#lot-game')?.value,
  area:document.querySelector('#lot-area')?.value,
  start:document.querySelector('#lot-start')?.value,
  end:document.querySelector('#lot-end')?.value,
  deliveryRowCount:[...(document.querySelector('table.table-list')?.querySelectorAll('tr')||[])].filter(tr=>[...tr.children].filter(c=>c.tagName==='TD').length>=10).length,
  genre:document.querySelector('#lot-genre')?.value,
  typeHeader:document.querySelector('table.table-list thead th:nth-child(3)')?.innerText.trim(),
  product:document.querySelector('#lot-type')?.value,
  table:!!document.querySelector('table.table-list'),
  hasDataRows:[...document.querySelectorAll('tr')].some(tr=>tr.querySelector('td')),
  empty:document.body?.innerText.includes('暂无数据')||false,
  rows:[...document.querySelectorAll('tr')].map(tr=>{
    const c=[...tr.children].filter(x=>x.tagName==='TD');
    const platform=c[6]?.innerText?.trim().match(/^FC\s*27\s*▶\s*(PS|XBOX|PC)$/i)?.[1];
    return platform?{platform:platform.toUpperCase(),record_id:c[1]?.innerText.trim(),
      delivery_type:c[2]?.innerText.trim(),trade_at:c[5]?.innerText.trim(),cny_per_1k:c[9]?.innerText.trim(),
      order_id:c[4]?.querySelector('a')?.getAttribute('href')?.match(/\/order\/admin_order\/look\/id\/(\d+)\.html/)?.[1],
      quantity:c[7]?.innerText.trim(),gift:c[8]?.innerText.trim(),cost_total:c[10]?.innerText.trim()}:null;
  }).filter(Boolean)
})"""

READ_ORDER = r"""async (orderId) => {
  let html;
  try {
    const response = await fetch(`/order/admin_order/look/id/${orderId}.html`, {
      redirect: 'error', signal: AbortSignal.timeout(8000)
    });
    if (!response.ok) return null;
    html = await response.text();
  } catch (error) {
    if (error.name === 'TimeoutError') return {timed_out: true};
    throw error;
  }
  const page = new DOMParser().parseFromString(html, 'text/html');
  const script = [...page.scripts].map(s => s.textContent)
    .map(s => s.match(/^\s*var\s+orderDeliveryData\s*=\s*(\{[^\n]*\});\s*$/m)?.[1]).find(Boolean);
  if (!script) return null;
  const goods = [...page.querySelectorAll('table.look-goods-table tbody tr[data-pid]')]
    .map(({dataset: d}) => ({pid: d.pid, gid: d.gid, cid: d.cid, aid: d.aid, unit: d.unit, qty: d.qty, used: d.used}));
  const deliveries = Object.values(JSON.parse(script)).map(d => ({id: d.id, pid: d.pid,
    qty: d.qty, gift: d.give, price: d.delivery_price, total: d.delivery_amount}));
  return {goods, deliveries, complete: !!page.querySelector('tr.log-item')?.querySelector('td.order-status-3')};
}"""


ORDER_DELIVERY = "\u8ba2\u5355\u53d1\u8d27"
NON_COST_TYPES = {"\u91c7\u8d2d\u6253\u6b3e", "\u9500\u552e\u8865\u53d1", "\u9500\u552e\u8d60\u9001"}


def valid_record(raw: dict):
    if raw.get("platform") not in PLATFORMS:
        return None
    delivery_type = raw.get("delivery_type")
    if delivery_type in NON_COST_TYPES:
        return None
    if delivery_type != ORDER_DELIVERY:
        # Missing or unknown type cannot fall back to an older cost or be retried as a timeout.
        raise ValueError("cost_delivery_type_unverified")
    record_id = str(raw.get("record_id") or "")
    if not re.fullmatch(r"\d+", record_id):
        return None
    try:
        cost = Decimal(str(raw.get("cny_per_1k")))
        trade_text = str(raw.get("trade_at")).strip()
        if re.fullmatch(r"\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", trade_text):
            traded = datetime.strptime(trade_text, "%y-%m-%d %H:%M:%S")
        else:
            traded = datetime.fromisoformat(trade_text.replace("/", "-"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not cost.is_finite() or cost <= 0 or traded.tzinfo is not None:
        return None
    trade_time = traded.replace(tzinfo=SHANGHAI)
    now = datetime.now(timezone.utc)
    if trade_time > now + timedelta(minutes=5) or trade_time < now - timedelta(days=8):
        return None
    return trade_time, {"game": "FC27", "product": "Game Coins",
                        "platform": raw["platform"], "record_id": record_id,
                        "traded_at": raw["trade_at"], "trade_at": raw["trade_at"],
                        "cny_per_k": str(cost), "cny_per_1k": str(cost),
                        "unit": "CNY/K", "status": "valid",
                        "delivery_type": ORDER_DELIVERY, "genre": "1",
                        "order_delivery": {key: raw.get(key) for key in ('order_id', 'quantity', 'gift', 'cost_total')}}


def shipment_number(value):
    try:
        number = Decimal(str(value).replace(',', ''))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def verified_delivery_cost(tab, record, order_cache):
    native = record['order_delivery']
    order_id = native['order_id']
    if not isinstance(order_id, str) or not re.fullmatch(r'\d+', order_id):
        return None
    if order_id not in order_cache:
        for _ in range(2):
            detail = tab.evaluate(READ_ORDER, order_id)
            if detail is None:
                raise ValueError('cost_order_detail_unavailable')
            if detail.get('timed_out') is not True:
                order_cache[order_id] = detail
                break
        else:
            raise ValueError('cost_order_detail_timeout')
    detail = order_cache[order_id]
    deliveries = detail['deliveries']
    matches = [delivery for delivery in deliveries if str(delivery['id']) == record['record_id']]
    if len(matches) != 1:
        return None
    delivery = matches[0]
    goods = [row for row in detail['goods'] if row['pid'] == delivery['pid']]
    if len(goods) != 1 or (goods[0]['gid'], goods[0]['cid'], goods[0]['unit']) != ('1322', '1', 'K'):
        return None
    quantity, gift, total = (shipment_number(native[key]) for key in ('quantity', 'gift', 'cost_total'))
    unit_cost = Decimal(record['cny_per_1k'])
    if (None in (quantity, gift, total) or (quantity, gift, total, unit_cost) !=
            tuple(shipment_number(delivery[key]) for key in ('qty', 'gift', 'total', 'price'))):
        return None
    purchased = shipment_number(goods[0]['qty'])
    delivered = quantity + gift
    if not purchased or not delivered or not total or abs(delivered * unit_cost - total) > Decimal('.01'):
        return None

    item_amounts = [(shipment_number(row['qty']), shipment_number(row['gift']))
                    for row in deliveries if row['pid'] == delivery['pid']]
    # A balancing shipment can hide a million-unit entry without adding real procurement.
    if len(item_amounts) > 1 and any(None not in pair and sum(pair) * 1000 == purchased
                                     for pair in item_amounts):
        return None
    scale = Decimal(1)
    if delivered * 1000 <= purchased:
        used = shipment_number(goods[0]['used'])
        # Order may correct the goods total before it corrects the underlying shipment.
        if (delivered * 1000 == purchased and detail['complete'] is True
                and used in (delivered, purchased) and len(item_amounts) == 1):
            scale = Decimal(1000)
        elif (used != purchased or any(None in pair for pair in item_amounts)
              or sum(sum(pair) for pair in item_amounts) != purchased):
            return None
    result = {key: value for key, value in record.items() if key != 'order_delivery'}
    result.update(cny_per_1k=str(unit_cost / scale), cny_per_k=str(unit_cost / scale),
                  quantity_evidence=dict(delivered_k=str(delivered * scale), ordered_k=str(purchased),
                                         native_quantity=str(delivered), native_unit='M' if scale == 1000 else 'K',
                                         total_cny=str(total)))
    return result


CollectorTimeoutError = PlaywrightTimeoutError


def timeout_diagnostic(exc):
    # Inspect only the API name; never emit exception text, URLs or page content.
    methods = ("BrowserType.connect_over_cdp", "BrowserContext.new_page",
               "Page.goto", "Page.evaluate", "Locator.click", "Page.close")
    method = next((name for name in methods if str(exc).startswith(name + ":")), None)
    codes = {"BrowserType.connect_over_cdp": "browser_connection_timeout",
             "BrowserContext.new_page": "page_create_timeout", "Page.goto": "page_navigation_timeout",
             "Page.evaluate": "page_read_timeout", "Locator.click": "platform_click_timeout",
             "Page.close": "page_close_timeout"}
    return codes.get(method, "collection_timeout"), {"api_method": method or "unrecorded"}


class CostPageError(ValueError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason)
        self.diagnostic = diagnostic


def read_page(page, number, observations=None, window=None):
    diagnostic = {"requested_page": number, "http_status": None,
                  "checked_at": datetime.now(timezone.utc).isoformat()}
    if window is not None:
        diagnostic['ps_window'] = {key: window[key].isoformat() for key in ('start', 'end')}
    try:
        response = page.goto(cost_url(number, window), wait_until="commit", timeout=35000)
    except PlaywrightTimeoutError:
        raise CostPageError(f"order_page_navigation_timeout:{number}", diagnostic) from None
    diagnostic["http_status"] = response.status if response is not None else None
    if diagnostic["http_status"] is not None and diagnostic["http_status"] >= 400:
        raise CostPageError(f"order_page_http_error:{number}:{response.status}", diagnostic)
    # A committed navigation may still be rendering. The page/filter checks below
    # ensure that no previous page or incomplete table can be treated as evidence.
    for _ in range(40):
        try:
            data = page.evaluate(READ_ROWS)
        except PlaywrightTimeoutError:
            raise CostPageError(f"order_page_read_timeout:{number}", diagnostic) from None
        diagnostic["observed"] = {k: data.get(k) for k in
                                  ("login", "ready", "page", "game", "area", "start", "end", "product", "genre", "typeHeader", "table", "hasDataRows", "empty", "deliveryRowCount")}
        if data.get("login"):
            raise CostPageError("login_expired", diagnostic)
        if window is not None and data.get('ready') not in ('interactive', 'complete'):
            page.wait_for_timeout(500)
            continue
        if (data.get("page") == str(number) and data.get("game") == "1322"
                and data.get("product") == "1" and data.get("genre") == "1"
                and data.get("typeHeader") == "\u4ea4\u8d27\u7c7b\u578b" and data.get("table") is True
                and (data["hasDataRows"] or data["empty"]
                     or window is not None and data.get("deliveryRowCount") == 0)):
            if window is not None and (
                    data.get('area') != window.get('area', '21942')
                    or data.get('start') != window['start'].strftime('%Y-%m-%d %H:%M')
                    or data.get('end') != window['end'].strftime('%Y-%m-%d %H:%M')
                    or not isinstance(data.get('deliveryRowCount'), int)
                    or data['deliveryRowCount'] != len(data['rows'])
                    or any((window.get('area', '21942') == '21942' and row.get('platform') != 'PS')
                           or row.get('delivery_type') != ORDER_DELIVERY for row in data['rows'])):
                raise CostPageError('cost_ps_filter_unverified', diagnostic)
            if observations is not None:
                observations.append(diagnostic)
            return data
        page.wait_for_timeout(500)
    raise CostPageError(f"filter_or_rows_unverified:{number}", diagnostic)


def remember(records, valid):
    if valid is None:
        return
    traded, record = valid
    key = int(record['record_id'])
    if key in records and records[key] != (traded, record):
        raise ValueError('cost_duplicate_record_conflict')
    records[key] = (traded, record)


def latest_ps(records, limit=6):
    return sorted((value for value in records.values() if value[1]['platform'] == 'PS'),
                  key=lambda value: (value[0], int(value[1]['record_id'])), reverse=True)[:limit]


def shared_console_cost(records, checked_at, boundary):
    samples = latest_ps(records)
    if len(samples) != 6:
        raise ValueError('ps_valid_delivery_sample_incomplete')
    if boundary.get('complete') is not True:
        raise ValueError('ps_valid_delivery_sample_boundary_unverified')
    observations = [{**row, 'checked_at': checked_at} for _, row in samples]
    selected = max(observations, key=lambda row: Decimal(row['cny_per_1k']))
    return dict(selected, source_platform='PS', sample_contract=CONSOLE_COST_CONTRACT,
                sample_complete=True, sample_records=observations, sample_boundary=boundary)


def collect_ps_cost(tab, observations, order_cache):
    end = datetime.now(SHANGHAI).replace(microsecond=0)
    for hours in (1, 2, 4, 8, 16, 32, 64, 128, 192):
        window = dict(start=end-timedelta(hours=hours), end=end)
        deliveries = {}
        complete = False
        for number in range(1, 16):
            data = read_page(tab, number, observations, window=window)
            for raw in data['rows']:
                valid = valid_record(raw)
                if valid and not window['start'] <= valid[0] <= window['end']:
                    raise ValueError('cost_time_window_filter_unverified')
                remember(deliveries, valid)
            if data['deliveryRowCount'] == 0:
                complete = True
                break
        if not complete:
            raise ValueError('ps_valid_delivery_sample_page_limit')
        verified = {}
        for traded, record in latest_ps(deliveries, limit=None):
            normal = verified_delivery_cost(tab, record, order_cache)
            if normal is not None:
                remember(verified, (traded, normal))
            if len(verified) == 6:
                break
        if len(verified) == 6:
            boundary = dict(complete=True, **{key: value.isoformat() for key, value in window.items()})
            return shared_console_cost(verified, datetime.now(timezone.utc).isoformat(), boundary)
    raise ValueError('ps_valid_delivery_sample_incomplete')


def collect_v6_delivery_samples(tab, observations, order_cache, confirmed_costs=None):
    """Read complete native time windows; ID order cannot prove a time boundary."""
    end = datetime.now(SHANGHAI).replace(microsecond=0)
    result = {p: dict(records=[], window_complete=False, history_complete=False) for p in PLATFORMS}
    for hours in (3, 6, 12, 24, 48, 96, 192):
        window = dict(start=end-timedelta(hours=hours), end=end, area='0')
        deliveries, complete = {}, False
        for page in range(1, 16):
            data = read_page(tab, page, observations, window=window)
            for raw in data['rows']:
                valid = valid_record(raw)
                if valid and not window['start'] <= valid[0] <= end:
                    raise ValueError('cost_time_window_filter_unverified')
                remember(deliveries, valid)
            if data['deliveryRowCount'] == 0:
                complete = True
                break
        if not complete:
            break
        verified = {p: [] for p in PLATFORMS}
        for _, record in sorted(deliveries.values(), key=lambda value: value[0], reverse=True):
            normal = verified_delivery_cost(tab, record, order_cache)
            if normal is not None:
                verified[record['platform']].append(normal)
        result = {p: dict(records=rows, window_complete=True, history_complete=hours == 192)
                  for p, rows in verified.items()}
        enough = []
        for platform, rows in verified.items():
            reference = (confirmed_costs or {}).get(platform)
            lower, upper = ((Decimal(str(reference)) / 2, Decimal(str(reference)) * 2)
                            if reference is not None else (Decimal('.05'), Decimal('5')))
            enough.append(sum(lower <= Decimal(row['cny_per_1k']) <= upper for row in rows) >= 6)
        if all(enough):
            break
    return result


def collect(*, curve_v6=False, confirmed_costs=None):
    config = {}
    with sync_playwright() as playwright:
        browser = open_backend(playwright)
        if len(browser.contexts) != 1:
            raise ValueError("browser_context_ambiguous")
        tab = browser.contexts[0].new_page()
        primary_error = None
        try:
            if curve_v6:
                observations = []
                samples = collect_v6_delivery_samples(tab, observations, {}, confirmed_costs)
                checked_at = datetime.now(timezone.utc).isoformat()
                records = []
                for platform in PLATFORMS:
                    rows = samples[platform]['records']
                    record = dict(rows[0] if rows else {}, platform=platform, checked_at=checked_at,
                                  v6_delivery_samples=samples[platform])
                    if not rows:
                        record.update(status='missing', reason='ordinary_delivery_cost_sample_missing')
                    records.append(record)
                return dict(status='valid', cost_protocol='fc27_curve_v6', checked_at=checked_at,
                            costs=records, page_observations=observations)
            # Preserve the existing PC rule and original page limit.
            candidates = {'XBOX': {}, 'PC': {}}
            observations = []
            for number in range(1, 16):
                data = read_page(tab, number, observations)
                for raw in data["rows"]:
                    valid = valid_record(raw)
                    if not valid:
                        continue
                    traded, record = valid
                    platform = record["platform"]
                    if platform in candidates:
                        remember(candidates[platform], valid)
                if not data["hasDataRows"] or data["empty"]:
                    break
            order_cache = {}
            console = collect_ps_cost(tab, observations, order_cache)
            found = {}
            for platform, deliveries in candidates.items():
                for _, candidate in sorted(deliveries.values(), key=lambda value: value[0], reverse=True):
                    normal = verified_delivery_cost(tab, candidate, order_cache)
                    if normal is not None:
                        found[platform] = normal
                        break
            checked_at = datetime.now(timezone.utc).isoformat()
            records = []
            for platform in PLATFORMS:
                if platform in ('PS', 'XBOX'):
                    record = dict(console, platform=platform)
                    if platform == 'XBOX' and platform in found:
                        record['observed_cost'] = {**found[platform], 'checked_at': checked_at}
                    records.append(record)
                elif platform in found:
                    records.append({**found[platform], "checked_at": checked_at})
                else:
                    records.append({"platform": platform, "status": "missing",
                                    "reason": "no_valid_recent_record"})
            return {"status": "valid" if all(r["status"] == "valid" for r in records) else "incomplete",
                    "checked_at": checked_at, "costs": records, "page_observations": observations}
        except Exception as exc:
            primary_error = exc
            raise
        finally:
            try:
                close_backend(tab)
            except Exception:
                if primary_error is None:
                    raise


def failure_result(exc):
    reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    if isinstance(exc, RuntimeError) and str(exc).startswith('global_order_unavailable:'):
        category = str(exc).split(':', 1)[1]
        reason = ('global_order_transport_unavailable' if category in {
            'TimeoutError', 'OSError', 'ConnectionError', 'ConnectionRefusedError',
            'ConnectionResetError', 'BrokenPipeError', 'FileNotFoundError',
            'no_socket', 'order_probe_unavailable'} else 'global_order_session_unavailable')
    result = {"status": "missing", "reason": reason[:120], "diagnostic": {
        "exception_type": type(exc).__name__,
        "stack": [{"file": os.path.basename(frame.filename), "function": frame.name,
                   "line": frame.lineno} for frame in traceback.extract_tb(exc.__traceback__)[-8:]]}}
    if isinstance(exc, CollectorTimeoutError):
        result["reason"], diagnostic = timeout_diagnostic(exc)
        result["diagnostic"].update(diagnostic)
    if isinstance(exc, CostPageError):
        result["diagnostic"].update(exc.diagnostic)
    return result


if __name__ == "__main__":
    try:
        references = os.environ.get('FC_V6_COST_REFERENCES')
        result = collect(curve_v6=references is not None,
                         confirmed_costs=json.loads(references) if references is not None else None)
        print(json.dumps(result))
        raise SystemExit(0 if result["status"] == "valid" else 1)
    except Exception as exc:
        print(json.dumps(failure_result(exc)))
        raise SystemExit(1)

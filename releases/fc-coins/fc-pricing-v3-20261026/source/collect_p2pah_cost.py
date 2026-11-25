"""Read current FC27 Game Coins procurement records over Order HTTP."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from order_http import OrderHTTP, OrderReadError, is_timeout

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from itertools import islice
import json
import os
import re
import traceback
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

PLATFORMS = ("PS", "XBOX", "PC")
SHANGHAI = ZoneInfo("Asia/Shanghai")
CONSOLE_COST_CONTRACT = 'ps_latest_six_valid_order_delivery_max_v1'


def cost_query(page: int, window=None) -> dict:
    today = datetime.now(SHANGHAI).date()
    query = {"gid": "1322", "aid": "0", "cid": "1",
             "start": str(today - timedelta(days=7)) + " 00:00",
             "end": str(today + timedelta(days=1)) + " 00:00",
             "show_ccy": "-1", "genre": "1", "status": "-1", "op_id": "0",
             "is_stock": "", "keyword": "", "sn": "", "page": str(page)}
    if window is not None:
        query.update(aid=window.get('area', '21942'), start=window['start'].strftime('%Y-%m-%d %H:%M:%S'),
                     end=window['end'].strftime('%Y-%m-%d %H:%M:%S'))
    return query


def broker_failure(reason):
    prefix, _, category = reason.partition(':')
    if prefix != 'global_order_unavailable':
        return None
    if category.startswith('transport:') or category in {
            'TimeoutError', 'OSError', 'ConnectionError', 'ConnectionRefusedError',
            'ConnectionResetError', 'BrokenPipeError', 'FileNotFoundError', 'no_socket',
            'order_probe_unavailable', 'order_probe_transport_unavailable',
            'order_probe_wait_timeout', 'order_login_transport_unavailable', 'order_login_deadline'}:
        return 'global_order_transport_unavailable'
    return 'global_order_session_unavailable'


def read_detail(reader, order_id, timeout_ms):
    result = reader.order_detail(order_id, timeout=timeout_ms / 1000)
    if result.status == 'timeout':
        return {'timed_out': True}
    if result.status == 'login_lost':
        raise ValueError('login_expired')
    if reason := broker_failure(result.reason):
        raise ValueError(reason)
    if result.status != 'found':
        return None
    return dict(goods=list(result.goods), deliveries=list(result.deliveries), complete=result.complete)


def read_detail_pair(reader, order_ids):
    def read(order_id):
        result = read_detail(reader, order_id, 8000)
        if result is not None and result.get('timed_out'):
            return read_detail(reader, order_id, 16000)
        return result

    with ThreadPoolExecutor(max_workers=len(order_ids)) as executor:
        futures = [executor.submit(read, order_id) for order_id in order_ids]
    for future in futures:
        if future.exception():
            raise future.exception()
        result = future.result()
        if result is None or result.get('timed_out'):
            break
    return [future.result() if future.exception() is None else None for future in futures]


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


def delivery_order_id(record):
    order_id = record['order_delivery']['order_id']
    return order_id if isinstance(order_id, str) and re.fullmatch(r'\d+', order_id) else None


def verified_delivery_cost(reader, record, order_cache, *, retry_timeout_ms=8000):
    native = record['order_delivery']
    order_id = delivery_order_id(record)
    if order_id is None:
        return None
    if order_id not in order_cache:
        for timeout_ms in (8000, retry_timeout_ms):
            detail = read_detail(reader, order_id, timeout_ms)
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


class CostPageError(ValueError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason)
        self.diagnostic = diagnostic


def read_page(reader, number, observations=None, window=None):
    diagnostic = {"requested_page": number, "http_status": None,
                  "checked_at": datetime.now(timezone.utc).isoformat()}
    if window is not None:
        diagnostic['ps_window'] = {key: window[key].isoformat() for key in ('start', 'end')}
    try:
        page = reader.delivery_page(cost_query(number, window), timeout=35)
    except OSError as exc:
        if isinstance(exc, HTTPError):
            diagnostic['http_status'] = exc.code
            if exc.fp is not None:
                exc.close()
            raise CostPageError(f'order_page_http_error:{number}:{exc.code}', diagnostic) from None
        reason = 'order_page_navigation_timeout' if is_timeout(exc) else 'order_page_transport_error'
        raise CostPageError(f'{reason}:{number}', diagnostic) from None
    except OrderReadError as exc:
        reason = ('login_expired' if str(exc) == 'login_lost'
                  else broker_failure(str(exc)) or f'filter_or_rows_unverified:{number}')
        raise CostPageError(reason, diagnostic) from exc
    diagnostic['http_status'] = 200
    fields = page.filters
    game, area, product, genre = (fields.get('lot-' + name) for name in ('game', 'area', 'type', 'genre'))
    start, end = fields.get('lot-start'), fields.get('lot-end')
    headers = page.headers
    type_header = headers[2] if len(headers) > 2 else None
    observed = diagnostic['observed'] = dict(
        login=False, ready='complete', page=str(number), game=game, area=area,
        start=start, end=end, product=product, genre=genre, typeHeader=type_header,
        table=True, hasDataRows=bool(page.rows),
        empty=page.explicit_empty or (window is not None and not page.rows), deliveryRowCount=len(page.rows))
    if (game, product, genre, type_header) != ('1322', '1', '1', '交货类型') or len(headers) < 11:
        raise CostPageError(f'filter_or_rows_unverified:{number}', diagnostic)
    if not observed['hasDataRows'] and not observed['empty']:
        raise CostPageError(f'filter_or_rows_unverified:{number}', diagnostic)
    # These are the column positions verified by the former Order DOM reader.
    # The known Order headers anchor the layout before those fields are consumed.
    if headers[4] != '商户订单号' or any(
            not headers[index] for index in (1, 5, 6, 7, 8, 9, 10)):
        raise CostPageError(f'filter_or_rows_unverified:{number}', diagnostic)
    rows = []
    for row, order_id in zip(page.rows, page.order_ids):
        match = re.fullmatch(r'FC\s*27\s*▶\s*(PS|XBOX|PC)', row[headers[6]], re.I)
        if match:
            rows.append(dict(platform=match[1].upper(), record_id=row[headers[1]],
                             delivery_type=row[type_header], trade_at=row[headers[5]],
                             cny_per_1k=row[headers[9]], order_id=order_id,
                             quantity=row[headers[7]], gift=row[headers[8]], cost_total=row[headers[10]]))
    data = dict(rows=rows, **{key: observed[key] for key in ('hasDataRows', 'empty', 'deliveryRowCount')})
    if window is not None and (
            area != window.get('area', '21942')
            or start != window['start'].strftime('%Y-%m-%d %H:%M')
            or end != window['end'].strftime('%Y-%m-%d %H:%M')
            or len(page.rows) != len(rows)
            or any((area == '21942' and row['platform'] != 'PS')
                   or row['delivery_type'] != ORDER_DELIVERY for row in rows)):
        raise CostPageError('cost_ps_filter_unverified', diagnostic)
    if observations is not None:
        observations.append(diagnostic)
    return data


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


def collect_ps_cost(reader, observations, order_cache):
    end = datetime.now(SHANGHAI).replace(microsecond=0)
    for hours in (1, 2, 4, 8, 16, 32, 64, 128, 192):
        window = dict(start=end-timedelta(hours=hours), end=end)
        deliveries = {}
        complete = False
        for number in range(1, 16):
            data = read_page(reader, number, observations, window=window)
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
            normal = verified_delivery_cost(reader, record, order_cache)
            if normal is not None:
                remember(verified, (traded, normal))
            if len(verified) == 6:
                break
        if len(verified) == 6:
            boundary = dict(complete=True, **{key: value.isoformat() for key, value in window.items()})
            return shared_console_cost(verified, datetime.now(timezone.utc).isoformat(), boundary)
    raise ValueError('ps_valid_delivery_sample_incomplete')


def list_verified_cost(record, reference, repeated_orders):
    order_id = delivery_order_id(record)
    if reference is None or order_id is None or order_id in repeated_orders:
        return None
    price = Decimal(record['cny_per_1k'])
    if not reference * Decimal('.7') <= price <= reference * Decimal('1.3'):
        return None
    native = record['order_delivery']
    quantity, gift, total = (shipment_number(native[key]) for key in ('quantity', 'gift', 'cost_total'))
    if None in (quantity, gift, total):
        return None
    delivered = quantity + gift
    if not delivered or not total or abs(price * delivered - total) > Decimal('.01'):
        return None
    result = {key: value for key, value in record.items() if key != 'order_delivery'}
    return dict(result, verification='list_fast_path',
                quantity_evidence=dict(delivered_k=str(delivered), ordered_k=None,
                                       native_quantity=str(delivered), native_unit='K',
                                       total_cny=str(total)))


def verified_v6_deliveries(reader, deliveries, order_cache, timed_out, list_verified):
    order_platforms = {}
    for _, record in deliveries:
        if record['record_id'] in list_verified:
            continue
        order_id = delivery_order_id(record)
        if order_id is not None:
            order_platforms.setdefault(order_id, set()).add(record['platform'])
    pending = (order_id for order_id, platforms in order_platforms.items()
               if order_id not in order_cache and not platforms <= timed_out)
    prefetched = {}
    for _, record in deliveries:
        if record['platform'] in timed_out:
            continue
        if record['record_id'] in list_verified:
            yield record, list_verified[record['record_id']]
            continue
        order_id = delivery_order_id(record)
        if order_id is not None and order_id not in order_cache:
            if order_id not in prefetched:
                pair = [order_id]
                mate = next((candidate for candidate in pending
                             if candidate != order_id and candidate not in prefetched), None)
                if mate is not None:
                    pair.append(mate)
                details = read_detail_pair(reader, pair)
                if not isinstance(details, list) or len(details) != len(pair):
                    raise ValueError('cost_order_detail_response_unverified')
                prefetched.update(zip(pair, details))
            detail = prefetched.pop(order_id)
            if detail is None:
                raise ValueError('cost_order_detail_unavailable')
            if not isinstance(detail, dict):
                raise ValueError('cost_order_detail_response_unverified')
            if detail.get('timed_out') is not True and (
                    type(detail.get('complete')) is not bool or not isinstance(detail.get('goods'), list)
                    or not isinstance(detail.get('deliveries'), list)):
                raise ValueError('cost_order_detail_response_unverified')
            order_cache[order_id] = detail
        # Validate in source order before staging a subsequent pair.
        if order_cache.get(order_id, {}).get('timed_out') is True:
            timed_out.update(order_platforms[order_id])
            continue
        normal = verified_delivery_cost(reader, record, order_cache, retry_timeout_ms=16000)
        yield record, dict(normal, verification='order_detail') if normal is not None else None


def collect_v6_delivery_samples(reader, observations, order_cache, confirmed_costs=None):
    """Verify the latest three hours and, where needed, the latest six qualified rows."""
    end = datetime.now(SHANGHAI).replace(microsecond=0)
    recent_start = end - timedelta(hours=3)
    result = {p: dict(records=[], window_complete=False, history_complete=False) for p in PLATFORMS}
    references = {p: (confirmed_costs or {}).get(p) for p in PLATFORMS}
    bounds = {p: (Decimal(str(ref)) / 2, Decimal(str(ref)) * 2) if ref is not None
              else (Decimal('.05'), Decimal('5')) for p, ref in references.items()}
    list_references = {p: Decimal(str(ref)) if ref is not None else None for p, ref in references.items()}
    previous = None
    first_delivery_by_order = {}
    repeated_orders = set()
    timed_out = set()
    for hours in (3, 6, 12, 24, 48, 96, 192):
        start = end - timedelta(hours=hours)
        window = dict(start=start, end=end, area='0')
        deliveries = {}
        orders_in_window = set()
        for page in range(1, 16):
            data = read_page(reader, page, observations, window=window)
            for raw in data['rows']:
                # Widening the window rereads earlier rows. Count new deliveries
                # across windows and repeated appearances within a single scan.
                order_id = raw.get('order_id')
                if order_id is not None:
                    first_delivery = first_delivery_by_order.setdefault(order_id, raw['record_id'])
                    if order_id in orders_in_window or raw['record_id'] != first_delivery:
                        repeated_orders.add(order_id)
                    orders_in_window.add(order_id)
                valid = valid_record(raw)
                if valid and not start <= valid[0] <= end:
                    raise ValueError('cost_time_window_filter_unverified')
                remember(deliveries, valid)
            if data['deliveryRowCount'] == 0:
                break
        else:
            break

        # Full windows still catch late inserts, removals and changes. Refresh any
        # same-round detail whose listing changed or whose order gained a row.
        if previous is not None:
            for key in previous.keys() | deliveries.keys():
                before, after = previous.get(key), deliveries.get(key)
                if before != after:
                    for value in (before, after):
                        if value is not None:
                            order_cache.pop(delivery_order_id(value[1]), None)
        previous = deliveries

        list_verified = {}
        for _, record in deliveries.values():
            normal = list_verified_cost(record, list_references[record['platform']], repeated_orders)
            if normal is not None:
                list_verified[record['record_id']] = normal
        ordered = sorted(deliveries.values(), key=lambda item: item[0], reverse=True)
        recent = [item for item in ordered if item[0] >= recent_start]
        older = {p: [] for p in PLATFORMS}
        for item in ordered[len(recent):]:
            older[item[1]['platform']].append(item)
        verified = {p: [] for p in PLATFORMS}
        for record, normal in verified_v6_deliveries(reader, recent, order_cache, timed_out, list_verified):
            if normal is not None:
                verified[record['platform']].append(normal)

        enough = []
        for platform, records in verified.items():
            if platform in timed_out:
                continue
            lower, upper = bounds[platform]
            within_bounds = sum(lower <= Decimal(row['cny_per_1k']) <= upper for row in records)
            candidates = iter(sorted(older[platform], key=lambda item: (item[0], item[1]['record_id']),
                                     reverse=True))
            inspected = 0
            while within_bounds < 6 and platform not in timed_out:
                batch = list(islice(candidates, min(2, 6 - within_bounds)))
                if not batch:
                    break
                inspected += len(batch)
                for _, normal in verified_v6_deliveries(reader, batch, order_cache, timed_out, list_verified):
                    if normal is not None:
                        records.append(normal)
                        within_bounds += lower <= Decimal(normal['cny_per_1k']) <= upper
            if platform in timed_out:
                continue
            unchecked = len(older[platform]) - inspected
            scope = dict(list_start=start.isoformat(), list_end=end.isoformat(),
                         full_detail_start=recent_start.isoformat(), older_detail_rows_checked=inspected,
                         older_detail_rows_not_checked=unchecked)
            if unchecked:
                scope['qualification_reference_cny_per_k'] = references[platform]
            result[platform] = dict(records=records, window_complete=True,
                                    history_complete=hours == 192 and not unchecked, detail_scope=scope)
            enough.append(within_bounds >= 6)
        if all(enough):
            break
    for platform in timed_out:
        result[platform] = dict(records=[], window_complete=False, history_complete=False,
                                reason='cost_order_detail_timeout')
    return result


def collect(*, curve_v6=False, confirmed_costs=None):
    reader = OrderHTTP()
    if curve_v6:
        observations = []
        samples = collect_v6_delivery_samples(reader, observations, {}, confirmed_costs)
        checked_at = datetime.now(timezone.utc).isoformat()
        records = []
        for platform in PLATFORMS:
            rows = samples[platform]['records']
            record = dict(rows[0] if rows else {}, platform=platform, checked_at=checked_at,
                          v6_delivery_samples=samples[platform])
            if not rows:
                record.update(status='missing', reason=samples[platform].get(
                    'reason', 'ordinary_delivery_cost_sample_missing'))
            records.append(record)
        return dict(status='valid', cost_protocol='fc27_curve_v6', checked_at=checked_at,
                    costs=records, page_observations=observations)
    # Preserve the existing PC rule and original page limit.
    candidates = {'XBOX': {}, 'PC': {}}
    observations = []
    for number in range(1, 16):
        data = read_page(reader, number, observations)
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
    console = collect_ps_cost(reader, observations, order_cache)
    found = {}
    for platform, deliveries in candidates.items():
        for _, candidate in sorted(deliveries.values(), key=lambda value: value[0], reverse=True):
            normal = verified_delivery_cost(reader, candidate, order_cache)
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


def failure_result(exc):
    reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    if isinstance(exc, RuntimeError):
        reason = broker_failure(str(exc)) or reason
    result = {"status": "missing", "reason": reason[:120], "diagnostic": {
        "exception_type": type(exc).__name__,
        "stack": [{"file": os.path.basename(frame.filename), "function": frame.name,
                   "line": frame.lineno} for frame in traceback.extract_tb(exc.__traceback__)[-8:]]}}
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

"""Read-only paid-order association for existing dedicated campaign codes.

This is order association, not a browser conversion or a product-line allocation.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import json
import time

from .core import ContractError, Money, canonical, identity

SOURCE_TZ = timezone(timedelta(hours=8))
BINDINGS = (
    ('6025', 'HWFC08', '1327', 8), ('6029', 'HWFC10', '1327', 10), ('6027', 'HWFC15', '1327', 15),
    ('6031', 'HWAION08', '891', 8), ('6035', 'HWAION10', '891', 10), ('6033', 'HWAION15', '891', 15),
    ('6043', 'HWMAPLE08', '1333', 8), ('6047', 'HWMAPLE10', '1333', 10), ('6045', 'HWMAPLE15', '1333', 15),
    ('6091', 'HWD408', '456', 8), ('6093', 'HWD410', '456', 10), ('6085', 'HWD415', '456', 15),
)

FC_BINDINGS = (('6049', 'FCSCOUT10', '1327', 10),)

def campaign_bindings(activity):
    if activity == 'mmoexp-seasonal':
        return BINDINGS
    if activity == 'fc27-season2':
        return FC_BINDINGS
    raise ContractError('ACTIVITY_SCOPE_REQUIRED')


def query_window(request):
    if set(request) - {'action', 'site_id', 'from', 'to', 'game', 'activity'} or request.get('site_id') != '266':
        raise ContractError('PROJECT_SITE_REQUIRED')
    try:
        start, end = (datetime.strptime(request[k], '%Y-%m-%d').replace(tzinfo=timezone.utc) for k in ('from', 'to'))
        if any(request[k] != v.strftime('%Y-%m-%d') for k, v in (('from', start), ('to', end))):
            raise ValueError()
        if not 0 <= (end - start).days <= 30:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ContractError('MAX_31_DAY_UTC_WINDOW_REQUIRED') from None
    activity = request.get('activity', 'mmoexp-seasonal')
    game = request.get('game', 'all')
    if activity == 'mmoexp-carnival' and request.get('action') == 'coupon_usage':
        if game != 'all':
            raise ContractError('GAME_SCOPE_REQUIRED')
    else:
        campaign_bindings(activity)
    if activity == 'fc27-season2' and game not in ('all', '1327'):
        raise ContractError('GAME_SCOPE_REQUIRED')
    if game not in ('all', '1327', '891', '1333', '456'):
        raise ContractError('GAME_SCOPE_REQUIRED')
    return start.astimezone(SOURCE_TZ), (end + timedelta(days=1)).astimezone(SOURCE_TZ), game


def amount(row):
    raw = row.get('amount_usd_format')
    if not isinstance(raw, str) or not re.fullmatch(r'\$\s*(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', raw):
        raise ContractError('USD_ORDER_AMOUNT_REQUIRED')
    usd = Money.parse(raw.replace('$', '').replace(',', '').strip(), 'USD', {'USD': 2}).minor
    parts, currency = row.get('pay_money_format2'), row.get('currency_code')
    if (not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency)
            or not isinstance(parts, list) or len(parts) != 2
            or not isinstance(parts[0], str) or not re.fullmatch('[A-Z]{3}', parts[0])
            or not isinstance(parts[1], str) or not re.fullmatch(r'\d{1,15}(?:\.\d{1,6})?', parts[1])):
        raise ContractError('PAID_CURRENCY_AMOUNT_REQUIRED')
    # Original payment currency and the Admin display currency can differ after conversion.
    return usd, parts[0], Decimal(parts[1])


def summarize(rows, start, end, game, activity='mmoexp-seasonal'):
    bindings = campaign_bindings(activity)
    codes = {code.casefold(): (native, code, gid, off) for native, code, gid, off in bindings}
    buckets = {code: dict(native_id=native, code=code, game_id=gid, off_percent=off,
                          paid_orders=0, paid_usd_minor=0, refunded_orders=0)
               for native, code, gid, off in bindings if game in ('all', gid)}
    currencies, seen = defaultdict(Decimal), {}
    excluded_unpaid = 0
    for row in rows:
        code = row.get('discount_code')
        if not isinstance(code, str) or code.strip().casefold() not in codes or str(row.get('site_id')) != '266':
            raise ContractError('DISCOUNT_ORDER_SCOPE_MISMATCH')
        native, code, gid, off = codes[code.strip().casefold()]
        if str(row.get('gid')) != gid:
            raise ContractError('DISCOUNT_ORDER_GAME_MISMATCH')
        try:
            paid_at = datetime.strptime(row['paytime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=SOURCE_TZ)
            if not start <= paid_at < end:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ContractError('PAYMENT_TIME_SCOPE_MISMATCH') from None
        number = identity(row.get('order_no'))
        signature = canonical({k: row.get(k) for k in ('site_id', 'gid', 'pay_status', 'paytime', 'discount_code',
                                                      'amount_usd_format', 'currency_code', 'pay_money_format2')})
        if number in seen:
            if seen[number] != signature:
                raise ContractError('CONFLICTING_DUPLICATE_ORDER')
            continue
        seen[number] = signature
        state = row.get('pay_status')
        if type(state) not in (int, str) or state not in (0, 1, 2, '0', '1', '2'):
            raise ContractError('PAYMENT_STATE_UNKNOWN')
        if state in (0, '0'):
            excluded_unpaid += 1
            continue
        if game not in ('all', gid):
            continue
        usd, currency, paid = amount(row)
        bucket = buckets[code]
        bucket['paid_orders'] += 1
        bucket['paid_usd_minor'] += usd
        # Refunded orders retain their payment observation; no unverified refund amount is invented.
        bucket['refunded_orders'] += int(state in (2, '2'))
        currencies[currency] += paid
    totals = {k: sum(b[k] for b in buckets.values()) for k in ('paid_orders', 'paid_usd_minor', 'refunded_orders')}
    if totals['paid_usd_minor'] > 9007199254740991:
        raise ContractError('REPORT_MONEY_EXCEEDS_SAFE_INTEGER')
    return dict(status='available', basis='dedicated_discount_code_paid_order', activity_id=activity,
                attribution_level='shared_activity_group' if activity == 'fc27-season2' else 'activity_group',
                page_allocation='not_available',
                totals=totals, codes=list(buckets.values()),
                paid_currencies=[dict(currency=k, amount=format(v, 'f')) for k, v in sorted(currencies.items())],
                refund_amount=None, net_amount=None, product_allocation='not_available', visitor_join='not_available',
                coverage=dict(complete=True, source_rows=len(rows), unique_orders=len(seen), excluded_unpaid=excluded_unpaid),
                period=dict(start=start.astimezone(timezone.utc).isoformat(), end_exclusive=end.astimezone(timezone.utc).isoformat(), timezone='UTC'),
                generated_at=datetime.now(timezone.utc).isoformat(),
                note='按付款时间和专属码关联整单；退款保留付款记录另列，不是商品分摊收入或访客转化率。')


def read_revenue(reader, request):
    deadline = time.monotonic() + 90
    start, end, game = query_window(request)
    activity = request.get('activity', 'mmoexp-seasonal')
    ids = {native: code for native, code, _, _ in campaign_bindings(activity)}
    # Include global-site collisions; a same-code record outside the approved IDs is ambiguous.
    natives = reader.pages('discounts', [('site_id', 'IN', '0,266'), ('code', 'IN', ','.join(ids.values()))],
                           validate=lambda r: str(r.get('id')) in ids and str(r.get('site_id')) in ('0', '266'))
    if ({str(r['id']) for r in natives} != set(ids)
            or any(str(r.get('code', '')).strip().casefold() != ids[str(r['id'])].casefold() for r in natives)):
        raise ContractError('ACTIVITY_CODE_IDENTITY_MISMATCH')
    rows, cursor = [], start
    while cursor < end:
        stop = min(end, cursor + timedelta(days=28))
        lo, hi = cursor.strftime('%Y-%m-%d %H:%M:%S'), (stop - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        rows.extend(reader.pages('orders', [('site_id', '=', '266'), ('paytime', 'RANGE', lo + ',' + hi),
                                           ('discount_code', 'IN', ','.join(ids.values()))]))
        cursor = stop
    result = summarize(rows, start, end, game, activity)
    if activity == 'fc27-season2':
        read_lines = getattr(reader, 'read_order_lines', None)
        if read_lines is None and hasattr(reader, 'session') and result['totals']['paid_orders']:
            from .order_lines import OrderLineReader
            read_lines = OrderLineReader(reader.session).read
        result['product_sales'] = product_sales(rows, read_lines, deadline=deadline)
    return result


def product_sales(rows, read_lines=None, *, deadline=None, clock=time.monotonic):
    """Only code-attributed paid orders enter this reader; Order item identities stay explicit."""
    paid = {identity(r.get('order_no')): r for r in rows if r.get('pay_status') in (1, 2, '1', '2')}
    eligible, covered, buckets, reason = len(paid), 0, {}, None
    for number, row in paid.items():
        if read_lines is None:
            reason = 'VERIFIED_ORDER_LINES_UNAVAILABLE'; break
        remaining = (deadline - clock()) if deadline is not None else 20
        if remaining <= 1:
            reason = 'ORDER_LINES_TIME_BUDGET'; break
        try:
            lines = read_lines(number, timeout=min(remaining, 20))
            # Validate a whole order before counting any of it, so missing lines never look complete.
            checked = []
            if not isinstance(lines, list): raise ContractError('ORDER_LINES_CONTRACT')
            for line in lines:
                if line.get('game_id') != '1322' or line.get('category_id') != '2': continue
                pid, aid = identity(line.get('product_id')), identity(line.get('attribute_id'))
                qty = str(line.get('quantity', ''))
                if not re.fullmatch(r'\d{1,16}(?:\.\d{1,6})?', qty) or Decimal(qty) <= 0: raise ContractError('ORDER_LINE_QUANTITY_INVALID')
                title, unit = line.get('title'), line.get('unit')
                if not isinstance(title, str) or not title.strip() or len(title) > 500 or not isinstance(unit, str) or not unit or len(unit) > 40: raise ContractError('ORDER_LINES_CONTRACT')
                checked.append((pid, aid, qty, title, unit, str(line.get('platform') or aid)))
        except TimeoutError:
            reason = 'ORDER_LINES_TIME_BUDGET'; break
        except (ContractError, OSError):
            reason = 'VERIFIED_ORDER_LINES_UNAVAILABLE'; continue
        per_order = {}
        for pid, aid, qty, title, unit, platform in checked:
            key = (pid, aid, unit)
            if key not in per_order: per_order[key] = dict(product_id=pid, attribute_id=aid, title=title, platform=platform, unit=unit, quantity=Decimal(0))
            per_order[key]['quantity'] += Decimal(qty)
        candidate = {key: dict(value) for key, value in buckets.items()}
        for key, value in per_order.items():
            bucket = candidate.setdefault(key, {**value, 'quantity': Decimal(0), 'paid_orders': 0, 'refunded_orders': 0, 'refunded_quantity': Decimal(0)})
            bucket['paid_orders'] += 1; bucket['quantity'] += value['quantity']
            if row['pay_status'] in (2, '2'):
                bucket['refunded_orders'] += 1; bucket['refunded_quantity'] += value['quantity']
        if len(json.dumps(list(candidate.values()),ensure_ascii=False,default=str).encode('utf-8')) > 1000000:
            reason = 'ORDER_LINES_RESPONSE_LIMIT'; break
        buckets = candidate
        covered += 1
    output=[]
    for key in sorted(buckets):
        row=buckets[key]; output.append({**row, 'quantity':format(row['quantity'],'f'), 'refunded_quantity':format(row['refunded_quantity'],'f'), 'line_amounts':[]})
    complete=covered==eligible
    return dict(status='available' if complete else 'partial' if covered else 'unavailable',
        reason=None if complete else reason or 'VERIFIED_ORDER_LINES_UNAVAILABLE', identity_source='order',
        rows=output if covered or not eligible else None,
        coverage=dict(complete=complete,eligible_paid_orders=eligible,covered_paid_orders=covered),
        amount_status='not_allocated', refunds_included=True)


# ---------------------------------------------------------------------------
# Unified FC27 activity coupon (replaces the three per-page codes for new orders)
# ---------------------------------------------------------------------------
# The coupon record carries cumulative issued/used counters; each use is one row in
# user.MemberCouponLog (filterable by coupon template) with the order number, the order price,
# the coupon discount, the amount actually paid and the 90-day repurchase figures. Log status
# 1 is a paid order and 0 is a coupon applied to an order that is not paid (the Admin page
# shows this as the order payment status). The Admin order list is only used to see refunds:
# some logged orders are not in it, so a missing order never fails the whole read.
# Per-day issuance is not read: the conversion from issued to used is cumulative (coupon counters)
# and the window counts uses, with their order amounts, straight from the log.
FC_COUPON = dict(id='1395', param_code='carnival_202611', site_id='266', game_id='1327')
CARNIVAL_SITE_ID = '266'
CARNIVAL_COUPON_PARAM = 'carnival_202611'
# Admin has only the odd-numbered templates in the approved ranges.
CARNIVAL_COUPONS = {
    'home': (1399,),
    'mystery': tuple(range(1401, 1436, 2)),
    'blackFriday': (*range(1443, 1500, 2), 1513, 1515),
    'capsule': tuple(range(1501, 1512, 2)),
}
COUPON_ORDER_CHUNK = 40


def coupon_money(value, code):
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not re.fullmatch(r'\d{1,12}(?:\.\d{1,2})?', str(value).strip()):
        raise ContractError(code)
    return Money.parse(str(value).strip(), 'USD', {'USD': 2}).minor


def coupon_counter(row, key):
    value = row.get(key)
    if type(value) is str and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        raise ContractError('COUPON_COUNTER_INVALID')
    return value


def coupon_record(row, expected=FC_COUPON):
    if (str(row.get('id')) != expected['id'] or str(row.get('site_id')) != expected['site_id']
            or ('game_id' in expected and str(row.get('game_id')) != expected['game_id'])
            or row.get('param_code') != expected['param_code']):
        raise ContractError('ACTIVITY_COUPON_IDENTITY_MISMATCH')
    return dict(coupon_id=expected['id'], title=str(row.get('title') or '')[:120], param_code=row['param_code'],
                issued_total=coupon_counter(row, 'fetch_qty'), used_total=coupon_counter(row, 'used_qty'),
                limit_qty=coupon_counter(row, 'limit_qty'), valid_days=coupon_counter(row, 'days'))


def summarize_coupon_usage(coupon, logs, orders, start, end, coupon_ids=(FC_COUPON['id'],)):
    """logs: MemberCouponLog rows in the window; orders: whichever Admin orders exist for those logs."""
    by_order = {}
    fields = ('pay_status', 'paytime', 'amount_usd_format')
    for row in orders:
        number = identity(str(row.get('order_no')))
        if str(row.get('site_id')) != FC_COUPON['site_id']:
            raise ContractError('COUPON_ORDER_SCOPE_MISMATCH')
        if number in by_order and canonical({k: row.get(k) for k in fields}) != canonical({k: by_order[number].get(k) for k in fields}):
            raise ContractError('CONFLICTING_DUPLICATE_ORDER')
        by_order[number] = row
    totals = dict(used_orders=0, paid_orders=0, refunded_orders=0, unpaid_orders=0, paid_usd_minor=0,
                  discount_usd_minor=0, repurchase_orders=0, repurchase_usd_minor=0, unique_buyers=0)
    coverage = dict(complete=True, logs=len(logs), unique_uses=0, orders_read=len(by_order), orders_unmatched=0, amounts_from_log=0)
    buyers, daily, seen = set(), {}, {}
    for log in logs:
        if str(log.get('site_id')) != FC_COUPON['site_id'] or str(log.get('coupon_id')) not in coupon_ids:
            raise ContractError('COUPON_LOG_SCOPE_MISMATCH')
        if log.get('status') not in (0, 1, '0', '1'):
            raise ContractError('COUPON_LOG_STATE_UNKNOWN')
        try:
            used_at = datetime.strptime(log['use_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=SOURCE_TZ)
            if not start <= used_at < end:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ContractError('COUPON_USE_TIME_SCOPE_MISMATCH') from None
        number = identity(str(log.get('order_no')))
        signature = canonical({k: log.get(k) for k in ('coupon_id', 'member_id', 'use_time', 'discount_amount', 'status')})
        if number in seen:
            if seen[number] != signature:
                raise ContractError('CONFLICTING_DUPLICATE_COUPON_USE')
            continue
        seen[number] = signature
        order = by_order.get(number)
        state = order.get('pay_status') if order else None
        if order is not None and (type(state) not in (int, str) or state not in (0, 1, 2, '0', '1', '2')):
            raise ContractError('PAYMENT_STATE_UNKNOWN')
        if order is None:
            coverage['orders_unmatched'] += 1
        # The order, when present, decides paid/refunded; otherwise the log's own status does.
        paid = state in (1, 2, '1', '2') if order is not None else log.get('status') in (1, '1')
        day = used_at.astimezone(timezone.utc).strftime('%Y-%m-%d')
        bucket = daily.setdefault(day, dict(date=day, used_orders=0, paid_orders=0, paid_usd_minor=0))
        totals['used_orders'] += 1
        bucket['used_orders'] += 1
        if not paid:
            totals['unpaid_orders'] += 1
            continue
        logged = log.get('order') if isinstance(log.get('order'), dict) else {}
        if order is not None:
            usd, _, _ = amount(order)
        else:
            usd = coupon_money(logged.get('amount'), 'COUPON_LOG_AMOUNT_INVALID')
            coverage['amounts_from_log'] += 1
        totals['paid_orders'] += 1
        totals['paid_usd_minor'] += usd
        bucket['paid_orders'] += 1
        bucket['paid_usd_minor'] += usd
        totals['refunded_orders'] += int(state in (2, '2'))
        member = log.get('member_id')
        if type(member) is int and member > 0:
            buyers.add(member)
        # The log's own amounts are used only when they equal the paid USD amount.
        try:
            if coupon_money(logged.get('amount'), 'COUPON_LOG_AMOUNT_INVALID') == usd:
                totals['discount_usd_minor'] += coupon_money(log.get('discount_amount'), 'COUPON_LOG_DISCOUNT_INVALID')
        except ContractError:
            pass
        # Admin's repurchase: paid orders by the same member on this site within 90 days after the use.
        try:
            count = log.get('repurchase_count')
            count = int(count) if type(count) in (int, str) and str(count).isdecimal() else 0
            if count > 0:
                totals['repurchase_orders'] += count
                totals['repurchase_usd_minor'] += coupon_money(log.get('repurchase_amount'), 'COUPON_LOG_REPURCHASE_INVALID')
        except ContractError:
            pass
    coverage['unique_uses'] = len(seen)
    totals['unique_buyers'] = len(buyers)
    if max(totals['paid_usd_minor'], totals['discount_usd_minor'], totals['repurchase_usd_minor']) > 9007199254740991:
        raise ContractError('REPORT_MONEY_EXCEEDS_SAFE_INTEGER')
    issued, used = coupon['issued_total'], coupon['used_total']
    # Rates are None when their denominator is zero: unknown is not zero.
    claim_to_use = round(used / issued, 6) if issued else None
    paid_per_use = round(totals['paid_orders'] / totals['used_orders'], 6) if totals['used_orders'] else None
    return dict(status='available', basis='activity_coupon_use_log', activity_id='fc27-season2',
                coupon=coupon, totals=totals, daily=[daily[k] for k in sorted(daily)],
                conversion=dict(claim_to_use=claim_to_use, claim_to_use_scope='cumulative',
                                paid_per_use=paid_per_use, issued_in_window='not_available'),
                coverage=coverage, page_allocation='not_available', visitor_join='not_available',
                generated_at=datetime.now(timezone.utc).isoformat(),
                note='券发放与使用累计来自券记录；窗口内按用户优惠券使用记录（user/memberCouponLog）统计，已付款以订单/记录状态为准，订单价、优惠额、实付额和复购均取自该记录。复购为 Admin 口径（用券后90天内同站点已支付订单，不含本单，截至读取时）。窗口内逐日发放未单独读取，页面领券步骤见行为统计。')


def read_coupon_logs(reader, coupon_ids, start, end):
    if len(coupon_ids) == 1:
        coupon_filter = ('coupon_id', '=', coupon_ids[0])
    else:
        coupon_filter = ('coupon_id', 'IN', ','.join(coupon_ids))
    logs, cursor = [], start
    while cursor < end:
        stop = min(end, cursor + timedelta(days=28))
        lo, hi = cursor.strftime('%Y-%m-%d %H:%M:%S'), (stop - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        logs.extend(reader.pages('coupon_logs', [('site_id', '=', FC_COUPON['site_id']), coupon_filter,
                                                 ('use_time', 'RANGE', lo + ',' + hi)]))
        cursor = stop
    return logs


def read_coupon_orders(reader, numbers):
    numbers = sorted(numbers)
    orders = []
    for index in range(0, len(numbers), COUPON_ORDER_CHUNK):
        chunk = numbers[index:index + COUPON_ORDER_CHUNK]
        orders.extend(reader.pages('orders', [('site_id', '=', FC_COUPON['site_id']), ('order_no', 'IN', ','.join(chunk))],
                                   validate=lambda r, chunk=chunk: str(r.get('order_no')) in chunk))
    return orders


def read_carnival_coupon_usage(reader, start, end):
    groups = {module: tuple(map(str, ids)) for module, ids in CARNIVAL_COUPONS.items()}
    counters = {}
    for coupon_ids in groups.values():
        for cid in coupon_ids:
            counters[cid] = coupon_record(reader.detail('coupon', cid),
                dict(id=cid, site_id=CARNIVAL_SITE_ID, param_code=CARNIVAL_COUPON_PARAM))

    logs_by_module = {}
    order_module = {}
    for module, coupon_ids in groups.items():
        logs = read_coupon_logs(reader, coupon_ids, start, end)
        for log in logs:
            number = identity(str(log.get('order_no')))
            if order_module.setdefault(number, module) != module:
                raise ContractError('CONFLICTING_DUPLICATE_COUPON_USE')
        logs_by_module[module] = logs
    orders_by_module = defaultdict(list)
    for row in read_coupon_orders(reader, order_module):
        orders_by_module[order_module[str(row['order_no'])]].append(row)

    modules, unmatched = [], 0
    for module, coupon_ids in groups.items():
        coupon = {key: sum(counters[cid][key] for cid in coupon_ids) for key in ('issued_total', 'used_total')}
        result = summarize_coupon_usage(coupon, logs_by_module[module], orders_by_module[module], start, end, coupon_ids)
        modules.append(dict(module=module, **coupon, **result['totals']))
        unmatched += result['coverage']['orders_unmatched']
    return dict(status='available', activity_id='mmoexp-carnival', modules=modules,
                coverage=dict(complete=True, orders_unmatched=unmatched),
                generated_at=datetime.now(timezone.utc).isoformat())


def read_coupon_usage(reader, request):
    start, end, _game = query_window(request)
    activity = request.get('activity')
    if activity == 'mmoexp-carnival':
        return read_carnival_coupon_usage(reader, start, end)
    if activity != 'fc27-season2':
        raise ContractError('ACTIVITY_SCOPE_REQUIRED')
    coupon = coupon_record(reader.detail('coupon', FC_COUPON['id']))
    logs = read_coupon_logs(reader, (FC_COUPON['id'],), start, end)
    orders = read_coupon_orders(reader, {identity(str(log.get('order_no'))) for log in logs})
    return summarize_coupon_usage(coupon, logs, orders, start, end)


# Carnival 2026 Mystery Shop: which members paid an order with one of a coupon set's
# Mystery coupons, and when. The public runtime unlocks that member's next round for the
# games of the set. Read only; only paid (status 1) uses within the carnival window count.
CARNIVAL_MYSTERY_SETS = {
    'fc27': ('1401', '1403', '1405'), 'aion2': ('1407', '1409', '1411'), 'wow': ('1413', '1415', '1417'),
    'd4': ('1419', '1421', '1423'), 'poe': ('1425', '1427', '1429'), 'mix': ('1431', '1433', '1435'),
}
CARNIVAL_WINDOW = ('2026-11-19 13:00:00', '2026-12-02 12:59:59')  # Beijing wall clock = Nov 19 – Dec 2 00:00 ET
# Internal test before the event: one test coupon stands in for every Mystery set, and
# only its uses before the real start count.
CARNIVAL_TEST_WINDOW = ('2026-11-17 00:00:00', '2026-11-19 12:59:59')


def carnival_unlocks(logs, test_coupon=None):
    if test_coupon:
        by_coupon = {test_coupon: tuple(CARNIVAL_MYSTERY_SETS)}
    else:
        by_coupon = {cid: (name,) for name, ids in CARNIVAL_MYSTERY_SETS.items() for cid in ids}
    uses, seen = [], set()
    for log in logs:
        if str(log.get('site_id')) != CARNIVAL_SITE_ID or str(log.get('coupon_id')) not in by_coupon:
            raise ContractError('COUPON_LOG_SCOPE_MISMATCH')
        if log.get('status') not in (0, 1, '0', '1'):
            raise ContractError('COUPON_LOG_STATE_UNKNOWN')
        if log.get('status') not in (1, '1'):
            continue
        member = log.get('member') if isinstance(log.get('member'), dict) else {}
        uid = str(member.get('uid') or '')
        if not re.fullmatch(r'[1-9]\d{0,19}', uid):
            continue
        try:
            used_at = datetime.strptime(log['use_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=SOURCE_TZ)
        except (KeyError, TypeError, ValueError):
            raise ContractError('COUPON_USE_TIME_INVALID') from None
        for name in by_coupon[str(log.get('coupon_id'))]:
            key = (uid, name, used_at)
            if key in seen:
                continue
            seen.add(key)
            uses.append(dict(uid=uid, set=name, used_at=used_at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
    uses.sort(key=lambda u: (u['used_at'], u['uid'], u['set']))
    return dict(status='available', basis='mystery_test_coupon_paid_use' if test_coupon else 'mystery_coupon_paid_use',
                uses=uses, generated_at=datetime.now(timezone.utc).isoformat())


def read_carnival_unlocks(reader, request):
    if set(request) - {'action', 'site_id', 'test_coupon_id'}:
        raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
    if str(request.get('site_id', CARNIVAL_SITE_ID)) != CARNIVAL_SITE_ID:
        raise ContractError('SITE_SCOPE_REQUIRED')
    test = request.get('test_coupon_id')
    if test is not None:
        if not isinstance(test, int) or isinstance(test, bool) or not 0 < test < 10**9:
            raise ContractError('TEST_COUPON_INVALID')
        test = str(test)
    ids = test or ','.join(cid for ids in CARNIVAL_MYSTERY_SETS.values() for cid in ids)
    logs = reader.pages('coupon_logs', [('site_id', '=', CARNIVAL_SITE_ID), ('coupon_id', 'IN', ids),
                                        ('use_time', 'RANGE', ','.join(CARNIVAL_TEST_WINDOW if test else CARNIVAL_WINDOW))])
    return carnival_unlocks(logs, test)

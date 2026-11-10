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
    campaign_bindings(activity)
    game = request.get('game', 'all')
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

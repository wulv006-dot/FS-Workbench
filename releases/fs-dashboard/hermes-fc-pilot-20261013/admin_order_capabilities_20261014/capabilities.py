"""Bounded projections for observed Admin/Order read capabilities.

Candidate only: no credentials, timer, network client, or production hooks.
The injected request function belongs to the existing authorized session.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
import json
import re
from urllib.parse import urlencode

CONTRACT = 'fc-capability-read-v1'
SHANGHAI = timezone(timedelta(hours=8))
KINDS = ('native_loss', 'product_sales', 'fulfillment_samples')
NATIVE_PATH = '/admin/order.Order/orderStaticsDetailByEs'
PRODUCT_PATH = '/admin/stats.productSalesByEs/index'
CATEGORIES = ('gold', 'items', 'powerleveling', 'account', 'top-up', 'coach')
LOSSES = ('ts', 'tssj', 'dc', 'cb', 'tkwtg', 'wh', 'bftk', 'qt', 'bh',
          'ts_zhui', 'tssj_zhui', 'dc_zhui', 'cb_zhui',
          'ts_zhui_no', 'tssj_zhui_no', 'dc_zhui_no', 'cb_zhui_no', 'pianzi')


def number(value, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value)
    if not re.fullmatch(r'-?\d{1,18}(?:\.\d{1,8})?', text):
        return None
    try:
        value = Decimal(text)
        if integer:
            return int(value) if value == int(value) and value >= 0 else None
        return format(value, 'f')
    except (InvalidOperation, ValueError):
        return None


def safe_label(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        return None
    if re.search(r'[@<>\r\n]|https?://|Bearer|Cookie|password|passwd|密码|密钥|sk-', value, re.I):
        return None
    return value


def checked_query(args, config, now=None):
    if not isinstance(args, dict) or args.get('kind') not in KINDS or args.get('profile') != 'FC27':
        raise ValueError('capability_query')
    if config.get('game_id') != 1327 or config.get('main_site_id') != 266:
        raise ValueError('capability_mapping')
    kind = args['kind']
    fields = {'kind', 'profile', 'start', 'end'} if kind != 'fulfillment_samples' else {'kind', 'profile'}
    optional = {'page', 'pages', 'page_size', 'area_id', 'category_id', 'sort'} if kind == 'product_sales' else {'platform', 'pages', 'samples'} if kind == 'fulfillment_samples' else set()
    if set(args) - fields - optional or not fields <= set(args):
        raise ValueError('capability_fields')
    q = dict(args)
    if kind != 'fulfillment_samples':
        now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
        try:
            lo, hi = date.fromisoformat(q['start']), date.fromisoformat(q['end'])
        except (ValueError, TypeError):
            raise ValueError('capability_period') from None
        if lo.isoformat() != q['start'] or hi.isoformat() != q['end'] or hi < lo or hi > now.date() or (hi-lo).days > 30:
            raise ValueError('capability_period')
        begin = datetime.combine(lo, time.min, SHANGHAI)
        stop = min(datetime.combine(hi, time(23, 59, 59), SHANGHAI), now.replace(microsecond=0))
        q['period'] = {'start':begin.strftime('%Y-%m-%d %H:%M:%S'), 'end':stop.strftime('%Y-%m-%d %H:%M:%S')}
        q['date_utc'] = [x.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') for x in (begin, stop)]
        q['ttl_seconds'] = 900 if hi == now.date() else 7200
    if kind == 'product_sales':
        for key, default, upper in (('page', 1, 1000), ('pages', 1, 3), ('page_size', 10, 100)):
            value = q.get(key, default)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('capability_paging')
            q[key] = value
        if q['page_size'] not in (10, 20, 50, 100):
            raise ValueError('capability_paging')
        if q['page'] + q['pages'] - 1 > 1000:
            raise ValueError('capability_paging')
        for key in ('area_id', 'category_id'):
            if key in q and (type(q[key]) is not int or not 0 <= q[key] <= 999999999):
                raise ValueError('capability_filter')
        q['sort'] = q.get('sort', 'order_count,desc')
        if q['sort'] not in ('order_count,desc', 'total_amount,desc'):
            raise ValueError('capability_sort')
    elif kind == 'fulfillment_samples':
        q['platform'] = q.get('platform', 'all')
        if q['platform'] not in ('all', 'PS', 'PC', 'XBOX', 'unknown'):
            raise ValueError('capability_platform')
        for key, default, upper in (('pages', 1, 3), ('samples', 3, 6)):
            value = q.get(key, default)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('capability_sample_budget')
            q[key] = value
        q['ttl_seconds'] = 900
    return q


def result(q, status, **data):
    query = {k:v for k,v in q.items() if k not in ('date_utc', 'ttl_seconds')}
    return {'contract':CONTRACT, 'kind':q['kind'], 'status':status, 'readonly':True,
            'source_system':'Order' if q['kind'] == 'fulfillment_samples' else 'Admin',
            'scope':{'project':'FC27', 'site':'www.mmoexp.com', 'admin_game_id':1327, 'admin_site_id':266},
            'query':query, 'timezone':'Asia/Shanghai', 'captured_at':datetime.now(timezone.utc).isoformat(),
            'source_data_as_of':None, 'immutable_watermark':False, **data}


def decoded(http_status, raw):
    if http_status in (401, 403):
        raise PermissionError('source_denied')
    if http_status != 200 or not isinstance(raw, (bytes, str)) or len(raw) > 2000000:
        raise ValueError('source_unavailable')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('source_contract')
    if value.get('code') in (401, 403):
        raise PermissionError('source_denied')
    if value.get('code') != 1 or not isinstance(value.get('data'), dict):
        raise ValueError('source_contract')
    return value


def native_projection(payload, q):
    raw = payload['data'].get('data')
    if not isinstance(raw, dict) or not isinstance(raw.get('game_rank'), dict) or not isinstance(raw.get('site_rank'), dict):
        raise ValueError('native_shape')
    games = list(raw['game_rank'].values())
    sites = list(raw['site_rank'].values())
    if any(not isinstance(g, dict) or str(g.get('gid')) != '1327' for g in games) or len(games) > 1:
        raise ValueError('native_game_filter')
    if any(not isinstance(s, dict) or s.get('site_name') != 'www.mmoexp.com' for s in sites):
        raise ValueError('native_site_filter')
    total = number(raw.get('total'), True)
    if total is None or (total > 0 and (not games or not sites)):
        raise ValueError('native_missing_game')
    g = games[0] if games else {}
    if g.get('cat') is not None and not isinstance(g['cat'], dict):raise ValueError('native_category_shape')
    def group(obj, count_key):
        return {'count':number(obj.get(count_key), True), 'amount_usd':number(obj.get('amount'))} if isinstance(obj, dict) else {'count':None, 'amount_usd':None}
    categories = {k:group((g.get('cat') or {}).get(k), 'num') for k in CATEGORIES}
    loss = {k:group(g.get(k), 'n') for k in LOSSES}
    peak_date = g.get('peak_order_date')
    if not isinstance(peak_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', peak_date):
        peak_date = None
    return result(q, 'available', endpoint=NATIVE_PATH, method='POST',
                  response_time=number(payload.get('time'), True), currency='USD',
                  source_orders=total, source_amount_usd=number(raw.get('amount')),
                  categories=categories, loss_groups=loss,
                  peak={'count':number(g.get('peak_order_count'), True), 'date':peak_date},
                  coverage={'aggregate_only':True, 'order_detail_complete':False, 'game_scope_checked':True,
                            'site_scope_checked':True, 'definitions_verified':False},
                  period_basis='source query interval; loss event/cohort basis and endpoint inclusivity unknown',
                  rule='Raw native categories may overlap or refer to older orders; null is missing; no net-profit or causal formula.')


def product_projection(row, q):
    if not isinstance(row, dict) or str(row.get('gid')) != '1327' or str(row.get('site_id')) != '266':
        raise ValueError('product_scope_filter')
    for key, field in (('area_id', 'aid'), ('category_id', 'cid')):
        if key in q and str(row.get(field)) != str(q[key]):
            raise ValueError('product_dimension_filter')
    # No member, contact, account, free-text note or nested upstream object crosses this projection.
    return {**{k:number(row.get(k), True) for k in ('gid', 'site_id', 'pid', 'aid', 'cid')},
            'title':safe_label(row.get('title')), 'category':safe_label(row.get('category_title')),
            'area':safe_label(row.get('gameArea__title')), 'sale_total':number(row.get('sale_total')),
            'order_count':number(row.get('order_count'), True), 'total_amount_usd':number(row.get('total_amount')),
            'source_paytime':number(row.get('paytime'), True)}


def collect_admin(request, args, config, now=None):
    """Only two observed endpoints. request(path, body_or_None) is session-owned."""
    q = checked_query(args, config, now)
    if q['kind'] == 'fulfillment_samples':
        raise ValueError('order_reader_required')
    if not config.get('enabled'):
        return result(q, 'not_available', reason='fc_detail_disabled')
    try:
        if q['kind'] == 'native_loss':
            body = {'order_status':'', 'pay_status':1, 'game':1327, 'site':266, 'country_code':'',
                    'client':'', 'date':q['date_utc'], 'pay_type':'', 'time_unit':1, 'cid':'', 'discount_code':'', 'isNew':''}
            return native_projection(decoded(*request(NATIVE_PATH, body)), q)
        rows, observations, seen, totals, errors = [], [], set(), [], []
        for page in range(q['page'], q['page']+q['pages']):
            params = {'page':page, 'limit':q['page_size'], 'order':q['sort']}
            filters = [('site_id', 266, '='), ('gid', 1327, '=')]
            filters += [(f, q[k], '=') for k,f in (('area_id','aid'), ('category_id','cid')) if k in q]
            filters.append(('paytime', q['period']['start']+','+q['period']['end'], 'RANGE'))
            for i,(field,value,operator) in enumerate(filters):
                params.update({'search[%s][field]'%i:field, 'search[%s][val]'%i:value, 'search[%s][operator]'%i:operator})
                if field == 'paytime':params['search[%s][render]'%i] = 'datetime'
            payload = decoded(*request(PRODUCT_PATH+'?'+urlencode(params), None))
            data = payload['data']; batch = data.get('list'); total = number(data.get('total'), True)
            if not isinstance(batch, list) or total is None or len(batch) > q['page_size']:
                raise ValueError('product_pagination_contract')
            projected = [product_projection(row, q) for row in batch]
            # Exact projected duplicates are evidence of partial paging, not a proved logical group key.
            duplicates = 0
            for row in projected:
                key = sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                if key in seen:duplicates += 1
                seen.add(key); rows.append(row)
            totals.append(total)
            observations.append({'page':page, 'rows':len(batch), 'source_total':total,
                                 'exact_duplicates':duplicates, 'response_time':number(payload.get('time'), True)})
            if len(batch) < q['page_size'] or page*q['page_size'] >= total:
                break
        stable = len(set(totals)) == 1
        if not stable:errors.append('source_total_changed')
        if any(x['exact_duplicates'] for x in observations):errors.append('exact_duplicate_rows')
        return result(q, 'partial', endpoint=PRODUCT_PATH, method='GET', currency='USD', rows=rows,
                      coverage={'pages':observations, 'source_total':totals[-1] if stable else None,
                                'total_stable':stable, 'received_rows':len(rows), 'distinct_projected_rows':len(seen),
                                'has_more':observations[-1]['page']*q['page_size'] < totals[-1],
                                'complete':False, 'stable_group_key_verified':False}, errors=errors,
                      period_basis='paytime RANGE submitted; aggregation/time filtering semantics not independently closed',
                      rule='SKU order_count is not distinct orders across products; sale_total unit unknown; title cannot infer historical coin K. Partial results cannot establish full revenue contribution.')
    except PermissionError:
        return result(q, 'denied', reason='source_denied')
    except (OSError, ValueError, TypeError, KeyError):
        return result(q, 'not_available', reason='source_contract_or_read_failed')


def fulfillment_projection(raw, q, task_key):
    """Project a trusted reader reply; raw order/event IDs are used only to pseudonymize."""
    if q['kind'] != 'fulfillment_samples' or not isinstance(task_key, bytes) or len(task_key) < 32:
        raise ValueError('fulfillment_query')
    if raw.get('contract') != 'fc-order-events-raw-v1':
        raise ValueError('fulfillment_contract')
    if raw.get('status') in ('denied', 'not_available', 'not_sent'):
        return result(q, raw['status'], reason=raw.get('reason') if raw.get('reason') in ('source_denied','collector_busy','existing_auth_unavailable') else 'source_unavailable')
    source_captured_at=raw.get('captured_at')
    try:
        if not isinstance(source_captured_at,str) or datetime.fromisoformat(source_captured_at).tzinfo is None:
            source_captured_at=None
    except ValueError:source_captured_at=None
    samples = []
    for row in raw.get('samples', []):
        if row.get('gid') != 1322 or row.get('source') != 'www.mmoexp.com' or row.get('status') != '问题单':
            raise ValueError('fulfillment_scope')
        if row.get('platform') not in ('PS', 'PC', 'XBOX', 'unknown') or q['platform'] not in ('all', row['platform']):
            raise ValueError('fulfillment_platform')
        rid = str(row.get('id'))
        if not re.fullmatch(r'\d{1,12}', rid):raise ValueError('fulfillment_identity')
        case = 'case_'+hmac.new(task_key,('Order/case\0'+rid).encode(),'sha256').hexdigest()[:24]
        events, seen = [], set()
        for event in row.get('events', [])[:100]:
            eid, stamp = str(event.get('id')), event.get('time')
            if not re.fullmatch(r'\d{1,18}', eid) or not isinstance(stamp, str) or not re.fullmatch(r'\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', stamp):
                raise ValueError('fulfillment_event')
            if eid in seen:raise ValueError('fulfillment_event_duplicate_id')
            seen.add(eid)
            events.append({'event_ref':'event_'+hmac.new(task_key,('Order/event\0'+rid+'\0'+eid).encode(),'sha256').hexdigest()[:24],
                           'source_time':stamp, 'state':safe_label(event.get('status'))})
        items = []
        for item in row.get('items', [])[:20]:
            if str(item.get('gid')) != '1322':raise ValueError('fulfillment_item_scope')
            product_id=number(item.get('pid'), True)
            item_ref='item_'+hmac.new(task_key,('Order/item\0'+rid+'\0'+str(product_id)).encode(),'sha256').hexdigest()[:24] if product_id is not None else None
            items.append({**{k:number(item.get(k), True) for k in ('gid', 'aid', 'cid')}, 'item_ref':item_ref,
                          'qty':number(item.get('qty')), 'used':number(item.get('used')), 'unit':safe_label(item.get('unit')),
                          'currency':item.get('currency') if item.get('currency') in ('USD','CNY') else None})
        event_count=number(row.get('event_count'), True)
        item_count=number(row.get('item_count'), True)
        samples.append({'case_ref':case, 'platform':row['platform'], 'items':items, 'events':events,
                        'source_event_count':event_count, 'source_item_count':item_count,
                        'truncated':len(row.get('events', []))>100 or len(row.get('items', []))>20 or
                                    (event_count is not None and event_count>len(events)) or
                                    (item_count is not None and item_count>len(items))})
    if len(samples) > q['samples']:raise ValueError('fulfillment_sample_budget')
    return result(q, 'partial', endpoint='/order/admin_order/index.html -> actual existing detail links', method='GET',
                  reference_only=True, source_data_as_of=None, source_captured_at=source_captured_at,
                  capture_time_basis='captured_at is projection time; source_captured_at is reader time when supplied; neither is immutable watermark', samples=samples,
                  coverage={'listed':number(raw.get('listed'), True), 'pages':number(raw.get('pages'), True),
                            'sampled':len(samples), 'has_more':raw.get('has_more') if type(raw.get('has_more')) is bool else None,
                            'complete':False, 'history_complete':False},
                  identity='task-scoped HMAC pseudonyms for order/event/item IDs; Order game/area/category dictionary IDs are distinct from Admin IDs',
                  period_basis='current problem pool status=6; event display time retained verbatim, not inferred historic day-end state',
                  rule='No raw notes, actor, contact, credentials or cost. Event IDs, not time/state, determine identity. Samples cannot establish overall cause/proportion.')

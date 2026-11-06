"""FC-only order facts. No raw contacts, account information or free-text notes survive."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib, html, re
from fc_dashboard import classify, project as dashboard_project

SHANGHAI = timezone(timedelta(hours=8))
CONTRACT = 'fc27-detail-analytics-v1'
CUSTOMERS = ('new', 'returning', 'unknown')

def cents(value):
    try:
        amount = Decimal(str(value).replace(',', '').replace('$', '').strip())
        return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None

def stamp(value):
    try:
        if not isinstance(value, str): return None
        parsed = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        return parsed.replace(tzinfo=SHANGHAI).isoformat()
    except ValueError:
        return None

def normalize(raw, config, site_ids):
    if str(raw.get('gid')) != str(config['game_id']) or str(raw.get('pay_status')) != '1': return None
    order_id = str(raw.get('order_no') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', order_id): raise ValueError('unstable_order_id')
    site = int(raw.get('site_id') or 0)
    scope = ('distribution_group' if site in config['distribution_site_ids'] else
             'main' if site == config['main_site_id'] else 'satellite' if site in site_ids else 'unknown')
    amount = cents(raw.get('amount_usd_format'))
    if amount is not None and amount != cents(raw.get('amount')): amount = None
    flag = raw.get('isNew')
    customer = ('new' if flag in (1, '1') else 'returning' if flag in (0, '0') else 'unknown') if config.get('trust_customer_flag') else 'unknown'
    uid = str(raw.get('uid') or '0')
    customer_key = hashlib.sha256((str(site) + ':' + uid).encode()).hexdigest()[:24] if uid.isdigit() and int(uid) > 0 else None
    content = html.unescape(re.sub(r'<[^>]*>', ' ', str(raw.get('content') or '')))
    platforms = set()
    if re.search(r'PlayStation|PS[45]', content, re.I): platforms.add('PS')
    if re.search(r'Xbox', content, re.I): platforms.add('XBOX')
    if re.search(r'\bPC\b', content, re.I): platforms.add('PC')
    platform = next(iter(platforms)) if len(platforms) == 1 else 'unknown'
    categories = set()
    for name, pattern in [('Coins', r'\bcoins?\b'), ('Items', r'Players|Packs|SBC|Coupons|Items'),
                          ('Boosting', r'Boosting|Coaching'), ('Accounts', r'Accounts'), ('Top Up', r'Top Up')]:
        if re.search(pattern, content, re.I): categories.add(name)
    product = next(iter(categories)) if len(categories) == 1 else '多品类' if categories else '待分类'
    status = str(raw.get('status_format') or '状态未知')[:80]
    terminal = raw.get('status') == 101 or status.startswith(('已完成', '已退款', '已取消', '删除订单'))
    funding = not terminal and any(k in status for k in ('退款', '投诉', 'Charge Back', '调查'))
    issue = not terminal and (raw.get('status') == 91 or funding or '问题' in status)
    return {'id': order_id, 'site_id': site, 'site': (raw.get('site') or {}).get('full_title') or '',
            **classify(raw.get('content'), raw.get('_fc_native_items'), config.get('_category_paths'), raw.get('_fc_items_complete') is True), 'platform_status': 'multiple' if len(platforms)>1 else 'verified' if platforms else 'unknown',
            'site_group': scope, 'platform': platform, 'product': product,
            'amount_cents': amount, 'customer': customer, 'customer_key': customer_key,
            'paid_at': stamp(raw.get('paytime')), 'created_at': stamp(raw.get('timestamp_format') or raw.get('timestamp')),
            'updated_at': stamp(raw.get('lasttime')), 'status': status, 'terminal': terminal,
            'backlog': not terminal and not funding, 'funding': funding, 'issue': issue,
            'reason': '资金待处理' if funding else '待确认',
            'country': str(raw.get('country_code') or 'unknown')[:12],
            'device': {0: 'Desktop', 1: 'Mobile'}.get(raw.get('device'), 'unknown'),
            'payment': str(raw.get('paytype_display') or 'unknown')[:80]}

def deduplicate(rows):
    result = {}
    for row in rows:
        key = (row.get('site_id', row.get('site_group')), row['id'])
        old = result.get(key)
        if old is None or (row.get('updated_at') or '') > (old.get('updated_at') or ''): result[key] = row
    return list(result.values())

def amount_bucket(value, edges):
    if value is None: return 'unpriced'
    for i, edge in enumerate(edges):
        if value >= edge * 100 and (i == len(edges) - 1 or value < edges[i + 1] * 100): return str(i)
    return 'unpriced'

def selected(row, query, config, current=False):
    if row['site_group'] not in ('main', 'satellite'): return False
    for field in ('platform', 'customer', 'product', 'site_group', 'country', 'device', 'payment'):
        if query.get(field, 'all') != 'all':
            actual = row.get('category', 'unknown') if field == 'product' and query[field] in ('Coins','Players','SBC','Packs','Other','unknown') else row[field]
            if actual != query[field]: return False
    if query.get('hour', 'all') != 'all' and (not row['paid_at'] or row['paid_at'][11:13] + ':00' != query['hour']): return False
    if query.get('bucket', 'all') != 'all' and amount_bucket(row['amount_cents'], config['amount_edges_usd']) != query['bucket']: return False
    if query.get('issue') == 'true' and not row['issue']: return False
    if not current:
        paid = (row['paid_at'] or '').replace('T',' ')[:16]
        period = query.get('period') or {'start': query['start'][:10]+' 00:00', 'end': (datetime.fromisoformat(query['end'][:10])+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}
        if not period['start'] <= paid < period['end']: return False
    return True

def facts(rows):
    valid = [r['amount_cents'] for r in rows if r['amount_cents'] is not None]
    counts = Counter(r['customer'] for r in rows)
    return {'orders': len(rows), 'revenue_usd': sum(valid) / 100 if len(valid)==len(rows) else None, 'known_revenue_usd':sum(valid)/100,
            'unpriced_orders': len(rows) - len(valid), 'new': counts['new'], 'returning': counts['returning'],
            'unknown': counts['unknown'], 'issues': sum(r['issue'] for r in rows),
            'unfinished': sum(r['backlog'] for r in rows), 'funding': sum(r['funding'] for r in rows),
            'completed': sum(r['terminal'] and r['status'].startswith('已完成') for r in rows)}

def elapsed_hours(row, at):
    value = row.get('paid_at') or row.get('created_at')
    try:
        stamp = datetime.fromisoformat(value) if value else None
        if at is None or stamp is None or stamp.tzinfo is None: return None
        hours = (at - stamp).total_seconds() / 3600
        return hours if hours >= 0 else None
    except (ValueError, TypeError):
        return None

def current_risks(backlog, coverage, as_of, config):
    result = {'source': 'Admin', 'as_of': as_of, 'currency': 'USD',
              'basis': 'current_paid_open_pool_not_selected_payment_period',
              'waiting_hours': 24, 'high_amount_usd': config['attention_amount_usd']}
    if coverage.get('backlog_status') != 'available' or coverage.get('backlog_failed_groups'):
        return {**result, 'status': 'not_available', 'reason': 'current_pool_incomplete_or_unverified'}
    try:
        at = datetime.fromisoformat(as_of)
        if at.tzinfo is None: at = None
    except (ValueError, TypeError): at = None
    def money(rows, unknown_selection=0):
        valid = [r['amount_cents'] for r in rows if type(r.get('amount_cents')) is int and r['amount_cents'] >= 0]
        missing = len(rows) - len(valid)
        known = sum(valid) / 100 if valid or not rows else None
        return {'orders': len(rows) if not unknown_selection else None, 'known_orders': len(rows),
                'amount_usd': known if not missing and not unknown_selection else None,
                'known_amount_usd': known, 'missing_amount_orders': missing,
                'unknown_selection_orders': unknown_selection}
    waiting = [r for r in backlog if r['backlog']]
    aging = {'under24': 0, '24to72': 0, 'at_least72': 0, 'unknown_time': 0, 'created_time_fallback': 0}
    old = []
    for row in waiting:
        hours = elapsed_hours(row, at)
        if hours is None: aging['unknown_time'] += 1; continue
        if not row.get('paid_at'): aging['created_time_fallback'] += 1
        aging['under24' if hours < 24 else '24to72' if hours < 72 else 'at_least72'] += 1
        if hours >= 24: old.append(row)
    unknown_amount = sum(type(r.get('amount_cents')) is not int or r['amount_cents'] < 0 for r in backlog)
    high = [r for r in backlog if type(r.get('amount_cents')) is int and r['amount_cents'] >= config['attention_amount_usd'] * 100]
    return {**result, 'status': 'partial' if unknown_amount or aging['unknown_time'] else 'available',
            'issues': money([r for r in backlog if r['issue']]),
            'waiting24': money(old, aging['unknown_time']), 'aging': aging,
            'high_amount': money(high, unknown_amount)}

def aggregate(dataset, query, config, now=None):
    now = now or datetime.now(SHANGHAI)
    if not config.get('trust_customer_flag'):
        dataset = {**dataset, 'orders': [{**r, 'customer': 'unknown'} for r in dataset['orders']],
                   'backlog': [{**r, 'customer': 'unknown'} for r in dataset['backlog']]}
    platform_gap = query.get('platform','all') in ('PS','PC','XBOX') and any(r.get('platform')=='unknown' and selected(r,{**query,'platform':'all','product':'all'},config) for r in dataset['orders'])
    classification_gap = platform_gap or query.get('product','all') != 'all' and any(r.get('category_status') != 'verified' and selected(r,{**query,'product':'all'},config) for r in dataset['orders'])
    paid_gap = dataset['coverage'].get('paid_complete') is False
    def view_facts(batch):
        values = facts(batch)
        if classification_gap or paid_gap:
            values.update(known_orders=values['orders'],known_revenue_usd=values['known_revenue_usd'],orders=None,revenue_usd=None)
        return values
    rows = [r for r in dataset['orders'] if selected(r, query, config)]
    backlog = [r for r in deduplicate(dataset['backlog']) if selected(r, query, config, True) and not r['terminal']]
    platform_pool_incomplete = query.get('platform','all') in ('PS','PC','XBOX') and any(r.get('platform')=='unknown' and selected(r,{**query,'platform':'all','product':'all'},config,True) for r in dataset['backlog'])
    category_pool_incomplete = platform_pool_incomplete or query.get('product','all') != 'all' and any(r.get('category_status') != 'verified' and selected(r,{**query,'product':'all'},config,True) for r in dataset['backlog'])
    risk_coverage = {**dataset['coverage'], 'backlog_status':'partial'} if category_pool_incomplete else dataset['coverage']
    edges = config['amount_edges_usd']
    buckets = []
    for i, lower in enumerate(edges):
        batch = [r for r in rows if amount_bucket(r['amount_cents'], edges) == str(i)]
        buckets.append({'key': str(i), 'label': str(lower) + ('+' if i == len(edges) - 1 else '–' + str(edges[i + 1])), **view_facts(batch)})
    buckets.append({'key': 'unpriced', 'label': '金额暂缺', **view_facts([r for r in rows if r['amount_cents'] is None])})
    users = defaultdict(list)
    for row in rows:
        if row['customer_key']: users[row['customer_key']].append(row)
    user_buckets = []
    for i in range(len(edges)):
        groups = [batch for batch in users.values() if all(r['amount_cents'] is not None for r in batch)
                  and amount_bucket(sum(r['amount_cents'] for r in batch), edges) == str(i)]
        user_buckets.append({'key': str(i), 'label': buckets[i]['label'], 'users': len(groups),
                             'revenue_usd': sum(r['amount_cents'] for batch in groups for r in batch) / 100})
    user_buckets.append({'key': 'unpriced', 'label': '累计金额暂缺',
                         'users': sum(any(r['amount_cents'] is None for r in batch) for batch in users.values()), 'revenue_usd': None})
    dimensions = {}
    for field in ('platform', 'product', 'country', 'device', 'payment', 'site_group'):
        groups = defaultdict(list)
        for row in rows: groups[row[field]].append(row)
        dimensions[field] = sorted([{'key': key, **view_facts(batch)} for key, batch in groups.items()], key=lambda r: -(r.get('known_orders') if r.get('orders') is None else r['orders']))
    hours = defaultdict(list)
    for row in rows:
        if row['paid_at']: hours[row['paid_at'][11:13] + ':00'].append(row)
    dimensions['hour'] = [{'key': key, **view_facts(batch)} for key, batch in sorted(hours.items())]
    days = defaultdict(list)
    for row in rows:
        if row['paid_at']: days[row['paid_at'][:10]].append(row)
    trend = []
    cursor = datetime.fromisoformat(query['start']).date()
    stop = datetime.fromisoformat(query['end']).date()
    missing_days = dataset['coverage'].get('missing_days', [])
    while cursor <= stop:
        key = cursor.isoformat()
        if key not in missing_days: trend.append({'date': key, **view_facts(days[key])})
        cursor += timedelta(days=1)
    wait_hours = {}
    for index, original in enumerate(backlog):
        row = dict(original)
        hours = elapsed_hours(row, now)
        wait_hours[(row.get('site_id'),row['id'])] = hours
        row['age_hours'] = round(hours, 1) if hours is not None else None
        row['age_basis'] = '支付时间' if row['paid_at'] else '下单时间' if row['created_at'] else '时间暂缺'
        row['attention'] = (['等待较久'] if hours is not None and hours >= config['attention_hours'] else [])
        if row['amount_cents'] is not None and row['amount_cents'] >= config['attention_amount_usd'] * 100: row['attention'].append('高金额')
        if row['customer'] == 'new': row['attention'].append('后台新客')
        backlog[index] = row
    # Preserve the deployed current-order sorting before pagination.
    backlog.sort(key=lambda r: (r['age_hours'] is None, r['age_hours'] if r['age_hours'] is not None else 0, r['id']))
    current = query.get('pool', 'paid') == 'current'
    listing = backlog if current else rows
    if query.get('list', 'orders') == 'issues': listing = [r for r in listing if r['issue'] or r.get('attention')]
    page = int(query.get('page', 1))
    public = lambda r: {k: v for k, v in r.items() if k not in ('customer_key', 'amount_cents', 'terminal')} | {'amount_usd': None if r['amount_cents'] is None else r['amount_cents'] / 100}
    signals = []
    slow = sum(wait_hours[(r.get('site_id'),r['id'])] is not None and wait_hours[(r.get('site_id'),r['id'])] >= config['attention_hours'] for r in backlog)
    if slow: signals.append({'text': '当前有 %s 单等待超过 %s 小时；订单详情默认按等待时长从短到长展示。' % (slow, config['attention_hours']), 'tab': 'fulfillment'})
    if view_facts(rows)['issues']: signals.append({'text': '所选支付日订单当前有 %s 单问题，查看具体订单。' % view_facts(rows)['issues'], 'tab': 'fulfillment'})
    missing = sum(r['amount_cents'] is None for r in rows)
    if missing: signals.append({'text': '%s 单缺 USD 金额，未作为零金额入档。' % missing, 'tab': 'consumption'})
    site_rows = [r for r in dataset['orders'] if selected(r, {**query, 'site_group': 'all'}, config)]
    site_groups = [{'key': group, **view_facts([r for r in site_rows if r['site_group'] == group])} for group in ('main', 'satellite')]
    scope_label = {'main': 'MMOEXP主站 · FC27订单明细', 'satellite': '卫星子站合计 · FC27订单', 'all': 'MMOEXP主站 + 卫星子站 · Admin网站订单'}[query.get('site_group', 'all')]
    return {'contractId': CONTRACT, 'snapshot_id': dataset['snapshot_id'], 'as_of': dataset['as_of'],
            'scope_label': scope_label, 'customer_basis': 'Admin后台新老客标记' if config.get('trust_customer_flag') else '新老客字段未验证；本次身份标为未知', 'customer_status': 'available' if config.get('trust_customer_flag') else 'not_verified',
            'distribution_identification': config['distribution_identification'], 'currency': 'USD',
            'query': query, 'coverage': dataset['coverage'], 'data_status': 'partial' if classification_gap or paid_gap else dataset['data_status'],
            'fc_dashboard': dashboard_project(dataset, query, config, selected),
            'totals': view_facts(rows), 'site_groups': site_groups, 'buckets': buckets,
            'user_buckets': user_buckets, 'users_identified': len(users),
            'orders_without_customer_id': sum(not r['customer_key'] for r in rows),
            'dimensions': dimensions, 'trend': trend, 'backlog_summary': view_facts(backlog) if not category_pool_incomplete and dataset['coverage'].get('backlog_status','available')=='available' else None, 'slow_orders': slow if not category_pool_incomplete and dataset['coverage'].get('backlog_status','available')=='available' else None,
            'current_risks': current_risks(backlog, risk_coverage, dataset['as_of'], config),
            'signals': signals[:3], 'orders': [public(r) for r in (listing if query.get('format') == 'csv' else listing[(page - 1) * 10:page * 10])],
            'current_category_status': 'partial' if category_pool_incomplete else 'available',
            'list_total': None if current and category_pool_incomplete else len(listing), 'list_known_total':len(listing), 'page': page, 'page_size': 10,
            'order_sort': 'waiting_hours_ascending_unknown_last' if current else 'source_order'}

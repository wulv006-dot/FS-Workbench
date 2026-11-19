"""Whole-order FC taxonomy and transaction-time delivery accounting. No allocation."""
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import csv
import io
import sys
import json
import re
from urllib.parse import urlencode

CONTRACT = 'fc-dashboard-category-v1-20261106'
CATEGORIES = (('Players', '球员卡'), ('SBC', 'SBC'), ('Packs', 'Packs'), ('Other', '其他'), ('Coins', '金币'), ('unknown', '待分类'))
PRIORITY = [key for key, _ in CATEGORIES[:-1]]

class Items(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.lines, self.active, self.buffer = [], False, ''
        self.feed(value)
        self.close()
    def handle_starttag(self, tag, attrs):
        if tag == 'span' and 'item' in dict(attrs).get('class', '').split():
            self.active, self.buffer = True, ''
        elif tag == 'br' and self.active:
            if self.buffer.strip(): self.lines.append(self.buffer.strip())
            self.buffer = ''
    def handle_data(self, value):
        if self.active: self.buffer += value
    def handle_endtag(self, tag):
        if tag == 'span' and self.active:
            if self.buffer.strip(): self.lines.append(self.buffer.strip())
            self.active, self.buffer = False, ''

def classify(content, native_items=None, paths=None, native_complete=False):
    """Recognize every native item line before applying the whole-order priority."""
    parsed = Items(str(content or ''))
    found, unknown = set(), 0
    for line in parsed.lines:
        matches = set()
        for key, pattern in (('Players', r'\bplayers?\b|球员'), ('SBC', r'\bSBC\b|squad building'),
                             ('Packs', r'\bpacks?\b|卡包'), ('Other', r'boosting|coaching|accounts?|top\s*up|coupons?|代练'),
                             ('Coins', r'\bcoins?\b|金币')):
            if re.search(pattern, line, re.I): matches.add(key)
        # A line containing two category names is not evidence for two distinct items.
        if len(matches) != 1: unknown += 1
        else: found.update(matches)
    # Markup names are diagnostic candidates only. Native identity and complete membership are required.
    complete, native = bool(native_complete and isinstance(native_items, list) and native_items and paths), set()
    if complete:
        for item in native_items:
            pid, goods = str(item.get('pid') or ''), item.get('goods') or {}
            path = paths.get(str(goods.get('cid')), [])
            native_type = str(item.get('native_type'))
            root_type = {'1':'1','2':'0','4':'2','3':'3','5':'5','7':'7','8':'8','9':'9'}
            if not pid.isdigit() or pid != str(goods.get('id')) or not path or root_type.get(path[0]) != native_type:
                complete = False; break
            if native_type == '1': native.add('Coins')
            elif native_type == '0':
                native.add('Players' if '9627' in path else 'SBC' if '9625' in path else 'Packs' if '9629' in path else 'Other')
            elif native_type in ('2','3','5','7','8','9'): native.add('Other')
            else: complete = False; break
    key = next((key for key in PRIORITY if key in native), 'unknown') if complete else 'unknown'
    return dict(category=key, category_status='verified' if complete else 'unknown',
                category_candidates=[key for key in PRIORITY if key in found],
                item_count=len(parsed.lines), unknown_items=unknown,
                category_reason=None if complete else 'native_item_identity_or_completeness_unverified')

def number(value):
    try:
        value = Decimal(re.sub(r'[¥￥,\s]', '', str(value)))
        return value if value.is_finite() else None
    except (InvalidOperation, TypeError, ValueError): return None

def taxonomy(tree):
    paths, conflicts = {}, set()
    def walk(nodes, ancestors):
        for node in nodes:
            key = str(node.get('id') or '')
            if not key.isdigit(): continue
            path = ancestors + [key]
            if key in paths and paths[key] != path: conflicts.add(key)
            paths[key] = path
            walk(node.get('children') or [], path)
    walk(tree, [])
    return {key: path for key, path in paths.items() if not any(item in conflicts for item in path)}

def native_membership(read, pages, paid, period, config):
    """Use native PID grouping and PID-filtered whole orders; names never identify a SKU."""
    status, raw = read('/admin/goods.GoodsCategory/categorySelect?gid=1327')
    if status in (301,302,401,403): raise PermissionError('fc_native_denied')
    value = json.loads(raw)
    if status != 200 or value.get('code') != 1: raise ValueError('fc_native_taxonomy_unavailable')
    paths = taxonomy((value.get('data') or {}).get('list') or [])
    if not paths: raise ValueError('fc_native_taxonomy_unavailable')
    filters = [('gid',1327,'='), ('paytime',period['start']+':00','RANGE')]
    stop = datetime.strptime(period['end'], '%Y-%m-%d %H:%M') - timedelta(seconds=1)
    filters[1] = ('paytime',period['start']+':00,'+stop.strftime('%Y-%m-%d %H:%M:%S'),'RANGE')
    def product_query(limit):
        params = {'page':1, 'limit':limit, 'order':'order_count,descending'}
        for i,(field,val,op) in enumerate(filters):
            params.update({f'search[{i}][field]':field,f'search[{i}][val]':val,f'search[{i}][operator]':op})
        params['search[1][render]'] = 'datetime'
        status, raw = read('/admin/stats.productSalesByEs/index?' + urlencode(params))
        if status in (301,302,401,403): raise PermissionError('fc_native_denied')
        value = json.loads(raw)
        if status != 200 or value.get('code') != 1: raise ValueError('fc_native_products_unavailable')
        return value.get('data') or {}
    data = product_query(1000)
    total = data.get('total')
    if type(total) is not int or total < 0: raise ValueError('fc_native_product_total')
    budget = config.get('native_product_budget',300)
    products = data.get('list')
    if not isinstance(products,list) or not min(budget,total) <= len(products) <= total:
        raise ValueError('fc_native_products_incomplete')
    identities, seen, completed, invalid = defaultdict(list), set(), 0, 0
    for product in products[:budget]:
        pid, goods = str(product.get('pid') or ''), product.get('goods')
        if not isinstance(goods, dict): goods = {}
        if not pid.isdigit() or int(pid) <= 0 or pid in seen or str(product.get('gid')) != '1327':
            raise ValueError('fc_native_product_relation')
        seen.add(pid)
        native = dict(pid=pid, goods={'id':str(goods.get('id')),'cid':str(goods.get('cid'))}, native_type=str(product.get('cid')))
        try:
            batch = pages([('gid',1327,'='),('pay_status',1,'='),('pid',pid,'='),filters[1]], 'native-pid-'+pid)
        except TimeoutError:
            break
        completed += 1
        invalid += classify('', [native], paths, True)['category_status'] != 'verified'
        for row in batch:
            key = (str(row.get('site_id')), str(row.get('order_no')))
            if native not in identities[key]: identities[key].append(native)
    for row in paid:
        items = identities.get((str(row.get('site_id')),str(row.get('order_no'))), [])
        # Even after a bounded partial read, validate every line of each individual order.
        line_count = len(Items(str(row.get('content') or '')).lines)
        row['_fc_native_items'], row['_fc_items_complete'] = items, bool(items) and line_count == len(items)
    return paths, dict(status='available' if completed == total and not invalid else 'partial',
                       native_products=total, scanned_native_products=completed, invalid_native_products=invalid,
                       source='productSalesByEs complete PID groups + order.Order/index native pid filter',
                       unmatched_orders=sum(classify(r.get('content'), r['_fc_native_items'], paths,
                                                     r['_fc_items_complete'])['category_status'] != 'verified' for r in paid))

def identity(row):
    return (str(row.get('site') or ''), str(row.get('id') or ''))

def export_csv(dashboard, *, scope=((), ())):
    """Export the same selected financial/category/trend facts, including unknowns."""
    stream = io.StringIO()
    writer = csv.writer(stream)
    fields = ('orders', 'revenue_usd', 'shipping_sales_cny', 'cost_cny', 'gross_profit_cny', 'gross_margin_pct')
    headings, values = scope
    writer.writerow(('范围', '分类', '时间', *fields, '分类覆盖', '发货汇总对账', *headings))
    coverage = dashboard['coverage']
    for row in dashboard['categories']:
        writer.writerow(('所选范围', row['label'], '', *(row.get(field) for field in fields), coverage['classification_status'], coverage.get('reconciliation_status', 'not_verified'), *values))
    for row in dashboard['trend']:
        writer.writerow(('所选范围', '全部所选分类', row['date'], *(row.get(field) for field in fields), coverage['classification_status'], coverage.get('reconciliation_status', 'not_verified'), *values))
    return '\ufeff' + stream.getvalue()

def reconcile_shipping(rows, native_sale, native_cost, native_transactions=None):
    sale, cost = number(native_sale), number(native_cost)
    sales, costs = [number(r.get('sale_total')) for r in rows], [number(r.get('cost_total')) for r in rows]
    if sale is None or cost is None or any(value is None for value in sales+costs):
        return dict(reconciliation_status='not_verified', native_summary_reconciled=False)
    matched = sale==sum(sales,Decimal(0)) and cost==sum(costs,Decimal(0))
    trades = number(native_transactions)
    return dict(reconciliation_status='matched' if matched else 'mismatch',native_summary_reconciled=matched,
                native_shipping_sales_cny=float(sale),native_cost_cny=float(cost),
                native_transactions=int(trades) if trades is not None else None,detail_shipping_rows=len(rows))

def filter_echo_matches(name, observed, expected):
    """The native form displays minute precision; monetary reconciliation remains exact."""
    if observed == expected: return True
    if name not in ('start','end') or not isinstance(observed,str) or not isinstance(expected,str): return False
    try:
        datetime.strptime(expected,'%Y-%m-%d %H:%M:%S')
        datetime.strptime(observed,'%Y-%m-%d %H:%M')
    except ValueError: return False
    return observed == expected[:16]

def collect_shipping(session, period):
    """Read native rows and independently reconcile the identical transaction-time scope."""
    from lxml import html
    sys.path.insert(0, '/opt/fs-hermes-fc')
    from channel_cost_source import collect
    end = datetime.strptime(period['end'],'%Y-%m-%d %H:%M')-timedelta(seconds=1)
    begin, stop = period['start']+':00', end.strftime('%Y-%m-%d %H:%M:%S')
    rows = collect(session, begin[:10], stop[:10], since=begin, until=stop, source='', gid='1322')
    params = dict(genre='1',gid='1322',aid='0',cid='-1',status='-1',op_id='0',show_ccy='-1',
                  keyword='',sn='',wid='',start=begin,end=stop,**{'source[]':'','ship_source[]':''})
    proof = {'reconciliation_status':'not_verified','native_summary_reconciled':False,'echo_precision':'second'}
    def unverified(reason):
        return dict(rows=rows,coverage={**proof,'reconciliation_reason':reason})
    status, raw = session.get_order('/stats/admin_index/delivery.html',**params)
    if status in (301,302,401,403): raise PermissionError('fc_shipping_denied')
    if status != 200: return unverified('native_summary_http_unavailable')
    doc=html.fromstring(raw)
    if doc.xpath('//input[@type="password"]'): raise PermissionError('fc_shipping_denied')
    forms=doc.xpath('//form[@action="/stats/admin_index/delivery.html"]')
    if len(forms)!=1: return unverified('native_summary_form_changed')
    for name, expected in params.items():
        fields=forms[0].xpath('.//*[@name=$name]',name=name)
        if len(fields)!=1: return unverified('native_summary_filter_missing:'+name)
        field=fields[0]
        if field.tag=='select':
            options=field.xpath('./option[@selected]')
            if not options and field.get('multiple') is None: options=field.xpath('./option')[:1]
            observed=options[0].get('value','') if len(options)==1 else '' if not options else None
        else: observed=field.get('value','')
        if not filter_echo_matches(name,observed,expected): return unverified('native_summary_filter_mismatch:'+name)
        if name in ('start','end') and observed!=expected: proof['echo_precision']='minute'
    tables=doc.xpath('//table[.//th[normalize-space()="订单总数"]]')
    if len(tables)!=1: return unverified('native_summary_table_changed')
    headers=[' '.join(cell.itertext()).strip() for cell in tables[0].xpath('.//th')]
    if len(headers)!=6 or headers[0]!='游戏' or '销售总额' not in headers[1] or '采购总额' not in headers[2] or '利润' not in headers[3] or headers[4:]!=['订单总数','交易总数']:
        return unverified('native_summary_columns_changed')
    native=[]
    for tr in tables[0].xpath('.//tbody/tr'):
        if tr.xpath('./td[@colspan]'): continue
        cells=[' '.join(cell.itertext()).strip() for cell in tr.xpath('./td')]
        if cells: native.append(cells)
    if len(native)!=1 or len(native[0])!=6 or not re.match(r'^1322\s*\|',native[0][0]): return unverified('native_summary_game_or_rows_changed')
    proof.update(reconcile_shipping(rows,native[0][1],native[0][2],native[0][5]))
    return dict(rows=rows,coverage=proof)

def shipping_membership(request, rows, config, site_ids, normalize, budget=2000, raw_results=None):
    """Resolve delivery orders outside the payment window using the native exact order filter."""
    result, failures = [], 0
    for index, (site, order) in enumerate(sorted({(r['source'], r['sn']) for r in rows})):
        if index >= budget: failures += 1; continue
        params = {'page': 1, 'limit': 100, 'order': 'id,desc'}
        for i, (field, value) in enumerate((('gid', 1327), ('order_no', order))):
            params.update({f'search[{i}][field]': field, f'search[{i}][val]': value, f'search[{i}][operator]': '='})
        status, raw = request('/admin/order.Order/index?' + urlencode(params))
        if status in (301, 302, 401, 403): raise PermissionError('fc_shipping_membership_denied')
        data = json.loads(raw)
        value = data.get('data') or {}
        batch = value.get('list')
        if status != 200 or data.get('code') != 1 or not isinstance(batch, list) or value.get('total') != len(batch):
            failures += 1; continue
        matches = [r for r in batch if str(r.get('order_no')) == order and str(r.get('gid')) == '1327'
                   and (r.get('site') or {}).get('full_title') == site]
        if len(matches) != 1: failures += 1; continue
        row = normalize(matches[0], config, site_ids)
        if row is None: failures += 1
        else:
            result.append(row)
            if raw_results is not None: raw_results.append(matches[0])
    return result, failures

def project(dataset, query, config, selected):
    platform_cohort = [r for r in dataset['orders'] if selected(r,{**query,'platform':'all','product':'all'},config)]
    unknown_platform_paid = sum(r.get('platform')=='unknown' for r in platform_cohort)
    platform_gap = query.get('platform','all') in ('PS','PC','XBOX') and unknown_platform_paid > 0
    category_cohort = [r for r in dataset['orders'] if selected(r,{**query,'product':'all'},config)]
    unknown_paid = sum(r.get('category_status') != 'verified' for r in category_cohort)
    paid = [r for r in dataset['orders'] if selected(r, query, config)]
    membership = defaultdict(list)
    for row in dataset.get('shipping_orders', dataset['orders']): membership[identity(row)].append(row)
    source = dataset.get('shipping_coverage', {'status': 'unavailable', 'reason': 'shipping_not_read'})
    deliveries, seen, duplicate, conflict, unjoined, unclassified, unknown_platform_shipping = [], {}, 0, 0, 0, 0, 0
    conflicted = set()
    for raw in dataset.get('shipping', []):
        did = (str(raw.get('source') or ''), str(raw.get('delivery_id') or ''))
        if not did[1]: conflict += 1; continue
        if did in seen:
            if seen[did] == raw: duplicate += 1
            else: conflict += 1; conflicted.add(did)
        else: seen[did] = raw
    for did, raw in seen.items():
        if did in conflicted: continue
        matches = membership.get((str(raw.get('source') or ''), str(raw.get('sn') or '')), [])
        if len(matches) != 1: unjoined += 1; continue
        row = matches[0]
        # Financial membership uses the same filters, with its own transaction-time window.
        when = str(raw.get('trade_at') or '')
        period = query.get('period') or {'start': query['start'][:10]+' 00:00', 'end': (datetime.fromisoformat(query['end'][:10])+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}
        if not period['start'] <= when[:16] < period['end']: continue
        if query.get('hour', 'all') != 'all' and when[11:13] + ':00' != query['hour']: continue
        if selected(row, {**query,'product':'all','platform':'all','hour':'all'},config,True) and row.get('platform')=='unknown': unknown_platform_shipping += 1
        if selected(row, {**query, 'product':'all', 'hour':'all'}, config, True) and row.get('category_status') != 'verified': unclassified += 1
        if not selected(row, {**query, 'hour':'all'}, config, True): continue
        deliveries.append((row, raw))

    # An unfiltered financial cohort needs no order/category join. Its complete
    # native reconciliation independently proves these exact raw delivery sums.
    direct_financial = (source.get('native_summary_reconciled') is True and not conflict
        and query.get('site_group','all') in ('all','main') and query.get('issue') != 'true'
        and all(query.get(field,'all')=='all' for field in
                ('product','platform','customer','bucket','country','device','payment','hour')))
    raw_financial = []
    period = query.get('period') or {'start':query['start'][:10]+' 00:00',
        'end':(datetime.fromisoformat(query['end'][:10])+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}
    if direct_financial:
        for raw in seen.values():
            if not period['start'] <= str(raw.get('trade_at') or '')[:16] < period['end']: continue
            if query.get('site_group','all')=='main' and raw.get('source')!='www.mmoexp.com': continue
            raw_financial.append(raw)

    def raw_financial_values(rows):
        sales, costs = [number(r.get('sale_total')) for r in rows], [number(r.get('cost_total')) for r in rows]
        if any(value is None or value<0 for value in sales+costs): return {}
        sale, cost = sum(sales,Decimal(0)), sum(costs,Decimal(0))
        return dict(shipping_rows=len(rows), shipping_orders=len({(r.get('source'),r.get('sn')) for r in rows}),
                    shipping_sales_cny=float(sale),cost_cny=float(cost),gross_profit_cny=float(sale-cost),
                    gross_margin_pct=float(100*(sale-cost)/sale) if sale else None,
                    known_shipping_sales_cny=float(sale),known_cost_cny=float(cost),missing_money_rows=0)

    def metrics(orders, shipped, category_scope=False):
        amounts = [r['amount_cents'] for r in orders if r.get('amount_cents') is not None]
        sales = [number(r.get('sale_total')) for _, r in shipped]
        costs = [number(r.get('cost_total')) for _, r in shipped]
        missing = sum(s is None or c is None or c < 0 for s, c in zip(sales, costs))
        complete = not (unknown_platform_shipping and query.get('platform','all') in ('PS','PC','XBOX')) and source.get('status') == 'available' and source.get('native_summary_reconciled') is not False and not (conflict or unjoined or missing) and not (unclassified and (category_scope or query.get('product','all') != 'all'))
        sale = sum((s for s in sales if s is not None), Decimal(0))
        cost = sum((c for c in costs if c is not None and c >= 0), Decimal(0))
        customers = {r.get('customer_key') for r in orders if r.get('customer_key')}
        fresh = {r.get('customer_key') for r in orders if r.get('customer_key') and r.get('customer') == 'new'}
        returning = {r.get('customer_key') for r in orders if r.get('customer_key') and r.get('customer') == 'returning'}
        trusted = config.get('trust_customer_flag') and len(customers) > 0 and all(r.get('customer_key') and r.get('customer') in ('new', 'returning') for r in orders) and not fresh.intersection(returning)
        paid_complete = not platform_gap and dataset['coverage'].get('paid_complete', not dataset['coverage'].get('missing_days')) and not (unknown_paid and (category_scope or query.get('product','all') != 'all'))
        return dict(orders=len(orders) if paid_complete else None, known_orders=len(orders),
                    revenue_usd=sum(amounts)/100 if paid_complete and len(amounts)==len(orders) else None, known_revenue_usd=sum(amounts)/100,
                    paying_customers=len(customers) if paid_complete and all(r.get('customer_key') for r in orders) else None, known_paying_customers=len(customers), new_customers=len(fresh) if trusted and paid_complete else None,
                    customer_identity_coverage=sum(bool(r.get('customer_key')) for r in orders)/len(orders) if orders else None,
                    repeat_rate_pct=100*len(returning)/len(customers) if trusted and paid_complete else None,
                    new_customer_share_pct=100*len(fresh)/len(customers) if trusted and paid_complete else None,
                    shipping_rows=len(shipped), shipping_orders=len({identity(r) for r, _ in shipped}),
                    shipping_sales_cny=float(sale) if complete else None, cost_cny=float(cost) if complete else None,
                    gross_profit_cny=float(sale-cost) if complete else None,
                    gross_margin_pct=float(100*(sale-cost)/sale) if complete and sale else None,
                    known_shipping_sales_cny=float(sale), known_cost_cny=float(cost), missing_money_rows=missing)
    totals = metrics(paid, deliveries)
    if direct_financial: totals.update(raw_financial_values(raw_financial))
    categories = []
    for key, label in CATEGORIES:
        values = metrics([r for r in paid if r.get('category', 'unknown') == key], [(r, s) for r, s in deliveries if r.get('category', 'unknown') == key], True)
        categories.append(dict(key=key, label=label, order_share_pct=100*values['known_orders']/len(paid) if paid and not unknown_paid and not platform_gap and dataset['coverage'].get('paid_complete',True) else None,
                               known_order_share_pct=100*values['known_orders']/len(paid) if paid else None, **values))
    grain = query.get('grain', 'day')
    def bucket(value): return value[:10] if grain == 'day' else value[:13].replace('T', ' ') + ':00'
    by_paid, by_ship = defaultdict(list), defaultdict(list)
    for row in paid:
        if row.get('paid_at'): by_paid[bucket(row['paid_at'])].append(row)
    for row, ship in deliveries: by_ship[bucket(ship['trade_at'])].append((row, ship))
    period = query.get('period') or {'start': query['start'][:10]+' 00:00', 'end': (datetime.fromisoformat(query['end'][:10])+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}
    trend, cursor = [], datetime.fromisoformat(period['start'])
    stop = datetime.fromisoformat(period['end'])
    while cursor < stop:
        key = cursor.strftime('%Y-%m-%d' if grain == 'day' else '%Y-%m-%d %H:00')
        missing = key[:10] in dataset['coverage'].get('missing_days', [])
        values = metrics(by_paid[key], by_ship[key])
        if direct_financial: values.update(raw_financial_values([r for r in raw_financial if bucket(r['trade_at'])==key]))
        if missing: values.update(orders=None, revenue_usd=None)
        trend.append(dict(date=key, **values, categories=[dict(key=category, **metrics([r for r in by_paid[key] if r.get('category', 'unknown')==category], [(r,s) for r,s in by_ship[key] if r.get('category','unknown')==category], True)) for category,_ in CATEGORIES]))
        cursor += timedelta(days=1) if grain == 'day' else timedelta(hours=1)
    hourly = {}
    if grain == 'day' and query['start'] == query['end']:
        # Re-project the same paid-order cohort; no new read, source key or financial series.
        hours = defaultdict(list)
        for row in paid:
            if row.get('paid_at'): hours[row['paid_at'][:13].replace('T',' ')+':00'].append(row)
        time_incomplete = bool(dataset['coverage'].get('missing_payment_time') or
                               query['start'] in dataset['coverage'].get('missing_days', []))
        def hourly_facts(batch, category_scope=False):
            values = metrics(batch, [], category_scope)
            result = {key:values[key] for key in ('orders','revenue_usd','known_orders','known_revenue_usd')}
            priced = [row['amount_cents'] for row in batch if row.get('amount_cents') is not None]
            result['unpriced_orders'] = len(batch)-len(priced)
            if time_incomplete: result.update(orders=None,revenue_usd=None)
            if not batch and result['orders'] is None:
                result.update(known_orders=None,known_revenue_usd=None)
            elif batch and not priced:
                result['known_revenue_usd'] = None
            return result
        points, cursor = [], datetime.fromisoformat(period['start']).replace(minute=0,second=0,microsecond=0)
        while cursor < stop:
            key = cursor.strftime('%Y-%m-%d %H:00');batch=hours[key]
            points.append(dict(date=key, **hourly_facts(batch),
                categories=[dict(key=category, **hourly_facts([row for row in batch if row.get('category','unknown')==category],True)) for category,_ in CATEGORIES]))
            cursor += timedelta(hours=1)
        hourly['hourly_trend'] = points
    return dict(contractId=CONTRACT, category_priority=PRIORITY, grain=grain, totals=totals, categories=categories, trend=trend, **hourly,
                basis=dict(orders='Admin paytime; whole-order unique category', revenue_usd='Admin paid order USD',
                           financial='Order delivery trade_at; sale_total minus cost_total CNY', margin='total gross profit / total shipping sales'),
                coverage=dict(source, duplicate_shipping_rows=duplicate, conflicting_shipping_rows=conflict,
                              financial_basis='native_matched_raw_delivery_cohort' if direct_financial else 'classified_order_join',
                              unmatched_shipping_rows=unjoined, unclassified_shipping_rows=unclassified,
                              paid_complete=dataset['coverage'].get('paid_complete',not dataset['coverage'].get('missing_days')),
                              native_classification=dataset['coverage'].get('native_classification',{}), unknown_category_orders=unknown_paid,
                              classification_status='partial' if unknown_paid else 'available',
                              unknown_platform_orders=unknown_platform_paid, unknown_platform_shipping_rows=unknown_platform_shipping,
                              platform_status='partial' if unknown_platform_paid else 'available',
                              category_conflict_orders=sum(r.get('category_status')=='conflict' for r in paid),
                              multi_platform_orders=sum(r.get('platform_status')=='multiple' for r in paid)))

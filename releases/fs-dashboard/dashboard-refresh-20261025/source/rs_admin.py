"""RS source adaptation. Shared Admin8767 only; aggregate output, no customer records."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import json
import sys
import time

SITES = {'all': ('', '全部网站'), 'rsorders': (320, 'www.rsorders.com'),
         'rsmalls': (333, 'www.rsmalls.com'), 'rsfast': (254, 'www.rsfast.com'),
         'mmoexp': (266, 'www.mmoexp.com')}
SERVERS = {'all': ('', '全部区服'), 'rs3': (12370, 'Runescape 3'), 'oldschool': (12368, 'Old School')}
CATEGORIES = {'all': ('', '全部类目'), 'currency': (1, '货币'), 'package': (5, '代练包'), 'items': (0, '物品')}
ORDER_TYPES = {'all': '', 'currency': '1', 'package': '4', 'items': '2'}
FIELDS = ('rs_site', 'rs_server', 'rs_category')


def selection(values):
    result = {k: values.get(k, 'all') for k in FIELDS}
    if any(result[k] not in allowed for k, allowed in zip(FIELDS, (SITES, SERVERS, CATEGORIES))):
        raise ValueError('invalid_rs_filter')
    return result


def label(q):
    return ' · '.join(table[q[key]][1] for key, table in zip(FIELDS, (SITES, SERVERS, CATEGORIES)))


def number(raw, integer=False):
    if raw is None or isinstance(raw, bool): raise ValueError('rs_missing_number')
    try: value = Decimal(str(raw).replace(',', '').replace('$', '').strip())
    except InvalidOperation: raise ValueError('rs_invalid_number')
    if not value.is_finite() or integer and (value < 0 or value != value.to_integral_value()):
        raise ValueError('rs_invalid_number')
    return int(value) if integer else value


def native_rows(data, period):
    chart = data.get('chart_sales_arr') or {}
    labels, counts, amounts = (chart.get(k, []) for k in ('date', 'n', 'amount'))
    if not len(labels) == len(counts) == len(amounts): raise ValueError('rs_trend_shape')
    start, end = (datetime.strptime(period[k], '%Y-%m-%d %H:%M') for k in ('start', 'end'))
    rows = []
    for name, count, amount in zip(labels, counts, amounts):
        candidates = []
        for year in range(start.year, end.year + 1):
            for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y.%m.%d %H:%M', '%Y.%m.%d'):
                try: point = datetime.strptime(str(name) if str(name).startswith(str(year)) else str(year)+'.'+str(name), fmt)
                except ValueError: continue
                if start <= point < end: candidates.append(point)
        candidates = set(candidates)
        if len(candidates) != 1: raise ValueError('rs_trend_date')
        rows.append(dict(date=candidates.pop().strftime('%Y-%m-%d %H:00'), orders=number(count, True), amount=float(number(amount))))
    if sum(r['orders'] for r in rows) != number(data['total'], True) or abs(sum(number(r['amount']) for r in rows)-number(data['amount'])) > Decimal('.02'):
        raise ValueError('rs_trend_totals')
    return rows


def detail_projection(rows, q, period, source_total):
    """The list's aid/cid relation filters define membership; validate all observable scope."""
    begin, stop = (datetime.strptime(period[k], '%Y-%m-%d %H:%M') for k in ('start', 'end'))
    seen, paid, refunded = set(), [], 0
    for row in rows:
        identity = row.get('id')
        if type(identity) is not int or identity <= 0 or identity in seen: raise ValueError('rs_order_identity')
        seen.add(identity)
        if str(row.get('gid')) != '506': raise ValueError('rs_game_scope')
        when = datetime.strptime(row['paytime'], '%Y-%m-%d %H:%M:%S')
        if not begin <= when < stop: raise ValueError('rs_time_scope')
        if q['rs_site'] != 'all' and str(row.get('site_id')) != str(SITES[q['rs_site']][0]): raise ValueError('rs_site_scope')
        if str(row.get('pay_status')) == '2': refunded += 1; continue
        if str(row.get('pay_status')) != '1': raise ValueError('rs_payment_scope')
        paid.append((row, when, number(row.get('amount_usd_format'))))
    if len(seen) != source_total: raise ValueError('rs_incomplete_orders')
    dimensions = {key: defaultdict(lambda: [0, Decimal(0)]) for key in ('channels','countries','payments','devices')}
    trend = defaultdict(lambda: [0, Decimal(0)])
    for row, when, amount in paid:
        names = {'channels': (row.get('site') or {}).get('full_title') or '来源未提供',
                 'countries': row.get('country_code') or '国家未提供',
                 'payments': row.get('paytype_display') or row.get('paytype') or '支付方式未提供',
                 'devices': {0: 'PC', 1: '移动端'}.get(row.get('device'), '设备未提供')}
        for key, name in names.items(): dimensions[key][str(name)][0] += 1; dimensions[key][str(name)][1] += amount
        point = when.strftime('%Y-%m-%d %H:00'); trend[point][0] += 1; trend[point][1] += amount
    amount = sum((v[2] for v in paid), Decimal(0))
    values = {'orders': len(paid), 'revenueUsd': float(amount),
              'averageOrderUsd': float(amount/len(paid)) if paid else None,
              'minOrderAmountUsd': float(min(v[2] for v in paid)) if paid else None,
              'maxOrderAmountUsd': float(max(v[2] for v in paid)) if paid else None}
    return values, {key: [dict(code=name, name=name, orders=v[0], revenueUsd=float(v[1])) for name,v in sorted(groups.items())]
                    for key, groups in dimensions.items()}, [dict(date=day, orders=v[0], amount=float(v[1])) for day,v in sorted(trend.items())], {
        'source_total': source_total, 'received': len(rows), 'paid_orders': len(paid), 'excluded_refunded': refunded,
        'complete': True, 'membership': 'Admin原生订单列表 aid/cid 关联筛选；非商品名推断'}


def collect(q):
    sys.path.insert(0, '/opt/sales-dashboard/collector')
    sys.path.insert(0, '/opt/fs-transaction-snapshot')
    import p2pah_auth as auth
    from supplement_fields import extract
    selected = selection(q); scope = label(selected); period = q['period']
    session = auth.Session(); token, error = auth.admin_token_from_service()
    if error: raise OSError(error)
    session.bind_admin_token(token); del token
    deadline = time.monotonic()+85
    def read(path, params, post=False):
        remaining=deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('rs_source_deadline')
        response=session.admin.request('POST' if post else 'GET', auth.ADMIN_API+path,
            **({'json':params} if post else {'params':params}), headers={'batoken':session.token}, timeout=min(30,remaining), allow_redirects=False)
        if response.status_code in (301,302,401,403): raise PermissionError('rs_admin_denied')
        if response.status_code != 200 or len(response.content)>8*1024*1024: raise OSError('rs_admin_read_failed')
        value=response.json()
        if value.get('code') != 1: raise ValueError('rs_admin_contract')
        return value['data']
    try:
        sites=read('/admin/site.Site/siteList',dict(page=1,initKey='id',initValue='',select='true',quick_search=''))['list']
        if not all(any(str(r.get('id'))==str(i) and r.get('full_title')==name for r in sites) for i,name in SITES.values() if i!=''):
            raise ValueError('rs_site_catalog_changed')
        payload={'order_status':'','pay_status':1,'game':506,'site':SITES[selected['rs_site']][0],
            'country_code':'','client':'','date':[period['start'],period['end']],'pay_type':'',
            'time_unit':1,'cid':CATEGORIES[selected['rs_category']][0],'discount_code':''}
        raw=read('/admin/order.Order/orderStaticsDetailByEs',payload,True)
        if isinstance(raw,dict) and isinstance(raw.get('data'),dict):raw=raw['data']
        mapped=extract(raw); rows=native_rows(raw,period)
        if selected['rs_site']!='all' and any(r.get('name')!=SITES[selected['rs_site']][1] for r in mapped['dimensions'].get('channels') or []):
            raise ValueError('rs_native_site_not_applied')
        native_scope=label({**selected,'rs_server':'all'})
        for metric in mapped['metrics'].values():metric['scope']=native_scope
        coverage={'complete':True,'basis':'Admin原生统计'}
        if selected['rs_server']!='all':
            # Native aggregate ignores aid; use complete list membership for the selected area.
            filters=[('gid',506,'='),('pay_status',1,'='),('aid',SERVERS[selected['rs_server']][0],'=')]
            if selected['rs_site']!='all':filters.append(('site_id',SITES[selected['rs_site']][0],'='))
            if selected['rs_category']!='all':filters.append(('cid',CATEGORIES[selected['rs_category']][0],'='))
            records=[];seen={};scanned=0;expected=None;previous=float('inf')
            begin=datetime.strptime(period['start'],'%Y-%m-%d %H:%M');stop=datetime.strptime(period['end'],'%Y-%m-%d %H:%M')
            cursor=begin
            while cursor<stop:
                end=min(cursor+timedelta(days=28),stop); segment=[];received=0;expected=None;previous=float('inf')
                rules=filters+[('paytime',cursor.strftime('%Y-%m-%d %H:%M:%S')+','+(end-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'),'RANGE')]
                for page in range(1,301):
                    params={'page':page,'limit':100,'order':'id,desc'}
                    for i,(field,value,op) in enumerate(rules):
                        params.update({f'search[{i}][field]':field,f'search[{i}][val]':value,f'search[{i}][operator]':op})
                        if field=='paytime':params[f'search[{i}][render]']='datetime'
                    data=read('/admin/order.Order/index',params);batch=data.get('list');total=data.get('total')
                    if type(total) is not int or total<0 or not isinstance(batch,list) or len(batch)>100 or expected is not None and total!=expected:raise ValueError('rs_pagination_changed')
                    expected=total;ids=[r['id'] for r in batch]
                    if any(type(i) is not int for i in ids) or ids!=sorted(ids,reverse=True) or ids and ids[0]>previous:raise ValueError('rs_duplicate_or_sort')
                    if any(not cursor.strftime('%Y-%m-%d %H:%M:%S')<=r['paytime']<end.strftime('%Y-%m-%d %H:%M:%S') for r in batch):raise ValueError('rs_segment_time_scope')
                    if ids:previous=ids[-1]
                    for row in batch:
                        identity=row['id'];signature=json.dumps(row,sort_keys=True,ensure_ascii=False)
                        # aid/cid joins repeat the same order; count its whole revenue once.
                        if identity in seen:
                            if seen[identity]!=signature:raise ValueError('rs_conflicting_order')
                        else:seen[identity]=signature;segment.append(row)
                    received+=len(batch);scanned+=len(batch)
                    if received==total:break
                    if not batch or received>total:raise ValueError('rs_incomplete_orders')
                else:raise ValueError('rs_page_budget')
                records.extend(segment);cursor=end
            values,dims,rows,coverage=detail_projection(records,selected,period,len(records))
            coverage.update(source_scanned_total=scanned,duplicate_source_rows=scanned-len(records))
            mapped['dimensions'].update(dims)
            for key,value in values.items():mapped['metrics'][key]={'value':value,'status':'available' if value is not None else 'not_provided','source':'Admin订单明细','scope':scope}
        return dict(system='admin.p2pah.cn',status='available',period=period,currency='USD',
            normalisedScope='rs-selected',filters=payload,rsSelection=selected,scopeLabel=scope,
            capturedAt=datetime.now(timezone.utc).isoformat(),sourceDataAsOf=None,rows=rows,
            seriesGranularity='day-or-hour',labelsVerified=True,coverage=coverage,**mapped)
    finally:session.close()

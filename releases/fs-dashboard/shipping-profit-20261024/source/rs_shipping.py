"""RS native Order shipping totals. Aggregate-only; reuse Order8768 without login."""
from datetime import datetime, timezone
from decimal import Decimal
import sys
from rs_admin import selection, SITES, SERVERS, ORDER_TYPES, label, number

ENDPOINT='/stats/admin_index/delivery.html'
SOURCE='order-shipping-rs-v1'

def filters(q):
    q={**q,**selection(q)}
    begin,stop=(datetime.strptime(q['period'][k],'%Y-%m-%d %H:%M') for k in ('start','end'))
    if stop<=begin:raise ValueError('shipping_period_invalid')
    return dict(genre='1',gid='506',aid=str(SERVERS[q['rs_server']][0] or '0'),
                cid=ORDER_TYPES[q['rs_category']] or '-1',status='-1',op_id='0',
                **{'source[]':'' if q['rs_site']=='all' else SITES[q['rs_site']][1]},
                is_stock='',show_ccy='-1',start=q['period']['start'],end=q['period']['end'],keyword='',sn='')

def project(raw,q):
    want=filters(q)
    if raw['filters']!=want or raw['headers']!=['游戏','￥销售总额','￥采购总额','利润率','订单总数','交易总数']:
        raise ValueError('shipping_filter_or_columns_changed')
    rows=raw['rows']
    if len(rows)>1 or rows and (len(rows[0])!=6 or rows[0][0]!='506 | RS'):
        raise ValueError('shipping_game_scope_changed')
    if rows:
        r=rows[0];sale,cost=number(r[1]),number(r[2]);rate=number(r[3].removesuffix('%'))
        orders,trades=number(r[4],True),number(r[5],True)
        if sale<0 or cost<0 or not r[3].endswith('%'):raise ValueError('shipping_amount_invalid')
        if sale and abs((sale-cost)/sale*100-rate)>Decimal('.015'):raise ValueError('shipping_margin_mismatch')
        if not sale and (cost or rate):raise ValueError('shipping_zero_denominator_changed')
    else:sale=cost=Decimal(0);rate=None;orders=trades=0
    if not sale:rate=None
    values={'profitCny':(sale-cost,'CNY'),'shippingSalesCny':(sale,'CNY'),'shippingCostCny':(cost,'CNY'),'profitMarginPct':(rate,'percent')}
    metrics={k:dict(value=float(v) if v is not None else None,status='available' if v is not None else 'not_applicable',unit=u,
                    source='Order发货统计',field='利润率' if k=='profitMarginPct' else k,scope=label(q),definition='发货统计销售总额减采购总额；非净利润') for k,(v,u) in values.items()}
    return dict(system='order.p2pah.cn',endpoint=ENDPOINT,sourceContract=SOURCE,status='available',period=q['period'],
                timezone='Asia/Shanghai',currency='CNY',filters=want,rsSelection=selection(q),scopeLabel=label(q),
                normalisedScope=want['source[]'] or 'all-websites',capturedAt=datetime.now(timezone.utc).isoformat(),
                timeBasis='交易时间',orders=orders,transactions=trades,metrics=metrics,rows=[],dimensions={},labelsVerified=True)

def collect(q):
    from lxml import html
    sys.path.insert(0,'/opt/sales-dashboard/collector')
    import p2pah_auth as auth
    session=auth.Session()
    try:
        auth._global_order.fill_jar(session.order.cookies)
        response=session.order.get(auth.ORDER_SITE+ENDPOINT,params=filters(q),timeout=90,verify=False,allow_redirects=False)
        if response.status_code in (301,302,401,403):raise PermissionError('shipping_session_denied')
        if response.status_code!=200:raise OSError('shipping_page_unavailable')
        doc=html.fromstring(response.text)
        if doc.xpath('//input[@type="password"]'):raise PermissionError('shipping_session_denied')
        forms=doc.xpath('//form[@action="'+ENDPOINT+'"]')
        if len(forms)!=1:raise ValueError('shipping_form_changed')
        echoed={}
        for name in filters(q):
            fields=forms[0].xpath('.//*[@name=$name]',name=name)
            if len(fields)!=1:raise ValueError('shipping_filter_missing')
            e=fields[0]
            if e.tag=='select':
                options=e.xpath('./option[@selected]')
                if not options and e.get('multiple') is None:options=e.xpath('./option')[:1]
                if len(options)>1:raise ValueError('shipping_multiple_sources')
                echoed[name]=options[0].get('value','') if options else ''
            else:echoed[name]=e.get('value','')
        tables=doc.xpath('//table[.//th[normalize-space()="订单总数"]]')
        if len(tables)!=1:raise ValueError('shipping_table_missing')
        headers=[' '.join(e.itertext()).strip() for e in tables[0].xpath('.//th')]
        rows=[]
        for tr in tables[0].xpath('.//tbody/tr'):
            cells=tr.xpath('./td')
            if cells and not tr.xpath('./td[@colspan]'):rows.append([' '.join(e.itertext()).strip() for e in cells])
            elif cells and '没有数据' not in ''.join(tr.itertext()) and '暂无' not in ''.join(tr.itertext()):raise ValueError('shipping_unknown_empty_state')
        return project(dict(filters=echoed,headers=headers,rows=rows),q)
    finally:session.close()

def daily(raw,expected):
    from profit_daily import check_scope,stamp,utc
    from datetime import date,timedelta
    day=date.fromisoformat(raw['date']);period={'start':str(day)+' 00:00','end':str(day+timedelta(days=1))+' 00:00'}
    f=raw['filters'];scope=dict(sites=raw['normalisedScope'],orderGameId=f['gid'],orderProductType=f['cid'],orderStatus=f['status'],orderAreaId=f['aid'])
    check_scope(raw['profileKey'],scope,expected)
    if raw['endpoint']!=ENDPOINT or raw['sourceContract']!=SOURCE or raw['period']!=period or raw['currency']!='CNY' or raw['timezone']!='Asia/Shanghai' or f['start']!=period['start'] or f['end']!=period['end'] or f['genre']!='1' or raw.get('labelsVerified') is not True:raise ValueError('shipping_daily_source_changed')
    captured=utc(raw['capturedAt'])
    if stamp(captured).astimezone(timezone(timedelta(hours=8))).date()<=day:raise ValueError('shipping_daily_not_closed')
    metrics=raw['metrics']
    return dict(profileKey='RS',date=str(day),period=period,timezone='Asia/Shanghai',currency='CNY',scope=scope,
                profitMarginPct=metrics['profitMarginPct']['value'],profitCny=metrics['profitCny']['value'],salesCny=metrics['shippingSalesCny']['value'],costCny=metrics['shippingCostCny']['value'],
                orders=raw['orders'],transactions=raw['transactions'],revenueUsd=None,profitUsd=None,costUsd=None,status='available',
                source='order.p2pah.cn',endpoint=ENDPOINT,sourceContract=SOURCE,capturedAt=captured,latestAttemptAt=captured,
                latestAttemptStatus='available',marginUnit='percent',profitCostStatus='available',stale=False)

def validate_day(row,expected):
    from profit_daily import check_scope,stamp
    from datetime import date,timedelta
    check_scope(row['profileKey'],row['scope'],expected);day=date.fromisoformat(row['date'])
    if row['period']!={'start':str(day)+' 00:00','end':str(day+timedelta(days=1))+' 00:00'} or row['endpoint']!=ENDPOINT or row['sourceContract']!=SOURCE or row['source']!='order.p2pah.cn' or row['currency']!='CNY' or row['timezone']!='Asia/Shanghai' or row['status']!='available':raise ValueError('shipping_daily_contract_changed')
    stamp(row['capturedAt']);stamp(row['latestAttemptAt'])
    sale,cost,profit=(number(row[k]) for k in ('salesCny','costCny','profitCny'))
    if abs(sale-cost-profit)>Decimal('.001') or any(row[k] is not None for k in ('revenueUsd','profitUsd','costUsd')):raise ValueError('shipping_daily_amount_changed')
    number(row['orders'],True);number(row['transactions'],True)
    rate=row['profitMarginPct']
    if sale and (rate is None or abs((sale-cost)/sale*100-number(rate))>Decimal('.015')) or not sale and rate is not None:raise ValueError('shipping_daily_margin_changed')

"""RS native Order shipping totals. Aggregate-only; reuse Order8768 without login."""
from datetime import datetime, timezone
from decimal import Decimal
import sys
from rs_admin import number
import re
# shortcut: IDs match the current dashboard catalog; extend when registering another game.
GAMES={'MMOEXP': '0', 'POE2': '552', 'D4': '456', 'AION2': '826', 'FC27': '1322', 'NBA2K27': '1306', 'NFL27': '1258', 'MLB26': '922', 'CFB27': '1256', 'FC26': '824', 'RS': '506', 'MAPLESTORY_CLASSIC': '1300', 'ARC_RAIDERS': '864', 'DARK_AND_DARKER': '588', 'WOW_FOREVER': '1364', 'ARENA_BREAKOUT_INFINITE': '836', 'COD_BO7': '838'}
from management_profiles import PROFILES as MANAGEMENT_PROFILES
GAMES.update({p[0]:str(p[2]) for p in MANAGEMENT_PROFILES})
CATEGORIES={'-1':'全部类目','0':'混合','1':'货币','2':'物品','3':'账号','4':'代练','5':'CD keys','6':'Coaching','7':'Top Up','8':'Skins','9':'Gift cards'}


ENDPOINT='/stats/admin_index/delivery.html'
SOURCE='order-shipping-v1'

def selection(q):
    site,category=q.get('profit_site','main'),q.get('profit_category','-1')
    if q.get('profile') not in GAMES or site not in ('main','all') or category not in CATEGORIES:raise ValueError('invalid_shipping_selection')
    return dict(gid=GAMES[q['profile']],site=site,cid=category)

def label(q):
    s=selection(q)
    return ('MMOEXP主站' if s['site']=='main' else '全部网站')+' · '+q['profile']+' · '+CATEGORIES[s['cid']]

def filters(q):
    s=selection(q)
    begin,stop=(datetime.strptime(q['period'][k],'%Y-%m-%d %H:%M') for k in ('start','end'))
    if stop<=begin:raise ValueError('shipping_period_invalid')
    return dict(genre='1',gid=s['gid'],aid='0',cid=s['cid'],status='-1',op_id='0',
                **{'source[]':'www.mmoexp.com' if s['site']=='main' else '', 'ship_source[]':''},
                show_ccy='-1',start=q['period']['start'],end=q['period']['end'],keyword='',sn='',wid='')

def project(raw,q):
    want=filters(q)
    if raw['filters']!=want or raw['headers']!=['游戏','￥销售总额','￥采购总额','利润率','订单总数','交易总数']:
        raise ValueError('shipping_filter_or_columns_changed')
    rows=raw['rows']
    seen=set();sale=cost=Decimal(0);orders=trades=0;rates=[]
    for r in rows:
        game=re.fullmatch(r'(\d+)\s*\|\s*.+',r[0]) if len(r)==6 else None
        if not game or game[1] in seen or want['gid']!='0' and game[1]!=want['gid']:raise ValueError('shipping_game_scope_changed')
        seen.add(game[1]);s,c=number(r[1]),number(r[2]);rate=number(r[3].removesuffix('%'))
        if s<0 or c<0 or not r[3].endswith('%'):raise ValueError('shipping_amount_invalid')
        if s and abs((s-c)/s*100-rate)>Decimal('.015'):raise ValueError('shipping_margin_mismatch')
        if not s and rate:raise ValueError('shipping_zero_denominator_changed')
        sale+=s;cost+=c;orders+=number(r[4],True);trades+=number(r[5],True);rates.append(rate)
    rate=((sale-cost)/sale*100 if want['gid']=='0' else rates[0]) if sale else None
    values={'profitCny':(sale-cost,'CNY'),'shippingSalesCny':(sale,'CNY'),'shippingCostCny':(cost,'CNY'),'profitMarginPct':(rate,'percent')}
    metrics={k:dict(value=float(v) if v is not None else None,status='available' if v is not None else 'not_applicable',unit=u,
                    source='Order发货统计',field='利润率' if k=='profitMarginPct' else k,scope=label(q),definition='发货统计销售总额减采购总额；非净利润') for k,(v,u) in values.items()}
    return dict(system='order.p2pah.cn',endpoint=ENDPOINT,sourceContract=SOURCE,status='available',period=q['period'],
                timezone='Asia/Shanghai',currency='CNY',filters=want,shippingSelection=selection(q),profileKey=q['profile'],gameRows=len(rows),scopeLabel=label(q),
                normalisedScope=want['source[]'] or 'all-websites',capturedAt=datetime.now(timezone.utc).isoformat(),
                timeBasis='交易时间',orders=orders,transactions=trades,metrics=metrics,rows=[],dimensions={},labelsVerified=True)

def collect(q,timeout=85):
    from lxml import html
    sys.path.insert(0,'/opt/sales-dashboard/collector')
    import p2pah_auth as auth
    session=auth.Session()
    try:
        auth._global_order.fill_jar(session.order.cookies)
        response=session.order.get(auth.ORDER_SITE+ENDPOINT,params=filters(q),timeout=timeout,verify=False,allow_redirects=False)
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
        if doc.xpath('//*[contains(@class,"pagination")]//a'):raise ValueError('shipping_pagination_unhandled')
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
    return dict(profileKey=raw['profileKey'],date=str(day),period=period,timezone='Asia/Shanghai',currency='CNY',scope=scope,
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
    if sale<0 or cost<0:raise ValueError('shipping_daily_amount_invalid')
    if sale and (rate is None or abs((sale-cost)/sale*100-number(rate))>Decimal('.015')) or not sale and rate is not None:raise ValueError('shipping_daily_margin_changed')

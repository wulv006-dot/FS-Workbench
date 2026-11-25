"""Read bounded daily profit aggregates from the shared Order HTTP session."""
from datetime import datetime,timezone,date,timedelta
from decimal import Decimal
import sys,json,re
from primary_fields import extract

import time

def number(raw,integer=False):
    n=Decimal(str(raw).replace('$','').replace(',',''))
    if not n.is_finite() or n<0 or (integer and n!=n.to_integral_value()):raise ValueError('invalid_metric')
    return int(n) if integer else float(n)

def parse_daily_label(label,begin,stop):
    """Native Beijing label; parse real calendars and enforce an exclusive end."""
    label=str(label)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}(?::00)?',label):
        point=datetime.strptime(label if ':' in label else label+':00','%Y-%m-%d %H:%M')
        if not begin<=point<stop:raise ValueError('primary_hour_outside_period')
        return point.strftime('%Y-%m-%d %H:%M'),'hour'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',label):
        day=date.fromisoformat(label)
    elif re.fullmatch(r'\d{2}-\d{2}',label):
        candidates=[]
        for year in range(begin.year,stop.year+1):
            try:candidate=date(year,int(label[:2]),int(label[3:]))
            except ValueError:continue
            if begin.date()<=candidate<stop.date():candidates.append(candidate)
        if len(candidates)!=1:raise ValueError('primary_date_label_ambiguous')
        day=candidates[0]
    else:raise ValueError('primary_date_label_unverified')
    if not begin.date()<=day<stop.date():raise ValueError('primary_day_outside_period')
    return day.isoformat(),'day'

SAFE_FAILURE_CODES=frozenset({
    'invalid_metric','primary_login_or_page_unavailable','primary_filter_mismatch',
    'primary_metric_labels_mismatch','primary_average_mismatch','primary_series_unavailable',
    'primary_series_dates_unavailable','primary_series_length_mismatch','primary_series_schema_unverified',
    'primary_hour_outside_period','primary_day_outside_period','primary_date_label_ambiguous',
    'primary_date_label_unverified','primary_duplicate_date_label','primary_mixed_date_granularity',
    'primary_series_totals_mismatch','primary_zero_sentinel_scope_unverified',
    'primary_zero_sentinel_nonzero','primary_zero_sentinel_position_unverified',
    'native_daily_read_timeout','native_daily_read_failed'})
SENTINEL_CONTRACT='order-hour-zero-exclusive-end-sentinel-v1'

def safe_failure_code(exc):
    # Only these fixed tokens can leave the reader; never emit arbitrary messages.
    if type(exc).__name__=='TimeoutError':return 'native_daily_read_timeout'
    if type(exc) is ValueError and str(exc) in SAFE_FAILURE_CODES:return str(exc)
    return 'native_daily_read_failed'

def native_hour_point(label):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}(?::00)?',str(label)):return None
    try:return datetime.strptime(str(label) if ':' in str(label) else str(label)+':00','%Y-%m-%d %H:%M')
    except ValueError:return None

def parse_native_series(chart,orders,sales,begin,stop):
    # The two observed native schemas contain exactly these two series. Unknown
    # extra metrics are rejected even when zero, so no nonzero tail is ignored.
    series=chart.get('series');labels=chart.get('labels')
    if not isinstance(series,list) or len(series)!=2 or any(not isinstance(s,dict) for s in series) or {s.get('name') for s in series}!={'订单数','订单金额'}:
        raise ValueError('primary_series_schema_unverified')
    counts=next(s.get('data') for s in series if s['name']=='订单数')
    amounts=next(s.get('data') for s in series if s['name']=='订单金额')
    if not isinstance(labels,list) or not labels:raise ValueError('primary_series_dates_unavailable')
    if not isinstance(counts,list) or not isinstance(amounts,list) or not len(counts)==len(amounts)==len(labels):raise ValueError('primary_series_length_mismatch')
    rows=[];seen=set();granularities=set();sentinel_count=0
    for index,(label,n,a) in enumerate(zip(labels,counts,amounts)):
        raw_count,raw_amount=n,a
        n=number(n,True);a=number(a)
        point=native_hour_point(label)
        if point==stop:
            # This exception is ONLY the observed single complete Beijing day,
            # hourly, exclusive-next-midnight, final, unique, dual-zero marker.
            if stop-begin!=timedelta(days=1) or begin.time()!=datetime.min.time() or stop.time()!=datetime.min.time():
                raise ValueError('primary_zero_sentinel_scope_unverified')
            # Check exact raw Decimal zeros: tiny nonzero values must not underflow
            # to float zero and become an accepted padding marker.
            if Decimal(str(raw_count).replace('$','').replace(',',''))!=0 or Decimal(str(raw_amount).replace('$','').replace(',',''))!=0:
                raise ValueError('primary_zero_sentinel_nonzero')
            if index!=len(labels)-1 or sentinel_count:raise ValueError('primary_zero_sentinel_position_unverified')
            stamp=point.strftime('%Y-%m-%d %H:%M');kind='hour'
            sentinel_count+=1
        else:
            stamp,kind=parse_daily_label(label,begin,stop)
        if stamp in seen:raise ValueError('primary_duplicate_date_label')
        seen.add(stamp);granularities.add(kind)
        if len(granularities)>1:raise ValueError('primary_mixed_date_granularity')
        if point!=stop:rows.append({'date':stamp,'orders':n,'amount':a})
    if not rows:raise ValueError('primary_series_dates_unavailable')
    if sum(r['orders'] for r in rows)!=orders or abs(sum(Decimal(str(r['amount'])) for r in rows)-Decimal(str(sales)))>Decimal('.02'):
        raise ValueError('primary_series_totals_mismatch')
    return rows,dict(schemaVersion=1,contractId=SENTINEL_CONTRACT,excludedZeroEndpointCount=sentinel_count,exclusiveEndPreserved=True)

def read_one(reader,item,timeout_ms):
    filters={'status':item.get('status',''),'gid':str(item['gid']),'tid':item.get('tid',''),
             'start_paytime':item['start'],'end_paytime':item['end']}
    raw=reader.native_order_stats(filters,timeout=timeout_ms/1000)
    if len(raw['names']) < 5 or not ('订单数量' in raw['names'][0] and '订单金额' in raw['names'][1]):raise ValueError('primary_metric_labels_mismatch')
    orders=number(raw['metrics'][0],True);sales=number(raw['metrics'][1]);avg=number(raw['metrics'][4])
    if orders and abs(sales/orders-avg)>.031:raise ValueError('primary_average_mismatch')
    chart=next((c for c in raw['charts'] if c and '订单数量和金额' in (c['title'] or [])),None)
    if not chart:raise ValueError('primary_series_unavailable')
    begin=datetime.strptime(item['start'],'%Y-%m-%d %H:%M')
    stop=datetime.strptime(item['end'],'%Y-%m-%d %H:%M')
    rows,boundary_audit=parse_native_series(chart,orders,sales,begin,stop)
    return {'system':'order.p2pah.cn','endpoint':'/stats/admin_order/index.html','status':'available',
      'normalisedScope':'all-websites','period':{'start':item['start'],'end':item['end']},'filters':filters,
      'capturedAt':datetime.now(timezone.utc).isoformat(),'orders':orders,'revenueUsd':sales,'rows':rows,
      'charts':raw['charts'],'metrics':extract(raw['names'],raw['metrics']),'seriesBoundaryAudit':boundary_audit,'labelsVerified':True,'timezone':'Asia/Shanghai','currency':'USD'}


def validate_requests(payload):
    from datetime import date,timedelta
    if not isinstance(payload,dict):raise ValueError('daily_batch_envelope')
    wanted=payload.get('requests');budget=payload.get('budgetSeconds')
    if not isinstance(wanted,list) or not 1<=len(wanted)<=12 or type(budget) not in (int,float) or not 15<=budget<=240:
        raise ValueError('daily_batch_bounds')
    seen=set()
    for item in wanted:
        if not isinstance(item,dict):raise ValueError('daily_request')
        day=date.fromisoformat(item['date'])
        if item['start']!=str(day)+' 00:00' or item['end']!=str(day+timedelta(days=1))+' 00:00':raise ValueError('daily_period')
        if item['key'] in seen:raise ValueError('daily_duplicate')
        seen.add(item['key'])
    return wanted,float(budget)

def collect_bounded(reader,wanted,deadline,clock=time.monotonic,read=read_one):
    results={};abort=False
    for item in wanted:
        remaining=deadline-clock()
        if abort or remaining<3:
            results[item['key']]={'status':'not_started_budget'};continue
        attempted=datetime.now(timezone.utc).isoformat()
        try:
            results[item['key']]=read(reader,item,max(1,int(min(20,remaining)*1000)))
        except Exception as exc:
            # No raw exception/upstream error/session values leave the container.
            code=safe_failure_code(exc)
            results[item['key']]={'status':'unavailable','attemptedAt':attempted,'errorCode':code}
            if type(exc) is ValueError and str(exc)=='primary_login_or_page_unavailable':abort=True
    return results

if __name__=='__main__':
    if '/opt/fs-order-session' not in sys.path:
        sys.path.insert(0, '/opt/fs-order-session')
    from order_http import OrderHTTP
    payload=json.loads(sys.argv[1]);wanted,budget=validate_requests(payload)
    started=time.monotonic();deadline=started+budget-10
    reader=OrderHTTP()
    reader.acquire_session(timeout=min(40,budget-10))
    results=collect_bounded(reader,wanted,deadline)
    print(json.dumps(results,ensure_ascii=False,allow_nan=False))

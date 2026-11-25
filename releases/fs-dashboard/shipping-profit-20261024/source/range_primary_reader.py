"""Read native range aggregates from the shared Order HTTP session."""
from datetime import datetime,timezone,date
from decimal import Decimal
import sys,json,re
if '/opt/fs-transaction-snapshot' not in sys.path:
    sys.path.insert(0, '/opt/fs-transaction-snapshot')
if '/opt/fs-order-session' not in sys.path:
    sys.path.insert(0, '/opt/fs-order-session')
from order_http import OrderHTTP
from primary_fields import extract


def number(raw,integer=False):
    n=Decimal(str(raw).replace('$','').replace(',',''))
    if not n.is_finite() or n<0 or (integer and n!=n.to_integral_value()):raise ValueError('invalid_metric')
    return int(n) if integer else float(n)


def collect(requests, reader):
    results = {}
    for item in requests:
        filters={'status':item.get('status',''),'gid':str(item['gid']),'tid':item.get('tid',''),
                 'start_paytime':item['start'],'end_paytime':item['end']}
        if 'aid' in item:
            if str(item['gid'])!='506' or str(item['aid']) not in ('0','12368','12370'):raise ValueError('invalid_rs_area')
            filters['aid']=str(item['aid'])
        timeout = 180 if item['start'][:10] != item['end'][:10] else 45
        raw = reader.native_order_stats(filters, timeout=timeout)
        if len(raw['names']) < 5 or not ('订单数量' in raw['names'][0] and '订单金额' in raw['names'][1]):raise ValueError('primary_metric_labels_mismatch')
        orders=number(raw['metrics'][0],True);sales=number(raw['metrics'][1]);avg=number(raw['metrics'][4])
        if orders and abs(sales/orders-avg)>.031:raise ValueError('primary_average_mismatch')
        chart=next((c for c in raw['charts'] if c and '订单数量和金额' in (c['title'] or [])),None)
        if not chart:raise ValueError('primary_series_unavailable')
        counts=next(s['data'] for s in chart['series'] if s['name']=='订单数')
        amounts=next(s['data'] for s in chart['series'] if s['name']=='订单金额')
        if not (len(counts)==len(amounts)==len(chart['labels'])):raise ValueError('primary_series_length_mismatch')
        rows=[];native_series=[];unknown_label=False;start=date.fromisoformat(item['start'][:10]);end=date.fromisoformat(item['end'][:10])
        for label,n,a in zip(chart['labels'],counts,amounts):
            label=str(label);hour=re.fullmatch(r'(\d{4}-\d{2}-\d{2}) (\d{2})',label)
            if hour:stamp=label+':00'
            elif re.fullmatch(r'\d{4}-\d{2}-\d{2}',label):stamp=label
            elif re.fullmatch(r'\d{2}-\d{2}',label):
                candidates=[date(y,int(label[:2]),int(label[3:])) for y in range(start.year,end.year+1)]
                candidates=[d for d in candidates if start<=d<=end]
                if len(candidates)!=1:raise ValueError('primary_date_label_ambiguous')
                stamp=candidates[0].isoformat()
            else:stamp=None;unknown_label=True
            native_series.append({'label':label,'orders':number(n,True),'amount':number(a)})
            if stamp is not None:rows.append({'date':stamp,'orders':number(n,True),'amount':number(a)})
        if sum(r['orders'] for r in native_series)!=orders or abs(sum(Decimal(str(r['amount'])) for r in native_series)-Decimal(str(sales)))>Decimal('.02'):
            raise ValueError('primary_series_totals_mismatch')
        results[item['key']]={'system':'order.p2pah.cn','endpoint':'/stats/admin_order/index.html','status':'available',
          'normalisedScope':'all-websites','period':{'start':item['start'],'end':item['end']},'filters':filters,
          'capturedAt':datetime.now(timezone.utc).isoformat(),'orders':orders,'revenueUsd':sales,'rows':[] if unknown_label else rows,'nativeSeries':native_series,'seriesGranularity':'upstream-undated' if unknown_label else 'day-or-hour',
          **({'rsScopeLabel':item.get('rsScopeLabel','')} if 'aid' in item else {}),'charts':raw['charts'],'metrics':extract(raw['names'],raw['metrics']),'labelsVerified':True,'timezone':'Asia/Shanghai','currency':'USD'}

    return results


if __name__ == '__main__':
    requests = json.loads(sys.argv[1])
    reader = OrderHTTP()
    if requests:
        reader.acquire_session()
    print(json.dumps(collect(requests, reader), ensure_ascii=False, allow_nan=False))

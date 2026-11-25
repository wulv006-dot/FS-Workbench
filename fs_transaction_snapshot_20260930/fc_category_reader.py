"""Read FC27 category aggregates through the shared Order HTTP session."""
from datetime import datetime,timezone,date
from decimal import Decimal
import sys,json,re,time
if '/opt/fs-order-session' not in sys.path:
    sys.path.insert(0, '/opt/fs-order-session')
from order_http import OrderHTTP
from primary_fields import extract

def number(raw,integer=False):
 n=Decimal(str(raw).replace('$','').replace(',',''))
 if not n.is_finite() or n<0 or (integer and n!=n.to_integral_value()):raise ValueError('primary_invalid_metric')
 return int(n) if integer else float(n)

def read(reader,item,deadline):
 if item['gid']!=1322 or str(item.get('tid','')) not in ('','1','2','4'):raise ValueError('primary_invalid_fc_filter')
 remaining=int((deadline-time.monotonic())*1000)
 if remaining<5000:raise ValueError('primary_batch_budget_exhausted')
 filters={'status':'','gid':'1322','aid':'0','tid':str(item.get('tid','')),'start_paytime':item['start'],'end_paytime':item['end']}
 raw=reader.native_order_stats(filters,timeout=min(45,remaining/1000))
 if len(raw['names']) < 5 or not ('订单数量' in raw['names'][0] and '订单金额' in raw['names'][1]):raise ValueError('primary_metric_labels_mismatch')
 orders=number(raw['metrics'][0],True);sales=number(raw['metrics'][1]);avg=number(raw['metrics'][4])
 if orders and abs(sales/orders-avg)>.031:raise ValueError('primary_average_mismatch')
 chart=next((c for c in raw['charts'] if c and '订单数量和金额' in (c['title'] or [])),None)
 if not chart:raise ValueError('primary_series_unavailable')
 counts=next(s['data'] for s in chart['series'] if s['name']=='订单数');amounts=next(s['data'] for s in chart['series'] if s['name']=='订单金额')
 if not(len(counts)==len(amounts)==len(chart['labels'])):raise ValueError('primary_series_length_mismatch')
 start=date.fromisoformat(item['start'][:10]);end=date.fromisoformat(item['end'][:10]);native=[];rows=[];unknown=False
 for label,n,a in zip(chart['labels'],counts,amounts):
  label=str(label);stamp=None
  if re.fullmatch(r'\d{4}-\d{2}-\d{2}( \d{2})?',label):stamp=label+':00' if len(label)>10 else label
  elif re.fullmatch(r'\d{2}-\d{2}',label):
   candidates=[date(y,int(label[:2]),int(label[3:])) for y in range(start.year,end.year+1)]
   candidates=[d for d in candidates if start<=d<=end]
   if len(candidates)!=1:raise ValueError('primary_date_label_ambiguous')
   stamp=candidates[0].isoformat()
  else:unknown=True
  row={'orders':number(n,True),'amount':number(a)};native.append({'label':label,**row})
  if stamp:rows.append({'date':stamp,**row})
 if sum(r['orders'] for r in native)!=orders or abs(sum(Decimal(str(r['amount'])) for r in native)-Decimal(str(sales)))>Decimal('.02'):raise ValueError('primary_series_totals_mismatch')
 return {'system':'order.p2pah.cn','endpoint':'/stats/admin_order/index.html','status':'available','normalisedScope':'all-websites',
  'period':{'start':item['start'],'end':item['end']},'filters':filters,'capturedAt':datetime.now(timezone.utc).isoformat(),
  'orders':orders,'revenueUsd':sales,'rows':[] if unknown else rows,'nativeSeries':native,'seriesGranularity':'upstream-undated' if unknown else 'day-or-hour',
  'charts':raw['charts'],'metrics':extract(raw['names'],raw['metrics']),'labelsVerified':True,'timezone':'Asia/Shanghai','currency':'USD'}

def main():
 requests=json.loads(sys.argv[1]);results={}
 if not isinstance(requests,list) or len(requests)>20:raise ValueError('invalid_batch')
 budget=min(540,max(20,int(requests[0].get('batchBudgetSeconds',540)))) if requests else 20
 deadline=time.monotonic()+budget
 reader=OrderHTTP()
 if requests:reader.acquire_session(timeout=min(40,budget))
 for item in requests:
  try:results[item['key']]=read(reader,item,deadline)
  except Exception as e:
   safe=str(e) if isinstance(e,ValueError) and str(e).startswith('primary_') else 'primary_category_unavailable'
   results[item['key']]={'status':'unavailable','period':{'start':item['start'],'end':item['end']},'error':safe}
 print(json.dumps(results,ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()

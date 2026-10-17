"""FC27 aggregate-only extension. Original source IDs and native rates are retained."""
from datetime import datetime,timedelta,date,timezone
from decimal import Decimal
import copy,math

TYPES=(('coins','1','Coins'),('items','2','Items'),('boosting','4','Boosting'))
KNOWN_TYPES={'1','2','3','4','5','6','7','8','9'}
CONTRACT='fc27-order-types-v1'

def scalar(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):return None
 return v

def compact(record):
 if not isinstance(record,dict) or record.get('status')!='available':
  return {'status':'unavailable','orders':None,'revenueUsd':None,'averageOrderUsd':None,'profitMarginPct':None,'rows':[],'nativeSeries':[]}
 metrics=record.get('metrics',{})
 return {'status':'available','orders':scalar(record.get('orders')),'revenueUsd':scalar(record.get('revenueUsd')),
  'averageOrderUsd':scalar(metrics.get('averageOrderUsd',{}).get('value')),
  'profitMarginPct':scalar(metrics.get('profitMarginPct',{}).get('value')),
  'period':copy.deepcopy(record.get('period')),'filters':copy.deepcopy(record.get('filters')),
  'capturedAt':record.get('capturedAt'),'rows':copy.deepcopy(record.get('rows',[])),
  'nativeSeries':copy.deepcopy(record.get('nativeSeries',[])),
  'seriesGranularity':record.get('seriesGranularity','day-or-hour'),
  'source':'order.p2pah.cn','metricDefinitions':copy.deepcopy(metrics)}

def valid_daily(row,day,tid):
 if not isinstance(row,dict) or row.get('status')!='available':return False
 end=(date.fromisoformat(day)+timedelta(days=1)).isoformat()+' 00:00'
 f=row.get('filters') or {}
 return row.get('period')=={'start':day+' 00:00','end':end} and str(f.get('gid'))=='1322' and f.get('tid')==tid and f.get('status','')=='' and str(f.get('aid','0'))=='0'

def merge_daily(previous,records,today):
 # Older successful native days keep their own provenance; no rate interpolation.
 earliest=(today-timedelta(days=90)).isoformat();out={}
 for day,rows in (previous or {}).get('dailyMetrics',{}).items():
  if earliest<=day<today.isoformat() and isinstance(rows,dict):
   good={key:copy.deepcopy(rows[key]) for key,tid,_ in TYPES if valid_daily(rows.get(key),day,tid)}
   if good:out[day]=good
 for request_key,r in records.items():
  parts=request_key.split(':')
  if len(parts)!=4 or parts[:2]!=['daily','FC27']:continue
  day,key=parts[2:];tid=next((tid for k,tid,_ in TYPES if k==key),None)
  if not tid or not (earliest<=day<today.isoformat()):continue
  candidate=compact(r)
  candidate['rows']=[];candidate['nativeSeries']=[]
  candidate['metricDefinitions']={k:v for k,v in candidate.get('metricDefinitions',{}).items() if k in ('averageOrderUsd','profitMarginPct')}
  if valid_daily(candidate,day,tid):out.setdefault(day,{})[key]=candidate
 return dict(sorted(out.items()))

def cycle_requests(today,history,cutoff,previous):
 period={'start':today.isoformat()+' 00:00','end':cutoff};out=[]
 for key,tid,_ in TYPES:
  out.append({'key':'analytics:'+key+':today','gid':1322,'tid':tid,**period})
 out.append({'key':'analytics:boosting:history','gid':1322,'tid':'4','start':history,'end':period['start']})
 # Refresh yesterday for final settlements and at most one missing older day.
 yesterday=today-timedelta(days=1);days=[yesterday]
 for n in range(2,8):
  d=today-timedelta(days=n);raw=(previous or {}).get('dailyMetrics',{}).get(d.isoformat(),{})
  if not all(valid_daily(raw.get(key),d.isoformat(),tid) for key,tid,_ in TYPES):days.append(d);break
 for day in days:
  for key,tid,_ in TYPES:
   out.append({'key':'daily:FC27:'+day.isoformat()+':'+key,'gid':1322,'tid':tid,
    'start':day.isoformat()+' 00:00','end':(day+timedelta(days=1)).isoformat()+' 00:00'})
 return out

def type_breakdown(total):
 rows=[]
 for c in total.get('charts') or []:
  if c and '产品类型' in (c.get('title') or []):
   for s in c.get('series') or []:
    for row in s.get('data') or []:
     if not isinstance(row,dict) or 'type' not in row:continue
     try:n=int(row['count']);v=float(Decimal(str(row['value'])))
     except (ValueError,TypeError,KeyError):continue
     if n<0 or not math.isfinite(v):continue
     rows.append({'rawTypeId':str(row['type']),'rawName':str(row.get('name') or row['type']),'orders':n,'revenueUsd':v,
      'mapping':'primary-category' if str(row['type']) in {tid for _,tid,_ in TYPES} else 'other-original-type' if str(row['type']) in KNOWN_TYPES else 'unmapped'})
 return rows

def analysis(total,records,keymap,period,daily=None):
 cats=[{'key':key,'rawTypeId':tid,'label':label,**compact(records.get(keymap[key]))} for key,tid,label in TYPES]
 core=compact(total);complete=core['status']=='available' and all(c['status']=='available' for c in cats)
 all_amount=core['revenueUsd'];subtotal=sum(Decimal(str(c['revenueUsd'])) for c in cats) if complete and all(c['revenueUsd'] is not None for c in cats) else None
 rest=None if subtotal is None or all_amount is None else float(Decimal(str(all_amount))-subtotal)
 share='available' if complete and all_amount is not None and all_amount>0 and rest is not None and rest>=-0.02 else 'not_computable' if all_amount==0 else 'incomplete'
 return {'schemaVersion':1,'contractId':CONTRACT,'scope':'all-websites','game':{'orderId':1322,'adminId':1327},
  'platform':{'orderAreaId':'0','label':'所有平台'},'statusFilter':'全部状态','timezone':'Asia/Shanghai','currency':'USD',
  'period':copy.deepcopy(period),'totals':core,'categories':cats,'originalTypes':type_breakdown(total),
  'status':'available' if complete else 'partial','shareStatus':share,'otherRevenueUsd':rest,
  'dailyMetrics':copy.deepcopy(daily or {}),'generatedAt':datetime.now(timezone.utc).isoformat(),
  'marginDefinition':'Order后台利润率原值；毛/净及成本公式未公开，不推算利润金额或平均每日比例',
  'missingFields':['SKU销售数量','商品TOP','分类新客/复购','利润金额'],
  'noCustomerAllocation':True,'unitDefinition':'订单数不是商品数量或金币到账量'}

def cycle_analysis(primary,extra,today,previous):
 daily=merge_daily(previous,extra,today)
 today_total=primary.get('FC27:today',{})
 current=analysis(today_total,extra,{key:'analytics:'+key+':today' for key,_,_ in TYPES},today_total.get('period'),daily)
 history_sources={'coins':primary.get('FC27:coins',{}),'items':primary.get('FC27:items',{}),'boosting':extra.get('analytics:boosting:history',{})}
 history_total=primary.get('FC27:all',{})
 current['history']=analysis(history_total,history_sources,{key:key for key,_,_ in TYPES},history_total.get('period'),daily)
 current['history']['dailyMetrics']={}
 if current['status']!='available' and (previous or {}).get('status')=='available':
  current['lastGood']={k:copy.deepcopy(v) for k,v in previous.items() if k not in ('lastGood','dailyMetrics','history')}
 return current

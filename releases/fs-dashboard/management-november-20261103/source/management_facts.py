"""Versioned management facts. Existing FS read API only; no model or business writes."""
from calendar import monthrange
from management_components import aggregate_components
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,date,timedelta,timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib,json,time
from pathlib import Path
SH=timezone(timedelta(hours=8))
CONTRACT='fs-management-daily-v2'
DATA_SCOPE='all-websites-v1'
SOURCE_CONTRACT='admin-paid-order-labelled-supplement-v2'
METRICS=('rev','ord','prof','new','aov','rep','ful','mar')
def numeric(v):return type(v) in (int,float) and v==v and abs(v)<1e15
def round2(v):return float(Decimal(str(v)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if numeric(v) else None
def stable(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def fingerprint(v):return hashlib.sha256(stable(v).encode()).hexdigest()
def metric(source,key):
 m=(source.get('metrics') or {}).get(key) or {}
 return m.get('value') if m.get('status')=='available' and numeric(m.get('value')) else None

def project_summary(raw,profile,start,end):
 q=raw.get('query') or {};p=raw.get('profile') or {};a=p.get('supplement') or {};o=p.get('primary') or {}
 period={'start':start+' 00:00','end':(date.fromisoformat(end)+timedelta(days=1)).isoformat()+' 00:00'}
 if raw.get('scopeContractId')!=SOURCE_CONTRACT or p.get('key')!=profile or q.get('start')!=start or q.get('end')!=end or q.get('timezone')!='Asia/Shanghai' or q.get('profile')!=profile or q.get('period')!=period:raise ValueError('source_contract_mismatch')
 result=dict.fromkeys(METRICS);notes={};sources={}
 for name,src in [('Admin',a),('Order',o)]:
  meta=(raw.get('sources') or {}).get(name) or {}
  sources[name]={k:meta.get(k,src.get(k)) for k in ('status','capturedAt','sourceDataAsOf','period','stale','normalisedScope')}
 def valid(src,name):
  meta=sources[name]
  # Keep the exact period's last successful native result during revalidation.
  return raw.get('status') in ('available','stale') and src.get('status')=='available' and src.get('period')==period and meta.get('status') in ('available','pending') and (not (raw.get('status')=='stale' or raw.get('stale') or src.get('stale') or meta.get('stale') or meta.get('status')=='pending') or bool(meta.get('capturedAt')))
 def all_sites(src):
  if src.get('normalisedScope')=='all-websites':return True
  return profile=='RS' and src.get('normalisedScope')=='rs-selected' and src.get('rsSelection')==dict(rs_site='all',rs_server='all',rs_category='all')
 if valid(a,'Admin'):
  filters=a.get('filters') or {}
  if not all_sites(a) or filters.get('site')!='' or filters.get('date')!=[period['start'],period['end']] or filters.get('pay_status')!=1 or filters.get('order_status')!='' or ((a.get('metrics') or {}).get('revenueUsd') or {}).get('unit')!='USD':raise ValueError('admin_all_sites_contract_mismatch')
  result.update(rev=metric(a,'revenueUsd'),ord=metric(a,'orders'))
  if not numeric(result['rev']) or result['rev']<0:result['rev']=None
  if type(result['ord']) is not int or result['ord']<0:result['ord']=None
  result.update(new=metric(a,'newCustomers'),rep=metric(a,'repeatRatePct'),ful=metric(a,'fulfillmentRatePct'))
  if type(result['new']) is not int or result['new']<0:result['new']=None
  for k in ('rep','ful'):
   if not numeric(result[k]) or not 0<=result[k]<=100:result[k]=None
  for k in ('new','rep','ful'):notes[k]='Admin 全站原生统计'
 if valid(o,'Order') and all_sites(o):
  native_rs=profile=='RS' and o.get('currency')=='CNY' and o.get('sourceContract')=='order-shipping-rs-v1' and o.get('rsSelection')==dict(rs_site='all',rs_server='all',rs_category='all') and (o.get('filters') or {}).get('source[]')==''
  if o.get('currency')=='USD' or native_rs:result['mar']=metric(o,'profitMarginPct')
 if numeric(result['rev']) and numeric(result['ord']) and result['ord']>0:result['aov']=round2(result['rev']/result['ord'])
 if numeric(result['rev']) and numeric(result['mar']):result['prof']=round2(result['rev']*result['mar']/100)
 notes.update(rev='Admin 全站已付款销售额（USD）；付款后退款保留付款记录',ord='Admin 全站已付款订单；付款后退款保留付款记录',aov='Admin 全站已付款销售额÷已付款订单',mar='Order 全站发货统计参考率' if profile=='RS' else 'Order 全站订单统计参考率',prof='Admin 全站销售额×Order 参考利润率；USD预估非实结，不是逐单实际成本毛利')
 retained=any(src.get('capturedAt') and (raw.get('status')=='stale' or raw.get('stale') or src.get('stale') or src.get('status')=='pending') for src in sources.values())
 return {'dataScope':DATA_SCOPE,'freshness':'retained' if retained else 'fresh','values':result,'notes':notes,'sources':sources,'period':{'start':start,'end':end},'status':'available' if all(numeric(result[k]) for k in ('rev','ord','prof')) else 'partial' if any(numeric(v) for v in result.values()) else 'unavailable'}

def periods(day,target):
 end=day-timedelta(days=1);first=date.fromisoformat(target+'-01');active=day.strftime('%Y-%m')==target
 prev_end=day-timedelta(days=day.weekday()+1);prev_start=prev_end-timedelta(days=6)
 return {'active':active,'start':first.isoformat(),'end':end.isoformat(),'observed':max(0,(end-first).days+1) if active else 0,'month_days':monthrange(first.year,first.month)[1],'previous_week':{'start':prev_start.isoformat(),'end':prev_end.isoformat()}}

def calculate(values,targets,observed,total):
 out={'completion':{},'forecast':{},'remainingDaily':{},'gapPoints':{}}
 for k in ('rev','ord','prof','new'):
  a,t=values.get(k),targets.get(k);ok=numeric(a) and numeric(t) and t>0 and observed>0
  out['completion'][k]=round2(a/t*100) if ok else None
  out['forecast'][k]=round2(a/observed*total) if ok else None
  out['remainingDaily'][k]=round2(max(t-a,0)/(total-observed)) if ok and total>observed else None
  out['gapPoints'][k]=round2(a/t*100-observed/total*100) if ok else None
 return out

def read_query(reader,profile,start,end,deadline,*,required=('rev','ord','prof'),sleep=time.sleep,monotonic=time.monotonic):
 from urllib.parse import urlencode
 path='/dashboard/fs-home/range.json?'+urlencode({'mode':'summary','profile':profile,'start':start,'end':end})
 local=min(deadline,monotonic()+100);best=None
 while monotonic()<local:
  try:reply=reader(path)
  except OSError as error:
   if best is not None and not isinstance(error,PermissionError):return best
   raise
  code=reply.get('http_status');raw=reply.get('body') or {}
  if code in (401,403):raise ValueError('source_denied')
  if code==200:
   row=project_summary(raw,profile,start,end)
   if all(numeric(row['values'][k]) for k in required):return row
   score=lambda x:sum(numeric(v) for v in x['values'].values())
   if best is None or score(row)>=score(best):best=row
  elif code not in (202,429,503):
   if best is not None:return best
   raise ValueError('source_http_'+str(code))
  remaining=local-monotonic()
  if remaining<=0:break
  delay=raw.get('retryAfterSeconds',5)
  if not numeric(delay) or delay<1:delay=5
  sleep(min(delay,remaining))
 if best is not None:return best
 raise TimeoutError('source_query_deadline')

def collect(at,targets,reader,*,cache=None,deadline_seconds=1800):
 if at.tzinfo is None:raise ValueError('timezone_required')
 at=at.astimezone(SH);day=at.date();period=periods(day,targets['period']);deadline=time.monotonic()+deadline_seconds
 cache=cache if cache is not None else {};errors=[]
 def query(profile,start,end,pin=False,required=('rev','ord','prof')):
  components=targets['models'].get(profile,{}).get('components')
  if components:
   return aggregate_components([query(key,start,end,pin=pin,required=required) for key in components])
  key=fingerprint([profile,start,end,SOURCE_CONTRACT,DATA_SCOPE])
  if pin and key in cache and cache[key].get('cacheCheckedOn')==day.isoformat() and all(numeric(cache[key]['values'].get(k)) for k in required):return cache[key]
  if time.monotonic()>=deadline:return {'values':dict.fromkeys(METRICS),'status':'unavailable','error':'collection_deadline'}
  try:
   row=read_query(reader,profile,start,end,deadline,required=required)
   if pin and row['status']=='available' and row['freshness']=='fresh':cache[key]=dict(row,cacheCheckedOn=day.isoformat())
   return row
  except (ValueError,TimeoutError,OSError) as error:
   code=str(error) if isinstance(error,ValueError) and str(error) in ('source_contract_mismatch','admin_all_sites_contract_mismatch','source_denied') else 'source_unavailable'
   return {'values':dict.fromkeys(METRICS),'status':'unavailable','error':code,'period':{'start':start,'end':end}}
 games=targets['overview']['games']
 def mapped(fn,items):
  with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(fn,items))
 # Finish all projects' main totals before spending the remaining budget on history.
 months=mapped(lambda g:query(g['profile'],period['start'],period['end']) if period['active'] and period['observed'] else {'values':dict.fromkeys(METRICS),'status':'target_period_expired' if not period['active'] else 'no_complete_days'},games)
 yesterdays=mapped(lambda g:query(g['profile'],period['end'],period['end'],pin=True),games)
 previous=mapped(lambda g:query(g['profile'],**period['previous_week'],pin=True),games)
 projects=[]
 for g,current,yday,prev in zip(games,months,yesterdays,previous):
  key=g['profile'];model=targets['models'][key];tgt={x['id']:x['val'] for x in model['l1']};l2={x['id']:x['val'] for x in model['l2']}
  result={'profile':key,'name':g['name'],'group':g['grp'],'owner':g['owner'],'month':current,'yesterday':yday,'previousWeek':prev,'targets':tgt,'secondaryTargets':l2,'daily':[],'weeks':[]}
  result.update(calculate(current['values'],tgt,period['observed'],period['month_days']));projects.append(result)
 by_key={x['profile']:x for x in projects}
 if period['active']:
  jobs=[(g['profile'],date.fromisoformat(period['end'])-timedelta(days=offset)) for offset in range(period['observed']) for g in games]
  def day_job(item):
   key,d=item;row=query(key,d.isoformat(),d.isoformat(),pin=True,required=('rev','ord'))
   return key,{'d':d.isoformat(),'w':d.weekday(),'rev':row['values']['rev'],'ord':row['values']['ord'],'status':row['status'],'sources':row.get('sources',{})}
  for key,row in mapped(day_job,jobs):by_key[key]['daily'].append(row)
 for result in projects:
  result['daily'].sort(key=lambda x:x['d']);model=targets['models'][result['profile']]
  for w in model['weeks']:
   import re
   dates=re.findall(r'(\d{1,2})/(\d{1,2})',w['lab']);row=dict(w,actRev=None,actOrd=None,days=0,status='not_started')
   if len(dates)==2:
    year=int(targets['period'][:4]);lo=date(year,int(dates[0][0]),int(dates[0][1]));hi=min(date(year,int(dates[1][0]),int(dates[1][1])),date.fromisoformat(period['end']))
    if period['active'] and lo<=hi:
     ds=[x for x in result['daily'] if lo.isoformat()<=x['d']<=hi.isoformat()];complete=len(ds)==(hi-lo).days+1 and all(numeric(x['rev']) and numeric(x['ord']) for x in ds)
     row.update(actRev=round2(sum(x['rev'] for x in ds)) if complete else None,actOrd=sum(x['ord'] for x in ds) if complete else None,days=(hi-lo).days+1,status='available' if complete else 'partial',sourcePeriod={'start':lo.isoformat(),'end':hi.isoformat()},basis='已读取 Admin 全站逐日合计；部分缺失不凑总数')
   result['weeks'].append(row)
 # The platform history uses the same all-websites contract, never the demo's embedded totals.
 history=[]
 for i in reversed(range(6)):
  month=day.month-i;year=day.year
  while month<=0:month+=12;year-=1
  first=date(year,month,1);last=min(date(year,month,monthrange(year,month)[1]),day-timedelta(days=1))
  if last<first:continue
  q=query('MMOEXP',first.isoformat(),last.isoformat(),pin=last.month!=day.month,required=('rev','ord'))
  history.append({'lab':str(month)+'月','start':first.isoformat(),'end':last.isoformat(),'rev':q['values']['rev'],'ord':q['values']['ord'],'prof':q['values']['prof'],'mtd':month==day.month,'status':q['status'],'sources':q.get('sources',{})})
 result={'contract':CONTRACT,'dataScope':DATA_SCOPE,'businessDate':day.isoformat(),'generatedAt':at.isoformat(),'validUntil':datetime.combine(day+timedelta(days=1),datetime.min.time(),SH).isoformat(),'timezone':'Asia/Shanghai','targetPeriod':targets['period'],'targetVersion':fingerprint(targets),'period':period,'projects':projects,'platformHistory':history,'forecastMethod':'累计实际÷已过完整日×目标月天数；线性情景，不是承诺','profitPolicy':'Admin 全站金额×Order 参考利润率；预估非实结','status':'available' if all(p['month']['status']=='available' and p['month'].get('freshness')=='fresh' for p in projects) else 'partial'}
 result['snapshotId']='management-'+fingerprint(result)[:24];return result

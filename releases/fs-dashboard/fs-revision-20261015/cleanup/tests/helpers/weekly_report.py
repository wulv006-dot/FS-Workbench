"""Server-only immutable weekly reports from existing readonly snapshots. No API auth."""
import argparse,copy,datetime as dt,hashlib,json,math,os,re,tempfile,subprocess
from pathlib import Path
from decimal import Decimal
TZ=dt.timezone(dt.timedelta(hours=8),'Asia/Shanghai')
CONTRACT='all-websites-order-primary-admin-supplement-v1'
CUSTOMERS={'1430398974':('mmoexp','MMOEXP-1'),'8154986819':('rsorder','RSOrder-1'),'3552474396':('rsorder','rsgoldfast.com · RSOrder')}
PROFILES=['MMOEXP','D4','POE2','FC27','FC26','NBA2K27','NFL27','MLB26','CFB27']
CORE=['orders','revenueUsd','averageOrderUsd','profitMarginPct']

def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()
def now():return dt.datetime.now(dt.timezone.utc)
def period(start):
 start=dt.date.fromisoformat(start)
 if start.weekday()!=0:raise ValueError('MONDAY_REQUIRED')
 stop=start+dt.timedelta(days=7)
 return {'id':start.isoformat()+'_'+stop.isoformat(),'start':start.isoformat(),'end':(stop-dt.timedelta(days=1)).isoformat(),'endExclusive':stop.isoformat(),'startAt':dt.datetime.combine(start,dt.time(),TZ).isoformat(),'endExclusiveAt':dt.datetime.combine(stop,dt.time(),TZ).isoformat(),'timezone':'Asia/Shanghai'}
def preceding_week(at):
 day=at.astimezone(TZ).date();return period((day-dt.timedelta(days=day.weekday()+7)).isoformat())
def next_monday(at):
 local=at.astimezone(TZ);day=local.date()+dt.timedelta(days=(7-local.weekday())%7);candidate=dt.datetime.combine(day,dt.time(2),TZ)
 return (candidate if candidate>local else candidate+dt.timedelta(days=7)).isoformat()
def finite(value):return type(value) in (int,float) and math.isfinite(value)
def parse_time(value):
 if not value:raise ValueError('PERIOD_NOT_PROVIDED')
 parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
 return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
def exact(source,p):
 r=source.get('period',{})
 try:return parse_time(r['start'])==parse_time(p['startAt']) and parse_time(r['end'])==parse_time(p['endExclusiveAt'])
 except (KeyError,ValueError,TypeError):return False
def pointer(path):
 if not path.is_file():raise ValueError('EXACT_BUSINESS_RANGE_MANIFEST_NOT_AVAILABLE')
 manifest=json.loads(path.read_text(encoding='utf-8'))
 relative=manifest.get('path','')
 if not re.fullmatch(r'(?:snapshots/)?[A-Za-z0-9_-]+/snapshot\.json',relative):raise ValueError('MANIFEST_PATH_INVALID')
 target=(path.parent/relative).resolve()
 if not target.is_relative_to(path.parent.resolve()):raise ValueError('MANIFEST_PATH_ESCAPE')
 raw=target.read_bytes()
 if len(raw)>5000000 or sha(raw)!=manifest.get('sha256'):raise ValueError('BUSINESS_SHA_MISMATCH')
 value=json.loads(raw)
 if value.get('snapshotId')!=manifest.get('snapshotId') or manifest.get('scopeContractId')!=CONTRACT:raise ValueError('BUSINESS_VERSION_MISMATCH')
 return value,{'snapshotId':manifest['snapshotId'],'sha256':manifest['sha256'],'generatedAt':manifest.get('generatedAt')}
def business(value,p,allow_fixture=False):
 if value.get('isMock') and not allow_fixture:raise ValueError('MOCK_INPUT_FORBIDDEN')
 if value.get('schemaVersion')!=2 or value.get('scope')!='all-websites' or value.get('scopeContractId')!=CONTRACT or value.get('timezone')!='Asia/Shanghai' or value.get('currency')!='USD':raise ValueError('BUSINESS_SCOPE_INVALID')
 # Provider must explicitly certify native exact half-open range aggregation.
 certificate=value.get('reportRange',{})
 if certificate.get('start')!=p['startAt'] or certificate.get('endExclusive')!=p['endExclusiveAt'] or certificate.get('boundary')!='[start,end)' or certificate.get('complete') is not True or certificate.get('coreAggregation')!='order-native':raise ValueError('EXACT_ORDER_WEEK_CERTIFICATE_NOT_AVAILABLE')
 result={key:value.get(key) for key in ['schemaVersion','supplementContractVersion','snapshotId','scopeContractId','scope','timezone','currency','generatedAt','generatedAtShanghai']}
 result['profiles']={};result['dashboard']={'profiles':{}};result['reportRange']=certificate
 for key in PROFILES:
  profile=value.get('profiles',{}).get(key)
  if not profile:raise ValueError('REQUIRED_WEEK_PROFILE_NOT_AVAILABLE')
  primary=profile.get('primary',{})
  if primary.get('system')!='order.p2pah.cn' or primary.get('status')!='available' or not exact(primary,p) or not exact(profile,p):raise ValueError('EXACT_PRIMARY_WEEK_NOT_AVAILABLE')
  metrics=copy.deepcopy(profile.get('metrics',{}))
  for field in CORE:
   metric=metrics.get(field,{})
   if metric.get('source')!='primary' or not finite(metric.get('value')):
    # A zero-order project may have an undefined native ratio; retain null, never infer.
    if key!='MMOEXP' and field in ['averageOrderUsd','profitMarginPct'] and metrics.get('orders',{}).get('value')==0 and metric.get('source')=='primary' and metric.get('value') is None:continue
    raise ValueError('NATIVE_ORDER_CORE_NOT_AVAILABLE')
  clean={k:copy.deepcopy(profile.get(k)) for k in ['key','name','period','dimensions'] if k in profile};clean['metrics']=metrics
  if clean.get('dimensions',{}).get('period') and not exact(clean['dimensions'],p):clean['dimensions']={}
  clean['primary']={k:copy.deepcopy(primary[k]) for k in ['system','status','period','filters','capturedAt','normalisedScope'] if k in primary}
  supplement=profile.get('supplement',{})
  if supplement.get('status')=='available' and supplement.get('system')=='admin.p2pah.cn' and exact(supplement,p):clean['supplement']={k:copy.deepcopy(supplement[k]) for k in ['system','status','period','filters','capturedAt','normalisedScope','metrics','dimensions'] if k in supplement}
  else:
   clean['supplement']={'status':'exact_week_not_provided','metrics':{},'dimensions':{},'period':{'start':p['startAt'],'end':p['endExclusiveAt']}}
   for field,item in metrics.items():
    if item.get('source')=='supplement':item.update(value=None,status='exact_week_not_provided')
  result['profiles'][key]=clean
  series=value.get('dashboard',{}).get('profiles',{}).get(key,{}).get('series',[])
  result['dashboard']['profiles'][key]={'series':[copy.deepcopy(row) for row in series if p['start']<=row.get('date','')<=p['end'] and not row.get('partial')],'hourly':[],'window':{'start':p['startAt'],'end':p['endExclusiveAt']}}
 return result

def change(a,b,percent=False):
 if not finite(a) or not finite(b):return None
 if percent:return {'kind':'percentage_points','value':a-b}
 return {'kind':'relative_percent','value':(a-b)/b*100} if b>0 else None
def comparison(current,previous):
 result={}
 for key,p in current['profiles'].items():
  old=(previous or {}).get('profiles',{}).get(key,{})
  # Native Admin whole-week metrics also have a verified previous range.
  # Prefer available primary values exactly as the renderer does; compare only
  # the same source, without inventing a cross-source denominator.
  def selected(profile):
   metrics=copy.deepcopy(profile.get('metrics',{}))
   for field,item in profile.get('supplement',{}).get('metrics',{}).items():
    if field not in CORE and (field not in metrics or not finite(metrics[field].get('value'))):metrics[field]=item
   return metrics
  before=selected(old)
  result[key]={field:change(item.get('value'),before.get(field,{}).get('value'),field.endswith('Pct')) if item.get('source')==before.get(field,{}).get('source') else None for field,item in selected(p).items()}
 return result
def coverage(dates,p):
 days=[(dt.date.fromisoformat(p['start'])+dt.timedelta(days=i)).isoformat() for i in range(7)];dates=sorted(set(d for d in dates if p['start']<=d<=p['end']))
 return {'requested_start':p['start'],'requested_end':p['end'],'returned_dates':dates,'latest_data_date':max(dates,default=None),'returned_days':len(dates),'requested_days':7,'missing_dates':[d for d in days if d not in dates],'complete_dates':dates==days}
def missing_table():return {'rows':[],'returned_dimension_rows':0,'displayed_rows':0,'row_coverage':None,'coverage_metric':'sessions','status':{'status':'exact_week_not_collected'}}
def stored_status(source,has_rows):
 attempt=(source or {}).get('lastAttemptStatus','unknown')
 semantic='api_failure_retained_rows' if attempt=='failed' and has_rows else 'api_failure_no_week_rows' if attempt=='failed' else 'latest_request_no_rows_not_zero' if attempt=='empty' else 'stored_week_rows_only' if has_rows else 'no_matching_week_rows'
 return {'status':'stored_daily_rows_only','latest_attempt_status':attempt,'result_semantics':semantic,'retained_previous':bool(has_rows and attempt in ['failed','empty']),'collected_at':(source or {}).get('collected_at'),'quality':{}}
def daily_source(source,p):
 rows=[{'dimensions':{'date':row['date']},'metrics':row['metrics']} for row in source.get('days',[]) if p['start']<=row['date']<=p['end']]
 c=coverage([r['dimensions']['date'] for r in rows],p)
 base={'resource':source.get('resource') or ('541418940' if source['id']=='ga4' else 'sc-domain:mmoexp.com'),'timezone':source['timezone'],'currency':source.get('currency'),'coverage':c,'daily':rows,'status':stored_status(source,bool(rows)),'aggregate_scope':'returned_daily_rows_only','changes':{},'comparison_status':'insufficient_dates','markets':[]}
 keys=['sessions','ecommercePurchases'] if source['id']=='ga4' else ['clicks','impressions']
 metrics={key:str(sum(Decimal(str(row['metrics'].get(key,'0'))) for row in rows)) if rows else None for key in keys}
 if source['id']=='ga4':
  metrics.update({key:None for key in ['activeUsers','newUsers','engagedSessions','engagementRate','screenPageViews','averageSessionDuration','bounceRate','purchaseRevenue']})
  base['breakdowns']={key:missing_table() for key in ['source_medium','device','country','landing_page']}
 else:
  clicks=Decimal(metrics['clicks'] or '0');impressions=Decimal(metrics['impressions'] or '0')
  metrics['ctr']=str(clicks/impressions) if impressions>0 else None
  metrics['position']=str(sum(Decimal(str(r['metrics'].get('position','0')))*Decimal(str(r['metrics'].get('impressions','0'))) for r in rows)/impressions) if impressions>0 else None
  base['breakdowns']={key:missing_table() for key in ['query','page','country']}
 base['metrics']=metrics;return base
def daily_ads(source,customer,p):
 rows=[{'dimensions':{'date':row['date']},'metrics':{key:str(row['metrics'].get(key,'0')) for key in ['impressions','clicks','conversions','conversionsValue']}|{'costMicros':str(Decimal(str(row['metrics'].get('cost','0')))*1000000)}} for row in (source or {}).get('days',[]) if p['start']<=row['date']<=p['end']]
 c=coverage([r['dimensions']['date'] for r in rows],p)
 c.update(query_range_complete=False,no_metric_row_dates=[],zero_rows_materialized=False)
 metrics={key:str(sum(Decimal(r['metrics'][key]) for r in rows)) if rows else None for key in ['impressions','clicks','conversions','conversionsValue']}
 metrics['cost']=str(sum(Decimal(r['metrics']['costMicros'])/1000000 for r in rows)) if rows else None
 for name,n,d in [('cpc','cost','clicks'),('cpa','cost','conversions'),('platformRoas','conversionsValue','cost')]:metrics[name]=str(Decimal(metrics[n])/Decimal(metrics[d])) if metrics.get(n) is not None and Decimal(metrics.get(d) or '0')>0 else None
 return {'customerId':customer,'brand':CUSTOMERS[customer][0],'label':CUSTOMERS[customer][1],'observed_name':(source or {}).get('label'),'currency':'USD','timezone':'Asia/Hong_Kong','metrics':metrics,'daily':rows,'coverage':c,'status':stored_status(source,bool(rows)),'aggregate_scope':'returned_daily_rows_only','changes':{},'comparison_status':'incomplete_query_range','campaigns':[],'campaign_count':None,'campaign_row_cost_coverage':None,'campaign_status':{'status':'exact_week_not_collected'}}
def marketing(model,p,allow_fixture=False):
 if model.get('schemaVersion')!=1 or (model.get('isMock') is not False and not allow_fixture):raise ValueError('REAL_GOOGLE_SNAPSHOT_REQUIRED')
 if any(a.get('resource') not in CUSTOMERS for a in model.get('adsAccounts',[])):raise ValueError('UNREVIEWED_ADS_CUSTOMER')
 selected=next((copy.deepcopy(row) for row in model.get('details',{}).get('periods',[]) if row['start']==p['start'] and row['end']==p['end']),None)
 if not selected:
  sources={s['id']:daily_source(s,p) for s in model.get('sources',[]) if s['id'] in ['ga4','gsc']}
  if set(sources)!= {'ga4','gsc'}:raise ValueError('GOOGLE_SOURCES_REQUIRED')
  accounts={a['resource']:a for a in model.get('adsAccounts',[])}
  selected={'id':p['start']+'_'+p['end'],'start':p['start'],'end':p['end'],'sources':sources,'adsAccounts':[daily_ads(accounts.get(c),c,p) for c in CUSTOMERS],'query_rules':{'version':'not_available_for_requested_week'},'comparison_period':None}
 else:
  if {a['customerId'] for a in selected['adsAccounts']}!=set(CUSTOMERS):raise ValueError('UNREVIEWED_ADS_CUSTOMER')
 notes=['GSC按America/Los_Angeles自然日，经营/GA4/Ads按北京时间或香港时间；不把窗口差异拼成跨源率']
 for name,source in selected['sources'].items():
  if not source['coverage']['complete_dates']:notes.append(name.upper()+'返回日行未覆盖完整本周；仅展示截至实际日期的已存数据')
  if source['status'].get('status')=='stored_daily_rows_only':notes.append(name.upper()+'本周去重/细分周报告尚未存储，不用日用户相加代替周用户')
  attempt=source['status'].get('latest_attempt_status',source['status'].get('status'))
  if attempt=='failed':notes.append(name.upper()+'最近请求失败，报告只保留已存有效数据；失败不是零数据')
  elif attempt=='empty':notes.append(name.upper()+'最近请求未返回指标行；无行不是接口失败，也未补零')
 for account in selected['adsAccounts']:
  if not account['coverage'].get('query_range_complete'):notes.append('Ads '+account['customerId']+'未存储完整周查询证明；缺日期行不自动等于采集失败')
  attempt=account['status'].get('latest_attempt_status',account['status'].get('status'))
  if attempt in ['failed','empty']:notes.append('Ads '+account['customerId']+('最近请求失败，保留已存数据' if attempt=='failed' else '最近请求未返回行，未视为失败或填0'))
 return {'period':selected,'notes':notes,'sourceReference':{'data_generated_at':model.get('data_generated_at'),'weekly_api_calls':0},'financialRevenueUsed':False,'crossSourceConversionRate':None}

def compose(current,previous,google,p,references,generated=None,allow_fixture=False):
 b=business(current,p,allow_fixture);before=None
 if previous:
  try:before=business(previous,period((dt.date.fromisoformat(p['start'])-dt.timedelta(days=7)).isoformat()),allow_fixture)
  except ValueError:before=None
 return {'schemaVersion':1,'isMock':bool(current.get('isMock')),'period':p,'generatedAt':generated or now().isoformat(),'business':b,'businessComparison':comparison(b,before),'previousBusinessAvailable':before is not None,'marketing':marketing(google,p,allow_fixture),'sourceReferences':references,'gaps':{'coupon_kol':'统一快照未提供优惠券到创作者映射；KOL销量、GMV、新客和Top coupon未生成','kol_social':'粉丝/浏览/点赞/佣金/创作者花名册未接入','cross_source':'不同网站/时区/区间缺同维度归因join，不生成用户转化率或财务ROAS','profit_amount':'Order利润率保留原值；利润金额/成本构成未公开，不推算'}}
def atomic(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
  os.chmod(name,0o644);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
def publish(report,web,at=None):
 if report['isMock']:raise ValueError('MOCK_REPORT_PUBLICATION_FORBIDDEN')
 identity=copy.deepcopy(report);identity.pop('generatedAt',None)
 digest=sha(encoded(identity));identifier=report['period']['id']+'-'+digest[:16];target=web/'reports'/identifier/'report.json'
 for directory in [web,web/'reports',target.parent]:
  if directory.is_symlink():raise ValueError('UNKNOWN_REPORT_DIRECTORY')
  directory.mkdir(mode=0o755,exist_ok=True);directory.chmod(0o755)
 if target.is_symlink():raise ValueError('UNKNOWN_REPORT_FILE')
 if target.exists():
  existing=json.loads(target.read_text(encoding='utf-8'));check=copy.deepcopy(existing);check.pop('generatedAt',None)
  if sha(encoded(check))!=digest:raise ValueError('IMMUTABLE_REPORT_CONFLICT')
  report=existing
 else:atomic(target,encoded(report))
 metrics=report['business']['profiles']['MMOEXP']['metrics']
 try:enabled=subprocess.run(['systemctl','is-enabled','mmoexp-weekly-report.timer'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode==0
 except FileNotFoundError:enabled=False
 manifest={'schemaVersion':1,'status':'ready','reportId':identifier,'path':'reports/'+identifier+'/report.json','sha256':sha(target.read_bytes()),'period':report['period'],'generatedAt':report['generatedAt'],'summary':{key:metrics[key] for key in CORE},'marketingNotes':report['marketing']['notes'],'nextPlannedAt':next_monday(at or now()),'timerEnabled':enabled}
 history=web/'history.json'
 previous=json.loads(history.read_text(encoding='utf-8')) if history.is_file() else {'schemaVersion':1,'reports':[]}
 if previous.get('schemaVersion')!=1:raise ValueError('UNKNOWN_REPORT_HISTORY')
 entries=[entry for entry in previous['reports'] if entry['reportId']!=identifier]+[manifest]
 entries.sort(key=lambda item:(item['period']['start'],item['generatedAt']),reverse=True)
 atomic(history,encoded({'schemaVersion':1,'reports':entries[:104]}));atomic(web/'current.json',encoded(manifest));return manifest
def run(args):
 if args.publish and args.as_of:raise ValueError('PUBLICATION_AS_OF_OVERRIDE_FORBIDDEN')
 at=parse_time(args.as_of) if args.as_of else now();p=period(args.week_start) if args.week_start else preceding_week(at)
 if parse_time(p['endExclusiveAt'])>at:raise ValueError('WEEK_NOT_COMPLETE')
 previous_start=(dt.date.fromisoformat(p['start'])-dt.timedelta(days=7)).isoformat()
 fields={'start':p['start'],'endExclusive':p['endExclusive'],'previousStart':previous_start,'previousEndExclusive':p['start']}
 refs={};current,refs['business']=pointer(Path(str(args.business_manifest).format(**fields)))
 previous=None
 if args.previous_business_manifest:
  try:previous,refs['previousBusiness']=pointer(Path(str(args.previous_business_manifest).format(**fields)))
  except (FileNotFoundError,ValueError):refs['previousBusiness']={'status':'exact_previous_week_not_available'}
 raw=args.google_snapshot.read_bytes();refs['google']={'sha256':sha(raw)};google=json.loads(raw)
 report=compose(current,previous,google,p,refs)
 if args.publish:return publish(report,args.web,at)
 return {'status':'validated','period':p,'readOnly':True,'financeComplete':True,'marketingNotes':report['marketing']['notes'],'report':report}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--business-manifest',type=Path,required=True);parser.add_argument('--previous-business-manifest',type=Path);parser.add_argument('--google-snapshot',type=Path,default=Path('/var/www/mmoexp-marketing/current/data.json'));parser.add_argument('--web',type=Path,default=Path('/var/www/mmoexp-weekly-report'));parser.add_argument('--week-start');parser.add_argument('--as-of');parser.add_argument('--publish',action='store_true');parser.add_argument('--not-before');args=parser.parse_args()
 at=parse_time(args.as_of) if args.as_of else now()
 if args.not_before and at<parse_time(args.not_before):print(json.dumps({'status':'before_first_planned_run','firstPlannedAt':args.not_before}));return
 # Serialise publications only; validation does not need a production lock.
 lock=None
 if args.publish:
  import fcntl
  lock=Path('/opt/mmoexp-weekly-report/report.lock').open('a')
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print(json.dumps({'status':'skipped_existing_generation'}));return
 try:
  result=run(args)
  if args.publish:atomic(args.web/'attempt.json',encoded({'status':'success','checkedAt':now().isoformat(),'period':result['period'],'reportId':result['reportId']}))
  print(json.dumps({key:value for key,value in result.items() if key!='report'},ensure_ascii=True))
 except (ValueError,FileNotFoundError,KeyError) as exc:
  code=str(exc) if isinstance(exc,ValueError) and re.fullmatch('[A-Z_]+',str(exc)) else type(exc).__name__.upper()
  attempt={'status':'waiting_for_exact_business_range','checkedAt':now().isoformat(),'errorCode':code,'firstPlannedAt':'2026-10-05T02:00:00+08:00','timerEnabled':False}
  if args.publish:atomic(args.web/'attempt.json',encoded(attempt))
  print(json.dumps(attempt));raise SystemExit(2)
if __name__=='__main__':main()

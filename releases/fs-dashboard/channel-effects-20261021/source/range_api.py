"""Authenticated, bounded native range reads using existing server sessions only."""
from pathlib import Path
from datetime import datetime,timedelta,date,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import sys,json,hashlib,os,fcntl,subprocess,re,time
sys.path.insert(0,'/opt/fs-transaction-snapshot')
from collector import call as existing_call,profile_record,dimensions,PROFILES
from atomic_snapshot import SHANGHAI,encoded
from fc_category_contract import analysis,TYPES
from fc_product_contract import CONTRACT as PRODUCT_CONTRACT
WEB=Path('/var/www/dashboard/fs-home/transactions');CACHE=Path('/var/lib/fs-business-ranges')
POOL=ThreadPoolExecutor(max_workers=1);LOCK=RLock();JOBS={};STARTS=[]
PROFILE_MAP={r[0]:r for r in PROFILES}

def call(container,script,requests,timeout):
 if script!='primary_reader.py':return existing_call(container,script,requests,timeout)
 # A native range may use weekly/monthly labels. Read exact h2 aggregates, retain
 # undated chart buckets verbatim, and never reinterpret them as daily counts.
 module=(Path('/opt/fs-transaction-snapshot')/'primary_fields.py').read_text()
 program=('import types,sys\nmodule=types.ModuleType("primary_fields")\nexec('+repr(module)+',module.__dict__)\nsys.modules["primary_fields"]=module\n').encode()+(Path(__file__).parent/'range_primary_reader.py').read_bytes()
 r=subprocess.run(['docker','exec','-i',container,'python3','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 if r.returncode:
  lines=r.stderr.decode('utf-8','replace').strip().splitlines()
  raise RuntimeError(lines[-1] if lines and lines[-1].startswith('ValueError: primary_') else 'native_primary_read_failed')
 return json.loads(r.stdout)

from catalog import build as build_catalog

def snapshot():
 # Legacy function name remains for internal consumers; no snapshot file is read.
 return build_catalog(PROFILES,datetime.now(SHANGHAI))

def query(params,d):
 allowed={'profile','start','end','snapshotId','grain','analysis','until'}
 if set(params)-allowed or any(len(v)!=1 for v in params.values()):raise ValueError('invalid_parameters')
 p={k:v[0] for k,v in params.items()}
 if p.get('snapshotId')!=d['catalogId']:raise LookupError('catalog_changed')
 key=p.get('profile');grain=p.get('grain','day')
 if key not in PROFILE_MAP or grain not in ('day','hour'):raise ValueError('invalid_profile_or_grain')
 if 'analysis' in p and (key!='FC27' or p['analysis'] not in ('fc27-categories','fc27-products') or grain!='day'):raise ValueError('invalid_fc_analysis')
 start=p.get('start','');end=p.get('end','')
 if grain=='day':
  if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',v) for v in (start,end)):raise ValueError('invalid_day')
  lo=date.fromisoformat(start);hi=date.fromisoformat(end);begin=datetime.combine(lo,datetime.min.time());stop=datetime.combine(hi+timedelta(days=1),datetime.min.time())
 else:
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:00',start) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:00',end):raise ValueError('invalid_hour')
  begin=datetime.strptime(start,'%Y-%m-%d %H:%M');last=datetime.strptime(end,'%Y-%m-%d %H:%M');stop=last+timedelta(hours=1);lo=begin.date();hi=last.date()
 cutoff=datetime.now(SHANGHAI).replace(second=0,microsecond=0,tzinfo=None)
 if hi>cutoff.date() or stop<=begin or (hi-lo).days>365 or begin>=cutoff:raise ValueError('invalid_period')
 stop=min(stop,cutoff)
 if 'until' in p:
  if p.get('analysis') not in ('fc27-categories','fc27-products') or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',p['until']):raise ValueError('invalid_analysis_boundary')
  until=datetime.strptime(p['until'],'%Y-%m-%d %H:%M')
  if not begin<until<=stop or (hi<cutoff.date() and until!=stop) or (hi==cutoff.date() and until.date()!=hi):raise ValueError('invalid_analysis_boundary')
  stop=until
 result={'profile':key,'start':start,'end':end,'grain':grain,'baseSnapshotId':d['snapshotId'],
         'period':{'start':begin.strftime('%Y-%m-%d %H:%M'),'end':stop.strftime('%Y-%m-%d %H:%M')}}
 if 'analysis' in p:result['analysis']=p['analysis']
 if 'until' in p:result['until']=p['until']
 return result


def capture(q,jobid):
 lock=None
 try:
  # The shared source lock remains; no periodic collector is required.
  lock=(WEB/'collector.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  _,name,gid,game,group=PROFILE_MAP[q['profile']];period=q['period']
  if q.get('analysis')=='fc27-products':
   base=snapshot()
   if base['snapshotId']!=q['baseSnapshotId']:raise RuntimeError('base_snapshot_changed')
   records=existing_call('fc27-p2pah-session','fc_product_reader.py',[{'key':'range',**period}],75)
   extension=records.get('range') or {}
   if extension.get('contractId')!=PRODUCT_CONTRACT or extension.get('status') not in ('available','empty') or extension.get('period')!=period or not extension.get('coverage',{}).get('complete'):raise RuntimeError('native_product_read_failed')
   if snapshot()['snapshotId']!=q['baseSnapshotId']:raise RuntimeError('base_snapshot_changed')
   data={'schemaVersion':1,'status':'available','query':q,'baseSnapshotId':q['baseSnapshotId'],'rangeId':jobid,
    'timezone':'Asia/Shanghai','generatedAt':datetime.now(timezone.utc).isoformat(),
    'fc27ProductRankings':extension,'refreshSeconds':7200,'clientCheckSeconds':60,'consistentPeriod':True}
   publish_cache(jobid,data)
   return
  if q.get('analysis')=='fc27-categories':
   base=snapshot()
   if base['snapshotId']!=q['baseSnapshotId']:raise RuntimeError('base_snapshot_changed')
   requests=[{'key':'all','gid':1322,'tid':'','batchBudgetSeconds':170,**period}]
   requests.extend({'key':key,'gid':1322,'tid':tid,**period} for key,tid,_ in TYPES)
   records=existing_call('fc27-cloud-browser','fc_category_reader.py',requests,200)
   if not all(records.get(k,{}).get('status')=='available' for k in ['all']+[v[0] for v in TYPES]):raise RuntimeError('native_category_read_failed')
   if any(v.get('period')!=period for v in records.values()):raise RuntimeError('source_period_mismatch')
   extension=analysis(records['all'],records,{key:key for key,_,_ in TYPES},period,{})
   if snapshot()['snapshotId']!=q['baseSnapshotId']:raise RuntimeError('base_snapshot_changed')
   data={'schemaVersion':1,'status':'available','query':q,'baseSnapshotId':q['baseSnapshotId'],'rangeId':jobid,
    'timezone':'Asia/Shanghai','currency':'USD','generatedAt':datetime.now(timezone.utc).isoformat(),
    'fc27Analytics':extension,'refreshSeconds':7200,'clientCheckSeconds':60,'consistentPeriod':True}
   publish_cache(jobid,data)
   return
  order={'key':'range','gid':gid,'status':'3' if group=='rpg' else '',**period}
  admin={'key':'range','game':game,'status':'101' if group=='rpg' else '',**period}
  with ThreadPoolExecutor(max_workers=2) as pool:
   pf=pool.submit(call,'fc27-cloud-browser','primary_reader.py',[order],210)
   af=pool.submit(call,'fc27-p2pah-session','supplement_reader.py',[admin],90)
   primary=pf.result()['range'];supplement=af.result()['range']
  if primary['period']!=period or supplement['period']!=period:raise RuntimeError('source_period_mismatch')
  profile=profile_record(q['profile'],name,primary,supplement);profile['dimensions']=dimensions(primary)
  # Non-additive quantities are native whole-range aggregates, never daily sums.
  data={'schemaVersion':1,'status':'available','query':q,'baseSnapshotId':q['baseSnapshotId'],'rangeId':jobid,
        'scopeContractId':'all-websites-order-primary-admin-supplement-v1','timezone':'Asia/Shanghai','currency':'USD',
        'generatedAt':datetime.now(timezone.utc).isoformat(),'profile':profile,'refreshSeconds':7200,'clientCheckSeconds':60,
        'supplementStatus':supplement['status'],'consistentPeriod':True,
        'captureContract':'native exact range; baseSnapshotId is a compatibility name for the catalog version; source capturedAt records read time; no daily unique/rate aggregation'}
  publish_cache(jobid,data)
 except Exception as exc:
  safe={'scheduled_collection_due','timer_schedule_unavailable','source_period_mismatch','base_snapshot_changed','native_category_read_failed','native_product_read_failed'}
  code=str(exc) if str(exc) in safe else 'collector_busy' if isinstance(exc,BlockingIOError) else 'native_range_read_failed'
  with LOCK:JOBS[jobid]={'status':'unavailable','error':code,'retryAfter':30,'failedAt':time.monotonic()}
 finally:
  if lock:lock.close()

def publish_cache(jobid,data):
 body=encoded(data);data['resultSha256']=hashlib.sha256(body).hexdigest()
 target=CACHE/(jobid+'.json');tmp=target.with_suffix('.tmp');tmp.write_bytes(encoded(data));os.chmod(tmp,0o600);os.replace(tmp,target)
 files=sorted(CACHE.glob('*.json'),key=lambda p:p.stat().st_mtime)
 for old in files[:-2048]:
  if re.fullmatch(r'[a-f0-9]{64}\.json',old.name) and not old.is_symlink():old.unlink()
 with LOCK:
  JOBS[jobid]={'status':'available'}
  if len(JOBS)>256:
   for key in list(JOBS):
    if len(JOBS)<=128:break
    if JOBS[key]['status']!='pending':JOBS.pop(key,None)

from live_summary import query as summary_query
from summary_bridge import build as build_summary
SUMMARY=build_summary(PROFILE_MAP,call,dimensions,WEB)
from profit_queries import ProfitQueries
PROFIT=ProfitQueries(PROFILE_MAP,call,SUMMARY.pools['Order'],WEB,CACHE/'profit-days')
from fc_detail import FCDetails
FC_POOL=ThreadPoolExecutor(max_workers=1)
FC_DETAIL=FCDetails(FC_POOL,CACHE/'fc-detail')
from fc_daily import DailyReports
FC_DAILY=DailyReports(FC_DETAIL,CACHE/'fc-daily')

def get_range(params):
 if params.get('mode') in (['fc-detail'],['fc-report']):return FC_DETAIL.get(params)
 if params.get('mode')==['catalog']:
  if set(params)!={'mode'}:raise ValueError('invalid_catalog_parameters')
  return 200,snapshot()
 if params.get('mode')==['summary']:return SUMMARY.get(summary_query(params,PROFILE_MAP))
 if params.get('mode')==['profit-history']:
  q=summary_query({**params,'mode':['summary']},PROFILE_MAP)
  if q['grain']!='day':raise ValueError('complete_daily_history_required')
  return PROFIT.get(q,snapshot()['catalogId'],datetime.now(SHANGHAI).date())
 d=snapshot();q=query(params,d);jobid=hashlib.sha256(encoded(q)).hexdigest();file=CACHE/(jobid+'.json')
 if file.is_file():
  cached=json.loads(file.read_text())
  age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached['generatedAt'])).total_seconds()
  if 0<=age<cached.get('refreshSeconds',7200):return 200,cached
 with LOCK:
  job=JOBS.get(jobid)
  if job and job['status']=='available':job=None
  if job and job['status']=='unavailable' and time.monotonic()-job['failedAt']>=60:job=None
  if job:return (202 if job['status']=='pending' else 503),{'schemaVersion':1,'rangeId':jobid,'baseSnapshotId':d['snapshotId'],**{k:v for k,v in job.items() if k!='failedAt'}}
  active=sum(1 for v in JOBS.values() if v['status']=='pending')
  now=time.monotonic();STARTS[:]=[v for v in STARTS if now-v<60]
  if active>=4 or len(STARTS)>=6:return 429,{'status':'busy','retryAfter':10}
  STARTS.append(now);JOBS[jobid]={'status':'pending'};POOL.submit(capture,q,jobid)
  return 202,{'schemaVersion':1,'status':'pending','rangeId':jobid,'baseSnapshotId':d['snapshotId'],'retryAfter':2}

from ai_advisor import Advisor
from fc_deep_service import DeepService
from fc_order_diagnostics import read_live as read_order_problem_clues
DEEP=DeepService(FC_DETAIL,FC_DAILY,CACHE/'advisor-memory',diagnostics=lambda:read_order_problem_clues(CACHE/'fc-order-clues',WEB))
FC_DAILY.deep=DEEP
# Optional Hermes controller is hosted in this existing FS key/ledger process.
HERMES=None
if os.environ.get('FS_HERMES_FC_ENABLED')=='1':
 sys.path.insert(0,'/opt/fs-hermes-fc')
 from controller import HermesService
 from fc_daily import admin as hermes_authorizer
 HERMES=HermesService(FC_DETAIL,FC_DAILY,get_range,lambda:read_order_problem_clues(CACHE/'fc-order-clues',WEB),
  '/var/lib/fs-hermes-fc/fs','/run/fs-hermes-fc','/opt/fs-hermes-fc',hermes_authorizer)
from conversation_service import ConversationService
from conversation_http import handle as conversation_handle, respond as conversation_respond, PREFIX as CONVERSATION_PREFIX
CONVERSATION=ConversationService(HERMES,'/var/lib/fs-hermes-fc/fs/conversations','/run/fs-hermes-fc') if HERMES is not None else None
CUSTOMER_TRACKING=None
if HERMES is not None:
 from tracking_controller import TrackingController
 CUSTOMER_TRACKING=TrackingController('/var/lib/fs-hermes-fc/fs/customer-tracking',hermes_authorizer,conversation=CONVERSATION)
 CONVERSATION.customer_tracking=CUSTOMER_TRACKING
CHANNELS=None
if HERMES is not None:
 from channel_effects import ChannelService
 CHANNELS=ChannelService('/var/lib/fs-channel-effects',hermes_authorizer)
ADVISOR=Advisor(snapshot,get_range,FC_DAILY,CACHE/'advisor',deep=DEEP)

class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  uri=urlsplit(self.path)
  if uri.path=='/health':self.reply(200,{'ok':True,'service':'fs-business-range','readonly':True,'active_customer_reports':CUSTOMER_TRACKING.active_reports() if CUSTOMER_TRACKING is not None else 0});return
  if uri.path==CONVERSATION_PREFIX or uri.path.startswith(CONVERSATION_PREFIX+'/'):
   if CONVERSATION is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})
   else:conversation_handle(self,'GET',uri,self.headers.get('X-Auth-User'),CONVERSATION,hermes_authorizer)
   return
  # Only the existing nginx auth_request identity is trusted; public headers are replaced.
  if not self.headers.get('X-Auth-User'):self.reply(401,{'error':'login_required'});return
  if uri.path=='/channels':
   if CHANNELS is None:self.reply(503,{'error':'channels_not_enabled'});return
   try:status,data=CHANNELS.get(parse_qs(uri.query,keep_blank_values=True,max_num_fields=16),self.headers.get('X-Auth-User'));self.reply(status,data)
   except (ValueError,LookupError):self.reply(422,{'error':'invalid_channel_request'})
   except Exception:self.reply(503,{'error':'channels_unavailable'})
   return
  if uri.path=='/advisor' and parse_qs(uri.query).get('structure')==['customer_tracking']:
   if CUSTOMER_TRACKING is None:self.reply(503,{'error':'tracking_not_enabled'});return
   try:status,data=CUSTOMER_TRACKING.get(self.headers.get('X-Auth-User'),parse_qs(uri.query,keep_blank_values=True,max_num_fields=8));self.reply(status,data)
   except PermissionError:self.reply(403,{'error':'admin_required'})
   except (ValueError,LookupError):self.reply(422,{'error':'invalid_tracking_request'})
   except Exception:self.reply(503,{'error':'tracking_unavailable'})
   return
  if uri.path=='/advisor' and parse_qs(uri.query).get('mode')==['hermes']:
   if HERMES is None:self.reply(503,{'error':'hermes_not_enabled'});return
   try:status,data=HERMES.get(parse_qs(uri.query,keep_blank_values=True,max_num_fields=8),self.headers.get('X-Auth-User'));self.reply(status,data)
   except ValueError:self.reply(422,{'error':'invalid_parameters'})
   except Exception:self.reply(503,{'error':'hermes_unavailable'})
   return
  if uri.path=='/advisor':
   try:status,data=ADVISOR.get(parse_qs(uri.query,keep_blank_values=True,max_num_fields=8),self.headers.get('X-Auth-User'));self.reply(status,data)
   except Exception:self.reply(503,{'error':'advisor_unavailable'})
   return
  if uri.path!='/range':self.reply(404,{'error':'not_found'});return
  params=parse_qs(uri.query,keep_blank_values=True)
  if params.get('mode')==['fc-daily']:
   try:status,data=FC_DAILY.get(params,self.headers.get('X-Auth-User'),self.headers);self.reply(status,data)
   except Exception:self.reply(503,{'error':'daily_report_unavailable'})
   return
  try:status,data=get_range(parse_qs(uri.query,keep_blank_values=True));self.reply(status,data)
  except LookupError:self.reply(409,{'error':'catalog_changed'})
  except (ValueError,KeyError,AssertionError):self.reply(422,{'error':'invalid_or_uncovered_range'})
  except Exception:self.reply(503,{'error':'query_unavailable'})
 def do_POST(self):
  uri=urlsplit(self.path)
  if uri.path==CONVERSATION_PREFIX or uri.path.startswith(CONVERSATION_PREFIX+'/'):
   if CONVERSATION is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})
   else:conversation_handle(self,'POST',uri,self.headers.get('X-Auth-User'),CONVERSATION,hermes_authorizer)
   return
  if uri.path not in ('/advisor','/boss-insight') or uri.query:self.reply(405,{'error':'read_only'});return
  user=self.headers.get('X-Auth-User')
  if not user:self.reply(401,{'error':'login_required'});return
  if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':self.reply(415,{'error':'json_required'});return
  length=self.headers.get('Content-Length','')
  if not re.fullmatch(r'[0-9]{1,5}',length) or not 1<=int(length)<=16384:self.reply(413,{'error':'body_too_large'});return
  try:
   self.connection.settimeout(15)
   body=json.loads(self.rfile.read(int(length)))
   if uri.path=='/advisor' and isinstance(body,dict) and body.get('kind')=='hermes_customer_tracking':
    if CUSTOMER_TRACKING is None:self.reply(503,{'error':'tracking_not_enabled'});return
    if self.headers.get('X-FS-Advisor-Action')!='submit' or self.headers.get('Sec-Fetch-Site')!='same-origin':self.reply(403,{'error':'same_origin_required'});return
    try:status,data=CUSTOMER_TRACKING.post(user,body);self.reply(status,data)
    except PermissionError:self.reply(403,{'error':'admin_required'})
    except (ValueError,LookupError):self.reply(422,{'error':'invalid_tracking_request'})
    except Exception:self.reply(503,{'error':'tracking_unavailable'})
    return
   if uri.path=='/advisor' and isinstance(body,dict) and str(body.get('kind','')).startswith('hermes_'):
    if HERMES is None:self.reply(503,{'error':'hermes_not_enabled'});return
    status,data=HERMES.post(body,user,self.headers)
   else:status,data=(ADVISOR.post if uri.path=='/advisor' else ADVISOR.post_boss)(body,user,self.headers)
   self.reply(status,data)
  except (ValueError,TypeError,UnicodeError):self.reply(422,{'error':'invalid_request'})
  except Exception:self.reply(503,{'error':'advisor_unavailable'})
 def do_PUT(self):self.reply(405,{'error':'read_only'})
 do_PATCH=do_PUT;do_DELETE=do_PUT
 def reply(self,status,payload):
  body=encoded(payload);self.send_response(status)
  for k,v in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),('Content-Length',str(len(body))),('X-Content-Type-Options','nosniff')]:self.send_header(k,v)
  self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass

if __name__=='__main__':
 CACHE.mkdir(parents=True,exist_ok=True);os.chmod(CACHE,0o700)
 FC_DAILY.start()
 ADVISOR.start()
 if HERMES is not None:HERMES.start()
 ThreadingHTTPServer(('127.0.0.1',8931),Handler).serve_forever()

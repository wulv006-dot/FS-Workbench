"""Authenticated, bounded native range reads using existing server sessions only."""
# 2026-10-28: 预加载 lxml，避免常驻服务多线程首次 import 时 etree 初始化竞争
try:
    import lxml.etree  # noqa: F401
    import lxml.html   # noqa: F401
    _lxml_preloaded = True
except Exception:
    _lxml_preloaded = False


from pathlib import Path
from datetime import datetime,timedelta,date,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import sys,json,hashlib,os,fcntl,subprocess,re,time
sys.path.insert(0,'/opt/fs-transaction-snapshot')
# Bind the range archive before Hermes adds its compatibility module directory.
import daily_archive
from collector import call as existing_call,profile_record,dimensions,PROFILES
from atomic_snapshot import SHANGHAI,encoded
from fc_category_contract import analysis,TYPES
from fc_product_contract import CONTRACT as PRODUCT_CONTRACT
WEB=Path('/var/www/dashboard/fs-home/transactions');CACHE=Path('/var/lib/fs-business-ranges')
POOL=ThreadPoolExecutor(max_workers=1);LOCK=RLock();JOBS={};STARTS=[]
from management_profiles import PROFILES as MANAGEMENT_PROFILES
PROFILES = [*PROFILES, *MANAGEMENT_PROFILES]
PROFILE_MAP={r[0]:r for r in PROFILES}


def maintenance_admission():
 from cache_retention import maintenance_reader
 return maintenance_reader()

def call(container,script,requests,timeout):
 if script=='order_shipping':
  from business_shipping import collect
  values={};deadline=time.monotonic()+timeout
  for r in requests:
   remaining=deadline-time.monotonic()
   if remaining<=0:raise TimeoutError('shipping_batch_deadline')
   values[r['key']]=collect({**r,'period':{'start':r['start'],'end':r['end']}},timeout=min(85,remaining))
  return values
 if script=='rs_shipping':
  from rs_shipping import collect
  return {r['key']:collect({**r,'period':{'start':r['start'],'end':r['end']}}) for r in requests}
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
 if 'analysis' not in p and PROFILE_MAP[key][4]=='rpg':result['adminCohort']='paid-all-status-v2'
 if 'analysis' in p:result['analysis']=p['analysis']
 if 'until' in p:result['until']=p['until']
 return result


def capture(q,jobid):
 try:
  with maintenance_admission():return _capture(q,jobid)
 except Exception as error:
  code='maintenance_in_progress' if isinstance(error,BlockingIOError) else 'native_range_read_failed'
  with LOCK:JOBS[jobid]={'status':'unavailable','error':code,'retryAfter':3,'failedAt':time.monotonic()}


def _capture(q,jobid):
 try:
  _,name,gid,game,group=PROFILE_MAP[q['profile']];period=q['period']
  if q.get('analysis')=='fc27-products':
   base=snapshot()
   if base['snapshotId']!=q['baseSnapshotId']:raise RuntimeError('base_snapshot_changed')
   records=existing_call(None,'fc_product_reader.py',[{'key':'range',**period}],75)
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
   with (WEB/'collector.lock').open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    records=existing_call('fs-order-browser','fc_category_reader.py',requests,200)
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
  admin={'key':'range','game':game,'status':'',**period}
  def primary_read():
   with (WEB/'collector.lock').open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    return call('fc27-cloud-browser','primary_reader.py',[order],210)
  with ThreadPoolExecutor(max_workers=2) as pool:
   pf=pool.submit(primary_read)
   af=pool.submit(call,None,'supplement_reader.py',[admin],90)
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

def publish_cache(jobid,data):
 from daily_archive import save,native_key,complete_native
 if complete_native(data):
  save('native',native_key(data['query'],PROFILE_MAP[data['query']['profile']]),data)
 body=encoded(data);data['resultSha256']=hashlib.sha256(body).hexdigest()
 with LOCK:
  target=CACHE/(jobid+'.json');tmp=target.with_suffix('.tmp');tmp.write_bytes(encoded(data));os.chmod(tmp,0o600);os.replace(tmp,target)
  files=sorted(CACHE.glob('*.json'),key=lambda p:p.stat().st_mtime)
  for old in files[:-2048]:
   if re.fullmatch(r'[a-f0-9]{64}\.json',old.name) and not old.is_symlink():old.unlink()
  JOBS[jobid]={'status':'available'}
  if len(JOBS)>256:
   for key in list(JOBS):
    if len(JOBS)<=128:break
    if JOBS[key]['status']!='pending':JOBS.pop(key,None)

from live_summary import query as summary_query
from summary_bridge import build as build_summary
SUMMARY=build_summary(PROFILE_MAP,call,dimensions,WEB)
SUMMARY.admission=maintenance_admission
from profit_queries import ProfitQueries
RS_PROFITS={}
SHIPPING_PROFITS={}
PROFIT=ProfitQueries(PROFILE_MAP,call,SUMMARY.pools['Order'],WEB,CACHE/'profit-days')
from fc_detail import FCDetails
FC_POOL=ThreadPoolExecutor(max_workers=1)
FC_DETAIL=FCDetails(FC_POOL,CACHE/'fc-detail')
from rs_backlog import RSBacklog
RS_BACKLOG=RSBacklog(SUMMARY.pools['Admin'])
from fc_daily import DailyReports
FC_DAILY=DailyReports(FC_DETAIL,CACHE/'fc-daily')

def get_range(params):
 if params.get('mode')==['archive-catalog']:
  if set(params)!={'mode'}:raise ValueError('invalid_archive_catalog_parameters')
  from daily_archive import Archive
  return 200,{'status':'available','datasets':Archive().catalog(),'coverage':'bounds may contain gaps; validate exact requested coverage'}
 from daily_archive import read,save,native_key,complete_native,rebind_native
 if 'mode' in params:return get_range_live(params)
 force=params.get('refresh')==['true']
 if 'refresh' in params and not force:raise ValueError('invalid_archive_refresh')
 params={k:v for k,v in params.items() if k!='refresh'}
 q=query(params,snapshot());selector=native_key(q,PROFILE_MAP[q['profile']])
 archived=None if force else read('native',selector)
 if archived is not None:
  return 200,rebind_native(archived,q)
 code,value=get_range_live(params,force=force)
 if code==200 and complete_native(value):
  try:
   with maintenance_admission():save('native',selector,value)
  except BlockingIOError:value['archive']={**(value.get('archive') or {}),'refreshDeferred':True,'reason':'maintenance_in_progress'}
 return code,value

def get_range_live(params,force=False):
 if params.get('mode')==['rs-backlog']:return RS_BACKLOG.get(params)
 if params.get('mode') in (['fc-detail'],['fc-report']):return FC_DETAIL.get(params)
 if params.get('mode')==['catalog']:
  if set(params)!={'mode'}:raise ValueError('invalid_catalog_parameters')
  return 200,snapshot()
 if params.get('mode')==['summary']:return SUMMARY.get(summary_query(params,PROFILE_MAP))
 if params.get('mode')==['profit-history']:
  q=summary_query({**params,'mode':['summary']},PROFILE_MAP)
  if q['grain']!='day':raise ValueError('complete_daily_history_required')
  profit=PROFIT
  if q['profile']=='RS':
   from rs_shipping import filters
   key=(q['rs_site'],q['rs_server'],q['rs_category'])
   with LOCK:
    if key not in RS_PROFITS:
     worker=ProfitQueries(PROFILE_MAP,call,SUMMARY.pools['Order'],WEB,CACHE/'profit-days')
     worker.rs_filters={k:q[k] for k in ('rs_site','rs_server','rs_category')}
     f=filters(q)
     worker.expected['RS']=dict(sites=f['source[]'] or 'all-websites',gid='506',tid=f['cid'],status=f['status'],aid=f['aid'],delivery=True)
     RS_PROFITS[key]=worker
    profit=RS_PROFITS[key]
  else:
   from business_shipping import filters
   key=(q['profile'],q['profit_site'],q['profit_category'])
   with LOCK:
    if key not in SHIPPING_PROFITS:
     worker=ProfitQueries(PROFILE_MAP,call,SUMMARY.pools['Order'],WEB,CACHE/'profit-days')
     worker.rs_filters={k:q[k] for k in ('profile','profit_site','profit_category')}
     f=filters(q)
     worker.expected[q['profile']]=dict(sites=f['source[]'] or 'all-websites',gid=f['gid'],tid=f['cid'],status=f['status'],aid=f['aid'],delivery='shipping')
     SHIPPING_PROFITS[key]=worker
    profit=SHIPPING_PROFITS[key]
  return profit.get(q,snapshot()['catalogId'],datetime.now(SHANGHAI).date())
 d=snapshot();q=query(params,d);jobid=hashlib.sha256(encoded(q)).hexdigest();file=CACHE/(jobid+'.json')
 if file.is_file():
  cached=json.loads(file.read_text())
  age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached['generatedAt'])).total_seconds()
  if not force and 0<=age<cached.get('refreshSeconds',7200):return 200,cached
 with LOCK:
  job=JOBS.get(jobid)
  if job and job['status']=='available':job=None
  if job and job['status']=='unavailable' and time.monotonic()-job['failedAt']>=60:job=None
  if job:return (202 if job['status']=='pending' else 503),{'schemaVersion':1,'rangeId':jobid,'baseSnapshotId':d['snapshotId'],**({'retryAfter':2} if job['status']=='pending' else {}),**{k:v for k,v in job.items() if k!='failedAt'}}
  active=sum(1 for v in JOBS.values() if v['status']=='pending')
  now=time.monotonic();STARTS[:]=[v for v in STARTS if now-v<60]
  if active>=4 or len(STARTS)>=6:return 429,{'status':'busy','retryAfter':10}
  try:
   with maintenance_admission():
    STARTS.append(now);JOBS[jobid]={'status':'pending'}
    pool=SUMMARY.pools['Admin'] if q.get('analysis')=='fc27-products' else POOL
    pool.submit(capture,q,jobid)
  except BlockingIOError:return 503,{'status':'busy','error':'maintenance_in_progress','rangeId':jobid,'retryAfter':3}
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

def conversation_runtime_diagnostics(service,user,cid,http_handle,store_path,tasks_path):
 """Observe this process's bound objects; never initialize a material ledger."""
 import hashlib,marshal,sqlite3,stat,types
 from contextlib import closing
 from pathlib import Path
 def existing(value):
  path=Path(value)
  if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):
   raise OSError('diagnostic_path_unavailable')
  if not stat.S_ISREG(path.stat().st_mode):raise OSError('diagnostic_path_unavailable')
  return path.resolve(strict=True)
 store=existing(service.store.path)
 with closing(sqlite3.connect(store.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
  db.execute('PRAGMA query_only=ON')
  if not db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?',(cid,user)).fetchone():
   raise LookupError('conversation_not_found')
 tasks=existing(service.hermes.tasks.path)
 with closing(sqlite3.connect(tasks.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
  db.execute('PRAGMA query_only=ON');db.execute('SELECT 1 FROM tasks LIMIT 0')
 if not isinstance(http_handle,types.FunctionType):raise ValueError('diagnostic_handler_unavailable')
 module=existing(http_handle.__globals__['__file__'])
 materials=getattr(service,'materials',None)
 return {'version':'materials_runtime_diagnostics_v1',
  'http':{'module_path':str(module),'handle_code_filename':http_handle.__code__.co_filename,
   'loaded_code_sha256':hashlib.sha256(marshal.dumps(http_handle.__code__)).hexdigest(),
   'code_fingerprint_format':'python_marshal_code_v1',
   'disk_file_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),
   'materials_branch_present':'materials' in http_handle.__code__.co_consts,
   'adapter_version':('materials_runtime_diagnostics_v1' if
       http_handle.__globals__.get('MATERIAL_ADAPTER_VERSION')=='materials_runtime_diagnostics_v1' else None)},
  'materials_bound':materials is not None,
  'materials_store_matches':getattr(getattr(materials,'conversation',None),'store',None) is service.store,
  'materials_tasks_matches':getattr(materials,'hermes',None) is service.hermes,
  'store_path_matches_expected':store==Path(store_path).resolve(strict=True),
  'tasks_path_matches_expected':tasks==Path(tasks_path).resolve(strict=True)==existing(service.hermes.root/'tasks.sqlite3')}

def bind_conversation_diagnostics(service,http_handle,*,
 store_path='/var/lib/fs-hermes-fc/fs/conversations/conversations.db',
 tasks_path='/var/lib/fs-hermes-fc/fs/tasks.sqlite3'):
 if service is not None:
  service.runtime_diagnostics=lambda user,cid:conversation_runtime_diagnostics(service,user,cid,http_handle,store_path,tasks_path)

def conversation_get(handler,uri,user):
 # Own only this diagnostic route so a cached old same-name HTTP module is
 # observable without replacing it or changing any ordinary routing decision.
 parts=uri.path[len(CONVERSATION_PREFIX):].strip('/').split('/')
 if len(parts)!=2 or parts[1]!='runtime-diagnostics':
  return conversation_handle(handler,'GET',uri,user,CONVERSATION,hermes_authorizer)
 if not user:conversation_respond(handler,401,{'error':'login_required'});return
 if hermes_authorizer(user) is not True:conversation_respond(handler,403,{'error':'admin_required'});return
 headers=[('X-FS-Material-Adapter','materials_runtime_diagnostics_v1')]
 if uri.query or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',parts[0]):
  conversation_respond(handler,404,{'error':'not_found'},headers=headers);return
 try:
  result=CONVERSATION.runtime_diagnostics(user,parts[0])
 except LookupError:conversation_respond(handler,404,{'error':'not_found'},headers=headers)
 except Exception:conversation_respond(handler,503,{'error':'runtime_diagnostics_unavailable'},headers=headers)
 else:conversation_respond(handler,200,result,headers=headers)

if HERMES is not None:
 from conversation_native import NATIVE_ROOT
 HERMES.native_root=Path(NATIVE_ROOT)
 HERMES.native_ownership=(9876,9876)
CONVERSATION=ConversationService(HERMES,'/var/lib/fs-hermes-fc/fs/conversations','/run/fs-hermes-fc') if HERMES is not None else None
CAMPAIGN_RECOMMENDATIONS=None
CAMPAIGN_RECOMMENDATIONS_ERROR=None
if HERMES is not None:
 try:
  from campaign_recommendations import CampaignRecommendations,handle as campaign_recommendations_handle
  CAMPAIGN_RECOMMENDATIONS=CampaignRecommendations(HERMES)
 except Exception:
  CAMPAIGN_RECOMMENDATIONS_ERROR='campaign_initialization_failed'
CAMPAIGN_WEEKLY=None
if CAMPAIGN_RECOMMENDATIONS is not None:
 try:
  from campaign_weekly import CampaignWeekly,handle as campaign_weekly_handle
  CAMPAIGN_WEEKLY=CampaignWeekly(HERMES,CAMPAIGN_RECOMMENDATIONS)
 except Exception:
  CAMPAIGN_RECOMMENDATIONS_ERROR='campaign_weekly_initialization_failed'
from conversation_desktop import DesktopRPC
DESKTOP_RPC=DesktopRPC(CONVERSATION,hermes_authorizer,'/etc/fs-hermes-desktop/fs-principal.json') if CONVERSATION is not None else None
bind_conversation_diagnostics(CONVERSATION,conversation_handle)
if CONVERSATION is not None:
 from conversation_material_runs import MaterialService
 CONVERSATION.materials=MaterialService(HERMES,CONVERSATION)
 CONVERSATION.pool.submit(CONVERSATION.materials.recover)
CUSTOMER_TRACKING=None
if HERMES is not None:
 from tracking_controller import TrackingController
 CUSTOMER_TRACKING=TrackingController('/var/lib/fs-hermes-fc/fs/customer-tracking',hermes_authorizer,conversation=CONVERSATION)
 CONVERSATION.customer_tracking=CUSTOMER_TRACKING
CHANNELS=None
ACTUAL_PROFITS=None
if HERMES is not None:
 from channel_effects import ChannelService
 CHANNELS=ChannelService('/var/lib/fs-channel-effects',hermes_authorizer)
 CHANNELS.admission=maintenance_admission
 from actual_profit import ActualProfitService
 ACTUAL_PROFITS=ActualProfitService(CHANNELS,PROFILE_MAP)
 HERMES.conversation=CONVERSATION
 HERMES.actual_profits=ACTUAL_PROFITS
ADVISOR=Advisor(snapshot,get_range,FC_DAILY,CACHE/'advisor',deep=DEEP)
USERS=None;USERS_ERROR=None
try:
 sys.path.insert(0,'/opt/fs-hermes-fc')
 from user_runtime import build as build_user_analytics
 from user_http import get as get_user_analytics
 USERS=build_user_analytics()
except (ImportError,OSError,ValueError) as error:
 USERS_ERROR=str(error) if isinstance(error,ValueError) and re.fullmatch(r'[a-z_]{1,80}',str(error)) else type(error).__name__

# Dedicated live reads remain disabled if the existing pool or verifier is unavailable.
LIVE_ADMIN=None
verify_live_session=None
private_live_body=None
try:
 from admin_live_admission import LiveAdminAdmission
 from admin_live_host import get as get_live_orders
 from admin_live_session import verify as verify_live_session
 from admin_live_dispatch import private_body_params as private_live_body
 LIVE_ADMIN=LiveAdminAdmission(SUMMARY.pools['Admin'],maintenance_admission)
except (ImportError,OSError,ValueError,AttributeError):pass

def campaign_unavailable(handler,method,uri):
 try:
  if method=='POST':
   from conversation_http import read_json
   operation_id=read_json(handler,maximum=300000).get('operation_id')
  else:
   query=parse_qs(uri.query,keep_blank_values=True,max_num_fields=1)
   operation_id=query.get('operation_id',[None])[0]
  if not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}',operation_id or ''):raise ValueError('operation_id')
 except (ValueError,TypeError,KeyError):handler.reply(422,{'error':'campaign_invalid_request'});return
 handler.reply(200,{'status':'unavailable','operation_id':operation_id,'error':'WEEKLY_HERMES_PROVIDER_UNAVAILABLE','reason':CAMPAIGN_RECOMMENDATIONS_ERROR,'provider_outcome':'not_dispatched'})

class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  uri=urlsplit(self.path)
  if uri.path=='/internal/hermes/campaign-weekly':
   if CAMPAIGN_WEEKLY is None:self.reply(503,{'error':'campaign_weekly_unavailable'})
   else:campaign_weekly_handle(self,'GET',uri,CAMPAIGN_WEEKLY)
   return
  if uri.path=='/internal/hermes/campaign-recommendations':
   if CAMPAIGN_RECOMMENDATIONS is None:campaign_unavailable(self,'GET',uri)
   else:campaign_recommendations_handle(self,'GET',uri,CAMPAIGN_RECOMMENDATIONS)
   return
  if uri.path=='/health':self.reply(200,{'ok':True,'service':'fs-business-range','readonly':True,'active_customer_reports':CUSTOMER_TRACKING.active_reports() if CUSTOMER_TRACKING is not None else 0,'user_analytics_ready':USERS is not None,'user_analytics_error':USERS_ERROR});return
  if uri.path==CONVERSATION_PREFIX or uri.path.startswith(CONVERSATION_PREFIX+'/'):
   if CONVERSATION is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})
   else:conversation_get(self,uri,self.headers.get('X-Auth-User'))
   return
  if uri.path=='/users/live-orders':
   if LIVE_ADMIN is None or not callable(verify_live_session):self.reply(503,{'error':'live_admission_unavailable'});return
   try:
    live_query=parse_qs(uri.query,keep_blank_values=True,max_num_fields=16)
    required={'site_id','game_id','start','end_exclusive'}
    if not required<=set(live_query) or set(live_query)-required-{'cursor'} or any(len(v)!=1 for v in live_query.values()):raise ValueError('invalid_live_query')
    first=date.fromisoformat(live_query['start'][0]);last=date.fromisoformat(live_query['end_exclusive'][0])
    if first.isoformat()!=live_query['start'][0] or last.isoformat()!=live_query['end_exclusive'][0] or not 1<=(last-first).days<=28:raise ValueError('invalid_live_query')
   except (ValueError,KeyError):self.reply(422,{'error':'invalid_live_query'});return
   cookie=self.headers.get('Cookie')
   try:
    auth_status,actor=verify_live_session(cookie)
    if auth_status!=200 or not actor:self.reply(auth_status if auth_status in (401,403,429,503) else 503,{'error':'session_unavailable' if auth_status==503 else 'session_denied'});return
    def run_scoped(operation,timeout):
     def checked():
      next_status,next_actor=verify_live_session(cookie)
      if next_status!=200 or next_actor!=actor:raise PermissionError('session_changed')
      return operation()
     return LIVE_ADMIN.run(checked,timeout)
    status,data=get_live_orders(live_query,actor,run_source=run_scoped)
    self.reply(status,data)
   except Exception:self.reply(503,{'error':'live_source_unavailable'})
   return
  # Only the existing nginx auth_request identity is trusted; public headers are replaced.
  if not self.headers.get('X-Auth-User'):self.reply(401,{'error':'login_required'});return
  if uri.path in ('/users','/users/private'):
   if USERS is None:self.reply(503,{'error':'user_analytics_not_ready','reason':USERS_ERROR});return
   try:status,data=get_user_analytics(USERS,uri.path,parse_qs(uri.query,keep_blank_values=True,max_num_fields=16),self.headers.get('X-Auth-User'));self.reply(status,data)
   except Exception:self.reply(503,{'error':'users_unavailable'})
   return
  if uri.path=='/channels':
   if CHANNELS is None:self.reply(503,{'error':'channels_not_enabled'});return
   try:
    params=parse_qs(uri.query,keep_blank_values=True,max_num_fields=16)
    service=ACTUAL_PROFITS if params.get('mode')==['actual-profit'] else CHANNELS
    status,data=service.get(params,self.headers.get('X-Auth-User'));self.reply(status,data)
   except (ValueError,LookupError):self.reply(422,{'error':'invalid_channel_request'})
   except Exception as exc:
    try:
     import sys as _s2;_s2.stderr.write('[channels] %s: %s\n'%(type(exc).__name__,str(exc)[:200]))
    except Exception:pass
    self.reply(503,{'error':'channels_unavailable'})
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
  if uri.path=='/internal/hermes/campaign-weekly':
   if CAMPAIGN_WEEKLY is None:self.reply(503,{'error':'campaign_weekly_unavailable'})
   else:campaign_weekly_handle(self,'POST',uri,CAMPAIGN_WEEKLY)
   return
  if uri.path=='/internal/hermes/campaign-recommendations':
   if CAMPAIGN_RECOMMENDATIONS is None:campaign_unavailable(self,'POST',uri)
   else:campaign_recommendations_handle(self,'POST',uri,CAMPAIGN_RECOMMENDATIONS)
   return
  if uri.path=='/users/order-email-export':
   if LIVE_ADMIN is None or not callable(verify_live_session):self.reply(503,{'error':'live_admission_unavailable','complete':False});return
   if uri.query or self.headers.get('Sec-Fetch-Site')!='same-origin':self.reply(403,{'error':'same_origin_required','complete':False});return
   if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':self.reply(415,{'error':'json_required','complete':False});return
   length=self.headers.get('Content-Length','')
   if not re.fullmatch(r'[0-9]{1,4}',length) or not 1<=int(length)<=4096:self.reply(413,{'error':'body_too_large','complete':False});return
   cookie=self.headers.get('Cookie')
   try:
    from admin_order_email_export import parse_body,get as export_emails
    auth_status,actor=verify_live_session(cookie)
    if auth_status!=200 or not actor:self.reply(auth_status if auth_status in (401,403,429,503) else 503,{'error':'session_denied','complete':False});return
    self.connection.settimeout(10)
    raw=self.rfile.read(int(length))
    if len(raw)!=int(length):raise ValueError('invalid_body')
    export_request=parse_body(raw)
    def run_export_scoped(operation,timeout):
     def checked():
      next_status,next_actor=verify_live_session(cookie)
      if next_status!=200 or next_actor!=actor:raise PermissionError('session_changed')
      return operation()
     return LIVE_ADMIN.run(checked,timeout)
    status,data=export_emails(export_request,actor,run_source=run_export_scoped);self.reply(status,data)
   except (ValueError,TypeError,UnicodeError):self.reply(422,{'error':'invalid_export_request','complete':False})
   except Exception:self.reply(503,{'error':'export_source_unavailable','complete':False})
   return
  if uri.path=='/users/live-orders':
   if LIVE_ADMIN is None or not callable(verify_live_session) or not callable(private_live_body):self.reply(503,{'error':'live_admission_unavailable'});return
   if uri.query or self.headers.get('Sec-Fetch-Site')!='same-origin':self.reply(403,{'error':'same_origin_required'});return
   if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':self.reply(415,{'error':'json_required'});return
   length=self.headers.get('Content-Length','')
   if not re.fullmatch(r'[0-9]{1,4}',length) or not 1<=int(length)<=4096:self.reply(413,{'error':'body_too_large'});return
   cookie=self.headers.get('Cookie')
   try:
    auth_status,actor=verify_live_session(cookie)
    if auth_status!=200 or not actor:self.reply(auth_status if auth_status in (401,403,429,503) else 503,{'error':'session_unavailable' if auth_status==503 else 'session_denied'});return
    self.connection.settimeout(10)
    raw=self.rfile.read(int(length))
    if len(raw)!=int(length):raise ValueError('invalid_body')
    live_query=private_live_body(raw)
    def run_scoped(operation,timeout):
     def checked():
      next_status,next_actor=verify_live_session(cookie)
      if next_status!=200 or next_actor!=actor:raise PermissionError('session_changed')
      return operation()
     return LIVE_ADMIN.run(checked,timeout)
    status,data=get_live_orders(live_query,actor,run_source=run_scoped);self.reply(status,data)
   except (ValueError,TypeError,UnicodeError):self.reply(422,{'error':'invalid_live_query'})
   except Exception:self.reply(503,{'error':'live_source_unavailable'})
   return
  if uri.path=='/users/private/search':
   from user_http import search as search_users
   user=self.headers.get('X-Auth-User')
   if not user:self.reply(401,{'error':'login_required'});return
   if uri.query or self.headers.get('Sec-Fetch-Site')!='same-origin':self.reply(403,{'error':'same_origin_required'});return
   if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':self.reply(415,{'error':'json_required'});return
   length=self.headers.get('Content-Length','')
   if not re.fullmatch(r'[0-9]{1,4}',length) or not 1<=int(length)<=4096:self.reply(413,{'error':'body_too_large'});return
   try:
    self.connection.settimeout(15)
    body=json.loads(self.rfile.read(int(length)))
    status,data=search_users(USERS,body,user);self.reply(status,data)
   except (ValueError,TypeError,UnicodeError):self.reply(422,{'error':'invalid_user_query'})
   except Exception:self.reply(503,{'error':'users_unavailable'})
   return
  if uri.path==CONVERSATION_PREFIX or uri.path.startswith(CONVERSATION_PREFIX+'/'):
   if CONVERSATION is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})
   else:conversation_handle(self,'POST',uri,self.headers.get('X-Auth-User'),CONVERSATION,hermes_authorizer)
   return
  if uri.path=='/internal/hermes/desktop' and not uri.query:
   if DESKTOP_RPC is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})
   else:DESKTOP_RPC.handle(self)
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

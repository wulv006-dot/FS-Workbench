"""Loopback-only, single-worker date-range reads; nginx authenticates callers."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit,parse_qs
import json,subprocess,sys,time,urllib.request,urllib.parse,os,tempfile,sqlite3
from datetime import datetime,timezone,timedelta
SHANGHAI=timezone(timedelta(hours=8))
from hashlib import sha256
from custom_range import validate
from traffic_contract import RULE_VERSION
from game_dimensions import VERSION as GAME_VERSION
POOL=ThreadPoolExecutor(max_workers=1);LOCK=RLock();JOBS={};BUSY=None
CACHE=Path('/opt/mmoexp-marketing/data/verified-readonly/traffic-ranges')
DETAIL_DATABASE=Path('/opt/mmoexp-marketing/data/verified-readonly/marketing.db')

def cache_path(start,end):
 validate(start,end)
 return CACHE/(RULE_VERSION+'_'+start+'_'+end+'.json')

def ttl(end):
 today=datetime.now(SHANGHAI).date().isoformat()
 return 900 if end>=today else 86400


def project_cached_content(value,start,end):
 # Only hydrate this additive display contract from the same stored raw snapshot.
 # Never recollect, replace totals, infer FC rows from global Top, or rewrite cache.
 breakdowns=((value.get('period') or {}).get('sources',{}).get('gsc') or {}).get('breakdowns',{})
 missing=[name for name in ('query','page') if isinstance(breakdowns.get(name,{}).get('fc27_content'),dict) and 'rows' not in breakdowns[name]['fc27_content']]
 if not missing:return value
 for name in missing:breakdowns[name]['fc27_content']['detail_projection']='legacy_cache_missing_raw'
 if any(p.is_symlink() for p in (DETAIL_DATABASE,*DETAIL_DATABASE.parents)) or not DETAIL_DATABASE.is_file():return value
 try:
  from detail_model import top_table
  db=sqlite3.connect(DETAIL_DATABASE.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
  try:
   for name in missing:
    item=db.execute('SELECT payload_json FROM detail_reports WHERE source=? AND resource=? AND report=? AND start_date=? AND end_date=?',('gsc','sc-domain:mmoexp.com',name,start,end)).fetchone()
    if not item or len(item[0])>8*1024*1024:continue
    raw=json.loads(item[0]);raw['report']=name
    old=breakdowns[name];content=old['fc27_content']
    # A different raw capture must not silently replace the cache's frozen facts.
    if not old.get('status',{}).get('collected_at') or raw.get('collected_at')!=old['status']['collected_at']:continue
    projected=top_table(raw,'clicks',20,None)['fc27_content']
    if projected['metrics']!=content.get('metrics') or projected['returned_matching_rows']!=content.get('returned_matching_rows'):continue
    projected['status']=dict(old.get('status') or {});projected['detail_projection']='stored_raw_same_snapshot'
    old['fc27_content']=projected
  finally:db.close()
 except (OSError,ValueError,TypeError,KeyError,ArithmeticError,sqlite3.Error):pass
 return value

def cached(start,end,allow_stale=False):
 from daily_archive import read
 archived=read('marketing',{'profile':'MMOEXP','start':start,'end':end,'rule':RULE_VERSION,'projection':GAME_VERSION})
 if archived is not None and not allow_stale:return project_cached_content(archived,start,end)
 p=cache_path(start,end)
 if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('linked_range_cache')
 if not p.is_file() or not allow_stale and time.time()-p.stat().st_mtime>=ttl(end):return None
 if p.stat().st_size>8*1024*1024:raise ValueError('range_cache_size')
 value=json.loads(p.read_text('utf8'))
 if not allow_stale and (value.get('period') or {}).get('game_projection_version')!=GAME_VERSION:return None
 if not allow_stale and value.get('validated_day')!=datetime.now(SHANGHAI).date().isoformat():return None
 if not allow_stale and value.get('status')=='partial' and time.time()-p.stat().st_mtime>120:return None
 if value.get('start')!=start or value.get('end')!=end or (value.get('period') or {}).get('rule_version')!=RULE_VERSION:return None
 return project_cached_content(value,start,end)

def retained(start,end):
 value=cached(start,end,allow_stale=True)
 if value is None:return {'schemaVersion':1,'status':'unavailable','start':start,'end':end,'reason':'来源查询失败，未填零。'}
 value.update(status='stale',retained_previous=True,last_attempt={'status':'failed','at':datetime.now(timezone.utc).isoformat()})
 period=value.get('period') or {}
 for source in list(period.get('sources',{}).values())+period.get('adsAccounts',[]):
  source['status']=dict(source.get('status') or {},status='failed',retained_previous=True)
  if isinstance(source.get('contract'),dict):source['contract']['status']='stale'
  if 'campaigns' in source:
   source['campaign_status']=dict(source.get('campaign_status') or {},status='failed',retained_previous=True)
   source['campaign_calculation_complete']=False
 return value

def save_cache(start,end,value):
 if value.get('status') not in ('available','partial'):return
 p=cache_path(start,end)
 if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('linked_range_cache')
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 previous=cached(start,end,allow_stale=True)
 if previous and value.get('status')=='partial':
  for name,current in value.get('period',{}).get('sources',{}).items():
   old=(previous.get('period',{}).get('sources') or {}).get(name)
   if old and current.get('metrics') is None and old.get('metrics') is not None:
    kept=json.loads(json.dumps(old));kept['status']=dict(kept.get('status') or {},status='failed',retained_previous=True)
    if isinstance(kept.get('contract'),dict):kept['contract']['status']='stale'
    value['period']['sources'][name]=kept
  old_accounts={a['customerId']:a for a in previous.get('period',{}).get('adsAccounts',[])}
  for account in value.get('period',{}).get('adsAccounts',[]):
   old=old_accounts.get(account['customerId'])
   if old and account.get('metrics') is None and old.get('metrics') is not None:
    for key in ('metrics','daily','contract'):account[key]=old.get(key)
    account['status']=dict(old.get('status') or {},status='failed',retained_previous=True)
    if isinstance(account.get('contract'),dict):account['contract']['status']='stale'
 value=dict(value,validated_day=datetime.now(SHANGHAI).date().isoformat())
 raw=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
 archive=p.parent/'versions';archive.mkdir(exist_ok=True,mode=0o700)
 if archive.is_symlink():raise ValueError('linked_range_cache')
 version=archive/(sha256(raw).hexdigest()+'.json')
 if not version.exists():
  with version.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  version.chmod(0o600)
 elif version.is_symlink() or version.read_bytes()!=raw:raise ValueError('range_archive_conflict')
 fd,temp=tempfile.mkstemp(prefix='.range-',dir=p.parent)
 try:
  with os.fdopen(fd,'w',encoding='utf8') as out:
   json.dump(value,out,ensure_ascii=False,allow_nan=False);out.flush();os.fsync(out.fileno())
  os.chmod(temp,0o600);os.replace(temp,p)
 finally:
  if os.path.exists(temp):os.unlink(temp)
 from daily_archive import save
 if value.get('status')=='available':
  save('marketing',{'profile':'MMOEXP','start':start,'end':end,'rule':RULE_VERSION,'projection':GAME_VERSION},value)
 return value

def run(start,end):
 try:
  value=subprocess.run([sys.executable,str(Path(__file__).with_name('custom_range.py')),start,end],capture_output=True,timeout=600)
  if value.returncode:raise ValueError('query_failed')
  result=json.loads(value.stdout)
  if result.get('schemaVersion')!=1 or result.get('start')!=start or result.get('end')!=end:raise ValueError('invalid_query_response')
  result=save_cache(start,end,result) or result
  return result
 except (OSError,ValueError,subprocess.TimeoutExpired):return retained(start,end)
def run_links(start,end):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8767/marketing/summary?'+urllib.parse.urlencode({'start':start,'end':end}),timeout=75) as response:return json.load(response)
 except (OSError,ValueError):return {'status':'unavailable','start':start,'end':end}

def query(start,end,submit=POOL.submit,kind='range',refresh=False):
 global BUSY
 validate(start,end);key=(kind,start,end)
 existing=None
 if kind=='range':
  existing=cached(start,end)
  if existing is not None and not refresh:
   stamp=(existing.get('archive') or {}).get('sourceCapturedAt')
   if not stamp or (datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()<ttl(end):return 200,existing
 with LOCK:
  now=time.monotonic()
  for old,record in list(JOBS.items()):
   if record['future'].done():
    record.setdefault('completed',now)
    result=record['future'].result()
    age=now-record['completed']
    success=result.get('status')=='available'
    lifetime=ttl(old[2]) if old[0]=='range' and success else 120 if result.get('status')=='partial' else 30
    same_day=record.get('day')==datetime.now(SHANGHAI).date().isoformat()
    if age>lifetime or not same_day:del JOBS[old]
  if refresh and key in JOBS and JOBS[key]['future'].done() and now-JOBS[key].get('completed',now)>=60:del JOBS[key]
  if key not in JOBS:
   if BUSY is not None and not BUSY.done():
    if existing is not None:
     existing.setdefault('archive',{})['refreshDeferred']=True
     return 200,existing
    return 429,{'status':'busy','reason':'已有一个区间查询正在运行，请稍后再试。'}
   future=submit(run_links if kind=='links' else run,start,end);JOBS[key]={'future':future,'created':now,'day':datetime.now(SHANGHAI).date().isoformat()};BUSY=future
  future=JOBS[key]['future']
  if existing is not None and not future.done():
   existing.setdefault('archive',{})['refreshing']=True
   return 200,existing
  return (200,future.result()) if future.done() else (202,{'status':'pending','start':start,'end':end})
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  p=urlsplit(self.path)
  if p.path not in ('/range','/links'):self.send_error(404);return
  if not self.headers.get('X-Auth-User'):self.send_error(401);return
  try:
   params=parse_qs(p.query,keep_blank_values=True)
   if set(params)-{'start','end','refresh'} or not {'start','end'}<=set(params) or any(len(v)!=1 for v in params.values()) or ('refresh' in params and params['refresh']!=['true']):raise ValueError('invalid_parameters')
   code,result=query(params['start'][0],params['end'][0],kind=p.path[1:],refresh=params.get('refresh')==['true'])
  except (ValueError,TypeError):code,result=400,{'status':'invalid','reason':'请输入有效起止日期，起始不晚于结束，范围不超过366天。'}
  raw=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
  self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8935),Handler).serve_forever()

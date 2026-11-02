"""Fixed one-page HMAC-proxy child. Only an authorized host may launch it."""
import base64,datetime,hashlib,json,os,re,stat,sys,types
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

SHARED='/opt/fs-order-session/fc_shared_admin.py'
SHARED_SHA256='c6eaf37907ef350459a3e980f8e8c8611db3e36c37755965e38d987e3f6a0327'

def load_shared():
 p=Path(SHARED)
 if any(q.is_symlink() for q in (p,*p.parents)):raise ValueError('shared_symlink')
 for parent in p.parents:
  info=parent.stat()
  if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022:raise ValueError('shared_parent_unsafe')
 with os.fdopen(os.open(str(p),os.O_RDONLY|os.O_NOFOLLOW),'rb') as f:
  a=os.fstat(f.fileno());raw=f.read(1048577);b=os.fstat(f.fileno())
  if not stat.S_ISREG(a.st_mode) or a.st_nlink!=1 or a.st_uid!=os.geteuid() or a.st_mode&0o022 or len(raw)>1048576 or (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)!=(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns) or hashlib.sha256(raw).hexdigest()!=SHARED_SHA256:raise ValueError('shared_source_drift')
 module=types.ModuleType('approved_shared_admin');module.__file__=str(p)
 exec(compile(raw,str(p),'exec'),module.__dict__)
 return module

def shanghai_today():return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()

def handle(value,loader=load_shared,*,today=shanghai_today):
 if not isinstance(value,dict) or set(value)!={'path','params','max_bytes'} or value['path']!='/admin/order.Order/index' or type(value['max_bytes']) is not int or not 1<=value['max_bytes']<=1048576:raise ValueError('worker_input')
 params=value['params']
 keys={'page','limit','order'}|{'search[%d][%s]'%(i,k) for i in range(3) for k in ('field','operator','val')}|{'search[2][render]'}
 if not isinstance(params,dict) or set(params)!=keys or type(params['page']) is not int or not 1<=params['page']<=2000 or type(params['limit']) is not int or not 1<=params['limit']<=100 or params['order']!='id,desc':raise ValueError('worker_scope')
 if any(params['search[%d][field]'%i]!=field or params['search[%d][operator]'%i]!=op for i,(field,op) in enumerate((('site_id','='),('gid','='),('paytime','RANGE')))) or params['search[2][render]']!='datetime' or params['search[0][val]']!='266':raise ValueError('worker_scope')
 game=params['search[1][val]'];period=params['search[2][val]']
 if not isinstance(game,str) or not game.isascii() or not game.isdigit() or len(game)>20 or not isinstance(period,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} 00:00:00,\d{4}-\d{2}-\d{2} 23:59:59',period):raise ValueError('worker_scope')
 try:
  start=datetime.date.fromisoformat(period[:10]);end=datetime.date.fromisoformat(period[20:30])
  if not 0<=(end-start).days<28:raise ValueError()
 except ValueError:raise ValueError('worker_dates') from None
 def check_current_date():
  current=today()
  if type(current) is not datetime.date or start<current-datetime.timedelta(days=365) or end>current:raise ValueError('worker_dates')
 check_current_date()
 shared=loader();session=shared.SessionManager({});base=shared.api_base(session.config)
 if base!='http://127.0.0.1:8912' or base not in shared.API_BASES:raise ValueError('worker_proxy')
 query=urlencode(params)
 if len(query)>4096:raise ValueError('worker_query')
 request=Request(base+value['path']+'?'+query,headers=dict(shared.HEADERS),method='GET')
 check_current_date()
 try:
  with session.opener.open(request,timeout=10) as response:status=response.status;body=response.read(value['max_bytes']+1)
 except HTTPError as error:
  try:status=error.code;body=b''
  finally:error.close()
 if type(status) is not int or not 100<=status<=599 or not isinstance(body,bytes) or len(body)>value['max_bytes']:raise ValueError('worker_response')
 return {'status':status,'body':base64.b64encode(body).decode('ascii')}

def main():
 if os.name!='posix' or os.geteuid()!=0:raise SystemExit(1)
 try:
  raw=sys.stdin.buffer.read(8193)
  if len(raw)>8192:raise ValueError('input_too_large')
  result=handle(json.loads(raw));sys.stdout.write(json.dumps(result,separators=(',',':')));sys.stdout.flush()
 except Exception:raise SystemExit(1)

if __name__=='__main__':main()

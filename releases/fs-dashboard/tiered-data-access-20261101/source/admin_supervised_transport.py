"""Bound source work by the original host's subprocess timeout boundary.

Opt-in host component; caller supplies the reviewed worker path/hash and a
trusted Python executable. No network, credentials or process starts on import.
"""
import base64,hashlib,json,os,re,stat,subprocess
from pathlib import Path

class SupervisedAdminTransport:
 def __init__(self,*,worker,worker_sha256,python,runner=subprocess.run):
  if not callable(runner) or not isinstance(worker_sha256,str) or re.fullmatch('[a-f0-9]{64}',worker_sha256) is None:raise ValueError('trusted_worker_required')
  self.worker=Path(worker).absolute();self.expected=worker_sha256;self.python=str(python);self.runner=runner
  if not Path(self.python).is_absolute():raise ValueError('absolute_python_required')
 def __call__(self,path,params,timeout_seconds,max_bytes):
  if path!='/admin/order.Order/index' or not isinstance(params,dict) or type(timeout_seconds) is not int or not 1<=timeout_seconds<=10 or type(max_bytes) is not int or not 1<=max_bytes<=1048576:raise ValueError('fixed_budget_required')
  if any(p.is_symlink() for p in (self.worker,*self.worker.parents)):raise ValueError('worker_symlink_refused')
  if os.name=='posix':
   for parent in self.worker.parents:
    info=parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022 and not (info.st_uid==0 and info.st_mode&stat.S_ISVTX):raise ValueError('worker_parent_permissions_invalid')
  with os.fdopen(os.open(str(self.worker),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as f:
   st=os.fstat(f.fileno());raw=f.read(65537)
   if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=self.expected:raise ValueError('worker_identity_changed')
   if os.name=='posix' and (st.st_uid!=os.geteuid() or st.st_mode&0o022):raise ValueError('worker_permissions_invalid')
  payload=json.dumps({'path':path,'params':params,'max_bytes':max_bytes},sort_keys=True,separators=(',',':')).encode('utf-8')
  if len(payload)>8192:raise ValueError('query_too_large')
  try:
   result=self.runner([self.python,'-I','-B',str(self.worker)],input=payload,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=timeout_seconds,check=False,
                      env={'PATH':'/usr/bin:/bin','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'})
  except subprocess.TimeoutExpired:raise TimeoutError('source_timeout') from None
  except OSError:raise OSError('source_transport_unavailable') from None
  if result.returncode!=0 or not isinstance(result.stdout,bytes) or len(result.stdout)>((max_bytes+2)//3)*4+1024:raise OSError('source_worker_failed')
  try:
   response=json.loads(result.stdout)
   if not isinstance(response,dict) or set(response)!={'status','body'} or type(response['status']) is not int or not 100<=response['status']<=599:raise ValueError()
   body=base64.b64decode(response['body'],validate=True)
   if len(body)>max_bytes:raise ValueError()
   return response['status'],body
  except (ValueError,TypeError,KeyError):raise ValueError('source_worker_response_invalid') from None

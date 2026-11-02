"""Existing host integration helper. The feature remains disabled unless configured."""
import json,os,stat,sys
from pathlib import Path
from admin_live_dispatch import handle
from admin_site_authorizer import ConfiguredAdminAuthorizer
from admin_supervised_transport import SupervisedAdminTransport

CONFIG='/opt/fs-hermes-fc/user_config.json'
WORKER='/opt/fs-hermes-fc/admin_live_worker.py'
WORKER_SHA256='fce78f897468a1ee22c89605cb473372d8129833e639dfef48b3e90cbf827606'

def read_existing_json(path):
 p=Path(path)
 if any(q.is_symlink() for q in (p,*p.parents)):raise ValueError('symlink_refused')
 with os.fdopen(os.open(str(p),os.O_RDONLY|os.O_NOFOLLOW),'rb') as f:
  a=os.fstat(f.fileno());raw=f.read(1048577);b=os.fstat(f.fileno())
  if not stat.S_ISREG(a.st_mode) or a.st_uid!=os.geteuid() or a.st_mode&0o022 or len(raw)>1048576 or (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)!=(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns):raise ValueError('unsafe_or_changed_configuration')
  value=json.loads(raw)
  if not isinstance(value,dict):raise ValueError('invalid_configuration')
  return value

def build_handler(*,load_config,load_policy,rbac,fetch):
 def get(params,user):
  if not user:return 401,{'error':'login_required'}
  try:
   config=load_config()
   if not isinstance(config,dict) or config.get('live_admin_single_page') is not True:return 503,{'error':'live_source_not_enabled'}
   def authorizer(subject):return ConfiguredAdminAuthorizer(subject=subject,load_policy=load_policy,load_config=load_config,rbac=rbac,policy_version='users-live-page-v1')
   return handle(params,user,authorize_for_user=authorizer,fetch=fetch,enabled=True)
  except Exception:return 503,{'error':'live_source_unavailable'}
 return get

def get(params,user):
 if not user:return 401,{'error':'login_required'}
 try:
  # Use the same existing policy module and trusted nginx subject as user_runtime.
  sys.path.insert(0,'/opt/fs-access-policy')
  import rbac
  fetch=SupervisedAdminTransport(worker=WORKER,worker_sha256=WORKER_SHA256,python=sys.executable)
  return build_handler(load_config=lambda:read_existing_json(CONFIG),load_policy=lambda:read_existing_json(rbac.LIVE_POLICY),rbac=rbac,fetch=fetch)(params,user)
 except Exception:return 503,{'error':'live_source_unavailable'}

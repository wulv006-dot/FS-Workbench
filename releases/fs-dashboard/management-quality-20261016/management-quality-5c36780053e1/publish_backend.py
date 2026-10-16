"""Management facts and Hermes adapter only. Shared release/provider/admission fences.
No credentials, model provider settings, pricing, target values or task rows are changed.
"""
import argparse,contextlib,fcntl,hashlib,importlib.util,json,os,re,sqlite3,stat,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
BACKUPS='/var/backups/fs-management-quality'
TARGETS={'management_context.py':'/opt/fs-hermes-fc/management_context.py'}
BASE_SHA='5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
sha=lambda data:hashlib.sha256(data).hexdigest()
at=lambda root,path:root/str(path).lstrip('/')
def digest(p):return sha(p.read_bytes()) if p.is_file() else None
def trusted(path,root):
 for p in (path,*path.parents):
  if p.is_symlink():raise ValueError('symlink_boundary')
  if p.exists():
   s=p.stat()
   if s.st_uid!=os.geteuid() or s.st_mode&0o022 or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)) or (p.is_file() and s.st_nlink!=1):raise ValueError('unsafe_boundary')
  if p==root:break

def base():
 path=HERE/'release_navigation_base.py'
 if digest(path)!=BASE_SHA:raise ValueError('reviewed_publisher_drift')
 spec=importlib.util.spec_from_file_location('_management_release_base',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def validate(m,stage):
 if m!=json.loads((HERE/'contract.json').read_text()) or m.get('scope')!='fs-management-quality-v1':raise ValueError('frozen_contract')
 if len(m['files'])!=len(TARGETS) or {r['candidate']:r['target'] for r in m['files']}!=TARGETS:raise ValueError('exact_targets')
 if not re.fullmatch(r'management-quality-[a-f0-9]{12}',m.get('releaseId','')):raise ValueError('release_id')
 if m.get('businessWrites') is not False or m.get('credentialsChanged') is not False:raise ValueError('scope')
 if stage:
  for r in m['files']:
   p=stage/r['candidate'];trusted(p,stage)
   if digest(p)!=r['sha256']:raise ValueError('candidate_drift')
 return m['files']

def runtime(args):
 result=subprocess.run(args,capture_output=True,text=True,timeout=60)
 if result.returncode:raise RuntimeError('runtime_failed:'+args[0]+':'+result.stderr[-500:])
 return result.stdout.strip()

def guards(m,root):
 for name in ('/var/lib/fs-dashboard-release/pending.json','/var/backups/fs-navigation-native-20261006/pending.json','/var/backups/fs-management-v2-static/pending.json'):
  if at(root,name).exists():raise ValueError('peer_publication_pending')
 for r in m['unchangedRequired']:
  p=at(root,r['path']);trusted(p,root)
  if digest(p)!=r['sha256']:raise ValueError('protected_source_drift:'+r['path'])
 if root==Path('/'):
  if runtime(['systemctl','show','fs-boss-management.service','-p','ActiveState']).partition('=')[2].strip() in ('activating','active','deactivating'):raise ValueError('management_collection_active')

def pending(root):return at(root,BACKUPS+'/pending.json')
def inspect(m,stage,root=Path('/')):
 rows=validate(m,stage);guards(m,root)
 if pending(root).exists():raise ValueError('unresolved_backend_publication')
 for r in rows:
  p=at(root,r['target']);trusted(p,root)
  if digest(p)!=r['beforeSha256']:raise ValueError('before_sha_drift:'+r['target'])
 if root==Path('/') and runtime(['systemctl','is-active','fs-business-range.service'])!='active':raise ValueError('controller_baseline_not_active')
 return {'status':'inspected','writes':0,'files':len(rows)}

@contextlib.contextmanager
def provider_fence(root):
 path=at(root,'/var/lib/fs-business-ranges/fc-daily/provider.lock');trusted(path,root)
 fd=os.open(path,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  for rel in ('advisor/advisor.sqlite3','fc-daily/daily.sqlite3'):
   p=at(root,'/var/lib/fs-business-ranges/'+rel);trusted(p,root)
   with contextlib.closing(sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)) as db:
    if db.execute("SELECT count(*) FROM jobs WHERE state IN ('pending','running')").fetchone()[0]:raise ValueError('other_model_job_active')
  yield
 finally:os.close(fd)

def journal(b,folder,j):b.atomic(folder/'journal.json',json.dumps(j,ensure_ascii=False,indent=2).encode(),0o600)
def current(j,root):
 guards(j['manifest'],root)
 for r in j['files']:
  p=at(root,r['target']);trusted(p,root)
  if digest(p) not in ({r['beforeSha256'],r['sha256']} if r['intent'] else {r['beforeSha256']}):raise ValueError('peer_target_drift')

def restore(b,folder,j,root):
 current(j,root)
 for r in j['files']:
  if r['beforeSha256'] is not None:
   original=folder/'original'/r['candidate'];trusted(original,root)
   if digest(original)!=r['beforeSha256']:raise ValueError('backup_drift')
 for r in reversed(j['files']):
  current(j,root)
  if r['intent'] and r['beforeSha256'] is not None:b.atomic(at(root,r['target']),(folder/'original'/r['candidate']).read_bytes(),r['mode'])
 # New unused Python helpers remain archived in place; old controller/unit do not load them.
 runtime(['systemctl','daemon-reload']);runtime(['systemctl','start','fs-business-range.service'])
 if runtime(['systemctl','is-active','fs-business-range.service'])!='active':raise RuntimeError('rollback_runtime')
 j['status']='rolled_back_new_helpers_retained';journal(b,folder,j)
 if pending(root).exists():pending(root).unlink();b.directory_sync(pending(root).parent)

def apply(m,stage,raw,approval,root=Path('/')):
 if sha(raw)!=approval:raise ValueError('reviewed_manifest_sha_required')
 b=base()
 with b.locks(root),provider_fence(root):
  fence=b.HermesAdmissionFence(root)
  try:
   inspect(m,stage,root)
   folder=at(root,BACKUPS+'/'+m['releaseId']);trusted(folder,root)
   if folder.exists():raise ValueError('backup_exists_no_replay')
   folder.mkdir(parents=True,mode=0o700);b.atomic(folder/'approved-manifest.json',raw,0o600)
   rows=[]
   for r in m['files']:
    p=at(root,r['target']);item=dict(r,mode=stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644,intent=False);rows.append(item)
    if p.exists():
     data=p.read_bytes()
     if sha(data)!=r['beforeSha256']:raise ValueError('backup_cas')
     b.atomic(folder/'original'/r['candidate'],data,0o600)
   j={'manifest':m,'files':rows,'status':'prepared','approvedManifestSha256':approval};journal(b,folder,j);b.atomic(pending(root),json.dumps({'backup':str(folder)}).encode(),0o600)
   # Drain is verified under admission + provider locks, then stop only FS controller.
   fence.stop_then_unlock_database();fence.modified=True
   try:
    None
    for r in rows:
     current(j,root);p=at(root,r['target']);data=(stage/r['candidate']).read_bytes()
     if digest(p)!=r['beforeSha256'] or sha(data)!=r['sha256']:raise ValueError('write_cas')
     r['intent']=True;journal(b,folder,j);b.atomic(p,data,r['mode'])
    current(j,root);runtime(['systemctl','daemon-reload']);runtime(['systemctl','start','fs-business-range.service'])
    if runtime(['systemctl','is-active','fs-business-range.service'])!='active':raise RuntimeError('controller_not_active')
    current(j,root)
    if any(digest(at(root,r['target']))!=r['sha256'] for r in rows):raise ValueError('final_readback')
    j['status']='applied_awaiting_loaded_skill_acceptance';journal(b,folder,j);pending(root).unlink();b.directory_sync(pending(root).parent);fence.confirmed=True
   except Exception:
    runtime(['systemctl','stop','fs-business-range.service']);None;restore(b,folder,j,root);fence.confirmed=True;raise
  finally:
   if fence.modified and not fence.confirmed:runtime(['systemctl','stop','fs-business-range.service'])
   fence.close()
 return {'status':j['status'],'backup':str(folder),'modelStarted':False,'businessWrites':False}

def rollback(folder,approval,root=Path('/')):
 if folder.parent!=at(root,BACKUPS) or not re.fullmatch(r'management-quality-[a-f0-9]{12}',folder.name):raise ValueError('backup_namespace')
 trusted(folder,root);raw=(folder/'approved-manifest.json').read_bytes();j=json.loads((folder/'journal.json').read_text())
 if sha(raw)!=approval or json.loads(raw)!=j['manifest'] or j['approvedManifestSha256']!=approval:raise ValueError('rollback_manifest')
 validate(j['manifest'],None);b=base()
 with b.locks(root),provider_fence(root):
  fence=b.HermesAdmissionFence(root)
  try:
   current(j,root);fence.stop_then_unlock_database();fence.modified=True
   None;restore(b,folder,j,root);fence.confirmed=True
  finally:
   if fence.modified and not fence.confirmed:runtime(['systemctl','stop','fs-business-range.service'])
   fence.close()
 return {'status':j['status'],'backup':str(folder)}

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['inspect','apply','rollback']);p.add_argument('--approved-manifest-sha');p.add_argument('--backup',type=Path);a=p.parse_args()
 if os.geteuid()!=0:raise ValueError('root_required')
 if a.action=='rollback':
  if not a.backup:raise ValueError('backup_required')
  out=rollback(a.backup,a.approved_manifest_sha)
 else:
  raw=(HERE/'contract.json').read_bytes();m=json.loads(raw)
  out=inspect(m,HERE) if a.action=='inspect' else apply(m,HERE,raw,a.approved_manifest_sha)
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()

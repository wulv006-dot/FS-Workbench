"""Software publication guard for the unified business dashboard HTML only.

It does not restrict root, change permissions, or alter authentication. Supported
publishers must use this entry point; direct SSH writes remain outside its guard.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,shutil,tempfile,re

DEPENDENCY_PREFIX="/var/www/dashboard/fs-home/transactions/"
REQUIRED_DEPENDENCIES=frozenset(DEPENDENCY_PREFIX+n for n in ("snapshot-client.js","supplement-insights.js","supplement-insights.css","exact-range-client.js","business-range.js","business-theme.js","business-theme.css"))
def dependency_contract(spec):
 deps=spec.get("dependencies")
 if not isinstance(deps,list) or len(deps)!=7:raise Refused("all seven exact shared dependency baselines required")
 if any(not isinstance(d,dict) or not isinstance(d.get("path"),str) or not isinstance(d.get("sha256"),str) or re.fullmatch(r"[0-9a-f]{64}",d["sha256"]) is None for d in deps):raise Refused("valid dependency path and SHA256 required")
 if set(d["path"] for d in deps)!=REQUIRED_DEPENDENCIES:raise Refused("exact unique shared dependency path set required")
 return deps

class Refused(RuntimeError):pass
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atomic_json(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
class Lock:
 def __init__(self,path):self.path=path
 def __enter__(self):
  self.path.parent.mkdir(parents=True,exist_ok=True);self.f=open(self.path,'a+b')
  try:
   if os.name=='nt':
    import msvcrt
    self.f.seek(0);self.f.write(b'0');self.f.flush();self.f.seek(0);msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl
    fcntl.flock(self.f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:self.f.close();raise Refused('another dashboard publication holds the release lock')
  return self
 def __exit__(self,*args):self.f.close()
def validate_reviewed_recovery(root,state,ledger,spec,payload,current):
 context=spec.get('reviewedUnmanagedRecovery')
 if not isinstance(context,dict) or not ledger:raise Refused('reviewed recovery contract and existing ledger required')
 if context.get('restoreFromReleaseId')!=ledger['releaseId'] or context.get('expectedLedgerSha256')!=ledger['sha256']:raise Refused('recovery must restore the latest recorded release')
 known=state/'records'/f"{ledger['releaseId']}.json"
 if not known.exists() or json.loads(known.read_text('utf-8'))!=ledger:raise Refused('recorded recovery baseline differs from current ledger')
 backup_path=context.get('incidentBackup','')
 if not isinstance(backup_path,str) or not backup_path.startswith('/var/backups/fs-dashboard-incident-') or '/' in backup_path.removeprefix('/var/backups/') or '..' in backup_path:raise Refused('approved incident backup path required')
 backup=root/backup_path.lstrip('/')
 if not backup.is_dir() or backup.is_symlink() or digest(backup/'index.html')!=current or json.loads((backup/'ledger.json').read_text('utf-8'))!=ledger:raise Refused('incident backup differs from reviewed current file or ledger')
 if (state/'pending.json').exists():raise Refused('unresolved pending publication; recovery refused')
 old_marker=f'<meta name="fs-dashboard-release" content="{ledger["releaseId"]}">'.encode()
 new_marker=f'<meta name="fs-dashboard-release" content="{spec["releaseId"]}">'.encode()
 if payload.count(new_marker)!=1 or hashlib.sha256(payload.replace(new_marker,old_marker,1)).hexdigest()!=ledger['sha256']:raise Refused('recovery payload must exactly match latest recorded HTML except release marker')
 if len(spec.get('dependencies',[]))!=7:raise Refused('reviewed recovery requires all seven shared dependency baselines')

def publish(root,manifest_path,rollback=False,recovery=False):
 root=Path(root);manifest_path=Path(manifest_path).resolve();stage=manifest_path.parent
 state=root/'var/lib/fs-dashboard-release';live=root/'var/www/dashboard/index.html'
 with Lock(root/'var/lock/fs-dashboard-release.lock'):
  spec=json.loads(manifest_path.read_text('utf-8'));ledger_path=state/'current.json'
  ledger=json.loads(ledger_path.read_text('utf-8')) if ledger_path.exists() else None
  current=digest(live) if live.exists() else None
  if current!=spec.get('expectedLiveSha256'):raise Refused('live file differs from reviewed baseline; re-read and merge first')
  if (ledger or {}).get('releaseId')!=spec.get('expectedReleaseId'):raise Refused('release ledger advanced; stale publisher refused')
  unmanaged=bool(ledger and current!=ledger['sha256'])
  if unmanaged and not recovery:raise Refused('unmanaged overwrite detected; deliberate adoption requires a reviewed recovery release')
  if recovery and (not unmanaged or rollback):raise Refused('reviewed recovery is only for an unmanaged overwrite, not normal publication or rollback')
  version=spec.get('version');release_id=spec.get('releaseId')
  if not isinstance(version,int) or not isinstance(release_id,str) or not release_id.replace('-','').replace('_','').isalnum():raise Refused('version and safe releaseId are required')
  if not rollback and ledger and version<=ledger['version']:raise Refused('older or same version refused; intentional rollback requires recorded release and explicit acknowledgement')
  src=(stage/spec.get('source','dashboard.html')).resolve()
  if src.parent!=stage or not src.is_file() or src.is_symlink():raise Refused('source must be a regular file in the staging directory')
  payload=src.read_bytes()
  if hashlib.sha256(payload).hexdigest()!=spec.get('sha256'):raise Refused('staged bytes differ from manifest')
  if recovery:validate_reviewed_recovery(root,state,ledger,spec,payload,current)
  dependencies=dependency_contract(spec)
  def check_dependencies():
   for dep in dependencies:
    path=dep.get('path','')
    if not path.startswith('/var/www/dashboard/fs-home/transactions/') or '/' in path.removeprefix('/var/www/dashboard/fs-home/transactions/') or not path.endswith(('.js','.css')):raise Refused('dependency path outside permitted shared frontend assets')
    if digest(root/path.lstrip('/'))!=dep.get('sha256'):raise Refused('shared dependency changed; re-read and merge first')
  check_dependencies()
  html=payload.decode('utf-8')
  requirements=['FSBusinessSnapshots(',"currentExact()",'id="supplement-insights"','profit-sales','fs-dashboard-release']
  if not all(x in html for x in requirements):raise Refused('required live data and chart contracts absent; legacy HTML refused')
  if rollback:
   known=state/'records'/f'{release_id}.json'
   if not known.exists() or json.loads(known.read_text())['sha256']!=spec['sha256']:raise Refused('rollback must target an exact previously recorded release')
  backup=root/'var/backups/fs-dashboard-releases'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
  backup.mkdir(parents=True)
  if live.exists():shutil.copy2(live,backup/'index.html')
  if ledger:atomic_json(backup/'previous-release.json',ledger)
  next_state={'schemaVersion':1,'releaseId':release_id,'version':version,'sha256':spec['sha256'],'publishedAt':now(),'previousReleaseId':(ledger or {}).get('releaseId'),'previousSha256':current,'backup':str(backup),'manifestSha256':digest(manifest_path),'intentionalRollback':rollback,'protectedPath':'/var/www/dashboard/index.html'}
  if recovery:next_state['reviewedUnmanagedRecovery']=spec['reviewedUnmanagedRecovery']
  # Durable intent makes a crash between HTML rename and ledger update detectable.
  atomic_json(state/'pending.json',next_state)
  fd,tmp=tempfile.mkstemp(prefix='.dashboard-release-',dir=live.parent)
  try:
   with os.fdopen(fd,'wb') as out:out.write(payload);out.flush();os.fsync(out.fileno())
   # Preserve the existing file mode; do not change site's authentication/ACLs.
   if os.name!='nt':os.chmod(tmp,live.stat().st_mode & 0o777)
   if digest(live)!=current:raise Refused('live changed during staging; abort without overwrite')
   check_dependencies()
   if ledger_path.exists() and json.loads(ledger_path.read_text('utf-8'))!=ledger:raise Refused('ledger changed during staging; abort without overwrite')
   os.replace(tmp,live)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
  if digest(live)!=spec['sha256']:raise Refused('post-publication digest mismatch')
  atomic_json(state/'records'/f'{release_id}.json',next_state);atomic_json(ledger_path,next_state)
  (state/'pending.json').unlink(missing_ok=True)
  atomic_json(backup/'deployment-report.json',next_state)
  return next_state
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='/');p.add_argument('--manifest',required=True);p.add_argument('--ack-intentional-rollback',action='store_true');p.add_argument('--ack-reviewed-unmanaged-recovery',action='store_true');a=p.parse_args()
 try:print(json.dumps(publish(a.root,a.manifest,a.ack_intentional_rollback,a.ack_reviewed_unmanaged_recovery)))
 except (Refused,OSError,ValueError) as e:print(json.dumps({'status':'refused','reason':str(e)}));raise SystemExit(2)
if __name__=='__main__':main()

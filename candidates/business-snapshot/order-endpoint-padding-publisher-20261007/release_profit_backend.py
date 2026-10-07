"""Draft restricted static range-client publisher; independent review required. Default inspection never writes.

Linux apply/rollback use exact target allowlist, manifest approval SHA, shared
gateway lock, per-file CAS, durable backups and rollback of this release only.
Only two existing reviewed profit helper files may be written; collector is protected. No current snapshot, auth, nginx, unit, timer, price, business HTML or Google source writes.
"""
import argparse, contextlib, hashlib, json, os, re, stat, subprocess, tempfile, time
from pathlib import Path

HASH=re.compile(r'^[a-f0-9]{64}$')
TARGETS={'profit_backfill.py': '/opt/fs-transaction-snapshot/profit_backfill.py', 'profit_daily_reader.py': '/opt/fs-transaction-snapshot/profit_daily_reader.py'}
RELATIVE=set(TARGETS)
PROTECTED=set(['/etc/nginx/conf.d/iggm-web.conf', '/etc/nginx/fs-business-range.locations.conf', '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', '/etc/nginx/fs-navigation-preview-20261006.locations.conf', '/etc/systemd/system/fs-transaction-collect.service', '/etc/systemd/system/fs-transaction-collect.timer', '/opt/auth-portal/auth_portal.py', '/opt/fc27-gate/fc27_gate.py', '/opt/fs-access-policy/access_policy.py', '/opt/fs-dashboard-release/release_gateway.py', '/opt/fs-exact-range-20261001/range_api.py', '/opt/fs-transaction-snapshot/atomic_snapshot.py', '/opt/fs-transaction-snapshot/collector.py', '/opt/fs-transaction-snapshot/fc_category_contract.py', '/opt/fs-transaction-snapshot/fc_category_reader.py', '/opt/fs-transaction-snapshot/fc_product_contract.py', '/opt/fs-transaction-snapshot/fc_product_reader.py', '/opt/fs-transaction-snapshot/primary_fields.py', '/opt/fs-transaction-snapshot/primary_reader.py', '/opt/fs-transaction-snapshot/profit-history-seed.json', '/opt/fs-transaction-snapshot/profit_daily.py', '/opt/fs-transaction-snapshot/profit_reader_adapter.py', '/opt/fs-transaction-snapshot/supplement_fields.py', '/opt/fs-transaction-snapshot/supplement_reader.py', '/var/lib/fs-navigation-formal-static/20261006/analytics/frame-theme.css', '/var/lib/fs-navigation-formal-static/20261006/analytics/index.html', '/var/lib/fs-navigation-formal-static/20261006/analytics/shell.css', '/var/lib/fs-navigation-formal-static/20261006/analytics/shell.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/business.css', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/business.html', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/business.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/google.css', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/google.html', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/google.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/home.html', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/index.html', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/metrics.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/navigation.json', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/runtime.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/shell.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/snapshot-client.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-3a65044a25f8/workspace.css', '/var/www/dashboard/fs-home/app.js', '/var/www/dashboard/fs-home/index.html', '/var/www/dashboard/fs-home/metrics.js', '/var/www/dashboard/fs-home/module-registry.json', '/var/www/dashboard/fs-home/navigation.json', '/var/www/dashboard/fs-home/styles.css', '/var/www/dashboard/fs-home/transactions/aion2-status.js', '/var/www/dashboard/fs-home/transactions/business-range.js', '/var/www/dashboard/fs-home/transactions/business-theme.css', '/var/www/dashboard/fs-home/transactions/business-theme.js', '/var/www/dashboard/fs-home/transactions/exact-range-client.js', '/var/www/dashboard/fs-home/transactions/snapshot-client.js', '/var/www/dashboard/fs-home/transactions/supplement-insights.css', '/var/www/dashboard/fs-home/transactions/supplement-insights.js', '/var/www/dashboard/index.html', '/var/www/fs-nav-preview/20261006/analytics/frame-theme.css', '/var/www/fs-nav-preview/20261006/analytics/index.html', '/var/www/fs-nav-preview/20261006/analytics/shell.css', '/var/www/fs-nav-preview/20261006/analytics/shell.js', '/var/www/mmoexp-marketing/current/business-module.js', '/var/www/mmoexp-marketing/current/index.html', '/var/www/mmoexp-marketing/current/marketing-module.css', '/var/www/mmoexp-marketing/current/marketing-module.js', '/var/www/sites/wulv/fc27-ops/data/fc-analytics.js', '/var/www/sites/wulv/fc27-ops/data/fc-products.js', '/var/www/sites/wulv/fc27-ops/index.html'])
WRITE_ORDER=['profit_backfill.py', 'profit_daily_reader.py']
AFTER_MODES={'profit_backfill.py': 420, 'profit_daily_reader.py': 420}
def target_for(rel):
 if rel not in TARGETS:raise ValueError('unapproved candidate file')
 return TARGETS[rel]

def rooted(root,path): return root/path.lstrip('/')
def digest(path):
 return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def directory_sync(path):
 fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
 try:os.fsync(fd)
 finally:os.close(fd)
def no_target_link(path):
 for p in (path,*path.parents):
  if p.is_symlink():raise ValueError('target or parent is a symlink: '+str(p))
 if path.exists() and not path.is_file():raise ValueError('target is not a regular file')
def atomic(path,data,mode=0o644):
 no_target_link(path)
 path.parent.mkdir(parents=True,exist_ok=True)
 no_target_link(path)
 fd,tmp=tempfile.mkstemp(prefix='.fs-nav-',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   f.write(data);f.flush()
   if hasattr(os,'fchmod'):os.fchmod(f.fileno(),mode)
   else:os.chmod(tmp,mode)
   os.fsync(f.fileno())
  os.replace(tmp,path);directory_sync(path.parent)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def validate(manifest,stage):
 files=manifest.get('files',[])
 if manifest.get('schemaVersion')!=1 or {f.get('candidate') for f in files}!=RELATIVE or len(files)!=len(RELATIVE):raise ValueError('manifest must contain exactly the 2 reviewed existing profit helper files')
 for row in files:
  rel=row['candidate'];src=stage/'candidate'/rel
  if row.get('afterMode')!=AFTER_MODES.get(rel):raise ValueError('unreviewed file permissions')
  if row.get('target')!=target_for(rel) or not HASH.fullmatch(row.get('sha256','')):raise ValueError('invalid target or hash')
  if not HASH.fullmatch(row.get('beforeSha256') or ''):raise ValueError('existing target requires exact baseline hash')
  if src.is_symlink() or not src.resolve().is_relative_to((stage/'candidate').resolve()):raise ValueError('candidate escaped stage')
  if digest(src)!=row['sha256']:raise ValueError('staged candidate SHA differs from reviewed manifest')
 protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}
 if set(protected)!=PROTECTED or len(manifest['unchangedRequired'])!=len(PROTECTED) or not all(HASH.fullmatch(v or '') for v in protected.values()):raise ValueError('exact protected profit baselines are required')
 return files
def guards(manifest,root):
 if rooted(root,'/var/lib/fs-dashboard-release/pending.json').exists():raise ValueError('pending gateway incident')
 if rooted(root,'/var/backups/fs-navigation-native-20261006/pending.json').exists():raise ValueError('pending native UI incident')
 ledger=json.loads(rooted(root,'/var/lib/fs-dashboard-release/current.json').read_text())
 if ledger.get('releaseId')!=manifest.get('expectedBusinessReleaseId') or ledger.get('version')!=manifest.get('expectedBusinessVersion'):raise ValueError('business ledger drift')
 for row in manifest['unchangedRequired']:
  if digest(rooted(root,row['path']))!=row['sha256']:raise ValueError('protected source drift: '+row['path'])
def monotonic_schedule_seconds(value):
 # systemctl pretty-prints monotonic timestamps, including weeks after uptime grows.
 # Validate the whole value: accepting a known suffix of an unknown unit is unsafe.
 units={'w':604800,'d':86400,'h':3600,'min':60,'m':60,'s':1}
 token=r'([0-9]+(?:\.[0-9]+)?)\s*(min|w|d|h|m|s)'
 value=value.strip()
 if not re.fullmatch(r'(?:'+token+r'\s*)+',value):raise RuntimeError('timer_schedule_unavailable')
 seconds=sum(float(number)*units[unit] for number,unit in re.findall(token,value))
 if not 0<=seconds<float('inf'):raise RuntimeError('timer_schedule_unavailable')
 return seconds

def collector_idle():
 r=subprocess.run(['systemctl','show','fs-transaction-collect.service','--no-pager','-p','ActiveState','-p','TimeoutStartUSec'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=4)
 props=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
 if r.returncode or props.get('ActiveState')!='inactive' or props.get('TimeoutStartUSec')!='30min':raise ValueError('collector active or service budget drift')
 r=subprocess.run(['systemctl','show','fs-transaction-collect.timer','--no-pager','-p','ActiveState','-p','NextElapseUSecMonotonic'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=4)
 props=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
 if r.returncode or props.get('ActiveState')!='active' or monotonic_schedule_seconds(props.get('NextElapseUSecMonotonic',''))-time.monotonic()<270:raise ValueError('natural collector due; wait without changing schedule')

def retirement(root):
 collector_idle()
 if rooted(root,'/opt/dashboard-collect/publish_to_server.py').exists():raise ValueError('old publisher reappeared')
 for unit in ('dashboard-pipeline.service','dashboard-publish.service','dashboard-fallback.service'):
  path=rooted(root,'/etc/systemd/system/'+unit)
  if not path.is_symlink() or str(path.readlink())!='/dev/null':raise ValueError('old release service no longer masked: '+unit)
 for unit in ('dashboard-pipeline.timer','dashboard-fallback.timer'):
  r=subprocess.run(['systemctl','show',unit,'--no-pager','-p','UnitFileState','-p','ActiveState'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
  props=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
  if r.returncode or props.get('UnitFileState')!='disabled' or props.get('ActiveState')!='inactive':raise ValueError('old release timer state changed: '+unit)
@contextlib.contextmanager
def locks(root):
 import fcntl
 handles=[]
 try:
  for name in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock','/var/www/dashboard/fs-home/transactions/collector.lock'):
   path=rooted(root,name)
   if name.endswith('/collector.lock'):
    no_target_link(path)
    fd=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
   else:
    # Standard root-owned /var/lock -> /run/lock alias only; keep the same lock inode.
    alias=rooted(root,'/var/lock')
    if alias.is_symlink():
     canonical=rooted(root,'/run/lock')
     for directory in (alias.parent,*alias.parent.parents,canonical,*canonical.parents):
      if directory.is_symlink():raise ValueError('unreviewed lock parent alias')
     if not alias.parent.is_dir() or not canonical.is_dir() or canonical.stat().st_uid!=os.geteuid():raise ValueError('unsafe canonical lock directory')
     if alias.lstat().st_uid!=os.geteuid() or alias.resolve(strict=True)!=canonical.resolve(strict=True):raise ValueError('unreviewed lock directory alias')
     path=canonical/Path(name).name
    no_target_link(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(str(path),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:
    os.close(fd);raise ValueError('unsafe release lock ownership/type')
   f=os.fdopen(fd,'a+b');handles.append(f);fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield
 finally:
  for f in reversed(handles):f.close()
def inspect(manifest,stage,root=Path('/')):
 files=validate(manifest,stage);guards(manifest,root);retirement(root)
 for row in files:
  path=rooted(root,row['target']);no_target_link(path)
  if digest(path)!=row['beforeSha256']:raise ValueError('target baseline drift: '+row['target'])
 return dict(releaseReady=manifest.get('releaseReady') is True,backendFiles=len(files),sourceCAS='passed',protectedCAS='passed',oldPublisher='still retired',mutations=False)
def journal_write(backup,journal):atomic(backup/'journal.json',json.dumps(journal,indent=2).encode(),0o600)
def rollback_journal(backup,journal,root):
 for row in journal['files']:
  if row.get('intent') and digest(rooted(root,row['target'])) not in (row['sha256'],row['beforeSha256']):raise ValueError('rollback intent target drift; preserve all files for manual review')
 rows=[row for row in journal['files'] if row['written']]
 # Check every written target and every backup BEFORE changing any of them.
 for row in rows:
  path=rooted(root,row['target']);no_target_link(path)
  if digest(path)!=row['sha256']:raise ValueError('rollback CAS drift; preserve for manual review: '+row['target'])
  if row['beforeSha256'] is not None and digest(backup/'files'/row['candidate'])!=row['beforeSha256']:raise ValueError('rollback backup SHA mismatch')
 for row in reversed(rows):
  path=rooted(root,row['target'])
  if digest(path)!=row['sha256']:raise ValueError('rollback target changed after validation')
  if row['beforeSha256'] is None:
   atomic(backup/'removed-new-files'/row['candidate'],path.read_bytes(),0o600)
   if digest(path)!=row['sha256']:raise ValueError('new file changed before removal')
   path.unlink();directory_sync(path.parent)
  else:atomic(path,(backup/'files'/row['candidate']).read_bytes(),row['beforeMode'])
  row['written']=False;journal_write(backup,journal)
 journal['status']='rolled-back';journal_write(backup,journal)
def apply(manifest,stage,approved_sha,manifest_bytes,release_id,root=Path('/')):
 if manifest.get('releaseReady') is not True:raise ValueError('releaseReady=false; independent profit-backend review gate remains OPEN')
 if hashlib.sha256(manifest_bytes).hexdigest()!=approved_sha:raise ValueError('reviewed manifest approval SHA differs')
 if not re.fullmatch(r'profit-backend-[0-9]{8}T[0-9]{6}Z',release_id):raise ValueError('release id must be profit-backend-YYYYMMDDTHHMMSSZ')
 files=validate(manifest,stage)
 with locks(root):
  inspect(manifest,stage,root)
  backup=rooted(root,'/var/backups/fs-profit-backend-20261006/'+release_id)
  if backup.exists():raise ValueError('release id already used; do not retry blindly')
  no_target_link(backup)
  backup.mkdir(parents=True,mode=0o700);directory_sync(backup.parent)
  journal=dict(status='prepared',approvedManifestSha256=approved_sha,manifest=manifest,files=[])
  for row in files:
   path=rooted(root,row['target'])
   saved={**row,'beforeMode':stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644,'written':False}
   if path.exists():atomic(backup/'files'/row['candidate'],path.read_bytes(),0o600)
   if saved['beforeSha256'] is not None and digest(backup/'files'/row['candidate'])!=saved['beforeSha256']:raise ValueError('backup source drift')
   journal['files'].append(saved)
  atomic(backup/'approved-manifest.json',manifest_bytes,0o600);journal_write(backup,journal)
  ordered=sorted(journal['files'],key=lambda row:WRITE_ORDER.index(row['candidate']))
  try:
   for row in ordered:
    guards(manifest,root);retirement(root)
    path=rooted(root,row['target']);no_target_link(path)
    if digest(path)!=row['beforeSha256']:raise ValueError('target drift before replacement: '+row['target'])
    payload=(stage/'candidate'/row['candidate']).read_bytes()
    if hashlib.sha256(payload).hexdigest()!=row['sha256']:raise ValueError('staged source changed during release')
    # Journal intent before rename; recovery can classify old/new hashes after a crash.
    row['intent']=True;journal_write(backup,journal)
    atomic(path,payload,row['afterMode']);row['written']=True;journal_write(backup,journal)
   guards(manifest,root);retirement(root)
   if any(digest(rooted(root,row['target']))!=row['sha256'] for row in journal['files']):raise ValueError('post-release SHA mismatch')
   journal['status']='applied-awaiting-new-natural-acceptance';journal_write(backup,journal)
  except Exception as error:
   # The rename may have succeeded before a later fsync/journal error.
   for row in journal['files']:
    if row.get('intent') and digest(rooted(root,row['target']))==row['sha256']:row['written']=True
   journal['failure']=str(error)
   try:journal_write(backup,journal)
   except OSError:pass
   guards(manifest,root);retirement(root)
   rollback_journal(backup,journal,root);raise
  return dict(backup=str(backup),status=journal['status'],backendFiles=len(files),collectorStarts=0,timerChanges=0,priceWrites=0)
def rollback(backup,approved_sha,root=Path('/')):
 no_target_link(backup/'journal.json')
 journal=json.loads((backup/'journal.json').read_text())
 if journal['approvedManifestSha256']!=approved_sha:raise ValueError('wrong release approval SHA')
 with locks(root):
  guards(journal['manifest'],root);retirement(root)
  # Recover a durable intent whose rename happened before written=true was journaled.
  for row in journal['files']:
   if row.get('intent'):
    sha=digest(rooted(root,row['target']))
    if sha==row['sha256']:row['written']=True
    elif sha!=row['beforeSha256']:raise ValueError('uncertain target drift; no rollback performed')
  rollback_journal(backup,journal,root)
 return dict(status='rolled-back',backup=str(backup),collectorStarts=0,timerChanges=0,priceWrites=0)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply','rollback'],nargs='?',default='inspect');parser.add_argument('--manifest',type=Path,default=Path(__file__).parent/'release-manifest-draft.json');parser.add_argument('--approved-manifest-sha');parser.add_argument('--release-id');parser.add_argument('--backup',type=Path)
 args=parser.parse_args()
 if args.action!='inspect' and os.name!='posix':raise ValueError('mutating commands require reviewed Linux release environment')
 if args.action=='rollback':
  if not args.backup or args.backup.parent!=Path('/var/backups/fs-profit-backend-20261006'):raise ValueError('backup must be exactly one range-client release backup')
  result=rollback(args.backup,args.approved_manifest_sha)
 else:
  manifest_bytes=args.manifest.read_bytes();manifest=json.loads(manifest_bytes)
  result=inspect(manifest,args.manifest.parent) if args.action=='inspect' else apply(manifest,args.manifest.parent,args.approved_manifest_sha,manifest_bytes,args.release_id)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()

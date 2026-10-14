"""Reviewed static navigation release only. Default inspection never writes.

Linux apply/rollback use exact target allowlist, manifest approval SHA, shared
gateway lock, per-file CAS, durable backups and rollback of this release only.
No auth, nginx, unit, worker, timer or business/Google source can be written.
"""
import argparse, contextlib, hashlib, json, os, re, stat, subprocess, tempfile
from pathlib import Path

HASH=re.compile(r'^[a-f0-9]{64}$')
RELATIVE={
 'fs-home/index.html','fs-home/navigation.js','fs-home/navigation.css','fs-home/navigation.json',
 'hubnav.js','hubnav.css',
 *(f'modules/{key}/index.html' for key in ('analytics','sports','arpg','collaboration','about')),
 *(f'analytics/{key}' for key in ('index.html','shell.js','shell.css','frame-theme.css')),
}
def target_for(rel):
 if rel not in RELATIVE: raise ValueError('unapproved candidate file')
 return '/var/www/hub/'+rel if rel in ('hubnav.js','hubnav.css') else '/var/www/dashboard/'+rel
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
 if manifest.get('schemaVersion')!=1 or {f.get('candidate') for f in files}!=RELATIVE or len(files)!=len(RELATIVE):raise ValueError('manifest must contain exactly the 15 approved static files')
 for row in files:
  rel=row['candidate'];src=stage/'candidate'/rel
  if row.get('target')!=target_for(rel) or not HASH.fullmatch(row.get('sha256','')):raise ValueError('invalid target or hash')
  if row.get('beforeSha256') is not None and not HASH.fullmatch(row['beforeSha256']):raise ValueError('invalid baseline hash')
  if src.is_symlink() or not src.resolve().is_relative_to((stage/'candidate').resolve()):raise ValueError('candidate escaped stage')
  if digest(src)!=row['sha256']:raise ValueError('staged candidate SHA differs from reviewed manifest')
 protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}
 if not HASH.fullmatch(protected.get('/var/www/dashboard/index.html','')):raise ValueError('protected business HTML SHA is required')
 return files
def guards(manifest,root):
 for row in manifest['unchangedRequired']:
  if digest(rooted(root,row['path']))!=row['sha256']:raise ValueError('protected source drift: '+row['path'])
def retirement(root):
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
  for name in ('fs-navigation-release.lock','fs-dashboard-release.lock'):
   path=rooted(root,'/var/lock/'+name);path.parent.mkdir(parents=True,exist_ok=True)
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
 return dict(releaseReady=manifest.get('releaseReady') is True,staticFiles=len(files),sourceCAS='passed',protectedCAS='passed',oldPublisher='still retired',mutations=False)
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
 if manifest.get('releaseReady') is not True:raise ValueError('releaseReady=false; permission/real-role gate remains OPEN')
 if hashlib.sha256(manifest_bytes).hexdigest()!=approved_sha:raise ValueError('reviewed manifest approval SHA differs')
 if not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z',release_id):raise ValueError('release id must be nav-YYYYMMDDTHHMMSSZ')
 files=validate(manifest,stage)
 with locks(root):
  inspect(manifest,stage,root)
  backup=rooted(root,'/var/backups/fs-navigation-20261006/'+release_id)
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
  ordered=sorted(journal['files'],key=lambda row:(row['candidate']=='fs-home/index.html',row['candidate']=='hubnav.js',row['candidate']))
  try:
   for row in ordered:
    guards(manifest,root);retirement(root)
    path=rooted(root,row['target']);no_target_link(path)
    if digest(path)!=row['beforeSha256']:raise ValueError('target drift before replacement: '+row['target'])
    payload=(stage/'candidate'/row['candidate']).read_bytes()
    if hashlib.sha256(payload).hexdigest()!=row['sha256']:raise ValueError('staged source changed during release')
    # Journal intent before rename; recovery can classify old/new hashes after a crash.
    row['intent']=True;journal_write(backup,journal)
    atomic(path,payload,row['beforeMode']);row['written']=True;journal_write(backup,journal)
   guards(manifest,root);retirement(root)
   if any(digest(rooted(root,row['target']))!=row['sha256'] for row in journal['files']):raise ValueError('post-release SHA mismatch')
   journal['status']='applied-awaiting-actual-http-role-acceptance';journal_write(backup,journal)
  except Exception as error:
   # The rename may have succeeded before a later fsync/journal error.
   for row in journal['files']:
    if row.get('intent') and digest(rooted(root,row['target']))==row['sha256']:row['written']=True
   journal['failure']=str(error)
   try:journal_write(backup,journal)
   except OSError:pass
   guards(manifest,root);retirement(root)
   rollback_journal(backup,journal,root);raise
  return dict(backup=str(backup),status=journal['status'],staticFiles=len(files),businessWorkerTimerActions=0)
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
 return dict(status='rolled-back',backup=str(backup),businessWorkerTimerActions=0)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply','rollback'],nargs='?',default='inspect');parser.add_argument('--manifest',type=Path,default=Path(__file__).parent/'release-diff.json');parser.add_argument('--approved-manifest-sha');parser.add_argument('--release-id');parser.add_argument('--backup',type=Path)
 args=parser.parse_args()
 if args.action!='inspect' and os.name!='posix':raise ValueError('mutating commands require reviewed Linux release environment')
 if args.action=='rollback':
  if not args.backup or args.backup.parent!=Path('/var/backups/fs-navigation-20261006'):raise ValueError('backup must be exactly one navigation release backup')
  result=rollback(args.backup,args.approved_manifest_sha)
 else:
  manifest_bytes=args.manifest.read_bytes();manifest=json.loads(manifest_bytes)
  result=inspect(manifest,args.manifest.parent) if args.action=='inspect' else apply(manifest,args.manifest.parent,args.approved_manifest_sha,manifest_bytes,args.release_id)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()

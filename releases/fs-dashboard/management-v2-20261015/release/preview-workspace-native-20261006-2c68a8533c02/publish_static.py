"""Fixed management-only static release. Exact manifest, shared locks, CAS and rollback.
This publisher never edits auth, timers, runtime code, targets, credentials or business data.
"""
import argparse,hashlib,importlib.util,json,os,re,stat,subprocess
from pathlib import Path
BASE_SHA='5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
HERE=Path(__file__).resolve().parent
BASE=HERE/'release_navigation_base.py'
FRAGMENT='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
HUB='/var/www/hub/hubnav.js'
BACKUPS='/var/backups/fs-management-v2-static'
NAMES={'aion2.html','arc_raiders.html','arena_breakout_infinite.html','cfb27.html','cod_bo7.html','d4.html','dark_and_darker.html','fc27.html','index.html','management-live.css','management-live.js','maplestory_classic.html','mlb26.html','nba2k27.html','nfl27.html','poe2.html','rs.html','sandbox-live.js','sandbox.html','targets.json','wow_forever.html'}
def sha(data):return hashlib.sha256(data).hexdigest()
def digest(p):return sha(p.read_bytes()) if p.is_file() else None
def at(root,path):return root/str(path).lstrip('/')
def trusted(path,root):
 for p in (path,*path.parents):
  if p.is_symlink():raise ValueError('symlink_boundary')
  if p.exists():
   s=p.stat()
   if s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)&0o022 or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)) or (p.is_file() and s.st_nlink!=1):raise ValueError('ownership_boundary')
  if p==root:break

def base():
 if digest(BASE)!=BASE_SHA:raise ValueError('publisher_baseline_changed')
 spec=importlib.util.spec_from_file_location('_fs_reviewed_release_base',BASE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def validate(manifest,stage):
 # contract.json is frozen with the package and independently reviewed before apply.
 contract=json.loads((HERE/'contract.json').read_text())
 if manifest!=contract:raise ValueError('frozen_contract_changed')
 if manifest.get('scope')!='fs-management-v2-static' or manifest.get('businessWrites') is not False:raise ValueError('scope')
 rid=manifest['releaseId']
 if not re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',rid):raise ValueError('release_id')
 rows=manifest['files'];prefix='/var/lib/fs-navigation-formal-static/'+rid+'/management/'
 expected={**{'assets/'+n:prefix+n for n in NAMES},'candidate/formal.conf':FRAGMENT,'candidate/hubnav.js':HUB}
 if len(rows)!=len(expected) or {r['candidate']:r['target'] for r in rows}!=expected:raise ValueError('fixed_targets')
 for r in rows:
  if r['candidate'].startswith('assets/') and r['beforeSha256'] is not None:raise ValueError('immutable_asset')
  if stage:
   p=stage/r['candidate'];trusted(p,stage)
   if digest(p)!=r['sha256']:raise ValueError('candidate_changed')
 return rows

def guards(manifest,root):
 for r in manifest['unchangedRequired']:
  p=at(root,r['path']);trusted(p,root)
  if digest(p)!=r['sha256']:raise ValueError('protected_file_changed:'+r['path'])
 if at(root,'/var/lib/fs-dashboard-release/pending.json').exists() or at(root,'/var/backups/fs-navigation-native-20261006/pending.json').exists():raise ValueError('peer_publication_pending')

def pending(root):return at(root,BACKUPS+'/pending.json')
def runtime(argv):
 p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=40)
 if p.returncode:raise RuntimeError('runtime_failed:'+argv[0]+':'+p.stderr[-500:])

def inspect(manifest,stage,root=Path('/')):
 rows=validate(manifest,stage);guards(manifest,root)
 if pending(root).exists():raise ValueError('unresolved_static_publication')
 for r in rows:
  p=at(root,r['target']);trusted(p,root)
  if digest(p)!=r['beforeSha256']:raise ValueError('target_baseline_changed:'+r['target'])
 return {'status':'inspected','writes':0,'files':len(rows)}

def write_journal(b,folder,j):b.atomic(folder/'journal.json',json.dumps(j,ensure_ascii=False,indent=2).encode(),0o600)
def current(j,root):
 guards(j['manifest'],root)
 for r in j['files']:
  p=at(root,r['target']);trusted(p,root)
  if digest(p) not in ({r['beforeSha256'],r['sha256']} if r['intent'] else {r['beforeSha256']}):raise ValueError('peer_drift:'+r['target'])

def restore(b,folder,j,root):
 mark=pending(root)
 if mark.exists() and json.loads(mark.read_text()).get('backup')!=str(folder):raise ValueError('peer_pending')
 validate(j['manifest'],None);current(j,root)
 mutable=[r for r in j['files'] if r['target'] in (FRAGMENT,HUB)]
 for r in mutable:
  p=folder/'original'/Path(r['candidate']).name;trusted(p,root)
  if digest(p)!=r['beforeSha256']:raise ValueError('backup_drift')
 for r in reversed(mutable):
  current(j,root)
  if r['intent']:b.atomic(at(root,r['target']),(folder/'original'/Path(r['candidate']).name).read_bytes(),r['mode'])
 if j.get('activationAttempted'):runtime(['nginx','-t']);runtime(['systemctl','reload','nginx'])
 if any(digest(at(root,r['target']))!=r['beforeSha256'] for r in mutable):raise ValueError('rollback_readback')
 j['status']='rolled_back_immutable_retained';write_journal(b,folder,j)
 if mark.exists():mark.unlink();b.directory_sync(mark.parent)

def apply(manifest,stage,raw,approval,root=Path('/')):
 if sha(raw)!=approval:raise ValueError('reviewed_manifest_sha_required')
 b=base()
 with b.locks(root):
  inspect(manifest,stage,root)
  folder=at(root,BACKUPS+'/'+manifest['releaseId']);trusted(folder,root)
  if folder.exists():raise ValueError('backup_exists_do_not_replay')
  folder.mkdir(parents=True,mode=0o700);b.directory_sync(folder.parent)
  b.atomic(folder/'approved-manifest.json',raw,0o600)
  rows=[]
  for r in manifest['files']:
   p=at(root,r['target']);item=dict(r,mode=stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644,intent=False);rows.append(item)
   if r['target'] in (FRAGMENT,HUB):
    data=p.read_bytes()
    if sha(data)!=r['beforeSha256']:raise ValueError('backup_cas')
    b.atomic(folder/'original'/Path(r['candidate']).name,data,0o600)
  j={'manifest':manifest,'approvedManifestSha256':approval,'files':rows,'status':'prepared','activationAttempted':False};write_journal(b,folder,j)
  b.atomic(pending(root),json.dumps({'backup':str(folder)}).encode(),0o600)
  try:
   for r in rows:
    current(j,root);p=at(root,r['target']);data=(stage/r['candidate']).read_bytes()
    if digest(p)!=r['beforeSha256'] or sha(data)!=r['sha256']:raise ValueError('before_write_cas')
    r['intent']=True;write_journal(b,folder,j);b.atomic(p,data,r['mode'])
   runtime(['nginx','-t']);j['activationAttempted']=True;write_journal(b,folder,j)
   current(j,root);runtime(['systemctl','reload','nginx']);current(j,root)
   if any(digest(at(root,r['target']))!=r['sha256'] for r in rows):raise ValueError('independent_readback')
   j['status']='applied_awaiting_browser_acceptance';write_journal(b,folder,j);pending(root).unlink();b.directory_sync(pending(root).parent)
  except Exception:
   restore(b,folder,j,root);raise
 return {'status':j['status'],'backup':str(folder)}

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['inspect','apply','rollback']);p.add_argument('--approved-manifest-sha');p.add_argument('--backup',type=Path);a=p.parse_args()
 if os.geteuid()!=0:raise ValueError('root_required')
 if a.action=='rollback':
  if not a.backup or a.backup.parent!=Path(BACKUPS):raise ValueError('fixed_backup_namespace')
  raw=(a.backup/'approved-manifest.json').read_bytes();j=json.loads((a.backup/'journal.json').read_text())
  if sha(raw)!=a.approved_manifest_sha or json.loads(raw)!=j['manifest']:raise ValueError('rollback_manifest')
  b=base()
  with b.locks(Path('/')):restore(b,a.backup,j,Path('/'))
  out={'status':'rolled_back_immutable_retained'}
 else:
  raw=(HERE/'contract.json').read_bytes();m=json.loads(raw)
  out=inspect(m,HERE) if a.action=='inspect' else apply(m,HERE,raw,a.approved_manifest_sha)
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()

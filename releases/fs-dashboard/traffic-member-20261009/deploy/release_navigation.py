"""Reviewed static navigation release only. Default inspection never writes.

Linux apply/rollback use exact target allowlist, manifest approval SHA, shared
gateway lock, per-file CAS, durable backups and rollback of this release only.
Permission scope changes exactly eight auth/taskboard assets and restarts those
two services. SQLite backups remain server-private; rollback never restores data.
Legacy rollback is refused after the first module-permission save.
"""
import argparse, contextlib, hashlib, json, os, re, stat, subprocess, tempfile, sqlite3, time, urllib.request
from pathlib import Path

HASH=re.compile(r'^[a-f0-9]{64}$')
RELATIVE={
 'fs-home/index.html','fs-home/navigation.js','fs-home/navigation.css','fs-home/navigation.json',
 'hubnav.js','hubnav.css',
 *(f'modules/{key}/index.html' for key in ('analytics','sports','arpg','collaboration','about')),
 *(f'analytics/{key}' for key in ('index.html','shell.js','shell.css','frame-theme.css')),
}
GREEN_TARGETS={
 'backend/taskboard_server.py':'/opt/mmoexp-taskboard/taskboard_server.py',
 'backend/green_plan.py':'/opt/mmoexp-taskboard/green_plan.py',
 'backend/green-plan-seed.json':'/opt/mmoexp-taskboard/green-plan-seed.json',
 'fs-home/navigation.json':'/var/www/dashboard/fs-home/navigation.json',
 **{'web/'+n:'/var/www/dashboard/tasks/green-plan/'+n for n in ('index.html','app.js','style.css','plan.html','plan.css','plan.js')},
}
GREEN_FIX_SCOPE='green-plan-review-fix-20261009'
GREEN_FIX_TARGETS={
 'auth/route-contract.json':'/opt/auth-portal/registration-runtime/20261007-ca6258ad/route-contract.json',
 'auth/native_access_policy.py':'/opt/auth-portal/registration-runtime/20261007-ca6258ad/vendor/native_access_policy.py',
 'auth/access_policy.py':'/opt/fs-access-policy/access_policy.py',
 **{'web/'+n:'/var/www/dashboard/tasks/green-plan/'+n for n in ('app.js','index.html')},
}
PERMISSION_SCOPE='registration-account-management-20261009'
PERMISSION_TARGETS={
 **{'permission-web/'+n:'/opt/auth-portal/registration-runtime/20261007-ca6258ad/web/'+n for n in ('app.js','index.html','access.css')},
 **{'permission-runtime/'+n:'/opt/auth-portal/registration-runtime/20261007-ca6258ad/'+n for n in ('runtime.py','module_permissions.py','consumer_seams.py','vendor/auth_candidate.py')},
 'permission-taskboard/taskboard_server.py':'/opt/mmoexp-taskboard/taskboard_server.py',
}
QUERY_SCOPE='fs-internal-query-api-20261009'
QUERY_TARGETS={
 'query_api.py':'/opt/fs-query-api/query_api.py',
 'clients.json':'/etc/fs-query-api/clients.json',
 'fs-query-api.service':'/etc/systemd/system/fs-query-api.service',
 'range.locations.conf':'/etc/nginx/fs-business-range.locations.conf',
}

TRAFFIC_SCOPE='fs-traffic-member-20261009'
TRAFFIC_TARGETS={'custom_range.py': '/opt/mmoexp-marketing/custom-range/custom_range.py', 'range_api.py': '/opt/mmoexp-marketing/custom-range/range_api.py', 'session/admin_links.py': '/opt/fc27-cloud/marketing-session-20261009/admin_links.py', 'session/p2pah_session_service.py': '/opt/fc27-cloud/marketing-session-20261009/p2pah_session_service.py', 'session/Dockerfile.session': '/opt/fc27-cloud/marketing-session-20261009/Dockerfile.session', 'fs-marketing-range.service': '/etc/systemd/system/fs-marketing-range.service', 'fc27-p2pah-session.service': '/etc/systemd/system/fc27-p2pah-session.service', 'traffic-auth/runtime.py': '/opt/auth-portal/registration-runtime/20261007-ca6258ad/runtime.py', 'traffic-auth/route-contract.json': '/opt/auth-portal/registration-runtime/20261007-ca6258ad/route-contract.json'}

def expected_files(manifest):
 if manifest.get("scope")==TRAFFIC_SCOPE:return set(TRAFFIC_TARGETS)
 if manifest.get("scope")==QUERY_SCOPE:return set(QUERY_TARGETS)
 if manifest.get('scope')==PERMISSION_SCOPE:return set(PERMISSION_TARGETS)
 if manifest.get('scope')==GREEN_FIX_SCOPE:return set(GREEN_FIX_TARGETS)
 return set(GREEN_TARGETS) if manifest.get('scope')=='green-plan-20261009' else RELATIVE

def target_for(rel):
 if rel in TRAFFIC_TARGETS:return TRAFFIC_TARGETS[rel]
 if rel in QUERY_TARGETS:return QUERY_TARGETS[rel]
 if rel in PERMISSION_TARGETS:return PERMISSION_TARGETS[rel]
 if rel in GREEN_FIX_TARGETS:return GREEN_FIX_TARGETS[rel]
 if rel in GREEN_TARGETS:return GREEN_TARGETS[rel]
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
 expected=expected_files(manifest)
 if manifest.get('schemaVersion')!=1 or {f.get('candidate') for f in files}!=expected or len(files)!=len(expected):raise ValueError('manifest must contain the exact approved scope')
 for row in files:
  rel=row['candidate'];src=stage/'candidate'/rel
  if row.get('target')!=target_for(rel) or not HASH.fullmatch(row.get('sha256','')):raise ValueError('invalid target or hash')
  if row.get('beforeSha256') is not None and not HASH.fullmatch(row['beforeSha256']):raise ValueError('invalid baseline hash')
  if manifest.get('scope')==GREEN_FIX_SCOPE and row.get('beforeSha256') is None:raise ValueError('review-fix existing target baseline required')
  if manifest.get('scope')==PERMISSION_SCOPE and rel!='permission-runtime/module_permissions.py' and row.get('beforeSha256') is None:raise ValueError('existing permission target baseline required')
  if manifest.get('scope')=='green-plan-20261009' and rel in ('backend/taskboard_server.py','fs-home/navigation.json') and row.get('beforeSha256') is None:raise ValueError('existing green-plan consumer baseline required')
  if src.is_symlink() or (stage/'candidate').resolve() not in src.resolve().parents:raise ValueError('candidate escaped stage')
  if digest(src)!=row['sha256']:raise ValueError('staged candidate SHA differs from reviewed manifest')
 if manifest.get('scope')==GREEN_FIX_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')!={'ActiveState':'active'}:raise ValueError('review-fix requires active auth service without PID pinning')
 if manifest.get('scope')==PERMISSION_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')!={'ActiveState':'active'}:raise ValueError('permission release requires active auth service')
 if manifest.get('scope')==QUERY_SCOPE:
  for row in files:
   if row['candidate']=='range.locations.conf':
    if not HASH.fullmatch(row.get('beforeSha256') or ''):raise ValueError('existing range route baseline required')
   elif row.get('beforeSha256') is not None:raise ValueError('first API release requires absent targets')
  clients=json.loads((stage/'candidate/clients.json').read_text())['clients']
  if len(clients)!=1 or clients[0]['id']!='dy-all-projects' or clients[0]['owner']!='DY' or clients[0]['includeProfit'] is not True or not HASH.fullmatch(clients[0]['tokenSha256']):raise ValueError('DY exact scope required')
  if set(clients[0]['projects'])!={'AION2','CFB27','D4','FC26','FC27','MLB26','MMOEXP','NBA2K27','NFL27','POE2'}:raise ValueError('project scope differs')
 if manifest.get('scope')==TRAFFIC_SCOPE:
  if manifest.get('sessionBaseImage')!='sha256:42d53d8c606491685f8a87db7bf6b0d1010c855464c37b8e37e7bbd45dd1dcda':raise ValueError('session image contract differs')
  for row in files:
   existing=row['candidate'] in ('fc27-p2pah-session.service','traffic-auth/runtime.py','traffic-auth/route-contract.json')
   if existing != (row.get('beforeSha256') is not None):raise ValueError('traffic first release target baseline differs')
 protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}
 if not HASH.fullmatch(protected.get('/var/www/dashboard/index.html','')):raise ValueError('protected business HTML SHA is required')
 return files
def guards(manifest,root):
 if manifest.get('scope')==TRAFFIC_SCOPE:
  actual=subprocess.check_output(['docker','image','inspect','-f','{{.Id}}','fc27-cloud-session:1'],universal_newlines=True).strip()
  if actual!=manifest['sessionBaseImage']:raise ValueError('session base image drift')

 for unit,expected in manifest.get('runtimeRequired',{}).items():
  if not re.fullmatch(r'[A-Za-z0-9@_.-]+\.(service|timer)',unit) or unit=='mmoexp-taskboard.service':raise ValueError('invalid protected unit')
  r=subprocess.run(['systemctl','show',unit,'--no-pager']+[v for k in expected for v in ('-p',k)],stdout=subprocess.PIPE,check=True,universal_newlines=True)
  actual=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
  if actual!=expected:raise ValueError('protected unit changed: '+unit)
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
def rollback_credentials(backup,journal,approved_sha):
 no_target_link(backup/'approved-manifest.json')
 payload=(backup/'approved-manifest.json').read_bytes()
 if not HASH.fullmatch(approved_sha or '') or hashlib.sha256(payload).hexdigest()!=approved_sha or journal['approvedManifestSha256']!=approved_sha:raise ValueError('wrong release approval SHA')
 manifest=json.loads(payload)
 if journal['manifest']!=manifest:raise ValueError('journal manifest differs from approved bytes')
 files=manifest['files']
 expected=expected_files(manifest)
 if manifest.get('schemaVersion')!=1 or {r['candidate'] for r in files}!=expected or len(files)!=len(expected):raise ValueError('rollback manifest scope differs')
 if len(journal['files'])!=len(files) or {r['candidate'] for r in journal['files']}!=expected:raise ValueError('rollback journal scope differs')
 approved={r['candidate']:r for r in files}
 for row in journal['files']:
  original=approved[row['candidate']]
  if any(row.get(k)!=v for k,v in original.items()) or row['target']!=target_for(row['candidate']):raise ValueError('rollback target differs from approved manifest')
  if not HASH.fullmatch(row['sha256']) or (row['beforeSha256'] is not None and not HASH.fullmatch(row['beforeSha256'])):raise ValueError('invalid rollback hash')
  if manifest.get('scope')==GREEN_FIX_SCOPE and row['beforeSha256'] is None:raise ValueError('review-fix rollback baseline required')

def rollback_journal(backup,journal,root):
 rollback_credentials(backup,journal,journal['approvedManifestSha256'])
 if journal['manifest'].get('scope')==PERMISSION_SCOPE:
  path=rooted(root,'/opt/auth-portal/data/registration-approval/registration.sqlite3');no_target_link(path)
  with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
   if db.execute('PRAGMA user_version').fetchone()[0]!=3 or db.execute("SELECT 1 FROM audit WHERE action='permissions' LIMIT 1").fetchone():
    raise ValueError('module permissions are active; legacy rollback refused, use schema4-compatible recovery; preserve database and checkpoint')
 rows=[]
 # Validate the entire release before restoring anything; unrelated runtime/files
 # are release preconditions, not permission to block restoring our exact code.
 for row in journal['files']:
  path=rooted(root,row['target']);no_target_link(path)
  sha=digest(path)
  if row.get('intent'):
   if sha not in (row['sha256'],row['beforeSha256']):raise ValueError('rollback intent target drift; preserve all files for manual review')
   if sha==row['sha256']:rows.append(row)
   elif row.get('written') and not row.get('rollbackIntent'):raise ValueError('rollback CAS drift; preserve for manual review: '+row['target'])
  elif row.get('written'):raise ValueError('written target lacks durable intent')
  if row['beforeSha256'] is not None:
   saved=backup/'files'/row['candidate'];no_target_link(saved)
   if digest(saved)!=row['beforeSha256']:raise ValueError('rollback backup SHA mismatch')
 for row in reversed(rows):
  path=rooted(root,row['target'])
  payload=None
  if row['beforeSha256'] is not None:
   payload=(backup/'files'/row['candidate']).read_bytes()
   if hashlib.sha256(payload).hexdigest()!=row['beforeSha256']:raise ValueError('rollback backup changed after validation')
  row['rollbackIntent']=True;journal_write(backup,journal)
  no_target_link(path)
  if digest(path)!=row['sha256']:raise ValueError('rollback target changed after validation')
  if payload is None:
   atomic(backup/'removed-new-files'/row['candidate'],path.read_bytes(),0o600)
   if digest(path)!=row['sha256']:raise ValueError('new file changed before removal')
   path.unlink();directory_sync(path.parent)
  else:atomic(path,payload,row['beforeMode'])
  row['written']=False;journal_write(backup,journal)
 journal['status']='rolled-back';journal_write(backup,journal)

def db_state(root):
 path=rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db')
 with contextlib.closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as conn:
  names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'green_%' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
  counts={name:conn.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
  members=conn.execute('SELECT * FROM members ORDER BY username').fetchall()
  return dict(counts=counts,membersSha256=hashlib.sha256(json.dumps(members,ensure_ascii=False,default=str).encode()).hexdigest())
def restart_taskboard():
 subprocess.run(['systemctl','restart','mmoexp-taskboard.service'],check=True)
 subprocess.run(['systemctl','is-active','--quiet','mmoexp-taskboard.service'],check=True)
 for attempt in range(50):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8932/health',timeout=1) as response:
    if response.status==200:return
  except OSError:pass
  time.sleep(0.1)
 raise ValueError('taskboard health unavailable after restart')
def restart_query():
 unit=Path('/etc/systemd/system/fs-query-api.service')
 if not unit.exists():
  subprocess.run(['systemctl','stop','fs-query-api.service'],check=False)
  subprocess.run(['systemctl','disable','fs-query-api.service'],check=False)
  subprocess.run(['systemctl','daemon-reload'],check=True)
 else:
  subprocess.run(['systemctl','daemon-reload'],check=True)
  subprocess.run(['nginx','-t'],check=True)
  subprocess.run(['systemctl','start','fs-query-api.service'],check=True)
  ready=False
  for attempt in range(50):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8933/api/fs/v1/profiles',timeout=1):raise ValueError('anonymous API allowed')
   except urllib.error.HTTPError as error:
    if error.code!=401:raise ValueError('unexpected query service response')
    ready=True;break
   except OSError:time.sleep(0.1)
  if not ready:raise ValueError('query API unavailable')
  subprocess.run(['systemctl','enable','fs-query-api.service'],check=True)
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)

def restart_traffic(manifest):
 source=Path('/opt/fc27-cloud/marketing-session-20261009')
 if (source/'Dockerfile.session').exists():
  subprocess.run(['docker','build','--network','none','--pull=false','-f',str(source/'Dockerfile.session'),'-t','fc27-cloud-session:traffic-20261009-ec4c7ba41c3c',str(source)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  output=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','sha256sum','fc27-cloud-session:traffic-20261009-ec4c7ba41c3c','/usr/local/bin/p2pah_session_service.py','/usr/local/bin/admin_links.py'],universal_newlines=True)
  expected={row['sha256'] for row in manifest['files'] if row['candidate'] in ('session/p2pah_session_service.py','session/admin_links.py')}
  if {line.split()[0] for line in output.splitlines()}!=expected:raise ValueError('built session source SHA differs')
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for unit in ('auth-portal.service','fc27-p2pah-session.service'):
  subprocess.run(['systemctl','restart',unit],check=True)
  subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
 if Path('/etc/systemd/system/fs-marketing-range.service').exists():
  subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True)
  subprocess.run(['systemctl','enable','fs-marketing-range.service'],check=True)
 else:
  subprocess.run(['systemctl','stop','fs-marketing-range.service'],check=False)
  subprocess.run(['systemctl','disable','fs-marketing-range.service'],check=False)
 for url,expected in [('http://127.0.0.1:8895/verify',401),('http://127.0.0.1:8767/health',200)]:
  ready=False
  for attempt in range(120):
   try:
    with urllib.request.urlopen(url,timeout=2) as response:code=response.status
   except urllib.error.HTTPError as error:code=error.code;error.close()
   except OSError:code=None
   if code==expected:ready=True;break
   time.sleep(1)
  if not ready:raise ValueError('existing service health failed after traffic release')

def restart_for(manifest):
 if manifest.get("scope")==TRAFFIC_SCOPE:restart_traffic(manifest);return
 if manifest.get("scope")==QUERY_SCOPE:restart_query();return
 if manifest.get('scope') in (GREEN_FIX_SCOPE,PERMISSION_SCOPE):
  subprocess.run(['systemctl','restart','auth-portal.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','auth-portal.service'],check=True)
  for attempt in range(50):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8895/verify',timeout=1) as response:raise ValueError('anonymous auth verify unexpectedly allowed')
   except urllib.error.HTTPError as error:
    if error.code==401:break
    raise ValueError('anonymous auth verify must return 401') from error
   except OSError:
    if attempt==49:raise ValueError('auth verify unavailable after restart')
    time.sleep(0.1)
 if manifest.get('scope') in ('green-plan-20261009',GREEN_FIX_SCOPE,PERMISSION_SCOPE):restart_taskboard()

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
  green=manifest.get('scope') in ('green-plan-20261009',GREEN_FIX_SCOPE,PERMISSION_SCOPE)
  if green:
   journal['databaseBefore']=db_state(root)
   source=rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db')
   saved=backup/'taskboard-private.sqlite3'
   with contextlib.closing(sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True)) as src, contextlib.closing(sqlite3.connect(str(saved))) as dst:src.backup(dst)
   os.chmod(saved,0o600);journal_write(backup,journal)
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
   if manifest.get('scope') in (QUERY_SCOPE,TRAFFIC_SCOPE):restart_for(manifest)
   if green:
    restart_for(manifest)
    journal['databaseAfter']=db_state(root)
    if journal['databaseAfter']!=journal['databaseBefore']:raise ValueError('Existing database tables/members changed during initialization')
   if any(digest(rooted(root,row['target']))!=row['sha256'] for row in journal['files']):raise ValueError('post-release SHA mismatch')
   journal['status']='applied-awaiting-actual-http-role-acceptance';journal_write(backup,journal)
  except Exception as error:
   # The rename may have succeeded before a later fsync/journal error.
   for row in journal['files']:
    if row.get('intent') and digest(rooted(root,row['target']))==row['sha256']:row['written']=True
   journal['failure']=str(error)
   try:journal_write(backup,journal)
   except OSError:pass
   rollback_journal(backup,journal,root)
   if green or manifest.get('scope') in (QUERY_SCOPE,TRAFFIC_SCOPE):restart_for(manifest)
   raise
  return dict(backup=str(backup),status=journal['status'],staticFiles=len(files),businessWorkerTimerActions=0)
def rollback(backup,approved_sha,root=Path('/')):
 with locks(root):
  no_target_link(backup/'journal.json')
  journal=json.loads((backup/'journal.json').read_text())
  rollback_credentials(backup,journal,approved_sha)
  rollback_journal(backup,journal,root)
  restart_for(journal['manifest'])
 return dict(status='rolled-back',backup=str(backup),businessWorkerTimerActions=0)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply','rollback'],nargs='?',default='inspect');parser.add_argument('--manifest',type=Path,default=Path(__file__).parent/'approved-manifest.json');parser.add_argument('--approved-manifest-sha');parser.add_argument('--release-id');parser.add_argument('--backup',type=Path)
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

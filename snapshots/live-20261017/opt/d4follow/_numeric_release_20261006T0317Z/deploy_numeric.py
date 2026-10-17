"""Authorized five-file release. No config/DB writes, no timer or cache operations.
Run only in reviewed staging; app/executor are gracefully stopped after idle gates.
Existing executor flock is acquired normally after its idle process exits; never cleared.
"""
import ast, datetime, fcntl, hashlib, json, os, pathlib, shutil, subprocess, sys, tarfile, time, urllib.request
ROOT=pathlib.Path('/opt/d4follow')
STAGE=pathlib.Path(__file__).resolve().parent
MANIFEST=json.loads((STAGE/'deploy-file-cas-manifest.json').read_text(encoding='utf-8-sig'))
FILES=MANIFEST['files']
ARCHIVE_SHA='b7d750b29ffce9f3a5ad769f3f8796ab18256813f300ebe2fbb94c3887bfcd99'
NOW=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
E={'startUTC':NOW(),'authorizedScope':'five numeric files; d4follow and p2pah-srv-exec only','events':[],'deployed':False,'rollback':None}
def persist():
 (STAGE/'release-result.json').write_text(json.dumps(E,ensure_ascii=True,indent=2))
def event(name,**kw):
 E['events'].append(dict(event=name,UTC=NOW(),**kw));persist()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
def cmd(args,timeout=30):
 p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if p.returncode:raise RuntimeError('command failed: '+args[0]+' '+args[1]+' rc='+str(p.returncode))
 return p.stdout.strip()
def state(unit):return cmd(['systemctl','show',unit,'--property=ActiveState','--value'])
def snapshot(script):
 p=subprocess.run(['/opt/d4follow/venv/bin/python',str(STAGE/script)],capture_output=True,text=True,timeout=70)
 if p.returncode:raise RuntimeError('reviewed snapshot failed: '+script)
 return json.loads(p.stdout)
def idle():
 q=snapshot('collect_queue_readonly.py');t=snapshot('read_task_status.py')
 E['latestQueue']=q;E['latestTasks']=t;persist()
 assert q['snapshotStable'] and not q['pendingDispatched'],'unstable or outstanding queue'
 assert q['srvExecState']['state']=='idle' and not q['srvExecState']['job'],'executor not idle'
 assert not q['containers']['out'],'writer container active'
 assert all(x.get('status')=='done' for x in t['tasks']) and t['tasks'],'known app task not terminal'
 all_tasks=snapshot('read_recent_task_status.py');E['retainedTaskAudit']=all_tasks;persist()
 assert not all_tasks['runningOrUnconfirmed'],'retained/manual task running or unconfirmed'
 for u in ['d4follow-collect.service','aion2-watch.service']:
  assert 'ActiveState=inactive' in q['units'][u]['out'],'producer active'
 # Unknown executor lock owners are never cleared or treated as stale.
 assert len(q['kernelLockOwners'])==1 and int(q['kernelLockOwners'][0]['pid'])==q['srvExecState']['pid'],'unexpected executor lock owner'
 return q
def cas(which):
 for f in FILES:
  assert sha(pathlib.Path(f['path']))==f[which],'CAS drift: '+f['path']
def untouched():
 rels=[p.relative_to(ROOT).as_posix() for p in ROOT.glob('*.py') if str(p) not in {f['path'] for f in FILES}]
 rels+=['_p2pah_srv/p2pah_local.py','_p2pah_srv/srv_run.py','templates/index.html']
 return {r:sha(ROOT/r) for r in sorted(set(rels))}
def config_stat():
 s=(ROOT/'config.json').stat();return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,inode=s.st_ino)
def health():
 assert state('d4follow.service')=='active' and state('p2pah-srv-exec.service')=='active'
 with urllib.request.urlopen('http://127.0.0.1:8900/',timeout=8) as r:
  assert r.status==200
  html=r.read(1024*1024).decode('utf-8','replace')
  assert 'RPG 游戏改价系统' in html
 return {'localRootHTTP':200,'existingDisplayNamePreserved':True}
def rollback(backups,installed,lock):
 # Services remain stopped here unless explicitly started at the very end.
 for f in FILES:
  n=pathlib.Path(f['path']).name;p=pathlib.Path(f['path'])
  expect=f['expectedAfterSHA256'] if n in installed else f['expectedBeforeSHA256']
  if sha(p)!=expect:raise RuntimeError('rollback CAS drift: '+n)
 for f in reversed(FILES):
  n=pathlib.Path(f['path']).name
  if n not in installed:continue
  p=pathlib.Path(f['path'])
  if f['action']=='add':p.unlink()
  else:
   tmp=p.with_name('.'+n+'.numeric-rollback-'+str(os.getpid()))
   shutil.copy2(backups/n,tmp);s=(backups/n).stat();os.chown(tmp,s.st_uid,s.st_gid);os.replace(tmp,p)
 cas('expectedBeforeSHA256');event('rollback-files-CAS-verified')
stopped=False;started=False;installed=[];exec_lock=None;deploy_lock=None
try:
 assert sys.version_info[:2]==(3,9),'wrong runtime'
 deploy_lock=(ROOT/'data/numeric-release.lock').open('a')
 fcntl.flock(deploy_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 event('release-lock-acquired')
 idle()
 cas('expectedBeforeSHA256')
 before_untouched=untouched();before_config=config_stat()
 E['untouchedBefore']=before_untouched;E['configMetadataBefore']=before_config
 a=STAGE/'five-files-reviewed.tar.gz';assert sha(a)==ARCHIVE_SHA
 candidate=STAGE/'candidate';candidate.mkdir(exist_ok=True)
 with tarfile.open(a) as tar:
  members=tar.getmembers();assert len(members)==5
  names={pathlib.Path(f['path']).name for f in FILES}
  for m in members:
   assert m.isfile() and m.name in names and '/' not in m.name
   (candidate/m.name).write_bytes(tar.extractfile(m).read())
 for f in FILES:
  p=candidate/pathlib.Path(f['path']).name
  assert sha(p)==f['expectedAfterSHA256'];ast.parse(p.read_text())
 backups=STAGE/'backup';backups.mkdir(exist_ok=False)
 metadata={}
 for f in FILES:
  p=pathlib.Path(f['path']);n=p.name
  if p.exists():
   s=p.stat();shutil.copy2(p,backups/n);os.chown(backups/n,s.st_uid,s.st_gid)
   assert sha(backups/n)==f['expectedBeforeSHA256']
   metadata[n]={'sha256':sha(p),'mode':s.st_mode & 0o7777,'uid':s.st_uid,'gid':s.st_gid}
  else:metadata[n]={'absentBefore':True}
 (backups/'metadata.json').write_text(json.dumps(metadata,indent=2))
 event('exact-backups-verified',metadata=metadata)
 idle();cas('expectedBeforeSHA256')
 assert config_stat()==before_config and untouched()==before_untouched,'protected baseline drift'
 # Only idle services, no stop/disable of producers or timers.
 cmd(['systemctl','stop','d4follow.service']);stopped=True
 # Application requests are now blocked. Check executor again before its normal stop.
 q=snapshot('collect_queue_readonly.py')
 assert q['snapshotStable'] and not q['pendingDispatched'] and q['srvExecState']['state']=='idle' and not q['containers']['out'],'race before executor stop'
 cmd(['systemctl','stop','p2pah-srv-exec.service'])
 exec_lock=(ROOT/'data/srv_exec.lock').open('r+')
 fcntl.flock(exec_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 event('idle-services-stopped-existing-lock-acquired-normally')
 cas('expectedBeforeSHA256');assert untouched()==before_untouched and config_stat()==before_config
 # Helper first, then dependent callers; no whole-directory overwrite.
 order=sorted(FILES,key=lambda f:0 if f['action']=='add' else 1)
 for f in order:
  p=pathlib.Path(f['path']);assert sha(p)==f['expectedBeforeSHA256']
  src=candidate/p.name;tmp=p.with_name('.'+p.name+'.numeric-release-'+str(os.getpid()))
  shutil.copyfile(src,tmp)
  if f['action']=='modify':s=p.stat();os.chmod(tmp,s.st_mode & 0o7777);os.chown(tmp,s.st_uid,s.st_gid)
  else:s=(ROOT/'core_gold.py').stat();os.chmod(tmp,s.st_mode & 0o7777);os.chown(tmp,s.st_uid,s.st_gid)
  assert sha(tmp)==f['expectedAfterSHA256'];os.replace(tmp,p);installed.append(p.name)
  event('file-installed',path=f['path'],sha256=sha(p))
 cas('expectedAfterSHA256');assert untouched()==before_untouched and config_stat()==before_config
 event('five-file-and-protected-baseline-verified')
 exec_lock.close();exec_lock=None
 cmd(['systemctl','start','d4follow.service']);cmd(['systemctl','start','p2pah-srv-exec.service']);started=True
 time.sleep(3);E['health']=health()
 E['postUnits']={u:cmd(['systemctl','show',u,'--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp']) for u in ['d4follow.service','p2pah-srv-exec.service']}
 cas('expectedAfterSHA256');assert untouched()==before_untouched and config_stat()==before_config
 E['deployed']=True;event('release-completed-no-price-test')
except Exception as ex:
 E['errorClass']=type(ex).__name__;E['error']=str(ex)
 if installed and not started:
  try:rollback(backups,installed,exec_lock);E['rollback']='five-file CAS restored'
  except Exception as rx:E['rollback']='BLOCKED: '+str(rx)
 elif installed:
  try:
   q=snapshot('collect_queue_readonly.py');tasks=snapshot('read_recent_task_status.py')
   assert q['snapshotStable'] and not q['pendingDispatched'] and q['srvExecState']['state']=='idle' and not q['containers']['out'] and not tasks['runningOrUnconfirmed']
   assert all('ActiveState=inactive' in q['units'][u]['out'] for u in ['d4follow-collect.service','aion2-watch.service'])
   cas('expectedAfterSHA256')
   cmd(['systemctl','stop','d4follow.service'])
   q=snapshot('collect_queue_readonly.py')
   assert q['snapshotStable'] and not q['pendingDispatched'] and q['srvExecState']['state']=='idle' and not q['containers']['out']
   cmd(['systemctl','stop','p2pah-srv-exec.service'])
   exec_lock=(ROOT/'data/srv_exec.lock').open('r+')
   fcntl.flock(exec_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   rollback(backups,installed,exec_lock);E['rollback']='five-file CAS restored'
  except Exception as rx:E['rollback']='BLOCKED; fresh idle/CAS not proved: '+str(rx)
 if stopped and (not installed or E['rollback']=='five-file CAS restored'):
  if exec_lock:exec_lock.close();exec_lock=None
  try:cmd(['systemctl','start','d4follow.service']);cmd(['systemctl','start','p2pah-srv-exec.service']);E['servicesRestored']=True
  except Exception as sx:E['servicesRestoreError']=str(sx)
 event('release-stopped')
finally:
 if exec_lock:exec_lock.close()
 if deploy_lock:deploy_lock.close()
 E['endUTC']=NOW();persist()
 print(json.dumps(E,ensure_ascii=True))
sys.exit(0 if E['deployed'] else 2)

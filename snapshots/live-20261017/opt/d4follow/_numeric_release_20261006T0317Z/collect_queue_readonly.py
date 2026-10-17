"""No app imports/API calls. Hash/copy production DB into self-cleaning temp only.
Queries copy, never locks/opens production SQLite through sqlite3 or clears locks.
"""
import pathlib,json,sqlite3,hashlib,shutil,tempfile,subprocess,datetime,re,os
ROOT=pathlib.Path('/opt/d4follow');DATA=ROOT/'data';DB=DATA/'iggm_follow.db'
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def run(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=20);return {'code':p.returncode,'out':p.stdout.strip(),'err':p.stderr.strip()[:200]}
def fingerprint(p):
 if not p.is_file():return {'exists':False}
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 s=p.stat();return {'exists':True,'bytes':s.st_size,'sha256':h.hexdigest(),'mtime_ns':s.st_mtime_ns}
doc={'startUTC':now(),'productionSQLiteOpened':False,'productionAPIInvoked':False,'snapshotStable':False,'credentialsRead':False}
files=[DB,pathlib.Path(str(DB)+'-wal')]
if not DB.is_file():doc['blocked']='database not present'
elif sum(p.stat().st_size for p in files if p.exists())>512*1024*1024:doc['blocked']='snapshot exceeds reviewed 512MiB read budget'
elif pathlib.Path(str(DB)+'-journal').exists():doc['blocked']='rollback journal present; conservative snapshot rejected'
else:
 for attempt in range(3):
  before={p.name:fingerprint(p) for p in files}
  with tempfile.TemporaryDirectory(prefix='d4-queue-readonly-snapshot-') as td:
   target=pathlib.Path(td)/DB.name
   for p in files:
    if before[p.name]['exists']:shutil.copyfile(p,pathlib.Path(td)/p.name)
   copied={p.name:fingerprint(pathlib.Path(td)/p.name) for p in files}
   after={p.name:fingerprint(p) for p in files}
   stable=before==after and all(copied[p.name].get('sha256')==before[p.name].get('sha256') for p in files)
   if not stable:continue
   con=sqlite3.connect('file:'+str(target)+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
   con.execute('PRAGMA query_only=ON')
   groups=[dict(r) for r in con.execute("SELECT status,kind,COALESCE(exec_mode,'local') AS exec_mode,count(*) AS n FROM local_job GROUP BY status,kind,COALESCE(exec_mode,'local')")]
   cols={r[1] for r in con.execute('PRAGMA table_info(local_job)')}
   selected=['id','ts','kind','status','exec_mode','created_at','claimed_at','started_at','finished_at','attempts','result_json','log']
   assert all(x in cols for x in selected)
   pending=[];uncertain=[];failedCount=0;parseFail=0;total=0
   for row in con.execute('SELECT '+','.join(selected)+' FROM local_job ORDER BY ts DESC'):
    total+=1;r=dict(row);rawlog=r.pop('log') or '';rawres=r.pop('result_json');res=None
    try:res=json.loads(rawres) if rawres else None
    except (TypeError,ValueError):parseFail+=1
    reasons=[]
    if re.search(r'超时|timeout|timed out|被放弃|人工核对后台|未知结果|未确认|uncertain|unconfirmed',rawlog,re.I):reasons.append('timeout-or-unconfirmed-log-marker')
    if r['status']=='dispatched':reasons.append('dispatched-awaiting-terminal-ack')
    if r['status']=='done' and not rawres:reasons.append('done-without-result-json')
    if rawres and res is None:reasons.append('result-json-parse-failed')
    if r['status']=='failed':failedCount+=1
    if r['status'] in ['pending','dispatched']:pending.append(r)
    if reasons:
     markers=[]
     markerPatterns={'executor-abandoned':r'执行超时.{0,30}容器已被放弃','front-push-not-confirmed':r'未确认推送成功','unknown-result':r'未知结果','read-timeout':r'Read timed out|ReadTimeout','connect-timeout':r'ConnectTimeout','playwright-timeout':r'TimeoutError|Timeout \d+ms exceeded','generic-timeout':r'timeout|timed out|超时','unconfirmed':r'未确认|unconfirmed'}
     for name,pat in markerPatterns.items():
      if re.search(pat,rawlog,re.I):markers.append(name)
     brief={}
     if isinstance(res,dict):
      for k in ['ok','fail','noop','returncode','clearcache_ok','clearcache_wanted']:
       if isinstance(res.get(k),(bool,int,float,type(None))):brief[k]=res.get(k)
      brief['mismatchCount']=len(res.get('mismatch') or []) if isinstance(res.get('mismatch') or [],list) else None
      brief['jobCount']=len(res.get('jobs') or []) if isinstance(res.get('jobs') or [],list) else None
      for k in ['sync_price','log_price']:
       sub=res.get(k)
       if isinstance(sub,dict):brief[k]={f:sub.get(f) for f in ['ok','getweb','allserver']}
     uncertain.append(dict(r,reasons=reasons,resultPresent=bool(rawres),logMarkerClasses=markers,resultSummary=brief))
   agents=[]
   for row in con.execute('SELECT agent,last_seen,running FROM local_agent'):
    r=dict(row);r['agentSHA256']=hashlib.sha256(str(r.pop('agent')).encode()).hexdigest()[:16];agents.append(r)
   con.close()
   doc.update({'snapshotStable':True,'snapshotAttempt':attempt+1,'databaseFingerprint':before,'groups':groups,'totalJobs':total,'pendingDispatched':pending,'uncertainCount':len(uncertain),'uncertainLatest':uncertain[:30],'historicalFailedCount':failedCount,'resultParseFailureCount':parseFail,'localAgents':agents})
   break
 if not doc['snapshotStable']:doc['blocked']='source database/WAL changed during all snapshot attempts'
 doc['temporarySnapshotRemoved']=not pathlib.Path(td).exists()
state=DATA/'srv_exec.json'
if state.is_file():
 d=json.loads(state.read_text());doc['srvExecState']={k:d.get(k) for k in ['state','job','kind','mode','done','failed','ts','pid','started']}
 lr=d.get('last_result') or {};doc['srvExecLastResult']={k:lr.get(k) for k in ['job','kind','ok','sec','ts','rc','clearcache_ok']}
doc['offSwitchExists']=(DATA/'srv_exec_off').exists()
doc['lockFileExists']=(DATA/'srv_exec.lock').exists()
doc['lockOwners']=run(['lslocks','--noheadings','--output','PID,COMMAND,PATH'])
doc['lockOwners']['out']='\n'.join(x for x in doc['lockOwners']['out'].splitlines() if '/opt/d4follow' in x)
lock=DATA/'srv_exec.lock';doc['kernelLockOwners']=[]
if lock.exists():
 st=lock.stat();key='%02x:%02x:%d'%(os.major(st.st_dev),os.minor(st.st_dev),st.st_ino)
 for line in pathlib.Path('/proc/locks').read_text().splitlines():
  parts=line.split()
  if key in parts:doc['kernelLockOwners'].append({'kind':parts[1],'advisory':parts[2],'mode':parts[3],'pid':parts[4]})
doc['units']={u:run(['systemctl','show',u,'--property=ActiveState,SubState,MainPID,UnitFileState,ExecMainStartTimestamp,NextElapseUSecRealtime,LastTriggerUSec']) for u in ['d4follow.service','p2pah-srv-exec.service','d4follow-collect.timer','d4follow-collect.service','aion2-watch.timer','aion2-watch.service']}
doc['containers']=run(['docker','ps','--no-trunc','--format','{{.ID}}|{{.Image}}|{{.Names}}'])
doc['containers']['out']='\n'.join(x for x in doc['containers']['out'].splitlines() if 'p2pah-srv' in x)
# Parse known operational phrases only; never print original log/account/price text.
phrases={'auto-off':r'自动跟价.*(?:关|停)|自动跟价.*False','auto-on':r'自动跟价.*(?:开启|开\b)|自动跟价.*True','master-off':r'系统总开关.*(?:关|False)','master-on':r'系统总开关.*(?:开启|开\b|True)','pending-block':r'pending|未完成工单|待执行工单'}
doc['recentOperationalFlags']=[]
for name in ['auto_collect.log','service.log','srv_exec.log']:
 p=ROOT/'logs'/name
 if not p.is_file():continue
 with p.open('rb') as f:
  f.seek(max(0,p.stat().st_size-512*1024));text=f.read().decode('utf-8','replace')
 hits=[]
 for line in text.splitlines():
  flags=[k for k,pat in phrases.items() if re.search(pat,line,re.I)]
  if flags:
   ts=re.search(r'\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d',line)
   hits.append({'timestamp':ts.group(0) if ts else None,'flags':flags})
 doc['recentOperationalFlags'].append({'file':name,'lastFlags':hits[-10:]})
doc['configMasterAutoIntentionRead']=False
doc['intentionLimit']='No mixed credential config read; logs are historical signals, not exact current master/auto configuration.'
doc['codeSHA256']={}
for rel in ['app.py','core_g2g.py','core_gold.py','srv_exec.py','gold_numeric_guard.py','_p2pah_srv/p2pah_local.py','_p2pah_srv/srv_run.py']:
 p=ROOT/rel;doc['codeSHA256'][rel]=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
doc['image']=run(['docker','image','inspect','p2pah-srv:1','--format','{{.Id}}'])
doc['timerListing']=run(['systemctl','list-timers','--all','--no-pager','d4follow-collect.timer','aion2-watch.timer'])
doc['endUTC']=now()
print(json.dumps(doc,ensure_ascii=True))

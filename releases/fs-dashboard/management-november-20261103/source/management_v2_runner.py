"""Collect once/day through the deployed FS reader; Hermes scheduling is separate.
Manual execution is an explicit operator action. Scheduled execution never catches up by day.
"""
import argparse,contextlib,fcntl,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from management_facts import collect,CONTRACT,DATA_SCOPE,SH,stable,fingerprint
ROOT=Path('/var/lib/fs-boss-workspaces/management-v2')
PUBLIC=Path('/var/lib/fs-boss-workspaces/public/management-v2.json')
STATUS=Path('/var/lib/fs-boss-workspaces/public/management.status.json')
TARGETS=Path('/opt/fs-boss-workspaces/source/management/targets.json')
def atomic(path,data,mode=0o600):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.management-',dir=path.parent)
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(stable(data));f.flush();os.fsync(f.fileno())
  os.chmod(name,mode);os.replace(name,path)
  d=os.open(path.parent,os.O_RDONLY)
  try:os.fsync(d)
  finally:os.close(d)
 finally:
  if os.path.exists(name):os.unlink(name)
@contextlib.contextmanager
def lock(path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:yield False;return
  yield True
 finally:os.close(fd)
def run(*,manual=False,root=ROOT,public=PUBLIC,status=STATUS,targets=TARGETS,reader=None,clock=None,budget=14400):
 now=(clock() if clock else datetime.now(SH)).astimezone(SH);day=now.date().isoformat()
 if not manual and now.hour>=7:return {'status':'outside_nightly_window','mutations':False}
 root=Path(root);journal=root/'journal'/(day+'.json');cachefile=root/'daily-cache.json'
 with lock(root/'run.lock') as held:
  if not held:return {'status':'already_running'}
  target_data=json.loads(Path(targets).read_text('utf-8'));target_version=fingerprint(target_data)
  if journal.is_file():
   old=json.loads(journal.read_text('utf-8'))
   if old.get('phase')=='completed' and old.get('status')=='facts_ready':
    if old.get('dataScope')==DATA_SCOPE and old.get('targetVersion')==target_version and not (manual and old.get('fact_status')=='partial'):return {'status':'already_completed','snapshotId':old.get('snapshotId')}
    # Manual migration/partial recheck preserves the successful original receipt verbatim.
    if not manual:return {'status':'scope_upgrade_requires_manual','mutations':False}
    history=root/'journal'/'history'/(day+'-'+hashlib.sha256(journal.read_bytes()).hexdigest()+'.json')
    if not history.exists():
     history.parent.mkdir(parents=True,exist_ok=True)
     with history.open('xb') as f:f.write(journal.read_bytes());f.flush();os.fsync(f.fileno())
   elif old.get('phase')!='completed' or old.get('status') not in ('failed',):return {'status':'original_operation_unreconciled','mutations':False}
  deadline=now.replace(hour=4,minute=30,second=0,microsecond=0) if not manual else now.replace(hour=23,minute=50,second=0,microsecond=0)
  if not manual and now>=deadline:deadline=now.replace(hour=6,minute=10,second=0,microsecond=0)
  seconds=min(budget,max(0,(deadline-now).total_seconds()))
  if seconds<=0:return {'status':'collection_deadline','mutations':False}
  record={'schema_version':2,'kind':'management','dataScope':DATA_SCOPE,'day':day,'started_at':now.isoformat(),'targetVersion':target_version,'trigger':'manual' if manual else 'scheduled','phase':'collecting','status':'running','ai_status':'not_requested'}
  atomic(journal,record);atomic(status,record,0o644)
  try:
   data=json.loads(Path(targets).read_text('utf-8'));cache=json.loads(cachefile.read_text('utf-8')) if cachefile.exists() else {}
   if not isinstance(cache,dict):raise ValueError('cache_contract')
   if reader is None:
    from boss_daily import read_summary
    reader=lambda path:read_summary(path,deadline=deadline)
   facts=collect(now,data,reader,cache=cache,deadline_seconds=seconds)
   finished=clock() if clock else datetime.now(SH)
   if finished.astimezone(SH).date().isoformat()!=day or (not manual and finished.astimezone(SH).hour>=7):raise TimeoutError('nightly_deadline_exceeded')
   facts['collectionFinishedAt']=finished.isoformat();facts['analysis']={'status':'pending','businessDate':day,'validUntil':facts['validUntil'],'source':'Hermes scheduled once after facts are ready'}
   atomic(cachefile,cache)
   frozen=root/'facts'/(facts['snapshotId']+'.json')
   if frozen.exists() and frozen.read_text('utf-8')!=stable(facts):raise ValueError('immutable_snapshot_conflict')
   if not frozen.exists():atomic(frozen,facts)
   with lock(root/'publish.lock') as publishing:
    if not publishing:raise ValueError('publication_busy')
    atomic(public,facts,0o644)
   record.update(phase='completed',status='facts_ready',fact_status=facts['status'],snapshotId=facts['snapshotId'],finished_at=finished.isoformat(),ai_status='pending_hermes',error_code=None)
  except Exception as e:
   record.update(phase='completed',status='failed',fact_status='unavailable',error_code=str(e) if isinstance(e,(ValueError,TimeoutError)) else 'collection_failed',finished_at=(clock() if clock else datetime.now(SH)).isoformat())
  atomic(journal,record);atomic(status,record,0o644)
  return {k:v for k,v in record.items() if k not in ('started_at',)}
def main():
 p=argparse.ArgumentParser();p.add_argument('--manual',action='store_true');p.add_argument('--budget',type=int,default=14400);a=p.parse_args()
 if not 60<=a.budget<=21600:raise SystemExit('budget must be 60..21600 seconds')
 print(stable(run(manual=a.manual,budget=a.budget)))
if __name__=='__main__':main()

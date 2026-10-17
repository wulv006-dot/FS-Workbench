"""Prepared server-only daily pipeline; does not enable services or publish files."""
import argparse,fcntl,json,os,subprocess,sys,tempfile,datetime as dt
from pathlib import Path
ROOT=Path('/opt/mmoexp-marketing')

def atomic_record(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise ValueError('linked_nightly_record')
    fd,temporary=tempfile.mkstemp(prefix='.nightly-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            json.dump(value,out);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
        directory=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--trigger',choices=('manual','scheduled'),default='manual')
    args=parser.parse_args()
    civil=dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    deadline=civil.replace(hour=6,minute=59,second=0,microsecond=0) if args.trigger=='scheduled' else None
    if deadline is not None and (civil< civil.replace(hour=0,minute=10,second=0,microsecond=0) or civil>=deadline):
        print(json.dumps({'status':'outside_nightly_window','publication_performed':False}));return
    os.umask(0o077)
    if os.getenv('MMOEXP_MARKETING_LIVE')!='approved' or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')!='/etc/mmoexp-marketing/service-account.json':raise SystemExit('LIVE_DISABLED')
    lock=(ROOT/'data/verified-readonly/collector.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({'status':'skipped_existing_collection','publication_performed':False}));return
    journal=ROOT/'data/verified-readonly/nightly-runs'/(civil.date().isoformat()+'.json') if deadline is not None else None
    if journal is not None and journal.exists():
        previous=json.loads(journal.read_text('utf-8'))
        print(json.dumps({'status':previous.get('status','incomplete'),'day':civil.date().isoformat(),'same_day_replay_disabled':True,
                          'phase':previous.get('phase'),'publication_performed':False}));return
    statuses={};started=dt.datetime.now(dt.timezone.utc).isoformat()
    if journal is not None:atomic_record(journal,{'day':civil.date().isoformat(),'phase':'started','status':'incomplete','started_at_utc':started,'steps':{}})
    def run(command):
        if journal is not None:atomic_record(journal,{'day':civil.date().isoformat(),'phase':'step_pending','status':'incomplete',
                                                     'started_at_utc':started,'steps':dict(statuses),'pending_step':Path(command[1]).name})
        if deadline is None:return subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        remaining=(deadline-dt.datetime.now(dt.timezone.utc)).total_seconds()
        if remaining<=0:raise subprocess.TimeoutExpired(command,0)
        return subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=remaining)
    def terminal(error=None,published=False):
        record={'started_at_utc':started,'completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'steps':statuses,
                'credentials_copied':False,'publication_performed':published,'source_values_retained_on_failure':True,
                'trigger':args.trigger,'error_code':error,
                'schedule':{'timezone':'Asia/Shanghai','daily_time':'00:10','stop_at':'06:59','complete_before':'07:00','daytime_catchup':False}}
        (ROOT/'verification-20260930/integrated-run-record.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
        if journal is not None:atomic_record(journal,dict(record,day=civil.date().isoformat(),phase='completed',status='failed' if error else 'succeeded'))
    try:
        for filename in ['server_collect_verified.py','server_collect_selected_ads.py']:
            completed=run([sys.executable,str(ROOT/'deployment'/filename)])
            statuses[filename]=completed.returncode
        output=ROOT/'data/verified-readonly'
        completed=run([sys.executable,str(ROOT/'details/collect_details.py'),'--parent-lock-held'])
        statuses['collect_details.py']=completed.returncode
        completed=run([sys.executable,str(ROOT/'details/detail_model.py'),'--database',str(output/'marketing.db'),'--output',str(output/'marketing-details.json')])
        statuses['detail_model.py']=completed.returncode
        if completed.returncode:
            terminal('detail_model_failed');raise SystemExit(2)
        completed=run([sys.executable,str(ROOT/'dashboard_module/build_module.py'),'--snapshot',str(output/'marketing-data.json'),'--details',str(output/'marketing-details.json'),'--collection-record',str(ROOT/'verification-20260930/real-collection-record.json'),'--output',str(ROOT/'staged-marketing-module')])
        statuses['build_module.py']=completed.returncode
        published=False
        if completed.returncode==0 and os.getenv('MMOEXP_MARKETING_PUBLISH')=='approved':
            completed=run([sys.executable,str(ROOT/'deployment/server_publish_module.py')])
            statuses['server_publish_module.py']=completed.returncode;published=completed.returncode==0
        terminal('preparation_failed' if any(statuses.values()) else None,published)
        if any(statuses.values()):raise SystemExit(2)
    except subprocess.TimeoutExpired:
        statuses['nightly_deadline']=1
        terminal('nightly_deadline_exceeded');raise SystemExit(2)

if __name__=='__main__':main()

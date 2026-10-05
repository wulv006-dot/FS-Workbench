"""Prepared server-only daily pipeline; does not enable services or publish files."""
import fcntl,json,os,subprocess,sys,datetime as dt
from pathlib import Path
ROOT=Path('/opt/mmoexp-marketing')

def main():
    os.umask(0o077)
    if os.getenv('MMOEXP_MARKETING_LIVE')!='approved' or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')!='/etc/mmoexp-marketing/service-account.json':raise SystemExit('LIVE_DISABLED')
    lock=(ROOT/'data/verified-readonly/collector.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({'status':'skipped_existing_collection','publication_performed':False}));return
    statuses={};started=dt.datetime.now(dt.timezone.utc).isoformat()
    for filename in ['server_collect_verified.py','server_collect_selected_ads.py']:
        completed=subprocess.run([sys.executable,str(ROOT/'deployment'/filename)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        # Existing scripts already archive safe diagnostics. Avoid stdout/stderr auth leaks.
        statuses[filename]=completed.returncode
    output=ROOT/'data/verified-readonly'
    completed=subprocess.run([sys.executable,str(ROOT/'details/collect_details.py'),'--parent-lock-held'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    statuses['collect_details.py']=completed.returncode
    completed=subprocess.run([sys.executable,str(ROOT/'details/detail_model.py'),'--database',str(output/'marketing.db'),'--output',str(output/'marketing-details.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    statuses['detail_model.py']=completed.returncode
    if completed.returncode:
        print(json.dumps({'status':'detail_model_failed','publication_performed':False,'steps':statuses}));raise SystemExit(2)
    completed=subprocess.run([sys.executable,str(ROOT/'dashboard_module/build_module.py'),'--snapshot',str(output/'marketing-data.json'),'--details',str(output/'marketing-details.json'),'--collection-record',str(ROOT/'verification-20260930/real-collection-record.json'),'--output',str(ROOT/'staged-marketing-module')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    statuses['build_module.py']=completed.returncode
    published=False
    if completed.returncode==0 and os.getenv('MMOEXP_MARKETING_PUBLISH')=='approved':
        completed=subprocess.run([sys.executable,str(ROOT/'deployment/server_publish_module.py')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        statuses['server_publish_module.py']=completed.returncode;published=completed.returncode==0
    record={'started_at_utc':started,'completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'steps':statuses,'credentials_copied':False,'publication_performed':published,'source_values_retained_on_failure':True,'schedule':{'timezone':'Asia/Shanghai','daily_time':'09:00'}}
    (ROOT/'verification-20260930/integrated-run-record.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
    if any(statuses.values()):raise SystemExit(2)

if __name__=='__main__':main()

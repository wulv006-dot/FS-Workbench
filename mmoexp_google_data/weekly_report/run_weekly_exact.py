"""Server weekly orchestration through the existing bounded exact-range service."""
import argparse,datetime as dt,fcntl,json,sys
from pathlib import Path
from types import SimpleNamespace
import range_adapter as adapter
import weekly_report as w

ROOT=Path('/opt/mmoexp-weekly-report')
def emit(value):print(json.dumps(value,ensure_ascii=True),flush=True)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--week-start');parser.add_argument('--publish',action='store_true');parser.add_argument('--not-before');args=parser.parse_args()
    if args.not_before and w.now()<w.parse_time(args.not_before):emit({'status':'before_first_planned_run','firstPlannedAt':args.not_before});return
    p=w.period(args.week_start) if args.week_start else w.preceding_week(w.now())
    if w.parse_time(p['endExclusiveAt'])>w.now():raise SystemExit('WEEK_NOT_COMPLETE')
    lock=(ROOT/'report.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:emit({'status':'skipped_existing_generation'});return
    attempt={'startedAt':w.now().isoformat(),'period':p,'invocation':'explicit_historical_test' if args.week_start else 'weekly_schedule','productionPublished':False}
    try:
        _,base_ref=w.pointer(adapter.BASE);base=base_ref['snapshotId'];attempt['baseSnapshotId']=base
        current,attempt['currentRanges']=adapter.fetch_week(p,base,event=emit)
        previous_p=w.period((dt.date.fromisoformat(p['start'])-dt.timedelta(days=7)).isoformat())
        previous,attempt['previousRanges']=adapter.fetch_week(previous_p,base,event=emit)
        _,latest=w.pointer(adapter.BASE)
        if latest['snapshotId']!=base:raise ValueError('EXACT_RANGE_BASE_CHANGED')
        options=SimpleNamespace(publish=args.publish,as_of=None,week_start=p['start'],business_manifest=current,previous_business_manifest=previous,google_snapshot=Path('/var/www/mmoexp-marketing/current/data.json'),web=ROOT/'public')
        result=w.run(options);attempt.update(status='success',completedAt=w.now().isoformat(),productionPublished=args.publish)
        attempt['output']={key:value for key,value in result.items() if key!='report'}
        adapter.private_write(ROOT/'verification'/('run-'+p['id']+'.json'),w.encoded(attempt))
        if args.publish:w.atomic(ROOT/'public/attempt.json',w.encoded({'status':'success','checkedAt':attempt['completedAt'],'period':p,'reportId':result['reportId'],'invocation':attempt['invocation']}))
        emit(attempt)
    except Exception as error:
        # Do not print source errors, session contents or raw credential-bearing logs.
        code=str(error) if isinstance(error,ValueError) and str(error).replace('_','').isupper() else type(error).__name__.upper()
        attempt.update(status='failed_preserved_previous_report',completedAt=w.now().isoformat(),errorCode=code)
        adapter.private_write(ROOT/'verification'/('run-'+p['id']+'.json'),w.encoded(attempt))
        if args.publish:w.atomic(ROOT/'public/attempt.json',w.encoded({'status':'failed_preserved_previous_report','checkedAt':attempt['completedAt'],'errorCode':code,'period':p}))
        emit(attempt);raise SystemExit(2)
if __name__=='__main__':main()

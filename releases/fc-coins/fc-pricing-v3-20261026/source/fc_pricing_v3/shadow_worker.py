"""Independent read-only consumer of the production V3 outbox."""
import argparse
import json
from datetime import timedelta
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import logging
from pathlib import Path
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc_pricing_v3.simulation import LOCAL, Shadow
from fc_pricing_v3.financial import fingerprint,instant


PRODUCTION = Path('/var/lib/fc27-cloud/v3/shadow-readonly.sqlite3')
SHADOW = Path('/var/lib/fc-pricing-v3-shadow/shadow.sqlite3')
LOG = logging.getLogger('fc_pricing_v3.shadow')


def maintenance_cutoff(now):
    local = now.astimezone(LOCAL)
    if (local.hour, local.minute) < (0, 10):
        return None
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def tick(shadow, production_path, now, last_maintenance=None):
    result = shadow.consume(production_path)
    cutoff = maintenance_cutoff(now)
    if cutoff and cutoff != last_maintenance:
        if shadow.summary(cutoff):
            shadow.prune(now)
            last_maintenance = cutoff
    return result, last_maintenance


def validate_shadow_state(path):
    if os.name != 'posix' or Path(path) != SHADOW:
        return
    state = path.parent.stat()
    if (state.st_uid != os.geteuid() or state.st_gid != os.getegid() or
            state.st_mode & 0o7777 != 0o2750):
        raise RuntimeError('shadow_state_permissions_invalid')


@contextmanager
def single_consumer(path):
    if os.name != 'posix':
        yield
        return
    import fcntl
    with Path(path).open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('shadow_consumer_already_running') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_daily(production_path=PRODUCTION,shadow_path=SHADOW,date=None):
    validate_shadow_state(shadow_path)
    date=date or json.loads((Path(shadow_path).parent/'request.json').read_text())['local_date']
    start=datetime.fromisoformat(date).replace(tzinfo=LOCAL)
    stop=start+timedelta(days=1)
    if stop>datetime.now(timezone.utc):raise ValueError('shadow_day_not_closed')
    output=Path(shadow_path).parent/('daily-'+date+'.json')
    if output.exists():return json.loads(output.read_text())
    with single_consumer(Path(shadow_path).parent/'worker.lock'):
        shadow=Shadow(shadow_path)
        while True:
            result=shadow.consume(production_path,through=stop,include_histories=False)
            if result['status']!='processed':raise ValueError(result['status'])
            if result['events']<100:break
        records=[]
        with shadow.connect() as db:
            for raw, in db.execute('SELECT body FROM runs'):
                row=json.loads(raw)
                if row.get('as_of') and start<=instant(row['as_of'])<stop:
                    decision=row.get('result') or row.get('last_result') or {}
                    chosen=decision.get('selected') or {}
                    records.append(dict(snapshot_id=row.get('snapshot_id') or row.get('external_snapshot_id'),
                        as_of=row['as_of'],strategy=row.get('policy'),kind=row.get('simulation_kind'),
                        status=row.get('status') or decision.get('status'),action=chosen.get('action'),
                        prediction=chosen.get('score'),reason=row.get('reason')))
        def policy_summary(rows,mode):
            matching=[r for r in rows if r['strategy']==mode]
            latest=max(matching,key=lambda r:r['as_of'],default={})
            prediction=latest.get('prediction') or {}
            return dict(evaluated=sum(r['status']=='READY' for r in matching),gaps=sum(r['status']!='READY' for r in matching),latest_action=latest.get('action'),forecast={k:prediction.get(k) for k in ('revenue','contribution','absolute_forecast_available','elasticity')})
        by_period=[]
        for first in range(0,24,6):
            rows=[r for r in records if first<=instant(r['as_of']).astimezone(LOCAL).hour<first+6]
            by_period.append(dict(start_hour=first,end_hour=first+6,snapshots=len({r['snapshot_id'] for r in rows}),
                results={mode:policy_summary(rows,mode) for mode in ('daily','acquisition','backlog','flash_sale','revenue_sprint')}))
        report=dict(local_date=date,timezone='Asia/Shanghai',status='available' if records else 'no_stored_snapshots',
            periods=by_period,record_count=len(records),input_gaps=[r for r in records if r['status']=='INPUT_GAP'],
            production_write_performed=False,external_collection_performed=False,training_eligible=False,
            interpretation='saved period inputs; missing strategy inputs are gaps; predictions are scenarios, never realized causal effects',
            cursor=result['cursor'],records_sha256=fingerprint(records))
        temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(report),encoding='utf-8');temporary.replace(output)
        shadow.summary(stop);shadow.prune(datetime.now(timezone.utc))
        return report


def run_historical(production_path,shadow_path,request_id):
    validate_shadow_state(shadow_path)
    output=Path(shadow_path).parent/('history-'+request_id+'.json')
    if output.exists():return json.loads(output.read_text())
    with single_consumer(Path(shadow_path).parent/'worker.lock'):
        shadow=Shadow(shadow_path)
        while True:
            result=shadow.consume(production_path,historical_only=True)
            if result['status']!='processed':raise ValueError(result['status'])
            if result['events']<100:break
        with shadow.connect() as db:
            if not db.execute('SELECT 1 FROM history WHERE id=?',(request_id,)).fetchone():
                raise ValueError('shadow_original_history_result_missing')
        result.update(request_id=request_id,production_write_performed=False,external_collection_performed=False)
        temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(result),encoding='utf-8');temporary.replace(output)
        return result


def main():
    parser = argparse.ArgumentParser(description='FC Pricing V3 read-only shadow consumer')
    parser.add_argument('--production-db', type=Path, default=PRODUCTION)
    parser.add_argument('--shadow-db', type=Path, default=SHADOW)
    parser.add_argument('--once',action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    request=json.loads((args.shadow_db.parent/'request.json').read_text())
    if request.get('kind')=='historical':run_historical(args.production_db,args.shadow_db,request['request_id'])
    else:run_daily(args.production_db,args.shadow_db,request['local_date'])


if __name__ == '__main__':
    main()

"""One finite, resumable full-history read through the original Admin session and locks."""
from datetime import datetime, timedelta
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).with_name('source')))
from user_contract import TZ, stamp, digest
from user_jobs import atomic, SOURCE_LOCK
from user_lifecycle import covered
from user_runtime import load_store
from user_source import shared_sync


def months(now, floor):
    floor = stamp(floor)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while end > floor:
        start = end.replace(day=1)
        if start == end:
            start = (start-timedelta(days=1)).replace(day=1)
        start = max(start,floor)
        yield start, end
        end = start


def source_count(site, start, end):
    sys.path[:0] = ['/opt/sales-dashboard/collector', '/opt/fs-hermes-fc']
    import p2pah_auth as auth
    from channel_source import search
    session = auth.Session()
    try:
        token, _ = auth.admin_token_from_service()
        if not token:
            raise ValueError('shared_session_required')
        session.bind_admin_token(token); del token
        a, b = start.strftime('%Y-%m-%d %H:%M:%S'), (end-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        status, value = session.get_admin('/admin/order.Order/index', page=1, limit=1, order='id,desc',
                                         **search([('site_id','=',site),('paytime','RANGE',a+','+b)]))
        data = value.get('data') or {}
        if status != 200 or value.get('code') != 1 or type(data.get('total')) is not int or data['total'] < 0 or not isinstance(data.get('list'),list):
            raise ValueError('source_month_count_contract')
        if any(str(r.get('site_id')) != site or not a <= str(r.get('paytime')) <= b for r in data['list']):
            raise ValueError('source_month_range_contract')
        if data['total'] == 0 and data['list']:
            raise ValueError('source_month_empty_contract')
        return data['total']
    finally:
        session.close()


def run():
    store = load_store(); today = datetime.now(TZ).replace(hour=0,minute=0,second=0,microsecond=0)
    floor = stamp(store.config['history_backfill_start'])
    if floor.time() != datetime.min.time() or floor >= today:
        raise ValueError('closed_day_history_start_required')
    progress = store.root/'history-backfill.json'
    # Grow a separate work ledger so the last complete proof stays valid during extension.
    inventory_path = store.root/('history-backfill-inventory-'+floor.date().isoformat()+'.json')
    prior_inventory = store.root/'history-full-inventory.json'
    inventory = json.loads((inventory_path if inventory_path.exists() else prior_inventory).read_text('utf-8')) if inventory_path.exists() or prior_inventory.exists() else {}
    completed = source_rows = 0
    def save(status, **extra):
        atomic(progress,dict(status=status,target_start=floor.isoformat(),target_end_exclusive=today.isoformat(),completed_windows=completed,source_rows=source_rows,at=datetime.now(TZ).isoformat(),**extra))
    for site in store.config['sites']:
        for start,end in months(today,floor.isoformat()):
            key = site+':'+start.isoformat()+':'+end.isoformat()
            while key not in inventory:
                # Give the existing 03/18/33/48 job its original opportunity to run.
                if datetime.now(TZ).minute % 15 in (1,2,3,4) or subprocess.run(['systemctl','is-active','--quiet','fs-user-analytics.service']).returncode == 0:
                    time.sleep(2); continue
                with SOURCE_LOCK.open('a+b') as lock:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:time.sleep(2);continue
                    inventory[key] = source_count(site,start,end)
                    atomic(inventory_path,inventory)
            stop=end
            while stop > start:
                begin=start if inventory[key] == 0 else max(start,stop-timedelta(days=1))
                if covered(store.coverage(),[site],begin,stop):
                    stop=begin;continue
                if datetime.now(TZ).minute % 15 in (1,2,3,4) or subprocess.run(['systemctl','is-active','--quiet','fs-user-analytics.service']).returncode == 0:
                    time.sleep(2); continue
                with (store.root/'jobs.lock').open('a+b') as jobs_lock, SOURCE_LOCK.open('a+b') as source_lock:
                    try:
                        fcntl.flock(jobs_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        fcntl.flock(source_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:time.sleep(2);continue
                    save('running',start=begin.isoformat(),end_exclusive=stop.isoformat())
                    try:
                        receipts=shared_sync(store,site,begin.isoformat(),stop.isoformat()) if inventory[key] else [store.replace_window(site,begin.isoformat(),stop.isoformat(),[],datetime.now(TZ).isoformat(),reason='verified_empty_month_inventory')]
                    except Exception:
                        save('failed',start=begin.isoformat(),end_exclusive=stop.isoformat());raise
                completed+=1;source_rows+=sum(r['source_rows'] for r in receipts)
                save('running',start=begin.isoformat(),end_exclusive=stop.isoformat())
                print(json.dumps(dict(site=site,start=begin.isoformat(),end_exclusive=stop.isoformat(),data_version=store.revision(),source_rows=sum(r['source_rows'] for r in receipts))),flush=True)
                stop=begin;time.sleep(.5)
    first = floor.isoformat()
    if not covered(store.coverage(),list(store.config['sites']),stamp(first),today):
        raise ValueError('bounded_history_coverage_gap')
    inventory_hash = digest(inventory)
    inventory_file = 'history-inventory-'+inventory_hash+'.json'
    frozen_inventory = store.root/inventory_file
    if frozen_inventory.exists():
        if digest(json.loads(frozen_inventory.read_text('utf-8'))) != inventory_hash:
            raise ValueError('history_inventory_readback_mismatch')
    else:
        atomic(frozen_inventory,inventory)
    atomic(store.root/'history-coverage.json',dict(contract='fs-users-bounded-history-v1',start=first,end_exclusive=today.isoformat(),sites=sorted(store.config['sites']),inventory_sha256=inventory_hash,inventory_file=inventory_file,data_version=store.revision()))
    save('complete',start=first,end_exclusive=today.isoformat())


if __name__ == '__main__':
    run()

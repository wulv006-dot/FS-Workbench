"""One bounded reader, existing source lock, durable windows and independent daily state."""
import argparse
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from user_contract import TZ, canonical, stamp
from user_runtime import ROOT, load_store, CONFIG
from user_source import shared_sync

SOURCE_LOCK = Path('/var/lib/fs-channel-effects/collector.lock')


def atomic(path, value):
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(canonical(value)); output.flush(); os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def day_windows(start, end):
    current, end = stamp(start), stamp(end)
    if current >= end or end - current > timedelta(days=366) or current.time() != datetime.min.time() or end.time() != datetime.min.time():
        raise ValueError('complete_daily_range_required')
    while current < end:
        stop = min(current + timedelta(days=1), end)
        yield current.isoformat(), stop.isoformat()
        current = stop


def has_window(jobs, site, start, end):
    return any(j['site'] == site and j['state'] == 'complete' and stamp(j['start']) <= stamp(start) and stamp(end) <= stamp(j['end']) for j in jobs)


def synchronize_day(store, site, start, end, reader=shared_sync, lock_path=SOURCE_LOCK):
    # Never wait ahead of a foreground collector or hold its lock across history slices.
    with Path(lock_path).open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(status='deferred', reason='existing_source_busy', site=site, start=start, end_exclusive=end)
        receipts = reader(store, site, start, end)
    return dict(status='complete', site=site, start=start, end_exclusive=end, receipts=receipts)


def advance_day(store, now):
    from user_query import Service
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = Service(store, lambda *_: True, clock=lambda: now).query(
        dict(start=(end - timedelta(days=30)).isoformat(), end_exclusive=end.isoformat(), state_basis='period_end'), 'internal_daily_calculation')
    value = dict(day=end.date().isoformat(), snapshot_id=result['snapshot_id'], evidence_id=result['evidence_id'],
                 data_version=result['data_version'], observation_date=result['observation_date'],
                 lifecycle_cutoff=end.isoformat(), executed_at=now.isoformat(), source_collection=False,
                 trigger='systemd' if os.environ.get('FS_USER_ANALYTICS_TRIGGER') == 'systemd' or os.environ.get('INVOCATION_ID') else 'manual',
                 invocation_id=os.environ.get('INVOCATION_ID'),
                 stocks={key: result['metrics'][key] for key in ('known_pool', 'recent', 'silent', 'lost', 'long_lost', 'unverified')})
    previous = store.root / 'daily-state.json'
    if not previous.exists() or json.loads(previous.read_text('utf-8'))['day'] != value['day']:
        with (store.root / 'daily-transitions.jsonl').open('a', encoding='utf-8') as journal:
            os.chmod(journal.name, 0o600)
            journal.write(canonical(value) + '\n'); journal.flush(); os.fsync(journal.fileno())
    atomic(store.root / 'daily-state.json', value)
    return value


def backup(store, now):
    root = store.root / 'backups'
    root.mkdir(mode=0o700, exist_ok=True)
    destination = root / now.date().isoformat()
    if destination.exists():
        # Existing partial/unknown backups are evidence, never replace them on a retry.
        receipt = destination / 'manifest.json'
        if not receipt.is_file():
            raise ValueError('backup_outcome_requires_reconciliation')
        value = json.loads(receipt.read_text('utf-8'))
        for name, digest in value['sha256'].items():
            if hashlib.sha256((destination / name).read_bytes()).hexdigest() != digest:
                raise ValueError('backup_readback_mismatch')
        return value
    destination.mkdir(mode=0o700)
    store.backup(destination / 'customers.sqlite3')
    for name, raw in (('identity.key', store.key), ('config.json', canonical(store.config).encode())):
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
    value = dict(contract='fs-users-private-backup-v1', captured_at=now.isoformat(), data_version=store.revision(),
                 scope='same_host_recovery_copy', sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()})
    atomic(destination / 'manifest.json', value)
    return value


def tick_windows(store, now):
    jobs = store.coverage()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for site in store.config['sites']:
        yield site, midnight.isoformat(), now.replace(microsecond=0).isoformat(), 'today_overlap'
        yield site, (midnight - timedelta(days=1)).isoformat(), midnight.isoformat(), 'yesterday_reconciliation'
        complete = [j for j in jobs if j['site'] == site and j['state'] == 'complete' and stamp(j['end']) <= midnight]
        if complete:
            old = min(complete, key=lambda j: json.loads(j['body']).get('captured_at', ''))
            yield site, old['start'], old['end'], 'historical_refund_reconciliation'
            first = min(stamp(j['start']) for j in complete)
            yield site, (first - timedelta(days=1)).isoformat(), first.isoformat(), 'historical_backfill'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('sync', 'tick', 'backup'))
    parser.add_argument('--start'); parser.add_argument('--end')
    parser.add_argument('--site', default='266'); parser.add_argument('--recheck', action='store_true')
    args = parser.parse_args()
    store = load_store(); now = datetime.now(TZ)
    with (store.root / 'jobs.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"deferred","reason":"user_job_active"}'); return
        if args.action == 'backup':
            print(canonical(backup(store, now))); return
        if args.action == 'sync':
            if args.site not in store.config['sites'] or not args.start or not args.end or stamp(args.end) > now.replace(hour=0, minute=0, second=0, microsecond=0):
                raise ValueError('connected_closed_day_range_required')
            queue = [(args.site, a, b, 'initial_backfill') for a, b in day_windows(args.start, args.end)]
        else:
            advance_day(store, now)
            queue = list(tick_windows(store, now))
        for site, start, end, reason in queue:
            if stamp(start) >= stamp(end):
                continue
            jobs = store.coverage()
            if args.action == 'sync' and not args.recheck and has_window(jobs, site, start, end):
                print(canonical(dict(status='reused', site=site, start=start, end_exclusive=end)), flush=True); continue
            try:
                result = synchronize_day(store, site, start, end)
            except Exception as error:
                atomic(store.root / 'job-status.json', dict(status='failed', site=site, start=start, end_exclusive=end, reason=reason, error=str(error) if isinstance(error, RuntimeError) and str(error).startswith('user_source_window_failed:') else type(error).__name__, at=now.isoformat()))
                raise
            result.update(reason=reason, at=datetime.now(TZ).isoformat())
            atomic(store.root / 'job-status.json', result)
            print(canonical(result), flush=True)
            if result['status'] == 'deferred':
                return
        advance_day(store, datetime.now(TZ)); backup(store, now)


if __name__ == '__main__':
    main()

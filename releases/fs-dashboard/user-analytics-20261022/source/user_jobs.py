"""One bounded reader, existing source lock, durable windows and independent daily state."""
import argparse
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path
import tempfile

from user_contract import TZ, canonical, stamp
from user_runtime import ROOT, load_store, CONFIG
from user_source import shared_sync, shared_correct

SOURCE_LOCK = Path('/var/lib/fs-channel-effects/collector.lock')
# A due interval, not a promise that a busy/failed source has been refreshed.
# No source status is currently proven immutable, so history never freezes.
HISTORY_RECHECK_AFTER = timedelta(hours=24)
# Observed Admin work-in-progress labels; these affect priority, never validity.
FAST_REFRESH_STATUSES = frozenset(('11', '21', '31', '32', '33', '34', '80'))
TARGETED_GROUP_LIMIT = 200


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


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def backup_signature(destination):
    from user_store import safe
    receipt = destination / 'manifest.json'
    safe(receipt)
    with receipt.open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('backup_manifest_size')
    value = json.loads(raw)
    names = ('config.json', 'customers.sqlite3', 'identity.key')
    if set(value['sha256']) != set(names):
        raise ValueError('backup_manifest_files')
    signatures = {}
    for name in (*names, 'manifest.json'):
        path = destination / name
        safe(path)
        stat = path.stat()
        signatures[name] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    return dict(manifest_sha256=hashlib.sha256(raw).hexdigest(), files=signatures)


def backup(store, now):
    root = store.root / 'backups'
    root.mkdir(mode=0o700, exist_ok=True)
    destination = root / now.date().isoformat()
    if destination.exists():
        # Existing partial/unknown backups are evidence, never replace them on a retry.
        receipt = destination / 'manifest.json'
        if not receipt.is_file():
            raise ValueError('backup_outcome_requires_reconciliation')
        backup_signature(destination)
        value = json.loads(receipt.read_text('utf-8'))
        for name, digest in value['sha256'].items():
            if file_sha256(destination / name) != digest:
                raise ValueError('backup_readback_mismatch')
        return value
    destination.mkdir(mode=0o700)
    store.backup(destination / 'customers.sqlite3')
    for name, raw in (('identity.key', store.key), ('config.json', canonical(store.config).encode())):
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
    value = dict(contract='fs-users-private-backup-v1', captured_at=now.isoformat(), data_version=store.revision(),
                 scope='same_host_recovery_copy', sha256={p.name: file_sha256(p) for p in destination.iterdir()})
    atomic(destination / 'manifest.json', value)
    return value


def daily_backup_status(store, now):
    destination = store.root / 'backups' / now.date().isoformat()
    target = store.root / 'backup-status.json'
    previous = json.loads(target.read_text('utf-8')) if target.is_file() else {}
    if destination.exists() and not (destination / 'manifest.json').is_file():
        value = dict(status='requires_reconciliation', reason='backup_outcome_requires_reconciliation',
                     retryable=False, day=now.date().isoformat(), backup_directory=str(destination))
        if value != previous:
            atomic(target, value)
        return value
    signature = backup_signature(destination) if destination.exists() else None
    if (previous.get('day') == now.date().isoformat() and previous.get('status') == 'complete'
            and signature is not None and previous.get('signature') == signature):
        return previous
    receipt = backup(store, now)
    after = backup_signature(destination)
    if signature is not None and signature != after:
        raise ValueError('backup_changed_during_verification')
    value = dict(status='complete', day=now.date().isoformat(), receipt=receipt, signature=after)
    atomic(target, value)
    return value


def payment_day_watermarks(jobs, site, now):
    """Latest whole-day verification from real coverage, without changing jobs.

    A newer prefix cannot freshen an older day's uncovered tail. When several
    partial intervals cover a day, its watermark is the oldest necessary piece
    in the newest complete coverage, rather than the newest partial capture.
    A touched day without complete coverage has no watermark and needs a full
    enumeration; this does not create or upgrade a durable coverage record.
    """
    now = now.astimezone(TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pieces = {}
    for job in jobs:
        if job['site'] != site or job['state'] != 'complete':
            continue
        begin, stop = stamp(job['start']), min(stamp(job['end']), midnight)
        if begin >= stop:
            continue
        captured = json.loads(job['body']).get('captured_at')
        captured = stamp(captured) if captured else None
        if captured is not None and captured > now:
            captured = None  # Clock drift must not suppress future reconciliation.
        day = begin.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < stop:
            end = day + timedelta(days=1)
            pieces.setdefault(day, []).append((max(begin, day), min(stop, end), captured))
            day = end
    unknown = datetime.min.replace(tzinfo=TZ)
    result = {}
    for day, intervals in pieces.items():
        result[day] = None
        end, covered = day + timedelta(days=1), []
        for begin, stop, captured in sorted(intervals, key=lambda item: item[2] or unknown, reverse=True):
            merged = []
            for left, right in sorted([*covered, (begin, stop)]):
                if merged and left <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], right))
                else:
                    merged.append((left, right))
            covered = merged
            if len(covered) == 1 and covered[0][0] <= day and covered[0][1] >= end:
                result[day] = captured
                break
    return result


def tick_windows(store, now):
    now = now.astimezone(TZ)
    jobs = store.coverage()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = midnight - timedelta(days=1)
    for site in store.config['sites']:
        yield site, midnight.isoformat(), now.replace(microsecond=0).isoformat(), 'today_overlap'
        yield site, yesterday.isoformat(), midnight.isoformat(), 'yesterday_reconciliation'
        days = payment_day_watermarks(jobs, site, now)
        due = [(captured or datetime.min.replace(tzinfo=TZ), day) for day, captured in days.items()
               if day < yesterday and (captured is None or now - captured >= HISTORY_RECHECK_AFTER)]
        if due:
            _, day = min(due)
            yield site, day.isoformat(), (day + timedelta(days=1)).isoformat(), 'historical_refund_reconciliation'
        complete = [j for j in jobs if j['site'] == site and j['state'] == 'complete' and stamp(j['end']) <= midnight]
        if complete:
            first = min(stamp(j['start']) for j in complete)
            floor = stamp(store.config.get('history_backfill_start','1970-01-01'))
            if first > floor:
                yield site, max(floor,first-timedelta(days=1)).isoformat(), first.isoformat(), 'historical_backfill'


def targeted_candidates(store, site, now, cursors):
    """Stream core facts, retaining eligible ID/key maps; only the request is capped.

    shortcut: stream existing core orders once per tick; use an indexed projection
    only if measured core-scan cost becomes significant.
    """
    from user_store import _validate_targeted_cursors
    _validate_targeted_cursors({site:cursors},store.config['sites'])
    groups = {'fast': {}, 'watch': {}}
    seen = {}
    cutoff = (stamp(now.isoformat()).replace(hour=0, minute=0, second=0, microsecond=0)-timedelta(days=1)).isoformat()
    with store.db() as db:
        for row in db.execute('SELECT order_key,body FROM orders WHERE site=? AND valid=1 AND paid_at<?', (site, cutoff)):
            body = json.loads(row['body'])
            if not isinstance(body,dict):raise ValueError('targeted_projection_identity')
            status = str(body.get('status'))
            # Current completed orders still receive the independent whole-day rotation.
            if status == '101' or str(body.get('pay_status')) != '1':
                continue
            ident = str(body.get('id') or '')
            if not ident.isascii() or not ident.isdigit() or not 0 < int(ident) < 2**63 or str(int(ident))!=ident:
                raise ValueError('targeted_projection_identity')
            group = 'fast' if status in FAST_REFRESH_STATUSES else 'watch'
            if ident in seen and seen[ident] != row['order_key']:
                raise ValueError('targeted_projection_identity')
            seen[ident]=row['order_key']
            groups[group][ident] = row['order_key']
    selected, after = {}, {}
    for group, values in groups.items():
        cursor = cursors.get(group, 0)
        ids = sorted(values, key=int)
        pending = [ident for ident in ids if int(ident) > cursor]
        batch = (pending+ids)[:min(TARGETED_GROUP_LIMIT, len(ids))]
        # Keep both encoded IN values inside the existing GET request-line budget.
        bounded=[];size=0
        for ident in batch:
            size+=len(ident)+3
            if size>3000:break
            bounded.append(ident)
        batch=bounded
        selected.update((ident, values[ident]) for ident in batch)
        after[group] = int(batch[-1]) if batch else 0
    return selected, after


def targeted_refresh(store, site, now, reader=shared_correct, lock_path=SOURCE_LOCK, force=False):
    from user_store import safe, _public_targeted_attempt, _validate_targeted_cursors
    path = store.root/'targeted-refresh.json'
    state = dict(contract='fs-users-targeted-refresh-v1', cursors={}, latest_attempts={})
    try:
        safe(path)
        if path.exists():
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            with os.fdopen(fd,'rb') as source:
                info=os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or info.st_mode&0o077:
                    raise ValueError('private_targeted_state_required')
                raw=source.read(65537)
            if len(raw)>65536:raise ValueError('targeted_state_size')
            state=json.loads(raw)
        if (not isinstance(state,dict) or state.get('contract')!='fs-users-targeted-refresh-v1'
                or not isinstance(state.get('cursors'),dict) or not isinstance(state.get('latest_attempts'),dict)
                or (set(state['cursors'])|set(state['latest_attempts']))-set(store.config['sites'])):
            raise ValueError('targeted_state_contract')
        if site not in store.config['sites']:raise ValueError('targeted_state_contract')
        _validate_targeted_cursors(state['cursors'],store.config['sites'])
        previous={key:_public_targeted_attempt(value) for key,value in state['latest_attempts'].items()}.get(site,{})
    except (OSError,ValueError,TypeError,KeyError):
        return dict(status='failed',at=now.isoformat(),site=site,mode='targeted',error='targeted_refresh_metadata_invalid',retryable=False)
    if previous.get('status')=='failed' and previous.get('retryable') is False and not force:
        return dict(previous,site=site,mode='targeted',automatic_retry_blocked=True)
    attempt = dict(status='complete', at=now.isoformat())
    try:
        requested,after=targeted_candidates(store,site,now,state['cursors'].get(site,{}))
        attempt.update(requested_rows=len(requested),returned_rows=0,missing_rows=0,changed_rows=0)
        if requested:
            with Path(lock_path).open('a+b') as lock:
                try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    attempt['status']='deferred'
                    for key in ('returned_rows','missing_rows','changed_rows'):attempt.pop(key,None)
                else:
                    result=reader(store,site,requested)
                    if (not isinstance(result,dict) or result.get('mode')!='targeted' or result.get('state') not in ('complete','partial')
                            or result.get('requested_rows')!=len(requested)
                            or any(type(result.get(key)) is not int or result[key]<0 for key in ('returned_rows','missing_rows','changed_rows'))
                            or result['returned_rows']+result['missing_rows']!=len(requested) or result['changed_rows']>result['returned_rows']
                            or (result['state']=='complete')!=(result['missing_rows']==0)):
                        raise ValueError('targeted_receipt_contract')
                    attempt.update(status=result['state'], **{key:result[key] for key in ('returned_rows','missing_rows','changed_rows')})
                    state['cursors'][site]=after
        else:
            state['cursors'][site]=after
    except Exception as error:
        attempt.update(status='failed',error=str(error) if isinstance(error,ValueError) and re.fullmatch('[a-z_]{1,80}',str(error)) else type(error).__name__,retryable=not isinstance(error,ValueError))
        for key in ('returned_rows','missing_rows','changed_rows'):attempt.pop(key,None)
    state['latest_attempts'][site]=attempt
    atomic(path,state)
    return dict(attempt,site=site,mode='targeted')


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
            if args.action == 'tick' and reason == 'yesterday_reconciliation':
                targeted = targeted_refresh(store,site,datetime.now(TZ),force=args.recheck)
                print(canonical(targeted),flush=True)
                if targeted['status']=='deferred':return
        advance_day(store, datetime.now(TZ))
        print(canonical(dict(backup=daily_backup_status(store, now))), flush=True)
        if args.action == 'tick':
            from user_customer_types import ensure_closed_month
            try:
                customer_types = ensure_closed_month(now)
            except (OSError,ValueError,RuntimeError,KeyError,TypeError,ImportError) as error:
                customer_types = dict(status='failed',error_type=type(error).__name__)
            atomic(store.root/'customer-type-status.json', customer_types)
            print(canonical(dict(customer_types=customer_types)),flush=True)


if __name__ == '__main__':
    main()

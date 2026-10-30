"""One resumable weekly publication over the existing fact/revision ledger."""
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
from time import monotonic

from user_contract import TZ, canonical, digest, stamp
from user_store import safe

CONTRACT = 'fs-users-weekly-publication-v1'
WORK = 'weekly-work.json'
META = 'weekly_publication'


class WeeklyUnavailable(LookupError):
    pass


def monday(now):
    now = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=now.weekday())


def window(now):
    # The original :18/:33/:48 timer gets bounded chances; no other timer changes.
    now = now.astimezone(TZ)
    return (4, 18) <= (now.hour, now.minute) < (5, 0)


def small_state(root):
    path = Path(root) / WORK
    safe(path)
    if not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise ValueError('weekly_work_size')
    value = json.loads(path.read_text('utf-8'))
    if (not isinstance(value, dict) or value.get('contract') != 'fs-users-weekly-work-v1'
            or value.get('phase') not in ('complete', 'windows', 'targeted', 'flags', 'publish', 'backup')):
        raise ValueError('weekly_work_contract')
    stamp(value['cutoff'])
    if stamp(value['cutoff']) != monday(stamp(value['cutoff'])):
        raise ValueError('weekly_work_cutoff')
    return value


def record_state(store, value):
    from user_jobs import atomic
    safe(store.root / WORK)
    atomic(store.root / WORK, value)


def checked(value):
    if (not isinstance(value, dict) or value.get('contract') != CONTRACT
            or not {'cutoff', 'published_at', 'captured_at', 'refresh_health', 'coverage_context', 'source_status_rule_versions'} <= set(value)
            or not isinstance(value.get('data_version'), str)
            or not value['data_version'].isdecimal() or str(int(value['data_version'])) != value['data_version']
            or not isinstance(value.get('config'), dict) or not isinstance(value.get('jobs'), list)
            or not isinstance(value.get('flag_manifests'), list)):
        raise ValueError('weekly_publication_contract')
    cutoff = stamp(value['cutoff'])
    if cutoff != monday(cutoff):
        raise ValueError('weekly_publication_cutoff')
    for job in value['jobs']:
        if (not isinstance(job, dict) or set(job) != {'site', 'start', 'end', 'state', 'body'}
                or job['site'] not in value['config']['sites'] or job['state'] not in ('complete', 'failed')
                or job['body'] != '{}' or not stamp(job['start']) < stamp(job['end']) <= cutoff):
            raise ValueError('weekly_publication_jobs')
    if value.get('publication_id') != 'uw_' + digest({k: v for k, v in value.items() if k != 'publication_id'})[:32]:
        raise ValueError('weekly_publication_integrity')
    return value


def stored_publication(store):
    with store.db() as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
    if not row:
        return None
    if len(row[0].encode()) > 4 * 1024 * 1024:
        raise ValueError('weekly_publication_size')
    return checked(json.loads(row[0]))


def write_publication(store, value, previous):
    checked(value)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
        old = checked(json.loads(row[0])) if row else None
        if (old or {}).get('publication_id') != previous:
            raise ValueError('weekly_publication_cas')
        revision = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
        if int(value['data_version']) > revision:
            raise ValueError('weekly_publication_future_version')
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (META, canonical(value)))


def from_snapshot(store, ident, cutoff, manifests, at, origin='weekly'):
    query, public = store.snapshot_public(ident)
    with store.db() as db:
        row = db.execute('SELECT members FROM snapshots WHERE id=?', (ident,)).fetchone()
        if len(row[0].encode()) > 256 or json.loads(row[0]).get('member_kind') != 'recipe-v1':
            raise ValueError('weekly_recipe_baseline_required')
        recipe = store._snapshot_members(db, row[0])
    if recipe.get('contract') != 'fs-users-private-replay-v1' or recipe['data_version'] != public['data_version']:
        raise ValueError('weekly_recipe_baseline_required')
    config = dict(recipe['config'], update_cadence='weekly-v1', snapshot_storage='recipe-v1')
    config.pop('period_customer_types', None)
    jobs = []
    for job in recipe['jobs']:
        if stamp(job['start']) < cutoff:
            jobs.append(dict(job, end=min(stamp(job['end']), cutoff).isoformat(), body='{}'))
    value = dict(contract=CONTRACT, cutoff=cutoff.isoformat(), published_at=at, origin=origin,
                 data_version=public['data_version'], config=config, jobs=jobs,
                 captured_at=public.get('captured_at'), refresh_health=public.get('refresh_health', {}),
                 coverage_context={k: v for k, v in public['coverage'].items()
                                   if k in ('backfill', 'backfill_target_start', 'history_window')},
                 source_status_rule_versions=public.get('source_status_rule_versions', []),
                 flag_manifests=manifests)
    if value['coverage_context'].get('history_window'):
        bound = dict(value['coverage_context']['history_window'])
        bound['end_exclusive'] = min(stamp(bound['end_exclusive']), cutoff).isoformat()
        value['coverage_context']['history_window'] = bound
    value['publication_id'] = 'uw_' + digest(value)[:32]
    return checked(value)


def publication(store, now):
    value = stored_publication(store)
    if value:
        return value
    # Initial adoption freezes an already validated recipe; never exposes a half-collected live revision.
    path = store.root / 'daily-state.json'
    safe(path)
    if not path.is_file() or path.stat().st_size > 65536:
        raise WeeklyUnavailable('weekly_initial_publication_pending')
    daily = json.loads(path.read_text('utf-8'))
    _, public = store.snapshot_public(daily['snapshot_id'])
    cutoff = monday(stamp(public['query']['as_of']))
    from user_customer_types import manifest_inventory
    value = from_snapshot(store, daily['snapshot_id'], cutoff, manifest_inventory(), now.isoformat(), origin='adoption')
    try:
        write_publication(store, value, None)
    except ValueError as error:
        if str(error) != 'weekly_publication_cas':
            raise
    return stored_publication(store)


def public_info(value):
    cutoff = stamp(value['cutoff'])
    return dict(cadence='weekly', publication_id=value['publication_id'], data_version=value['data_version'],
                data_through=(cutoff - timedelta(days=1)).date().isoformat(), cutoff=value['cutoff'],
                default_start=(cutoff - timedelta(days=7)).isoformat(), last_successful_update=value['published_at'],
                next_planned_update=(cutoff + timedelta(days=7, hours=4, minutes=18)).isoformat())


def wake(root, loader, now=None, force=False, clock=monotonic):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    state = small_state(root)
    latest = monday(now)
    if state and state.get('retryable') is False and not force:
        return dict(status='requires_reconciliation', reason=state.get('error'), cutoff=state['cutoff'], source_calls=0)
    if state and (not window(now) or state['phase'] == 'complete' and stamp(state['cutoff']) >= latest
                  or state.get('retryable') is False and not force):
        return dict(status='reused', reason='weekly_idle', cutoff=state['cutoff'], source_calls=0)
    store = loader()
    import fcntl
    with (store.root / 'jobs.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(status='deferred', reason='user_job_active')
        state = small_state(root)
        try:
            published = publication(store, now)
        except WeeklyUnavailable:
            published = None
        if not window(now):
            if published and state is None:
                record_state(store, dict(contract='fs-users-weekly-work-v1', cutoff=published['cutoff'],
                                         phase='backup' if published.get('origin') == 'weekly' else 'complete'))
            return dict(status='reused', reason='weekly_outside_window', source_calls=0)
        if state is None and published and published.get('origin') == 'weekly':
            state = dict(contract='fs-users-weekly-work-v1', cutoff=published['cutoff'], phase='backup')
            record_state(store, state)
        if state is None or state['phase'] == 'complete':
            if published and stamp(published['cutoff']) >= latest:
                record_state(store, dict(contract='fs-users-weekly-work-v1', cutoff=published['cutoff'], phase='complete'))
                return dict(status='reused', reason='weekly_already_published', source_calls=0)
            start = min(stamp(published['cutoff']), latest-timedelta(days=7)) if published else latest-timedelta(days=7)
            # Completed orders can later be refunded; recheck the usual three-month analysis horizon weekly.
            review_start = max(stamp(store.config.get('history_backfill_start', '1970-01-01')), latest-timedelta(days=90))
            start = min(start, review_start)
            state = dict(contract='fs-users-weekly-work-v1', cutoff=latest.isoformat(), phase='windows',
                         started_at=now.isoformat(), start=start.isoformat(), next_days={site: start.isoformat() for site in store.config['sites']},
                         base_publication=(published or {}).get('publication_id'), historical_done=[], backfill_done=[], targeted_done=[])
            record_state(store, state)
        if state.get('retryable') is False and not force:
            return dict(status='requires_reconciliation', reason=state.get('error'), cutoff=state['cutoff'])
        state.pop('error', None); state.pop('retryable', None)
        try:
            return run(store, state, published, now, clock, force=force)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            code = str(error) if isinstance(error, (ValueError, RuntimeError)) and len(str(error)) < 120 else type(error).__name__
            if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_:' for c in code):
                code = type(error).__name__
            retryable = not isinstance(error, (ValueError, KeyError, TypeError, PermissionError)) and not any(
                token in code.lower() for token in ('permission', 'denied', 'invalid', 'unmapped', 'contract', 'identity', 'sort', 'valueerror'))
            state.update(error=code, retryable=retryable)
            record_state(store, state)
            return dict(status='deferred' if retryable else 'requires_reconciliation', reason=code, cutoff=state['cutoff'])


def run(store, state, published, now, clock, force=False):
    from user_jobs import synchronize_day, targeted_refresh, payment_day_watermarks, backup, backup_signature, atomic
    from user_customer_types import ensure_period, manifest_inventory, read_pinned_flags
    cutoff = stamp(state['cutoff'])
    if cutoff - stamp(state['start']) > timedelta(days=90):
        raise ValueError('weekly_gap_exceeds_three_months')
    started = clock()
    deadline = started + 360
    def at():
        return now + timedelta(seconds=max(0, clock()-started))
    def checkpoint():
        record_state(store, state)
        return clock() >= deadline or not window(now + timedelta(seconds=clock()-started))
    if published and published['cutoff'] == state['cutoff']:
        state['phase'] = 'backup'  # Reconcile a commit whose checkpoint was interrupted.
    if state['phase'] == 'windows':
        for site in store.config['sites']:
            day = stamp(state['next_days'][site])
            while day < cutoff:
                end = day + timedelta(days=1)
                already = any(j['site'] == site and j['state'] == 'complete' and stamp(j['start']) <= day
                              and stamp(j['end']) >= end and stamp(json.loads(j['body']).get('captured_at', '1970-01-01')) >= stamp(state['started_at'])
                              for j in store.coverage())
                if not already:
                    result = synchronize_day(store, site, day.isoformat(), end.isoformat())
                    if result['status'] == 'deferred':
                        return dict(status='deferred', reason='existing_source_busy', cutoff=state['cutoff'])
                day = end; state['next_days'][site] = day.isoformat()
                if checkpoint():
                    return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
            if site not in state['historical_done']:
                days = payment_day_watermarks(store.coverage(), site, now)
                older = [(at or datetime.min.replace(tzinfo=TZ), day) for day, at in days.items() if day < stamp(state['start'])]
                if older:
                    _, day = min(older)
                    result = synchronize_day(store, site, day.isoformat(), (day+timedelta(days=1)).isoformat())
                    if result['status'] == 'deferred':
                        return dict(status='deferred', reason='existing_source_busy', cutoff=state['cutoff'])
                state['historical_done'].append(site)
                if checkpoint():return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
            if site not in state.get('backfill_done', []):
                complete = [stamp(j['start']) for j in store.coverage() if j['site'] == site and j['state'] == 'complete']
                floor = stamp(store.config.get('history_backfill_start', '1970-01-01'))
                if complete and min(complete) > floor:
                    end = min(complete)
                    result = synchronize_day(store, site, max(floor, end-timedelta(days=1)).isoformat(), end.isoformat())
                    if result['status'] == 'deferred':return dict(status='deferred', reason='existing_source_busy', cutoff=state['cutoff'])
                state.setdefault('backfill_done', []).append(site)
                if checkpoint():return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
        state['phase'] = 'targeted'; record_state(store, state)
    if state['phase'] == 'targeted':
        for site in store.config['sites']:
            if site in state['targeted_done']:continue
            result = targeted_refresh(store, site, now, force=force)
            if result['status'] != 'complete':
                if result['status'] == 'partial' or result.get('retryable') is False:
                    state.update(error='weekly_targeted_'+result['status'], retryable=False)
                    record_state(store, state)
                return dict(status='requires_reconciliation' if state.get('retryable') is False else 'deferred', reason='weekly_targeted_'+result['status'], cutoff=state['cutoff'])
            state['targeted_done'].append(site)
            if checkpoint():return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
        state['phase'] = 'flags'; record_state(store, state)
    if state['phase'] == 'flags':
        result = ensure_period(state['start'], state['cutoff'], now)
        if result['status'] != 'complete':
            return dict(status='deferred', reason='weekly_customer_type_pending', cutoff=state['cutoff'])
        state['phase'] = 'publish'; record_state(store, state)
        if checkpoint():return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
    if state['phase'] == 'publish':
        from user_query import Service
        from user_lifecycle import covered
        jobs = store.coverage()
        if not covered(jobs, list(store.config['sites']), stamp(state['start']), cutoff):
            raise ValueError('weekly_complete_day_coverage_required')
        manifests = manifest_inventory()
        _, flags = read_pinned_flags(dict(start=state['start'], end_exclusive=state['cutoff']), manifests)
        if flags['status'] != 'complete':
            state['phase'] = 'flags'; record_state(store, state)
            return dict(status='deferred', reason='weekly_customer_type_pending', cutoff=state['cutoff'])
        service = Service(store, lambda *_: True, clock=lambda: cutoff,
                          customer_type_reader=lambda query: read_pinned_flags(query, manifests), weekly_publication=False)
        result = service.query(dict(start=(cutoff-timedelta(days=7)).isoformat()), 'internal_weekly_calculation')
        value = from_snapshot(store, result['snapshot_id'], cutoff, manifests, at().isoformat())
        write_publication(store, value, state['base_publication'])
        state['phase'] = 'backup'; record_state(store, state)
    if state['phase'] == 'backup':
        published = stored_publication(store)
        day = recovery_day(store, state, published, at())
        state['backup_day'] = day; record_state(store, state)
        receipt = backup(store, at(), day=day, weekly_cutoff=state['cutoff'])
        if receipt['data_version'] != stored_publication(store)['data_version']:
            raise ValueError('weekly_backup_version_requires_reconciliation')
        folder = store.root / 'backups' / day
        atomic(store.root/'backup-status.json', dict(status='complete', day=day, receipt=receipt, signature=backup_signature(folder)))
        state.update(phase='complete', completed_at=at().isoformat()); record_state(store, state)
    return dict(status='complete', cutoff=state['cutoff'], data_version=stored_publication(store)['data_version'])


def recovery_day(store, state, published, now):
    """Reconcile an existing cycle before choosing a new directory; never duplicate an unknown copy."""
    first = stamp(published['published_at']).date().isoformat()
    today = now.date().isoformat()
    root = store.root / 'backups'; safe(root)
    matches = []
    if root.exists():
        for folder in root.iterdir():
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', folder.name) or not first <= folder.name <= today:
                continue
            safe(folder)
            if not folder.is_dir():raise ValueError('weekly_backup_unknown_directory')
            path = folder/'manifest.json'; safe(path)
            if not path.is_file():raise ValueError('weekly_backup_unknown_directory')
            with path.open('rb') as stream:raw = stream.read(65537)
            if len(raw)>65536:raise ValueError('weekly_backup_manifest_size')
            value = json.loads(raw)
            if value.get('weekly_cutoff') == state['cutoff']:
                matches.append(folder.name)
    if len(matches)>1:raise ValueError('weekly_duplicate_backups_requires_reconciliation')
    if matches:return matches[0]
    planned = state.get('backup_day', first)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', planned):raise ValueError('weekly_backup_day')
    return planned if (root/planned).exists() else today

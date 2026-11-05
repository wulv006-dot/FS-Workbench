"""One resumable publication over the existing fact/revision ledger."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from time import monotonic

from user_contract import TZ, canonical, digest, stamp
from user_store import safe

CONTRACT = 'fs-users-weekly-publication-v1'
WORK = 'weekly-work.json'
META = 'weekly_publication'
REVIEW_POLICY = 'calendar-months-v1'


class WeeklyUnavailable(LookupError):
    pass


def monday(now):
    now = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=now.weekday())


def calendar_review_start(cutoff):
    """Current calendar month and the preceding two, through the cutoff midnight."""
    cutoff = cutoff.astimezone(TZ)
    month_index = cutoff.year * 12 + cutoff.month - 1 - 2
    year, month = divmod(month_index, 12)
    return cutoff.replace(year=year, month=month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


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
            or value.get('cadence', 'weekly') not in ('daily', 'weekly')
            or value.get('phase') not in ('complete', 'windows', 'targeted', 'flags', 'publish', 'backup')):
        raise ValueError('weekly_work_contract')
    stamp(value['cutoff'])
    boundary = stamp(value['cutoff']).replace(hour=0, minute=0, second=0, microsecond=0) if value.get('cadence') == 'daily' else monday(stamp(value['cutoff']))
    if stamp(value['cutoff']) != boundary:
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
            or not isinstance(value.get('flag_manifests'), list)
            or value.get('cadence', 'weekly') not in ('daily', 'weekly')):
        raise ValueError('weekly_publication_contract')
    cutoff = stamp(value['cutoff'])
    boundary = cutoff.replace(hour=0, minute=0, second=0, microsecond=0) if value.get('cadence') == 'daily' else monday(cutoff)
    if cutoff != boundary:
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
    config = dict(recipe['config'], update_cadence='daily-v1' if origin == 'daily' else 'weekly-v1', snapshot_storage='recipe-v1')
    config.pop('period_customer_types', None)
    jobs = []
    for job in recipe['jobs']:
        if stamp(job['start']) < cutoff:
            jobs.append(dict(job, end=min(stamp(job['end']), cutoff).isoformat(), body='{}'))
    value = dict(contract=CONTRACT, cutoff=cutoff.isoformat(), published_at=at, origin=origin, cadence='daily' if origin == 'daily' else 'weekly',
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
    days = 1 if value.get('cadence') == 'daily' else 7
    result = dict(cadence=value.get('cadence', 'weekly'), publication_id=value['publication_id'], data_version=value['data_version'],
                data_through=(cutoff - timedelta(days=1)).date().isoformat(), cutoff=value['cutoff'],
                default_start=(cutoff - timedelta(days=7)).isoformat(), last_successful_update=value['published_at'],
                next_planned_update=(cutoff + timedelta(days=days, hours=4, minutes=18)).isoformat(),
                backup_policy='on_demand_only')
    if value.get('review_pending'):
        result['review_pending'] = value['review_pending']
    return result


def error_state(error):
    code = str(error) if isinstance(error, (ValueError, RuntimeError)) and len(str(error)) < 120 else type(error).__name__
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_:' for c in code):
        code = type(error).__name__
    retryable = not isinstance(error, (ValueError, KeyError, TypeError, PermissionError)) and not any(
        token in code.lower() for token in ('permission', 'denied', 'invalid', 'unmapped', 'contract', 'identity', 'sort', 'valueerror'))
    return dict(error=code, retryable=retryable)


def wake(root, loader, now=None, force=False, clock=monotonic, cadence='weekly'):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    state = small_state(root)
    if cadence not in ('daily', 'weekly'): raise ValueError('publication_cadence')
    latest = now.replace(hour=0, minute=0, second=0, microsecond=0) if cadence == 'daily' else monday(now)
    retiring_backup = state is not None and state['phase'] == 'backup'
    calendar_review = bool(state and state.get('review_policy') == REVIEW_POLICY and state.get('review_start'))
    if state and not calendar_review and not retiring_backup and state.get('retryable') is False and not force:
        return dict(status='requires_reconciliation', reason=state.get('error'), cutoff=state['cutoff'], source_calls=0)
    if state and not retiring_backup and (not window(now) or state['phase'] == 'complete' and stamp(state['cutoff']) >= latest
                  or not calendar_review and state.get('retryable') is False and not force):
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
        if state is None and published and published.get('origin') in ('weekly', 'daily'):
            state = dict(contract='fs-users-weekly-work-v1', cutoff=published['cutoff'], phase='backup', cadence=published.get('cadence', 'weekly'))
        if state and state['phase'] == 'backup' and not calendar_review:
            if not published or published['cutoff'] != state.get('publication_cutoff', state['cutoff']):
                return dict(status='requires_reconciliation', reason='weekly_publication_checkpoint_mismatch', source_calls=0)
            # Old pending copies are left intact; they no longer block the next weekly publication.
            return dict(finish_week(store, state, published, now), source_calls=0)
        if not window(now):
            if published and state is None:
                record_state(store, dict(contract='fs-users-weekly-work-v1', cutoff=published['cutoff'], phase='complete', cadence=published.get('cadence', 'weekly')))
            return dict(status='reused', reason='weekly_outside_window', source_calls=0)
        if state is None or state['phase'] == 'complete':
            if published and stamp(published['cutoff']) >= latest:
                record_state(store, dict(contract='fs-users-weekly-work-v1', cutoff=published['cutoff'], phase='complete', cadence=published.get('cadence', 'weekly')))
                return dict(status='reused', reason='weekly_already_published', source_calls=0)
            start = min(stamp(published['cutoff']), latest-timedelta(days=7)) if published else latest-timedelta(days=7)
            if cadence == 'daily':
                # Date enumeration includes every order status. A weekly calendar-month
                # review replaces the daily old-day rotation and targeted-ID pass.
                if published:
                    start = stamp(published['cutoff'])
                review_start = calendar_review_start(latest) if latest.weekday() == 0 else None
                if review_start is not None:
                    start = min(start, review_start)
            else:
                # Preserve the legacy weekly caller and already running work contract.
                review_start = max(stamp(store.config.get('history_backfill_start', '1970-01-01')), latest-timedelta(days=90))
                start = min(start, review_start)
            state = dict(contract='fs-users-weekly-work-v1', cutoff=latest.isoformat(), phase='windows', cadence=cadence,
                         started_at=now.isoformat(), start=start.isoformat(), next_days={site: start.isoformat() for site in store.config['sites']},
                         base_publication=(published or {}).get('publication_id'), historical_done=[], backfill_done=[], targeted_done=[])
            if cadence == 'daily':
                state.update(review_policy=REVIEW_POLICY, review_start=review_start.isoformat() if review_start else None,
                             initial_published_cutoff=(published or {}).get('cutoff'))
            record_state(store, state)
        review_blocked = state.get('retryable') is False and not force
        if review_blocked and not (state.get('review_policy') == REVIEW_POLICY and state.get('review_start')):
            return dict(status='requires_reconciliation', reason=state.get('error'), cutoff=state['cutoff'])
        if not review_blocked:
            state.pop('error', None); state.pop('retryable', None)
        try:
            return run(store, state, published, now, clock, force=force)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            state.update(error_state(error))
            record_state(store, state)
            return dict(status='deferred' if state['retryable'] else 'requires_reconciliation', reason=state['error'], cutoff=state['cutoff'])


def review_cycle_id(state):
    return 'ur_' + digest({key: state[key] for key in ('review_policy', 'cutoff', 'started_at')})[:24]


def snapshot_candidate(store, start, cutoff, now, cadence):
    """Shared daily/review publication over complete facts and pinned ES files."""
    from user_customer_types import manifest_inventory, read_pinned_flags, read_pinned_identities
    from user_query import Service
    manifests = manifest_inventory()
    _, flags = read_pinned_flags(dict(start=min(stamp(start), cutoff-timedelta(days=7)).isoformat(), end_exclusive=cutoff.isoformat()), manifests)
    if flags['status'] != 'complete':
        return None, 'weekly_customer_type_pending'
    identity_rows, identity_info = read_pinned_identities(dict(start=start, end_exclusive=cutoff.isoformat()), manifests)
    if identity_info['status'] != 'complete':
        return None, 'identity_archive_pending'
    evidence = store.enrich_order_identities(start, cutoff.isoformat(), identity_rows, identity_info['sourceVersion'])
    service = Service(store, lambda *_: True, clock=lambda: cutoff,
                      customer_type_reader=lambda query: read_pinned_flags(query, manifests), weekly_publication=False)
    result = service.query(dict(start=(cutoff-timedelta(days=7)).isoformat()), 'internal_weekly_calculation')
    value = from_snapshot(store, result['snapshot_id'], cutoff, manifests, now.isoformat(), origin=cadence)
    return value, evidence


def advance_daily_during_review(store, state, published, now, checkpoint):
    """Use the same lock/work file; keep the original monthly cursor untouched."""
    from user_jobs import synchronize_day, has_window
    from user_customer_types import ensure_period
    from user_lifecycle import covered
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if published and stamp(published['cutoff']) >= cutoff:
        return None
    start = stamp(published['cutoff']) if published else cutoff-timedelta(days=7)
    for site in store.config['sites']:
        day = start
        while day < cutoff:
            end = day + timedelta(days=1)
            if not has_window(store.coverage(), site, day.isoformat(), end.isoformat()):
                result = synchronize_day(store, site, day.isoformat(), end.isoformat())
                if result['status'] == 'deferred':
                    return dict(status='deferred', reason='daily_source_busy', cutoff=cutoff.isoformat())
            day = end
            if checkpoint():
                return dict(status='continuing', phase='daily_priority', cutoff=cutoff.isoformat())
    if not covered(store.coverage(), list(store.config['sites']), start, cutoff):
        raise ValueError('daily_complete_day_coverage_required')
    flags = ensure_period(min(start, cutoff-timedelta(days=7)).isoformat(), cutoff.isoformat(), now, daily=True)
    if flags['status'] != 'complete':
        return dict(status='deferred', reason='daily_customer_type_pending', cutoff=cutoff.isoformat())
    value, evidence = snapshot_candidate(store, start.isoformat(), cutoff, now, 'daily')
    if value is None:
        return dict(status='deferred', reason=evidence, cutoff=cutoff.isoformat())
    if not state.get('review_complete'):
        value['review_pending'] = dict(cycle_id=review_cycle_id(state), start=state['review_start'], cutoff=state['cutoff'])
    value['publication_id'] = 'uw_' + digest({k: v for k, v in value.items() if k != 'publication_id'})[:32]
    # Save the exact candidate before the CAS write so an interrupted response is reconciled.
    state['daily_publication_id'] = value['publication_id']; record_state(store, state)
    write_publication(store, value, (published or {}).get('publication_id'))
    state['base_publication'] = value['publication_id']; record_state(store, state)
    return None


def run(store, state, published, now, clock, force=False):
    from user_jobs import synchronize_day, targeted_refresh, payment_day_watermarks
    from user_customer_types import ensure_period
    cutoff = stamp(state['cutoff'])
    calendar_policy = state.get('review_policy') == REVIEW_POLICY
    review_start = stamp(state['review_start']) if calendar_policy and state.get('review_start') else None
    started = clock()
    deadline = started + 360
    def at():
        return now + timedelta(seconds=max(0, clock()-started))
    def checkpoint():
        record_state(store, state)
        return clock() >= deadline or not window(now + timedelta(seconds=clock()-started))
    if published and ((calendar_policy and state.get('final_publication_id') == published['publication_id'])
                      or not calendar_policy and published['cutoff'] == state['cutoff']):
        state['phase'] = 'backup'  # Reconcile a commit whose checkpoint was interrupted.
    if calendar_policy and review_start is not None and state['phase'] == 'backup':
        if not published or published['publication_id'] not in (state.get('final_publication_id'), state.get('daily_publication_id')):
            raise ValueError('weekly_publication_checkpoint_mismatch')
        state.update(review_complete=True, publication_cutoff=published['cutoff'])
    if state['phase'] != 'backup':
        if calendar_policy:
            lower = min(calendar_review_start(cutoff), stamp(state['initial_published_cutoff'])
                        if state.get('initial_published_cutoff') else cutoff-timedelta(days=7))
            if (not lower <= stamp(state['start']) < cutoff
                    or review_start is not None and (review_start != calendar_review_start(cutoff) or cutoff.weekday() != 0)):
                raise ValueError('calendar_review_range')
        elif cutoff - stamp(state['start']) > timedelta(days=90):
            raise ValueError('weekly_gap_exceeds_three_months')
    if calendar_policy and review_start is not None:
        if state.get('daily_error', {}).get('retryable') is False and not force:
            return dict(status='requires_reconciliation', reason=state['daily_error']['error'], phase='daily_priority', cutoff=state['cutoff'])
        try:
            priority = advance_daily_during_review(store, state, published, at(), checkpoint)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            state['daily_error'] = error_state(error); record_state(store, state)
            return dict(status='deferred' if state['daily_error']['retryable'] else 'requires_reconciliation',
                        reason=state['daily_error']['error'], phase='daily_priority', cutoff=state['cutoff'])
        if priority is not None:
            return priority
        state.pop('daily_error', None)
        published = stored_publication(store)
        state['base_publication'] = (published or {}).get('publication_id')
        if state.get('review_complete'):
            state['publication_cutoff'] = published['cutoff']
        record_state(store, state)
        if state.get('retryable') is False and not force:
            return dict(status='requires_reconciliation', reason=state['error'], cutoff=state['cutoff'], review_pending=True)
        if checkpoint():return dict(status='continuing', phase='review', cutoff=state['cutoff'])
    if state['phase'] == 'windows':
        for site in store.config['sites']:
            day = stamp(state['next_days'][site])
            while day < cutoff:
                end = day + timedelta(days=1)
                reuse_archived = (not review_start or day < review_start) if calendar_policy else bool(
                    state.get('cadence') == 'daily' and published and day >= stamp(published['cutoff']))
                already = any(j['site'] == site and j['state'] == 'complete' and stamp(j['start']) <= day
                              and stamp(j['end']) >= end and (stamp(json.loads(j['body']).get('captured_at', '1970-01-01')) >= stamp(state['started_at'])
                              or reuse_archived)
                              for j in store.coverage())
                if not already:
                    result = synchronize_day(store, site, day.isoformat(), end.isoformat())
                    if result['status'] == 'deferred':
                        return dict(status='deferred', reason='existing_source_busy', cutoff=state['cutoff'])
                day = end; state['next_days'][site] = day.isoformat()
                if checkpoint():
                    return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
            if not calendar_policy and site not in state['historical_done']:
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
        state['phase'] = 'flags' if calendar_policy else 'targeted'; record_state(store, state)
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
        flag_start = min(stamp(state['start']), cutoff-timedelta(days=7))
        options = dict(daily=state.get('cadence') == 'daily')
        if calendar_policy and review_start is not None:
            if flag_start < review_start:
                gap = ensure_period(flag_start.isoformat(), review_start.isoformat(), now, daily=True)
                if gap['status'] != 'complete':
                    return dict(status='deferred', reason='weekly_customer_type_pending', cutoff=state['cutoff'])
            flag_start = review_start
            options.update(daily=False, fresh_after=state['started_at'], cycle_id=review_cycle_id(state))
        result = ensure_period(flag_start.isoformat(), state['cutoff'], now, **options)
        if result['status'] != 'complete':
            return dict(status='deferred', reason='weekly_customer_type_pending', cutoff=state['cutoff'])
        state['phase'] = 'publish'; record_state(store, state)
        if checkpoint():return dict(status='continuing', phase=state['phase'], cutoff=state['cutoff'])
    if state['phase'] == 'publish':
        from user_lifecycle import covered
        jobs = store.coverage()
        if not covered(jobs, list(store.config['sites']), stamp(state['start']), cutoff):
            raise ValueError('weekly_complete_day_coverage_required')
        publish_cutoff = max(cutoff, stamp(published['cutoff'])) if calendar_policy and published else cutoff
        value, evidence = snapshot_candidate(store, state['start'], publish_cutoff, at(), 'daily' if state.get('cadence') == 'daily' else 'weekly')
        if value is None:
            state['phase'] = 'flags'; record_state(store, state)
            return dict(status='deferred', reason=evidence, cutoff=state['cutoff'])
        state.update(identity_evidence=evidence, publication_cutoff=publish_cutoff.isoformat(), final_publication_id=value['publication_id'])
        record_state(store, state)
        write_publication(store, value, state['base_publication'])
        state['phase'] = 'backup'; record_state(store, state)
    return finish_week(store, state, stored_publication(store), at(), force=force)


def finalize_review_archive(store, state, published):
    from user_customer_types import compact_after_publication
    ident = published['publication_id']
    previous = state.get('cleanup_plan_sha256')
    result = None
    if previous:
        try:
            result = compact_after_publication(store, ident, apply=True, expected_plan_sha256=previous)
        except ValueError as error:
            if str(error) not in ('es_archive_references_changed', 'es_archive_compaction_changed'):
                raise
            # The original receipt has been reconciled. A new dry plan re-evaluates
            # remaining original candidates against the new publication/references.
    if result is None:
        plan = compact_after_publication(store, ident)
        state['cleanup_plan_sha256'] = plan['plan_sha256']
        if previous and previous != plan['plan_sha256']:
            state['cleanup_previous_plan_sha256'] = previous
        record_state(store, state)
        result = compact_after_publication(store, ident, apply=True, expected_plan_sha256=plan['plan_sha256'])
    if result.get('applied') is not True or result.get('plan_sha256') != state['cleanup_plan_sha256']:
        raise ValueError('archive_cleanup_receipt_contract')
    state['cleanup'] = dict(status='complete', plan_sha256=result['plan_sha256'], publication_id=ident,
                           removed_manifests=result['removed_manifests'], removed_files=result['removed_files'])
    state.pop('cleanup_error', None)
    record_state(store, state)


def finish_week(store, state, published, now, force=False):
    """Commit a tiny completion receipt; full database backups are explicit manual operations only."""
    if not published or published['cutoff'] != state.get('publication_cutoff', state['cutoff']):
        raise ValueError('weekly_publication_checkpoint_mismatch')
    if state.get('review_policy') == REVIEW_POLICY and state.get('review_start'):
        state['review_complete'] = True
        if state.get('cleanup_error', {}).get('retryable') is False and not force:
            return dict(status='requires_reconciliation', reason=state['cleanup_error']['error'], cleanup_pending=True, cutoff=published['cutoff'])
        if state.get('cleanup', {}).get('status') != 'complete':
            try:
                finalize_review_archive(store, state, published)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                state['cleanup_error'] = error_state(error); record_state(store, state)
                return dict(status='deferred' if state['cleanup_error']['retryable'] else 'requires_reconciliation',
                            reason=state['cleanup_error']['error'], cleanup_pending=True, cutoff=published['cutoff'])
    if state.get('error'):
        state['retired_backup_error'] = state.pop('error')
    state.pop('retryable', None)
    state.update(phase='complete', completed_at=now.isoformat(), backup_policy='on_demand_only',
                 data_version=published['data_version'])
    record_state(store, state)
    result = dict(status='complete', cutoff=published['cutoff'], data_version=published['data_version'],
                  backup_policy='on_demand_only', automatic_backup=False)
    if state.get('review_policy') == REVIEW_POLICY and state.get('review_start'):
        result['review_cutoff'] = state['cutoff']
    return result

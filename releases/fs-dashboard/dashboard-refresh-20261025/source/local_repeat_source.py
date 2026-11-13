"""Attach an authorized, fixed-revision customer aggregate to the summary reply."""
from copy import copy, deepcopy
from datetime import date, timedelta
from sqlite3 import Error as SQLiteError

from admin_scope import repeat_metrics


def cohort_query(q, supplement):
    scope = supplement.get('requested_scope') or {}
    if (q['profile'] == 'RS' or q['grain'] != 'day' or q.get('country_code')
            or q.get('admin_site') != '266' or scope.get('site') != '266'
            or scope.get('country_code') != 'all'):
        return None
    period = {'start': q['start'] + ' 00:00',
              'end': (date.fromisoformat(q['end']) + timedelta(days=1)).isoformat() + ' 00:00'}
    if q['period'] != period or scope.get('period') != period:
        return None
    game = scope.get('game')
    if not isinstance(game, str) or (game != 'all' and not game.isdecimal()):
        return None
    effective = supplement.get('effective_scope') or {}
    if any(effective.get(k) != scope[k] for k in ('site','game','country_code','period')):
        coverage = supplement.get('coverage') or {}
        if coverage.get('scope_status') != 'empty_result_membership_unverified':
            return None
    from user_contract import stamp
    start, end = (stamp(period[k]).isoformat() for k in ('start','end'))
    return dict(scope='site',scope_id='266',game=game,start=start,end_exclusive=end,as_of=end,
                state_basis='period_cohort',policy_version='fc-v1' if game == '1327' else 'common-v1',H=30)


def read(query, service, actor, authorization_scope, cache, lock):
    from user_contract import stamp
    from user_lifecycle import analyze, covered
    from user_weekly import stored_publication

    site, game = query['scope_id'], query['game']
    access = {k:query[k] for k in ('scope','scope_id','start','end_exclusive','as_of','state_basis','policy_version','H')}
    service.permit(actor, access)
    if game != 'all':
        service.permit(actor, dict(access,scope='project',scope_id=game))
    if not lock.acquire(blocking=False):
        return None, 'local_repeat_busy'
    try:
        store = copy(service.store)
        store.read_only = True
        publication = stored_publication(store)
        if publication is None:
            return None, 'publication_unavailable'
        config = publication['config']
        if site not in config['sites'] or (game != 'all' and game not in config['projects']):
            return None, 'publication_scope_unverified'
        start, end = query['start'], query['end_exclusive']
        if stamp(end) > stamp(publication['cutoff']) or not covered(publication['jobs'], [site], stamp(start), stamp(end)):
            return None, 'publication_period_incomplete'
        key = (authorization_scope, site, game, start, end, publication['publication_id'], publication['data_version'])
        if key not in cache:
            rows = store.read_at(publication['data_version'],start,end,bounded_only=True)
            if rows is None:
                return None, 'bounded_revision_unavailable'
            if game != 'all':
                rows = [row for row in rows if row['gid'] == game]
            cohort, _ = analyze(rows, publication['jobs'], access, config, details=False)
            coverage = cohort['coverage']
            local = dict(scope={k:query[k] for k in ('scope','scope_id','game','start','end_exclusive')},
                coverage={k:coverage[k] for k in ('period_complete','identity_deduplication_complete','missing_identity_orders','state_basis')},
                repeat_rate=cohort['repeat_rate'],data_revision=publication['data_version'],publication_id=publication['publication_id'])
            if len(cache) >= 32:
                cache.pop(next(iter(cache)))
            cache[key] = local
        return cache[key], None
    finally:
        lock.release()


def attach(value, q, actor, service, cache, lock):
    profile = value.get('profile') or {}
    supplement = profile.get('supplement') or {}
    if not actor or service is None or supplement.get('status') != 'available' or 'local_repeat_rate' not in supplement:
        return value
    try:
        query = cohort_query(q, supplement)
        local, reason = (read(query, service, actor, q.get('authorization_scope', actor), cache, lock)
                         if query else (None, 'scope_not_supported'))
    except PermissionError:
        local, reason = None, 'user_scope_denied'
    except (ImportError, LookupError, OSError, SQLiteError, TypeError, ValueError):
        local, reason = None, 'publication_read_unavailable'
    result = repeat_metrics({}, {}, local)['local_repeat_rate']
    if reason:
        result['reason'] = reason
    return {**value,'profile':{**profile,'supplement':{**supplement,'local_repeat_rate':result}}}

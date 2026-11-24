"""Attach an authorized, fixed-revision customer aggregate to the summary reply."""
from copy import copy
from datetime import date, timedelta
from sqlite3 import Error as SQLiteError

from admin_scope import repeat_metrics


def cohort_query(q, supplement):
    if q['profile'] == 'RS':
        return None, 'rs_not_supported'
    if q.get('admin_site') != '266':
        return None, 'main_site_required'
    if q.get('country_code'):
        return None, 'country_filter_not_supported'
    if q['grain'] != 'day':
        return None, 'full_days_required'
    if q.get('profit_category') not in (None, '', '-1'):
        return None, 'product_filter_not_supported'
    period = {'start': q['start'] + ' 00:00',
              'end': (date.fromisoformat(q['end']) + timedelta(days=1)).isoformat() + ' 00:00'}
    if q['period'] != period:
        return None, 'full_days_required'

    # Derived archives strip effective/requested scope and percentages. Their
    # original per-profile Admin filter still identifies the requested game.
    scope = supplement.get('requested_scope')
    filters = supplement.get('filters') or {}
    if scope:
        if scope.get('site') != '266' or scope.get('country_code') != 'all' or scope.get('period') != period:
            return None, 'publication_scope_unverified'
        game = scope.get('game')
    elif str(filters.get('site')) == '266' and not filters.get('country_code'):
        game = str(filters.get('game') or 'all')
    else:
        return None, 'publication_scope_unverified'
    if not isinstance(game, str) or (game != 'all' and not game.isdecimal()):
        return None, 'publication_scope_unverified'

    from user_contract import stamp
    start, end = (stamp(period[k]).isoformat() for k in ('start','end'))
    return dict(scope='site', scope_id='266', game=game, start=start, end_exclusive=end), None


def read(query, service, actor, authorization_scope, cache, lock):
    from user_contract import stamp
    from user_lifecycle import covered, period_repeat
    from user_weekly import stored_publication

    site, game = query['scope_id'], query['game']
    access = {k:query[k] for k in ('scope','scope_id','start','end_exclusive')}
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
            rate, unidentified = period_repeat(rows, site, game, stamp(start), stamp(end))
            coverage = dict(period_complete=True, identity_deduplication_complete=True,
                            missing_identity_orders=unidentified, state_basis='period_cohort')
            local = dict(scope=query, coverage=coverage, repeat_rate=rate,
                         data_revision=publication['data_version'], publication_id=publication['publication_id'])
            if len(cache) >= 32:
                cache.pop(next(iter(cache)))
            cache[key] = local
        return cache[key], None
    finally:
        lock.release()


def attach(value, q, actor, service, cache, lock):
    profile = value.get('profile') or {}
    supplement = profile.get('supplement') or {}
    if not actor or service is None:
        return value
    try:
        query, reason = cohort_query(q, supplement)
        local = None
        if query is not None:
            local, reason = read(query, service, actor, q.get('authorization_scope', actor), cache, lock)
    except PermissionError:
        local, reason = None, 'user_scope_denied'
    except (ImportError, LookupError, OSError, SQLiteError, TypeError, ValueError):
        local, reason = None, 'publication_read_unavailable'
    result = repeat_metrics({}, {}, local)['local_repeat_rate']
    if reason:
        result['reason'] = reason
    return {**value,'profile':{**profile,'supplement':{**supplement,'local_repeat_rate':result}}}

"""Pure shared date contract; no source calls, grants, or production activation."""
from calendar import monthrange
from datetime import date, timedelta

CONTRACT = 'fs-data-capability-v2'


class PolicyError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def day(value):
    if not isinstance(value, str):
        raise PolicyError('date_range_required')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise PolicyError('invalid_date') from None
    if parsed.isoformat() != value:
        raise PolicyError('invalid_date')
    return parsed


def subtract(end, span):
    value, unit = span['value'], span['unit']
    if type(value) is not int or value <= 0:
        raise PolicyError('invalid_span')
    if unit == 'days':
        return end - timedelta(days=value)
    if unit not in ('calendar_months', 'calendar_years'):
        raise PolicyError('invalid_span')
    months = value * (12 if unit == 'calendar_years' else 1)
    year, month = divmod(end.year * 12 + end.month - 1 - months, 12)
    return date(year, month + 1, min(end.day, monthrange(year, month + 1)[1]))


def validate(cap, request):
    """cap must be produced *after* trusted server-side scope authorization."""
    if cap.get('contract') != CONTRACT:
        raise PolicyError('invalid_capability')
    if request.get('policy_version') != cap['policy_version']:
        raise PolicyError('policy_changed')
    if request.get('timezone') != cap['timezone']:
        raise PolicyError('timezone_mismatch')
    if request.get('dataset_id') != cap['dataset_id'] or request.get('scope') != cap['scope']:
        raise PolicyError('permission_denied')
    mode = request.get('mode')
    if mode not in cap['allowed_modes']:
        raise PolicyError('mode_not_allowed')
    start, end = day(request.get('start')), day(request.get('end_exclusive'))
    if start >= end:
        raise PolicyError('range_out_of_policy')
    policy = cap['live'] if mode == 'fresh' else cap[mode]
    if not policy.get('enabled'):
        raise PolicyError('range_not_available')
    if start < subtract(end, policy['max_query_span']):
        raise PolicyError('range_out_of_policy')
    if mode == 'fresh':
        if not all(policy.get(k) for k in ('earliest_available_date', 'earliest_allowed_live_date', 'latest_available_end_exclusive')):
            raise PolicyError('range_not_available')
        if start < max(day(policy['earliest_available_date']), day(policy['earliest_allowed_live_date'])) or end > day(policy['latest_available_end_exclusive']):
            raise PolicyError('range_out_of_policy')
    else:
        if mode == 'frozen':
            if not policy.get('snapshot_id') or policy.get('snapshot_revision') is None or (request.get('snapshot_id'), request.get('snapshot_revision')) != (policy.get('snapshot_id'), policy.get('snapshot_revision')):
                raise PolicyError('missing_history')
        cursor = start
        for interval in sorted(policy.get('coverage_intervals', []), key=lambda item: item['start']):
            lo, hi = day(interval['start']), day(interval['end_exclusive'])
            if lo > cursor: break
            if hi > cursor: cursor = hi
            if cursor >= end: break
        if cursor < end:
            raise PolicyError('range_not_available')
    return dict(start=start.isoformat(), end_exclusive=end.isoformat())


def get_capability(identity, dataset_id, requested_scope, mode, *, authorize, resolve):
    # The caller must use the existing trusted identity/grant resolver. This
    # contract deliberately cannot manufacture a grant from a client scope.
    grant = authorize(identity, dataset_id, requested_scope, mode)
    if not grant:
        raise PolicyError('permission_denied')
    cap = resolve(grant, dataset_id, requested_scope, mode)
    if cap['scope'] != requested_scope or cap['dataset_id'] != dataset_id or mode not in cap['allowed_modes']:
        raise PolicyError('permission_denied')
    return cap

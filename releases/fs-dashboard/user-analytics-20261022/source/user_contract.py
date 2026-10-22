"""Deterministic purchase-customer contract. No source calls or model arithmetic."""
import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
STATES = ('recent', 'silent', 'lost', 'long_lost')
POLICIES = {'common-v1': (30, 60, 90), 'fc-v1': (14, 30, 90)}
VIEWS = ('summary', 'trend', 'projects', 'transitions', 'cohort', 'migration')


def stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid_time')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # Source paytime is explicitly Beijing local time. Query timestamps use the same convention.
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def policy(value):
    points = tuple(value)
    if len(points) != 3 or any(type(v) is not int for v in points) or not 0 < points[0] < points[1] < points[2]:
        raise ValueError('invalid_policy')
    return points


def state(last, observation, points):
    days = (observation - last.date()).days
    if days < 0:
        raise ValueError('future_purchase')
    return STATES[sum(days >= p for p in policy(points))]


def checked_query(args, config, now=None):
    fields = {'view', 'scope', 'scope_id', 'start', 'end_exclusive', 'as_of', 'policy_version', 'policy_mode', 'snapshot_id', 'H'}
    if not isinstance(args, dict) or set(args) - fields or any(type(v) not in (str, int) for v in args.values()):
        raise ValueError('query_fields')
    if not {'start', 'end_exclusive'} <= set(args):
        raise ValueError('query_period_required')
    now = now or datetime.now(TZ)
    start, end = stamp(args['start']), stamp(args['end_exclusive'])
    if not start < end or end - start > timedelta(days=366):
        raise ValueError('invalid_period')
    if end > (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError('future_period')
    actual = stamp(args['as_of']) if 'as_of' in args else min(end, now)
    if not start < actual <= min(end, now):
        raise ValueError('invalid_as_of')
    if end <= now and actual != end:
        raise ValueError('historical_as_of_must_equal_end')
    view, scope = args.get('view', 'summary'), args.get('scope', 'global')
    sid = str(args.get('scope_id', ''))
    if view not in VIEWS or scope not in ('global', 'site', 'project', 'series'):
        raise ValueError('invalid_scope_or_view')
    if scope == 'global' and sid or scope != 'global' and not sid:
        raise ValueError('invalid_scope_id')
    if scope == 'site' and sid not in config['sites']:
        raise ValueError('site_not_connected')
    if scope == 'project' and (not sid.isdigit() or len(sid) > 10):
        raise ValueError('invalid_project_id')
    if scope == 'series' and sid not in {p.get('series') for p in config['projects'].values()}:
        raise ValueError('series_not_mapped')
    pv = args.get('policy_version', 'fc-v1' if scope == 'project' and sid == '1327' else 'common-v1')
    if pv not in config['policies']:
        raise ValueError('unknown_policy')
    policy(config['policies'][pv])
    mode = args.get('policy_mode', 'per_project')
    if mode not in ('per_project', 'uniform'):
        raise ValueError('invalid_policy_mode')
    horizon = args.get('H', 7)
    if type(horizon) is not int or horizon not in (7, 30):
        raise ValueError('invalid_horizon')
    return dict(view=view, scope=scope, scope_id=sid, start=start.isoformat(), end_exclusive=end.isoformat(),
                as_of=actual.isoformat(), policy_version=pv, policy_mode=mode, H=horizon)


def aggregate_only(value):
    forbidden = {'customer_id', 'customer_key', 'uid', 'order_no', 'order_key', 'email', 'phone', 'address', 'password', 'token', 'cookie', 'authorization'}
    if isinstance(value, dict):
        if set(value) & forbidden:
            raise ValueError('private_identity_in_aggregate')
        for child in value.values():
            aggregate_only(child)
    elif isinstance(value, list):
        for child in value:
            aggregate_only(child)

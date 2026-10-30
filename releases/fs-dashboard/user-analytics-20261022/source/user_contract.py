"""Deterministic purchase-customer contract. No source calls or model arithmetic."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
STATES = ('recent', 'silent', 'lost', 'long_lost')
OBSERVATION_POLICIES = {'short-term-v1': (7, 14, 30), 'long-term-v1': (14, 30, 60)}
POLICIES = {'common-v1': (30, 60, 90), 'fc-v1': (14, 30, 90), **OBSERVATION_POLICIES}
VIEWS = ('summary', 'trend', 'projects', 'transitions', 'cohort', 'migration', 'trajectories')
METRIC_DEFINITIONS = {key: dict(label=label, unit='customers', definition=definition) for key, label, definition in (
    ('purchasers', '区间购买客户', '有效区间内至少一次有效购买，按已核主邮箱去重'),
    ('first_purchasers', '已确认首次购买', '首付已由完整历史证实且发生在区间内；历史缺口不填成新客'),
    ('old_purchasers', '已确认老客购买', '区间内购买，且存在区间开始前的有效购买证据'),
    ('first_unverified', '首购身份待确认', '本期购买但无法证实窗前已买或真实历史首购'),
    ('repeat_purchasers', '区间复购客户', '区间内发生第二笔或之后的有效订单；可含本期首购客户'),
    ('silent_wakeup', '沉默唤醒客户', '本期购买前已进入沉默但尚未流失'),
    ('lost_return', '流失回流客户', '本期购买前已进入流失或长期流失'),
    ('known_pool', '已覆盖购买客户池', '截止前已识别且至少一笔有效购买的已覆盖客户，并非全部历史'),
    ('recent', '近期购买', '观察日距末次有效购买天数小于当前规则A'),
    ('silent', '沉默期', '观察日距末购达到A但未达到C'),
    ('lost', '流失期', '观察日距末购达到C但未达到L'),
    ('long_lost', '长期流失', '观察日距末购达到L'),
    ('unverified', '状态待核', '已识别客户的末购之后存在来源覆盖缺口'),
    ('entered_silent', '新进入沉默', '区间内发生沉默进入事件的去重客户；事件次数另列'),
    ('entered_lost', '新进入流失', '区间内发生流失进入事件的去重客户；不等于净变化'),
    ('entered_long_lost', '新进入长期流失', '区间内发生长期流失进入事件的去重客户'),
    ('high_value_entered_silent', '高价值且刚进入沉默', '已覆盖历史USD消费达到客户池第75百分位且本期进入沉默'),
    ('first_without_repeat', '已确认首购后尚未二购', '已确认本期首次购买，截止前未见另一笔有效订单；不等于成熟未留存'),
    ('new_purchasers', '后台标记新客', '所选期间第一笔有效订单的ES是否新客户为是；不冒充全历史独立证明'),
    ('old_flag_purchasers', '后台标记老客', '所选期间第一笔有效订单的ES是否新客户为否'),
    ('customer_type_unknown', '新老客标记待核', '期间第一笔有效订单的ES标记缺失、未匹配或冲突，不默认老客'),
    ('waiting', '待观察', '期间只买一笔且距末购尚未达到沉默阈值'),
    ('period_without_repeat', '期间首次下单后未再购买', '所选期间只有一笔有效订单；新老客均可，不等于已流失'),
)}


def money(value):
    if value is None or str(value).strip() in ('', '-', '—'):
        return None
    try:
        number = Decimal(re.sub(r'[$￥¥,\s]', '', str(value)))
        return format(number.normalize(), 'f') if number.is_finite() else None
    except InvalidOperation:
        return None


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
    fields = {'view', 'scope', 'scope_id', 'start', 'end_exclusive', 'as_of', 'state_basis', 'policy_version', 'policy_mode', 'snapshot_id', 'H'}
    if not isinstance(args, dict) or set(args) - fields or any(type(v) not in (str, int) for v in args.values()):
        raise ValueError('query_fields')
    if 'start' not in args:
        raise ValueError('query_period_required')
    now = now or datetime.now(TZ)
    weekly_cutoff = stamp(config['weekly_data_cutoff']) if config.get('weekly_data_cutoff') else None
    basis = args.get('state_basis', 'period_end' if 'as_of' in args else 'period_cohort')
    if basis not in ('current', 'period_end', 'period_cohort'):
        raise ValueError('invalid_state_basis')
    if basis == 'period_cohort':
        end = weekly_cutoff or now.replace(hour=0, minute=0, second=0, microsecond=0)
        if 'as_of' in args or 'end_exclusive' in args and stamp(args['end_exclusive']) != end:
            raise ValueError('period_cohort_ends_yesterday')
    elif 'end_exclusive' not in args:
        raise ValueError('query_period_required')
    else:
        end = stamp(args['end_exclusive'])
    start = stamp(args['start'])
    if weekly_cutoff and end > weekly_cutoff:
        raise ValueError('period_after_published_data')
    if not start < end or end - start > timedelta(days=366):
        raise ValueError('invalid_period')
    if end > (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError('future_period')
    actual = stamp(args['as_of']) if 'as_of' in args else now if basis == 'current' else min(end, now)
    if weekly_cutoff and basis == 'current':
        actual = weekly_cutoff - timedelta(microseconds=1)
    if not start < actual <= now or basis == 'period_end' and actual > end:
        raise ValueError('invalid_as_of')
    if basis == 'period_end' and end <= now and actual != end:
        raise ValueError('historical_as_of_must_equal_end')
    if basis == 'current' and 'as_of' in args:
        raise ValueError('current_uses_server_clock')
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
    fc_scope = scope == 'project' and config['projects'].get(sid, {}).get('series') == 'FC' or scope == 'series' and sid == 'FC'
    pv = args.get('policy_version', 'fc-v1' if fc_scope else 'common-v1')
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
                as_of=actual.isoformat(), state_basis=basis, policy_version=pv, policy_mode=mode, H=horizon)


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

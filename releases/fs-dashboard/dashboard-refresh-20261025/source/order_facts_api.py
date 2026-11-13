"""Authorized aggregate-only D2 reads, using the existing channel worker budget."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import csv
import hashlib
import io
import json
import math
import re
import time

from order_facts import summarize

VERSION = 'order-facts-api-20261113-v1'
CHANNELS = ('all', 'SEO', 'Direct', 'PPC', 'Referral', 'Campaign', 'unknown')
ACTIVE = ('pending', 'cost_pending')


def aggregate_csv(result):
    output = io.StringIO()
    writer = csv.writer(output)
    scope = result['effective_scope']
    writer.writerow(('开始日期','结束日期','站点ID','游戏ID','渠道筛选','时区','时间口径',
                     '快照版本','事实定义','归因定义','来源修订','同单核算口径','未分配到日的订单'))
    writer.writerow((scope['start'],scope['end'],scope['site_id'],scope['gid'],scope['channel'],
                     result['source_timezone'],result['time_basis'],result['snapshot_id'],result['facts_version'],
                     result['attribution_version'],json.dumps(result['revisions'],sort_keys=True),
                     result['totals']['accounting_basis'],result['trend_unallocated_orders']))
    writer.writerow(('维度','项目','范围状态','已知订单数','已知美元金额','缺美元金额订单数',
                     '已读采购人民币','已核同单毛利人民币','完整成本订单数'))
    for kind, key, rows in (('渠道','channel',result['channels']),('日期','day',result['trend'])):
        for row in rows:
            usd = row['admin_paid_usd'] if row['orders'] != row['missing_admin_usd_orders'] or not row['orders'] else None
            cost = row['observed_cost_cny'] if kind == '日期' or row['cost_records'] else None
            writer.writerow((kind,row[key],row.get('status',result['status']),row['orders'],usd,
                             row['missing_admin_usd_orders'],cost,
                             row['procurement_gross_cny'],row['cost_covered_orders']))
    return '\ufeff' + output.getvalue()


def selection(params):
    allowed = {'mode', 'start', 'end', 'site_id', 'gid', 'channel', 'refresh'}
    if set(params) - allowed or any(not isinstance(v, list) or len(v) != 1 or
            not isinstance(v[0], str) or len(v[0]) > 80 for v in params.values()):
        raise ValueError('order_facts_parameters')
    q = {k: v[0] for k, v in params.items()}
    if q.pop('mode', None) != 'order-facts':raise ValueError('order_facts_mode')
    if 'refresh' in q and q['refresh'] != '1':raise ValueError('order_facts_refresh')
    start, end = (date.fromisoformat(q.get(k, '')) for k in ('start', 'end'))
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if (start.isoformat() != q['start'] or end.isoformat() != q['end'] or
            not 0 <= (end-start).days < 28 or end > today or start < today-timedelta(days=365)):
        raise ValueError('order_facts_period')
    for key in ('site_id', 'gid'):
        q.setdefault(key, 'all')
        if q[key] != 'all' and not re.fullmatch(r'[1-9][0-9]{0,9}', q[key]):
            raise ValueError('order_facts_dimension')
    q.setdefault('channel', 'all')
    if q['channel'] not in CHANNELS:raise ValueError('order_facts_channel')
    return q


def public(data, q, games=()):
    """Never copy raw inputs, original order keys, or arbitrary source metadata."""
    scope = {k: q[k] for k in ('start', 'end', 'site_id', 'gid')}
    if any(data.get('input_scope', {}).get(k) != v for k, v in scope.items()):
        raise ValueError('order_facts_source_scope')
    rows = data['orders']
    selected = []
    groups, daily = defaultdict(list), defaultdict(list)
    unknown_days = set()
    unallocated = 0
    specific_channel = q['channel'] not in ('all','unknown')
    for row in rows:
        channel = row['channel']
        match = q['channel'] == 'all' or channel == q['channel']
        if not match and not (specific_channel and channel == 'unknown'):
            continue
        try:
            paid_at = datetime.strptime(row['paid_at'], '%Y-%m-%d %H:%M:%S')
            day = paid_at.date().isoformat()
            if not q['start'] <= day <= q['end']:
                day = None
        except (TypeError, ValueError):
            day = None
        if match:
            selected.append(row)
            groups[channel].append(row)
            if day:
                daily[day].append(row)
            else:
                unallocated += 1
        if channel == 'unknown':
            unknown_days.add(day)
    # Coverage counts describe the source cohort; totals describe the selection.
    coverage = {k: v for k, v in data.get('coverage', {}).items()
                if k in ('linked_orders', 'unlinked_admin_rows', 'unlinked_attribution_rows',
                         'unlinked_cost_records', 'duplicate_admin_rows', 'duplicate_cost_rows')
                and type(v) is int and v >= 0}
    source = data.get('source_coverage', {})
    revisions = {k: source[k] for k in ('source_revision', 'data_revision', 'publication_id')
                 if type(source.get(k)) in (str, int)}
    cost = source.get('cost', {})
    revisions['cost'] = {k:cost[k] for k in ('source_revision','generated_at','status')
                         if isinstance(cost.get(k),str)}
    revisions['cost']['period'] = {k:v for k,v in (cost.get('period') or {}).items()
                                    if k in ('start','end','until') and isinstance(v,str)}
    revisions['cost']['order_cost_complete'] = cost.get('order_cost_complete') is True
    revisions['cost']['shipment_window_complete'] = cost.get('shipment_window_complete') is True
    attribution = source.get('attribution', {})
    revisions['attribution'] = {k: attribution[k] for k in
        ('source_revision', 'data_revision', 'publication_id', 'identity_revision', 'available_at')
        if type(attribution.get(k)) in (str, int)}
    bridge = {k: v for k, v in attribution.get('bridge_counts', {}).items()
              if k in ('linked', 'identity_coverage_unverified', 'cross_site_ambiguous',
                       'identity_unmatched', 'site_label_unverified', 'order_status_revision_mismatch') and type(v) is int and v >= 0}
    coverage['attribution'] = dict(
        status=attribution.get('status') if attribution.get('status') in
            ('available', 'partial', 'unavailable') else 'unavailable',
        identity_status='complete' if attribution.get('identity_status') == 'complete' else 'unverified',
        bridge_counts=bridge)
    admin_complete = source.get('admin_complete') is True and data['status'] == 'available'
    trend = []
    day = date.fromisoformat(q['start'])
    end = date.fromisoformat(q['end'])
    while day <= end:
        key = day.isoformat()
        summary = summarize(daily[key])
        orders = summary['orders']
        complete = admin_complete and not unallocated and not (specific_channel and (key in unknown_days or None in unknown_days))
        missing_usd = summary['missing_admin_usd_orders']
        missing_cny = summary['missing_admin_cny_orders']
        # Zero means a known empty day or known zero amounts. Missing data stays blank.
        usd_known = orders > missing_usd if orders else complete
        cny_known = orders > missing_cny if orders else complete
        trend.append(dict(day=key, orders=orders,
            status='available' if complete and not (missing_usd or missing_cny) else 'partial',
            admin_paid_usd=summary['admin_paid_usd'] if usd_known else None,
            admin_paid_cny=summary['admin_paid_cny'] if cny_known else None,
            missing_admin_usd_orders=missing_usd, missing_admin_cny_orders=missing_cny,
            observed_cost_cny=summary['observed_cost_cny'] if summary['cost_records'] else None,
            procurement_gross_cny=summary['procurement_gross_cny'],
            cost_covered_orders=summary['cost_covered_orders'],
            gross_covered_orders=summary['gross_covered_orders']))
        day += timedelta(days=1)
    status = 'partial' if any(row['status'] == 'partial' for row in trend) else data['status']
    result = dict(version=VERSION, facts_version=data['version'],
                attribution_version=data['attribution_version'], status=status,
                requested_scope=deepcopy(q), effective_scope={**scope,'channel':q['channel']},
                channel_filter='derived_order_facts', coverage_scope=scope,
                totals=summarize(selected),
                channels=[dict(channel=k, **summarize(v)) for k, v in sorted(groups.items())],
                trend=trend, trend_unallocated_orders=unallocated, coverage=coverage, revisions=revisions,
                source_timezone='Asia/Shanghai', time_basis='Admin paytime',
                captured_at=source.get('captured_at'), options={'games':deepcopy(list(games))},
                admin_complete=source.get('admin_complete') is True,
                readonly=True, private=True)
    revision_input = {k: v for k, v in result.items() if k not in ('options','captured_at')}
    result['snapshot_id'] = 'order-facts-' + hashlib.sha256(
        json.dumps(revision_input, sort_keys=True).encode()).hexdigest()[:24]
    result['aggregate_csv'] = aggregate_csv(result)
    return result


class OrderFactsService:
    def __init__(self, channels, source, clock=time.monotonic, *, games=()):
        self.channels, self.source, self.clock = channels, source, clock
        self.games = deepcopy(list(games))
        self.entries = {}

    def capture(self, key, q):
        try:
            with self.channels.admission():
                value = public(self.source({k: q[k] for k in ('start', 'end', 'site_id', 'gid')}), q, self.games)
            state = 'available'
        except PermissionError:
            value, state = None, 'denied'
        except BlockingIOError:
            value, state = None, 'deferred'
        except Exception:
            # Exception messages may contain upstream original order identifiers.
            value, state = None, 'source_failed'
        with self.channels.lock:
            self.entries[key].update(state=state, value=value, finished=self.clock())
            self.channels.jobs.pop(key, None)

    def get(self, params, user):
        if not user or not self.channels.authorizer(user):
            return 403, {'status': 'denied', 'error': 'admin_required'}
        q = selection(params)
        force = q.pop('refresh', None) == '1'
        key = 'order-facts:' + hashlib.sha256(json.dumps([user, q], sort_keys=True).encode()).hexdigest()
        with self.channels.lock:
            now = self.clock()
            entry = self.entries.get(key)
            if entry and entry['state'] == 'pending':return 202, {'status': 'pending', 'retryAfter': 3}
            if entry and entry['state'] == 'available' and 0 <= now-entry['finished'] < 600:
                if not force:return 200, deepcopy(entry['value'])
                if now-entry['finished'] < 60:
                    return 200, dict(deepcopy(entry['value']), refresh_deferred=True,
                        refresh_reason='recent_capture', retryAfter=math.ceil(60-(now-entry['finished'])))
            if entry and 0 <= now-entry['started'] < 60:
                code = 403 if entry['state'] == 'denied' else 503
                return code, {'status': entry['state'], 'retryAfter': 60}
            active = sum(v in ACTIVE for v in self.channels.jobs.values()) + sum(
                v in ACTIVE for v in getattr(self.channels, 'actual_jobs', {}).values())
            if active >= 2:
                if force and entry and entry['state'] == 'available':
                    return 200, dict(deepcopy(entry['value']), refresh_deferred=True,
                        refresh_reason='shared_workers_busy', retryAfter=10)
                return 429, {'status': 'busy', 'retryAfter': 10}
            if key not in self.entries and len(self.entries) >= 32:
                victim = next((k for k, v in self.entries.items() if v['state'] != 'pending'), None)
                if victim is None:return 429, {'status': 'busy', 'retryAfter': 10}
                self.entries.pop(victim)
            try:
                with self.channels.admission():
                    self.entries[key] = dict(state='pending', started=now)
                    self.channels.jobs[key] = 'pending'
                    self.channels.pool.submit(self.capture, key, deepcopy(q))
            except Exception as error:
                self.channels.jobs.pop(key, None)
                state = 'deferred' if isinstance(error, BlockingIOError) else 'source_failed'
                self.entries[key] = dict(state=state, started=now, finished=now, value=None)
                return 503, {'status': state, 'retryAfter': 60}
        return 202, {'status': 'pending', 'retryAfter': 3}

"""Authorized aggregate-only D2 reads, using the existing channel worker budget."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import re
import time

from order_facts import summarize

VERSION = 'order-facts-api-20261113-v1'
CHANNELS = ('all', 'SEO', 'Direct', 'PPC', 'Referral', 'Campaign', 'unknown')
ACTIVE = ('pending', 'cost_pending')


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
    selected = [r for r in rows if q['channel'] == 'all' or r['channel'] == q['channel']]
    groups = defaultdict(list)
    for row in selected:groups[row['channel']].append(row)
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
    return dict(version=VERSION, facts_version=data['version'],
                attribution_version=data['attribution_version'], status=data['status'],
                requested_scope=deepcopy(q), effective_scope=scope,
                channel_filter='derived_order_facts', coverage_scope=scope,
                totals=summarize(selected),
                channels=[dict(channel=k, **summarize(v)) for k, v in sorted(groups.items())],
                coverage=coverage, revisions=revisions, options={'games':deepcopy(list(games))},
                admin_complete=source.get('admin_complete') is True,
                readonly=True, private=True)


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

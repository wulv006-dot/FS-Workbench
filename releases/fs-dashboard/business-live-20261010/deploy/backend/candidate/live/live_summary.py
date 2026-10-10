"""Shared, bounded summary cache. The existing authenticated range route is its only caller."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta, timezone
from threading import RLock
import copy, hashlib, json, time

SHANGHAI = timezone(timedelta(hours=8))
TTL = 120
CONTRACT = 'admin-main-order-labelled-supplement-v1'
SITE = 'www.mmoexp.com'

def query(params, profiles, now=None):
    if set(params) - {'mode', 'profile', 'start', 'end', 'grain'} or any(len(v) != 1 for v in params.values()):
        raise ValueError('invalid_parameters')
    p = {k: v[0] for k, v in params.items()}
    if p.get('mode') != 'summary' or p.get('profile') not in profiles:
        raise ValueError('invalid_summary')
    now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).replace(second=0, microsecond=0)
    grain = p.get('grain', 'day')
    start, end = p.get('start', ''), p.get('end', '')
    if grain == 'day':
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        if lo.isoformat() != start or hi.isoformat() != end:
            raise ValueError('invalid_date')
        begin = datetime.combine(lo, datetime.min.time(), SHANGHAI)
        stop = datetime.combine(hi + timedelta(days=1), datetime.min.time(), SHANGHAI)
    elif grain == 'hour':
        begin = datetime.strptime(start, '%Y-%m-%d %H:%M').replace(tzinfo=SHANGHAI)
        last = datetime.strptime(end, '%Y-%m-%d %H:%M').replace(tzinfo=SHANGHAI)
        if begin.strftime('%Y-%m-%d %H:00') != start or last.strftime('%Y-%m-%d %H:00') != end:
            raise ValueError('invalid_hour')
        lo, hi = begin.date(), last.date()
        stop = last + timedelta(hours=1)
    else:
        raise ValueError('invalid_grain')
    if stop <= begin or begin >= now or hi > now.date() or (hi - lo).days > 365:
        raise ValueError('invalid_period')
    return {'profile': p['profile'], 'start': start, 'end': end, 'grain': grain,
            'site': SITE, 'contractId': CONTRACT, 'timezone': 'Asia/Shanghai',
            'period': {'start': begin.strftime('%Y-%m-%d %H:%M'), 'end': min(stop, now).strftime('%Y-%m-%d %H:%M')}}

def key_of(q):
    # Query cutoff advances without changing the shared selection key.
    return hashlib.sha256(json.dumps({k: v for k, v in q.items() if k != 'period'}, sort_keys=True).encode()).hexdigest()

def missing(system, period, status='unavailable'):
    return {'system': system, 'status': status, 'period': period, 'currency': 'USD',
            'orders': None, 'revenueUsd': None, 'metrics': {}, 'dimensions': {},
            'capturedAt': None, 'sourceDataAsOf': None}

class SummaryCache:
    def __init__(self, admin_read, order_read, profiles, fallback=None, clock=time.monotonic):
        self.readers = {'Admin': admin_read, 'Order': order_read}
        self.profiles, self.fallback, self.clock = profiles, fallback, clock
        self.pools = {name: ThreadPoolExecutor(max_workers=1) for name in self.readers}
        self.lock, self.entries, self.starts = RLock(), {}, []

    def close(self):
        for pool in self.pools.values():
            pool.shutdown(wait=True)

    def capture(self, name, q, slot):
        try:
            record = self.readers[name](q)
            if record.get('status') != 'available' or record.get('period') != q['period']:
                raise ValueError('source_period_or_status')
            stamp = datetime.fromisoformat(record['capturedAt']).astimezone(timezone.utc)
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if age < -30 or age > TTL:
                raise ValueError('source_capture_stale')
            value = copy.deepcopy(record)
            value['sourceDataAsOf'] = record.get('sourceDataAsOf')
            with self.lock:
                slot.update(value=value, at=self.clock(), state='available', error=None)
        except Exception as exc:
            with self.lock:
                slot.update(at=self.clock(), state='denied' if isinstance(exc, PermissionError) else 'unavailable',
                            error='permission_denied' if isinstance(exc, PermissionError) else 'source_read_failed')

    def get(self, q):
        key, now = key_of(q), self.clock()
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= 256:
                    victim = next((k for k, e in self.entries.items() if all(s['state'] != 'pending' for s in e.values())), None)
                    if victim is None:
                        return 429, {'status': 'busy', 'retryAfter': 10}
                    self.entries.pop(victim)
                entry = self.entries[key] = {n: {'state': 'new', 'at': -float('inf'), 'value': None} for n in self.readers}
            if any(s['state'] == 'denied' and now - s['at'] < 30 for s in entry.values()):
                for s in entry.values():
                    s['value'] = None
                return 403, {'status': 'denied', 'error': 'source_permission_denied'}
            due = [n for n, s in entry.items() if s['state'] != 'pending' and
                   now - s['at'] >= (TTL if s['state'] == 'available' else 30)]
            self.starts[:] = [t for t in self.starts if now - t < 60]
            active = sum(any(s['state'] == 'pending' for s in e.values()) for e in self.entries.values())
            throttled = bool(due) and (active >= 4 or len(self.starts) >= 6)
            if due and not throttled:
                self.starts.append(now)
                # Each source has its own worker; a slow/failing Order cannot hold Admin.
                for name in due:
                    slot = entry[name]
                    slot['state'] = 'pending'
                    self.pools[name].submit(self.capture, name, copy.deepcopy(q), slot)
            admin, order = entry['Admin'], entry['Order']
            if admin['state'] == 'denied' or order['state'] == 'denied':
                for s in entry.values():
                    s['value'] = None
                return 403, {'status': 'denied', 'error': 'source_permission_denied'}
            a, o = copy.deepcopy(admin['value']), copy.deepcopy(order['value'])
            stale = admin['state'] != 'available' or now - admin['at'] >= TTL
            origin = 'live-cache'
            if a is None and self.fallback:
                try:
                    old = self.fallback(q)
                    if old:
                        a, o, origin = old.get('supplement'), old.get('primary'), 'historical-snapshot'
                        stale = True
                except (OSError, ValueError, KeyError, AssertionError):
                    pass
            if a is None:
                status = 429 if throttled else 202 if admin['state'] == 'pending' else 503
                return status, {'schemaVersion': 1, 'status': 'busy' if throttled else 'pending' if status == 202 else 'unavailable',
                                'query': q, 'rangeId': key, 'retryAfter': 2 if status == 202 else 10}
            # Never apply an old/different-period margin to a newly captured Admin amount.
            if o is None or o.get('period') != a['period'] or order['state'] == 'unavailable' or (origin == 'live-cache' and now - order['at'] >= TTL):
                o = missing('order.p2pah.cn', a['period'], 'pending' if order['state'] == 'pending' else 'unavailable')
            profile = {'key': q['profile'], 'name': self.profiles[q['profile']][1], 'period': a['period'],
                       'primary': o, 'supplement': a, 'metrics': o.get('metrics', {}), 'dimensions': o.get('dimensions', {})}
            freshness = {n: {'status': s['state'], 'capturedAt': (a if n == 'Admin' else o).get('capturedAt'),
                             'sourceDataAsOf': (a if n == 'Admin' else o).get('sourceDataAsOf'),
                             'asOfStatus': 'upstream_watermark_unknown' if not (a if n == 'Admin' else o).get('sourceDataAsOf') else 'provided',
                             'stale': stale if n == 'Admin' else o['status'] != 'available'} for n, s in entry.items()}
            return 200, {'schemaVersion': 1, 'status': 'stale' if stale else 'available', 'query': q, 'rangeId': key,
                         'profile': profile, 'timezone': 'Asia/Shanghai', 'currency': 'USD', 'origin': origin,
                         'stale': stale, 'sources': freshness, 'generatedAt': a['capturedAt'],
                         'refreshSeconds': TTL, 'clientCheckSeconds': 60,
                         'expiresInSeconds': max(0, TTL - (now - admin['at'])) if not stale else 0,
                         'consistentPeriod': True, 'scopeContractId': CONTRACT}

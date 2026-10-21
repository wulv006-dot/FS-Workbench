"""Shared, bounded summary cache. The existing authenticated range route is its only caller."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta, timezone
from threading import RLock
import copy, hashlib, json, time

SHANGHAI = timezone(timedelta(hours=8))
TTL = 900
HISTORY_TTL = 7200
CAPTURE_MAX_AGE = 120
STALE_GRACE = 180
STALE_LIMIT = TTL + STALE_GRACE
CONTRACT = 'admin-main-order-labelled-supplement-v1'
SITE = 'www.mmoexp.com'

def query(params, profiles, now=None):
    if set(params) - {'mode', 'profile', 'start', 'end', 'grain', 'refresh'} or any(len(v) != 1 for v in params.values()):
        raise ValueError('invalid_parameters')
    p = {k: v[0] for k, v in params.items()}
    if p.get('mode') != 'summary' or p.get('profile') not in profiles:
        raise ValueError('invalid_summary')
    if 'refresh' in p and p['refresh'] != 'true':
        raise ValueError('invalid_refresh')
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
            **({'refresh': True} if p.get('refresh') == 'true' else {}),
            'cacheSeconds': TTL if hi == now.date() else HISTORY_TTL,
            'cachePolicy': 'today' if hi == now.date() else 'historical',
            'period': {'start': begin.strftime('%Y-%m-%d %H:%M'), 'end': min(stop, now).strftime('%Y-%m-%d %H:%M')}}

def key_of(q):
    # Query cutoff advances without changing the shared selection key.
    return hashlib.sha256(json.dumps({k: v for k, v in q.items() if k not in ('period', 'refresh')}, sort_keys=True).encode()).hexdigest()

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
        self.coherent = {}

    def close(self):
        for pool in self.pools.values():
            pool.shutdown(wait=True)

    def capture(self, name, q, slot):
        with self.lock:
            slot.update(startedAt=self.clock(), phase='reading')
        try:
            record = self.readers[name](q)
            if record.get('status') != 'available' or record.get('period') != q['period']:
                raise ValueError('source_period_or_status')
            stamp = datetime.fromisoformat(record['capturedAt']).astimezone(timezone.utc)
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if age < -30 or age > CAPTURE_MAX_AGE:
                raise ValueError('source_capture_stale')
            value = copy.deepcopy(record)
            value['sourceDataAsOf'] = record.get('sourceDataAsOf')
            with self.lock:
                slot.update(value=value, at=self.clock(), valueAt=self.clock(), finishedAt=self.clock(), state='available', phase='available', error=None)
        except Exception as exc:
            with self.lock:
                error = ('permission_denied' if isinstance(exc, PermissionError) else
                         'collector_busy' if isinstance(exc, BlockingIOError) else
                         'scheduled_collection_due' if str(exc) == 'scheduled_collection_due' else
                         'source_read_failed')
                slot.update(at=self.clock(), finishedAt=self.clock(), state='denied' if isinstance(exc, PermissionError) else 'unavailable',
                            phase='deferred' if error in ('collector_busy', 'scheduled_collection_due') else 'failed', error=error)
        self.persist_complete(q)

    def persist_complete(self, q):
        from daily_archive import save, summary_key, complete_summary
        with self.lock:
            entry = self.entries.get(key_of(q))
            if not entry or any(s['state'] != 'available' for s in entry.values()): return
            code, value = self.get_live(q)
        if code == 200 and complete_summary(value): save('summary', summary_key(q), value)

    def progress(self, slot):
        now = self.clock()
        queued, started, finished = slot.get('queuedAt'), slot.get('startedAt'), slot.get('finishedAt')
        return {'phase': slot.get('phase', 'queued'), 'error': slot.get('error'),
                'queueSeconds': round(max(0, (started if started is not None else now) - queued), 3) if queued is not None else 0,
                'readSeconds': round(max(0, (finished if finished is not None else now) - started), 3) if started is not None else 0}

    def get(self, q):
        from daily_archive import read, save, summary_key, complete_summary, derive_summary
        selector = summary_key(q)
        if not q.get('refresh'):
            archived = read('summary', selector)
            if archived is not None:
                archived['origin'] = 'dated-archive'
                at = datetime.fromisoformat(archived['archive']['sourceCapturedAt'])
                if (datetime.now(timezone.utc)-at).total_seconds() < HISTORY_TTL:
                    return 200, archived
                code, current = self.get_live(q)
                if code == 403: return code, current
                if code == 200 and complete_summary(current):
                    save('summary', selector, current)
                    return code, current
                archived['archive']['refreshing'] = True
                return 200, archived
        derived = derive_summary(selector) if not q.get('refresh') else None
        if derived is not None: derived['query'] = copy.deepcopy(q)
        code, value = self.get_live(q)
        if code == 200 and complete_summary(value): save('summary', selector, value)
        elif derived is not None and code != 403:
            derived['archive']['nativeStatus'] = value.get('status')
            return 200, derived
        return code, value

    def get_live(self, q):
        key, now = key_of(q), self.clock()
        ttl = q.get('cacheSeconds', TTL)
        stale_limit = ttl + STALE_GRACE
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= 256:
                    victim = next((k for k, e in self.entries.items() if all(s['state'] != 'pending' for s in e.values())), None)
                    if victim is None:
                        return 429, {'status': 'busy', 'retryAfter': 10}
                    self.entries.pop(victim)
                    self.coherent.pop(victim, None)
                entry = self.entries[key] = {n: {'state': 'new', 'at': -float('inf'), 'value': None} for n in self.readers}
            if any(s['state'] == 'denied' and now - s['at'] < 30 for s in entry.values()):
                self.coherent.pop(key, None)
                for s in entry.values():
                    s['value'] = None
                return 403, {'status': 'denied', 'error': 'source_permission_denied'}
            due = [n for n, s in entry.items() if s['state'] != 'pending' and
                   (q.get('refresh') and s['state'] == 'available' or
                    now - s['at'] >= (ttl if s['state'] == 'available' else 30))]
            read_query = copy.deepcopy(q)
            read_query.pop('refresh', None)
            if 'Admin' not in due and entry['Admin']['value'] is not None:
                read_query['period'] = entry['Admin']['value']['period']
            elif entry['Order']['state'] == 'pending' and entry['Order'].get('requestPeriod'):
                read_query['period'] = entry['Order']['requestPeriod']
            elif 'Admin' in due and entry['Order']['value'] is not None and entry['Order']['value']['period'] != q['period'] and 'Order' not in due:
                due.append('Order')
            self.starts[:] = [t for t in self.starts if now - t < 60]
            active = sum(any(s['state'] == 'pending' for s in e.values()) for e in self.entries.values())
            throttled = bool(due) and (active >= 4 or len(self.starts) >= 6)
            if due and not throttled:
                self.starts.append(now)
                # Each source has its own worker; a slow/failing Order cannot hold Admin.
                for name in due:
                    slot = entry[name]
                    slot.update(state='pending', phase='queued', queuedAt=self.clock(), startedAt=None, finishedAt=None, error=None, requestPeriod=read_query['period'])
                    self.pools[name].submit(self.capture, name, copy.deepcopy(read_query), slot)
            if q.get('refresh') and throttled:
                return 429, {'status': 'busy', 'retryAfter': 10}
            admin, order = entry['Admin'], entry['Order']
            if admin['state'] == 'denied' or order['state'] == 'denied':
                self.coherent.pop(key, None)
                for s in entry.values():
                    s['value'] = None
                return 403, {'status': 'denied', 'error': 'source_permission_denied'}
            a, o = copy.deepcopy(admin['value']), copy.deepcopy(order['value'])
            stale = admin['state'] != 'available' or now - admin['at'] >= ttl
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
                                'query': q, 'rangeId': key, 'retryAfter': 2 if status == 202 else 10,
                                'sources': {n: {'status': s['state'], **self.progress(s)} for n, s in entry.items()}}
            order_age = now - order.get('valueAt', order['at'])
            refreshing = order['state'] in ('pending', 'unavailable') or throttled
            # Retain one bounded, coherent pair during refresh; never blend cutoffs.
            previous = self.coherent.get(key)
            if origin == 'live-cache' and o is not None and o.get('period') == a['period'] and admin['state'] == order['state'] == 'available':
                self.coherent[key] = (copy.deepcopy(a), copy.deepcopy(o), min(admin.get('valueAt', admin['at']), order.get('valueAt', order['at'])))
            elif origin == 'live-cache' and refreshing and previous and now - previous[2] < stale_limit and (o is None or o.get('period') != a['period']):
                a, o = copy.deepcopy(previous[:2])
                stale = True
                order_age = now - previous[2]
            retained = origin == 'live-cache' and o is not None and o.get('period') == a['period'] and refreshing and order_age < stale_limit
            # Completed fresh source omissions are authoritative; prior metrics are not filled in.
            if o is None or o.get('period') != a['period'] or (not retained and (order['state'] == 'unavailable' or (origin == 'live-cache' and order_age >= ttl))):
                o = missing('order.p2pah.cn', a['period'], 'pending' if order['state'] == 'pending' else 'unavailable')
            o['stale'] = origin == 'historical-snapshot' or retained or o['status'] != 'available' or order_age >= ttl
            o['readPhase'] = 'period-mismatch' if o['status'] == 'unavailable' and order['state'] == 'available' else self.progress(order)['phase']
            profile = {'key': q['profile'], 'name': self.profiles[q['profile']][1], 'period': a['period'], 'cachePolicy': q.get('cachePolicy'),
                       'primary': o, 'supplement': a, 'metrics': o.get('metrics', {}), 'dimensions': o.get('dimensions', {})}
            freshness = {n: {'status': s['state'], 'capturedAt': (a if n == 'Admin' else o).get('capturedAt'),
                             'sourceDataAsOf': (a if n == 'Admin' else o).get('sourceDataAsOf'),
                             'asOfStatus': 'upstream_watermark_unknown' if not (a if n == 'Admin' else o).get('sourceDataAsOf') else 'provided',
                             'stale': stale if n == 'Admin' else o['stale'],
                             **self.progress(s)} for n, s in entry.items()}
            return 200, {'schemaVersion': 1, 'status': 'stale' if stale else 'available', 'query': q, 'rangeId': key,
                         'profile': profile, 'timezone': 'Asia/Shanghai', 'currency': 'USD', 'origin': origin,
                         'stale': stale, 'sources': freshness, 'generatedAt': a['capturedAt'],
                         'refreshSeconds': ttl, 'cachePolicy': q.get('cachePolicy'), 'clientCheckSeconds': ttl,
                         'expiresInSeconds': max(0, ttl - (now - admin['at'])) if not stale else 0,
                         'consistentPeriod': True, 'scopeContractId': CONTRACT}

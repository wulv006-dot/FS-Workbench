"""Project-scoped machine reads over the existing FS snapshot/range service."""
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, BoundedSemaphore
from urllib.parse import urlsplit, parse_qs, urlencode
import argparse
import hmac
import http.client
import json
import math
import re
import time

VERSION = 'fs-query-v1-20261012'
WEB = Path('/var/www/dashboard/fs-home/transactions')
REGISTRY = Path('/etc/fs-query-api/clients.json')
POLICY = 'admin-main-order-labelled-supplement-v1'
METRICS = ('orders', 'revenueUsd', 'averageOrderUsd', 'newCustomers',
           'repeatRatePct', 'fulfillmentRatePct', 'profitMarginPct', 'estimatedProfitUsd')
PROFIT = {'profitMarginPct', 'estimatedProfitUsd'}
MAIN = 'MMOEXP'
ADMIN_REFERENCE = '后台原统计范围（含其他站点），仅参考'
ORDER_REFERENCE = '后台全站参考；与 Admin 主站口径不同'
LIMIT_LOCK = Lock()
STARTS = {}
INFLIGHT = BoundedSemaphore(2)


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def number(v):
    return type(v) in (int, float) and math.isfinite(v)


def authenticate(header, now=None):
    if not re.fullmatch(r'Bearer fsq_[A-Za-z0-9_-]{43}', header or ''):
        raise Rejected(401, 'invalid_credentials')
    hashed = sha256(header[7:].encode()).hexdigest()
    now = time.time() if now is None else now
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    for client in registry['clients']:
        if hmac.compare_digest(hashed, client['tokenSha256']):
            if not client.get('enabled') or client['expiresAtEpoch'] <= now:
                break
            projects = client.get('projects')
            if not isinstance(projects, list) or not projects or any(not isinstance(p, str) for p in projects):
                raise Rejected(503, 'client_configuration_invalid')
            if '*' in projects and (projects != ['*'] or client.get('id') != 'dy-all-projects' or client.get('owner') != 'DY'):
                raise Rejected(503, 'client_configuration_invalid')
            return client
    raise Rejected(401, 'invalid_credentials')


def throttle(client):
    now = time.monotonic()
    with LIMIT_LOCK:
        recent = [t for t in STARTS.get(client['id'], []) if now-t < 60]
        if len(recent) >= 30:
            raise Rejected(429, 'rate_limited')
        STARTS[client['id']] = recent + [now]


def snapshot():
    # Compatibility name: return source capabilities, never a transaction snapshot.
    status, data = upstream({'mode': 'catalog'})
    if status != 200 or data.get('schemaVersion') != 2 or not re.fullmatch(r'catalog-[a-f0-9]{16}', data.get('catalogId', '')):
        raise ValueError('invalid_catalog')
    return data


def params(query, client):
    try:
        p = parse_qs(query, keep_blank_values=True, max_num_fields=5)
        if set(p) != {'profile', 'start', 'end'} or any(len(v) != 1 for v in p.values()):
            raise ValueError()
        p = {k: v[0] for k, v in p.items()}
        if client['projects'] != ['*'] and p['profile'] not in client['projects']:
            raise Rejected(403, 'project_forbidden')
        if any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', p[k]) for k in ('start', 'end')):
            raise ValueError()
        lo, hi = date.fromisoformat(p['start']), date.fromisoformat(p['end'])
        if not 0 <= (hi-lo).days <= 365:
            raise ValueError()
        return p
    except ValueError:
        raise Rejected(400, 'invalid_parameters')


def upstream(p):
    conn = http.client.HTTPConnection('127.0.0.1', 8931, timeout=10)
    try:
        conn.request('GET', '/range?'+urlencode(p), headers={'X-Auth-User': 'fs-query-api'})
        response = conn.getresponse()
        if 'application/json' not in (response.getheader('Content-Type') or ''):
            raise ValueError('upstream_not_json')
        raw = response.read(4*1024*1024+1)
        if len(raw) > 4*1024*1024:
            raise ValueError('upstream_too_large')
        return response.status, json.loads(raw)
    finally:
        conn.close()

def exact_range(p, sid):
    return upstream(dict(p, grain='day', mode='summary'))


def project_metrics(profile, include_profit):
    admin, order = profile.get('supplement') or {}, profile.get('primary') or {}
    ap, op = admin.get('period') or {}, order.get('period') or {}
    available = admin.get('status') == 'available' and bool(ap.get('start'))
    rows = (admin.get('dimensions') or {}).get('channels') or []
    main = [r for r in rows if (r.get('code') or r.get('name')) == 'www.mmoexp.com'] if available else []
    row = main[0] if len(main) == 1 else None
    scope = MAIN if row is not None and len(rows) == 1 else ADMIN_REFERENCE

    def field(value=None, source='Admin', field_scope=scope, captured=None):
        return dict(value=value, status='available' if value is not None else 'not_provided',
                    source=source, scope=field_scope, capturedAt=captured)

    metrics = {}
    for key in METRICS:
        item = (admin.get('metrics') or {}).get(key) or {}
        metrics[key] = field(item.get('value') if key not in PROFIT and available and item.get('status') == 'available'
                             and number(item.get('value')) else None, captured=admin.get('capturedAt'))
    for key in ('orders', 'revenueUsd'):
        val = row.get(key) if row is not None else None
        valid = number(val) and (key != 'orders' or val >= 0 and int(val) == val and val <= 9007199254740991)
        if available and not rows and all((admin.get('metrics') or {}).get(k, {}).get('value') == 0
                                         for k in ('orders', 'revenueUsd')):
            val, valid = 0, True
        metrics[key] = field(val if valid else None, field_scope=MAIN, captured=admin.get('capturedAt'))
    for key in ('profitMarginPct', 'averageOrderUsd', 'fulfillmentRatePct'):
        if metrics[key]['value'] is not None:
            continue
        item = (order.get('metrics') or {}).get(key) or {}
        val = item.get('value')
        valid = ap == op and order.get('status') == 'available' and order.get('currency') == 'USD' and item.get('status') == 'available' and number(val)
        metrics[key] = field(val if valid else None, 'Order', ORDER_REFERENCE, order.get('capturedAt'))
    revenue, rate = metrics['revenueUsd']['value'], metrics['profitMarginPct']['value']
    # Match the deployed page's cent / basis-point rounding, including negative rates.
    def jsround(value):
        return math.floor(value+0.5)
    estimated = jsround(jsround(revenue*100)*jsround(rate*100)/10000)/100 if revenue is not None and rate is not None else None
    metrics['estimatedProfitUsd'] = field(estimated, 'Admin × Order',
        '预估：MMOEXP销售额 × Order利润率；不是后台实结利润', None)
    metrics['estimatedProfitUsd'].update(estimated=True, formula='Admin MMOEXP revenueUsd * Order profitMarginPct / 100',
        sourceCapturedAt={'Admin': admin.get('capturedAt'), 'Order': order.get('capturedAt')})
    for key in list(metrics):
        if key in PROFIT and not include_profit:
            del metrics[key]
            continue
        item = metrics[key]
        unit = 'USD' if key.endswith('Usd') else 'percent' if key.endswith('Pct') else 'count'
        item['unit'] = unit
        if item['value'] is not None:
            if unit == 'USD':
                item['value'] = str(Decimal(str(item['value'])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            elif key in ('orders', 'newCustomers'):
                item['value'] = int(item['value'])
    return metrics


def handle(path, query, header):
    client = authenticate(header)
    throttle(client)
    if path not in ('/api/fs/v1/profiles', '/api/fs/v1/statistics'):
        raise Rejected(404, 'not_found')
    if path.endswith('/profiles'):
        if query:
            raise Rejected(400, 'invalid_parameters')
        d = snapshot()
        entries = []
        for key in d['profiles'] if client['projects'] == ['*'] else client['projects']:
            if key in d['profiles']:
                coverage = d.get('dashboard', {}).get('profiles', {}).get(key, {}).get('coverage', {})
                entries.append({'profile': key, 'coverage': {'from':None,'to':None,'status':'upstream_history_coverage_unknown'},
                                'queryWindow': {k:coverage.get(k) for k in ('from','to')},'maximumRangeDays':366})
        return 200, dict(schemaVersion=1, readonly=True, profiles=entries,
                         includeProfit=client['includeProfit'], snapshotId=d['catalogId'], catalogId=d['catalogId']), client['id']
    p = params(query, client)
    if not INFLIGHT.acquire(blocking=False):
        raise Rejected(429, 'busy')
    try:
        d = snapshot()
        if p['profile'] not in d['profiles']:
            raise Rejected(400, 'project_unavailable')
        status, result = exact_range(p, d['snapshotId'])
    finally:
        INFLIGHT.release()
    if status != 200:
        mapping = {202: 'pending', 409: 'catalog_changed', 422: 'invalid_or_uncovered_range',
                   429: 'upstream_busy', 503: 'upstream_unavailable'}
        if status not in mapping:
            raise Rejected(503, 'upstream_unavailable')
        return status, dict(schemaVersion=1, status=mapping[status], profile=p['profile'],
                            retryAfter=10 if status in (202, 429, 503) else None), client['id']
    q = result.get('query') or {}
    if result.get('status') not in ('available','stale') or result.get('scopeContractId') != POLICY or result.get('profile',{}).get('key') != p['profile'] or any(q.get(k) != v for k, v in p.items()):
        raise ValueError('upstream_scope_mismatch')
    profile = result['profile']
    captured = result['generatedAt']
    age = time.time()-datetime.fromisoformat(captured).timestamp()
    ttl = 900 if p['end'] >= datetime.now(timezone(timedelta(hours=8))).date().isoformat() else 7200
    period = profile['period']
    return 200, dict(schemaVersion=1, sourcePolicyVersion=POLICY, profile=p['profile'], site=MAIN,
        timezone='Asia/Shanghai', currency='USD', period={'start': period['start'], 'endExclusive': period['end']},
        requestedDates={'start': p['start'], 'endInclusive': p['end']},
        snapshotId=d['catalogId'], catalogId=d['catalogId'], generatedAt=captured, freshness='fresh' if not result.get('stale') and 0 <= age <= ttl else 'stale',
        metrics=project_metrics(profile, client['includeProfit']),
        coverage={'status': 'exact_range', 'partialLastDay': period['end'] != (date.fromisoformat(p['end'])+timedelta(days=1)).isoformat()+' 00:00'}), client['id']


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        client_id = None
        route = urlsplit(self.path)
        try:
            if len(self.path) > 2048 or len(self.headers.get_all('Authorization', [])) != 1:
                raise Rejected(401, 'invalid_credentials')
            status, data, client_id = handle(route.path, route.query, self.headers.get('Authorization'))
        except Rejected as exc:
            status, data = exc.status, {'error': exc.code}
        except Exception:
            status, data = 503, {'error': 'service_unavailable'}
        self.reply(status, data)
        # Never log URL query strings, credentials, business values or upstream responses.
        print(json.dumps({'event': 'query', 'clientId': client_id, 'route': route.path if route.path in
                         ('/api/fs/v1/profiles', '/api/fs/v1/statistics') else 'unknown',
                         'status': status, 'time': datetime.now(timezone.utc).isoformat()}), flush=True)

    def do_POST(self):
        self.reply(405, {'error': 'read_only'})

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = do_POST

    def reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        for k, v in [('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store'),
                     ('Content-Length', str(len(raw))), ('Connection', 'close'), ('X-Content-Type-Options', 'nosniff')]:
            self.send_header(k, v)
        if status in (202, 429, 503):
            self.send_header('Retry-After', '10')
        if status == 401:
            self.send_header('WWW-Authenticate', 'Bearer')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8933)
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()

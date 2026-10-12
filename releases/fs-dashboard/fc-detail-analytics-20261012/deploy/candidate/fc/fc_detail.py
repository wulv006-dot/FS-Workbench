"""FC extension of the existing authenticated range service and its shared queue."""
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from threading import RLock
from urllib.parse import urlencode
import csv, hashlib, io, json, os, subprocess, tempfile, time
from fc_detail_model import aggregate, selected, CONTRACT

HERE = Path(__file__).resolve().parent

def query(params, now=None):
    allowed = {'mode', 'profile', 'start', 'end', 'grain', 'platform', 'customer', 'product', 'site_group', 'bucket', 'issue', 'pool', 'list', 'page', 'format', 'country', 'device', 'payment', 'hour', 'refresh'}
    if set(params) - allowed or any(len(v) != 1 for v in params.values()): raise ValueError('invalid_fc_parameters')
    values = {k: v[0] for k, v in params.items()}
    if values.get('profile') != 'FC27' or values.get('grain', 'day') != 'day': raise ValueError('fc_day_required')
    if values.get('mode') not in ('fc-detail', 'fc-report'): raise ValueError('invalid_fc_mode')
    now = now or datetime.now(timezone(timedelta(hours=8)))
    lo, hi = date.fromisoformat(values.get('start', '')), date.fromisoformat(values.get('end', ''))
    if lo.isoformat() != values['start'] or hi.isoformat() != values['end'] or hi < lo or hi > now.date() or (hi - lo).days > 365: raise ValueError('invalid_fc_period')
    enums = {'platform': ('all', 'PS', 'PC', 'XBOX', 'unknown'), 'customer': ('all', 'new', 'returning', 'unknown'),
             'site_group': ('all', 'main', 'satellite'), 'pool': ('paid', 'current'), 'issue': ('false', 'true'),
             'list': ('orders', 'issues'), 'format': ('json', 'csv'), 'refresh': ('true',),
             'product': ('all', 'Coins', 'Items', 'Boosting', 'Accounts', 'Top Up', '多品类', '待分类'),
             'bucket': ('all', 'unpriced') + tuple(str(i) for i in range(10))}
    for key, options in enums.items():
        if key in values and values[key] not in options: raise ValueError('invalid_fc_filter')
    for key in ('country', 'device', 'payment', 'hour'):
        if key in values and (not 1 <= len(values[key]) <= 80 or any(ord(c) < 32 for c in values[key])): raise ValueError('invalid_fc_dimension')
    if not values.get('page', '1').isdigit() or not 1 <= int(values.get('page', '1')) <= 100000: raise ValueError('invalid_fc_page')
    stop = min(datetime.combine(hi + timedelta(days=1), datetime.min.time()).replace(tzinfo=now.tzinfo), now.replace(second=0, microsecond=0))
    values['period'] = {'start': lo.isoformat() + ' 00:00', 'end': stop.strftime('%Y-%m-%d %H:%M')}
    return values

def read_source(q, config):
    model = (HERE / 'fc_detail_model.py').read_text('utf-8')
    reader = (HERE / 'fc_detail_reader.py').read_text('utf-8')
    prefix = 'import types,sys\nm=types.ModuleType("fc_detail_model")\nexec(%r,m.__dict__)\nsys.modules["fc_detail_model"]=m\n' % model
    result = subprocess.run(['docker', 'exec', '-i', 'fc27-p2pah-session', 'python3', '-',
                             json.dumps({'query': q, 'config': config})], input=(prefix + reader).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if result.returncode: raise OSError('fc_source_read_failed')
    data = json.loads(result.stdout)
    if not data.get('snapshot_id', '').startswith('fc-detail-') or not isinstance(data.get('orders'), list): raise ValueError('fc_source_contract')
    return data

def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.fc-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json.dumps(data, ensure_ascii=False).encode()); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

class FCDetails:
    def __init__(self, pool, cache, reader=read_source, config=None):
        self.pool, self.cache, self.reader = pool, Path(cache), reader
        self.config = config or json.loads((HERE / 'fc_detail_config.json').read_text('utf-8'))
        self.lock, self.jobs, self.starts = RLock(), {}, []

    def capture(self, key, q):
        try:
            data = self.reader(q, self.config)
            if data['coverage']['period'] != q['period']: raise ValueError('fc_source_period')
            atomic(self.cache / (key + '.json'), data)
            with self.lock: self.jobs.pop(key, None)
        except Exception:
            with self.lock: self.jobs[key] = {'state': 'failed', 'at': time.monotonic()}

    def get(self, params):
        q = query(params)
        if not self.config['enabled']: return 503, {'contractId': CONTRACT, 'data_status': 'unavailable', 'error': 'fc_detail_disabled'}
        if not self.config.get('trust_customer_flag') and q.get('customer') in ('new', 'returning'): raise ValueError('fc_customer_not_verified')
        source_q = {k: q[k] for k in ('start', 'end', 'period')}
        key = hashlib.sha256(json.dumps({'start': q['start'], 'end': q['end'], 'config': self.config}, sort_keys=True).encode()).hexdigest()
        file = self.cache / (key + '.json'); data = None
        if file.is_file():
            try: data = json.loads(file.read_text('utf-8'))
            except (ValueError, OSError): pass
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(data['as_of'])).total_seconds() if data else float('inf')
        ttl = self.config['today_cache_seconds'] if q['end'] == datetime.now(timezone(timedelta(hours=8))).date().isoformat() else self.config['history_cache_seconds']
        # Current open orders have their own shorter freshness bound even in a historical report.
        ttl = min(ttl, self.config['today_cache_seconds'])
        if q.get('refresh') == 'true' or not 0 <= age < ttl:
            with self.lock:
                job = self.jobs.get(key)
                if job and job['state'] == 'failed' and time.monotonic() - job['at'] >= 60: job = None
                if not job:
                    now = time.monotonic(); self.starts[:] = [n for n in self.starts if now - n < 60]
                    if len(self.starts) >= 3 or sum(j['state'] == 'pending' for j in self.jobs.values()) >= 2:
                        if data is None: return 429, {'data_status': 'pending', 'retryAfter': 10}
                    else:
                        self.starts.append(now); self.jobs[key] = job = {'state': 'pending', 'at': now}
                        self.pool.submit(self.capture, key, source_q)
                if data is None: return (503 if job and job['state'] == 'failed' else 202), {'contractId': CONTRACT, 'data_status': 'unavailable' if job and job['state'] == 'failed' else 'pending', 'retryAfter': 2}
                if q.get('refresh') == 'true': return (202 if job and job['state'] == 'pending' else 429), {'data_status': 'pending', 'retryAfter': 2}
        result = aggregate(data, q, self.config)
        result['stale'] = not 0 <= age < ttl
        if result['stale']: result['data_status'] = 'partial'
        result['refreshing'] = self.jobs.get(key, {}).get('state') == 'pending'
        result['refresh_error'] = self.jobs.get(key, {}).get('state') == 'failed'
        if q.get('format') == 'csv':
            current = q.get('pool', 'paid') == 'current'
            rows = result['orders']
            result['orders'] = rows[:10]
            output = io.StringIO(); writer = csv.writer(output)
            writer.writerow(['订单号', '范围', '平台', '商品分类', 'USD', '客户标记', '支付时间', '当前状态'])
            safe = lambda v: "'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v
            for r in rows: writer.writerow([safe(v) for v in (r['id'], r['site_group'], r['platform'], r['product'], '' if r['amount_usd'] is None else r['amount_usd'], r['customer'], r['paid_at'] or '', r['status'])])
            result['csv'] = '\ufeff' + output.getvalue()
        if q['mode'] == 'fc-report':
            core = {k: v for k, v in result.items() if k not in ('orders', 'csv', 'refreshing', 'refresh_error', 'page')}
            report_id = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:24]
            report_file = self.cache / 'reports' / (report_id + '.json')
            with self.lock:
                if not report_file.is_file(): atomic(report_file, {**core, 'report_id': report_id, 'generated_at': datetime.now(timezone.utc).isoformat()})
                result['report'] = json.loads(report_file.read_text('utf-8'))
        return 200, result

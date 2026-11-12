"""FC27 Evolutions pricing; consumes global sessions, never logs in."""
import argparse
import copy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import fcntl
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
BASE = '/dashboard/fc27-evolutions'
VERSION = 'evolutions-20261021-v1'
GID, CID = 1327, 9825
CATEGORIES = {9825, 10397, 10399}
PLATFORMS = {21587: 'PS', 21585: 'XBOX', 21589: 'PC'}
DEFAULT = {'revision': 1, 'automatic': False, 'premium': '1.1',
           'interval_minutes': 120, 'overrides': {}}


def number(value, minimum='0', maximum='1000000000', zero=False):
    if isinstance(value, bool):
        raise ValueError('数值不能是开关')
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result > Decimal(maximum) or (
                result < Decimal(minimum) if zero else result <= Decimal(minimum)):
            raise ValueError('数值超出范围')
        return result
    except (InvalidOperation, TypeError):
        raise ValueError('数值无效') from None


def money(value):
    return number(value, zero=True).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def target(coins, rate, premium, fixed=None):
    result = money(fixed if fixed is not None else
                   number(coins) / 1000 * number(rate) * number(premium, maximum='100'))
    if result <= 0:
        raise ValueError('目标售价不足一美分')
    return str(result)


def product_identity(row, model):
    if not (type(row.get('id')) is int and row['id'] > 0
            and row.get('gid') == GID and row.get('mid') == model['id']
            and row.get('cid') == model['cid'] and row.get('site_id') == 0
            and row.get('aid') in PLATFORMS
            and row.get('sid') == 7645 and row.get('top_cid') == 2
            and row.get('title') == model['title']
            and row.get('sku_switch') == 0 and row.get('attr_switch') == 0
            and number(row.get('num')) == 1):
        raise ValueError('产品身份或SKU不符合Evolutions/ALL范围')


def model_identity(row):
    if not (type(row.get('id')) is int and row['id'] > 0
            and row.get('gid') == GID and row.get('cid') in CATEGORIES
            and row.get('sku_switch') == 0 and row.get('attr_switch') == 0
            and isinstance(row.get('title'), str) and row['title']):
        raise ValueError('模型身份不符合Evolutions范围')


def validate_config(current, body, model_ids):
    if type(body.get('expected_revision')) is not int or body['expected_revision'] != current['revision']:
        raise ValueError('配置已变化，请重新载入')
    if set(body) - {'expected_revision', 'automatic', 'premium', 'interval_minutes', 'overrides'}:
        raise ValueError('未知配置字段')
    result = copy.deepcopy(current)
    for key in ('automatic', 'premium', 'interval_minutes'):
        if key not in body:
            continue
        value = body[key]
        if key == 'automatic':
            if type(value) is not bool:
                raise ValueError('自动开关须为布尔值')
        elif key == 'premium':
            value = str(number(value, maximum='100'))
        else:
            if type(value) is not int or not 5 <= value <= 10080:
                raise ValueError('周期须为5到10080分钟的整数')
        result[key] = value
    if 'overrides' in body:
        incoming = body['overrides']
        if not isinstance(incoming, dict):
            raise ValueError('单品配置须为对象')
        for mid, entry in incoming.items():
            if mid not in model_ids:
                raise ValueError('模型未拉取或已移除')
            if not isinstance(entry, dict) or set(entry) - {'enabled', 'coins', 'premium', 'prices'}:
                raise ValueError('单品配置字段无效')
            clean = {}
            if type(entry.get('enabled', True)) is not bool:
                raise ValueError('单品开关须为布尔值')
            clean['enabled'] = entry.get('enabled', True)
            for key in ('coins', 'premium'):
                if entry.get(key) not in (None, ''):
                    value = number(entry[key], maximum='100' if key == 'premium' else '1000000000')
                    if key == 'coins' and value != value.to_integral_value():
                        raise ValueError('金币数量须为整数')
                    clean[key] = str(value)
            prices = entry.get('prices', {})
            if not isinstance(prices, dict) or set(prices) - {'PS', 'XBOX', 'PC'}:
                raise ValueError('单品平台无效')
            clean['prices'] = {p: str(money(v)) for p, v in prices.items() if v not in ('', None)}
            if any(Decimal(v) <= 0 for v in clean['prices'].values()):
                raise ValueError('固定售价须大于零')
            result['overrides'][mid] = clean
    result['revision'] += 1
    return result


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Backend:
    def __init__(self):
        sys.path.insert(0, '/opt/fc27-pack-bundles/vendor')
        from admin_api_client import build_query
        import p2pah_price
        sys.path.insert(0, '/opt/fc27-cloud-browser')
        from fc_shared_admin import SessionManager, read_private_config
        self.admin = SessionManager(read_private_config())
        self.query = build_query
        self.price_reader = p2pah_price

    def _admin_request(self, path, *, params=None, data=None, require_success=True):
        if not self.admin.ensure():
            raise ValueError('Admin identity unconfirmed')
        if params:
            path += ('&' if '?' in path else '?') + self.query(params)
        # SessionManager dispatches once. A write timeout must reach the original
        # operation's UNKNOWN handler; never retry or fall back to the old broker.
        status, raw = self.admin.request(path, data=data)
        if status != 200:
            raise ValueError('Admin HTTP response unconfirmed: ' + str(status))
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError('Admin JSON response invalid') from None
        if not isinstance(result, dict):
            raise ValueError('Admin JSON response invalid')
        if require_success and result.get('code') not in (1, '1'):
            raise ValueError('Admin response unconfirmed')
        return result

    def get(self, path, params):
        return self._admin_request(path, params=params)['data']

    def row(self, kind, identity):
        return self.get('/admin/goods.' + kind + '/edit', {'id': identity})['row']

    def listing(self, kind, filters):
        result, ids, total = [], set(), None
        for page in range(1, 101):
            data = self.get('/admin/goods.' + kind + '/index', {
                'page': page, 'limit': 200, 'order': 'id,desc',
                'search': [{'field': k, 'operator': '=', 'val': str(v)} for k, v in filters.items()]})
            rows = data.get('list')
            if not isinstance(rows, list) or type(data.get('total')) is not int:
                raise ValueError('列表合同无效')
            if total is not None and total != data['total']:
                raise ValueError('分页期间目录发生变化')
            total = data['total']
            for row in rows:
                if row['id'] in ids:
                    raise ValueError('分页重复')
                ids.add(row['id'])
                result.append(row)
            if len(result) == total:
                return result
            if not rows or len(result) > total:
                break
        raise ValueError('目录分页不完整')

    def catalog(self):
        models = self.listing('GoodsMould', {'gid': GID, 'cid': CID})
        if not models:
            raise ValueError('Evolutions目录为空')
        for row in models:
            model_identity(row)
        products = self.listing('Goods', {'gid': GID, 'cid': CID, 'site_id': 0})
        by_id = {m['id']: m for m in models}
        for row in products:
            if row.get('mid') not in by_id:
                raise ValueError('产品与模型目录不一致')
            product_identity(row, by_id[row['mid']])
        return models, products

    def rates(self):
        data = self.price_reader.fetch_rows(user=None, password=None, gid=1322, timeout=60)
        if data.get('ok') is not True:
            raise ValueError('全局Order取价失败')
        rates = {}
        for row in data.get('rows', []):
            platform = row.get('area', '').strip().upper()
            if row.get('gid') != 1322 or platform not in PLATFORMS.values() or platform in rates:
                raise ValueError('Order游戏或平台单价行不唯一')
            rates[platform] = str(number(row['b2c']))
        if set(rates) != set(PLATFORMS.values()):
            raise ValueError('Order平台单价缺失')
        return rates

    def write(self, row, price):
        # Admin requires its complete edit row; preserve every non-price field.
        payload = copy.deepcopy(row)
        discount = number(row['discount'], maximum='100')
        payload['price'] = float(price)
        payload['unit_price'] = float((Decimal(price) * 100 / discount).quantize(
            Decimal('0.00000001'), rounding=ROUND_HALF_UP))
        self._admin_request('/admin/goods.Goods/edit', data=payload)
        return payload

    def clear_cache(self):
        for attempt in range(2):
            result = self._admin_request('/admin/tools.Caches/clear?server=1',
                                         data={'type': 'all', 'file': ''}, require_success=False)
            if result.get('code') in (1, '1'):
                return
            limited = '操作过于频繁' in str(result.get('msg', ''))
            if not limited or attempt:
                raise ValueError('缓存清理限流' if limited else '缓存清理未确认')
            # Cache invalidation is idempotent; only an explicit rate limit permits retry.
            time.sleep(31)


def plan(models, products, rates, config):
    result = []
    for model in models:
        override = config['overrides'].get(str(model['id']), {})
        coins = override.get('coins', model.get('unit'))
        premium = override.get('premium', config['premium'])
        children = [r for r in products if r['mid'] == model['id']]
        platforms = [PLATFORMS[r['aid']] for r in children]
        error = None
        if sorted(platforms) != sorted(PLATFORMS.values()):
            error = 'ALL三平台产品缺失或重复'
        for row in children:
            platform = PLATFORMS[row['aid']]
            item = {'model_id': model['id'], 'product_id': row['id'], 'cid': model['cid'],
                    'title': model['title'], 'platform': platform, 'coins': str(coins),
                    'model_coins': model.get('unit'), 'premium': premium,
                    'rate': rates[platform], 'current': str(row['price']),
                    'enabled': override.get('enabled', True), 'error': error,
                    'fixed': override.get('prices', {}).get(platform)}
            try:
                if model.get('status') != 1 or row.get('status') != 1:
                    raise ValueError('模型或产品已禁用')
                number(row.get('discount'), maximum='100')
                item['target'] = target(coins, rates[platform], premium, item['fixed'])
            except ValueError as exc:
                item['error'] = str(exc)
                item['target'] = None
            result.append(item)
    return result


class Store:
    def __init__(self, directory, backend):
        self.directory, self.backend = Path(directory), backend
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.operations = self.directory / 'operations'
        self.operations.mkdir(mode=0o700, exist_ok=True)
        self.jobs = self.directory / 'jobs'
        self.jobs.mkdir(mode=0o700, exist_ok=True)
        self.guard = (self.directory / 'writer.lock').open('a')
        fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.lock = threading.RLock()
        path = self.directory / 'state.json'
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'config': copy.deepcopy(DEFAULT), 'snapshot': None, 'job': None, 'history': [], 'blocked': False}
        if (self.data.get('job') or {}).get('status') == 'running':
            self.data['job']['status'] = 'interrupted'
        self.data['blocked'] = self.unresolved_operations_exist()
        self.persist()

    @staticmethod
    def operation_blocks(record):
        coverage = record.get('current_state_coverage') or {}
        covered = (coverage.get('operation_id') == record['id']
                   and coverage.get('source') == 'admin_goods_catalog'
                   and coverage.get('product', {}).get('id') == record['product_id'])
        return record['status'] in ('pending', 'unknown') and not covered

    def unresolved_operations_exist(self):
        return any(self.operation_blocks(json.loads(path.read_text()))
                   for path in self.operations.glob('*.json'))

    def cover_historical_state(self, job, models, products, read_started_at, observed_at):
        # A real Admin observation can replace the current gate, not the outcome
        # of an old POST. The original status/target/receipt remain unchanged.
        if time.time() - read_started_at > 300:
            return
        model_map = {row['id']: row for row in models}
        for path in self.operations.glob('*.json'):
            record = json.loads(path.read_text())
            if not self.operation_blocks(record) or record['job_id'] == job['id']:
                continue
            original_path = self.jobs / (record['job_id'] + '.json')
            if not original_path.exists():
                continue
            original = json.loads(original_path.read_text())
            finished = original.get('finished_at')
            if (original.get('status') not in ('completed', 'partial', 'failed', 'needs_review', 'interrupted')
                    or type(finished) not in (int, float) or not 0 < finished <= read_started_at):
                continue
            matches = [row for row in products if row.get('id') == record['product_id']]
            if len(matches) != 1:
                continue
            row = matches[0]
            if any(row.get(key) != record['before'].get(key)
                   for key in ('id', 'gid', 'cid', 'mid', 'aid', 'site_id', 'sid')):
                continue
            try:
                model = model_map[row['mid']]
                model_identity(model)
                product_identity(row, model)
                price = number(row['price'])
                discount = number(row['discount'], maximum='100')
                if abs(number(row['unit_price']) * discount / 100 - price) > Decimal('0.000001'):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            record['current_state_coverage'] = {
                'operation_id': record['id'], 'refresh_job_id': job['id'],
                'source': 'admin_goods_catalog', 'read_started_at': read_started_at,
                'observed_at': observed_at, 'original_job_finished_at': finished,
                'product': {key: row[key] for key in
                            ('id', 'gid', 'cid', 'mid', 'aid', 'site_id', 'sid', 'price', 'unit_price', 'discount')}}
            save(path, record)
        # Established coverage is a historical fact, not a renewable TTL lease.
        # Every future write still has the existing fresh-read/CAS checks.
        self.data['blocked'] = self.unresolved_operations_exist()

    def persist(self):
        save(self.directory / 'state.json', self.data)
        if self.data.get('job'):
            save(self.jobs / (self.data['job']['id'] + '.json'), self.data['job'])

    def state(self):
        with self.lock:
            result = copy.deepcopy(self.data)
        result['version'] = VERSION
        snap = result['snapshot']
        if snap:
            result['rows'] = plan(snap['models'], snap['products'], snap['rates'], result['config'])
        else:
            result['rows'] = []
        result['stale'] = not snap or time.time() - snap['at'] > 300
        return result

    def configure(self, body):
        with self.lock:
            off = set(body) == {'expected_revision', 'automatic'} and body['automatic'] is False
            if self.running() and not off:
                raise ValueError('任务进行中，请等待；可随时关闭自动改价')
            snap = self.data['snapshot'] or {'models': []}
            previous = self.data['config']
            config = validate_config(previous, body, {str(m['id']) for m in snap['models']})
            if config['automatic'] and not previous['automatic']:
                self.data['next_auto_at'] = time.time()
            elif config['interval_minutes'] != previous['interval_minutes']:
                self.data['next_auto_at'] = time.time() + config['interval_minutes'] * 60
            self.data['config'] = config
            self.persist()

    def running(self):
        return (self.data.get('job') or {}).get('status') == 'running'

    def start(self, action, identity, actor, revision=None):
        if str(uuid.UUID(identity)) != identity or action not in ('refresh', 'apply', 'reconcile'):
            raise ValueError('请求标识或动作无效')
        with self.lock:
            old_path = self.jobs / (identity + '.json')
            old = json.loads(old_path.read_text()) if old_path.exists() else None
            if old:
                if old['action'] != action:
                    raise ValueError('请求标识已用于其他动作')
                return old
            if self.running():
                raise ValueError('已有任务进行中')
            if action == 'apply' and (self.data['blocked'] or revision != self.data['config']['revision']):
                raise ValueError('写入结果待核实或配置已变化')
            previous = self.data.get('job')
            if previous:
                self.data['history'] = (self.data['history'] + [previous])[-20:]
            job = {'id': identity, 'action': action, 'actor': actor, 'at': time.time(),
                   'status': 'running', 'results': []}
            self.data['job'] = job
            self.persist()
            threading.Thread(target=self.run, args=(job,), daemon=True).start()
            return copy.deepcopy(job)

    def run(self, job):
        try:
            if job['action'] == 'reconcile':
                self.reconcile()
            else:
                read_started_at = time.time()
                models, products = self.backend.catalog()
                observed_at = time.time()
                rates = self.backend.rates()
                with self.lock:
                    config = copy.deepcopy(self.data['config'])
                    self.data['snapshot'] = {'at': time.time(), 'models': models, 'products': products, 'rates': rates}
                    if job['action'] == 'refresh':
                        self.cover_historical_state(job, models, products, read_started_at, observed_at)
                    self.persist()
                if job['action'] == 'apply':
                    self.apply(job, models, products, rates, config)
            with self.lock:
                if self.data['blocked']:
                    job['status'] = 'needs_review'
                elif any(r['action'] == 'skipped_invalid' for r in job['results']):
                    job['status'] = 'partial'
                else:
                    job['status'] = 'completed'
        except Exception as exc:
            # Exception text from an upstream library can contain tokens or full URLs.
            with self.lock:
                job['status'] = 'failed'
                job['error'] = str(exc)[:160] if isinstance(exc, ValueError) else type(exc).__name__
        finally:
            with self.lock:
                job['finished_at'] = time.time()
                if job['action'] == 'apply':
                    self.data['next_auto_at'] = job['finished_at'] + self.data['config']['interval_minutes'] * 60
                self.persist()

    def apply(self, job, models, products, rates, config):
        rows = plan(models, products, rates, config)
        model_map = {m['id']: m for m in models}
        current_models = {}
        changed = False
        for item in rows:
            if not item['enabled']:
                continue
            if item['error']:
                with self.lock:
                    job['results'].append({'product_id': item['product_id'],
                        'action': 'skipped_invalid', 'error': item['error']})
                    self.persist()
                continue
            mid, pid = item['model_id'], item['product_id']
            if mid not in current_models:
                current_models[mid] = self.backend.row('GoodsMould', mid)
                model_identity(current_models[mid])
                for key in ('id', 'gid', 'cid', 'unit', 'title', 'status', 'sku_switch', 'attr_switch'):
                    if current_models[mid].get(key) != model_map[mid].get(key):
                        raise ValueError('写前模型发生变化，请重新拉取')
            row = self.backend.row('Goods', pid)
            product_identity(row, current_models[mid])
            baseline = next(r for r in products if r['id'] == pid)
            for key in ('price', 'unit_price', 'discount', 'status', 'unit', 'num'):
                if str(row.get(key)) != str(baseline.get(key)):
                    raise ValueError('写前产品发生变化，请重新拉取')
            if money(row['price']) == Decimal(item['target']):
                with self.lock:
                    job['results'].append({'product_id': pid, 'action': 'unchanged'})
                    self.persist()
                continue
            opid = job['id'] + '-' + str(pid)
            record = {'id': opid, 'job_id': job['id'], 'product_id': pid, 'model': model_map[mid],
                      'before': row, 'target': item['target'], 'status': 'pending'}
            with self.lock:
                if config['revision'] != self.data['config']['revision']:
                    raise ValueError('配置已变更，本轮停止后续写入')
                if job['actor'] == 'system-automation' and not self.data['config']['automatic']:
                    raise ValueError('自动改价已关闭，本轮停止后续写入')
                if time.time() - self.data['snapshot']['at'] > 300:
                    raise ValueError('本轮取价超过5分钟，请重新拉取')
                save(self.operations / (opid + '.json'), record)
                self.data['blocked'] = True
                self.persist()
                try:
                    self.backend.write(row, item['target'])
                except Exception:
                    record['status'] = 'unknown'
                    save(self.operations / (opid + '.json'), record)
                    job['results'].append({'product_id': pid, 'action': 'unknown', 'operation_id': opid})
                    self.persist()
                    return
            try:
                after = self.backend.row('Goods', pid)
                product_identity(after, model_map[mid])
                self.confirm_price(after, record)
            except Exception:
                record['status'] = 'unknown'
                save(self.operations / (opid + '.json'), record)
                with self.lock:
                    job['results'].append({'product_id': pid, 'action': 'unknown', 'operation_id': opid})
                    self.persist()
                return
            record['status'] = 'confirmed'
            record['after'] = after
            save(self.operations / (opid + '.json'), record)
            with self.lock:
                self.data['blocked'] = False
                self.data['cache_pending'] = True
                job['results'].append({'product_id': pid, 'action': 'confirmed', 'target': item['target'], 'operation_id': opid})
                baseline.update(after)
                self.persist()
            changed = True
        if changed or self.data.get('cache_pending'):
            self.backend.clear_cache()
            with self.lock:
                job['cache'] = 'cleared'
                self.data['cache_pending'] = False
                self.persist()

    @staticmethod
    def confirm_price(row, record):
        expected = Decimal(record['target'])
        if (money(row['price']) != expected or number(row['discount']) != number(record['before']['discount'])
                or abs(number(row['unit_price']) * number(row['discount']) / 100 - expected) > Decimal('0.000001')):
            raise ValueError('价格回读不一致')

    def reconcile(self):
        pending = []
        for path in self.operations.glob('*.json'):
            record = json.loads(path.read_text())
            if self.operation_blocks(record):
                pending.append((path, record))
        for path, record in pending:
            row = self.backend.row('Goods', record['product_id'])
            product_identity(row, record['model'])
            self.confirm_price(row, record)
            record.update(status='confirmed_after_unknown', after=row)
            save(path, record)
        if pending or self.data.get('cache_pending'):
            self.backend.clear_cache()
        with self.lock:
            self.data['blocked'] = False
            self.data['cache_pending'] = False


def authorized(headers, write=False):
    user, role = headers.get('X-Evo-User', ''), headers.get('X-Evo-Role', '')
    if not user or (write and role != 'admin'):
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    def send(self, status, value, mime='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/health':
            return self.send(200, {'version': VERSION})
        if not authorized(self.headers):
            return self.send(403, {'error': '需要门户登录'})
        path = urlsplit(self.path).path
        if path == BASE + '/api/state':
            state = self.server.store.state()
            state['writable'] = authorized(self.headers, True)
            return self.send(200, state)
        files = {BASE + '/': ('index.html', 'text/html; charset=utf-8'),
                 BASE + '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 BASE + '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in files:
            name, mime = files[path]
            return self.send(200, (ROOT / name).read_bytes(), mime)
        self.send(404, {'error': '未找到入口'})

    def do_POST(self):
        if not authorized(self.headers, True):
            return self.send(403, {'error': '仅管理员可修改'})
        if (self.headers.get('Origin') != 'https://47.85.224.112'
                or self.headers.get('X-Evo-Request') != '1'
                or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
            return self.send(403, {'error': '请求来源无效'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 131072:
                raise ValueError('请求大小无效')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('请求须为对象')
            path = urlsplit(self.path).path
            if path == BASE + '/api/config':
                self.server.store.configure(body)
                return self.send(200, {'saved': True})
            actions = {BASE + '/api/' + name: name for name in ('refresh', 'apply', 'reconcile')}
            if path not in actions:
                return self.send(404, {'error': '未知操作'})
            job = self.server.store.start(actions[path], body['request_id'], self.headers['X-Evo-User'], body.get('expected_revision'))
            self.send(202, job)
        except (ValueError, KeyError, TypeError) as exc:
            self.send(409, {'error': str(exc)[:160]})

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='/var/lib/fc27-evolutions')
    parser.add_argument('--port', type=int, default=8914)
    args = parser.parse_args()
    store = Store(args.data, Backend())
    def schedule():
        while True:
            time.sleep(5)
            with store.lock:
                config, job = store.data['config'], store.data.get('job')
                due = time.time() >= store.data.get('next_auto_at', 0)
                if config['automatic'] and due and not store.running() and not store.data['blocked']:
                    store.start('apply', str(uuid.uuid4()), 'system-automation', config['revision'])
    threading.Thread(target=schedule, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.store = store
    server.serve_forever()


if __name__ == '__main__':
    main()

"""FC daily reports in the existing range process; reuse FCDetails source queue/cache."""
from datetime import date, datetime, time as clock_time, timedelta, timezone
import hashlib
import importlib.util
import logging
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from fc_daily_model import configured, explain, projection

SHANGHAI = timezone(timedelta(hours=8))
CONTRACT = 'fc-daily-v1'
SCHEDULE_HOUR, SCHEDULE_MINUTE = 9, 15
FACT_KEYS = ('orders', 'revenue_usd', 'issues', 'unpriced_orders', 'unfinished', 'completed', 'funding')


def now(): return datetime.now(SHANGHAI)
def model_daily_limit():
    value=os.environ.get('FS_MODEL_DAILY_LIMIT','0')
    if not re.fullmatch(r'[0-9]{1,6}',value):raise ValueError('invalid_model_limit')
    return int(value)

@contextmanager
def provider_slot(root):
    fd=os.open(str(root/'provider.lock'),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        try:
            if os.name=='nt':
                import msvcrt
                if os.fstat(fd).st_size==0:os.write(fd,b'0')
                os.lseek(fd,0,0);msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            yield False;return
        yield True
    finally:os.close(fd)
def encoded(data): return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def digest(data): return hashlib.sha256(encoded(data).encode()).hexdigest()


def checked_day(value, at):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError('invalid_date')
    day = date.fromisoformat(value)
    if not at.date() - timedelta(days=365) <= day < at.date(): raise ValueError('complete_day_required')
    return day


_POLICY_PATH = Path('/opt/fs-access-policy/access_policy.py')
_POLICY_LOCK = threading.RLock()
_POLICY_MODULE = None
_POLICY_STAMP = None
_POLICY_ERROR = None


def admin_status(user):
    global _POLICY_MODULE, _POLICY_STAMP, _POLICY_ERROR
    if not user:
        return {'verified': True, 'is_admin': False, 'reason': 'login_required'}
    with _POLICY_LOCK:
        try:
            info = _POLICY_PATH.stat()
            stamp = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
            if _POLICY_MODULE is None or stamp != _POLICY_STAMP:
                spec = importlib.util.spec_from_file_location('fs_daily_existing_policy', _POLICY_PATH)
                policy = importlib.util.module_from_spec(spec)
                # Compile fresh bytes so a same-second replacement cannot reuse stale pycache.
                exec(compile(_POLICY_PATH.read_bytes(), str(_POLICY_PATH), 'exec'), policy.__dict__)
                _POLICY_MODULE, _POLICY_STAMP = policy, stamp
            policy = _POLICY_MODULE
            allowed = policy.is_admin(user) if hasattr(policy, 'is_admin') else user in policy.ADMINS
            health = policy.status() if hasattr(policy, 'status') else {}
            if health.get('degraded'):
                return {'verified': False, 'is_admin': False, 'reason': 'admin_unverified', 'error': 'policy_degraded'}
            _POLICY_ERROR = None
            return {'verified': True, 'is_admin': bool(allowed), 'reason': None if allowed else 'not_admin'}
        except Exception as error:
            _POLICY_MODULE, _POLICY_STAMP = None, None
            kind = type(error).__name__
            if kind != _POLICY_ERROR:
                logging.getLogger(__name__).warning('FS admin policy unavailable: %s', kind)
                _POLICY_ERROR = kind
            return {'verified': False, 'is_admin': False, 'reason': 'admin_unverified', 'error': kind}


def admin(user):
    return admin_status(user)['is_admin']


admin.status = admin_status


def safe_facts(source):
    result = {k: source[k] for k in FACT_KEYS}
    if result['unpriced_orders']: result['revenue_usd'] = None
    return result


def build_report(day, data, main, previous=None):
    """All numbers derive from the existing deterministic aggregation, never the model."""
    period = {'start': day + ' 00:00', 'end': (date.fromisoformat(day) + timedelta(days=1)).isoformat() + ' 00:00'}
    for item in (data, main):
        if item.get('contractId') != 'fc27-detail-analytics-v1' or item['coverage']['period'] != period or item['query']['start'] != day or item['query']['end'] != day:
            raise ValueError('source_period_mismatch')
    if data['snapshot_id'] != main['snapshot_id']: raise ValueError('source_snapshot_changed')
    if not data['coverage'].get('paid_complete') or data['coverage'].get('missing_days'):
        raise ValueError('paid_data_incomplete')
    groups = {r['key']: safe_facts(r) for r in data['site_groups']}
    if set(groups) != {'main', 'satellite'}: raise ValueError('site_scope_missing')
    warnings = ['新老客字段尚未验证，日报不推算新客或复购率。',
                '独立分销业务归属字段未取得，当前按已授权网站及显式排除配置统计，不声称已完整排除。',
                '订单与销售额来自 Admin FC 明细；本期无已验证利润、成本或同比来源，不作推算。',
                '履约状态为数据读取时的当前状态，不是历史日末快照；未接原始客服备注。']
    if data['data_status'] != 'available': warnings.append('来源部分缺项，完整支付区间已核验，其他指标按可用范围展示。')
    if groups['main']['unpriced_orders'] or groups['satellite']['unpriced_orders']:
        warnings.append('存在缺 USD 金额订单，相关销售额显示暂缺，未补零。')
    comparison = None
    if previous and previous['date'] == (date.fromisoformat(day)-timedelta(days=1)).isoformat() and previous['scope_fingerprint'] == digest({'contract': data['contractId'], 'rule': data['coverage'].get('site_rule'), 'distribution': data['distribution_identification']}):
        old, current = previous['main'], groups['main']
        if old['revenue_usd'] is not None and current['revenue_usd'] is not None:
            delta = round(current['revenue_usd'] - old['revenue_usd'], 2)
            comparison = {'revenue_delta': delta, 'revenue_pct': round(delta / old['revenue_usd'] * 100, 2) if old['revenue_usd'] else None,
                          'orders_delta': current['orders'] - old['orders']}
    if comparison is None: warnings.append('缺少同口径前一日日报，环比暂缺。')
    totals = safe_facts(data['totals'])
    metrics = groups['main']
    analysis = {'average_order_usd': round(metrics['revenue_usd'] / metrics['orders'], 2) if metrics['orders'] and metrics['revenue_usd'] is not None else None,
                'issue_share_pct': round(metrics['issues'] / metrics['orders'] * 100, 2) if metrics['orders'] else None}
    dimensions = {key: [{'key': row['key'], **safe_facts(row)} for row in main['dimensions'][key]] for key in ('platform', 'product')}
    return {'contractId': CONTRACT, 'date': day, 'period': period, 'timezone': 'Asia/Shanghai', 'currency': 'USD',
            'source': '现有 FCDetails / Admin 只读接口与日期缓存', 'snapshot_id': data['snapshot_id'], 'data_as_of': data['as_of'],
            'scope': 'MMOEXP 主站详细分析 + 已配置卫星子站汇总',
            'scope_fingerprint': digest({'contract': data['contractId'], 'rule': data['coverage'].get('site_rule'), 'distribution': data['distribution_identification']}),
            'main': metrics, 'satellite': groups['satellite'], 'totals': totals, 'dimensions': dimensions, 'analysis': analysis,
            'comparison': comparison, 'warnings': warnings,
            'backlog': safe_facts(data['backlog_summary']) if data['coverage'].get('backlog_status') == 'available' and data.get('backlog_summary') else None,
            'data_status': data['data_status'], 'ai': {'status': 'not_run'}}


class DailyReports:
    def __init__(self, detail, root, model=explain, is_configured=configured, clock=now, wait=time.sleep, authorizer=admin):
        self.detail, self.root, self.model, self.is_configured = detail, Path(root), model, is_configured
        self.clock, self.wait, self.authorizer = clock, wait, authorizer
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.root / 'daily.sqlite3'
        self.worker_lock = threading.Lock()
        self.deep = None
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL,
                requested_at TEXT NOT NULL, trigger TEXT NOT NULL, state TEXT NOT NULL,
                finished_at TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS reports (job_id INTEGER PRIMARY KEY, day TEXT NOT NULL, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_calls (fingerprint TEXT PRIMARY KEY, day TEXT NOT NULL, state TEXT NOT NULL, content TEXT);
                CREATE TABLE IF NOT EXISTS scheduler_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
        self.db_path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(str(self.db_path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def latest(self, day):
        with self.db() as db:
            row = db.execute('SELECT content FROM reports WHERE day=? ORDER BY job_id DESC LIMIT 1', (day,)).fetchone()
        return json.loads(row[0]) if row else None

    def enqueue(self, day, request_id, trigger='manual'):
        # Legacy generation is retired; the shared model ledger remains for Hermes.
        return {'state': 'retired', 'error': 'legacy_bailian_analysis_retired'}

    def source(self, day, site='all'):
        params = {k: [v] for k, v in {'mode': 'fc-detail', 'profile': 'FC27', 'grain': 'day', 'start': day, 'end': day, 'site_group': site}.items()}
        deadline = time.monotonic() + 920
        while time.monotonic() < deadline:
            status, item = self.detail.get(params)
            if status == 200 and not item.get('stale') and not item.get('refreshing'): return item
            if status not in (200, 202, 429): raise ValueError('source_unavailable')
            self.wait(5)
        raise ValueError('source_timeout')

    def model_result(self, report):
        return self.bounded_model(projection(report), self.model)

    def bounded_model(self, projected, model):
        if not self.is_configured(): return {'status': 'configuration_missing'}
        fingerprint = digest(projected)
        with self.db() as db:
            prior=db.execute('SELECT state,content FROM model_calls WHERE fingerprint=?',(fingerprint,)).fetchone()
        if prior:return json.loads(prior['content']) if prior['content'] else {'status':'unknown_previous_attempt'}
        with provider_slot(self.root) as acquired:
            if not acquired:return {'status':'model_busy'}
            return self._send_model(projected,model,fingerprint)

    def _send_model(self, projected, model, fingerprint):
        try:limit=model_daily_limit()
        except ValueError:return {'status':'configuration_invalid'}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT state,content FROM model_calls WHERE fingerprint=?', (fingerprint,)).fetchone()
            if prior: return json.loads(prior['content']) if prior['content'] else {'status': 'unknown_previous_attempt'}
            count = db.execute('SELECT COUNT(*) FROM model_calls WHERE day=?', (self.clock().date().isoformat(),)).fetchone()[0]
            if limit and count >= limit: return {'status': 'daily_model_limit'}
            db.execute("INSERT INTO model_calls VALUES(?,?,'started',NULL)", (fingerprint, self.clock().date().isoformat()))
        # Receipt is durable before the request; uncertain delivery is never silently retried.
        try: result = model(projected)
        except Exception: result = {'status': 'unknown_model_error'}
        with self.db() as db: db.execute('UPDATE model_calls SET state=?,content=? WHERE fingerprint=?', (result['status'], encoded(result), fingerprint))
        return result

    def run_one(self):
        # Legacy generation is retired; the shared model ledger remains for Hermes.
        return False

    def tick(self):
        # Legacy generation is retired; the shared model ledger remains for Hermes.
        return None

    def start(self):
        # Only the existing range service owns the scheduler across restarts/processes.
        # Legacy generation is retired; the shared model ledger remains for Hermes.
        return None

    def get(self, params, user, headers):
        at = self.clock()
        if not user: return 401, {'error': 'login_required'}
        if set(params)-{'mode', 'date', 'action', 'request_id', 'revision'} or any(len(v)!=1 for v in params.values()): return 422, {'error': 'invalid_parameters'}
        day = params.get('date', [(at.date()-timedelta(days=1)).isoformat()])[0]
        try: checked_day(day, at)
        except ValueError: return 422, {'error': 'complete_day_required'}
        can_generate = False
        if 'action' in params:
            if self.authorizer(user): return 410, {'error': 'legacy_bailian_analysis_retired', 'replacement': '/dashboard/fs-home/hermes/index.html'}
            if params['action'] != ['run']: return 422, {'error': 'invalid_action'}
            if not can_generate: return 403, {'error': 'admin_required'}
            if headers.get('X-FS-Report-Action') != 'generate' or headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
                return 403, {'error': 'same_origin_required'}
            try: job = self.enqueue(day, params.get('request_id', [''])[0])
            except ValueError: return 422, {'error': 'invalid_request_id'}
            if job['state'] == 'busy': return 429, {'error': job['error'], 'retryAfter': 60}
        report = self.latest(day)
        with self.db() as db:
            if 'revision' in params:
                if not re.fullmatch(r'\d{1,10}', params['revision'][0]): return 422, {'error': 'invalid_revision'}
                row = db.execute('SELECT content FROM reports WHERE day=? AND job_id=?', (day, int(params['revision'][0]))).fetchone()
                if not row: return 404, {'error': 'revision_not_found'}
                report = json.loads(row[0])
            last = db.execute('SELECT id,day,state,error,requested_at,finished_at,trigger FROM jobs WHERE day=? ORDER BY id DESC LIMIT 1', (day,)).fetchone()
            history = db.execute('SELECT day,MAX(job_id) AS revision FROM reports GROUP BY day ORDER BY day DESC LIMIT 90').fetchall()
            versions = db.execute('SELECT job_id AS revision FROM reports WHERE day=? ORDER BY job_id DESC LIMIT 30', (day,)).fetchall()
            scheduler = dict(db.execute('SELECT key,value FROM scheduler_state').fetchall())
        next_run = datetime.combine(at.date(), clock_time(SCHEDULE_HOUR, SCHEDULE_MINUTE), SHANGHAI)
        if next_run <= at: next_run += timedelta(days=1)
        return 200, {'contractId': CONTRACT, 'date': day, 'can_generate': can_generate, 'report': report,
                     'last_attempt': dict(last) if last else None, 'history': [dict(r) for r in history], 'versions': [dict(r) for r in versions],
                     'schedule': {'enabled': False, 'status': 'retired', 'timezone': 'Asia/Shanghai', 'time': None, 'next_run': None, 'replacement': '/dashboard/fs-home/hermes/index.html'},
                     'model_configured': False}

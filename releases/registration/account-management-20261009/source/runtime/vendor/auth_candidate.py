"""Local-only registration candidate. Import is inert; no production adapter exists."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
from urllib.parse import unquote, urlsplit, parse_qs
import uuid
import native_access_policy as _native_policy
from schema_contract import validate as validate_schema

ADMINS = _native_policy.ADMINS  # Compatibility export; live checks use the source policy below.
ITERATIONS = 600_000
TTL = 43200
COOKIE = 'FS_ACCESS_CANDIDATE'
PREFIX = '/__auth/access'
# Synthetic route contract only. No wildcard grants to arbitrary GET endpoints.
READ_ROUTES = frozenset(('/dashboard/', '/dashboard/index.html', '/dashboard/analytics/',
    '/dashboard/analytics/index.html', '/dashboard/marketing/', '/dashboard/marketing/index.html',
    '/dashboard/marketing/data.json', '/dashboard/marketing/weekly/', '/dashboard/weekly/'))
READ_ROUTES = READ_ROUTES | frozenset(('/dashboard/tasks/', '/dashboard/tasks/api/projects',
    '/s/wulv/fc27-ops/', '/fc27/analysis', '/tools/fc27-players/'))
CONTROL = frozenset(('admin', 'deploy', 'apply', 'execute', 'run', 'start',
    'stop', 'pause', 'resume', 'reset', 'delete', 'save', 'update', 'set',
    'clear', 'unlock', 'collect', 'backfill', 'publish', 'restart', 'refresh-now',
    'refresh_now', 'clear-lock', 'clear_lock', 'reset-lock', 'reset_lock', 'ban', 'unban'))
READ_QUERY_KEYS = frozenset(('mode', 'brand', 'days', 'scope', 'period', 'category'))


class Denied(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{2,31}', value):
        raise Denied(400, '账号须为3–32位字母、数字或._-，以字母开头')
    return value.lower()


def text_field(value, minimum=1, maximum=240):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise Denied(400, '信息长度不符合要求')
    value = value.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Denied(400, '信息含无效字符')
    return value


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise Denied(400, '密码须为12–128位')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def password_matches(password, encoded):
    try:
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            return False
        algorithm, rounds, salt, wanted = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or int(rounds) != ITERATIONS:
            return False
        got = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(got, wanted)
    except (ValueError, TypeError):
        return False


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class LegacyIdentity:
    """Only a trusted server-side portal resolver may construct this proof."""
    user: str
    groups: tuple
    role: str


SCHEMA = '''
CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
 password TEXT NOT NULL, team TEXT NOT NULL, purpose TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','readonly','rejected','revoked')),
 epoch INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
CREATE TABLE requests(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','revoked')),
 version INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL,
 applicant_name TEXT NOT NULL, team TEXT NOT NULL, purpose TEXT NOT NULL);
CREATE UNIQUE INDEX one_pending ON requests(user_id) WHERE status='pending';
CREATE TRIGGER request_snapshot_immutable BEFORE UPDATE OF user_id,created,applicant_name,team,purpose ON requests
 BEGIN SELECT RAISE(ABORT, 'immutable request snapshot'); END;
CREATE TRIGGER request_history_no_delete BEFORE DELETE ON requests
 BEGIN SELECT RAISE(ABORT, 'request history retained'); END;
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id),
 legacy_user TEXT, csrf TEXT NOT NULL, epoch INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE audit(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, actor TEXT NOT NULL,
 action TEXT NOT NULL, request_id TEXT NOT NULL REFERENCES requests(id), subject TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TRIGGER audit_append_only_update BEFORE UPDATE ON audit
 BEGIN SELECT RAISE(ABORT, 'append-only audit'); END;
CREATE TRIGGER audit_append_only_delete BEFORE DELETE ON audit
 BEGIN SELECT RAISE(ABORT, 'append-only audit'); END;
CREATE TABLE limits(bucket TEXT PRIMARY KEY, n INTEGER NOT NULL, until INTEGER NOT NULL);
PRAGMA user_version=2;
'''


class Store:
    def __init__(self, sandbox, *, reserved_names, clock=time.time, allow_existing=False, policy_module=None):
        self.policy = policy_module or _native_policy
        # Safety constraint is intentional: this candidate cannot open a production DB.
        if Path(sandbox).is_symlink():
            raise ValueError('sandbox link rejected')
        root = Path(sandbox).resolve()
        temp = Path(tempfile.gettempdir()).resolve()
        if root == temp or temp not in root.parents or not root.name.startswith('fs-registration-'):
            raise ValueError('candidate requires a dedicated fs-registration-* temp directory')
        if not root.is_dir() or root.is_symlink():
            raise ValueError('sandbox must already exist')
        self.path, self.reserved_names, self.clock = root / 'candidate.sqlite3', reserved_names, clock
        if self.path.is_symlink():
            raise ValueError('database link rejected')
        exists = self.path.exists()
        if exists and not allow_existing:
            raise ValueError('candidate requires a new database')
        with self.connection() as db:
            if exists:
                validate_schema(db, SCHEMA, db.execute('PRAGMA user_version').fetchone()[0])
            else:
                db.executescript(SCHEMA)
                validate_schema(db, SCHEMA, 2)
        # Never uses real account hash for missing-user timing work.
        self.dummy = password_hash('Synthetic-only-dummy-42')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def now(self):
        return int(self.clock())

    def reserved(self):
        names = self.reserved_names()
        if names is None or not isinstance(names, (set, frozenset)):
            raise Denied(503, '注册暂不可用')
        if any(not isinstance(n, str) or not n for n in names):
            raise Denied(503, '注册暂不可用')
        return {n.casefold() for n in names} | {n.casefold() for n in self.policy.ADMINS}

    def throttle(self, *buckets, maximum=6, window=300):
        # Counter increments survive failed authentication/registration transactions.
        with self.transaction() as db:
            blocked = False
            for bucket in buckets:
                key = digest(bucket)
                row = db.execute('SELECT * FROM limits WHERE bucket=?', (key,)).fetchone()
                n = row['n'] + 1 if row and row['until'] > self.now() else 1
                until = row['until'] if row and row['until'] > self.now() else self.now() + window
                db.execute('INSERT OR REPLACE INTO limits VALUES(?,?,?)', (key, n, until))
                blocked = blocked or n > maximum
            db.execute('DELETE FROM limits WHERE until<=?', (self.now(),))
        if blocked:
            raise Denied(429, '请求过多，请稍后重试')

    def audit(self, db, actor, action, rid, subject, reason=''):
        db.execute('INSERT INTO audit(at,actor,action,request_id,subject,reason) VALUES(?,?,?,?,?,?)',
                   (self.now(), actor, action, rid, subject, reason))

    def register(self, name, password, team, purpose):
        key = username(name)
        team, purpose = text_field(team, maximum=80), text_field(purpose)
        if key in self.reserved() or key.startswith('reg.'):
            raise Denied(409, '账号不可使用，请选择其它账号或使用原门户登录')
        encoded = password_hash(password)
        uid, rid = str(uuid.uuid4()), str(uuid.uuid4())
        with self.transaction() as db:
            # Check again immediately before insert: provider unavailable => rollback.
            if key in self.reserved():
                raise Denied(409, '账号不可使用')
            try:
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,0,?)',
                    (uid, name, key, encoded, team, purpose, 'pending', self.now()))
            except sqlite3.IntegrityError:
                raise Denied(409, '账号不可使用，请选择其它账号或使用原门户登录') from None
            db.execute('INSERT INTO requests VALUES(?,?,?,0,?,?,?,?)',
                       (rid, uid, 'pending', self.now(), name, team, purpose))
            self.audit(db, 'reg:' + uid, 'register', rid, uid)
        return {'request_id': rid, 'state': 'pending'}

    def session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        with self.connection() as db:
            # One SQLite read snapshot: token/expiry/epoch/state cannot span revocation.
            row = db.execute('SELECT s.*,u.state AS live_state,u.name AS live_name FROM sessions s '
                             'LEFT JOIN users u ON u.id=s.user_id '
                             'WHERE s.token_hash=? AND s.expires>? AND '
                             '(s.user_id IS NULL OR s.epoch=u.epoch)',
                             (digest(token), self.now())).fetchone()
            if not row:
                return None
            return dict(row)

    def new_session(self, uid=None, legacy_user=None, old=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.transaction() as db:
            epoch = 0
            if uid:
                row = db.execute('SELECT epoch FROM users WHERE id=?', (uid,)).fetchone()
                if not row:
                    raise Denied(401, '请重新登录')
                epoch = row['epoch']
            if old:
                db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(old),))
            db.execute('DELETE FROM sessions WHERE expires<=?', (self.now(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
                       (digest(token), uid, legacy_user, csrf, epoch, self.now() + TTL))
        return token, csrf

    def login(self, name, password, old=None):
        key = username(name)
        # Never resolves a local username into an existing portal identity.
        if key in self.reserved():
            password_matches(password, self.dummy)
            raise Denied(401, '请使用原门户登录')
        with self.connection() as db:
            row = db.execute('SELECT id,password FROM users WHERE name_key=?', (key,)).fetchone()
        valid = password_matches(password, row['password'] if row else self.dummy)
        if not row or not valid:
            raise Denied(401, '账号或密码不正确')
        return self.new_session(uid=row['id'], old=old)

    def logout(self, token):
        with self.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))

    def status(self, uid):
        with self.connection() as db:
            row = db.execute('SELECT id,name,team,purpose,state FROM users WHERE id=?', (uid,)).fetchone()
            if not row:
                raise Denied(401, '请重新登录')
            req = db.execute('SELECT id,status,version,applicant_name,team,purpose FROM requests WHERE user_id=? ORDER BY rowid DESC LIMIT 1',
                             (uid,)).fetchone()
            decision = db.execute("SELECT reason FROM audit WHERE request_id=? AND action IN ('approve','reject','revoke') ORDER BY id DESC LIMIT 1",
                                  (req['id'],)).fetchone()
        return dict(row) | {'request': dict(req) | {'reason': decision['reason'] if decision else ''},
                            'role': 'readonly' if row['state'] == 'readonly' else 'pending'}

    def apply(self, uid, purpose, session_hash):
        purpose = text_field(purpose)
        rid = str(uuid.uuid4())
        with self.transaction() as db:
            # Recheck under the write lock; a pre-revocation CSRF context cannot reapply.
            live = db.execute('SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id '
                'WHERE s.token_hash=? AND s.user_id=? AND s.expires>? AND s.epoch=u.epoch',
                (session_hash, uid, self.now())).fetchone()
            if not live:
                raise Denied(401, '请重新登录')
            row = db.execute('SELECT state,name,team FROM users WHERE id=?', (uid,)).fetchone()
            if not row or row['state'] not in ('rejected', 'revoked'):
                raise Denied(409, '当前状态不能再次申请')
            db.execute('UPDATE users SET state=?,purpose=? WHERE id=?', ('pending', purpose, uid))
            db.execute('INSERT INTO requests VALUES(?,?,?,0,?,?,?,?)',
                       (rid, uid, 'pending', self.now(), row['name'], row['team'], purpose))
            self.audit(db, 'reg:' + uid, 'apply', rid, uid)
        return {'request_id': rid, 'state': 'pending'}

    def decide(self, actor, rid, version, action, reason):
        # Guard at both transport and transaction layer. No username-based elevation.
        if not isinstance(actor, LegacyIdentity) or actor.user not in self.policy.ADMINS or actor.role != 'admin' or not actor.groups:
            raise Denied(403, '仅现有管理员可审批')
        if action not in ('approve', 'reject', 'revoke') or type(version) is not int or version < 0:
            raise Denied(400, '审批参数无效')
        if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9-]{36}', rid):
            raise Denied(400, '申请ID无效')
        reason = text_field(reason)
        wanted = 'approved' if action == 'revoke' else 'pending'
        status, state = {'approve': ('approved', 'readonly'), 'reject': ('rejected', 'rejected'),
                         'revoke': ('revoked', 'revoked')}[action]
        with self.transaction() as db:
            row = db.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
            if not row or row['status'] != wanted or row['version'] != version:
                raise Denied(409, '申请已变化，请刷新后重试')
            uid = row['user_id']
            db.execute('UPDATE requests SET status=?,version=version+1 WHERE id=?', (status, rid))
            db.execute('UPDATE users SET state=? WHERE id=?', (state, uid))
            if action == 'revoke':
                db.execute('UPDATE users SET epoch=epoch+1 WHERE id=?', (uid,))
                db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
            self.audit(db, 'legacy:' + actor.user, action, rid, uid, reason)
        return {'state': state, 'version': version + 1}

    def listing(self, kind, after=0):
        if type(after) is not int or after < 0:
            raise Denied(400, '分页参数无效')
        with self.connection() as db:
            if kind == 'requests':
                rows = db.execute('SELECT r.rowid AS cursor,r.id,r.status,r.version,r.applicant_name AS name,r.team,r.purpose,r.user_id '
                    'FROM requests r WHERE r.rowid>? ORDER BY r.rowid LIMIT 50', (after,))
            else:
                rows = db.execute('SELECT a.*,r.applicant_name AS name,r.team,r.purpose '
                    'FROM audit a JOIN requests r ON r.id=a.request_id WHERE a.id>? ORDER BY a.id LIMIT 50', (after,))
            return [dict(r) for r in rows]


def readonly_allowed(method, uri, group=''):
    if method not in ('GET', 'HEAD') or group not in ('', 'dashboard'):
        return False
    if not isinstance(uri, str) or len(uri) > 2048:
        return False
    try:
        for _ in range(4):
            uri = unquote(uri, errors='strict')
        if '%' in uri or '\\' in uri or any(ord(c) < 32 or ord(c) == 127 for c in uri):
            return False
        parsed = urlsplit(uri)
        if parsed.netloc or parsed.scheme or parsed.fragment or not parsed.path.startswith('/') or parsed.path.startswith('//'):
            return False
        parts = parsed.path.split('/')
        if set(p.lower() for p in parts) & (CONTROL | {'.', '..'}):
            return False
        query = parse_qs(parsed.query, keep_blank_values=True)
        # Empty/bare controls remain present; no unknown or repeated query keys.
        keys = [k.casefold() for k in query]
        if (set(keys) & (CONTROL | {'action', 'op', 'cmd', 'command'}) or
                set(keys) - READ_QUERY_KEYS or len(set(keys)) != len(keys) or
                any(len(values) != 1 or not values[0] or len(values[0]) > 80 for values in query.values())):
            return False
        if any(not re.fullmatch(r'[A-Za-z0-9_.:-]+', values[0]) for values in query.values()):
            return False
        return parsed.path in READ_ROUTES
    except (ValueError, UnicodeError):
        return False


class Adapter:
    def __init__(self, store, *, legacy_resolver, legacy_authorize):
        self.store, self.legacy_resolver, self.legacy_authorize = store, legacy_resolver, legacy_authorize

    def legacy(self, cookies):
        identity = self.legacy_resolver(cookies)
        if identity is not None and (not isinstance(identity, LegacyIdentity) or not identity.groups or
                identity.role not in ('readonly', 'admin') or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', identity.user) or
                any(g not in ('dashboard', 'deploy') for g in identity.groups) or
                (identity.role == 'admin' and identity.user not in self.store.policy.ADMINS)):
            raise Denied(503, '身份源不可用')
        return identity

    def verify(self, cookies, method, uri, group=''):
        """Server-side seam; caller must supply original method/URI from trusted nginx."""
        try:
            identity = self.legacy(cookies)
            session = self.store.session(cookies.get(COOKIE, ''))
            if identity and session and session['user_id']:
                return 403, {}
            if identity:
                code = self.legacy_authorize(identity, method, uri, group)
                if code != 200:
                    return code, {}
                return 200, {'X-Auth-User': identity.user, 'X-Auth-Groups': ','.join(identity.groups),
                             'X-Auth-Role': identity.role}
            if not session or not session['user_id']:
                return 401, {}
            # Collision added after registration also fails closed.
            if session['live_name'].casefold() in self.store.reserved():
                return 403, {}
            if session['live_state'] != 'readonly' or not readonly_allowed(method, uri, group):
                return 403, {}
            return 200, {'X-Auth-User': 'reg:' + session['user_id'], 'X-Auth-Groups': 'dashboard',
                         'X-Auth-Role': 'readonly'}
        except Exception:
            return 503, {}


class App:
    """Pure HTTP-shaped dispatcher. Headers can never construct a legacy identity."""
    def __init__(self, adapter, origin):
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or parsed.netloc not in ('127.0.0.1', 'localhost') and not re.fullmatch(r'(127\.0\.0\.1|localhost):[0-9]+', parsed.netloc):
            raise ValueError('only local loopback origins allowed by candidate')
        if origin != f'{parsed.scheme}://{parsed.netloc}':
            raise ValueError('origin must not contain a path')
        self.adapter, self.store, self.origin = adapter, adapter.store, origin

    def cookie(self, token):
        # Local HTTP demo needs no Secure; any future HTTPS transport must use Secure.
        secure = '; Secure' if self.origin.startswith('https:') else ''
        return f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={TTL if token else 0}{secure}'

    def dispatch(self, method, path, *, headers=None, cookies=None, body=b'', client='local'):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        cookies = cookies or {}
        response_headers = {'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'}
        try:
            result, cookie = self._dispatch(method, path, headers, cookies, body, client)
            if cookie is not None:
                response_headers['Set-Cookie'] = self.cookie(cookie)
            native_cookie = result.pop('__native_cookie', None)
            if native_cookie is not None:
                response_headers['Set-Cookie'] = [response_headers['Set-Cookie'], native_cookie]
            return 200, result, response_headers
        except Denied as exc:
            return exc.code, {'error': exc.message}, response_headers
        except Exception:
            return 503, {'error': '服务暂不可用，请稍后重试'}, response_headers

    def _dispatch(self, method, path, headers, cookies, body, client):
        parsed = urlsplit(path)
        if parsed.path not in ('/api/bootstrap', '/api/register', '/api/login', '/api/native-login', '/api/apply',
                              '/api/logout', '/api/requests', '/api/audit', '/api/decision', '/api/revoke', '/api/permissions'):
            raise Denied(404, '未找到')
        read = parsed.path in ('/api/bootstrap', '/api/requests', '/api/audit')
        if method != ('GET' if read else 'POST'):
            raise Denied(405, '请求方法不允许')
        # Explicit logout uses only session+Origin+CSRF and signature validation;
        # an unavailable membership source must still allow safe revocation.
        identity = None if parsed.path == '/api/logout' else self.adapter.legacy(cookies)
        token = cookies.get(COOKIE, '')
        session = self.store.session(token)
        if identity and session and session['user_id'] and parsed.path != '/api/logout':
            raise Denied(403, '存在不同账号会话，请先退出')
        if parsed.path == '/api/bootstrap':
            self.store.throttle('bootstrap:' + client, maximum=120)
            owner = identity.user if identity else None
            if not session or session['legacy_user'] != owner:
                token, _ = self.store.new_session(legacy_user=owner, old=token)
                session = self.store.session(token)
            status = self.store.status(session['user_id']) if session['user_id'] else {
                'role': identity.role if identity else 'guest', 'name': identity.user if identity else ''}
            result = {'csrf': session['csrf'], 'account': status}
            if hasattr(self.store, 'permission_update'):
                from module_permissions import options
                result['permission_modules'] = options()
            return result, token
        if not session or (session['legacy_user'] != (identity.user if identity else None) and parsed.path != '/api/logout'):
            raise Denied(401, '请刷新页面或重新登录')
        if not read:
            if headers.get('origin') != self.origin or not hmac.compare_digest(headers.get('x-csrf-token', ''), session['csrf']):
                raise Denied(403, '请求校验失败，请刷新页面')
            if headers.get('content-type') != 'application/json' or len(body) > 4096:
                raise Denied(400, '请求格式无效')
            try:
                def pairs(items):
                    result = {}
                    for k, v in items:
                        if k in result:
                            raise ValueError('duplicate key')
                        result[k] = v
                    return result
                form = json.loads(body.decode('utf-8'), object_pairs_hook=pairs)
                if not isinstance(form, dict):
                    raise ValueError('not object')
            except (ValueError, UnicodeError):
                raise Denied(400, '请求格式无效') from None
        else:
            form = {}
        route = parsed.path
        fields = {'/api/register': {'username', 'password', 'team', 'purpose'},
                  '/api/login': {'username', 'password'}, '/api/apply': {'purpose'},
                  '/api/native-login': {'username', 'password'},
                  '/api/logout': set(), '/api/decision': {'request_id', 'version', 'action', 'reason'},
                  '/api/revoke': {'request_id', 'version', 'reason'},
                  '/api/permissions': {'request_id', 'request_version', 'version', 'permissions', 'reason'}}
        if not read and set(form) != fields[route]:
            raise Denied(400, '请求字段无效')
        if route == '/api/native-login':
            if session['user_id'] or identity:
                raise Denied(409, '请先退出当前账号')
            self.store.throttle(route + ':ip:' + client, route + ':name:' + str(form['username']).casefold())
            native_token, native_identity = self.adapter.native_login(form['username'], form['password'])
            token, csrf = self.store.new_session(legacy_user=native_identity.user, old=token)
            return {'csrf':csrf,'account':{'name':native_identity.user,'role':native_identity.role},
                    '__native_cookie':self.adapter.native_cookie(native_token)}, token
        if route in ('/api/register', '/api/login'):
            if session['user_id'] or identity:
                raise Denied(409, '请先退出当前账号')
            key = username(form['username'])
            self.store.throttle(route + ':ip:' + client, route + ':name:' + key)
            if route == '/api/register':
                return self.store.register(form['username'], form['password'], form['team'], form['purpose']), None
            token, csrf = self.store.login(form['username'], form['password'], old=token)
            return {'csrf': csrf, 'account': self.store.status(self.store.session(token)['user_id'])}, token
        if route == '/api/logout':
            if hasattr(self.adapter,'logout'):
                self.adapter.logout(token, cookies)
                return {'ok':True,'__native_cookie':self.adapter.native_cookie('')}, ''
            self.store.logout(token)
            return {'ok': True}, ''
        if route == '/api/apply':
            if not session['user_id']:
                raise Denied(403, '仅注册本人可申请')
            return self.store.apply(session['user_id'], form['purpose'], session['token_hash']), None
        if not identity or identity.role != 'admin' or identity.user not in self.store.policy.ADMINS:
            raise Denied(403, '仅现有管理员可访问')
        if route == '/api/permissions':
            return self.store.permission_update(identity, form['request_id'], form['request_version'], form['version'], form['permissions'], form['reason']), None
        if route in ('/api/requests', '/api/audit'):
            query = parse_qs(parsed.query)
            if set(query) - {'after'} or len(query.get('after', ['0'])) != 1:
                raise Denied(400, '分页参数无效')
            try:
                after = int(query.get('after', ['0'])[0])
            except ValueError:
                raise Denied(400, '分页参数无效') from None
            return {'items': self.store.listing(route.split('/')[-1], after)}, None
        action = form.get('action') if route == '/api/decision' else 'revoke'
        if route == '/api/decision' and action not in ('approve', 'reject'):
            raise Denied(400, '审批动作无效')
        return self.store.decide(identity, form['request_id'], form['version'], action, form['reason']), None

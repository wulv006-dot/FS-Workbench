"""Opaque OAuth state; FS cookies stay in the private server-side database."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from urllib.parse import urlsplit

from .portal import PortalError, Principal


class AuthError(Exception):
    def __init__(self, error='invalid_grant'):
        self.error = error
        super().__init__(error)


def _hash(value):
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise AuthError('invalid_request')
    return hashlib.sha256(value.encode()).hexdigest()


def _redirect_valid(uri):
    if not isinstance(uri, str) or len(uri) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in uri):
        return False
    try:
        p = urlsplit(uri)
        return bool(p.hostname and p.username is None and p.password is None and not p.fragment
                    and p.port != 0 and '\\' not in uri and '#' not in uri
                    and (p.scheme == 'https' or (p.scheme == 'http'
                         and p.hostname in ('localhost', '127.0.0.1', '::1'))))
    except ValueError:
        return False


class AuthStore:
    CODE_TTL = 300
    ACCESS_TTL = 3600
    REFRESH_TTL = 30 * 86400
    TABLE_LIMITS = {'clients': 10000, 'login_requests': 10000, 'pending': 10000,
                    'codes': 10000, 'grants': 10000, 'tokens': 100000}

    def __init__(self, path, resource, portal, *, clock=time.time):
        if not _redirect_valid(resource) or urlsplit(resource).query:
            raise ValueError('absolute protected resource URL required')
        self.path, self.resource, self.portal, self.clock = Path(path).absolute(), resource, portal, clock
        if any(p.is_symlink() for p in (self.path, *self.path.parents)):
            raise ValueError('OAuth storage links are not allowed')
        # The deployment creates a dedicated private directory; never change a shared parent's mode.
        if not self.path.parent.is_dir():
            self.path.parent.mkdir(mode=0o700)
        if os.name == 'posix':
            parent_stat = self.path.parent.stat()
            if parent_stat.st_uid != os.geteuid() or parent_stat.st_mode & 0o077:
                raise ValueError('OAuth storage directory must be private to the service')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1 or (os.name == 'posix'
                    and (file_stat.st_uid != os.geteuid() or file_stat.st_mode & 0o077)):
                raise ValueError('OAuth database must be a private regular file')
        finally:
            os.close(fd)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY, redirects TEXT NOT NULL, name TEXT NOT NULL,
                    grant_types TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY, client TEXT NOT NULL, resource TEXT NOT NULL,
                    subject TEXT NOT NULL, cookie TEXT NOT NULL, scope TEXT NOT NULL,
                    expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS codes (
                    hash TEXT PRIMARY KEY, client TEXT NOT NULL, redirect TEXT NOT NULL,
                    resource TEXT NOT NULL, challenge TEXT NOT NULL, subject TEXT NOT NULL,
                    cookie TEXT NOT NULL, scope TEXT NOT NULL, expires REAL NOT NULL,
                    grant_id TEXT);
                CREATE TABLE IF NOT EXISTS tokens (
                    hash TEXT PRIMARY KEY, kind TEXT NOT NULL, grant_id TEXT NOT NULL,
                    expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS pending (
                    id TEXT PRIMARY KEY, params TEXT NOT NULL, csrf TEXT NOT NULL,
                    subject TEXT NOT NULL, cookie_hash TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_requests (
                    hash TEXT PRIMARY KEY, params TEXT NOT NULL, expires REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS codes_expiry ON codes(expires);
                CREATE INDEX IF NOT EXISTS grants_expiry ON grants(expires);
                CREATE INDEX IF NOT EXISTS grants_revoked ON grants(revoked);
                CREATE INDEX IF NOT EXISTS tokens_expiry ON tokens(expires);
                CREATE INDEX IF NOT EXISTS tokens_grant ON tokens(grant_id);
                CREATE INDEX IF NOT EXISTS pending_expiry ON pending(expires);
                CREATE INDEX IF NOT EXISTS login_requests_expiry ON login_requests(expires);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'grant_types' not in {row['name'] for row in db.execute('PRAGMA table_info(clients)')}:
                db.execute('''ALTER TABLE clients ADD COLUMN grant_types TEXT NOT NULL
                              DEFAULT '["authorization_code", "refresh_token"]' ''')
        self.cleanup()

    @contextmanager
    def _db(self, *, write=True):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def cleanup(self):
        now = self.clock()
        with self._db() as db:
            db.execute('DELETE FROM codes WHERE expires<=?', (now,))
            db.execute('DELETE FROM pending WHERE expires<=?', (now,))
            db.execute('DELETE FROM login_requests WHERE expires<=?', (now,))
            db.execute('''DELETE FROM tokens WHERE expires<=? OR grant_id IN
                          (SELECT id FROM grants WHERE expires<=? OR revoked=1)''', (now, now))
            db.execute('''DELETE FROM grants WHERE expires<=? OR revoked=1
                          OR NOT EXISTS (SELECT 1 FROM tokens WHERE tokens.grant_id=grants.id)''', (now,))

    def _capacity(self, db, table, adding=1):
        if db.execute('SELECT count(*) FROM ' + table).fetchone()[0] + adding > self.TABLE_LIMITS[table]:
            raise AuthError('temporarily_unavailable')

    def register_client(self, redirect_uris, client_name='', grant_types=None):
        if grant_types is None:
            grant_types = ['authorization_code', 'refresh_token']
        if (not isinstance(redirect_uris, list) or not 1 <= len(redirect_uris) <= 10
                or not all(_redirect_valid(uri) for uri in redirect_uris)
                or not isinstance(client_name, str) or len(client_name) > 128
                or any(ord(c) < 32 for c in client_name)
                or not isinstance(grant_types, list)
                or not all(isinstance(grant, str) for grant in grant_types)
                or len(grant_types) != len(set(grant_types))
                or 'authorization_code' not in grant_types
                or set(grant_types) - {'authorization_code', 'refresh_token'}):
            raise AuthError('invalid_client_metadata')
        client_id = secrets.token_urlsafe(32)
        self.cleanup()
        with self._db() as db:
            self._capacity(db, 'clients')
            db.execute('INSERT INTO clients (id,redirects,name,grant_types) VALUES (?,?,?,?)',
                       (client_id, json.dumps(redirect_uris), client_name, json.dumps(grant_types)))
        return self.get_client(client_id)

    def get_client(self, client_id):
        if not isinstance(client_id, str) or not 1 <= len(client_id) <= 128:
            raise AuthError('invalid_client')
        with self._db(write=False) as db:
            row = db.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
        if row is None:
            raise AuthError('invalid_client')
        return dict(client_id=row['id'], redirect_uris=json.loads(row['redirects']),
                    client_name=row['name'], token_endpoint_auth_method='none',
                    grant_types=json.loads(row['grant_types']), response_types=['code'])

    def validate_authorization(self, client_id, redirect_uri, resource, code_challenge, scope='fs.read'):
        client = self.get_client(client_id)
        if redirect_uri not in client['redirect_uris']:
            raise AuthError('invalid_request')
        if resource != self.resource:
            raise AuthError('invalid_target')
        if scope != 'fs.read':
            raise AuthError('invalid_scope')
        if not isinstance(code_challenge, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code_challenge):
            raise AuthError('invalid_request')

    def _validate_request(self, params):
        allowed = {'client_id', 'redirect_uri', 'resource', 'code_challenge', 'code_challenge_method',
                   'response_type', 'scope', 'state'}
        if (not isinstance(params, dict) or set(params) - allowed
                or params.get('response_type') != 'code' or params.get('code_challenge_method') != 'S256'
                or not isinstance(params.get('state', ''), str) or len(params.get('state', '')) > 2048):
            raise AuthError('invalid_request')
        try:
            self.validate_authorization(**{k: params[k] for k in
                ('client_id', 'redirect_uri', 'resource', 'code_challenge')}, scope=params.get('scope', 'fs.read'))
        except KeyError:
            raise AuthError('invalid_request') from None

    def create_login_request(self, params):
        self._validate_request(params)
        request_id = secrets.token_urlsafe(32)
        self.cleanup()
        with self._db() as db:
            self._capacity(db, 'login_requests')
            db.execute('INSERT INTO login_requests VALUES (?,?,?)',
                       (_hash(request_id), json.dumps(params), self.clock() + self.CODE_TTL))
        return request_id

    def consume_login_request(self, request_id):
        request_hash = _hash(request_id)
        with self._db() as db:
            row = db.execute('SELECT * FROM login_requests WHERE hash=?', (request_hash,)).fetchone()
            if row is None or row['expires'] <= self.clock():
                raise AuthError('invalid_request')
            db.execute('DELETE FROM login_requests WHERE hash=?', (request_hash,))
        return json.loads(row['params'])

    def create_pending(self, params, principal):
        self._validate_request(params)
        pending, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.cleanup()
        with self._db() as db:
            self._capacity(db, 'pending')
            db.execute('INSERT INTO pending VALUES (?,?,?,?,?,?)', (pending, json.dumps(params),
                _hash(csrf), principal.subject, _hash(principal.session_cookie), self.clock() + self.CODE_TTL))
        return pending, csrf

    def consume_pending(self, pending_id, csrf_token, principal):
        _hash(pending_id)
        with self._db() as db:
            row = db.execute('SELECT * FROM pending WHERE id=?', (pending_id,)).fetchone()
            if (row is None or row['expires'] <= self.clock() or row['subject'] != principal.subject
                    or not hmac.compare_digest(row['csrf'], _hash(csrf_token))
                    or not hmac.compare_digest(row['cookie_hash'], _hash(principal.session_cookie))):
                raise AuthError('invalid_request')
            db.execute('DELETE FROM pending WHERE id=?', (pending_id,))
        return json.loads(row['params'])

    def issue_code(self, client_id, redirect_uri, resource, code_challenge, principal, scope='fs.read'):
        self.validate_authorization(client_id, redirect_uri, resource, code_challenge, scope)
        self._verify(principal.subject, principal.session_cookie)
        code = secrets.token_urlsafe(32)
        self.cleanup()
        with self._db() as db:
            self._capacity(db, 'codes')
            db.execute('INSERT INTO codes VALUES (?,?,?,?,?,?,?,?,?,NULL)', (_hash(code), client_id,
                redirect_uri, resource, code_challenge, principal.subject, principal.session_cookie,
                scope, self.clock() + self.CODE_TTL))
        return code

    def _verify(self, subject, cookie):
        try:
            principal = self.portal.verify(cookie, '/dashboard/')
        except PortalError as exc:
            if exc.status == 503:
                raise AuthError('temporarily_unavailable') from None
            raise AuthError() from None
        if not hmac.compare_digest(principal.subject, subject):
            raise AuthError()
        return principal

    def _tokens(self, db, grant_id, scope, grant_expires, client_id):
        access = secrets.token_urlsafe(32)
        now = self.clock()
        expires = min(self.ACCESS_TTL, max(0, grant_expires - now))
        tokens = [(_hash(access), 'access', grant_id, now + expires)]
        result = dict(access_token=access, token_type='Bearer', expires_in=int(expires), scope=scope)
        client = db.execute('SELECT grant_types FROM clients WHERE id=?', (client_id,)).fetchone()
        if client is None:
            raise AuthError('invalid_client')
        if 'refresh_token' in json.loads(client['grant_types']):
            refresh = secrets.token_urlsafe(32)
            tokens.append((_hash(refresh), 'refresh', grant_id, grant_expires))
            result['refresh_token'] = refresh
        self._capacity(db, 'tokens', len(tokens))
        db.executemany('INSERT INTO tokens VALUES (?,?,?,?,0)', tokens)
        return result

    @staticmethod
    def _revoke_grant(db, grant_id):
        db.execute("UPDATE grants SET revoked=1,cookie='' WHERE id=?", (grant_id,))

    def exchange_code(self, code, client_id, redirect_uri, resource, code_verifier):
        if not isinstance(code_verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', code_verifier):
            raise AuthError()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b'=').decode()
        replay = False
        self.cleanup()
        with self._db() as db:
            row = db.execute('SELECT * FROM codes WHERE hash=?', (_hash(code),)).fetchone()
            if (row is None or row['expires'] <= self.clock() or row['client'] != client_id
                    or row['redirect'] != redirect_uri or row['resource'] != resource
                    or resource != self.resource or not hmac.compare_digest(row['challenge'], challenge)):
                raise AuthError()
            if row['grant_id']:
                self._revoke_grant(db, row['grant_id'])
                replay = True
            else:
                self._verify(row['subject'], row['cookie'])
                grant = secrets.token_urlsafe(32)
                expires = self.clock() + self.REFRESH_TTL
                self._capacity(db, 'grants')
                db.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?,0)',
                    (grant, client_id, resource, row['subject'], row['cookie'], row['scope'], expires))
                db.execute("UPDATE codes SET grant_id=?,cookie='' WHERE hash=?", (grant, _hash(code)))
                result = self._tokens(db, grant, row['scope'], expires, client_id)
        if replay:
            raise AuthError()
        return result

    def _token(self, db, token, kind, resource, client_id=None):
        row = db.execute('''SELECT t.kind,t.used,t.expires AS token_expires,g.*
                            FROM tokens t JOIN grants g ON g.id=t.grant_id WHERE t.hash=?''',
                         (_hash(token),)).fetchone()
        if (row is None or row['kind'] != kind or row['revoked'] or row['token_expires'] <= self.clock()
                or row['expires'] <= self.clock() or row['resource'] != resource or resource != self.resource
                or (client_id is not None and row['client'] != client_id)):
            raise AuthError()
        return row

    def authenticate(self, access_token, resource):
        with self._db(write=False) as db:
            row = self._token(db, access_token, 'access', resource)
        principal = self._verify(row['subject'], row['cookie'])
        # A logout/revocation may commit while the portal request is in flight.
        with self._db(write=False) as db:
            self._token(db, access_token, 'access', resource)
        return principal

    def refresh(self, refresh_token, client_id, resource):
        replay = False
        self.cleanup()
        with self._db() as db:
            row = self._token(db, refresh_token, 'refresh', resource, client_id)
            if row['used']:
                self._revoke_grant(db, row['id'])
                replay = True
            else:
                self._verify(row['subject'], row['cookie'])
                db.execute('UPDATE tokens SET used=1 WHERE hash=?', (_hash(refresh_token),))
                result = self._tokens(db, row['id'], row['scope'], row['expires'], client_id)
        if replay:
            raise AuthError()
        return result

    def revoke(self, token, client_id):
        if not isinstance(client_id, str) or not 1 <= len(client_id) <= 128:
            raise AuthError('invalid_client')
        with self._db() as db:
            row = db.execute('''SELECT g.id FROM tokens t JOIN grants g ON g.id=t.grant_id
                                WHERE t.hash=? AND g.client=?''', (_hash(token), client_id)).fetchone()
            if row:
                self._revoke_grant(db, row['id'])

"""Read named Players routes with an isolated, server-held browser sub-session."""
from dataclasses import dataclass, field
import hashlib
from http.cookies import CookieError, SimpleCookie
import json
import re
import threading
import time
from urllib.parse import urlsplit

import httpx

from .catalog import ValidationError, permit, validate


ROOT = '/tools/fc27-players'
ID = {'type': 'string', 'pattern': '[0-9a-f]{32}', 'minLength': 32, 'maxLength': 32}
OPERATIONS = {
    'players.status': {'path': '/api/status', 'properties': {}},
    'players.candidates': {'path': '/api/candidates', 'properties': {'collection_id': ID}},
    'players.models': {'path': '/api/models', 'backend': True, 'properties': {
        'snapshot_id': ID, 'page': {'type': 'integer', 'minimum': 1, 'maximum': 10000},
        'per_page': {'type': 'integer', 'minimum': 1, 'maximum': 200},
        'is_rec': {'type': 'integer', 'enum': [0, 1]}, 'status': {'type': 'integer', 'enum': [0, 1]},
        'tag_id': {'type': 'integer', 'minimum': 1},
        'tag_name': {'type': 'string', 'maxLength': 160}, 'keyword': {'type': 'string', 'maxLength': 160}}},
    'players.tags': {'path': '/api/tags', 'backend': True, 'properties': {}},
    'players.jobs': {'path': '/api/jobs', 'properties': {}},
    'players.job': {'path': '/api/jobs/{job_id}', 'properties': {'job_id': ID}, 'required': ['job_id']},
    'players.plan': {'path': '/api/plans/{plan_id}', 'properties': {'plan_id': ID}, 'required': ['plan_id']},
}
for _row in OPERATIONS.values():
    _row['input_schema'] = {'type': 'object', 'properties': _row.pop('properties'),
        'required': _row.pop('required', []), 'additionalProperties': False}


class PlayersError(RuntimeError):
    def __init__(self, code, status_code=503):
        self.code, self.status_code = code, status_code
        super().__init__(code)


@dataclass
class _Session:
    lock: object = field(default_factory=threading.Lock, repr=False)
    sid: str = field(default='', repr=False)
    csrf: str = field(default='', repr=False)
    shared: bool = False
    backend_until: float = 0
    auth_unknown: bool = False


def _project(value):
    if isinstance(value, dict):
        # Execution APIs also carry duplicate raw JSON columns; use their parsed fields.
        return {key: _project(child) for key, child in value.items()
            if key not in {'artifact_path', 'planned_json', 'before_json', 'after_json'}}
    if isinstance(value, list):
        return [_project(child) for child in value]
    return value


class PlayersService:
    def __init__(self, base_url, authorize, *, transport=None, clock=time.monotonic):
        origin = urlsplit(base_url)
        if (origin.scheme != 'https' or not origin.hostname or origin.username is not None
                or origin.password is not None or origin.path not in ('', '/') or origin.query
                or origin.fragment or '\\' in base_url or any(ord(c) < 33 for c in base_url)):
            raise ValueError('fixed_https_origin_required')
        self.base_url, self.authorize = base_url.rstrip('/'), authorize
        self.transport, self.clock = transport, clock
        self._sessions, self._lock = {}, threading.Lock()

    def _session(self, principal):
        cookie = principal.session_cookie
        if (not isinstance(cookie, str) or not cookie or len(cookie) > 8192
                or any(ord(c) < 32 or ord(c) > 126 for c in cookie)
                or re.search(r'(?:^|;\s*)FC27PLAYER_SID=', cookie)):
            raise PlayersError('invalid_saved_session', 401)
        key = (principal.subject, hashlib.sha256(cookie.encode()).digest())
        with self._lock:
            if key not in self._sessions:
                # Upstream bootstrap records never expire; do not evict and silently recreate them.
                if len(self._sessions) >= 512:
                    raise PlayersError('players_session_capacity')
                self._sessions[key] = _Session()
            return self._sessions[key]

    def _http(self, principal, session, method, path, *, params=None):
        permit(self.authorize, principal, ROOT+path, method)
        headers = {'Cookie': principal.session_cookie + ('; FC27PLAYER_SID='+session.sid if session.sid else ''),
                   'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        if method == 'POST':
            headers.update({'Origin': self.base_url, 'X-CSRF-Token': session.csrf})
        maximum = 16384 if path in {'/api/bootstrap', '/api/auth/shared'} else 4194304
        started = time.monotonic()
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False, trust_env=False, timeout=5) as client:
                kwargs = {'params': params} if method == 'GET' else {'json': {}}
                with client.stream(method, self.base_url+ROOT+path, headers=headers, **kwargs) as response:
                    if 300 <= response.status_code < 400:
                        raise PlayersError('players_redirect_rejected', 502)
                    if response.headers.get('Content-Encoding', 'identity') != 'identity':
                        raise PlayersError('players_response_encoding_rejected', 502)
                    length = response.headers.get('Content-Length')
                    if length is not None and (not length.isdigit() or int(length) > maximum):
                        raise PlayersError('players_response_too_large', 502)
                    body = bytearray()
                    for chunk in response.iter_bytes(65536):
                        body.extend(chunk)
                        if len(body) > maximum:
                            raise PlayersError('players_response_too_large', 502)
                        if time.monotonic()-started > 25:
                            raise PlayersError('players_timeout', 504)
                    value = json.loads(body)
                    if not isinstance(value, dict):
                        raise PlayersError('players_invalid_response', 502)
                    cookies = response.headers.get_list('Set-Cookie')
                    return response.status_code, value, cookies
        except httpx.TimeoutException:
            raise PlayersError('players_timeout', 504) from None
        except httpx.HTTPError:
            raise PlayersError('players_unavailable') from None
        except (ValueError, UnicodeError):
            raise PlayersError('players_invalid_response', 502) from None

    @staticmethod
    def _raise(status, value):
        allowed = {'AUTH_REQUIRED', 'MODEL_SNAPSHOT_REQUIRED', 'FS_SHARED_SESSION_DISABLED',
                   'ROLE_REQUIRED', 'BROWSER_SESSION_REQUIRED', 'BACKEND_AUTH_UNAVAILABLE', 'CSRF_INVALID'}
        code = value.get('error')
        raise PlayersError('players_'+code.lower() if code in allowed else 'players_upstream_rejected', status)

    def _bootstrap(self, principal, session):
        status, value, cookies = self._http(principal, session, 'GET', '/api/bootstrap')
        if status != 200:
            self._raise(status, value)
        if (value.get('owner') != principal.subject or value.get('root_path') != ROOT
                or not isinstance(value.get('csrf'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', value['csrf'])
                or type(value.get('shared_backend_session')) is not bool
                or type(value.get('backend_authenticated')) is not bool):
            raise PlayersError('players_invalid_bootstrap', 502)
        sid_values = []
        for header in cookies:
            parsed = SimpleCookie()
            try:
                parsed.load(header)
            except CookieError:
                raise PlayersError('players_invalid_bootstrap', 502) from None
            if 'FC27PLAYER_SID' in parsed:
                sid_values.append(parsed['FC27PLAYER_SID'].value)
        if len(sid_values) > 1 or sid_values and not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', sid_values[0]):
            raise PlayersError('players_invalid_bootstrap', 502)
        if sid_values:
            session.sid = sid_values[0]
        if not session.sid:
            raise PlayersError('players_invalid_bootstrap', 502)
        session.csrf, session.shared = value['csrf'], value['shared_backend_session']
        session.backend_until = self.clock()+1790 if value['backend_authenticated'] else 0
        if value['backend_authenticated']:
            session.auth_unknown = False

    def _backend(self, principal, session):
        if session.auth_unknown:
            self._bootstrap(principal, session)
            if session.auth_unknown:
                raise PlayersError('players_auth_unknown')
        if session.backend_until > self.clock():
            return
        if not session.shared:
            raise PlayersError('players_shared_session_disabled', 409)
        try:
            status, value, _ = self._http(principal, session, 'POST', '/api/auth/shared')
        except PlayersError:
            # A timed-out POST may have rotated CSRF: reconcile via the same SID, never replay it.
            session.auth_unknown = True
            raise
        if status != 200:
            if status >= 500:
                session.auth_unknown = True
            self._raise(status, value)
        if value.get('authenticated') is not True or not isinstance(value.get('csrf'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', value['csrf']):
            session.auth_unknown = True
            raise PlayersError('players_auth_unknown')
        session.csrf, session.backend_until = value['csrf'], self.clock()+1790

    def query(self, principal, operation, arguments):
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ValidationError('unknown_players_operation')
        row = OPERATIONS[operation]
        validate(arguments, row['input_schema'])
        params, path = dict(arguments), row['path']
        for key in ('job_id', 'plan_id'):
            if key in params:
                path = path.replace('{'+key+'}', params.pop(key))
        permit(self.authorize, principal, ROOT+path, 'GET')
        session = self._session(principal)
        with session.lock:
            if not session.sid:
                self._bootstrap(principal, session)
            for attempt in range(2):
                if row.get('backend'):
                    self._backend(principal, session)
                status, value, _ = self._http(principal, session, 'GET', path, params=params)
                if attempt == 0 and status == 403 and value.get('error') == 'BROWSER_SESSION_REQUIRED':
                    self._bootstrap(principal, session)
                    continue
                if attempt == 0 and status == 409 and value.get('error') == 'AUTH_REQUIRED' and row.get('backend'):
                    session.backend_until = 0
                    continue
                if not 200 <= status < 300:
                    self._raise(status, value)
                break
            from .backend import _secret_fields
            projected = _project(value)
            if _secret_fields(projected):
                raise PlayersError('players_sensitive_response_rejected', 502)
            permit(self.authorize, principal, ROOT+path, 'GET')
            from .redaction import redact_data
            return {'status_code': status, 'data': redact_data(projected), 'provenance': {
                'source': 'fc27_players_cloud/player_web/main.py', 'path': ROOT+path, 'method': 'GET',
                'session_preparation': 'bootstrap and optional auth/shared prepare an original FS-authorized read session; no business write'}}

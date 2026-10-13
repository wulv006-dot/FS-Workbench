"""Loopback transport hosted by the existing FS process; no provider secrets here.

Admission/mint/renew are Python calls from the authenticated FS controller, never
HTTP routes. A grant binds one task, owner and lease. Runtime receives only that
short-lived token. Existing ModelGateway remains the sole provider caller.
"""
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import secrets
import threading
import time

from background import background_index, read_section
from pilot import encoded, digest
from runs_contract import WIRE_TOOLS


@dataclass(frozen=True)
class Grant:
    owner: str
    task_id: str
    lease: str
    expires: float


class Grants:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._items = {}
        self._lock = threading.Lock()

    def mint(self, owner, task_id, lease, ttl=600):
        if type(ttl) is not int or not 1 <= ttl <= 600:
            raise ValueError('grant_ttl')
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._items[self._key(token)] = Grant(owner, task_id, lease, self.clock()+ttl)
        return token

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    def resolve(self, token):
        if not isinstance(token, str) or not 40 <= len(token) <= 80 or not token.isascii():
            raise PermissionError('grant_invalid')
        with self._lock:
            item = self._items.get(self._key(token))
        if item is None or self.clock() >= item.expires:
            raise PermissionError('grant_invalid')
        return item

    def renew(self, token, owner, task_id, lease):
        # Trusted FS controller calls this after rechecking task/worker liveness.
        item = self.resolve(token)
        if (item.owner, item.task_id, item.lease) != (owner, task_id, lease):
            raise PermissionError('grant_scope')
        with self._lock:
            self._items[self._key(token)] = Grant(owner, task_id, lease, self.clock()+600)

    def revoke(self, token):
        with self._lock:
            self._items.pop(self._key(token), None)


class Proxy:
    def __init__(self, grants, gateway_for, background=None):
        self.grants, self.gateway_for, self.background = grants, gateway_for, background

    @staticmethod
    def _turn(db_factory, grant, request):
        # Persist request identity before model reservation. SDK transport retry
        # cannot allocate another billable turn, including after FS restart.
        key = digest(request)
        with db_factory() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS hermes_turns ('
                       'owner TEXT, task TEXT, request_digest TEXT, turn INTEGER, '
                       'PRIMARY KEY(owner,task,request_digest), UNIQUE(owner,task,turn))')
            old = db.execute('SELECT turn FROM hermes_turns WHERE owner=? AND task=? AND request_digest=?',
                             (grant.owner, grant.task_id, key)).fetchone()
            if old is not None:
                return old[0]
            turn = db.execute('SELECT COALESCE(MAX(turn),-1)+1 FROM hermes_turns WHERE owner=? AND task=?',
                              (grant.owner, grant.task_id)).fetchone()[0]
            db.execute('INSERT INTO hermes_turns VALUES(?,?,?,?)', (grant.owner, grant.task_id, key, turn))
            return turn

    def dispatch(self, method, path, token, body=None):
        grant = self.grants.resolve(token)
        gateway = self.gateway_for(grant)
        gateway.scope.context(grant.owner, grant.task_id, grant.lease)
        if (method, path) == ('POST', '/fc/tools/call'):
            if not isinstance(body, dict) or set(body) != {'name', 'arguments'}:
                raise ValueError('tool_request')
            return gateway.scope.call(grant.owner, grant.task_id, grant.lease, body['name'], body['arguments'])
        if (method, path) == ('GET', '/fc/context/index') and self.background:
            return background_index(self.background)
        if (method, path) == ('POST', '/fc/context/section') and self.background:
            if not isinstance(body, dict) or set(body) != {'section_id', 'version', 'sha256'}:
                raise ValueError('context_request')
            return read_section(self.background, body['section_id'], expected_version=body['version'],
                                expected_sha256=body['sha256'])
        if (method, path) != ('POST', '/v1/chat/completions'):
            raise PermissionError('route_denied')
        if not isinstance(body, dict) or set(body)-{'messages', 'max_tokens', 'model', 'tools', 'tool_choice', 'stream'}:
            raise ValueError('request_fields')
        if body.get('model') != gateway.budget.policy['model'] or body.get('stream', False) is not False:
            raise ValueError('provider_override')
        if body.get('tool_choice', 'auto') != 'auto':
            raise ValueError('tool_choice')
        if 'tools' in body:
            names = [x.get('function', {}).get('name') for x in body['tools'] if isinstance(x, dict)]
            if len(names) != len(body['tools']) or len(names) != len(set(names)) or set(names) != set(WIRE_TOOLS):
                raise ValueError('tool_allowlist')
        request = {'messages': body.get('messages'), 'max_tokens': body.get('max_tokens')}
        # Validate before recording request identity or changing any ledger table.
        from proxy_gateway import request_body
        request_body(request, gateway.budget.policy['model'])
        turn = self._turn(gateway.budget.db, grant, request)
        receipt = gateway.call(grant.owner, grant.task_id, grant.lease, turn, request)
        message = receipt['message']
        return {'id': receipt['provider_request_id'], 'object': 'chat.completion',
                'created': int(time.time()), 'model': receipt['model'], 'usage': receipt['usage'],
                'choices': [{'index': 0, 'message': message,
                             'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}]}


def start_loopback(proxy, port=8940):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def log_message(self, *args):
            pass  # Never log authorization or request/provider bodies.

        def do_GET(self):
            self._handle('GET')

        def do_POST(self):
            self._handle('POST')

        def _handle(self, method):
            self.connection.settimeout(120)
            try:
                auth = self.headers.get_all('Authorization', [])
                if len(auth) != 1 or not auth[0].startswith('Bearer '):
                    raise PermissionError('auth_required')
                if self.headers.get('Transfer-Encoding'):
                    raise ValueError('transfer_encoding')
                sizes = self.headers.get_all('Content-Length', [])
                if method == 'POST' and (len(sizes) != 1 or not sizes[0].isdigit()):
                    raise ValueError('content_length')
                size = int(sizes[0]) if sizes else 0
                if size > 128000 or (method == 'GET' and size):
                    raise ValueError('request_size')
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('request_incomplete')
                body = json.loads(raw) if size else None
                result = proxy.dispatch(method, self.path, auth[0][7:], body)
                status = 200
            except PermissionError:
                status, result = 403, {'error': {'message': 'request denied', 'type': 'permission_error'}}
            except (ValueError, TypeError, KeyError):
                status, result = 400, {'error': {'message': 'invalid or unreconciled request', 'type': 'invalid_request_error'}}
            except Exception:
                status, result = 503, {'error': {'message': 'request unavailable', 'type': 'server_error'}}
            data = encoded(result).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, name='fs-hermes-proxy', daemon=True)
    worker.start()
    return server, worker

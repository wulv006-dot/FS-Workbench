"""Loopback transport hosted by the existing FS process; no provider secrets here.

Admission/mint/renew are Python calls from the authenticated FS controller, never
HTTP routes. A grant binds one task, owner and lease. Runtime receives only that
short-lived token. Existing ModelGateway remains the sole provider caller.
"""
from dataclasses import dataclass
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import secrets
import threading
import time

from proxy_gateway import MAX_PROVIDER_WIRE_BYTES
from background import background_index, read_section
from pilot import encoded, digest
from runs_contract import WIRE_TOOLS
SAFE_MODEL_ERRORS = frozenset({'pilot_usage_hold', 'context_window_exceeded','provider_transport_recovery_exhausted',
                              'provider_payload_too_large', 'context_rejected',
                              'model_busy', 'provider_outcome_unknown', 'unverified_provider_result', 'stream_not_supported'})


@dataclass(frozen=True)
class Grant:
    owner: str
    task_id: str
    lease: str
    expires: float
    reasoning_effort: str = 'none'


class Grants:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._items = {}
        self._lock = threading.Lock()

    def mint(self, owner, task_id, lease, ttl=600, reasoning_effort='none'):
        if type(ttl) is not int or not 1 <= ttl <= 600:
            raise ValueError('grant_ttl')
        if reasoning_effort not in ('none','low','high','max'):
            raise ValueError('grant_reasoning')
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._items[self._key(token)] = Grant(owner, task_id, lease, self.clock()+ttl,reasoning_effort)
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
        if not isinstance(token, str) or not 40 <= len(token) <= 80 or not token.isascii():
            raise PermissionError('grant_invalid')
        with self._lock:
            item = self._items.get(self._key(token))
            if item is None or self.clock() >= item.expires:
                raise PermissionError('grant_invalid')
            if (item.owner, item.task_id, item.lease) != (owner, task_id, lease):
                raise PermissionError('grant_scope')
            self._items[self._key(token)] = Grant(owner, task_id, lease, self.clock()+600,item.reasoning_effort)

    def revoke(self, token):
        with self._lock:
            self._items.pop(self._key(token), None)


class Proxy:
    def __init__(self, grants, gateway_for, background=None, *, market=None, desktop_identity=None):
        self.grants, self.gateway_for, self.background = grants, gateway_for, background
        self.market, self.desktop_identity = market, desktop_identity
        self._active={};self._active_lock=threading.Lock()

    def active(self,task_id):
        with self._active_lock:return self._active.get(task_id,0)

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
        if (method, path) == ('POST', '/fc/market-snapshot'):
            if not self.market or not self.desktop_identity or not isinstance(token, str) or not secrets.compare_digest(token, self.desktop_identity()):
                raise PermissionError('desktop_identity_required')
            return self.market(body)
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
        if not isinstance(body, dict) or set(body)-{'messages', 'max_tokens', 'model', 'tools', 'tool_choice', 'stream', 'stream_options', 'reasoning_effort'}:
            raise ValueError('request_fields')
        # The FS-issued grant pins the business model mode. The client cannot
        # escalate, disable or silently downgrade it using a body parameter.
        effort=grant.reasoning_effort
        auxiliary='tools' not in body and 'max_tokens' not in body
        # Fixed native compression omits max_tokens/tools and probes streaming.
        # Its pre-dispatch stream probe is rejected as HTTP400, so official
        # auxiliary_client falls back once to a plain request without a charge.
        if auxiliary:
            if body.get('stream_options') not in (None,{'include_usage':True}):raise ValueError('stream_options')
            if body.get('stream') is True:raise ValueError('stream_not_supported')
            if body.get('reasoning_effort') not in (None,'none',effort):raise ValueError('reasoning_policy')
            body=deepcopy(body)
            body.pop('stream_options',None)
            body['reasoning_effort']=effort
            from proxy_gateway import MAX_HERMES_OUTPUT_TOKENS
            body['max_tokens']=MAX_HERMES_OUTPUT_TOKENS
        elif 'stream_options' in body:raise ValueError('stream_options')
        if (effort=='none' and body.get('reasoning_effort') not in (None,'none') or
                effort!='none' and body.get('reasoning_effort')!=effort):
            raise ValueError('reasoning_policy')
        if body.get('model') != gateway.budget.policy['model'] or body.get('stream', False) is not False:
            raise ValueError('provider_override')
        if body.get('tool_choice', 'auto') != 'auto':
            raise ValueError('tool_choice')
        if 'tools' in body:
            names = [x.get('function', {}).get('name') for x in body['tools'] if isinstance(x, dict)]
            if len(names) != len(body['tools']) or len(names) != len(set(names)) or set(names) != set(WIRE_TOOLS):
                raise ValueError('tool_allowlist')
        messages = deepcopy(body.get('messages'))
        if isinstance(messages,list):
            for message in messages:
                if isinstance(message,dict) and 'reasoning' in message:
                    # Fixed Hermes stores a generic carrier beside DeepSeek's
                    # native carrier. Strip only a provably identical duplicate;
                    # divergent/non-native reasoning is an explicit failure.
                    if message.get('role')!='assistant' or (message.get('reasoning')!=message.get('reasoning_content') and
                            not (isinstance(message.get('reasoning'),str) and isinstance(message.get('reasoning_content'),str) and
                                 message['reasoning'].strip()==message['reasoning_content'].strip())):
                        raise ValueError('reasoning_carrier_mismatch')
                    message.pop('reasoning')
                if isinstance(message,dict) and 'reasoning_content' in message:
                    pad=message['reasoning_content']
                    if message.get('role')!='assistant' or (pad is not None and not isinstance(pad,str)):
                        raise ValueError('reasoning_content_policy')
                    if effort=='none':
                        if pad is not None and (len(pad)>8 or pad.strip()): raise ValueError('reasoning_content_policy')
                        message.pop('reasoning_content')
                    elif pad is None:
                        message.pop('reasoning_content')
                    elif len(pad.encode())>MAX_PROVIDER_WIRE_BYTES:
                        raise ValueError('reasoning_content_size')
        request = {'messages': messages, 'max_tokens': body.get('max_tokens')}
        if auxiliary:request['auxiliary']=True
        if effort!='none':request['reasoning_effort']=effort
        # Validate before recording request identity or changing any ledger table.
        from proxy_gateway import request_body
        request_body(request, gateway.budget.policy['model'])
        learning=getattr(gateway,'learning',None);proof=None
        if learning:
            from business_context import effective_learning
            proof=dict(effective_learning(learning,messages),request_sha256=digest(request),status='validated_for_provider')
            gateway.record_learning(proof)
        turn = self._turn(gateway.budget.db, grant, request)
        with self._active_lock:self._active[grant.task_id]=self._active.get(grant.task_id,0)+1
        try:receipt = gateway.call(grant.owner, grant.task_id, grant.lease, turn, request)
        finally:
            with self._active_lock:self._active[grant.task_id]-=1
        if proof:gateway.record_learning(dict(proof,status='provider_response_success',provider_request_id=receipt['provider_request_id'],model=receipt['model']))
        message = receipt['message']
        return {'id': receipt['provider_request_id'], 'object': 'chat.completion',
                'created': int(time.time()), 'model': receipt['model'], 'usage': receipt['usage'],
                'choices': [{'index': 0, 'message': message,
                             'finish_reason':receipt['finish_reason']}]}


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
                if len(sizes) > 1 or (sizes and not sizes[0].isdigit()):
                    raise ValueError('content_length')
                if method == 'POST' and (len(sizes) != 1 or not sizes[0].isdigit()):
                    raise ValueError('content_length')
                size = int(sizes[0]) if sizes else 0
                limit = MAX_PROVIDER_WIRE_BYTES
                if size > limit or (method == 'GET' and size):
                    raise ValueError('request_size')
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('request_incomplete')
                body = json.loads(raw) if size else None
                result = proxy.dispatch(method, self.path, auth[0][7:], body)
                status = 200
            except PermissionError:
                status, result = 403, {'error': {'message': 'request denied', 'type': 'permission_error'}}
            except (ValueError, TypeError, KeyError) as error:
                code = str(error) if isinstance(error, ValueError) and str(error) in SAFE_MODEL_ERRORS else None
                message = 'FC model request blocked: '+code if code else 'invalid or unreconciled request'
                status, result = 400, {'error': {'message': message, 'type': 'invalid_request_error'}}
                if code=='provider_transport_recovery_exhausted':status,result=503,{'error':{'message':'FC model connection recovery exhausted: provider_transport_recovery_exhausted','type':'upstream_transport_error'}}
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

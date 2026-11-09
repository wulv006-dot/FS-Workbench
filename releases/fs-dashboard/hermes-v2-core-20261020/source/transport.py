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

from proxy_gateway import MAX_PROVIDER_WIRE_BYTES, _NativeModelGuardError, _NATIVE_GUARD_MESSAGES
from background import background_index, read_section
from pilot import encoded, digest
from runs_contract import WIRE_TOOLS
SAFE_MODEL_ERRORS = frozenset({'pilot_usage_hold', 'context_window_exceeded','provider_transport_recovery_exhausted',
                              'provider_payload_too_large', 'context_rejected',
                              'model_busy', 'provider_outcome_unknown', 'unverified_provider_result', 'stream_not_supported'})
SAFE_CALCULATION_ERRORS=frozenset({'calculation_evidence','calculation_bindings','calculation_assumption','calculation_operand_mismatch','evidence_path','decimal_required','calculation_fields','calculation_operation'})
_MATERIAL_GUARD_MESSAGES = {
    'request_fields': 'fs_material_transport/material_guard_v1/request_fields',
    'provider_override': 'fs_material_transport/material_guard_v1/provider_override',
    'stream_options': 'fs_material_transport/material_guard_v1/stream_options',
    'reasoning_policy': 'fs_material_transport/material_guard_v1/reasoning_policy',
    'tool_choice': 'fs_material_transport/material_guard_v1/tool_choice',
    'tool_allowlist': 'fs_material_transport/material_guard_v1/tool_allowlist',
    'reasoning_carrier_mismatch': 'fs_material_transport/material_guard_v1/reasoning_carrier_mismatch',
    'reasoning_content_policy': 'fs_material_transport/material_guard_v1/reasoning_content_policy',
    'reasoning_content_size': 'fs_material_transport/material_guard_v1/reasoning_content_size',
}


class _MaterialGuardError(ValueError):
    """Only a fixed local protocol check, never provider/error text."""


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
        from proxy_gateway import structured_scope
        native = structured_scope(gateway.scope)
        if (method, path) == ('POST', '/fc/tools/call'):
            if not isinstance(body, dict) or set(body) != {'name', 'arguments'}:
                raise ValueError('tool_request')
            return gateway.scope.call(grant.owner, grant.task_id, grant.lease, body['name'], body['arguments'])
        if (method, path) == ('GET', '/fc/context/index') and self.background and not native:
            return background_index(self.background)
        if (method, path) == ('POST', '/fc/context/section') and self.background and not native:
            if not isinstance(body, dict) or set(body) != {'section_id', 'version', 'sha256'}:
                raise ValueError('context_request')
            return read_section(self.background, body['section_id'], expected_version=body['version'],
                                expected_sha256=body['sha256'])
        if (method, path) != ('POST', '/v1/chat/completions'):
            raise PermissionError('route_denied')
        book = getattr(gateway.scope, 'book', None)
        material = getattr(book, 'material_execution', False)
        auxiliary=isinstance(body,dict) and 'tools' not in body and 'max_tokens' not in body

        def invalid(code):
            # Scope is established above. Only these literal local checks can
            # identify this producer; matching another exception's text cannot.
            if material and not auxiliary:
                raise _MaterialGuardError(code)
            raise ValueError(code)

        fields = {'messages', 'max_tokens', 'model', 'tools', 'tool_choice', 'stream', 'stream_options', 'reasoning_effort'}
        if native: fields.add('response_format')
        if not isinstance(body, dict) or set(body)-fields:
            invalid('request_fields')
        # The FS-issued grant pins the business model mode. The client cannot
        # escalate, disable or silently downgrade it using a body parameter.
        effort=grant.reasoning_effort
        if native:
            measured=gateway.scope.reasoning_effort()
            if measured is not None:effort=measured
        # Fixed native compression omits max_tokens/tools and probes streaming.
        # Its pre-dispatch stream probe is rejected as HTTP400, so official
        # auxiliary_client falls back once to a plain request without a charge.
        if auxiliary:
            if body.get('stream_options') not in (None,{'include_usage':True}):raise ValueError('stream_options')
            if native and type(body.get('stream',False)) is not bool:raise ValueError('provider_override')
            if body.get('stream') is True and not native:raise ValueError('stream_not_supported')
            if body.get('reasoning_effort') not in (None,'none',effort):raise ValueError('reasoning_policy')
            body=deepcopy(body)
            body.pop('stream_options',None)
            body['reasoning_effort']=effort
            from proxy_gateway import MAX_HERMES_OUTPUT_TOKENS
            body['max_tokens']=MAX_HERMES_OUTPUT_TOKENS
        elif material or native:
            # Streaming is a response encoding, not another provider call or
            # permission to override the trusted model/tool/policy selection.
            if type(body.get('stream', False)) is not bool:
                invalid('provider_override')
            options=body.get('stream_options')
            if (options is not None and
                    (type(options) is not dict or set(options)-{'include_usage'} or
                     ('include_usage' in options and type(options['include_usage']) is not bool))):
                invalid('stream_options')
            if not body.get('stream', False) and options:
                invalid('stream_options')
        elif 'stream_options' in body:invalid('stream_options')
        if (effort=='none' and body.get('reasoning_effort') not in (None,'none') or
                effort!='none' and body.get('reasoning_effort')!=effort):
            invalid('reasoning_policy')
        if (body.get('model') != gateway.budget.policy['model'] or
                (not (native or material and not auxiliary) and body.get('stream', False) is not False)):
            invalid('provider_override')
        if not native and body.get('tool_choice', 'auto') != 'auto':
            invalid('tool_choice')
        tool_schemas = None
        if material or native:
            # The authenticated gateway context above owns this book. Never
            # select a task kind or expand tools from client request fields.
            from proxy_gateway import task_schemas
            tool_schemas = task_schemas(book)
        allowed_tools = (WIRE_TOOLS if tool_schemas is None else
                         tuple(item['function']['name'] for item in tool_schemas))
        if 'tools' in body:
            names = [x.get('function', {}).get('name') for x in body['tools'] if isinstance(x, dict)]
            if len(names) != len(body['tools']) or len(names) != len(set(names)) or set(names) != set(allowed_tools):
                invalid('tool_allowlist')
            if native and body['tools'] != tool_schemas:
                invalid('tool_allowlist')
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
                        invalid('reasoning_carrier_mismatch')
                    message.pop('reasoning')
                if isinstance(message,dict) and 'reasoning_content' in message:
                    pad=message['reasoning_content']
                    if message.get('role')!='assistant' or (pad is not None and not isinstance(pad,str)):
                        invalid('reasoning_content_policy')
                    if effort=='none':
                        if pad is not None and (len(pad)>8 or pad.strip()): invalid('reasoning_content_policy')
                        message.pop('reasoning_content')
                    elif pad is None:
                        message.pop('reasoning_content')
                    elif len(pad.encode())>MAX_PROVIDER_WIRE_BYTES:
                        invalid('reasoning_content_size')
        request = {'messages': messages, 'max_tokens': body.get('max_tokens')}
        if native:
            request['tools'] = deepcopy(tool_schemas) if 'tools' in body else []
            if 'tool_choice' in body:request['tool_choice']=deepcopy(body['tool_choice'])
            if 'response_format' in body:
                request['response_format'] = deepcopy(body['response_format'])
        if auxiliary:request['auxiliary']=True
        if effort!='none':request['reasoning_effort']=effort
        # Validate before recording request identity or changing any ledger table.
        from proxy_gateway import request_body
        if tool_schemas is None:
            request_body(request, gateway.budget.policy['model'])
        else:
            request_body(request, gateway.budget.policy['model'], tool_schemas=tool_schemas, native_chat=native)
        learning=getattr(gateway,'learning',None);proof=None
        if learning:
            from business_context import effective_learning
            from proxy_gateway import schemas
            proof=dict(effective_learning(learning,messages),request_sha256=digest(request),status='validated_for_provider',
                task_id=grant.task_id,owner=grant.owner,project='FS',tool_schema_sha256=digest(schemas()),
                requested_model=gateway.budget.policy['model'],reasoning_effort=effort,
                evidence_refs=sorted(getattr(gateway.scope.book,'evidence',{})),report_contract='hermes-autonomous-original-v1')
            gateway.record_learning(proof)
        turn = self._turn(gateway.budget.db, grant, request)
        with self._active_lock:self._active[grant.task_id]=self._active.get(grant.task_id,0)+1
        try:receipt = gateway.call(grant.owner, grant.task_id, grant.lease, turn, request)
        finally:
            with self._active_lock:self._active[grant.task_id]-=1
        if proof:gateway.record_learning(dict(proof,status='provider_response_success',provider_request_id=receipt['provider_request_id'],model=receipt['model'],model_validation=receipt.get('model_validation'),finish_reason=receipt['finish_reason']))
        message = receipt['message']
        return {'id': receipt['provider_request_id'], 'object': 'chat.completion',
                'created': int(time.time()), 'model': receipt['model'], 'usage': receipt['usage'],
                'choices': [{'index': 0, 'message': message,
                             'finish_reason':receipt['finish_reason']}]}


def _completion_events(result, include_usage):
    # The existing gateway has already completed and accounted for one call.
    # Adapt that receipt to SDK SSE; this does not promise live upstream tokens.
    base={key:result[key] for key in ('id','created','model')}
    base['object']='chat.completion.chunk'
    choice=result['choices'][0]
    delta=deepcopy(choice['message'])
    if 'tool_calls' in delta:
        delta['tool_calls']=[dict(call,index=index) for index,call in enumerate(delta['tool_calls'])]
    events=[dict(base,choices=[{'index':0,'delta':delta,'finish_reason':None}]),
            dict(base,choices=[{'index':0,'delta':{},'finish_reason':choice['finish_reason']}])]
    if include_usage:
        events.append(dict(base,choices=[],usage=result['usage']))
    return (''.join('data: '+encoded(event)+'\n\n' for event in events)+
            'data: [DONE]\n\n').encode('utf-8')


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
            body=None
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
                if self.path=='/v1/chat/completions' and type(error) is ValueError and code=='model_busy':
                    # No reservation or provider call occurred; let the native SDK retry this same request.
                    status=503
                    result['error'].update(type='server_error',code='model_busy')
                if (type(error) is _MaterialGuardError and len(error.args)==1
                        and type(error.args[0]) is str and error.args[0] in _MATERIAL_GUARD_MESSAGES):
                    # Hermes summarizes message only. Select a finite literal
                    # response, never copy an exception's dynamic text.
                    guard_code=error.args[0]
                    result['error'].update(message=_MATERIAL_GUARD_MESSAGES[guard_code],
                        source='fs_material_transport', diagnostic_version='material_guard_v1', code=guard_code)
                if (type(error) is _NativeModelGuardError and len(error.args)==1
                        and type(error.args[0]) is str and error.args[0] in _NATIVE_GUARD_MESSAGES):
                    code=error.args[0]
                    result['error'].update(message=_NATIVE_GUARD_MESSAGES[code],
                        source='fs_native_gateway',diagnostic_version='native_guard_v1',code=code)
                if (self.path=='/fc/tools/call' and isinstance(body,dict) and body.get('name') in ('fc.calculate','mcp__fcro__fc_calculate')
                        and isinstance(error,ValueError) and str(error) in SAFE_CALCULATION_ERRORS):
                    result={'error':{'message':'invalid calculation arguments','type':'invalid_request_error','code':str(error)}}
                if code=='provider_transport_recovery_exhausted':status,result=503,{'error':{'message':'FC model connection recovery exhausted: provider_transport_recovery_exhausted','type':'upstream_transport_error'}}
            except Exception:
                status, result = 503, {'error': {'message': 'request unavailable', 'type': 'server_error'}}
            streaming=(status==200 and self.path=='/v1/chat/completions' and
                       isinstance(body,dict) and body.get('stream') is True)
            data = (_completion_events(result, (body.get('stream_options') or {}).get('include_usage') is True)
                    if streaming else encoded(result).encode('utf-8'))
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8' if streaming else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, name='fs-hermes-proxy', daemon=True)
    worker.start()
    return server, worker

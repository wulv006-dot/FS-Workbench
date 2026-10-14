"""In-process candidate adapters. Inject existing DB/lock/provider; no sockets or keys."""
from copy import deepcopy
import json
import re
from pilot import digest, encoded, TOOLS, SHANGHAI
from runs_contract import WIRE_TOOLS, SEMANTIC_TOOLS

# FS transport protection, not a Hermes or provider context-window claim.
# This applies only to the task-scoped Hermes bridge; legacy advisor stays 96 KB.
MAX_PROVIDER_WIRE_BYTES = 1000000
# Authenticated Bailian model-page readback: both input and context are 1M.
MAX_PROVIDER_CONTEXT_TOKENS = 1000000


def sensitive_context(value):
    if isinstance(value, str):
        # Inspect raw values: JSON serialization turns a newline into "\\n",
        # whose final letter would otherwise hide a standalone key boundary.
        pattern = r'Bearer\s|(?<![A-Za-z0-9_])sk-[A-Za-z0-9]|\\(?:[nrtfb]|u[0-9a-f]{4})sk-[A-Za-z0-9]|Cookie\s*[:=]|password\s*[:=]'
        return re.search(pattern, value, re.I) is not None
    if isinstance(value, dict):
        return any(sensitive_context(k) or sensitive_context(v) for k, v in value.items())
    if isinstance(value, list):
        return any(sensitive_context(v) for v in value)
    return False


def conservative_input_bound(request):
    # Byte fallback plus tool/framing allowance; deliberately not an exact tokenizer.
    return len(encoded(request).encode('utf-8')) + 8192 + 128 * len(request['messages'])


def require_context_window(request):
    if conservative_input_bound(request) + request['max_tokens'] > MAX_PROVIDER_CONTEXT_TOKENS:
        raise ValueError('context_window_exceeded')


def schemas():
    result = []
    for semantic, wire in zip(TOOLS, WIRE_TOOLS):
        fields = {}
        if semantic != 'fc.get_metric_definitions':
            fields['snapshot_id'] = {'type': 'string'}
            if semantic != 'fc.compare_periods':
                fields['window'] = {'type': 'string', 'enum': ['target', 'previous']}
            if semantic == 'fc.get_breakdown':
                fields['dimension'] = {'type': 'string', 'enum': ['platform', 'product', 'bucket']}
        result.append({'type': 'function', 'function': {'name': wire,
            'description': 'FC aggregate evidence only: '+semantic,
            'parameters': {'type': 'object', 'properties': fields,
                           'required': list(fields), 'additionalProperties': False}}})
    from research import tool_schemas
    return result+tool_schemas()


class ScopedTools:
    def __init__(self, tasks, book, clock, deadline=None):
        self.tasks, self.book, self.clock, self.deadline = tasks, book, clock, deadline

    def context(self, owner, task_id, lease):
        task = self.tasks.get(task_id, owner)
        if (task['state'] != 'RUNNING' or task['lease'] != lease or
                task['spec']['snapshot_id'] != self.book.capture_id or
                (self.deadline is not None and self.clock() >= self.deadline)):
            raise PermissionError('inactive_task')
        return task

    def call(self, owner, task_id, lease, name, arguments):
        self.context(owner, task_id, lease)
        if name not in WIRE_TOOLS:
            raise PermissionError('tool_denied')
        result = self.book.call(SEMANTIC_TOOLS[WIRE_TOOLS.index(name)], arguments)
        return {'snapshot_id': self.book.capture_id, 'tool': name, 'data': result}


def request_body(body, model):
    # No client endpoint, credentials, system identity or tool definitions accepted.
    if not isinstance(body, dict) or set(body)-{'messages', 'max_tokens','reasoning_effort'} or not {'messages','max_tokens'}.issubset(body):
        raise ValueError('request_fields')
    effort=body.get('reasoning_effort')
    if effort is not None and effort not in ('low','high','max'):raise ValueError('reasoning_effort_invalid')
    output_limit=16384 if effort in ('high','max') else 6000
    if type(body['max_tokens']) is not int or not 1 <= body['max_tokens'] <= output_limit:
        raise ValueError('output_limit')
    messages = body['messages']
    if not isinstance(messages, list) or not messages:
        raise ValueError('messages_limit')
    pending = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError('message_invalid')
        role = message.get('role')
        allowed = {'role', 'content'}
        if role == 'assistant':
            allowed.add('tool_calls')
            if effort is not None:allowed.add('reasoning_content')
        elif role == 'tool':
            allowed.add('tool_call_id')
        elif role not in {'system', 'user'}:
            raise ValueError('role_invalid')
        if set(message)-allowed or not isinstance(message.get('content'), (str, type(None))):
            raise ValueError('message_fields')
        if 'reasoning_content' in message and not isinstance(message['reasoning_content'],str):raise ValueError('reasoning_content_invalid')
        if role != 'assistant' and not isinstance(message.get('content'), str):
            raise ValueError('message_content')
        if role == 'tool':
            call_id = message.get('tool_call_id')
            if call_id not in pending:
                raise ValueError('orphan_tool_result')
            pending.remove(call_id)
        else:
            if pending:
                raise ValueError('tool_result_missing')
            for call in message.get('tool_calls', []):
                validate_tool_call(call)
                if call['id'] in pending:
                    raise ValueError('duplicate_tool_call')
                pending.add(call['id'])
    if pending:
        raise ValueError('tool_result_missing')
    serialized = encoded(messages)
    if len(serialized.encode()) > MAX_PROVIDER_WIRE_BYTES or sensitive_context(messages):
        raise ValueError('context_rejected')
    result={'model': model, 'messages': deepcopy(messages), 'max_tokens': body['max_tokens'],
            'tools': schemas(), 'tool_choice': 'auto', 'stream': False, 'enable_thinking': effort is not None}
    if effort is not None:result['reasoning_effort']=effort
    # Include trusted tool schemas and all framing in the exact UTF-8 wire budget, before reservation/network.
    if len(encoded(result).encode())>MAX_PROVIDER_WIRE_BYTES:raise ValueError('provider_payload_too_large')
    require_context_window(result)
    return result


def validate_tool_call(call):
    if not isinstance(call, dict) or not {'id','type','function'}<=set(call) or set(call)-{'id','type','function','index'} or call['type'] != 'function':
        raise ValueError('tool_call_fields')
    if 'index' in call and (type(call['index']) is not int or call['index']<0):raise ValueError('tool_call_index')
    if not isinstance(call['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', call['id']):
        raise ValueError('tool_call_id')
    function = call['function']
    if not isinstance(function, dict) or set(function) != {'name', 'arguments'} or function['name'] not in WIRE_TOOLS:
        raise ValueError('tool_call_denied')
    if not isinstance(function['arguments'], str) or len(function['arguments']) > 4096:
        raise ValueError('tool_arguments')
    args = json.loads(function['arguments'])
    if not isinstance(args, dict):
        raise ValueError('tool_arguments')


def safe_diagnostic(response, request, reason):
    """Keep billing/shape evidence, never provider messages or private reasoning."""
    out={'status':'unknown','reason':reason if isinstance(reason,str) and re.fullmatch(r'[a-z0-9_]{3,80}',reason) else 'provider_result_unverified'}
    if not isinstance(response,dict):return out
    if type(response.get('http_status')) is int and 100<=response['http_status']<=599:out['http_status']=response['http_status']
    code=response.get('provider_error_code')
    if isinstance(code,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}',code):out['provider_error_code']=code
    identity=response.get('id')
    if isinstance(identity,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}',identity):out['provider_request_id']=identity
    usage=response.get('usage')
    if isinstance(usage,dict):
        projected={k:usage.get(k) for k in ('prompt_tokens','completion_tokens','total_tokens')}
        if all(type(v) is int and v>=0 for v in projected.values()) and projected['total_tokens']==projected['prompt_tokens']+projected['completion_tokens']:
            out['provider_usage']=projected
    choices=response.get('choices')
    shape={'model_matches':response.get('model')==request.get('model'),'choices_count':len(choices) if isinstance(choices,list) else None}
    if isinstance(choices,list) and choices and isinstance(choices[0],dict):
        choice=choices[0];message=choice.get('message')
        if choice.get('finish_reason') in ('stop','tool_calls','length','content_filter'):shape['finish_reason']=choice['finish_reason']
        if isinstance(message,dict):
            shape.update(message_fields=[k for k in ('role','content','tool_calls','reasoning_content','refusal','function_call') if k in message],
                         unknown_message_field_count=len(set(message)-{'role','content','tool_calls','reasoning_content','refusal','function_call'}))
            calls=message.get('tool_calls')
            if isinstance(calls,list):
                shape['tool_call_count']=len(calls)
                shape['tool_shapes']=[{'known_fields':[k for k in ('id','type','function','index') if k in c],
                    'unknown_field_count':len(set(c)-{'id','type','function','index'}),
                    'index_valid':type(c.get('index')) is int and c['index']>=0 if 'index' in c else None,
                    'function_fields':[k for k in ('name','arguments') if isinstance(c.get('function'),dict) and k in c['function']],
                    'unknown_function_field_count':len(set(c['function'])-{'name','arguments'}) if isinstance(c.get('function'),dict) else None}
                    if isinstance(c,dict) else {'object':False} for c in calls[:64]]
                shape['omitted_tool_shapes']=max(0,len(calls)-64)
    out['response_shape']=shape
    return out


def require_reconciled_usage(rows, accepted_unknowns, owner, task):
    for row in rows:
        if row['state'] == 'invalid_response' and row['owner'] == owner and row['task'] == task:
            raise ValueError('invalid_previous_result')
        if row['state'] not in ('succeeded', 'invalid_response'):
            if (row['state'] == 'unknown' and row['owner'] == owner and row['task'] != task and
                    accepted_unknowns.get(row['fingerprint']) == row['microcny']):
                continue
            raise ValueError('pilot_usage_hold')


class UnifiedBudget:
    """Use existing daily.db() and model_calls. New table is reservation metadata only.

    Constructor is an explicit migration; instantiate ONLY against an isolated fixture
    until shared DB migration is reviewed. No default production path is present.
    """
    def __init__(self, db, policy, clock, accepted_unknowns=None):
        self.db, self.clock = db, clock
        self.accepted_unknowns=dict(accepted_unknowns or {})
        if any(not isinstance(k,str) or not re.fullmatch(r'[a-f0-9]{64}',k) or type(v) is not int or v<=0 for k,v in self.accepted_unknowns.items()):
            raise ValueError('unknown_acceptance_invalid')
        required = {'id', 'model', 'price_version', 'input_microcny', 'output_microcny'}
        if set(policy) != required or any(not isinstance(policy[k], str) or not policy[k]
                for k in ('id', 'model', 'price_version')):
            raise ValueError('policy_fields')
        if any(type(policy[k]) is not int or policy[k] <= 0 for k in required-{'id','model','price_version'}):
            raise ValueError('positive_price_required')
        self.policy = deepcopy(policy)
        with db() as conn:
            if [r[1] for r in conn.execute('PRAGMA table_info(model_calls)')] != ['fingerprint','day','state','content']:
                raise ValueError('existing_ledger_required')
            conn.execute('CREATE TABLE IF NOT EXISTS hermes_reservations ('
                         'fingerprint TEXT PRIMARY KEY, owner TEXT NOT NULL, task TEXT NOT NULL, '
                         'turn INTEGER NOT NULL, request_digest TEXT NOT NULL, policy TEXT NOT NULL, '
                         'tokens INTEGER NOT NULL, microcny INTEGER NOT NULL, '
                         'UNIQUE(owner,task,turn))')

    def restore_tool_indexes(self,owner,task,turn,request):
        # Pinned Hermes normalizes ToolCall into id/name/arguments and omits index.
        # Restore only metadata from this task's already-paid successful receipts.
        if type(turn) is not int or turn<0:raise ValueError('turn_invalid')
        with self.db() as conn:
            rows=conn.execute("SELECT m.content FROM hermes_reservations r JOIN model_calls m ON r.fingerprint=m.fingerprint WHERE r.owner=? AND r.task=? AND r.turn<? AND m.state='succeeded' ORDER BY r.turn",(owner,task,turn)).fetchall()
        calls={}
        for row in rows:
            for call in json.loads(row[0]).get('message',{}).get('tool_calls',[]):
                if 'index' in call:calls[call['id']]=call
        for message in request['messages']:
            for call in message.get('tool_calls',[]):
                original=calls.get(call['id'])
                if original is None:continue
                if (call['function']['name']!=original['function']['name'] or
                    json.loads(call['function']['arguments'])!=json.loads(original['function']['arguments']) or
                    'index' in call and call['index']!=original['index']):raise ValueError('provider_tool_history_changed')
                call['index']=original['index']
        if len(encoded(request['messages']).encode())>MAX_PROVIDER_WIRE_BYTES:raise ValueError('context_rejected')
        return request

    def reserve(self, owner, task, turn, request, input_bound, daily_limit=0):
        if type(turn) is not int or turn < 0:
            raise ValueError('turn_invalid')
        if type(input_bound) is not int or input_bound <= 0:
            raise ValueError('trusted_token_bound_required')
        day = self.clock().astimezone(SHANGHAI).date().isoformat()
        request_hash = digest(request)
        fingerprint = digest({'hermes': 1, 'owner': owner, 'task': task, 'turn': turn, 'request': request_hash})
        p = self.policy
        tokens = input_bound+request['max_tokens']
        cost = input_bound*p['input_microcny']+request['max_tokens']*p['output_microcny']
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT r.*,m.state,m.content FROM hermes_reservations r JOIN model_calls m '
                               'ON r.fingerprint=m.fingerprint WHERE r.owner=? AND r.task=? AND r.turn=?', (owner,task,turn)).fetchone()
            if old:
                if old['request_digest'] != request_hash or old['policy'] != encoded(p):
                    raise ValueError('turn_conflict')
                if old['state'] != 'succeeded':
                    raise ValueError('unknown_previous_attempt')
                return fingerprint, json.loads(old['content'])
            count = conn.execute('SELECT COUNT(*) FROM model_calls WHERE day=?', (day,)).fetchone()[0]
            if daily_limit and count >= daily_limit:
                raise ValueError('daily_model_limit')
            rows = conn.execute('SELECT r.*,m.state,m.content,m.day FROM hermes_reservations r JOIN model_calls m '
                                'ON r.fingerprint=m.fingerprint').fetchall()
            require_reconciled_usage(rows, self.accepted_unknowns, owner, task)
            task_cost = task_tokens = day_cost = turns = 0
            for row in rows:
                if row['state'] not in ('succeeded', 'invalid_response'):
                    continue  # Already confirmed for a different task; never settle it as zero.
                receipt = json.loads(row['content'])
                if row['day'] == day:
                    day_cost += receipt['cost_microcny']
                if row['owner'] == owner and row['task'] == task:
                    if row['policy'] != encoded(p):
                        raise ValueError('task_policy_changed')
                    task_cost += receipt['cost_microcny']; task_tokens += receipt['usage']['total_tokens']; turns += 1
            conn.execute("INSERT INTO model_calls VALUES(?,?,'started',NULL)", (fingerprint,day))
            conn.execute('INSERT INTO hermes_reservations VALUES(?,?,?,?,?,?,?,?)',
                         (fingerprint,owner,task,turn,request_hash,encoded(p),tokens,cost))
        return fingerprint, None

    def settle(self, fingerprint, response, request, input_bound):
        try:
            usage = {key: response['usage'][key] for key in ('prompt_tokens','completion_tokens','total_tokens')}
            if any(type(x) is not int or x < 0 for x in usage.values()):
                raise ValueError('usage_invalid')
            if usage['total_tokens'] != usage['prompt_tokens']+usage['completion_tokens'] or usage['prompt_tokens'] > input_bound or usage['completion_tokens'] > request['max_tokens']:
                raise ValueError('usage_outside_reservation')
            if not isinstance(response['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', response['id']):
                raise ValueError('provider_receipt_invalid')
            choices = response['choices']
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError('choices_invalid')
            finish_reason=choices[0].get('finish_reason','tool_calls' if choices[0].get('message',{}).get('tool_calls') else 'stop')
            if finish_reason not in ('stop','tool_calls','length','content_filter'):raise ValueError('finish_reason_invalid')
            message = deepcopy(choices[0]['message'])
            if not isinstance(message, dict):
                raise ValueError('response_message_invalid')
            # Providers may include an empty reasoning slot even with thinking off.
            if message.get('reasoning_content', None) is None or message.get('reasoning_content')=='':
                message.pop('reasoning_content', None)
            # Standard optional null slots carry no instruction or authority.
            for optional in ('refusal','audio','function_call','tool_calls'):
                if optional in message and message[optional] is None:message.pop(optional)
            allowed={'role','content','tool_calls'} | ({'reasoning_content'} if request['enable_thinking'] else set())
            if not isinstance(message, dict) or message.get('role') != 'assistant' or set(message)-allowed:
                raise ValueError('response_message_invalid')
            if 'reasoning_content' in message and not isinstance(message['reasoning_content'],str):raise ValueError('response_reasoning_invalid')
            if message.get('content') is not None and not isinstance(message['content'], str):
                raise ValueError('response_content_invalid')
            calls = message.get('tool_calls', [])
            if not isinstance(calls, list):
                raise ValueError('response_tools_limit')
            ids = set()
            for call in calls:
                # Retain verified Bailian index metadata in provider replay.
                validate_tool_call(call)
                if call['id'] in ids:
                    raise ValueError('duplicate_tool_call')
                ids.add(call['id'])
            if len(encoded(message).encode()) > MAX_PROVIDER_WIRE_BYTES:
                raise ValueError('response_size')
            p = self.policy
            receipt = {'status':'succeeded', 'provider_request_id':response['id'], 'usage':usage,
                       'cost_microcny':usage['prompt_tokens']*p['input_microcny']+usage['completion_tokens']*p['output_microcny'],
                       'price_version':p['price_version'], 'model':p['model'], 'message':message,
                       'cost_basis':'configured_public_rate_estimate_not_account_invoice',
                       'enable_thinking':request['enable_thinking'],'reasoning_effort':request.get('reasoning_effort')}
            receipt['finish_reason']=finish_reason
            reasoning_tokens=response.get('usage',{}).get('completion_tokens_details',{}).get('reasoning_tokens') if isinstance(response.get('usage',{}).get('completion_tokens_details'),dict) else None
            if reasoning_tokens is not None:
                if type(reasoning_tokens)is not int or not 0<=reasoning_tokens<=usage['completion_tokens']:raise ValueError('reasoning_usage_invalid')
                receipt['reasoning_tokens']=reasoning_tokens  # Already included in completion, never double charged.
        except (ValueError, TypeError, KeyError) as error:
            diagnostic=safe_diagnostic(response,request,str(error))
            usage=diagnostic.get('provider_usage')
            # A malformed model message must fail the run, while a verified
            # receipt/usage still accounts paid work exactly once. No fake success.
            if (usage and 'provider_request_id' in diagnostic and
                    diagnostic.get('response_shape',{}).get('model_matches') is True and
                    usage['prompt_tokens']<=input_bound and usage['completion_tokens']<=request['max_tokens']):
                receipt=dict(diagnostic,status='invalid_response',usage=usage,
                             cost_microcny=usage['prompt_tokens']*self.policy['input_microcny']+usage['completion_tokens']*self.policy['output_microcny'],
                             price_version=self.policy['price_version'],model=self.policy['model'],
                             cost_basis='configured_public_rate_estimate_not_account_invoice',
                             enable_thinking=request['enable_thinking'],reasoning_effort=request.get('reasoning_effort'))
                with self.db() as conn:
                    updated=conn.execute("UPDATE model_calls SET state='invalid_response',content=? WHERE fingerprint=? AND state='started'",(encoded(receipt),fingerprint))
                    if updated.rowcount!=1:raise ValueError('settlement_state')
            else:self.hold(fingerprint,diagnostic)
            raise ValueError('unverified_provider_result') from None
        with self.db() as conn:
            updated = conn.execute("UPDATE model_calls SET state='succeeded',content=? WHERE fingerprint=? AND state='started'",
                                   (encoded(receipt),fingerprint))
            if updated.rowcount != 1:
                raise ValueError('settlement_state')
        return deepcopy(receipt)

    def hold(self, fingerprint, diagnostic=None):
        with self.db() as conn:
            conn.execute("UPDATE model_calls SET state='unknown',content=? WHERE fingerprint=? AND state='started'", (encoded(diagnostic) if diagnostic else None,fingerprint))


class ModelGateway:
    def __init__(self, scope, budget, provider_slot, provider, input_bound, daily_limit):
        self.scope, self.budget, self.slot = scope, budget, provider_slot
        self.provider, self.input_bound, self.daily_limit = provider, input_bound, daily_limit

    def call(self, owner, task_id, lease, turn, body):
        self.scope.context(owner, task_id, lease)
        request = self.budget.restore_tool_indexes(owner,task_id,turn,request_body(body,self.budget.policy['model']))
        if len(encoded(request).encode())>MAX_PROVIDER_WIRE_BYTES:raise ValueError('provider_payload_too_large')
        require_context_window(request)  # Recheck after trusted replay metadata is restored.
        bound = self.input_bound(request)  # Production requires a verified conservative tokenizer.
        with self.slot() as acquired:
            if not acquired:
                raise ValueError('model_busy')
            self.scope.context(owner, task_id, lease)
            limit = self.daily_limit()
            if type(limit) is not int or limit < 0:
                raise ValueError('daily_limit_invalid')
            # Existing global call-count limit is checked atomically for new calls only.
            fingerprint, prior = self.budget.reserve(owner,task_id,turn,request,bound,limit)
            if prior is not None:
                return prior
            try:
                self.scope.context(owner,task_id,lease)
                response = self.provider(request)
            except Exception as error:
                self.budget.hold(fingerprint,safe_diagnostic(getattr(error,'response',None),request,str(error)))
                raise ValueError('provider_outcome_unknown') from None
            receipt = self.budget.settle(fingerprint,response,request,bound)
            # Paid work is accounted even when cancellation arrives during the request.
            self.scope.context(owner,task_id,lease)
            return receipt

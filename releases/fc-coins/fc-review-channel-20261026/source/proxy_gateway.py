"""In-process candidate adapters. Inject existing DB/lock/provider; no sockets or keys."""
from copy import deepcopy
import json
import re
from pilot import digest, encoded, TOOLS, SHANGHAI
from runs_contract import WIRE_TOOLS, SEMANTIC_TOOLS

# FS transport protection, not a Hermes or provider context-window claim.
# This applies only to the task-scoped Hermes bridge; legacy advisor stays 96 KB.
MAX_PROVIDER_WIRE_BYTES = 10000000
# Official DeepSeek /models authenticated readback: joint context is 1,048,576.
MAX_PROVIDER_CONTEXT_TOKENS = 1048576
# Official direct maximum; 384 Ki tokens includes reasoning and visible output.
MAX_HERMES_OUTPUT_TOKENS = 393216
MAX_PROVIDER_WAIT_SECONDS = 1800


def sensitive_context(value):
    if isinstance(value, str):
        # Explicit user instruction: sk- text is allowed in this FC pilot.
        return re.search(r'Bearer\s|Cookie\s*[:=]|password\s*[:=]', value, re.I) is not None
    if isinstance(value, dict):
        return any(sensitive_context(k) or sensitive_context(v) for k, v in value.items())
    if isinstance(value, list):
        return any(sensitive_context(v) for v in value)
    return False


def conservative_input_bound(request):
    # Byte fallback plus tool/framing allowance; deliberately not an exact tokenizer.
    return len(encoded(request).encode('utf-8')) + 8192 + 128 * len(request['messages'])


def require_context_window(request):
    # Byte/framing estimates are reservation metadata, never a token admission gate.
    # Pinned native compaction uses the configured 1M joint context; the vendor
    # validates its actual token window. Do not reject bytes as if they were tokens.
    return None


def schemas():
    result = []
    for semantic, wire in zip(TOOLS, WIRE_TOOLS):
        fields = {}
        if semantic != 'fc.get_metric_definitions':
            fields['snapshot_id'] = {'type': 'string'}
            if semantic != 'fc.compare_periods':
                fields['window'] = {'type': 'string', 'enum': ['target', 'previous']}
            if semantic == 'fc.get_breakdown':
                fields['dimension'] = {'type': 'string', 'enum': ['platform', 'product']}
        result.append({'type': 'function', 'function': {'name': wire,
            'description': 'FC aggregate evidence only: '+semantic,
            'parameters': {'type': 'object', 'properties': fields,
                           'required': list(fields), 'additionalProperties': False}}})
    from research import tool_schemas
    from strategy_tools import schemas as strategy_schemas
    from conversation_file_tools import tool_schemas as file_schemas
    return result+tool_schemas()+strategy_schemas()+file_schemas()


def native_scope(scope):
    if getattr(scope, 'native_chat', False) is not True:
        return False
    from native_chat import NativeChatScope
    return isinstance(scope, NativeChatScope)


def task_schemas(book):
    if native_scope(book):
        return book.schemas()
    if getattr(book, 'material_execution', False):
        from conversation_file_tools import tool_schemas
        return tool_schemas(scope='material_execution_files')
    return schemas()


class ScopedTools:
    def __init__(self, tasks, book, clock, deadline=None):
        self.tasks, self.book, self.clock, self.deadline = tasks, book, clock, deadline

    def context(self, owner, task_id, lease):
        task = self.tasks.get(task_id, owner)
        if (task['state'] != 'RUNNING' or task['lease'] != lease or
                task['spec']['snapshot_id'] != self.book.capture_id or
                (self.deadline is not None and self.clock() >= self.deadline)):
            raise PermissionError('inactive_task')
        if getattr(self.book, 'material_execution', False) and self.book.authorize_execution() is not True:
            raise PermissionError('material_execution_inactive')
        return task

    def call(self, owner, task_id, lease, name, arguments):
        self.context(owner, task_id, lease)
        if getattr(self.book, 'material_execution', False):
            from conversation_file_tools import WIRE_NAMES
            if name not in WIRE_NAMES:
                raise PermissionError('material_tool_denied')
        if name not in WIRE_TOOLS:
            raise PermissionError('tool_denied')
        semantic=SEMANTIC_TOOLS[WIRE_TOOLS.index(name)]
        from conversation_file_tools import NAMES as FILE_NAMES
        if semantic in FILE_NAMES and not getattr(self.book, '_conversation_file_tools', False):
            raise PermissionError('conversation_file_context_required')
        from strategy_tools import NAMES,call
        if semantic in NAMES:result=call(self,owner,task_id,lease,semantic,arguments)
        else:result = self.book.call(semantic, arguments)
        return {'snapshot_id': self.book.capture_id, 'tool': name, 'data': result}


def request_body(body, model, *, tool_schemas=None, native_chat=False):
    # No client endpoint, credentials, system identity or tool definitions accepted.
    fields = {'messages', 'max_tokens', 'reasoning_effort', 'auxiliary'}
    if native_chat:
        fields.add('tools')
    if not isinstance(body, dict) or set(body)-fields or not {'messages','max_tokens'}.issubset(body):
        raise ValueError('request_fields')
    if native_chat and (tool_schemas is None or body.get('tools') not in (None, [], tool_schemas)):
        raise ValueError('tool_allowlist')
    effort=body.get('reasoning_effort')
    if effort is not None and effort not in ('low','high','max'):raise ValueError('reasoning_effort_invalid')
    auxiliary=body.get('auxiliary',False)
    if type(auxiliary) is not bool:raise ValueError('auxiliary_invalid')
    output_limit=MAX_HERMES_OUTPUT_TOKENS
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
        structured = native_chat and role == 'user' and type(message.get('content')) is list
        if set(message)-allowed or (not structured and not isinstance(message.get('content'), (str, type(None)))):
            raise ValueError('message_fields')
        if structured:
            validate_native_content(message['content'])
        if 'reasoning_content' in message and not isinstance(message['reasoning_content'],str):raise ValueError('reasoning_content_invalid')
        if role != 'assistant' and not structured and not isinstance(message.get('content'), str):
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
                validate_tool_call(call, tool_schemas=tool_schemas if native_chat else None)
                if call['id'] in pending:
                    raise ValueError('duplicate_tool_call')
                pending.add(call['id'])
    if pending:
        raise ValueError('tool_result_missing')
    serialized = encoded(messages)
    if len(serialized.encode()) > MAX_PROVIDER_WIRE_BYTES or (not native_chat and sensitive_context(messages)):
        raise ValueError('context_rejected')
    result={'model': model, 'messages': deepcopy(messages), 'max_tokens': body['max_tokens'],
            'tools': [] if auxiliary else (schemas() if tool_schemas is None else deepcopy(tool_schemas)), 'tool_choice': 'auto', 'stream': False, 'enable_thinking': effort is not None}
    if native_chat and 'tools' in body:
        result['tools'] = deepcopy(body['tools'])
    if effort is not None:result['reasoning_effort']=effort
    # Include trusted tool schemas and all framing in the exact UTF-8 wire budget, before reservation/network.
    if len(encoded(result).encode())>MAX_PROVIDER_WIRE_BYTES:raise ValueError('provider_payload_too_large')
    require_context_window(result)
    return result


def validate_native_content(content):
    """OpenAI user text/image parts; file bytes are delivered by the workspace bridge."""
    if not content:
        raise ValueError('message_content')
    for part in content:
        if type(part) is not dict:
            raise ValueError('message_content')
        if part.get('type') == 'text':
            if set(part) != {'type', 'text'} or type(part['text']) is not str:
                raise ValueError('message_content')
        elif part.get('type') == 'image_url':
            image = part.get('image_url')
            if (set(part) != {'type', 'image_url'} or type(image) is not dict or
                    set(image)-{'url', 'detail'} or type(image.get('url')) is not str or
                    not re.fullmatch(r'data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}', image['url']) or
                    image.get('detail', 'auto') not in ('auto', 'low', 'high')):
                raise ValueError('message_content')
        else:
            raise ValueError('message_content')


def validate_tool_call(call, *, tool_schemas=None):
    if not isinstance(call, dict) or not {'id','type','function'}<=set(call) or set(call)-{'id','type','function','index'} or call['type'] != 'function':
        raise ValueError('tool_call_fields')
    if 'index' in call and (type(call['index']) is not int or call['index']<0):raise ValueError('tool_call_index')
    if not isinstance(call['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', call['id']):
        raise ValueError('tool_call_id')
    function = call['function']
    allowed_names = set(WIRE_TOOLS) if tool_schemas is None else {item['function']['name'] for item in tool_schemas}
    if isinstance(function,dict) and allowed_names == set(WIRE_TOOLS):
        aliases={semantic:wire for semantic,wire in zip(SEMANTIC_TOOLS,WIRE_TOOLS)}
        aliases.update({semantic.replace('.','_'):wire for semantic,wire in zip(SEMANTIC_TOOLS,WIRE_TOOLS)})
        name=function.get('name')
        if isinstance(name,str) and name in aliases:function['name']=aliases[name]
    if not isinstance(function, dict) or set(function) != {'name', 'arguments'} or function['name'] not in allowed_names:
        raise ValueError('tool_call_denied')
    if not isinstance(function['arguments'], str) or len(function['arguments'].encode('utf-8')) > MAX_PROVIDER_WIRE_BYTES:
        raise ValueError('tool_arguments')
    try:
        args = json.loads(function['arguments'])
    except json.JSONDecodeError:
        raise ValueError('tool_arguments_json_invalid') from None
    if not isinstance(args, dict):
        raise ValueError('tool_arguments')


def transport_trace(response):
    """Non-secret correlation only; headers and model text never enter this projection."""
    if not isinstance(response,dict):return {}
    out={}
    for key in ('local_trace_id','provider_response_id'):
        value=response.get(key)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}',value):out[key]=value
    for key in ('provider_http_request_id','provider_ds_trace_id'):
        value=response.get(key)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',value):out[key]=value
    value=response.get('request_started_at')
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00',value):out['request_started_at']=value
    value=response.get('response_headers_received')
    if type(value) is bool:out['response_headers_received']=value
    value=response.get('transport_phase')
    if value in ('opening','reading_stream','reading_body','http_rejected'):out['transport_phase']=value
    for key in ('response_bytes_received','stream_events_received'):
        value=response.get(key)
        if type(value) is int and 0<=value<=1000000000:out[key]=value
    return out


def safe_diagnostic(response, request, reason):
    """Keep billing/shape evidence, never provider messages or private reasoning."""
    out={'status':'unknown','reason':reason if isinstance(reason,str) and re.fullmatch(r'[a-z0-9_]{3,80}',reason) else 'provider_result_unverified'}
    if not isinstance(response,dict):return out
    out.update(transport_trace(response))
    if type(response.get('http_status')) is int and 100<=response['http_status']<=599:out['http_status']=response['http_status']
    for key in ('transport_error_type','transport_reason_type'):
        if response.get(key) in ('TimeoutError','URLError','OSError','ConnectionResetError','ConnectionRefusedError','BrokenPipeError','SSLError','RemoteDisconnected','IncompleteRead'):
            out[key]=response[key]
    for key in ('elapsed_seconds','timeout_seconds'):
        value=response.get(key)
        if type(value) in (int,float) and 0<=value<=86400:out[key]=value
    code=response.get('provider_error_code')
    if isinstance(code,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}',code):out['provider_error_code']=code
    direction=response.get('inspection_direction')
    if direction in ('input','output','unknown'):out['inspection_direction']=direction
    identity=response.get('provider_request_id') or response.get('id')
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
                    'unknown_function_field_count':len(set(c['function'])-{'name','arguments'}) if isinstance(c.get('function'),dict) else None,
                    'tool_name':c['function'].get('name') if isinstance(c.get('function'),dict) and isinstance(c['function'].get('name'),str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',c['function']['name']) else None}
                    if isinstance(c,dict) else {'object':False} for c in calls[:64]]
                shape['omitted_tool_shapes']=max(0,len(calls)-64)
    out['response_shape']=shape
    return out


def transport_reset(value):
    return isinstance(value,dict) and (value.get('transport_error_type')=='ConnectionResetError' or value.get('transport_reason_type')=='ConnectionResetError')


def require_reconciled_usage(rows, accepted_unknowns, owner, task, allow_unknown_costs=False, current_transport_unknowns=(), active_tasks=()):
    for row in rows:
        if row['state'] == 'invalid_response' and row['owner'] == owner and row['task'] == task:
            raise ValueError('invalid_previous_result')
        if row['state']=='started' and row['task']!=task and (row['owner'],row['task']) in active_tasks:
            continue  # Accounted in-flight work in another live lane is not an unknown outcome.
        if row['state'] not in ('succeeded', 'invalid_response'):
            if (row['state'] == 'unknown' and (row['task'] != task or allow_unknown_costs and row['fingerprint'] in current_transport_unknowns) and
                    (allow_unknown_costs or row['owner'] == owner and accepted_unknowns.get(row['fingerprint']) == row['microcny'])):
                continue
            raise ValueError('pilot_usage_hold')


class UnifiedBudget:
    """Use existing daily.db() and model_calls. New table is reservation metadata only.

    Constructor is an explicit migration; instantiate ONLY against an isolated fixture
    until shared DB migration is reviewed. No default production path is present.
    """
    def __init__(self, db, policy, clock, accepted_unknowns=None, allow_unknown_costs=False):
        self.db, self.clock = db, clock
        if type(allow_unknown_costs) is not bool:raise ValueError('unknown_cost_policy_invalid')
        self.allow_unknown_costs=allow_unknown_costs
        self.active_tasks=lambda:()
        self.accepted_unknowns=dict(accepted_unknowns or {})
        if any(not isinstance(k,str) or not re.fullmatch(r'[a-f0-9]{64}',k) or type(v) is not int or v<=0 for k,v in self.accepted_unknowns.items()):
            raise ValueError('unknown_acceptance_invalid')
        required = {'id', 'model', 'price_version', 'input_microcny', 'output_microcny'}
        if set(policy) != required or any(not isinstance(policy[k], str) or not policy[k]
                for k in ('id', 'model', 'price_version')):
            raise ValueError('policy_fields')
        unknown_price = (policy['id']=='no-pilot-quotas-deepseek-direct-stream-tokens-only-v2' and policy['model']=='deepseek-flash' and
                         policy['price_version']=='deepseek-direct-no-cny-invoice-or-fx-v1' and
                         policy['input_microcny'] is None and policy['output_microcny'] is None)
        if not unknown_price and any(type(policy[k]) is not int or policy[k] <= 0 for k in required-{'id','model','price_version'}):
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
        # Existing NOT NULL column: -1 explicitly means unavailable CNY amount, never zero cost.
        cost = input_bound*p['input_microcny']+request['max_tokens']*p['output_microcny'] if p['input_microcny'] is not None else -1
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
            transport_unknowns={row['fingerprint'] for row in rows if row['state']=='unknown' and row['owner']==owner and row['task']==task and row['content'] and transport_reset(json.loads(row['content']))}
            require_reconciled_usage(rows, self.accepted_unknowns, owner, task, self.allow_unknown_costs,transport_unknowns,self.active_tasks())
            task_cost = task_tokens = day_cost = turns = 0
            for row in rows:
                if row['state'] not in ('succeeded', 'invalid_response'):
                    continue  # Already confirmed for a different task; never settle it as zero.
                receipt = json.loads(row['content'])
                if row['day'] == day:
                    day_cost += receipt['cost_microcny'] if receipt['cost_microcny'] is not None else 0
                if row['owner'] == owner and row['task'] == task:
                    if row['policy'] != encoded(p):
                        raise ValueError('task_policy_changed')
                    task_cost += receipt['cost_microcny'] if receipt['cost_microcny'] is not None else 0; task_tokens += receipt['usage']['total_tokens']; turns += 1
            conn.execute("INSERT INTO model_calls VALUES(?,?,'started',NULL)", (fingerprint,day))
            conn.execute('INSERT INTO hermes_reservations VALUES(?,?,?,?,?,?,?,?)',
                         (fingerprint,owner,task,turn,request_hash,encoded(p),tokens,cost))
        return fingerprint, None

    def prior_transport_reset(self,owner,task,turn,request):
        if not self.allow_unknown_costs:return False
        with self.db() as conn:
            row=conn.execute('SELECT r.request_digest,r.policy,m.state,m.content FROM hermes_reservations r JOIN model_calls m ON r.fingerprint=m.fingerprint WHERE r.owner=? AND r.task=? AND r.turn=?',(owner,task,turn)).fetchone()
        return bool(row and row['state']=='unknown' and row['request_digest']==digest(request) and row['policy']==encoded(self.policy) and row['content'] and transport_reset(json.loads(row['content'])))

    def settle(self, fingerprint, response, request, input_bound):
        try:
            usage = {key: response['usage'][key] for key in ('prompt_tokens','completion_tokens','total_tokens')}
            if any(type(x) is not int or x < 0 for x in usage.values()):
                raise ValueError('usage_invalid')
            if usage['total_tokens'] != usage['prompt_tokens']+usage['completion_tokens'] or usage['prompt_tokens'] > MAX_PROVIDER_CONTEXT_TOKENS or usage['completion_tokens'] > request['max_tokens']:
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
            if not request['tools'] and calls:raise ValueError('auxiliary_tool_calls')
            ids = set()
            for call in calls:
                # Retain verified Bailian index metadata in provider replay.
                validate_tool_call(call, tool_schemas=request['tools'])
                if call['id'] in ids:
                    raise ValueError('duplicate_tool_call')
                ids.add(call['id'])
            if len(encoded(message).encode()) > MAX_PROVIDER_WIRE_BYTES:
                raise ValueError('response_size')
            p = self.policy
            receipt = {'status':'succeeded', 'provider_request_id':response['id'], 'usage':usage,
                       'cost_microcny':usage['prompt_tokens']*p['input_microcny']+usage['completion_tokens']*p['output_microcny'] if p['input_microcny'] is not None else None,
                       'price_version':p['price_version'], 'model':p['model'], 'message':message,
                       'cost_basis':'configured_public_rate_estimate_not_account_invoice' if p['input_microcny'] is not None else 'amount_unknown_no_cny_invoice_or_fx',
                       'enable_thinking':request['enable_thinking'],'reasoning_effort':request.get('reasoning_effort')}
            receipt['finish_reason']=finish_reason
            validation=response.get('model_validation')
            if isinstance(validation,dict):
                if validation.get('status') not in ('accepted_no_effort_echo','provider_metadata_confirmed') or validation.get('requested_effort')!=request.get('reasoning_effort') or validation.get('response_model')!=p['model'] or validation.get('forwarded_verified') is not True:
                    raise ValueError('model_validation_invalid')
                receipt['model_validation']=deepcopy(validation)
            receipt.update(transport_trace(response))
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
                    usage['prompt_tokens']<=MAX_PROVIDER_CONTEXT_TOKENS and usage['completion_tokens']<=request['max_tokens']):
                receipt=dict(diagnostic,status='invalid_response',usage=usage,
                             cost_microcny=usage['prompt_tokens']*self.policy['input_microcny']+usage['completion_tokens']*self.policy['output_microcny'] if self.policy['input_microcny'] is not None else None,
                             price_version=self.policy['price_version'],model=self.policy['model'],
                             cost_basis='configured_public_rate_estimate_not_account_invoice' if self.policy['input_microcny'] is not None else 'amount_unknown_no_cny_invoice_or_fx',
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
    def __init__(self, scope, budget, provider_slot, provider, input_bound, daily_limit, preflight=None,transport_retries=0,retry_wait=None):
        self.scope, self.budget, self.slot = scope, budget, provider_slot
        self.provider, self.input_bound, self.daily_limit = provider, input_bound, daily_limit
        self.preflight = preflight
        if type(transport_retries) is not int or transport_retries not in (0,2):raise ValueError('transport_retry_policy')
        if transport_retries and (budget.policy['model']!='deepseek-flash' or budget.policy['id']!='no-pilot-quotas-deepseek-direct-stream-tokens-only-v2' or not budget.allow_unknown_costs):raise ValueError('transport_retry_scope')
        self.transport_retries=transport_retries
        self.retry_wait=retry_wait or self._retry_wait

    def _retry_wait(self,seconds,check):
        import time
        until=time.monotonic()+seconds
        while True:
            check();remaining=until-time.monotonic()
            if remaining<=0:return
            time.sleep(min(0.2,remaining))

    def call(self, owner, task_id, lease, turn, body):
        self.scope.context(owner, task_id, lease)
        if type(turn) is not int or turn<0:raise ValueError('turn_invalid')
        # Logical turn identity remains in hermes_turns. Existing reservation slots encode
        # each physical attempt as turn*3+ordinal, with no schema migration or old-row rewrite.
        base_turn=turn*(self.transport_retries+1)
        request = self.budget.restore_tool_indexes(owner,task_id,base_turn,request_body(body,self.budget.policy['model'], tool_schemas=task_schemas(getattr(self.scope, 'book', None)), native_chat=native_scope(self.scope)))
        if len(encoded(request).encode())>MAX_PROVIDER_WIRE_BYTES:raise ValueError('provider_payload_too_large')
        require_context_window(request)  # Recheck after trusted replay metadata is restored.
        if self.preflight is not None:self.preflight(request)  # Final vendor wire before any reservation/network.
        bound = self.input_bound(request)  # Reservation estimate only; actual vendor usage is authoritative.
        with self.slot() as acquired:
            if not acquired:
                raise ValueError('model_busy')
            self.scope.context(owner, task_id, lease)
            limit = self.daily_limit()
            if type(limit) is not int or limit < 0:
                raise ValueError('daily_limit_invalid')
            # Existing global call-count limit is checked atomically for new calls only.
            for attempt in range(self.transport_retries+1):
                self.scope.context(owner,task_id,lease)
                if attempt:self.retry_wait(2**attempt,lambda:self.scope.context(owner,task_id,lease))
                physical_turn=base_turn+attempt
                try:fingerprint,prior=self.budget.reserve(owner,task_id,physical_turn,request,bound,limit)
                except ValueError as error:
                    if str(error)=='unknown_previous_attempt' and self.transport_retries and self.budget.prior_transport_reset(owner,task_id,physical_turn,request):continue
                    raise
                if prior is not None:return prior
                try:
                    self.scope.context(owner,task_id,lease)
                    response = self.provider(request)
                except Exception as error:
                    diagnostic=safe_diagnostic(getattr(error,'response',None),request,str(error))
                    self.budget.hold(fingerprint,diagnostic)
                    if attempt<self.transport_retries and transport_reset(diagnostic):continue
                    raise ValueError('provider_transport_recovery_exhausted' if self.transport_retries and transport_reset(diagnostic) else 'provider_outcome_unknown') from None
                receipt = self.budget.settle(fingerprint,response,request,bound)
                # Each real request keeps its own record, including unknown cost after reset.
                self.scope.context(owner,task_id,lease)
                return receipt
            raise ValueError('provider_transport_recovery_exhausted')

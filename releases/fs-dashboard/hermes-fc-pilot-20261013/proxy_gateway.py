"""In-process candidate adapters. Inject existing DB/lock/provider; no sockets or keys."""
from copy import deepcopy
import json
import re
from pilot import digest, encoded, TOOLS, SHANGHAI
from runs_contract import WIRE_TOOLS, SEMANTIC_TOOLS


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
    if type(body['max_tokens']) is not int or not 1 <= body['max_tokens'] <= 6000:
        raise ValueError('output_limit')
    messages = body['messages']
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
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
    if len(serialized.encode()) > 96000 or re.search(r'Bearer\s|sk-[A-Za-z0-9]|Cookie\s*[:=]|password\s*[:=]', serialized, re.I):
        raise ValueError('context_rejected')
    result={'model': model, 'messages': deepcopy(messages), 'max_tokens': body['max_tokens'],
            'tools': schemas(), 'tool_choice': 'auto', 'stream': False, 'enable_thinking': effort is not None}
    if effort is not None:result['reasoning_effort']=effort
    return result


def validate_tool_call(call):
    if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function':
        raise ValueError('tool_call_fields')
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


class UnifiedBudget:
    """Use existing daily.db() and model_calls. New table is reservation metadata only.

    Constructor is an explicit migration; instantiate ONLY against an isolated fixture
    until shared DB migration is reviewed. No default production path is present.
    """
    def __init__(self, db, policy, clock):
        self.db, self.clock = db, clock
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
            task_cost = task_tokens = day_cost = turns = 0
            for row in rows:
                # An unknown request anywhere in the pilot holds further pilot spending.
                if row['state'] != 'succeeded':
                    raise ValueError('pilot_usage_hold')
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
            message = deepcopy(choices[0]['message'])
            if not isinstance(message, dict):
                raise ValueError('response_message_invalid')
            # Providers may include an empty reasoning slot even with thinking off.
            if message.get('reasoning_content', None) is None or message.get('reasoning_content')=='':
                message.pop('reasoning_content', None)
            allowed={'role','content','tool_calls'} | ({'reasoning_content'} if request['enable_thinking'] else set())
            if not isinstance(message, dict) or message.get('role') != 'assistant' or set(message)-allowed:
                raise ValueError('response_message_invalid')
            if 'reasoning_content' in message and not isinstance(message['reasoning_content'],str):raise ValueError('response_reasoning_invalid')
            if message.get('content') is not None and not isinstance(message['content'], str):
                raise ValueError('response_content_invalid')
            calls = message.get('tool_calls', [])
            if not isinstance(calls, list) or len(calls) > 5:
                raise ValueError('response_tools_limit')
            ids = set()
            for call in calls:
                validate_tool_call(call)
                if call['id'] in ids:
                    raise ValueError('duplicate_tool_call')
                ids.add(call['id'])
            if len(encoded(message).encode()) > 96000:
                raise ValueError('response_size')
            p = self.policy
            receipt = {'status':'succeeded', 'provider_request_id':response['id'], 'usage':usage,
                       'cost_microcny':usage['prompt_tokens']*p['input_microcny']+usage['completion_tokens']*p['output_microcny'],
                       'price_version':p['price_version'], 'model':p['model'], 'message':message,
                       'cost_basis':'configured_public_rate_estimate_not_account_invoice',
                       'enable_thinking':request['enable_thinking'],'reasoning_effort':request.get('reasoning_effort')}
            reasoning_tokens=response.get('usage',{}).get('completion_tokens_details',{}).get('reasoning_tokens') if isinstance(response.get('usage',{}).get('completion_tokens_details'),dict) else None
            if reasoning_tokens is not None:
                if type(reasoning_tokens)is not int or not 0<=reasoning_tokens<=usage['completion_tokens']:raise ValueError('reasoning_usage_invalid')
                receipt['reasoning_tokens']=reasoning_tokens  # Already included in completion, never double charged.
        except (ValueError, TypeError, KeyError):
            self.hold(fingerprint)
            raise ValueError('unverified_provider_result') from None
        with self.db() as conn:
            updated = conn.execute("UPDATE model_calls SET state='succeeded',content=? WHERE fingerprint=? AND state='started'",
                                   (encoded(receipt),fingerprint))
            if updated.rowcount != 1:
                raise ValueError('settlement_state')
        return deepcopy(receipt)

    def hold(self, fingerprint):
        with self.db() as conn:
            conn.execute("UPDATE model_calls SET state='unknown' WHERE fingerprint=? AND state='started'", (fingerprint,))


class ModelGateway:
    def __init__(self, scope, budget, provider_slot, provider, input_bound, daily_limit):
        self.scope, self.budget, self.slot = scope, budget, provider_slot
        self.provider, self.input_bound, self.daily_limit = provider, input_bound, daily_limit

    def call(self, owner, task_id, lease, turn, body):
        self.scope.context(owner, task_id, lease)
        request = request_body(body, self.budget.policy['model'])
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
            except Exception:
                self.budget.hold(fingerprint)
                raise ValueError('provider_outcome_unknown') from None
            receipt = self.budget.settle(fingerprint,response,request,bound)
            # Paid work is accounted even when cancellation arrives during the request.
            self.scope.context(owner,task_id,lease)
            return receipt

"""Bounded messages on an authenticated stream; no URL, shell or identity forwarding."""
from datetime import datetime, timezone
import json
import re

from .contracts import CONTEXT, build_job, encoded, instant

MAX_MESSAGE = 131072


def utc():
    return datetime.now(timezone.utc)


def read_message(stream):
    raw = stream.readline(MAX_MESSAGE + 1)
    if not raw:
        raise EOFError('peer_disconnected')
    if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
        raise ValueError('message_limit_invalid')
    try:
        def invalid_constant(_):
            raise ValueError('message_number_invalid')
        value = json.loads(raw.decode('utf-8'), parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('message_invalid') from None
    if not isinstance(value, dict):
        raise ValueError('message_invalid')
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, (dict, list)):
            if depth > 16:
                raise ValueError('message_nesting_invalid')
            pending.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return value


def write_message(stream, value):
    raw = (encoded(value) + '\n').encode('utf-8')
    if len(raw) > MAX_MESSAGE:
        raise ValueError('message_limit_invalid')
    stream.write(raw)
    stream.flush()


def validate_task(task, identity, versions, now):
    extra = {'attempts', 'lease_epoch', 'request_budget_reserved', 'node_id', 'node_boot_id', 'attempt_id',
             'lease_started_at', 'clock_margin_seconds', 'lease_expires_at', 'retry_not_before'}
    try:
        base = build_job(dict(run_id=task['parent_run_id'], created_at=task['created_at']), task['source_id'],
                         {key: task[key] for key in CONTEXT}, task['deadline_at'])
        if set(task) - set(base) - extra or any(task[key] != value for key, value in base.items()):
            raise ValueError('task_contract_invalid')
        if (task['node_id'] != identity['node_id'] or task['node_boot_id'] != identity['node_boot_id']
                or versions.get(task['source_id']) != task['adapter_version']
                or not 0 < (instant(task['deadline_at']) - instant(now)).total_seconds() <= 900
                or not 0 < task['total_request_budget'] <= 8 or not 0 < task['total_attempt_limit'] <= 3
                or not 0 <= task['clock_margin_seconds'] <= 5
                or (instant(task['lease_started_at']) - instant(now)).total_seconds() > task['clock_margin_seconds']
                or instant(now) >= instant(task['lease_expires_at'])
                or instant(task['lease_expires_at']) > instant(task['deadline_at'])):
            raise ValueError('task_scope_invalid')
    except (KeyError, TypeError, AttributeError):
        raise ValueError('task_contract_invalid') from None
    return task


def handle_callback(coordinator, identity, task, message, clock=utc):
    ident = message.get('id')
    reply = dict(kind='reply', id=ident)
    try:
        if set(message) != {'kind', 'id', 'method', 'params'} or message['kind'] != 'call' or type(ident) is not int:
            raise ValueError('callback_invalid')
        method, params = message['method'], message['params']
        if not isinstance(params, dict):
            raise ValueError('callback_invalid')
        fields = {
            'renew_lease': {'job_id', 'attempt_id', 'lease_epoch'},
            'reserve_request': {'job_id', 'lease_epoch', 'request_group'},
            'complete_request': {'job_id', 'lease_epoch', 'permit_id'},
            'submit_observation': {'observation'}}
        if method not in fields or set(params) != fields[method]:
            raise ValueError('method_not_allowed')
        if task is None and method != 'submit_observation':
            raise ValueError('resend_only')
        if method != 'submit_observation' and params['job_id'] != task['job_id']:
            raise ValueError('callback_job_invalid')
        now = clock()
        if method == 'renew_lease':
            result = coordinator.renew_lease(identity, params['job_id'], params['attempt_id'], params['lease_epoch'], now)
        elif method == 'reserve_request':
            result = coordinator.reserve_request(identity, params['job_id'], params['lease_epoch'], params['request_group'], now)
        elif method == 'complete_request':
            result = coordinator.complete_request(identity, params['job_id'], params['lease_epoch'], params['permit_id'], now)
        else:
            result = coordinator.submit_observation(identity, params['observation'], now)
        reply['result'] = result
    except (ValueError, KeyError, TypeError) as exc:
        reason = str(exc)
        reply['error'] = reason if re.fullmatch(r'[a-z][a-z0-9_]{0,119}', reason) else 'callback_rejected'
    return reply


class CallbackEndpoint:
    def __init__(self, task, identity, reader, writer):
        self.task, self.identity, self.reader, self.writer = task, identity, reader, writer
        self.sequence, self.claimed = 0, False

    def call(self, method, params):
        self.sequence += 1
        if self.sequence > 64:
            raise ValueError('callback_limit')
        write_message(self.writer, dict(kind='call', id=self.sequence, method=method, params=params))
        response = read_message(self.reader)
        if (response.get('kind') != 'reply' or response.get('id') != self.sequence
                or set(response) not in ({'kind', 'id', 'result'}, {'kind', 'id', 'error'})):
            raise ValueError('callback_reply_invalid')
        if 'error' in response:
            from .adapters import SourceUnavailable
            allowed = {'request_budget_unavailable', 'lease_invalid', 'identity_invalid', 'request_budget_invalid',
                       'permit_invalid', 'observation_conflict', 'observation_schema_invalid', 'collection_routing_changed'}
            reason = response['error'] if response['error'] in allowed else 'coordinator_rejected'
            raise SourceUnavailable(reason)
        return response['result']

    def claim_job(self, identity, capabilities, now):
        if identity != self.identity:
            raise ValueError('identity_invalid')
        if self.task is None:
            return None
        if self.task['source_id'] not in capabilities:
            raise ValueError('capability_invalid')
        if self.claimed:
            return None
        self.claimed = True
        return self.task

    def renew_lease(self, identity, job_id, attempt_id, lease_epoch, now):
        return self.call('renew_lease', dict(job_id=job_id, attempt_id=attempt_id, lease_epoch=lease_epoch))

    def reserve_request(self, identity, job_id, lease_epoch, request_group, now):
        return self.call('reserve_request', dict(job_id=job_id, lease_epoch=lease_epoch, request_group=request_group))

    def complete_request(self, identity, job_id, lease_epoch, permit_id, now):
        return self.call('complete_request', dict(job_id=job_id, lease_epoch=lease_epoch, permit_id=permit_id))

    def submit_observation(self, identity, observation, now):
        return self.call('submit_observation', dict(observation=observation))


def serve_task(task, identity, adapters, versions, spool, fetch, reader, writer, clock=utc):
    from .worker import Worker
    validate_task(task, identity, versions, clock())
    endpoint = CallbackEndpoint(task, identity, reader, writer)
    receipt = Worker(endpoint, identity, adapters, spool, fetch, clock=clock).run_once()
    write_message(writer, dict(kind='done', result=receipt))


def serve_replay(identity, spool, reader, writer, clock=utc):
    from .worker import Worker
    endpoint = CallbackEndpoint(None, identity, reader, writer)
    def no_fetch(*_):
        raise ValueError('resend_only')
    receipt = Worker(endpoint, identity, {}, spool, no_fetch, clock=clock).run_once()
    write_message(writer, dict(kind='done', result=receipt))

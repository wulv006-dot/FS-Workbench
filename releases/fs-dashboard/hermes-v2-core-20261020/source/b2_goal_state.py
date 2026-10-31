"""Host-held goal state and short-task proposals; no I/O or execution.

The host supplies identity/scope authorization on EVERY call and atomically saves
the returned state against expected_revision BEFORE dispatching its request_id.
A pure transition is not a database CAS, task reservation or execution receipt.
Evidence locators still require A's authorization when resolved. No scheduler,
customer ledger, provider client or automatic goal-achievement inference lives
here. Ordinary questions do not create goals.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from b1_model_routing import handoff
from b2_customer_followup import moment

VERSION = 'b2_goal_state_v1'
PENDING = {'prepared', 'queued', 'running', 'provider_returned', 'unknown'}
TERMINAL = {'completed', 'failed', 'cancelled'}
STATE_KEYS = {'version', 'revision', 'goal_id', 'owner', 'scope_ref', 'objective',
              'constraints', 'status', 'next_check_at', 'updated_at', 'work',
              'evidence', 'completed_actions'}
WORK_KEYS = {'request_id', 'fact_version', 'checkpoint_at', 'status', 'receipt_ref',
             'receipt_digest'}


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('nonempty_reference_required')
    return value


def _at(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return moment(value).astimezone(timezone.utc)


def _stamp(value):
    return _at(value).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':'))


def _validate(state):
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise ValueError('goal_state_contract')
    if (state['version'] != VERSION or type(state['revision']) is not int
            or state['revision'] < 1 or state['status'] not in {'active', 'paused', 'stopped'}):
        raise ValueError('goal_state_version_or_status')
    for field in ('goal_id', 'owner', 'scope_ref', 'objective'):
        _text(state[field])
    _at(state['next_check_at'])
    _at(state['updated_at'])
    # Reuse the existing bounded, exact-field evidence contract.
    handoff(task_id=state['goal_id'], revision=state['revision'],
            goal=state['objective'], constraints=state['constraints'],
            evidence=state['evidence'], completed_actions=state['completed_actions'],
            next_step='host-controlled continuation')
    for ref in state['evidence']:
        if _at(ref['as_of']) > _at(state['updated_at']):
            raise ValueError('future_evidence')
    work = state['work']
    if work is not None:
        if not isinstance(work, dict) or set(work) != WORK_KEYS:
            raise ValueError('work_contract')
        _text(work['request_id'])
        _text(work['fact_version'])
        if work['checkpoint_at'] is not None:
            if _at(work['checkpoint_at']) > _at(state['updated_at']):
                raise ValueError('future_consumed_checkpoint')
        if work['status'] not in PENDING | TERMINAL:
            raise ValueError('work_status')
        if work['status'] == 'prepared':
            if work['receipt_ref'] is not None or work['receipt_digest'] is not None:
                raise ValueError('prepared_is_not_a_receipt')
        else:
            _text(work['receipt_ref'])
            digest = work['receipt_digest']
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in '0123456789abcdef' for c in digest)):
                raise ValueError('receipt_digest')
    if len(_json(state).encode('utf-8')) > 32768:
        raise ValueError('goal_state_too_large')


def _guard(state, expected_revision, now, authorize):
    _validate(state)
    if not callable(authorize) or authorize(state['owner'], state['scope_ref']) is not True:
        # No cached handoff/private evidence is returned after revocation.
        raise PermissionError('goal_scope_unavailable')
    if type(expected_revision) is not int or expected_revision != state['revision']:
        raise ValueError('goal_revision_conflict')
    if _at(now) < _at(state['updated_at']):
        raise ValueError('observation_clock_regressed')


def _result(before, state, action, changed, now, continuation=None):
    if changed:
        state['revision'] += 1
        state['updated_at'] = _stamp(now)
    _validate(state)
    return {'expected_revision': before['revision'], 'state': state, 'action': action,
            'request_id': state['work']['request_id'] if state['work'] else None,
            'handoff': continuation, 'model_call_performed': False,
            'business_write_performed': False}


def create_goal(*, goal_id, owner, scope_ref, objective, constraints, recheck_at,
                now, explicit_goal, authorize):
    """Only an explicit host-confirmed long-term goal creates a state object.

scope_ref is a nonsecret locator/version, never a grant supplied by a model.
The host persists this object using its existing create-if-absent mechanism.
"""
    if explicit_goal is not True:
        raise ValueError('explicit_goal_required')
    if not callable(authorize) or authorize(_text(owner), _text(scope_ref)) is not True:
        raise PermissionError('goal_scope_unavailable')
    state = dict(version=VERSION, revision=1, goal_id=goal_id, owner=owner,
                 scope_ref=scope_ref, objective=objective, constraints=deepcopy(constraints),
                 status='active', next_check_at=_stamp(recheck_at), updated_at=_stamp(now),
                 work=None, evidence=[], completed_actions=[])
    _validate(state)
    return state


def plan_step(state, *, expected_revision, now, fact_version, request_id, authorize):
    """Propose at most one short task on changed facts or an explicit due point.

Persist the proposed state via host CAS before dispatch. A replay of prepared
state reconciles the original ID; it never assumes an absent receipt means no
execution. The host's original task ledger owns cross-history ID uniqueness.
fact_version must be the trusted scope/identity/policy/data version composite,
not the current clock, a model claim or an unscoped digest.
"""
    _guard(state, expected_revision, now, authorize)
    new = deepcopy(state)
    work = state['work']
    if state['status'] != 'active':
        # Stopping a goal prevents proposals; it does not cancel a real task.
        return _result(state, new, state['status'], False, now)
    if work and work['status'] in PENDING:
        return _result(state, new, 'reconcile_original', False, now)
    _text(fact_version)
    _text(request_id)
    changed_facts = work is None or fact_version != work['fact_version']
    due = _at(now) >= _at(state['next_check_at'])
    unused_checkpoint = work is None or work['checkpoint_at'] is None or (
        _at(work['checkpoint_at']) != _at(state['next_check_at']))
    if not changed_facts and not (due and unused_checkpoint):
        return _result(state, new, 'wait', False, now)
    if work and request_id == work['request_id']:
        raise ValueError('new_trigger_requires_new_request_id')
    new['work'] = dict(request_id=request_id, fact_version=fact_version,
                       checkpoint_at=state['next_check_at'] if due else None,
                       status='prepared', receipt_ref=None, receipt_digest=None)
    continuation = handoff(task_id=request_id, revision=state['revision'] + 1,
                           goal=state['objective'], constraints=state['constraints'],
                           evidence=state['evidence'],
                           completed_actions=state['completed_actions'],
                           next_step='Read authorized frozen evidence; preserve missing fields, '
                                     'compare changes and the explicit checkpoint; include '
                                     'no-intervention. A task result does not achieve the goal.')
    return _result(state, new, 'dispatch_after_cas', True, now, continuation)


def record_receipt(state, *, expected_revision, request_id, status, receipt_ref,
                   now, authorize, evidence=None, completed_actions=None):
    """Record a host-verified ORIGINAL task receipt, not a model's success text.

UNKNOWN can resolve only against that request. A provider response stays pending
until the actual task receipt is terminal. Terminal receipt replays are exact
and idempotent; conflicting/late receipts cannot overwrite a terminal or newer
task. Evidence is the existing B2/B1 reference shape, with its original cutoff
and missing fields, never the raw investigation result or customer rows.
"""
    _guard(state, expected_revision, now, authorize)
    work = state['work']
    if not work or request_id != work['request_id']:
        raise ValueError('original_task_receipt_required')
    if status not in (PENDING - {'prepared'}) | TERMINAL:
        raise ValueError('receipt_status')
    _text(receipt_ref)
    if status != 'completed' and (evidence is not None or completed_actions is not None):
        raise ValueError('only_completed_task_updates_handoff')
    payload = dict(status=status, receipt_ref=receipt_ref, evidence=evidence,
                   completed_actions=completed_actions)
    digest = hashlib.sha256(_json(payload).encode('utf-8')).hexdigest()
    if digest == work['receipt_digest']:
        return _result(state, deepcopy(state), 'receipt_already_recorded', False, now)
    if work['status'] in TERMINAL:
        raise ValueError('terminal_receipt_conflict')
    if work['status'] in {'running', 'provider_returned'} and status == 'queued':
        raise ValueError('receipt_state_regressed')
    new = deepcopy(state)
    new['work'].update(status=status, receipt_ref=receipt_ref, receipt_digest=digest)
    if evidence is not None:
        new['evidence'] = deepcopy(evidence)
    if completed_actions is not None:
        new['completed_actions'] = deepcopy(completed_actions)
    return _result(state, new, 'recorded', True, now)


def configure_goal(state, *, expected_revision, now, authorize, status=None, recheck_at=None):
    """Explicit host instruction only; no autonomous cadence or business write.

A stopped goal stays stopped. Pause/stop retains any outstanding original task
for reconciliation and makes no claim that its provider or billing stopped.
"""
    _guard(state, expected_revision, now, authorize)
    if status is not None and status not in {'active', 'paused', 'stopped'}:
        raise ValueError('goal_status')
    if state['status'] == 'stopped' and status not in {None, 'stopped'}:
        raise ValueError('stopped_goal_cannot_resume')
    new = deepcopy(state)
    if status is not None:
        new['status'] = status
    if recheck_at is not None:
        new['next_check_at'] = _stamp(recheck_at)
    return _result(state, new, 'configured', new != state, now)

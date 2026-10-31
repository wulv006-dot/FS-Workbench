"""Injected local goal host bridge; no runtime wiring, model or source client.

A owns ConversationGoals, its transactions and admission lock. The injected
dispatcher owns an INDEPENDENT original task ledger; submit only reserves/enqueues
and must atomically deduplicate the full binding+handoff fingerprint. It must not
write the conversation DB, wait for a provider, or perform business actions while
admission is held. verify_receipt must check that ledger, not model assertions.

A committed/replayed/prepared state is not permission to replay a submission.
Only this call's fresh CAS winner + verified not_found + live admission can submit.
Any uncertain boundary retains the original ID, including an admission exit error.
"""
from copy import deepcopy
import hashlib

from b2_goal_state import (PENDING, _json, _text, _validate, configure_goal,
                           create_goal, plan_step, record_receipt)

TRANSPORT = (OSError, TimeoutError, ConnectionError)
BINDING_KEYS = {'owner', 'cid', 'goal_id', 'scope_ref', 'request_id', 'intent_sha256'}
RECEIPT_KEYS = {'binding', 'status', 'receipt_ref'}
RECEIPT_STATUS = {'not_found', 'queued', 'running', 'provider_returned', 'unknown',
                  'completed', 'failed', 'cancelled'}


class GoalHost:
    def __init__(self, goals, *, owner, cid, authorize, dispatcher, verify_receipt):
        self.owner, self.cid = _text(owner), _text(cid)
        if goals.owner != owner or goals.cid != cid:
            raise ValueError('goal_host_store_identity')
        if not all(callable(f) for f in (authorize, verify_receipt, dispatcher.lookup,
                                        dispatcher.submit, goals.admission)):
            raise ValueError('goal_host_callbacks_required')
        self.goals, self.authorize = goals, authorize
        self.dispatcher, self.verify_receipt = dispatcher, verify_receipt

    def _check(self, goal_id, state):
        _validate(state)
        if state['goal_id'] != goal_id or state['owner'] != self.owner:
            raise PermissionError('goal_host_identity')
        if self.authorize(self.owner, state['scope_ref']) is not True:
            raise PermissionError('goal_scope_unavailable')
        return state

    def _load(self, goal_id):
        state = self.goals.load_goal(goal_id)
        if state is None:
            raise LookupError('goal_not_found')
        return self._check(goal_id, deepcopy(state))

    def _binding(self, state):
        work = state['work']
        if work is None:
            raise ValueError('original_work_required')
        binding = dict(owner=self.owner, cid=self.cid, goal_id=state['goal_id'],
                       scope_ref=state['scope_ref'], request_id=work['request_id'])
        # Stable logical intent across progress receipts/evidence updates. The
        # task ledger ALSO fingerprints the complete submitted handoff; this
        # digest alone is neither an access grant nor that full fingerprint.
        logical = dict(binding, objective=state['objective'], constraints=state['constraints'],
                       fact_version=work['fact_version'], checkpoint_at=work['checkpoint_at'])
        binding['intent_sha256'] = hashlib.sha256(_json(logical).encode('utf-8')).hexdigest()
        return binding

    def _result(self, goal_id, state, action, **extra):
        self._check(goal_id, state)  # Recheck after injected I/O before returning cached data.
        return dict(action=action, goal_id=goal_id,
                    request_id=state['work']['request_id'] if state['work'] else None,
                    state=deepcopy(state), **extra)

    def _cas(self, state, expected_revision, mutation_id):
        self._check(state['goal_id'], state)
        try:
            receipt = self.goals.cas_goal(state['goal_id'], expected_revision=expected_revision,
                                           mutation_id=mutation_id, state=deepcopy(state))
        except PermissionError:
            raise
        except TRANSPORT:
            return None  # Could have committed: never infer rollback or dispatch.
        if (not isinstance(receipt, dict) or receipt.get('applied') is not True
                or type(receipt.get('replayed')) is not bool
                or receipt.get('goal_id') != state['goal_id']
                or type(receipt.get('revision')) is not int
                or receipt['revision'] != state['revision']
                or receipt.get('state') != state or receipt.get('mutation_id') != mutation_id):
            raise ValueError('goal_cas_receipt_contract')
        self._check(state['goal_id'], state)
        return receipt

    def create(self, goal_id, *, mutation_id, scope_ref, objective, constraints,
               recheck_at, now, explicit_goal):
        state = create_goal(goal_id=goal_id, owner=self.owner, scope_ref=scope_ref,
                            objective=objective, constraints=constraints, recheck_at=recheck_at,
                            now=now, explicit_goal=explicit_goal, authorize=self.authorize)
        receipt = self._cas(state, 0, mutation_id)
        if receipt is None:
            return dict(action='reconcile_storage', goal_id=goal_id, mutation_id=mutation_id)
        return self._result(goal_id, self._load(goal_id), 'created', replayed=receipt['replayed'])

    def configure(self, goal_id, *, mutation_id, now, status=None, recheck_at=None):
        state = self._load(goal_id)
        proposal = configure_goal(state, expected_revision=state['revision'], now=now,
                                  authorize=self.authorize, status=status, recheck_at=recheck_at)
        if proposal['state'] == state:
            return self._result(goal_id, state, 'unchanged')
        saved = self._cas(proposal['state'], proposal['expected_revision'], mutation_id)
        if saved is None:
            return dict(action='reconcile_storage', goal_id=goal_id, mutation_id=mutation_id)
        return self._result(goal_id, self._load(goal_id), 'configured', replayed=saved['replayed'])

    def _receipt(self, state, receipt):
        self._check(state['goal_id'], state)
        expected = self._binding(state)
        if (not isinstance(receipt, dict) or not RECEIPT_KEYS <= set(receipt)
                or set(receipt) - RECEIPT_KEYS - {'evidence', 'completed_actions'}
                or not isinstance(receipt['binding'], dict)
                or set(receipt['binding']) != BINDING_KEYS or receipt['binding'] != expected
                or receipt['status'] not in RECEIPT_STATUS):
            raise ValueError('task_receipt_binding')
        if receipt['status'] != 'completed' and set(receipt) - RECEIPT_KEYS:
            raise ValueError('nonterminal_receipt_payload')
        _text(receipt['receipt_ref'])
        if self.verify_receipt(deepcopy(receipt), deepcopy(expected)) is not True:
            raise PermissionError('task_receipt_unverified')
        self._check(state['goal_id'], state)
        return deepcopy(receipt)

    def _save_receipt(self, state, receipt, now):
        receipt = self._receipt(state, receipt)
        if receipt['status'] == 'not_found':
            return self._result(state['goal_id'], self._load(state['goal_id']),
                                'reconcile_original', lookup_status='not_found')
        proposal = record_receipt(state, expected_revision=state['revision'],
            request_id=state['work']['request_id'], status=receipt['status'],
            receipt_ref=receipt['receipt_ref'], evidence=receipt.get('evidence'),
            completed_actions=receipt.get('completed_actions'), now=now, authorize=self.authorize)
        if proposal['state'] == state:
            return self._result(state['goal_id'], self._load(state['goal_id']),
                                'receipt_already_recorded')
        # A receipt can legitimately recur after UNKNOWN at a later revision.
        # Identify the CAS operation, not just the external receipt; retries of
        # the same proposal still produce exactly the same mutation identity.
        operation = dict(expected_revision=proposal['expected_revision'],
                         state=proposal['state'], receipt=receipt)
        mutation = 'goal_receipt_' + hashlib.sha256(_json(operation).encode('utf-8')).hexdigest()
        saved = self._cas(proposal['state'], proposal['expected_revision'], mutation)
        if saved is None:
            return dict(action='reconcile_storage', goal_id=state['goal_id'],
                        request_id=state['work']['request_id'], mutation_id=mutation)
        return self._result(state['goal_id'], self._load(state['goal_id']),
                            'receipt_recorded', replayed=saved['replayed'])

    def observe(self, goal_id, *, receipt, now):
        """Host-verified push for the original task; allowed even after goal stop.

This records execution truth, without reading sources, making a new proposal or
claiming that pause/stop cancelled a provider. Old task receipts fail binding.
"""
        return self._save_receipt(self._load(goal_id), receipt, now)

    def step(self, goal_id, *, mutation_id, request_id, fact_version, now,
             evidence=None, expected_revision=None):
        """One non-looping continuation attempt. No automatic retries anywhere."""
        state = self._load(goal_id)
        if expected_revision is not None and (type(expected_revision) is not int
                                               or expected_revision != state['revision']):
            raise ValueError('goal_revision_conflict')
        proposal = plan_step(state, expected_revision=state['revision'], now=now,
                             fact_version=fact_version, request_id=request_id,
                             authorize=self.authorize, evidence=evidence)
        if proposal['action'] not in {'dispatch_after_cas', 'reconcile_original'}:
            return self._result(goal_id, state, proposal['action'])
        fresh = False
        if proposal['action'] == 'dispatch_after_cas':
            saved = self._cas(proposal['state'], proposal['expected_revision'], mutation_id)
            if saved is None:
                return dict(action='reconcile_storage', goal_id=goal_id,
                            request_id=request_id, mutation_id=mutation_id)
            fresh = not saved['replayed']
            state = self._load(goal_id)
            if state != proposal['state']:
                # Someone paused/stopped or changed revision after our CAS.
                return self._result(goal_id, state, 'reconcile_original')
        if state['status'] != 'active' or state['work']['status'] not in PENDING:
            return self._result(goal_id, state, 'reconcile_original')
        binding = self._binding(state)
        self._check(goal_id, state)
        try:
            found = self.dispatcher.lookup(binding=deepcopy(binding))
        except PermissionError:
            raise
        except TRANSPORT:
            return self._result(goal_id, self._load(goal_id), 'reconcile_original',
                                lookup_status='unknown')
        found = self._receipt(state, found)  # not_found ALSO requires ledger verification.
        if found['status'] != 'not_found' or not fresh:
            return self._save_receipt(state, found, now)
        try:
            with self.goals.admission(goal_id, expected_revision=state['revision'],
                                      request_id=state['work']['request_id']) as admitted:
                self._check(goal_id, admitted)
                if admitted != state:
                    raise ValueError('goal_admission_changed')
                receipt = self.dispatcher.submit(binding=deepcopy(binding),
                                                 handoff=deepcopy(proposal['handoff']))
            # Outside the conversation transaction: avoid nested same-DB writes.
        except PermissionError:
            raise
        except TRANSPORT:
            return self._result(goal_id, self._load(goal_id), 'reconcile_original',
                                lookup_status='unknown')
        return self._save_receipt(state, receipt, now)

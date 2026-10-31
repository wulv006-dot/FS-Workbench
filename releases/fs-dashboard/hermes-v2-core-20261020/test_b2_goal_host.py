"""Real A SQLite + B host, synthetic independent task-ledger callbacks only."""
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / 'source'),
               str(HERE.parent / 'hermes-conversation-20261018/source')]
from conversation_store import ConversationStore
from conversation_goals import ConversationGoals
from b2_goal_host import GoalHost

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
DUE = NOW + timedelta(days=2)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


class SyntheticTaskLedger:
    """Test-only local ledger, NOT a production TaskStore or worker adapter.

Use a separate real SQLite DB to prove an admission rollback cannot roll back
an already committed reservation. No model/task runtime is constructed.
"""
    def __init__(self, path):
        self.path = path
        self.submits, self.lookups = 0, 0
        self.submit_error = self.lookup_error = None
        self.lookup_hook = None
        self.verified = True
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS synthetic_tasks '
                       '(request_id TEXT PRIMARY KEY, fingerprint TEXT, receipt TEXT)')
            db.commit()

    def _read(self, binding):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT receipt FROM synthetic_tasks WHERE request_id=?',
                             (binding['request_id'],)).fetchone()
        return json.loads(row[0]) if row else dict(binding=deepcopy(binding), status='not_found',
                                                  receipt_ref='lookup:' + binding['request_id'])

    def lookup(self, *, binding):
        self.lookups += 1
        if self.lookup_hook:
            self.lookup_hook()
        if self.lookup_error:
            raise self.lookup_error
        return self._read(binding)

    def submit(self, *, binding, handoff):
        self.submits += 1
        fingerprint = hashlib.sha256(encoded([binding, handoff]).encode()).hexdigest()
        receipt = dict(binding=deepcopy(binding), status='queued',
                       receipt_ref='task-ledger:' + binding['request_id'] + ':queued')
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT fingerprint,receipt FROM synthetic_tasks WHERE request_id=?',
                                 (binding['request_id'],)).fetchone()
                if old and old[0] != fingerprint:
                    raise ValueError('task_intent_conflict')
                if old:
                    receipt = json.loads(old[1])
                else:
                    db.execute('INSERT INTO synthetic_tasks VALUES(?,?,?)',
                               (binding['request_id'], fingerprint, encoded(receipt)))
        if self.submit_error:
            raise self.submit_error
        return receipt

    def verify(self, receipt, binding):
        return self.verified if receipt == self._read(binding) else False

    def change(self, binding, status, **extra):
        receipt = dict(binding=deepcopy(binding), status=status,
                       receipt_ref='task-ledger:' + binding['request_id'] + ':' + status, **extra)
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute('UPDATE synthetic_tasks SET receipt=? WHERE request_id=?',
                           (encoded(receipt), binding['request_id']))
        return receipt


class GoalHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConversationStore(Path(self.temp.name) / 'conversations')
        self.cid = self.store.create('operator')['conversation_id']
        self.allowed = True
        self.goals = ConversationGoals(self.store, 'operator', self.cid, self.authorize)
        self.ledger = SyntheticTaskLedger(Path(self.temp.name) / 'synthetic-tasks.sqlite3')
        self.host = self.new_host()
        self.host.create('goal-1', mutation_id='create-1', scope_ref='project:1327/scope-v1',
            objective='Observe repeat purchases', constraints=['No business actions'],
            recheck_at=DUE, now=NOW, explicit_goal=True)

    def authorize(self, owner, scope):
        return self.allowed if owner == 'operator' and scope == 'project:1327/scope-v1' else False

    def new_host(self):
        goals = ConversationGoals(self.store, 'operator', self.cid, self.authorize)
        return GoalHost(goals, owner='operator', cid=self.cid, authorize=self.authorize,
                        dispatcher=self.ledger, verify_receipt=self.ledger.verify)

    def step(self, host=None, **changes):
        args = dict(mutation_id='prepare-1', request_id='task-request-1',
                    fact_version='synthetic-scope/identity/policy/contract/data-v1', now=NOW)
        args.update(changes)
        return (host or self.host).step('goal-1', **args)

    def state(self):
        return self.goals.load_goal('goal-1')

    def binding(self):
        return self.host._binding(self.state())

    def test_real_sqlite_prepared_then_separate_task_then_receipt_outside_admission(self):
        # The host uses its own bound instance; instrument that same instance.
        active = [False]
        original_admission = self.host.goals.admission
        original_cas = self.host.goals.cas_goal
        original_submit = self.ledger.submit
        @contextmanager
        def admission(*a, **kw):
            with original_admission(*a, **kw) as state:
                active[0] = True
                try:
                    yield state
                finally:
                    active[0] = False
        def cas(*a, **kw):
            self.assertFalse(active[0], 'receipt CAS must not nest on the admission DB')
            return original_cas(*a, **kw)
        def submit(**kw):
            self.assertTrue(active[0])
            self.assertEqual(kw['handoff']['task_id'], 'task-request-1')
            self.assertEqual(kw['handoff']['revision'], 2)
            return original_submit(**kw)
        with patch.object(self.host.goals, 'admission', admission), \
             patch.object(self.host.goals, 'cas_goal', cas), patch.object(self.ledger, 'submit', submit):
            result = self.step()
        self.assertEqual(result['action'], 'receipt_recorded')
        self.assertEqual(result['state']['work']['status'], 'queued')
        self.assertEqual(self.ledger.submits, 1)
        self.assertEqual(self.state()['revision'], 3)

    def test_submit_committed_but_response_lost_reconnect_queries_original_only(self):
        self.ledger.submit_error = TimeoutError('transport details must not be returned')
        result = self.step()
        self.assertEqual(result['action'], 'reconcile_original')
        self.assertEqual(self.state()['work']['status'], 'prepared')
        restarted = self.new_host()
        self.ledger.submit_error = None
        recovered = self.step(restarted, request_id='never-use-new-id', fact_version='v2')
        self.assertEqual(recovered['state']['work']['request_id'], 'task-request-1')
        self.assertEqual(recovered['state']['work']['status'], 'queued')
        self.assertEqual(self.ledger.submits, 1)

    def test_prepared_cas_commit_then_response_loss_not_found_does_not_dispatch(self):
        original = self.host.goals.cas_goal
        def lose(*a, **kw):
            original(*a, **kw)
            raise TimeoutError('CAS committed, reply lost')
        with patch.object(self.host.goals, 'cas_goal', lose):
            result = self.step()
        self.assertEqual(result['action'], 'reconcile_storage')
        self.assertEqual(self.state()['work']['status'], 'prepared')
        recovered = self.step(self.new_host(), request_id='never-replace')
        self.assertEqual(recovered['lookup_status'], 'not_found')
        self.assertEqual(self.ledger.submits, 0)

    def test_receipt_cas_commit_then_reply_loss_keeps_queued_original_no_replay(self):
        original = self.host.goals.cas_goal
        def lose_receipt(*a, **kw):
            result = original(*a, **kw)
            if kw['state']['work']['status'] == 'queued':
                raise TimeoutError('receipt CAS reply lost')
            return result
        with patch.object(self.host.goals, 'cas_goal', lose_receipt):
            result = self.step()
        self.assertEqual(result['action'], 'reconcile_storage')
        self.assertEqual(self.state()['work']['status'], 'queued')
        replay = self.step(self.new_host())
        self.assertEqual(replay['action'], 'receipt_already_recorded')
        self.assertEqual(self.ledger.submits, 1)

    def test_admission_exit_failure_does_not_rollback_independent_reservation(self):
        original = self.host.goals.admission
        @contextmanager
        def fail_exit(*a, **kw):
            with original(*a, **kw) as state:
                yield state
                raise OSError('failure after external reservation')
        with patch.object(self.host.goals, 'admission', fail_exit):
            result = self.step()
        self.assertEqual(result['lookup_status'], 'unknown')
        self.assertEqual(self.state()['work']['status'], 'prepared')
        recovered = self.step(self.new_host())
        self.assertEqual(recovered['state']['work']['status'], 'queued')
        self.assertEqual(self.ledger.submits, 1)

    def test_replayed_cas_receipt_is_not_fresh_dispatch_permission(self):
        original = self.host.goals.cas_goal
        def replay(*a, **kw):
            original(*a, **kw)
            return original(*a, **kw)  # Real A replay, not a fabricated bool.
        with patch.object(self.host.goals, 'cas_goal', replay):
            result = self.step()
        self.assertEqual(result['lookup_status'], 'not_found')
        self.assertEqual(self.ledger.submits, 0)

    def test_pause_wins_after_lookup_and_before_admission_no_task_reserved(self):
        def pause():
            self.host.configure('goal-1', mutation_id='pause', now=NOW, status='paused')
        self.ledger.lookup_hook = pause
        with self.assertRaisesRegex(ValueError, 'goal_revision_conflict'):
            self.step()
        self.assertEqual(self.state()['status'], 'paused')
        self.assertEqual(self.ledger.submits, 0)

    def test_paused_and_stopped_do_not_query_even_existing_original(self):
        self.step()
        for status in ('paused', 'stopped'):
            self.host.configure('goal-1', mutation_id=status, now=NOW, status=status)
            count = self.ledger.lookups
            result = self.step(request_id='new-id')
            self.assertEqual(result['action'], status)
            self.assertEqual(self.ledger.lookups, count)
        self.assertEqual(self.ledger.submits, 1)

    def test_verified_push_can_record_cancel_after_stop_without_execution(self):
        self.step()
        binding = self.binding()
        self.host.configure('goal-1', mutation_id='stop', now=NOW, status='stopped')
        receipt = self.ledger.change(binding, 'cancelled')
        result = self.host.observe('goal-1', receipt=receipt, now=NOW)
        self.assertEqual(result['state']['status'], 'stopped')
        self.assertEqual(result['state']['work']['status'], 'cancelled')
        self.assertEqual(self.ledger.submits, 1)

    def test_completed_partial_evidence_preserves_cutoff_missing_and_stable_original_binding(self):
        self.step()
        binding = self.binding()
        evidence = [dict(ref='us_original/ua_partial', source='authorized_frozen_user_analytics',
                        as_of=(NOW - timedelta(days=7)).isoformat(), coverage='partial',
                        missing=['candidate_pages_unread'], version='scope/data-v1')]
        receipt = self.ledger.change(binding, 'completed', evidence=evidence,
                                     completed_actions=['read-only:receipt'])
        result = self.host.observe('goal-1', receipt=receipt, now=NOW)
        self.assertEqual(result['state']['evidence'], evidence)
        self.assertEqual(result['state']['status'], 'active')
        self.assertEqual(self.host._binding(result['state']), binding)
        replay = self.host.observe('goal-1', receipt=receipt, now=NOW)
        self.assertEqual(replay['action'], 'receipt_already_recorded')
        self.assertEqual(self.step()['action'], 'wait')
        later = self.step(mutation_id='prepare-2', request_id='task-request-2',
                           fact_version='new-verified-composite', now=DUE)
        self.assertEqual(later['state']['evidence'], evidence)
        with self.assertRaisesRegex(ValueError, 'task_receipt_binding'):
            self.host.observe('goal-1', receipt=receipt, now=DUE)
        self.assertEqual(self.ledger.submits, 2)

    def test_unverified_not_found_or_forged_model_success_never_admits(self):
        self.ledger.verified = 1
        with self.assertRaisesRegex(PermissionError, 'unverified'):
            self.step()
        self.assertEqual(self.ledger.submits, 0)
        self.ledger.verified = True
        # The prior prepared reservation is never retried even after validation recovers.
        self.assertEqual(self.step()['lookup_status'], 'not_found')
        fake = dict(binding=self.binding(), status='completed', receipt_ref='model-says-success')
        with self.assertRaisesRegex(PermissionError, 'unverified'):
            self.host.observe('goal-1', receipt=fake, now=NOW)

    def test_lookup_transport_error_and_permission_denial_are_distinct(self):
        self.ledger.lookup_error = TimeoutError('sensitive transport text')
        result = self.step()
        self.assertEqual(result['lookup_status'], 'unknown')
        self.assertNotIn('sensitive', encoded(result))
        self.ledger.lookup_error = PermissionError('denied')
        with self.assertRaises(PermissionError):
            self.step()
        self.assertEqual(self.ledger.submits, 0)

    def test_unknown_and_provider_returned_keep_original_when_new_facts_arrive(self):
        self.step()
        for status in ('provider_returned', 'unknown'):
            receipt = self.ledger.change(self.binding(), status)
            self.host.observe('goal-1', receipt=receipt, now=NOW)
            result = self.step(self.new_host(), request_id='never-replace',
                               fact_version='changed-composite', now=DUE)
            self.assertEqual(result['state']['work']['status'], status)
            self.assertEqual(result['request_id'], 'task-request-1')
        self.assertEqual(self.ledger.submits, 1)

    def test_revocation_after_io_denies_cached_state_and_submit(self):
        self.ledger.lookup_hook = lambda: setattr(self, 'allowed', False)
        with self.assertRaises(PermissionError):
            self.step()
        self.assertEqual(self.ledger.submits, 0)
        self.allowed = 1
        with self.assertRaises(PermissionError):
            self.step()

    def test_misbound_receipt_and_raw_payload_rejected_before_state_write(self):
        self.step()
        original = self.ledger._read(self.binding())
        for field in ('owner', 'cid', 'goal_id', 'scope_ref', 'request_id', 'intent_sha256'):
            fake = deepcopy(original)
            fake['binding'][field] = 'mismatched'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'binding'):
                self.host.observe('goal-1', receipt=fake, now=NOW)
        with self.assertRaises(ValueError):
            self.host.observe('goal-1', receipt=dict(original, raw_model_reply='private'), now=NOW)
        self.assertEqual(self.state()['work']['status'], 'queued')

    def test_cas_receipt_shape_must_not_claim_fresh_with_truthy_values(self):
        original = self.host.goals.cas_goal
        def malformed(*a, **kw):
            result = original(*a, **kw)
            return dict(result, replayed=0)
        with patch.object(self.host.goals, 'cas_goal', malformed):
            with self.assertRaisesRegex(ValueError, 'cas_receipt_contract'):
                self.step()
        self.assertEqual(self.ledger.submits, 0)


if __name__ == '__main__':
    unittest.main()

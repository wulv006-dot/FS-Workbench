"""Offline goal/CAS contract, including the existing real A2/B2 consumer."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent / 'source'))
from b2_goal_state import create_goal, plan_step, record_receipt, configure_goal

NOW = datetime(2026, 10, 30, 0, tzinfo=timezone.utc)
DUE = NOW + timedelta(days=2)


class GoalState(unittest.TestCase):
    def setUp(self):
        self.allowed = True
        self.checks = []
        self.state = create_goal(goal_id='goal-1', owner='host-operator',
            scope_ref='project:1327/scope-version-1', objective='Observe repeat purchases',
            constraints=['Read only', 'Include no-intervention'], recheck_at=DUE,
            now=NOW, explicit_goal=True, authorize=self.authorize)

    def authorize(self, owner, scope):
        self.checks.append((owner, scope))
        return self.allowed

    def plan(self, state=None, **kw):
        state = self.state if state is None else state
        args = dict(expected_revision=state['revision'], now=NOW, fact_version='frozen-v1',
                    request_id='request-1', authorize=self.authorize)
        args.update(kw)
        return plan_step(state, **args)

    def receipt(self, state, **kw):
        args = dict(expected_revision=state['revision'], request_id=state['work']['request_id'],
                    status='completed', receipt_ref='host-receipt-1', now=NOW,
                    authorize=self.authorize)
        args.update(kw)
        return record_receipt(state, **args)

    def config(self, state, **kw):
        args = dict(expected_revision=state['revision'], now=NOW, authorize=self.authorize)
        args.update(kw)
        return configure_goal(state, **args)

    def test_explicit_goal_only_and_strict_live_authorization(self):
        args = dict(goal_id='g', owner='o', scope_ref='s', objective='goal', constraints=[],
                    recheck_at=DUE, now=NOW, authorize=self.authorize)
        for value in (False, None, 1, 'yes'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                create_goal(explicit_goal=value, **args)
        for allowed in (False, None, 1, 'admin'):
            self.allowed = allowed
            with self.subTest(allowed=allowed), self.assertRaises(PermissionError):
                self.plan()
        self.allowed = True
        self.plan()
        self.assertEqual(self.checks[-1], ('host-operator', 'project:1327/scope-version-1'))

    def test_two_proposals_need_atomic_host_cas_not_just_local_revision_check(self):
        stored = deepcopy(self.state)
        a, b = self.plan(), self.plan(request_id='request-racer')
        def cas(proposal):
            nonlocal stored
            if stored['revision'] != proposal['expected_revision']:
                return False
            stored = deepcopy(proposal['state'])
            return True
        self.assertTrue(cas(a))
        self.assertFalse(cas(b))
        self.assertEqual(a['action'], 'dispatch_after_cas')
        self.assertEqual(a['handoff']['task_id'], 'request-1')
        self.assertEqual(self.state['revision'], 1)
        replay = self.plan(stored, request_id='never-dispatch-this-id')
        self.assertEqual(replay['action'], 'reconcile_original')
        self.assertEqual(replay['request_id'], 'request-1')
        self.assertIsNone(replay['handoff'])

    def test_all_outstanding_states_hold_original_despite_new_facts_and_due(self):
        prepared = self.plan()['state']
        for status in ('prepared', 'queued', 'running', 'provider_returned', 'unknown'):
            state = prepared if status == 'prepared' else self.receipt(prepared, status=status)['state']
            result = self.plan(state, now=DUE, request_id='different', fact_version='new-v2')
            self.assertEqual(result['action'], 'reconcile_original', status)
            self.assertEqual(result['state'], state)
            self.assertEqual(result['request_id'], 'request-1')
            self.assertIsNone(result['handoff'])

    def test_unchanged_facts_wait_then_exact_checkpoint_consumed_once(self):
        state = self.receipt(self.plan()['state'])['state']
        self.assertEqual(self.plan(state, now=NOW + timedelta(days=1))['action'], 'wait')
        due = self.plan(state, now=DUE, request_id='request-2')
        self.assertEqual(due['action'], 'dispatch_after_cas')
        self.assertEqual(due['state']['work']['checkpoint_at'], DUE.isoformat())
        done = self.receipt(due['state'], now=DUE, receipt_ref='receipt-2')['state']
        self.assertEqual(self.plan(done, now=DUE + timedelta(days=1))['action'], 'wait')
        rescheduled = self.config(done, now=DUE, recheck_at=DUE + timedelta(days=7))['state']
        self.assertEqual(self.plan(rescheduled, now=DUE + timedelta(days=7),
                                   request_id='request-3')['action'], 'dispatch_after_cas')

    def test_changed_facts_start_short_task_without_automatic_goal_completion(self):
        state = self.receipt(self.plan()['state'])['state']
        step = self.plan(state, request_id='request-2', fact_version='v2')
        self.assertEqual(step['action'], 'dispatch_after_cas')
        self.assertEqual(step['state']['status'], 'active')
        self.assertFalse(step['model_call_performed'])
        self.assertFalse(step['business_write_performed'])
        with self.assertRaisesRegex(ValueError, 'new_trigger'):
            self.plan(state, fact_version='v2')

    def test_failed_and_cancelled_do_not_blindly_replay_same_due_trigger(self):
        for status in ('failed', 'cancelled'):
            prepared = self.plan(now=DUE)['state']
            state = self.receipt(prepared, status=status, now=DUE)['state']
            result = self.plan(state, now=DUE + timedelta(days=1), request_id='retry')
            self.assertEqual(result['action'], 'wait')

    def test_unknown_resolves_only_by_host_receipt_for_original_task(self):
        state = self.receipt(self.plan()['state'], status='unknown')['state']
        with self.assertRaisesRegex(ValueError, 'original_task'):
            self.receipt(state, request_id='replacement')
        resolved = self.receipt(state, receipt_ref='verified-original')['state']
        self.assertEqual(resolved['work']['status'], 'completed')
        self.assertEqual(resolved['work']['request_id'], 'request-1')
        self.assertEqual(resolved['status'], 'active')

    def test_exact_receipt_replay_is_idempotent_terminal_conflicts_and_late_task_rejected(self):
        state = self.receipt(self.plan()['state'])['state']
        again = self.receipt(state, now=NOW + timedelta(hours=1))
        self.assertEqual(again['state'], state)
        self.assertEqual(again['action'], 'receipt_already_recorded')
        with self.assertRaisesRegex(ValueError, 'terminal_receipt_conflict'):
            self.receipt(state, status='cancelled')
        next_state = self.plan(state, request_id='request-2', fact_version='v2')['state']
        with self.assertRaisesRegex(ValueError, 'original_task'):
            self.receipt(next_state, request_id='request-1')

    def test_revocation_denies_plan_receipt_and_configuration_without_cached_handoff(self):
        state = self.plan()['state']
        self.allowed = False
        for call in (lambda: self.plan(state), lambda: self.receipt(state),
                     lambda: self.config(state, status='stopped')):
            with self.assertRaises(PermissionError):
                call()
        self.assertEqual(state['work']['status'], 'prepared')

    def test_pause_stop_do_not_pretend_to_cancel_provider_or_erase_original_task(self):
        state = self.receipt(self.plan()['state'], status='running')['state']
        paused = self.config(state, status='paused')['state']
        self.assertEqual(self.plan(paused)['action'], 'paused')
        resumed = self.config(paused, status='active')['state']
        self.assertEqual(self.plan(resumed)['action'], 'reconcile_original')
        stopped = self.config(resumed, status='stopped')['state']
        self.assertEqual(stopped['work']['status'], 'running')
        self.assertEqual(self.plan(stopped)['action'], 'stopped')
        with self.assertRaisesRegex(ValueError, 'cannot_resume'):
            self.config(stopped, status='active')
        acknowledged = self.receipt(stopped, status='cancelled')['state']
        self.assertEqual(acknowledged['status'], 'stopped')

    def test_revision_conflict_clock_and_unaware_time_fail_without_mutating_input(self):
        before = deepcopy(self.state)
        for args in ({'expected_revision': 2}, {'expected_revision': True},
                     {'now': NOW - timedelta(seconds=1)}, {'now': NOW.replace(tzinfo=None)}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.plan(**args)
        self.assertEqual(self.state, before)

    def test_receipt_regression_and_provider_success_do_not_achieve_goal(self):
        state = self.receipt(self.plan()['state'], status='provider_returned')['state']
        with self.assertRaisesRegex(ValueError, 'regressed'):
            self.receipt(state, status='queued')
        with self.assertRaisesRegex(ValueError, 'only_completed'):
            self.receipt(state, status='provider_returned', evidence=[])
        self.assertEqual(state['status'], 'active')
        self.assertEqual(self.plan(state)['action'], 'reconcile_original')

    def test_minimal_reference_only_missing_and_original_cutoff_survive_continuation(self):
        evidence = [dict(ref='us_frozen/ua_summary', source='authorized_frozen_user_analytics',
            as_of=(NOW - timedelta(days=7)).isoformat(), coverage='partial; checkpoint not covered',
            missing=['refund_history', 'checkpoint_cutoff'], version='scope-v1/data-v1')]
        state = self.receipt(self.plan()['state'], evidence=evidence,
                             completed_actions=['receipt:read-only-investigation'])['state']
        evidence[0]['missing'].clear()
        next_step = self.plan(state, now=DUE, request_id='request-2')
        self.assertEqual(next_step['handoff']['evidence'][0]['missing'],
                         ['refund_history', 'checkpoint_cutoff'])
        self.assertEqual(next_step['handoff']['evidence'][0]['as_of'],
                         (NOW - timedelta(days=7)).isoformat())
        self.assertEqual(next_step['state']['status'], 'active')
        self.assertNotIn('customers', next_step['state'])
        next_step['handoff']['evidence'].clear()
        self.assertTrue(next_step['state']['evidence'])

    def test_unbounded_raw_or_future_evidence_not_admitted_to_state(self):
        prepared = self.plan()['state']
        ref = dict(ref='ref', source='source', as_of=NOW.isoformat(), coverage='partial',
                   missing=['not_complete'], version='v1')
        for evidence in ([dict(ref, rows=[{'email': 'private@example.invalid'}])],
                         [dict(ref, as_of=DUE.isoformat())],
                         [dict(ref, ref='x' * 33000)]):
            with self.subTest(evidence_type=list(evidence[0])), self.assertRaises(ValueError):
                self.receipt(prepared, evidence=evidence)
        self.assertEqual(prepared['work']['status'], 'prepared')

    def test_fresh_server_evidence_is_bound_with_prepared_not_a_fake_task_completion(self):
        checked = NOW + timedelta(hours=1)
        reference = dict(ref='us_frozen/ua_summary', source='authorized_frozen_user_analytics',
                         as_of=checked.isoformat(), coverage='partial',
                         missing=['refund_history'], version='scope/identity/data-v2')
        result = self.plan(now=checked, evidence=[reference])
        self.assertEqual(result['state']['revision'], self.state['revision'] + 1)
        self.assertEqual(result['state']['work']['status'], 'prepared')
        self.assertEqual(result['state']['evidence'], [reference])
        self.assertEqual(result['handoff']['evidence'], [reference])
        self.assertEqual(self.state['evidence'], [])
        self.assertEqual(result['state']['completed_actions'], [])
        pending = self.plan(result['state'], now=checked, evidence=[{'untrusted': 'ignored'}])
        self.assertEqual(pending['state'], result['state'])
        self.assertEqual(pending['action'], 'reconcile_original')
        with self.assertRaisesRegex(ValueError, 'future_evidence'):
            self.plan(evidence=[reference])

    def test_real_frozen_investigation_to_goal_to_existing_b1_handoff(self):
        from test_b2_frozen_investigation import FrozenInvestigation
        fixture = FrozenInvestigation('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        result = fixture.run_investigation(request_id='request-1', page_budget=1)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['evidence'])
        state = self.receipt(self.plan()['state'], evidence=result['evidence'])['state']
        followup = self.plan(state, now=DUE, request_id='request-2')
        refs = followup['handoff']['evidence']
        self.assertEqual(refs, result['evidence'])
        self.assertTrue(any('candidate_pages_unread' in ref['missing'] for ref in refs))
        encoded = json.dumps(followup['state'])
        # The existing identity policy name contains "email"; it is a version
        # label, not a raw customer-email field or address.
        for field in ('email', 'orders', 'events', 'rows'):
            self.assertNotIn('"' + field + '":', encoded)
        self.assertLess(len(encoded.encode()), 32768)
        self.assertEqual(followup['state']['status'], 'active')


if __name__ == '__main__':
    unittest.main()

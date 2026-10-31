"""Actual frozen A2 SQLite -> goal CAS -> native-DB goal outbox, no worker."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / 'source'), str(HERE.parent / 'user-analytics-20261022/tests'),
               str(HERE.parent / 'hermes-conversation-20261018/source'),
               str(HERE.parent / 'hermes-fc-pilot-20261013')]
import test_a2_query_context as fixtures
from b2_goal_facts import FrozenGoalFacts, frozen_fact, FactUnavailable
from b2_goal_host import GoalHost
from conversation_store import ConversationStore
from conversation_goals import ConversationGoals
from pilot import TaskStore


class FixtureMixin:
    def facts_setup(self):
        self.fixture = fixtures.A2Context('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.now = fixtures.NOW
        self.old = self.fixture.summary(end='2026-10-25')
        self.current = self.fixture.summary(end='2026-10-30')
        self.sid = self.current['source']['snapshot_id']


class FrozenFactMetadata(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.facts_setup()

    def fact(self, receipt=None):
        return frozen_fact(self.current if receipt is None else receipt,
                           scope=fixtures.SCOPE, snapshot_id=self.sid, now=self.now)

    def test_native_frozen_versions_and_actual_policy_not_capture_clock_define_fact(self):
        first = self.fact()
        self.assertTrue(first['fact_version'].startswith('b2f_'))
        self.assertEqual(first['evidence']['as_of'], self.current['source']['query']['as_of'])
        changed_clock = deepcopy(self.current)
        changed_clock['source']['captured_at'] = (self.now - timedelta(hours=1)).isoformat()
        self.assertEqual(self.fact(changed_clock)['fact_version'], first['fact_version'])
        changed_policy = deepcopy(self.current)
        changed_policy['data']['lifecycle_policy']['thresholds_days'][-1] += 1
        self.assertNotEqual(self.fact(changed_policy)['fact_version'], first['fact_version'])
        changed_data = deepcopy(self.current)
        changed_data['source']['data_version'] = changed_data['data']['data_version'] = 'next-source-version'
        self.assertNotEqual(self.fact(changed_data)['fact_version'], first['fact_version'])

    def test_missing_or_unknown_native_version_never_gets_a_clock_based_replacement(self):
        for field in ('data_version', 'scope_version', 'identity_version', 'contract_version'):
            for value in (None, '', 'unknown'):
                broken = deepcopy(self.current)
                broken['source'][field] = broken['data'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(FactUnavailable):
                    self.fact(broken)

    def test_source_summary_reference_mismatch_and_future_capture_rejected(self):
        broken = deepcopy(self.current)
        broken['data']['data_version'] = 'not-the-frozen-source'
        with self.assertRaisesRegex(ValueError, 'version_mismatch'):
            self.fact(broken)
        broken = deepcopy(self.current)
        broken['evidence_ref']['scope'] = {'scope': 'project', 'scope_id': 'other'}
        with self.assertRaisesRegex(ValueError, 'reference_mismatch'):
            self.fact(broken)
        broken = deepcopy(self.current)
        broken['source']['captured_at'] = (self.now + timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'future_frozen_source'):
            self.fact(broken)

    def test_partial_native_coverage_missing_and_original_cutoff_are_minimal_references(self):
        partial = deepcopy(self.current)
        partial['status'] = 'partial'
        ref = self.fact(partial)['evidence']
        self.assertIn('frozen_summary_partial', ref['missing'])
        self.assertIn('purchase_cost', ref['missing'])
        self.assertEqual(ref['as_of'], self.current['source']['query']['as_of'])
        raw = json.dumps(ref)
        self.assertNotIn('@example.test', raw)
        for field in ('email', 'orders', 'rows', 'events'):
            self.assertNotIn('"' + field + '":', raw)
        self.assertFalse(json.loads(ref['coverage'])['enumeration_complete'])


class SpyContext:
    def __init__(self, native):
        self.native, self.identity, self.scope = native, native.identity, deepcopy(native.scope)
        self.calls = []
        self.transform = self.after_aggregate = None

    def source_authorized(self, *args):
        return self.native.source_authorized(*args)

    def catalog(self):
        self.calls.append('catalog')
        return self.native.catalog()

    def aggregate(self, *, snapshot_id, section):
        self.calls.append(snapshot_id)
        value = deepcopy(self.native.aggregate(snapshot_id=snapshot_id, section=section))
        if self.transform:
            value = self.transform(value)
        if self.after_aggregate:
            self.after_aggregate()
        return value


class FrozenGoalOutbox(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.facts_setup()
        # This module is A-owned. Import only after its fixed candidate is merged.
        from conversation_goal_tasks import ConversationGoalTasks
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConversationStore(Path(self.temp.name) / 'conversations')
        self.cid = self.store.create('operator')['conversation_id']
        self.tasks = TaskStore(Path(self.temp.name) / 'existing-native-tasks.sqlite3')
        self.goal_allowed = True
        self.goals = ConversationGoals(self.store, 'operator', self.cid, self.authorize)
        self.queue = ConversationGoalTasks(self.tasks, 'operator', self.cid, self.authorize,
                                            expected_path=Path(self.tasks.path).resolve())
        self.host = GoalHost(self.goals, owner='operator', cid=self.cid, authorize=self.authorize,
                             dispatcher=self.queue, verify_receipt=self.queue.verify_receipt)
        self.host.create('goal-1', mutation_id='create', scope_ref='project:1327/scope-v1',
                         objective='Observe repeat purchases', constraints=['Read only'],
                         recheck_at=self.now + timedelta(days=7), now=self.now, explicit_goal=True)
        self.spy = SpyContext(self.fixture.context)
        self.mapping = deepcopy(fixtures.SCOPE)
        self.factories = 0
        self.bridge = FrozenGoalFacts(self.host, resolve_scope=self.resolve, context_for=self.context_for)

    def authorize(self, owner, scope):
        return self.goal_allowed if owner == 'operator' and scope == 'project:1327/scope-v1' else False

    def resolve(self, owner, reference):
        return deepcopy(self.mapping)

    def context_for(self, owner, scope):
        self.factories += 1
        return self.spy

    def step(self, **changes):
        args = dict(snapshot_id=self.sid, mutation_id='prepare', request_id='original-request', now=self.now)
        args.update(changes)
        return self.bridge.step('goal-1', **args)

    def state(self):
        return self.goals.load_goal('goal-1')

    def seed_baseline(self):
        # Starting facts, not an invented executed task or provider receipt.
        value = self.state()
        value['revision'] += 1
        value['evidence'] = [frozen_fact(self.old, scope=fixtures.SCOPE,
            snapshot_id=self.old['source']['snapshot_id'], now=self.now)['evidence']]
        self.goals.cas_goal('goal-1', expected_revision=1, mutation_id='seed-test-baseline', state=value)

    def test_real_frozen_summary_and_persistent_outbox_without_a_native_task_or_worker(self):
        with patch.object(self.queue, 'submit', wraps=self.queue.submit) as submit:
            result = self.step()
            self.assertEqual(result['state']['work']['status'], 'queued')
            self.assertEqual(submit.call_count, 1)
            sent = submit.call_args.kwargs['handoff']['evidence']
        self.assertEqual(sent, result['state']['evidence'])
        self.assertEqual(json.loads(sent[0]['ref'])['snapshot_id'], self.sid)
        self.assertEqual(sent[0]['as_of'], self.current['source']['query']['as_of'])
        with self.tasks.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
        receipt = self.queue.lookup(binding=self.host._binding(self.state()))
        self.assertTrue(self.queue.verify_receipt(receipt, self.host._binding(self.state())))
        self.assertEqual(receipt['status'], 'queued')  # Outbox only, no run_id invented.

    def test_pending_reconciliation_ignores_new_snapshot_and_never_reads_a2_again(self):
        with patch.object(self.queue, 'submit', wraps=self.queue.submit) as submit:
            self.step()
            self.spy.calls.clear()
            factories = self.factories
            replay = self.step(snapshot_id='never-read-this', request_id='never-replace')
            self.assertEqual(replay['request_id'], 'original-request')
            self.assertEqual(submit.call_count, 1)
        self.assertEqual(self.factories, factories)
        self.assertEqual(self.spy.calls, [])

    def test_pending_metadata_does_not_return_private_cached_refs_without_source_recheck(self):
        self.step()
        self.fixture.source_allowed = False
        self.spy.calls.clear()
        factories = self.factories
        result = self.step()
        self.assertEqual(result['request_id'], 'original-request')
        self.assertNotIn('state', result)
        self.assertNotIn('evidence', result)
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(self.factories, factories)

    def test_paused_and_stopped_do_not_construct_data_context(self):
        for status in ('paused', 'stopped'):
            self.host.configure('goal-1', mutation_id=status, now=self.now, status=status)
            self.assertEqual(self.step()['action'], status)
        self.assertEqual(self.factories, 0)
        self.assertEqual(self.spy.calls, [])

    def test_unknown_scope_mapping_never_opens_context_or_reserves(self):
        self.mapping = None
        with patch.object(self.queue, 'submit', wraps=self.queue.submit) as submit:
            result = self.step()
            self.assertEqual(submit.call_count, 0)
        self.assertEqual(result['action'], 'unavailable')
        self.assertEqual(self.factories, 0)
        self.assertIsNone(self.state()['work'])

    def test_missing_version_is_unavailable_without_updating_goal_evidence(self):
        def missing(value):
            value['source']['data_version'] = value['data']['data_version'] = None
            return value
        self.spy.transform = missing
        with patch.object(self.queue, 'submit', wraps=self.queue.submit) as submit:
            result = self.step()
            self.assertEqual(submit.call_count, 0)
        self.assertEqual(result['action'], 'unavailable')
        self.assertIsNone(self.state()['work'])
        self.assertEqual(self.state()['evidence'], [])

    def test_baseline_is_replayed_from_native_snapshot_and_both_original_refs_retained(self):
        self.seed_baseline()
        result = self.step()
        refs = result['state']['evidence']
        self.assertEqual([json.loads(ref['ref'])['snapshot_id'] for ref in refs],
                         [self.sid, self.old['source']['snapshot_id']])
        self.assertEqual(len(self.spy.calls), 3)  # catalog + current + baseline, not candidate rows.
        self.assertEqual(refs[1]['as_of'], self.old['source']['query']['as_of'])

    def test_same_snapshot_keeps_previously_reported_missing_fields(self):
        value = self.state()
        value['revision'] += 1
        value['evidence'] = [frozen_fact(self.current, scope=fixtures.SCOPE,
                                        snapshot_id=self.sid, now=self.now)['evidence']]
        value['evidence'][0]['missing'].append('earlier_candidate_pages_unread')
        self.goals.cas_goal('goal-1', expected_revision=1, mutation_id='seed-current', state=value)
        result = self.step()
        self.assertIn('earlier_candidate_pages_unread', result['state']['evidence'][0]['missing'])
        self.assertEqual(len(self.spy.calls), 2)  # No duplicate replay of the same snapshot.

    def test_same_policy_name_with_different_frozen_definition_is_incomparable(self):
        self.seed_baseline()
        def changed(value):
            if value['source']['snapshot_id'] == self.sid:
                value['data']['lifecycle_policy']['thresholds_days'][-1] += 1
            return value
        self.spy.transform = changed
        with patch.object(self.queue, 'submit', wraps=self.queue.submit) as submit:
            self.assertEqual(self.step()['action'], 'incomparable')
            self.assertEqual(submit.call_count, 0)
        self.assertIsNone(self.state()['work'])

    def test_missing_baseline_is_not_reconstructed_from_a_hash_or_current_data(self):
        self.seed_baseline()
        native = self.spy.aggregate
        def missing(*, snapshot_id, section):
            if snapshot_id == self.old['source']['snapshot_id']:
                raise LookupError('snapshot_missing')
            return native(snapshot_id=snapshot_id, section=section)
        with patch.object(self.spy, 'aggregate', missing):
            self.assertEqual(self.step()['action'], 'unavailable')
        self.assertIsNone(self.state()['work'])

    def test_source_revocation_after_read_blocks_goal_cas_and_outbox(self):
        self.spy.after_aggregate = lambda: setattr(self.fixture, 'source_allowed', False)
        with patch.object(self.queue, 'submit', wraps=self.queue.submit) as submit:
            with self.assertRaises(PermissionError):
                self.step()
            self.assertEqual(submit.call_count, 0)
        self.assertEqual(self.state()['evidence'], [])

    def test_goal_revision_change_after_source_read_does_not_apply_stale_facts(self):
        self.spy.after_aggregate = lambda: self.host.configure('goal-1', mutation_id='pause-racer',
                                                              now=self.now, status='paused')
        with self.assertRaisesRegex(ValueError, 'goal_revision_conflict'):
            self.step()
        self.assertEqual(self.state()['status'], 'paused')
        self.assertIsNone(self.state()['work'])

    def test_cas_reply_loss_keeps_fresh_evidence_and_prepared_together_without_dispatch(self):
        original = self.goals.cas_goal
        def lose(*args, **kw):
            original(*args, **kw)
            raise TimeoutError('CAS committed; reply lost')
        with patch.object(self.goals, 'cas_goal', lose):
            result = self.step()
        self.assertEqual(result['action'], 'reconcile_storage')
        state = self.state()
        self.assertEqual(state['revision'], 2)
        self.assertEqual(state['work']['status'], 'prepared')
        self.assertEqual(json.loads(state['evidence'][0]['ref'])['snapshot_id'], self.sid)
        self.spy.calls.clear()
        held = self.step(request_id='never-replace')
        self.assertEqual(held['lookup_status'], 'not_found')
        self.assertEqual(self.spy.calls, [])

    def test_context_owner_and_physical_scope_cannot_be_swapped(self):
        self.spy.identity = 'other-operator'
        with self.assertRaises(PermissionError):
            self.step()
        self.spy.identity = 'operator'
        self.spy.scope = {'scope': 'project', 'scope_id': 'other'}
        with self.assertRaises(PermissionError):
            self.step()
        self.assertEqual(self.spy.calls, [])


if __name__ == '__main__':
    unittest.main()

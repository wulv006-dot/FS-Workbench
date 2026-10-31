"""B2/A2 combination: real synthetic Store/Service, no source/model client."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / 'source'), str(HERE.parent / 'user-analytics-20261022/tests')]
import test_a2_query_context as fixtures
from b1_model_routing import handoff
from b2_frozen_investigation import investigate, page_chain, aware, encoded, followup


class FrozenInvestigation(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.A2Context(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.baseline = self.fixture.snapshot(self.fixture.summary())
        self.current = self.fixture.snapshot(self.fixture.summary(end='2026-10-30'))
        people = self.fixture.context.candidates(self.baseline)['rows']
        self.cid = max(people, key=lambda row: row['purchases']['covered_history_orders'])['opaque_customer_id']
        self.context = self.fixture.plan(self.cid)

    def run_investigation(self, context=None, **changes):
        args = dict(request_id='original-investigation:1', baseline_snapshot_id=self.baseline,
                    current_snapshot_id=self.current, observation_at='2026-10-29T00:00:00+08:00',
                    observation_anchor=aware('2026-10-25T00:00:00+08:00'), now=fixtures.NOW,
                    customer_ids=[self.cid], page_budget=10, limit=1)
        args.update(changes)
        return investigate(context or self.context, **args)

    def test_complete_cursor_chain_and_financial_limits_are_separate(self):
        result = self.run_investigation()
        self.assertEqual(result['status'], 'observed_with_limits')
        self.assertEqual(result['candidate_coverage']['observed'], 2)
        self.assertTrue(result['candidate_coverage']['enumeration_complete'])
        self.assertEqual(result['decisions'][0]['payment_observation'], 'due_no_new_purchase_observed')
        self.assertEqual(result['decisions'][0]['followup']['state'], 'needs_evidence')
        self.assertEqual(result['decisions'][0]['followup']['maturity'], {'7': None, '14': None, '30': None})
        self.assertEqual(result['decisions'][0]['net_contribution'], 'unknown')
        self.assertIn('complete_refund_change_cursor', result['decisions'][0]['limits'])
        self.assertEqual(result['options'][0]['action'], 'no_intervention')
        self.assertFalse(result['business_write_performed'])
        self.assertFalse(result['model_call_performed'])

    def test_205_candidates_are_enumerated_but_not_copied_into_handoff(self):
        self.fixture.rows = [fixtures.order(i + 10, person='person' + str(i)) for i in range(205)]
        self.fixture.load()
        old = self.fixture.snapshot(self.fixture.summary())
        current = self.fixture.snapshot(self.fixture.summary(end='2026-10-30'))
        cid = self.fixture.context.candidates(old)['rows'][0]['opaque_customer_id']
        context = self.fixture.plan(cid)
        result = self.run_investigation(context, baseline_snapshot_id=old, current_snapshot_id=current,
                                        customer_ids=[cid], page_budget=2, limit=200)
        self.assertTrue(result['candidate_coverage']['enumeration_complete'])
        self.assertEqual(result['candidate_coverage']['observed'], 205)
        self.assertEqual(result['load']['context_calls']['candidates'], 2)
        self.assertEqual(len(result['decisions']), 1)
        task = handoff(task_id='frozen-goal', revision=1, goal='investigate selected customer',
                       constraints=['no business actions'], evidence=result['evidence'],
                       completed_actions=[], next_step='review missing refund evidence')
        text = encoded(task)
        for forbidden in ('@example.test', 'synthetic-', '"orders"', '"purchases"', '"email"'):
            self.assertNotIn(forbidden, text)
        self.assertIn('us_', text)
        self.assertIn('ua_', text)
        self.assertIn('cursor', text)
        self.assertIn('scope', text)
        self.assertEqual(result['load']['source_rows_scanned'], 'unknown')
        self.assertGreater(result['load']['response_bytes'], 0)

    def test_partial_candidate_and_timeline_pages_do_not_erase_useful_observation(self):
        result = self.run_investigation(page_budget=1)
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['candidate_coverage']['enumeration_complete'])
        self.assertIsNotNone(result['candidate_coverage']['next_cursor'])
        self.assertFalse(result['decisions'][0]['timeline_coverage']['enumeration_complete'])
        self.assertEqual(result['decisions'][0]['payment_observation'], 'due_no_new_purchase_observed')
        self.assertIn('candidate_pages_unread', result['decisions'][0]['limits'])

    def test_terminal_tail_without_prior_pages_never_claims_whole_query(self):
        first = self.context.candidates(self.current, limit=1)
        final = self.context.candidates(self.current, cursor=first['next_cursor'], limit=1)
        self.assertIsNone(final['next_cursor'])
        self.assertFalse(final['complete'])
        tail = page_chain(self.context, method='candidates', snapshot_id=self.current,
                          group='known_pool', cursor=first['next_cursor'], page_budget=1, limit=1)
        self.assertFalse(tail['coverage']['enumeration_complete'])
        self.assertFalse(tail['coverage']['started_from_beginning'])

    def test_duplicate_page_and_changed_source_are_not_counted_as_complete(self):
        first = self.context.candidates(self.current, limit=1)
        second = self.context.candidates(self.current, cursor=first['next_cursor'], limit=1)
        for mutate in ('duplicate', 'version'):
            wrong = deepcopy(second)
            if mutate == 'duplicate':
                wrong['rows'] = deepcopy(first['rows'])
            else:
                wrong['source']['data_version'] = 'different-version'
            client = SimpleNamespace(candidates=Mock(side_effect=[first, wrong]))
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                page_chain(client, method='candidates', snapshot_id=self.current,
                           group='known_pool', page_budget=2, limit=1)

    def test_cursor_reference_mismatch_and_row_count_gap_are_rejected(self):
        first = self.context.candidates(self.current, limit=1)
        for mutate in ('reference', 'count'):
            wrong = deepcopy(first)
            if mutate == 'reference':
                wrong['evidence_ref']['query']['group'] = 'entered_silent'
            else:
                wrong['total'] += 1
                wrong['next_cursor'] = None
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                page_chain(SimpleNamespace(candidates=Mock(return_value=wrong)), method='candidates',
                           snapshot_id=self.current, group='known_pool', page_budget=1, limit=1)

    def test_old_cutoff_stays_old_and_does_not_prove_no_purchase(self):
        result = self.run_investigation(current_snapshot_id=self.baseline)
        self.assertEqual(result['decisions'][0]['payment_observation'], 'refresh_required')
        self.assertEqual(aware(result['source_as_of']), aware('2026-10-25T00:00:00+08:00'))
        self.assertNotEqual(result['source_as_of'], result['observation_at'])

    def test_new_purchase_and_late_refund_correction_remain_observations(self):
        self.fixture.rows.append(fixtures.order(9, '2026-10-28'))
        self.fixture.load()
        current = self.fixture.snapshot(self.fixture.summary(end='2026-10-30'))
        original = self.fixture.context.candidates(current)['rows']
        value = self.run_investigation(current_snapshot_id=current)
        self.assertEqual(value['decisions'][0]['payment_observation'], 'due_with_new_purchase')
        self.assertEqual(value['decisions'][0]['causal_effect'], 'unknown')
        self.fixture.rows[-1] = fixtures.order(9, '2026-10-28', paid='2')
        self.fixture.load()
        corrected = self.fixture.snapshot(self.fixture.summary(end='2026-10-30'))
        result = self.run_investigation(baseline_snapshot_id=current, current_snapshot_id=corrected)
        self.assertEqual(result['decisions'][0]['payment_observation'], 'requires_review')
        self.assertEqual(result['decisions'][0]['followup']['state'], 'needs_evidence')
        self.assertEqual(self.fixture.context.candidates(current)['rows'], original)

    def test_incomparable_snapshot_does_not_produce_followup_decision(self):
        self.fixture.config['identity_version'] = 'different-synthetic-identity'
        current = self.fixture.snapshot(self.fixture.summary(end='2026-10-30'))
        value = self.run_investigation(current_snapshot_id=current)
        self.assertEqual(value['status'], 'incomparable')
        self.assertTrue(all('followup' not in row for row in value['decisions']))

    def test_revocation_mid_chain_does_not_return_previous_private_results(self):
        native = self.context.candidates
        calls = []
        def read(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                self.fixture.host_allowed = False
            return native(*args, **kwargs)
        self.context.candidates = read
        with self.assertRaises(PermissionError):
            self.run_investigation()
        self.assertEqual(len(calls), 2)

    def test_unknown_keeps_original_identity_and_never_retries_or_runs_comparison(self):
        timeline = Mock(side_effect=TimeoutError('PRIVATE_SOURCE_DETAIL'))
        changes = Mock()
        context = SimpleNamespace(catalog=self.context.catalog, aggregate=self.context.aggregate,
                                  candidates=self.context.candidates, timeline=timeline, changes_due=changes)
        value = self.run_investigation(context)
        self.assertEqual(value['status'], 'unknown')
        self.assertEqual(value['request_id'], 'original-investigation:1')
        self.assertFalse(value['retry_allowed'])
        self.assertNotIn('PRIVATE_SOURCE_DETAIL', encoded(value))
        timeline.assert_called_once()
        changes.assert_not_called()

    def test_unknown_after_first_page_preserves_read_reference_and_stops(self):
        first = self.context.candidates(self.current, limit=1)
        pages = Mock(side_effect=[first, TimeoutError('PRIVATE_SOURCE_DETAIL')])
        changes, timeline = Mock(), Mock()
        context = SimpleNamespace(catalog=self.context.catalog, aggregate=self.context.aggregate,
                                  candidates=pages, timeline=timeline, changes_due=changes)
        result = self.run_investigation(context)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['candidate_coverage']['observed'], 1)
        self.assertEqual(pages.call_count, 2)
        self.assertEqual(result['evidence'][-1]['ref'].count('chain_sha256'), 1)
        self.assertIn(first['next_cursor'], result['candidate_coverage']['next_cursor'])
        self.assertFalse(result['retry_allowed'])
        timeline.assert_not_called()
        changes.assert_not_called()

    def test_handoff_pins_both_snapshot_versions(self):
        result = self.run_investigation()
        text = encoded(result['evidence'])
        self.assertIn(self.baseline, text)
        self.assertIn(self.current, text)
        self.assertIn('frozen_baseline', text)
        self.assertEqual(result['load']['context_calls']['aggregate'], 2)

    def test_partial_history_beyond_conservative_cutoff_is_missing_not_future_fact(self):
        comparison = self.context.changes_due(self.baseline, self.current, '2026-10-29T00:00:00+08:00',
            [{'opaque_customer_id': self.cid, 'snapshot_id': self.baseline}])
        source = deepcopy(comparison['source'])
        source['coverage']['state_data_through'] = '2026-10-10T00:00:00+08:00'
        source['coverage']['period_complete'] = False
        value = followup(comparison['changes'][0], source, now=fixtures.NOW,
                         observation_anchor=aware('2026-10-05T00:00:00+08:00'))
        self.assertEqual(value['state'], 'needs_evidence')
        self.assertIn('payment_outside_conservative_cutoff', value['evidence']['missing'])
        self.assertEqual(value['maturity'], {'7': None, '14': None, '30': None})

    def test_stopped_goal_does_not_read_even_the_catalog(self):
        context = Mock()
        result = self.run_investigation(context, goal_active=False)
        self.assertEqual(result['status'], 'stopped')
        context.catalog.assert_not_called()
        self.assertEqual(result['load']['context_calls'], {})

    def test_source_scope_or_future_cutoff_mismatch_is_rejected(self):
        aggregate = self.context.aggregate(snapshot_id=self.current)
        for mutate in ('scope', 'future'):
            wrong = deepcopy(aggregate)
            if mutate == 'scope':
                wrong['source']['query']['scope_id'] = '1329'
            else:
                wrong['source']['query']['as_of'] = '2026-11-02T00:00:00+08:00'
                wrong['source']['coverage']['state_data_through'] = '2026-11-02T00:00:00+08:00'
            context = SimpleNamespace(catalog=self.context.catalog, aggregate=Mock(return_value=wrong))
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.run_investigation(context)


if __name__ == '__main__':
    unittest.main()

"""Decision consumption of real A2 synthetic Store/Service receipts; no models."""
from copy import deepcopy
import base64
import importlib
import json
import unittest

import test_b2_frozen_investigation as frozen


class DecisionCard(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('b2_decision_card'),
                             'B2 decision-card consumer has not been implemented')
        self.build = importlib.import_module('b2_decision_card').decision_card
        self.fixture = frozen.FrozenInvestigation(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.result = self.fixture.run_investigation()

    def card(self, result=None, **changes):
        args = dict(opaque_customer_id=self.fixture.cid, goal='调查复购节奏，不执行触达',
                    recheck_at='2026-11-02T10:00:00+08:00')
        args.update(changes)
        return self.build(self.result if result is None else result, **args)

    def test_real_frozen_receipt_answers_six_questions_without_business_execution(self):
        before = deepcopy(self.result)
        card = self.card()
        self.assertEqual(card['subject'], self.fixture.cid)
        self.assertEqual(card['recommendation'], 'investigate_evidence')
        self.assertEqual({x['action'] for x in card['alternatives']},
                         {'no_intervention', 'investigate_evidence'})
        self.assertTrue(all(x['reason'] for x in card['alternatives']))
        self.assertEqual(card['source_as_of'], self.result['source_as_of'])
        self.assertTrue(card['evidence'])
        self.assertIn('complete_refund_change_cursor', card['missing'])
        self.assertEqual(card['recheck_at'], '2026-11-02T10:00:00+08:00')
        self.assertEqual(card['authorization']['execution'], 'not_granted_by_this_card')
        self.assertFalse(card['goal_completed'])
        self.assertFalse(card['business_write_performed'])
        self.assertEqual(card['net_contribution'], 'unknown')
        self.assertEqual(card['causal_effect'], 'unknown')
        self.assertEqual(self.result, before)
        card['missing'].append('consumer_change')
        self.assertEqual(self.result, before)

    def test_partial_pages_never_present_a_complete_investigation(self):
        card = self.card(self.fixture.run_investigation(page_budget=1))
        self.assertEqual(card['status'], 'partial')
        self.assertIn('candidate_pages_unread', card['missing'])
        self.assertIn('timeline_pages_unread', card['missing'])
        self.assertFalse(card['coverage']['candidates_complete'])
        self.assertFalse(card['coverage']['timeline_complete'])

    def test_due_with_stale_cutoff_requires_refresh_without_advancing_source_date(self):
        result = deepcopy(self.result)
        row = result['decisions'][0]
        row['payment_observation'] = 'refresh_required'
        row['followup'].update(state='refresh_required', reason='source_does_not_cover_due_check')
        card = self.card(result)
        self.assertEqual(card['reason'], 'source_does_not_cover_due_check')
        self.assertEqual(card['recommendation'], 'investigate_evidence')
        self.assertEqual(card['source_as_of'], result['source_as_of'])

    def test_waiting_can_recommend_no_intervention_without_declaring_goal_complete(self):
        result = deepcopy(self.result)
        row = result['decisions'][0]
        row.update(limits=[], payment_observation='not_due')
        row['followup'].update(state='waiting', reason='within_supplied_purchase_cadence')
        self.assertEqual(self.card(result)['recommendation'], 'investigate_evidence')
        # The real fixture has refund gaps. Only a separately complete input may
        # prefer waiting; do not weaken the consumer to conceal those gaps.
        for reference in result['evidence']:
            reference['missing'] = []
        card = self.card(result)
        self.assertEqual(card['recommendation'], 'no_intervention')
        self.assertFalse(card['goal_completed'])

    def test_correction_or_missing_data_never_recommends_a_discount(self):
        result = deepcopy(self.result)
        result['decisions'][0]['followup'].update(
            state='needs_evidence', reason='refund_correction_requires_review')
        result['decisions'][0]['options'].append('discount_customer')
        card = self.card(result)
        self.assertEqual(len(card['alternatives']), 2)
        self.assertEqual(card['recommendation'], 'investigate_evidence')

    def test_stopped_or_unavailable_input_does_not_leak_old_decisions(self):
        for status in ('stopped', 'unavailable', 'unknown', 'incomparable'):
            with self.subTest(status=status):
                result = deepcopy(self.result)
                result['status'] = status
                card = self.card(result)
                self.assertEqual(card['status'], status)
                self.assertNotIn('subject', card)
                self.assertNotIn('evidence', card)

    def test_only_requested_customer_and_minimal_refs_are_returned(self):
        result = deepcopy(self.result)
        other = 'c_' + 'f' * 32
        row = deepcopy(result['decisions'][0])
        row.update(opaque_customer_id=other, private_text='PRIVATE_OTHER')
        result['decisions'].append(row)
        result['raw_orders'] = ['RAW_ORDERS']
        result['model_text'] = 'IGNORE PERMISSIONS'
        reference = deepcopy(result['evidence'][-1])
        reference['ref'] = json.dumps({'query': {'opaque_customer_id': other}})
        result['evidence'].append(reference)
        card = self.card(result)
        text = json.dumps(card)
        for secret in (other, 'PRIVATE_OTHER', 'RAW_ORDERS', 'IGNORE PERMISSIONS'):
            self.assertNotIn(secret, text)
        self.assertFalse(card['model_call_performed'])

    def test_real_candidate_cursor_does_not_disclose_previous_customer(self):
        people = self.fixture.context.candidates(self.fixture.current)['rows']
        ids = sorted(row['opaque_customer_id'] for row in people)
        self.assertEqual(len(ids), 2)
        for cid in ids:
            with self.subTest(customer=cid):
                context = self.fixture.fixture.plan(cid)
                result = self.fixture.run_investigation(context, customer_ids=[cid], limit=1)
                # A real candidate-chain cursor contains the first customer's ID.
                tokens = [json.loads(e['ref']).get('last', {}).get('query', {}).get('cursor')
                          for e in result['evidence']]
                decoded = [json.loads(base64.urlsafe_b64decode(t + '=' * (-len(t) % 4)))
                           for t in tokens if t]
                self.assertTrue(any(v.get('after') == ids[0] for v in decoded))
                card = self.card(result, opaque_customer_id=cid)
                for ref in card['evidence']:
                    locator = json.loads(ref['ref'])
                    queries = [locator.get('query', {}), locator.get('first', {}).get('query', {}),
                               locator.get('last', {}).get('query', {})]
                    self.assertTrue(all(q.get('method') != 'candidates' for q in queries))
                    for query in queries:
                        token = query.get('cursor')
                        if token:
                            position = json.loads(base64.urlsafe_b64decode(
                                token + '=' * (-len(token) % 4)))['after']
                            if isinstance(position, str) and position.startswith('c_'):
                                self.assertEqual(position, cid)
                self.assertIn('candidate_reference_withheld_for_privacy', card['missing'])
                self.assertEqual(card['coverage']['candidates_complete'], True)

    def test_real_multi_customer_comparison_removal_is_explicit_not_forged(self):
        people = self.fixture.context.candidates(self.fixture.current)['rows']
        ids = [row['opaque_customer_id'] for row in people]
        context = self.fixture.fixture.make(observation={
            'observation_at': '2026-10-29T00:00:00+08:00',
            'checks': {cid: {'recheck_at': '2026-10-28T00:00:00+08:00'} for cid in ids}})
        result = self.fixture.run_investigation(context, customer_ids=ids)
        comparison = [e for e in result['evidence']
                      if json.loads(e['ref']).get('query', {}).get('method') == 'changes_due']
        self.assertEqual(len(comparison), 1)
        for cid in ids:
            card = self.card(result, opaque_customer_id=cid)
            self.assertIn('comparison_reference_withheld_for_privacy', card['missing'])
            self.assertEqual(card['evidence_delivery'], 'partial')
            self.assertEqual(card['status'], 'partial')
            self.assertEqual(card['recommendation'], 'investigate_evidence')
            self.assertEqual(card['source_as_of'], result['source_as_of'])
            for ref in card['evidence']:
                self.assertIn(ref, result['evidence'])  # Never forge a single-customer query.
                self.assertNotEqual(json.loads(ref['ref']).get('query', {}).get('method'),
                                    'changes_due')

    def test_incomplete_coverage_overrides_summary_label(self):
        result = deepcopy(self.result)
        result['candidate_coverage']['enumeration_complete'] = False
        self.assertEqual(self.card(result)['status'], 'partial')

    def test_followup_specific_missing_history_is_not_lost(self):
        result = deepcopy(self.result)
        result['decisions'][0]['followup']['evidence']['missing'].append(
            'payment_outside_conservative_cutoff')
        self.assertIn('payment_outside_conservative_cutoff', self.card(result)['missing'])

    def test_executed_or_model_receipts_are_not_relabelled_as_offline_investigation(self):
        for field in ('business_write_performed', 'model_call_performed'):
            with self.subTest(field=field):
                result = deepcopy(self.result)
                result[field] = True
                with self.assertRaises(ValueError):
                    self.card(result)

    def test_unknown_customer_duplicate_and_invalid_times_are_rejected(self):
        with self.assertRaises(ValueError):
            self.card(opaque_customer_id='c_' + 'e' * 32)
        result = deepcopy(self.result)
        result['decisions'].append(deepcopy(result['decisions'][0]))
        with self.assertRaises(ValueError):
            self.card(result)
        for value in ('not-a-time', '2026-11-02T10:00:00'):
            with self.assertRaises(ValueError):
                self.card(recheck_at=value)


if __name__ == '__main__':
    unittest.main()

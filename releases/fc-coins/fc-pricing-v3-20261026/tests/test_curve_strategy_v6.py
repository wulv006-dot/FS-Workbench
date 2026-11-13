"""Fixed reference and confirmed adoption on synthetic full-curve inputs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from test_price_curve_v6 import EDITOR_CONTRACT, catalogue, read
from test_pricing_proof_v6 import fixture as proof_fixture
from fc_pricing_v3.curve_strategy_v6 import (
    build_candidates, choose_action, confirm_adoption, intermediate_candidates, market_preference,
    minimum_repair, propose_adoption,
)
from fc_pricing_v3.price_curve import curve_key, read_curve
from fc_pricing_v3.pricing_proof_v6 import validate_curve


def saved(curve):
    contract = {key: value for key, value in curve['native_contract'].items() if key != 'catalogue_origin'}
    return read_curve(curve['native_payload'], curve['identity'], contract)


def fixture():
    row = catalogue()
    row.update(id=163329311, aid=21587)
    row['more']['discount'][6:] = [95, 95]
    row['more']['price'][6:] = [190, 475]
    identity = dict(read()['identity'], id='163329311')
    current = read_curve(row, identity, EDITOR_CONTRACT)
    reference = dict(reference_curve_id='adopted-A', reference_curve=current)
    episode = dict(comparison_episode_id='episode-1', initial_reference_curve_id='adopted-A',
                   initial_reference_curve=current)
    return current, reference, episode


def candidate(comparison, label):
    return next(record for record in comparison['candidates'] if label in record['labels'])


def proof(curve, *, cost_status='verified', fee_status='verified'):
    _, baskets, evidence, domain = proof_fixture()
    key = curve_key(curve)
    evidence['curve_key'] = domain['curve_key'] = key
    evidence['paths'][0].update(curve_key=key, cost_status=cost_status, fee_status=fee_status)
    return validate_curve(curve, baskets, evidence, domain)


def evidence():
    return dict(order_revisions={'anon-order-1': 'semantic-cost-v1'}, window_ids=['window-A', 'window-B'],
                window_start='2026-11-11T00:00:00+00:00', window_end='2026-11-12T00:00:00+00:00',
                cost_revision='cost-v1', maturity='comparison-available', reason='Mature procurement contribution',
                changed_judgment='Observed contribution supports previously uncertain trial',
                cumulative=dict(initial_reference_curve_id='adopted-A', evidence_ref='cumulative-result',
                                revenue_delta_usd='-3', procurement_gross_delta_usd='12', new_customer_delta='0'))


class FixedCurveCandidates(unittest.TestCase):
    def test_reference_not_rebased_by_competitor_or_temporary_b(self):
        current, reference, episode = fixture()
        first = build_candidates(current, reference, episode, 'large')
        b = candidate(first, 'B')
        self.assertEqual(b['curve']['tiers'][4]['native_price_usd'], '92.15')
        self.assertEqual(b['curve']['tiers'][2]['native_price_usd'], '10')
        # Same A persists when B is confirmed, including across a new episode.
        later = build_candidates(saved(b['curve']), reference, dict(episode, comparison_episode_id='new'), 'large')
        self.assertEqual(candidate(later, 'B')['curve_key'], b['curve_key'])
        self.assertEqual(set(candidate(later, 'B')['labels']), {'CURRENT', 'B'})
        self.assertEqual(candidate(later, 'A')['curve_key'], curve_key(current))

    def test_same_100k_different_high_tier_is_distinct_and_write_gap_preserved(self):
        current, reference, episode = fixture()
        comparison = build_candidates(current, reference, episode, 'large')
        a, b, c = (candidate(comparison, label) for label in 'ABC')
        self.assertEqual(len({a['curve_key'], b['curve_key'], c['curve_key']}), 3)
        for row in (a, b, c):
            self.assertEqual(row['curve']['tiers'][2]['native_price_usd'], '10')
        self.assertEqual(b['write_gaps'], ['native_discount_write_unverified'])
        self.assertEqual(b['discount_changes'][0]['purchase_k'], '1000')

    def test_rounding_outside_three_percent_reports_unsearched_gap(self):
        current, reference, episode = fixture()
        comparison = build_candidates(current, reference, episode, 'small')
        self.assertEqual(comparison['gaps']['C'][0]['code'], 'editor_anchor_not_expressible')
        self.assertEqual(comparison['boundary_search_status'], 'intermediate_native_steps_unsearched')
        result = choose_action(comparison, {}, preferred_label='C')
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')

    def test_bounded_intermediate_steps_stay_on_original_reference(self):
        current, reference, episode = fixture()
        comparison = build_candidates(current, reference, episode, 'large')
        steps = list(intermediate_candidates(comparison, 'B', EDITOR_CONTRACT,
                                             tier_price_factors_verified=True))
        self.assertGreater(len(steps), 1)
        self.assertEqual(steps[0]['curve']['tiers'][4]['native_price_usd'], '92.16')
        self.assertEqual(steps[-1]['curve']['tiers'][4]['native_price_usd'], '94.99')
        self.assertTrue(all(step['curve']['tiers'][2] == current['tiers'][2] for step in steps))
        outer = candidate(comparison, 'B')['curve']
        again = build_candidates(saved(outer), reference, episode, 'large')
        self.assertEqual([step['curve_key'] for step in steps],
                         [step['curve_key'] for step in intermediate_candidates(again, 'B', EDITOR_CONTRACT)])

    def test_varying_discounts_do_not_flatten_selected_segment_beyond_bound(self):
        current, reference, episode = fixture()
        row = deepcopy(current['native_payload'])
        row['more']['price'][6:] = [180, 450]
        row['more']['discount'][6:] = [90, 90]
        changed = read_curve(row, current['identity'], EDITOR_CONTRACT)
        comparison = build_candidates(changed, dict(reference, reference_curve=changed), episode, 'large')
        self.assertEqual(comparison['gaps']['B'], [dict(code='compiled_tier_outside_segment_step',
                                                       purchase_k='2000')])

    def test_current_and_a_are_not_legal_without_same_curve_f2_proof(self):
        current, reference, episode = fixture()
        comparison = build_candidates(current, reference, episode, 'large')
        key = curve_key(current)
        good = proof(current)
        for proofs in ({}, {key: dict(good, proof_hash='other')},
                       {key: proof(candidate(comparison, 'B')['curve'])},
                       {key: proof(current, fee_status='unknown')}):
            with self.subTest(proofs=proofs.keys()):
                result = choose_action(comparison, proofs)
                self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
                self.assertIsNone(result['selected'])
        result = choose_action(comparison, {key: good})
        self.assertEqual(result['status'], 'KEEP')
        self.assertIs(result['execution_authorized'], False)

    def test_proof_legal_trial_keeps_writer_gap(self):
        current, reference, episode = fixture()
        comparison = build_candidates(current, reference, episode, 'large')
        b = candidate(comparison, 'B')
        result = choose_action(comparison, {b['curve_key']: proof(b['curve'])}, preferred_label='B')
        self.assertEqual(result['status'], 'BOUNDED_TRIAL')
        self.assertEqual(result['gaps'], ['native_discount_write_unverified'])
        self.assertIs(result['execution_authorized'], False)
        verified = build_candidates(current, reference, episode, 'large', tier_price_factors_verified=True)
        self.assertEqual(candidate(verified, 'B')['curve_key'], b['curve_key'])
        self.assertEqual(candidate(verified, 'B')['write_gaps'], [])

    def test_market_needs_same_platform_regular_quantity_and_business_movement(self):
        current, _, _ = fixture()
        now = datetime(2026, 11, 13, 6, tzinfo=timezone.utc)
        stamp = (now - timedelta(minutes=2)).isoformat()
        offer = dict(source='Lootbar', platform='PS', purchase_k='1000', delivered_k='1000',
                     regular_price='85', currency='USD', promotion_eligibility='all_customers',
                     comparable=True, conditional=False, captured_at=stamp)
        weak = dict(paid_orders=9, net_paid_usd='90', procurement_gross_usd='15')
        stable = dict(paid_orders=10, net_paid_usd='100', procurement_gross_usd='20')
        sample = dict(coverage_status='comparable', margin_basis='procurement_gross_usd',
                      current=weak, previous=stable)
        self.assertEqual(market_preference(current, 'PS', [offer], {'large': sample}, now)['label'], 'B')
        self.assertEqual(market_preference(current, 'PS', [offer],
                                           {'large': dict(sample, margin_basis=None)}, now)['label'], 'B')
        self.assertIsNone(market_preference(current, 'PS', [offer],
                                           {'large': dict(sample, current=stable)}, now))
        for changed in (dict(platform='PC'), dict(source='U7Buy'), dict(purchase_k='2000'),
                        dict(conditional=True), dict(region_id=39),
                        dict(captured_at=(now - timedelta(hours=1)).isoformat())):
            with self.subTest(changed=changed):
                self.assertIsNone(market_preference(current, 'PS', [dict(offer, **changed)], {'large': sample}, now))
        higher = dict(offer, regular_price='106')
        self.assertEqual(market_preference(current, 'PS', [higher],
                                           {'large': dict(sample, current=stable)}, now)['label'], 'C')
        self.assertIsNone(market_preference(current, 'PS', [higher],
                                           {'large': dict(sample, current=stable, margin_basis=None)}, now))

    def test_minimum_repair_changes_only_affected_segment_and_keeps_native_specs(self):
        current, reference, episode = fixture()
        stronger = candidate(build_candidates(current, reference, episode, 'large'), 'C')['curve']
        row = deepcopy(current['native_payload'])
        row['more']['price'][4] = '95.01'
        minimal = read_curve(row, current['identity'], EDITOR_CONTRACT)
        bad = deepcopy(row)
        bad['more']['give'][4] = '999'
        changed_gift = read_curve(bad, current['identity'], EDITOR_CONTRACT)
        bad = deepcopy(row)
        bad['more']['price'][2] = '10.01'
        changed_other_segment = read_curve(bad, current['identity'], EDITOR_CONTRACT)
        choices = [dict(curve=value) for value in (changed_gift, stronger, changed_other_segment, minimal)]
        self.assertEqual(minimum_repair(current, choices, ['large'])['curve'], minimal)
        self.assertIsNone(minimum_repair(current, choices, ['small']))

    def test_different_offer_terms_keep_current_for_proof_and_block_old_a_trial(self):
        current, reference, episode = fixture()
        row = deepcopy(current['native_payload'])
        row['more']['give'][4] = 0
        new = read_curve(row, current['identity'], EDITOR_CONTRACT)
        comparison = build_candidates(new, reference, episode, 'large')
        self.assertEqual([row['labels'] for row in comparison['candidates']], [['CURRENT']])
        self.assertEqual(choose_action(comparison, {}, preferred_label='B')['gaps'],
                         ['current_reference_catalogue_terms_differ'])


class CurveAdoption(unittest.TestCase):
    def setUp(self):
        current, self.reference, self.episode = fixture()
        trial = candidate(build_candidates(current, self.reference, self.episode, 'large'), 'B')
        self.current = saved(trial['curve'])
        self.comparison = build_candidates(self.current, self.reference, self.episode, 'large')
        self.key = curve_key(self.current)
        self.decision = choose_action(self.comparison, {self.key: proof(self.current)})

    def test_reference_moves_only_after_original_confirmed_readback(self):
        proposal = propose_adoption(self.reference, self.comparison, self.decision, evidence(),
                                    operation_id='original-op')
        self.assertEqual(self.reference['reference_curve_id'], 'adopted-A')
        receipt = dict(operation_id='original-op', status='COMPLETED', complete_curve_readback=True,
                       curve_key=self.key, readback_ref='existing-confirmed-receipt')
        for invalid in (dict(status='UNKNOWN'), dict(operation_id='new-op'),
                        dict(complete_curve_readback=False), dict(curve_key='same-100k-but-other-high')):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'readback_unconfirmed'):
                confirm_adoption(self.reference, proposal, self.current, dict(receipt, **invalid))
        adopted = confirm_adoption(self.reference, proposal, self.current, receipt)
        self.assertEqual(adopted['reference_curve_id'], proposal['adoption_id'])
        self.assertEqual(adopted['initial_reference_curve_id'], 'adopted-A')
        self.assertEqual(adopted['confirmed_operation_id'], 'original-op')
        self.assertIn(dict(purchase_k='1000', initial_usd='95', target_usd='92.15'),
                      proposal['cumulative_tier_prices'])
        self.assertEqual(adopted, confirm_adoption(adopted, proposal, self.current, receipt))

    def test_evidence_refresh_not_new_adoption_and_cost_revision_can_be_new_evidence(self):
        baseline = deepcopy(self.reference)
        data = evidence()
        original = propose_adoption(baseline, self.comparison, self.decision, data, operation_id='prior')
        baseline['adoption_evidence'] = dict(order_revisions=data['order_revisions'],
                                             used_evidence_hashes=[original['evidence_hash']])
        cosmetic = dict(data, checked_at='later', reason='Reworded summary', window_ids=['renamed'])
        with self.assertRaisesRegex(ValueError, 'no_new_evidence'):
            propose_adoption(baseline, self.comparison, self.decision, cosmetic, operation_id='another')
        mature = dict(data, order_revisions={'anon-order-1': 'semantic-cost-v2'}, cost_revision='cost-v2')
        proposal = propose_adoption(baseline, self.comparison, self.decision, mature, operation_id='another')
        self.assertEqual(proposal['evidence_delta'], {'anon-order-1': dict(before='semantic-cost-v1',
                                                                        after='semantic-cost-v2')})
        self.assertNotEqual(proposal['evidence_hash'], original['evidence_hash'])


if __name__ == '__main__':
    unittest.main()

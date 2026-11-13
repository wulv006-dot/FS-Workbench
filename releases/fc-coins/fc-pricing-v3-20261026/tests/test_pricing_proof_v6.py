"""V6 proof arithmetic over synthetic frozen quotes and path coverage."""
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
from fc_pricing_v3.pricing_proof_v6 import validate_curve


def make_curve(*, high_price='100', observed_at='old'):
    goods = dict(id=163329311, mid=41217957, gid=1327, cid=9623, site_id=266,
                 aid=21587, unit='K', status=1, unit_price='.1', observed_at=observed_at,
                 more=dict(gold=['100', '1000'], give=['0', '30'], discount=['100', '100'],
                           price=['10', high_price]))
    identity = {key: goods[key] for key in IDENTITY_FIELDS}
    return read_curve(goods, identity, {'version': 'synthetic-native-v1'})


def quote(path_id, key, **overrides):
    row = dict(path_id=path_id, site_id='266', curve_key=key, proof_status='verified',
               cost_status='verified', fee_status='verified', quote_ref='fixture-quote:' + path_id,
               cost_ref='fixture-cost:' + path_id, fee_ref='fixture-fee:' + path_id,
               currency='USD', amount_kind='TOTAL', quantity_basis='PURCHASE_K',
               native_tier_or_rule='tier-1000', rounding_contract='fixture-native-cent',
               offer_version='fixture-offer', fulfilment_contract='fixture-order',
               purchase_k='1000', promised_bonus_k='30', promised_delivered_k='1030',
               regular_usd='100', net_receipt_usd='100', known_fee_usd='1',
               expected_cost_usd='75', safe_cost_usd='76', stress_cost_usd='80')
    return dict(row, **overrides)


def basket(selection, weights):
    return dict(selection=selection, coverage_status='complete', coverage_gaps=[],
                evidence_ref='fixture-basket:' + selection,
                members=[dict(path_id=path_id, weight=weight) for path_id, weight in weights])


def fixture():
    curve = make_curve()
    key = curve_key(curve)
    evidence = dict(curve_key=key, paths=[quote('ordinary', key)])
    domain = dict(curve_key=key, platform='PS', version='synthetic-domain-v1',
                  coverage_status='complete', coverage_gaps=[],
                  source_revisions=dict(quantity='quantity-v1', offers='offers-v1',
                                        fulfilment='fulfilment-v1', propagation='propagation-v1'),
                  site_paths={'266': ['ordinary']})
    baskets = dict(main=basket('closed_bjt_7d', [('ordinary', '50')]),
                   recent=basket('latest_24h', [('ordinary', '30')]))
    return curve, baskets, evidence, domain


def add_path(evidence, domain, path_id, site_id='266', **overrides):
    evidence['paths'].append(quote(path_id, evidence['curve_key'], site_id=site_id, **overrides))
    domain['site_paths'].setdefault(site_id, []).append(path_id)


class PricingProofV6(unittest.TestCase):
    def test_24_percent_not_rejected_by_target25(self):
        result = validate_curve(*fixture())
        self.assertEqual(result['status'], 'PROVEN')
        self.assertEqual(result['minimum_safe_procurement_margin'], '0.24')
        self.assertEqual(result['paths'][0]['zero_line_surplus_usd'], '19')
        self.assertEqual(result['target']['target_gap_pp'], '1')
        self.assertEqual(result['target']['gain_needed_at_fixed_revenue_usd'], '50')
        self.assertAlmostEqual(Decimal(result['target']['net_revenue_needed_at_fixed_cost_usd']),
                               Decimal('66.6666666667'))
        self.assertIs(result['target']['target_is_hard_constraint'], False)

    def test_recent_basket_can_fail_without_a_new_per_tier_floor(self):
        curve, baskets, evidence, domain = fixture()
        add_path(evidence, domain, 'discounted', net_receipt_usd='90')
        baskets['main'] = basket('closed_bjt_7d', [('ordinary', '40'), ('discounted', '10')])
        baskets['recent'] = basket('latest_3d', [('discounted', '32')])
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'HARD_CONSTRAINT_FAILED')
        self.assertEqual(result['hard_failures'], ['platform_margin:recent'])
        self.assertEqual(result['baskets']['main']['net_receipt_usd'], '4900')
        self.assertEqual(result['baskets']['main']['safe_cost_usd'], '3800')
        self.assertAlmostEqual(Decimal(result['baskets']['main']['safe_procurement_margin']),
                               Decimal(1100) / 4900)
        self.assertEqual(result['minimum_safe_procurement_margin'],
                         result['baskets']['recent']['safe_procurement_margin'])

    def test_exact_zero_and_eighteen_are_legal(self):
        curve, baskets, evidence, domain = fixture()
        evidence['paths'][0].update(safe_cost_usd='82', stress_cost_usd='99')
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROVEN')
        self.assertEqual(result['paths'][0]['zero_line_surplus_usd'], '0')
        self.assertEqual(result['minimum_safe_procurement_margin'], '0.18')
        evidence['paths'][0].update(safe_cost_usd='82.0000000000000000000001')
        self.assertEqual(validate_curve(curve, baskets, evidence, domain)['status'],
                         'HARD_CONSTRAINT_FAILED')

    def test_fee_unknown_not_zero_but_procurement_margin_remains_evaluable(self):
        curve, baskets, evidence, domain = fixture()
        for amount in (None, '0', '1'):
            with self.subTest(amount=amount):
                evidence['paths'][0].update(fee_status='unknown', known_fee_usd=amount)
                result = validate_curve(curve, baskets, evidence, domain)
                self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
                self.assertIn('path:ordinary:fee_unverified', result['gaps'])
                self.assertIsNone(result['paths'][0]['known_fee_usd'])
                self.assertIsNone(result['paths'][0]['zero_line_surplus_usd'])
                self.assertEqual(result['minimum_safe_procurement_margin'], '0.24')
        evidence['paths'][0].update(fee_status='verified', known_fee_usd='0')
        self.assertEqual(validate_curve(curve, baskets, evidence, domain)['status'], 'PROVEN')

    def test_confirmed_merchant_rates_close_the_fee_domain_for_site266_only(self):
        curve, baskets, evidence, domain = fixture()
        evidence['paths'][0].update(fee_status='unknown', fee_ref=None, known_fee_usd=None)
        result = validate_curve(curve, baskets, evidence, domain)
        row = result['paths'][0]
        self.assertEqual(row['merchant_fee_components']['payment_rate'], '0')
        self.assertEqual(row['merchant_fee_components']['fulfilment_rate'], '0')
        self.assertEqual(row['merchant_fee_components']['source'], 'creator_confirmation_2026-11-13')
        self.assertEqual(row['known_fee_usd'], '0')
        self.assertEqual(row['zero_line_surplus_usd'], '20')
        self.assertEqual(result['status'], 'PROVEN')
        evidence['paths'][0]['additional_necessary_fee_pending']=True
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertIn('fee_unverified', result['paths'][0]['gaps'])
        self.assertIsNone(result['paths'][0]['known_fee_usd'])
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')

    def test_unknown_cost_not_dropped(self):
        curve, baskets, evidence, domain = fixture()
        add_path(evidence, domain, 'missing-cost', cost_status='unknown', safe_cost_usd=None)
        baskets['main']['members'].append(dict(path_id='missing-cost', weight='10'))
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        main = result['baskets']['main']
        self.assertIsNone(main['safe_procurement_margin'])
        self.assertEqual(main['members'][0]['weight'], '10')
        self.assertIn('basket_path_incomplete:missing-cost', main['gaps'])
        self.assertEqual(result['baskets']['recent']['safe_procurement_margin'], '0.24')

    def test_shared_fulfilment_zero_floor(self):
        curve, baskets, evidence, domain = fixture()
        add_path(evidence, domain, 'merged-orders', fulfilment_contract='fixture-shared-batch',
                 known_fee_usd='2', expected_cost_usd='90', safe_cost_usd='94', stress_cost_usd='99')
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'HARD_CONSTRAINT_FAILED')
        self.assertEqual(result['hard_failures'], ['zero_line:merged-orders'])
        self.assertEqual(result['paths'][0]['zero_line_surplus_usd'], '-1')
        self.assertEqual(result['minimum_safe_procurement_margin'], '0.24')

    def test_satellite_checks_its_own_zero_line_but_has_no_margin_floor(self):
        curve, baskets, evidence, domain = fixture()
        add_path(evidence, domain, 'satellite', '300', net_receipt_usd='81', safe_cost_usd='80')
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROVEN')
        self.assertEqual(result['paths'][1]['zero_line_surplus_usd'], '0')
        evidence['paths'][1]['known_fee_usd'] = '1.01'
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['hard_failures'], ['zero_line:satellite'])

    def test_scope_attestation_and_quote_binding_are_required(self):
        curve, baskets, evidence, domain = fixture()
        evidence['paths'][0]['proof_status'] = 'unverified'
        domain['coverage_status'] = 'partial'
        domain['coverage_gaps'] = ['custom_quantity_domain_unknown']
        domain['source_revisions'].pop('propagation')
        domain['platform'] = 'PC'
        domain['site_paths']['300'] = ['missing-quote']
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertEqual(result['scope']['coverage_gaps'], ['custom_quantity_domain_unknown'])
        self.assertIn('domain_revision_missing:propagation', result['gaps'])
        self.assertIn('path:ordinary:native_quote_unverified', result['gaps'])
        self.assertIn('path:missing-quote:quote_path_missing', result['gaps'])
        self.assertIn('curve_scope_mismatch', result['gaps'])

    def test_duplicate_path_and_stale_quote_cannot_be_silently_used(self):
        curve, baskets, evidence, domain = fixture()
        evidence['paths'].append(dict(evidence['paths'][0], net_receipt_usd='99'))
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertIn('path:ordinary:quote_path_duplicate', result['gaps'])
        self.assertIsNone(result['minimum_safe_procurement_margin'])
        evidence['paths'].pop()
        evidence['paths'][0]['curve_key'] = 'stale-key'
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertIn('path:ordinary:path_curve_key_mismatch', result['gaps'])
        result = validate_curve(make_curve(high_price='99'), baskets, evidence, domain)
        self.assertIn('curve_key_mismatch', result['gaps'])

    def test_empty_missing_or_zero_weight_and_zero_revenue_are_not_evaluable(self):
        for weights in ([], [('ordinary', None)], [('ordinary', 0)], [('ordinary', -1)]):
            with self.subTest(weights=weights):
                curve, baskets, evidence, domain = fixture()
                baskets['main'] = basket('closed_bjt_7d', weights)
                result = validate_curve(curve, baskets, evidence, domain)
                self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
                self.assertEqual(result['baskets']['main']['status'], 'NOT_EVALUABLE')
                self.assertIsNone(result['baskets']['main']['safe_procurement_margin'])
        evidence['paths'][0].update(net_receipt_usd='0')
        baskets['main'] = basket('closed_bjt_7d', [('ordinary', '50')])
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertIn('main:basket_zero_revenue', result['gaps'])
        self.assertEqual(result['baskets']['main']['status'], 'NOT_EVALUABLE')
        self.assertEqual(result['hard_failures'], ['zero_line:ordinary'])

    def test_invalid_units_quantities_and_cost_bounds_are_gaps(self):
        curve, baskets, evidence, domain = fixture()
        evidence['paths'][0].update(currency='CNY', amount_kind='PER_BASIS_K',
                                    promised_delivered_k='1000', stress_cost_usd='75')
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertEqual(result['paths'][0]['gaps'], ['expected_total_usd_amounts',
                                                      'promised_delivery_mismatch',
                                                      'cost_bounds_inconsistent'])

    def test_main_fallback_keeps_members_and_explicitly_records_selection(self):
        curve, baskets, evidence, domain = fixture()
        baskets['recent'] = basket('main_fallback', [('ordinary', '30')])
        baskets['main']['members'][0]['quote_ref'] = evidence['paths'][0]['quote_ref']
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertIn('recent:fallback_members_mismatch', result['gaps'])
        baskets['recent']['members'] = deepcopy(baskets['main']['members'])
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROVEN')
        self.assertEqual(result['baskets']['recent']['selection'], 'main_fallback')

    def test_basket_quote_reference_must_match_current_path_when_supplied(self):
        curve, baskets, evidence, domain = fixture()
        baskets['main']['members'][0]['quote_ref'] = 'old-quote'
        result = validate_curve(curve, baskets, evidence, domain)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIn('main:basket_quote_ref_mismatch:ordinary', result['gaps'])
        self.assertIsNone(result['baskets']['main']['safe_procurement_margin'])

    def test_fingerprint_canonicalizes_order_decimals_and_context_and_binds_evidence(self):
        curve, baskets, evidence, domain = fixture()
        add_path(evidence, domain, 'other')
        baskets['main']['members'].append(dict(path_id='other', weight='5'))
        original = validate_curve(curve, baskets, evidence, domain)
        evidence['paths'].reverse()
        evidence['paths'][0]['safe_cost_usd'] = '76.00000'
        domain['site_paths']['266'].reverse()
        baskets['main']['members'].reverse()
        baskets['main']['members'][0]['weight'] = Decimal('5.000')
        with localcontext() as context:
            context.prec = 6
            equivalent = validate_curve(make_curve(observed_at='new'), baskets, evidence, domain)
        self.assertEqual(equivalent, original)
        evidence['paths'][0]['fee_ref'] = 'fee-revised'
        self.assertNotEqual(validate_curve(curve, baskets, evidence, domain)['proof_hash'],
                            original['proof_hash'])


if __name__ == '__main__':
    unittest.main()

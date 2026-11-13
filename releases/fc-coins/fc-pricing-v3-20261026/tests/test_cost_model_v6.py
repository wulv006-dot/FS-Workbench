"""Given verified same-layer USD costs, preserve quantity dimensions and gaps."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3.cost_model import normalize_cost, estimate_layer

LAYER = dict(platform='PS', quantity_bucket='large', offer_version='offer1',
             fulfilment_contract='normal1')


def row(order='a', **values):
    return dict(dict(order_key=order, layer=LAYER, purchase_k='1000', promised_bonus_k='30',
                     cost_usd='50', cost_kind='TOTAL', quantity_basis='PURCHASE_K',
                     cost_complete=True), **values)


class CostModel(unittest.TestCase):
    def test_total_and_unit_cost_keep_same_total_across_bases(self):
        for basis in ('PURCHASE_K', 'PROMISED_DELIVERED_K'):
            total = normalize_cost(row(), basis)
            unit = normalize_cost(row(cost_usd='.05', cost_kind='PER_BASIS_K'), basis)
            self.assertEqual(total['total_usd'], Decimal('50'))
            self.assertEqual(unit, total)
            self.assertEqual(total['unit_usd'] * total['basis_k'], Decimal('50'))

    def test_actual_shipping_basis_requires_total_not_future_unit(self):
        sample = row(quantity_basis='ACTUAL_SHIPPED_K', actual_shipped_k='1500')
        self.assertEqual(normalize_cost(sample, 'PURCHASE_K')['unit_usd'], Decimal('.05'))
        with self.assertRaisesRegex(ValueError, 'source_basis'):
            normalize_cost(dict(sample, cost_kind='PER_BASIS_K'), 'PURCHASE_K')
        with self.assertRaisesRegex(ValueError, 'target_basis'):
            normalize_cost(sample, 'ACTUAL_SHIPPED_K')

    def test_alpha_uses_quantity_not_order_count_and_upper_not_added_twice(self):
        samples = [row(), row('b', purchase_k='2000', promised_bonus_k='60',
                              cost_complete=False, cost_usd='20')]
        result = estimate_layer(samples, LAYER, 'PURCHASE_K', upper=row(cost_usd='80'))
        self.assertEqual(result['alpha'], Decimal(2) / 3)
        self.assertEqual(result['expected_unit_usd'], Decimal('.05'))
        self.assertEqual(result['safe_unit_usd'], Decimal('.07'))
        self.assertEqual(result['stress_unit_usd'], Decimal('.08'))
        self.assertEqual(result['known_partial_usd'], Decimal('20'))

    def test_partial_cost_is_lower_bound(self):
        result = estimate_layer([row(), row('b', cost_complete=False, cost_usd='100')],
                                LAYER, 'PURCHASE_K', upper=row(cost_usd='80'))
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIn('upper_below_known_partial', result['gaps'])
        self.assertIsNone(result['safe_unit_usd'])
        self.assertIsNone(result['stress_unit_usd'])

    def test_missing_and_unknown_quantity_not_dropped(self):
        result = estimate_layer([row(), row('b', cost_complete=False, cost_usd=None),
                                 row('c', purchase_k=None, cost_complete=False, cost_usd=None)],
                                LAYER, 'PURCHASE_K')
        self.assertEqual(result['unknown_quantity_orders'], 1)
        self.assertEqual(result['incomplete_cost_orders'], 2)
        self.assertEqual(result['alpha'], Decimal('.5'))
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIsNone(result['safe_unit_usd'])

    def test_unknown_quantity_retains_known_total_outside_rate_denominator(self):
        result = estimate_layer([row(), row('b', purchase_k=None, cost_complete=False,
                                           cost_usd='12')], LAYER, 'PURCHASE_K')
        self.assertEqual(result['unallocated_known_cost_usd'], Decimal('12'))
        self.assertEqual(result['known_quantity_k'], Decimal('1000'))
        self.assertEqual(result['unknown_quantity_orders'], 1)

    def test_same_order_duplicate_and_cross_layer_rejected(self):
        for samples in ([row(), row()], [row(), row('b', layer=dict(LAYER, platform='PC'))]):
            with self.assertRaises(ValueError):
                estimate_layer(samples, LAYER, 'PURCHASE_K')

    def test_true_zero_cost_preserved_and_complete_missing_is_gap(self):
        result = estimate_layer([row(cost_usd='0')], LAYER, 'PURCHASE_K')
        self.assertEqual(result['expected_unit_usd'], Decimal(0))
        self.assertEqual(result['safe_unit_usd'], Decimal(0))
        result = estimate_layer([row(cost_usd=None)], LAYER, 'PURCHASE_K')
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIsNone(result['expected_unit_usd'])

    def test_promised_basis_weights_bonus_once(self):
        result = estimate_layer([row(), row('b', cost_complete=False, cost_usd=None)],
                                LAYER, 'PROMISED_DELIVERED_K', upper=row(cost_usd='80'))
        self.assertEqual(result['safe_unit_usd'] * Decimal(1030), Decimal('65'))
        self.assertEqual(result['stress_unit_usd'] * Decimal(1030), Decimal('80'))


if __name__ == '__main__':
    unittest.main()

import unittest

from fc_pricing_v3.demand_model import fit


class ZeroOrdersTest(unittest.TestCase):
    def test_zero_order_group_does_not_claim_fitted_elasticity(self):
        rows = [dict(mode='production', origin='actual_order_and_price_window',
                     price_window_id=str(i), assignment_probability=1,
                     offset_kind='effective_hours', exposure='3', paid_orders='0',
                     price_group='region:21:PC', effective_price_usd=str(price),
                     as_of='2026-11-05T00:00:00+00:00')
                for i, price in enumerate((10, 11, 10))]
        result = fit(rows)
        self.assertNotIn('region:21:PC', result['groups'])
        self.assertEqual(result['status'], 'central_prior_no_qualified_price_variation_yet')


if __name__ == '__main__':
    unittest.main()

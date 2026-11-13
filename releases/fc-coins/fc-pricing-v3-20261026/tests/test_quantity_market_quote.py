from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3.engine import quantity_market_quote, market_quote
from fc_pricing_v3.competitor_offers import POLICY

NOW=datetime(2026,11,13,tzinfo=timezone.utc)


class QuantityMarketQuote(unittest.TestCase):
    def setUp(self):
        self.row=dict(status='valid',source='U7Buy',platform='PC',run_id='run',
            purchase_k='1000',bonus_k='100',currency='USD',regular_price='70',
            eligible_net_price='60',promotion_eligibility='new_customer',
            delivery_method='comfort',delivery_tier='standard',conditional=True,
            comparable=True,captured_at=NOW.isoformat(),necessary_fees=None)
        self.evidence=dict(run_id='run',competitor_policy=POLICY,competitor_offers=[self.row])

    def quote(self,**kwargs):
        fields=dict(source='U7Buy',platform='PC',purchase_k='1000',
            promotion_eligibility='new_customer',delivery_method='comfort',
            delivery_tier='standard',currency='USD',now=NOW)
        fields.update(kwargs)
        return quantity_market_quote(self.evidence,**fields)

    def test_exact_observed_quantity_conditions_and_delivered_basis(self):
        original=deepcopy(self.evidence)
        value=self.quote(price_kind='eligible_net')
        self.assertEqual(value['selected_price'],'60')
        self.assertEqual(value['delivered_k'],'1100')
        self.assertIsNone(value['necessary_fees'])
        self.assertFalse(value['price_action_authorized'])
        self.assertEqual(self.evidence,original)

    def test_no_100k_scaling_no_customer_or_delivery_substitution(self):
        for kwargs in (dict(purchase_k='100'),dict(promotion_eligibility='all_customers'),
                       dict(delivery_tier='express'),dict(currency='EUR')):
            with self.assertRaisesRegex(ValueError,'offer_missing'):self.quote(**kwargs)

    def test_unknown_price_and_stale_same_run_do_not_quote(self):
        self.row['eligible_net_price']=None
        with self.assertRaisesRegex(ValueError,'comparison_unverified'):self.quote(price_kind='eligible_net')
        self.row['run_id']='other'
        with self.assertRaisesRegex(ValueError,'run_mismatch'):self.quote()

    def test_u7_never_falls_into_old_arab_dispatch(self):
        with self.assertRaisesRegex(ValueError,'source_unsupported:U7Buy'):
            market_quote({'arab_ut_quotes':[self.row]},'PC','U7Buy',NOW)

    def test_unrelated_stale_quantity_does_not_block_fresh_selected_offer(self):
        self.evidence['competitor_offers'].append(dict(self.row,purchase_k='100',captured_at='2026-11-12T00:00:00+00:00'))
        self.assertEqual(self.quote()['selected_price'],'70')
        with self.assertRaisesRegex(ValueError,'capture_stale'):self.quote(purchase_k='100')


if __name__=='__main__':unittest.main()

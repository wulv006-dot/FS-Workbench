from datetime import datetime, timezone, timedelta
from decimal import Decimal
import unittest
from fc_pricing_v3 import simulation

NOW=datetime(2026,11,10,12,tzinfo=timezone.utc)
class ThreePlatformShadowTest(unittest.TestCase):
    def evidence(self):
        mix={'by_platform':{p:dict(net_order_usd=str(r*800),undiscounted_order_usd='800',retained_ratio=str(r)) for p,r in [('PS',Decimal('.9')),('XBOX',Decimal('.8')),('PC',Decimal('.7'))]}}
        return dict(historical_discount_mix=mix,storefront={'rows':{p:{'package_usd':'10'} for p in mix['by_platform']}},region_rules=[])
    def test_shadow_context_uses_each_platform_eight_day_buckets(self):
        path=simulation.initial_path('daily',self.evidence(),NOW)
        context=simulation.context_for(path,NOW)
        self.assertEqual({p:v['retained_ratio'] for p,v in context['by_platform'].items()},{'PS':'0.9','XBOX':'0.8','PC':'0.7'})
        self.assertEqual({v['bucket_count'] for v in context['by_platform'].values()},{8})
        self.assertEqual(set(path['price_anchor']['base_prices']),{'PS','XBOX','PC'})
    def test_original_pooled_snapshot_replays_original_two_groups(self):
        from fixtures import fixture,NOW,set_console_cost
        evidence=fixture(legacy=True)[0];set_console_cost(evidence)
        for rules in evidence['promotion_envelope']['packages'].values():
            for tier in rules['tiers']:
                if str(tier['base_k'])=='100':tier['bonus_k']='5'
        from fc_pricing_v3.financial import fingerprint
        evidence['promotion_envelope']['sha256']=fingerprint({k:v for k,v in evidence['promotion_envelope'].items() if k not in ('sha256','checked_at')})
        result=simulation.evaluate(evidence,'daily',now=NOW,evaluation_context=simulation.historical_context(evidence,'same_real_snapshot'))
        self.assertEqual(result['status'],'READY')
        self.assertEqual(set(result['selected']['action']['base_prices']),{'console','pc'})
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(result['financial_contract_version'],'fc27_dual20_d9_d2_v2')

    def test_old_pooled_shadow_is_explicit_read_only(self):
        from fc_pricing_v3.legacy_simulation import evaluate_platform_v2
        with self.assertRaisesRegex(ValueError,'read_only'):evaluate_platform_v2({},'daily')

if __name__=='__main__':unittest.main()

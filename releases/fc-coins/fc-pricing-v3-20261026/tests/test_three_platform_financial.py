"""Independent amount-weighted discounts and exact platform floors; synthetic data."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fixtures import fixture, NOW, set_console_cost
from fc_pricing_v3 import financial as f, engine


def platform_history(data, ratios=('.92','.95','.88')):
    by_platform={}
    for platform,ratio in zip(engine.PLATFORMS,ratios):
        net=Decimal(ratio)*100
        mix=dict(status='available',platform=platform,period=f.history_period(NOW),
                 history_window_contract=f.HISTORY_WINDOW_CONTRACT,observed_orders=10,eligible_orders=10,
                 net_order_usd=str(net),actual_discount_usd=str(100-net),
                 undiscounted_order_usd='100',retained_ratio=str(net/100))
        mix['sha256']=f.fingerprint(mix);by_platform[platform]=mix
    root=dict(status='available',platform_contract='fc27_history_platform_v1',
              history_window_contract=f.HISTORY_WINDOW_CONTRACT,period=f.history_period(NOW),
              by_platform=by_platform,source_coverage=dict(unknown_platform_orders=0),
              aggregate=dict(observed_orders=30,eligible_orders=30,
                             net_order_usd=str(sum(Decimal(r)*100 for r in ratios)),
                             actual_discount_usd=str(sum((1-Decimal(r))*100 for r in ratios)),
                             undiscounted_order_usd='300'))
    root['sha256']=f.fingerprint(root);data['historical_discount_mix']=root
    return data


class IndependentPlatformFinancial(unittest.TestCase):
    def test_same_cost_different_actual_discounts_produce_distinct_floor_and_display(self):
        data=platform_history(fixture()[0])
        basis=engine.price_basis(data,NOW)
        self.assertNotIn('historical_retained_ratio',basis)
        for platform,ratio in zip(engine.PLATFORMS,('.92','.95','.88')):
            row=basis['rows'][platform]
            self.assertEqual(Decimal(row['historical_retained_ratio']),Decimal(ratio))
            self.assertEqual(Decimal(row['average_discount_pct']),(1-Decimal(ratio))*100)
        self.assertLess(Decimal(basis['rows']['XBOX']['average_floor_usd']),Decimal(basis['rows']['PS']['average_floor_usd']))

    def test_each_platform_floor_rejects_its_own_previous_cent(self):
        data=platform_history(fixture()[0])
        floors={p:engine.required_base_bound(data,p,NOW) for p in engine.PLATFORMS}
        action=dict(base_prices={p:str(v) for p,v in floors.items()},region_coefficients={})
        proof=engine.financial(data,action,NOW)
        self.assertEqual(proof['financial_contract_version'],'fc27_dual20_d9_d2_platform_100k_v4')
        self.assertTrue(all(row['price']['delivered_k']=='100' for row in proof['prices'].values()))
        for platform in engine.PLATFORMS:
            self.assertEqual(proof['prices']['global:'+platform]['average']['platform'],platform)
            lower=deepcopy(action);lower['base_prices'][platform]=str(floors[platform]-Decimal('.01'))
            with self.assertRaisesRegex(ValueError,'margin_floor'):
                engine.financial(data,lower,NOW)

    def test_missing_platform_or_unassigned_identity_never_borrows_pooled_ratio(self):
        for missing in (True,False):
            data=platform_history(fixture()[0]);root=data['historical_discount_mix']
            if missing:del root['by_platform']['XBOX']
            else:root['source_coverage']['unknown_platform_orders']=1
            root['sha256']=f.fingerprint({k:v for k,v in root.items() if k!='sha256'})
            with self.assertRaises(ValueError):f.required_history_ratio(data,NOW,platform='XBOX',require_current=True)

    def test_platform_and_amount_hash_are_checked(self):
        data=platform_history(fixture()[0]);root=data['historical_discount_mix']
        root['by_platform']['XBOX']['platform']='PS'
        root['by_platform']['XBOX']['sha256']=f.fingerprint({k:v for k,v in root['by_platform']['XBOX'].items() if k!='sha256'})
        root['sha256']=f.fingerprint({k:v for k,v in root.items() if k!='sha256'})
        with self.assertRaisesRegex(ValueError,'platform'):f.required_history_ratio(data,NOW,platform='XBOX')

    def test_old_pooled_contract_cannot_become_live_by_relabelling_version(self):
        data=fixture(legacy=True)[0]
        with self.assertRaisesRegex(ValueError,'platform'):f.required_history_ratio(data,NOW,platform='PS',require_current=True)

    def test_independent_market_quotes_are_not_combined_into_a_console_target(self):
        data=platform_history(fixture()[0])
        data.update(region_rules=[],regional_controls=[])
        for cost in data['costs'].values():cost['cny_per_1k']='.14'
        set_console_cost(data)
        for platform,price in zip(engine.PLATFORMS,('10','12','14')):
            data['offers'][platform]['Lootbar']['usd_price']=price
        result=engine.evaluate(data,'revenue_sprint',now=NOW)
        self.assertEqual(result['status'],'READY',result['failures'])
        selected=result['selected']
        self.assertEqual(set(selected['action']['base_prices']),set(engine.PLATFORMS))
        prices=[Decimal(selected['action']['base_prices'][p]) for p in engine.PLATFORMS]
        self.assertLess(prices[0],prices[1]);self.assertLess(prices[1],prices[2])
        self.assertEqual(set(selected['market_comparison']),set(engine.PLATFORMS))

    def test_rehashed_platform_amounts_must_still_reconcile_to_population(self):
        data=platform_history(fixture()[0]);root=data['historical_discount_mix']
        root['aggregate']['net_order_usd']='1000'
        root['sha256']=f.fingerprint({k:v for k,v in root.items() if k!='sha256'})
        with self.assertRaisesRegex(ValueError,'platform_amounts'):
            f.required_history_ratio(data,NOW,platform='PS')

    def test_retired_100k_bonus_is_rejected_but_large_order_gifts_do_not_raise_floor(self):
        data=platform_history(fixture()[0]);rules=data['promotion_envelope']['packages']['PS']
        baseline=engine.required_unit_bound(data,'PS',NOW)
        for tier in rules['tiers']:
            if f.number(tier['base_k'])>=1000:tier['bonus_k']=str(f.number(tier['base_k'])*Decimal('.5'))
        envelope=data['promotion_envelope'];envelope['sha256']=f.fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
        self.assertEqual(engine.required_unit_bound(data,'PS',NOW),baseline)
        f.package_100k(rules)['bonus_k']='5'
        envelope['sha256']=f.fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
        with self.assertRaisesRegex(ValueError,'100k_bonus_retired'):
            engine.required_unit_bound(data,'PS',NOW)


if __name__=='__main__':unittest.main()

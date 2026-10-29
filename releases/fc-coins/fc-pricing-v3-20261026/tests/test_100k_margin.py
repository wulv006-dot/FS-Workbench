"""100K-only dual20 contract; saved anonymous amount/path aggregates, no live I/O."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import engine,financial
from test_dual20_sprint import source,NOW

SAVED=json.loads(Path(__file__).with_name('100k-78a225e7-aggregate.json').read_text('utf-8'))


def saved():
    data=deepcopy(SAVED['evidence'])
    regions=deepcopy(SAVED['regions'])
    for region in regions:region['history']=deepcopy(SAVED['history'])
    data.update(region_rules=[r for r in regions if r['id'] is not None],regional_controls=regions)
    return data,datetime.fromisoformat(SAVED['now'])


class HundredKMargin(unittest.TestCase):
    def test_original_global_minimum_and_previous_cent(self):
        data,now=saved()
        expected={'PS':'7.26','XBOX':'7.26','PC':'8.11'}
        cost,_=financial.common_cost(data)
        ratio=engine.history_ratio(data,now)
        for platform,total in expected.items():
            with self.subTest(platform=platform):
                rules=data['promotion_envelope']['packages'][platform]
                c=cost if platform!='PC' else data['costs'][platform]['cny_per_1k']
                floor=engine.required_unit_bound(data,platform,now)
                self.assertEqual(floor*100,Decimal(total))
                proof=financial.prove_catalog(floor,c,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio)
                self.assertEqual(proof['pricing_scope'],'100k_package_only')
                self.assertEqual(proof['purchase_k'],'100')
                self.assertEqual(proof['delivered_k'],'105')
                self.assertEqual(proof['published_packages'],1)
                self.assertFalse(proof['all_integer_custom_quantities_covered'])
                with self.assertRaisesRegex(ValueError,'margin_floor'):
                    financial.prove_catalog(floor-Decimal('.0001'),c,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio)

    def test_original_94_paths_saudi_factor_one_minimum_and_previous_cent(self):
        data,now=saved()
        self.assertEqual(len(SAVED['history']['replay_paths']),94)
        for r in data['region_rules']+data['regional_controls']:r['factor']='1'
        action=dict(base_prices=dict(console='7.30',pc='8.11'),region_coefficients={'21:PS':'1','21:XBOX':'1','21:PC':'1'})
        proof=engine.financial(data,action,now,regions=data['regional_controls'])
        self.assertEqual(proof['pricing_scope'],'100k_package_only')
        self.assertEqual(engine.required_base_bound(data,'PS',now),Decimal('7.30'))
        self.assertEqual(engine.required_base_bound(data,'XBOX',now),Decimal('7.30'))
        self.assertEqual(engine.required_base_bound(data,'PC',now),Decimal('8.11'))
        for platform in ('PS','XBOX'):
            row=proof['prices']['21:'+platform]
            self.assertGreaterEqual(Decimal(row['catalog']['minimum_estimated_average_margin_pct']),20)
            self.assertEqual(row['price']['regular_usd'],'7.30')
            previous=deepcopy(action);previous['base_prices']['console']='7.29'
            with self.assertRaisesRegex(ValueError,'margin_floor'):
                engine.financial(data,previous,now,regions=[next(r for r in data['regional_controls'] if r['platforms']==[platform])])

    def test_region_coefficient_rounding_is_exact_and_lower_cent_rejected(self):
        data,now=saved()
        region=next(r for r in data['region_rules'] if r['platforms']==['XBOX'])
        self.assertEqual(region['factor'],'0.9754')
        floor=engine.required_base_bound(data,'XBOX',now,dict(mode='daily',resources=['base:console']))
        self.assertEqual(floor,Decimal('7.48'))
        action=dict(base_prices=dict(console=str(floor),pc='8.11'),region_coefficients={'21:XBOX':region['factor']})
        self.assertTrue(engine.financial(data,action,now,regions=[region])['pass_all'])
        action['base_prices']['console']=str(floor-Decimal('.01'))
        with self.assertRaisesRegex(ValueError,'margin_floor'):engine.financial(data,action,now,regions=[region])

    def test_other_sizes_do_not_raise_hard_floor_or_claim_coverage(self):
        data,now=saved()
        rules=data['promotion_envelope']['packages']['PS']
        cost,_=financial.common_cost(data);ratio=engine.history_ratio(data,now)
        before=financial.catalog_floor(cost,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio)
        for tier in rules['tiers']:
            if tier['base_k']!='100':tier.update(bonus_k=tier['base_k'],retained_ratio='.1')
        rules.update(min_custom_k='1',max_delivered_ratio='2',minimum_package_retained_ratio='.1')
        self.assertEqual(financial.catalog_floor(cost,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio),before)
        proof=financial.prove_catalog(before,cost,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio)
        self.assertFalse(proof['all_integer_custom_quantities_covered'])

    def test_100k_gifts_and_unique_identity_remain_required(self):
        data,now=saved();rules=data['promotion_envelope']['packages']['PS']
        cost,_=financial.common_cost(data);ratio=engine.history_ratio(data,now)
        base=financial.catalog_floor(cost,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio)
        tier=financial.package_100k(rules);tier['bonus_k']='10'
        self.assertGreater(financial.catalog_floor(cost,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio),base)
        rules['tiers'].append(deepcopy(tier))
        with self.assertRaisesRegex(ValueError,'100k_package_required'):
            financial.catalog_floor(cost,data['fx']['cny_per_usd'],0,20,rules,average_ratio=ratio)

    def test_daily_and_sprint_use_same_scope(self):
        data=source(cost='.35',loot='4',item='4',bonus='5')
        for mode in ('daily','revenue_sprint'):
            result=engine.evaluate(data,mode,now=NOW)
            self.assertIsNotNone(result['selected'],result['failures'])
            self.assertEqual(result['selected']['financial_proof']['pricing_scope'],'100k_package_only')


if __name__=='__main__':unittest.main()

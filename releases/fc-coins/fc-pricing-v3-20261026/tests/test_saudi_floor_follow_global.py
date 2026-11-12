"""A binding 100K dual20 floor removes Saudi discounts, even with a real Arab quote."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import engine,financial,runtime
from fc_pricing_v3.ledger import Ledger
from test_dual20_sprint import source,NOW


def regional(data, platform='PS', factor='.9754', quote='4'):
    control=dict(id=3 if platform=='PS' else 5,region_id=21,platforms=[platform],factor=factor,resource='region:21:'+platform,verified=True,
                 price_semantics='regional_regular_multiplicative',rounding='half_up_cent',history=dict(by_platform={p:dict(basis='platform_other_promotions_excluding_region_verified') for p in engine.PLATFORMS}),scope={},expected_rule_set_sha256='a'*64)
    data['region_rules']=[control]
    data['regional_controls']=[control]
    data['arab_ut_quotes']=[dict(platform=platform,region_id=21,price_usd=quote,purchase_k='100',bonus_k='0',captured_at=NOW.isoformat(),delivery='normal',selection_verified=True,currency='USD')]
    return control


class SaudiFloorFollowGlobal(unittest.TestCase):
    def test_global_floor_with_real_arab_quote_forces_one_for_console_platforms(self):
        for platform in ('PS','XBOX'):
            data=source(loot='4',item='4',cost='.35',bonus='0')
            regional(data,platform)
            global_market=engine.competition(data,['PS','XBOX'],NOW)
            self.assertEqual(global_market['decision_type'],'floor_fallback')
            market=engine.competition(data,[platform],NOW,region=21,resolved_global=global_market,base_total=global_market['minimum_legal_base_total'])
            self.assertEqual(market['legal_coefficients'],['1'])
            self.assertEqual(market['reason'],'USER_GLOBAL_PRICING_FOLLOW_GLOBAL')
            self.assertEqual(market['regional_fallbacks'],{})

    def test_local_floor_with_competitive_global_also_forces_one(self):
        data=source(loot='10',item='11',cost='.35',bonus='0')
        regional(data,quote='4')
        global_market=engine.competition(data,['PS','XBOX'],NOW)
        self.assertEqual(global_market['decision_type'],'competitive')
        market=engine.competition(data,['PS'],NOW,region=21,resolved_global=global_market,base_total='9.50')
        self.assertEqual(market['legal_coefficients'],['1'])
        self.assertEqual(market['reason'],'USER_GLOBAL_PRICING_FOLLOW_GLOBAL')

    def test_nonbinding_region_keeps_legal_competitive_discount(self):
        data=source(loot='10',item='11',cost='.10',bonus='0')
        regional(data,quote='9')
        global_market=engine.competition(data,['PS','XBOX'],NOW)
        market=engine.competition(data,['PS'],NOW,region=21,resolved_global=global_market,base_total='10')
        self.assertEqual(market['decision_type'],'regional_follow_global')
        self.assertTrue(market['legal_coefficients'])
        self.assertEqual(market['legal_coefficients'],['1'])

    def test_missing_arab_keeps_its_original_reason(self):
        data=source(loot='4',item='4',cost='.35',bonus='0')
        regional(data);data['arab_ut_quotes']=[]
        market=engine.competition(data,['PS'],NOW,region=21,base_total='10')
        self.assertEqual(market['legal_coefficients'],['1'])
        self.assertEqual(market['reason'],'USER_GLOBAL_PRICING_FOLLOW_GLOBAL')

    def test_owned_region_candidate_and_runtime_revalidation_agree(self):
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            root=Path(folder);db=Ledger(root/'control.db');db.activate_generation('g',[])
            plan=db.create_plan('revenue_sprint',['base:PS','base:XBOX','base:PC','region:21:XBOX'],dict(base_prices=dict(PS='20',XBOX='20',PC='20'),region_coefficients={'21:XBOX':'.9754'}),ends_at=(NOW+timedelta(hours=3)).isoformat())
            db.activate_plan(plan['plan_id'])
            data=source(loot='4',item='4',cost='.35',bonus='0');regional(data,'XBOX')
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate(data)
                runtime.verify_quote(dict(evidence=data,result=result),dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
            receipt=result['decision_receipt']
            self.assertEqual(receipt['action']['region_coefficients']['21:XBOX'],'1')
            self.assertEqual(receipt['regional_market_comparison']['21:XBOX']['reason'],'USER_GLOBAL_PRICING_FOLLOW_GLOBAL')
            self.assertTrue(receipt['financial_proof']['pass_all'])
            self.assertTrue(any(s['kind']=='region' and s['key']=='21:XBOX' for s in receipt['steps']))
            invalid=deepcopy(result);tampered=invalid['decision_receipt']
            tampered['action']['region_coefficients']['21:XBOX']='.9999'
            regions=engine.proof_regions(data,tampered['before_action'],tampered['action'],promised_regions=tampered['regional_market_comparison'])
            tampered['financial_proof']=engine.financial(data,tampered['action'],NOW,regions=regions)
            tampered['sha256']=financial.fingerprint({k:v for k,v in tampered.items() if k!='sha256'})
            with self.assertRaisesRegex(ValueError,'pricing_saudi_follow_global_factor_must_be_one'):
                runtime.verify_quote(dict(evidence=data,result=invalid),dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)

    def test_base_only_plan_preserves_one_without_region_write(self):
        data=source(loot='4',item='4',cost='.35',bonus='0');regional(data,'XBOX',factor='1')
        plan=dict(mode='revenue_sprint',resources=['base:PS','base:XBOX','base:PC'],price_anchor=dict(base_prices=dict(PS='20',XBOX='20',PC='20'),region_coefficients={'21:XBOX':'1'}))
        result=engine.evaluate(data,'revenue_sprint',plan=plan,now=NOW)
        self.assertIsNotNone(result['selected'],result['failures'])
        for candidate in result['candidates']:
            self.assertEqual(candidate['action']['region_coefficients']['21:XBOX'],'1')
            self.assertFalse(any(s['kind']=='region' for s in candidate['steps']))


if __name__=='__main__':unittest.main()

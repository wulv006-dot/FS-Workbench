"""Daily ItemD2R fallback changes the actual price, with the same financial proof."""
from copy import deepcopy
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from test_dual20_sprint import source,NOW
from test_optional_competitors import missing
from fc_pricing_v3 import engine,financial,runtime,monitoring
from fc_pricing_v3.ledger import Ledger


class DailyItemTarget(unittest.TestCase):
    def test_financial_floor_within_same_public_cent_does_not_mark_target_unmet(self):
        data=source(cost='.10',bonus='5',item='8.14');missing(data,'Lootbar')
        tier=dict(base_k='100',bonus_k='5',retained_ratio='.5')
        with patch.object(engine,'package_100k',return_value=tier):
            target=engine.daily_item_target(data,['PC'],engine.daily_reference(data,engine.PLATFORMS,NOW),Decimal('17.10'))
        self.assertEqual(target['target_base_total'],'17.09')
        self.assertTrue(target['financial_floor_applied'])
        self.assertTrue(target['item_target_met'])
        self.assertIsNone(target['unmet_reason'])

    def test_unreachable_cent_inverse_cannot_claim_target_or_financial_floor(self):
        # A coarse inverse counterexample exercises the presentation guard. The
        # real financial contract separately rejects this multiplier above 1.
        data=source(cost='.10',bonus='5',item='8.11');missing(data,'Lootbar')
        tier=dict(base_k='100',bonus_k='5',retained_ratio='1.1')
        with patch.object(engine,'package_100k',return_value=tier):
            target=engine.daily_item_target(data,['PC'],engine.daily_reference(data,engine.PLATFORMS,NOW),Decimal('1'))
        self.assertEqual((target['target_public_usd'],target['target_base_total'],target['target_base_high']),('8.52','7.75','7.74'))
        self.assertFalse(target['target_public_cent_reachable']);self.assertFalse(target['item_target_met'])
        self.assertFalse(target['financial_floor_applied'])
        self.assertEqual(target['unmet_reason'],'public_cent_not_reachable')
        self.assertEqual(target['actual_minus_target_public_usd'],'0.01')
        with self.assertRaisesRegex(ValueError,'pricing_package_invalid'):financial.package_100k(dict(tiers=[tier]))

    def test_item_actual_delivered_quantity_rounding_and_first_base_cent(self):
        for price,bonus in [('8.10','0'),('8.14','0'),('8.40','5')]:
            for retained in ('1','.95','.9999'):
                with self.subTest(price=price,bonus=bonus,retained=retained):
                    data=source(cost='.10',bonus='5',item=price);missing(data,'Lootbar')
                    for row in data['reference_market']['offers']:row['bonus_k']=bonus
                    for rules in data['promotion_envelope']['packages'].values():
                        for tier in rules['tiers']:tier['retained_ratio']=retained
                    envelope=data['promotion_envelope'];envelope['sha256']=financial.fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
                    result=engine.evaluate(data,'daily',now=NOW)
                    self.assertEqual(result['status'],'READY',result['failures'])
                    selected=result['selected'];target=selected['daily_pricing']['console']
                    expected=(Decimal(price)/(100+Decimal(bonus))*105).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                    self.assertEqual(Decimal(target['target_public_usd']),expected)
                    self.assertEqual(Decimal(selected['financial_proof']['prices']['global:PS']['price']['regular_usd']),expected)
                    self.assertEqual(Decimal(target['selected_base_total']),Decimal(target['target_base_total']))
                    previous=Decimal(target['previous_target_base_cent'])*Decimal(retained)
                    self.assertLess(previous.quantize(Decimal('.01'),rounding=ROUND_HALF_UP),expected)
                    self.assertTrue(target['item_target_met'])
                    self.assertTrue(target['target_public_cent_reachable'])
                    self.assertEqual(target['actual_minus_target_public_usd'],'0.00')

    def test_console_uses_lower_item_target_and_reports_other_platform_difference(self):
        data=source(cost='.10',bonus='5',item='9');missing(data,'Lootbar',['PS','XBOX'])
        next(r for r in data['reference_market']['offers'] if r['platform']=='XBOX')['gross_usd']='8.14'
        selected=engine.evaluate(data,'daily',now=NOW)['selected'];target=selected['daily_pricing']['console']
        self.assertEqual(target['driver_platform'],'XBOX')
        self.assertEqual(Decimal(selected['action']['base_prices']['console']),Decimal('8.55'))
        self.assertEqual(target['platforms']['PS']['reference_source'],'ItemD2R')
        self.assertLess(Decimal(target['platforms']['PS']['difference_pct']),0)
        self.assertNotIn('pc',selected['daily_pricing'])
        self.assertTrue(all(Decimal(c['action']['base_prices']['pc']) in {Decimal(v) for v in ('18.40','19.20','20','20.80','21.60')} for c in engine.evaluate(data,'daily',now=NOW)['candidates']))

    def test_only_one_console_loot_gap_drives_common_price_without_relabelling_other_source(self):
        data=source(cost='.10',bonus='5',item='8.14');missing(data,'Lootbar',['XBOX'])
        selected=engine.evaluate(data,'daily',now=NOW)['selected'];target=selected['daily_pricing']['console']
        self.assertEqual(target['driver_platform'],'XBOX')
        self.assertEqual(target['platforms']['PS']['reference_source'],'Lootbar')
        self.assertEqual(selected['daily_reference']['PS']['source'],'Lootbar')
        self.assertEqual(selected['action']['base_prices']['console'],'8.55')

    def test_item_target_below_double20_uses_first_legal_price_and_keeps_region(self):
        data=source(cost='.56',bonus='5',item='8.14');missing(data,'Lootbar')
        control=dict(id=3,region_id=21,platforms=['PS'],factor='.97',resource='region:21:PS',verified=True,rounding='half_up_cent',price_semantics='regional_regular_multiplicative',history=dict(basis='pooled_other_promotions_excluding_region_verified'))
        data['region_rules']=[control];data['regional_controls']=[control]
        selected=engine.evaluate(data,'daily',now=NOW)['selected'];target=selected['daily_pricing']['console']
        self.assertEqual(Decimal(selected['action']['region_coefficients']['21:PS']),Decimal('.97'))
        self.assertTrue(target['financial_floor_applied']);self.assertFalse(target['item_target_met'])
        self.assertEqual(selected['decision_reason'],'DAILY_ITEMD2R_TARGET_BELOW_MARGIN_FLOOR')
        self.assertEqual(selected['minimum_legal_price_proof']['console']['previous_cent'],str(Decimal(target['selected_base_total'])-Decimal('.01')))
        self.assertTrue(selected['financial_proof']['pass_all'])
        self.assertIn('21:PS',selected['financial_proof']['prices'])

    def test_mixed_console_item_target_still_preserves_missing_platform_average30(self):
        for item in ('5','15'):
            data=source(cost='.35',bonus='5',item=item)
            missing(data,'Lootbar',['PS','XBOX']);missing(data,'ItemD2R',['PS'])
            selected=engine.evaluate(data,'daily',now=NOW)['selected'];target=selected['daily_pricing']['console']
            self.assertEqual(target['driver_platform'],'XBOX')
            self.assertEqual(set(selected['daily_average_target_proof']),{'PS'})
            self.assertGreaterEqual(Decimal(selected['daily_average_target_proof']['PS']['scopes']['global:PS']['estimated_average_margin_pct']),30)
            self.assertEqual(target['financial_floor_applied'],item=='5')
            if item=='15':self.assertNotIn('console',selected['minimum_legal_price_proof'])

    def test_loot_available_keeps_original_daily_candidates_and_objective(self):
        first=source(item='1');second=source(item='20')
        a=engine.evaluate(first,'daily',now=NOW);b=engine.evaluate(second,'daily',now=NOW)
        self.assertEqual([c['action'] for c in a['candidates']],[c['action'] for c in b['candidates']])
        self.assertEqual(a['selected']['action'],b['selected']['action'])
        self.assertEqual(a['selected']['daily_pricing'],{})
        self.assertEqual(a['selected']['decision_reason'],'daily_objective')

    def test_write_before_recomputes_item_target_and_one_cent_change_is_rejected(self):
        data=source(cost='.10',bonus='5',item='8.14');missing(data,'Lootbar',['XBOX'])
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            root=Path(folder);db=Ledger(root/'control.db');db.activate_generation('g',[])
            plan=db.create_plan('daily',['base:console','base:pc'],dict(base_prices=dict(console='20',pc='20'),region_coefficients={}))
            db.activate_plan(plan['plan_id'])
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate(data);quote=dict(evidence=data,result=result)
                runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
                for change in ('-.01','.01'):
                    altered=deepcopy(quote);receipt=altered['result']['decision_receipt']
                    receipt['action']['base_prices']['console']=str(Decimal(receipt['action']['base_prices']['console'])+Decimal(change))
                    receipt['financial_proof']=engine.financial(data,receipt['action'],NOW)
                    for row in altered['result']['rows']:
                        if row['platform']!='PC':row['proposal']=str(Decimal(receipt['action']['base_prices']['console'])/100)
                    receipt['sha256']=financial.fingerprint({k:v for k,v in receipt.items() if k!='sha256'})
                    with self.subTest(change=change),self.assertRaisesRegex(ValueError,'pricing_daily_item_target_price_changed'):
                        runtime.verify_quote(altered,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
                altered=deepcopy(quote);receipt=altered['result']['decision_receipt'];receipt['daily_pricing']['console']['driver_platform']='PS'
                receipt['sha256']=financial.fingerprint({k:v for k,v in receipt.items() if k!='sha256'})
                with self.assertRaisesRegex(ValueError,'pricing_daily_item_target_proof_changed'):
                    runtime.verify_quote(altered,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
                snapshot=db.get('pricing_snapshots',data['run_id'])
        observed=monitoring.source_coverage([snapshot],[plan],NOW)
        self.assertEqual(observed['status'],'verified',observed)
        for p in ('PS','XBOX'):
            self.assertEqual(observed['plans'][0]['competitive_sources'][p]['price_driver_source'],'ItemD2R')
            self.assertEqual(observed['plans'][0]['competitive_sources'][p]['price_driver_platform'],'XBOX')
        self.assertTrue(result['decision_receipt']['daily_pricing']['console']['item_target_met'])


if __name__=='__main__':unittest.main()

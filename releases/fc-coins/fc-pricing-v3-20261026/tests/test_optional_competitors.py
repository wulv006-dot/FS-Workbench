"""Current-run competitor gaps never waive financial or public-price evidence."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from test_dual20_sprint import source,NOW
from fc_pricing_v3 import engine,financial,runtime
from fc_pricing_v3.ledger import Ledger


def missing(data,source_name,platforms=engine.PLATFORMS):
    if source_name=='Lootbar':
        for p in platforms:data['offers'][p].pop('Lootbar',None)
    else:
        data['reference_market']['offers']=[r for r in data['reference_market']['offers'] if r['platform'] not in platforms]
        data['reference_market'].update(status='unavailable',reason='itemd2r_cloudflare_403',http_status=403,blocked_by='cloudflare')


class OptionalCompetitors(unittest.TestCase):
    def test_invalid_lootbar_is_not_read_again_while_rendering_receipt(self):
        data=source();data['offers']['PS']['Lootbar']['usd_price']='invalid'
        selected=engine.evaluate(data,'revenue_sprint',now=NOW)['selected']
        result=runtime.render_result(data,selected,{},'revenue_sprint')
        row=next(r for r in result['rows'] if r['platform']=='PS')
        self.assertIsNone(row['lootbar_page_usd'])
        self.assertIsNone(row['lootbar_usd_per_1k'])
        self.assertEqual(selected['market_comparison']['console']['anchors']['PS']['source'],'ItemD2R')

    def test_no_competitors_preserve_saudi_follow_global_and_region_30_proof(self):
        data=source(cost='.56',bonus='5')
        for s in ('Lootbar','ItemD2R'):missing(data,s)
        control=dict(id=3,region_id=21,platforms=['PS'],factor='.97',resource='region:21:PS',verified=True,rounding='half_up_cent',price_semantics='regional_regular_multiplicative',history=dict(basis='pooled_other_promotions_excluding_region_verified'))
        data['region_rules']=[control];data['regional_controls']=[control]
        sprint=engine.evaluate(data,'revenue_sprint',now=NOW)['selected']
        self.assertEqual(sprint['action']['region_coefficients']['21:PS'],'1')
        self.assertEqual(sprint['regional_market_comparison']['21:PS']['decision_type'],'regional_follow_global')
        plan=dict(mode='daily',resources=['base:console','base:pc'])
        daily=engine.evaluate(data,'daily',plan=plan,now=NOW)['selected']
        self.assertEqual(Decimal(daily['action']['region_coefficients']['21:PS']),Decimal('.97'))
        self.assertGreaterEqual(Decimal(daily['daily_average_target_proof']['PS']['scopes']['21:PS']['estimated_average_margin_pct']),30)
        self.assertEqual(Decimal(daily['financial_proof']['prices']['21:PS']['coefficient']),Decimal('.97'))

    def test_average30_floor_is_first_legal_cent_under_actual_package_rounding(self):
        for cost in ('.1000','.3201','.5600'):
            for retained in ('1','.9999','.95'):
                for history in ('1','.9','.83456'):
                    with self.subTest(cost=cost,retained=retained,history=history):
                        rules=deepcopy(source(bonus='5')['promotion_envelope']['packages']['PS'])
                        for tier in rules['tiers']:tier['retained_ratio']=retained
                        result=financial.catalog_floor(cost,'7','1','30',rules,average_ratio=history)*100
                        delivered_cost=Decimal(cost)/7*105
                        net=lambda base:(base*Decimal(retained)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)*Decimal(history)
                        self.assertGreaterEqual(net(result)*Decimal('.7'),delivered_cost)
                        self.assertLess(net(result-Decimal('.01'))*Decimal('.7'),delivered_cost)

    def test_sprint_both_single_and_no_current_source(self):
        for absent,chosen in [((), 'Lootbar'),(('ItemD2R',),'Lootbar'),(('Lootbar',),'ItemD2R'),(('Lootbar','ItemD2R'),None)]:
            with self.subTest(absent=absent):
                data=source(cost='.35',bonus='5')
                for s in absent:missing(data,s)
                result=engine.evaluate(data,'revenue_sprint',now=NOW)
                self.assertEqual(result['status'],'READY')
                selected=result['selected']
                for market in selected['market_comparison'].values():
                    self.assertEqual({a['source'] for a in market['anchors'].values()},{chosen})
                    self.assertEqual(set(market['competition_available'].values()),{chosen is not None})
                    if chosen is None:
                        self.assertEqual(market['targets'],{})
                        self.assertEqual(market['decision_type'],'floor_fallback')
                        self.assertEqual(market['reason'],'BOTH_COMPETITOR_QUOTES_MISSING_USE_MARGIN_FLOOR')
                if chosen is None:
                    self.assertEqual(set(selected['minimum_legal_price_proof']),{'console','pc'})
                    for positions in selected['market_position'].values():
                        self.assertTrue(all(not r['competitive_band_met'] for r in positions.values()))
                self.assertTrue(selected['financial_proof']['pass_all'])

    def test_stale_or_invalid_offers_cannot_fill_a_current_gap(self):
        for update in [dict(captured_at=(NOW-timedelta(seconds=901)).isoformat()),dict(gross_usd='0'),dict(currency='EUR'),dict(purchase_k='5')]:
            data=source();missing(data,'Lootbar')
            for row in data['reference_market']['offers']:row.update(update)
            with self.subTest(update=update):
                result=engine.evaluate(data,'revenue_sprint',now=NOW)
                self.assertEqual(result['status'],'READY')
                self.assertEqual(result['selected']['market_comparison']['console']['targets'],{})
                self.assertTrue(result['selected']['market_comparison']['console']['source_gaps'])

    def test_daily_both_missing_proves_average_30_and_previous_cent_fails(self):
        data=source(cost='.56',bonus='5')
        for s in ('Lootbar','ItemD2R'):missing(data,s)
        selected=engine.evaluate(data,'daily',now=NOW)['selected']
        self.assertEqual(selected['decision_reason'],'DAILY_MISSING_REFERENCE_AVERAGE_MARGIN_30')
        self.assertEqual(set(selected['daily_average_target_proof']),set(engine.PLATFORMS))
        self.assertEqual(selected['financial_proof']['minimum_pct'],'20')
        for p,proof in selected['daily_average_target_proof'].items():
            for row in proof['scopes'].values():
                net=Decimal(row['public_usd'])*Decimal(row['retained_ratio'])
                cost=Decimal(row['delivered_cost_usd'])
                self.assertGreaterEqual((net-cost)/net*100,30)
        for g in engine.GROUPS:
            previous=deepcopy(selected['action']);previous['base_prices'][g]=str(Decimal(previous['base_prices'][g])-Decimal('.01'))
            full=engine.financial(data,previous,NOW)
            with self.assertRaisesRegex(ValueError,'average_30'):
                engine.daily_average_target_proof(data,full,engine.GROUPS[g])
            self.assertEqual(selected['minimum_legal_price_proof'][g]['previous_cent'],previous['base_prices'][g])

    def test_console_shared_base_requires_30_only_for_missing_platform(self):
        data=source(cost='.56',bonus='5')
        for s in ('Lootbar','ItemD2R'):missing(data,s,['XBOX'])
        selected=engine.evaluate(data,'daily',now=NOW)['selected']
        self.assertEqual(set(selected['daily_average_target_proof']),{'XBOX'})
        self.assertEqual(selected['daily_reference']['PS']['source'],'Lootbar')
        self.assertIsNone(selected['daily_reference']['PS']['average_margin_target_pct'])
        self.assertIsNone(selected['daily_reference']['XBOX']['source'])
        self.assertEqual(selected['daily_reference']['PC']['source'],'Lootbar')
        self.assertEqual(set(selected['minimum_legal_price_proof']),{'console'})

    def test_hard_evidence_missing_still_blocks_with_no_competitors(self):
        for key in ('fx','historical_discount_mix','costs','promotion_envelope','storefront'):
            for mode in ('daily','revenue_sprint'):
                data=source()
                for s in ('Lootbar','ItemD2R'):missing(data,s)
                data.pop(key)
                with self.subTest(key=key,mode=mode),self.assertRaises((KeyError,ValueError)):
                    engine.evaluate(data,mode,now=NOW)

    def test_runtime_recomputes_current_sources_and_explicit_30_proof(self):
        for mode in ('daily','revenue_sprint'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
                root=Path(folder);db=Ledger(root/'control.db');db.activate_generation('g',[])
                plan=db.create_plan(mode,['base:console','base:pc'],dict(base_prices=dict(console='20',pc='20'),region_coefficients={}))
                db.activate_plan(plan['plan_id']);data=source(cost='.56',bonus='5')
                for s in ('Lootbar','ItemD2R'):missing(data,s)
                with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                    result=runtime.calculate(data)
                    quote=dict(evidence=data,result=result)
                    runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
                    if mode=='daily':
                        bad=deepcopy(quote);receipt=bad['result']['decision_receipt']
                        receipt['daily_average_target_proof']['PS']['scopes']['global:PS']['estimated_average_margin_pct']='99'
                        receipt['sha256']=financial.fingerprint({k:v for k,v in receipt.items() if k!='sha256'})
                        with self.assertRaisesRegex(ValueError,'pricing_daily_average_target_proof_changed'):
                            runtime.verify_quote(bad,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
                        lower=deepcopy(quote);receipt=lower['result']['decision_receipt']
                        receipt['action']['base_prices']['console']=str(Decimal(receipt['action']['base_prices']['console'])-Decimal('.01'))
                        receipt['financial_proof']=engine.financial(data,receipt['action'],NOW)
                        for row in lower['result']['rows']:
                            if row['platform'] in ('PS','XBOX'):row['proposal']=str(Decimal(receipt['action']['base_prices']['console'])/100)
                        receipt['sha256']=financial.fingerprint({k:v for k,v in receipt.items() if k!='sha256'})
                        with self.assertRaisesRegex(ValueError,'pricing_daily_missing_market_average_30'):
                            runtime.verify_quote(lower,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
                    # Fresh source becoming stale between calculation and execution changes the decision.
                    fresh=source(cost='.56',bonus='5')
                    for p in engine.PLATFORMS:fresh['offers'][p]['Lootbar']['checked_at']=(NOW-timedelta(seconds=899)).isoformat()
                    for row in fresh['reference_market']['offers']:row['captured_at']=(NOW-timedelta(seconds=899)).isoformat()
                    quote=dict(evidence=fresh,result=runtime.calculate(fresh))
                    with self.assertRaisesRegex(ValueError,'pricing_daily_reference_changed' if mode=='daily' else 'pricing_market_proof_changed'):
                        runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW+timedelta(seconds=2))


if __name__=='__main__':unittest.main()

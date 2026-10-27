from copy import deepcopy
from datetime import timedelta
from decimal import Decimal,ROUND_UP
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fixtures import fixture,NOW
from fc_pricing_v3 import engine,financial,runtime,api
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.legacy_simulation import dual10_financial


def source(loot='10',item='11',cost='.35',bonus='0'):
    data=fixture()[0];data['run_id']='00000000-0000-4000-8000-000000000099'
    data['region_rules']=[];data['regional_controls']=[]
    data['reference_market']=dict(offers=[])
    for p in engine.PLATFORMS:
        data['costs'][p]['cny_per_1k']=cost
        data['storefront']['rows'][p].update(bonus_k=bonus,package_usd='20.00')
        data['offers'][p]={'Lootbar':dict(usd_price=loot,base_k='100',bonus_k='0',checked_at=NOW.isoformat(),currency='USD',coupon_excluded=True)}
        data['reference_market']['offers'].append(dict(source='ItemD2R',platform=p,purchase_k='100',bonus_k='0',gross_usd=item,captured_at=NOW.isoformat(),currency='USD',coupon_excluded=True,conditional=False,delivery_method='normal'))
        rules=data['promotion_envelope']['packages'][p]
        rules['max_delivered_ratio']=str(1+Decimal(bonus)/100)
        for tier in rules['tiers']:tier['bonus_k']=str(Decimal(tier['base_k'])*Decimal(bonus)/100)
    envelope=data['promotion_envelope'];envelope['sha256']=financial.fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
    return data


class Dual20Sprint(unittest.TestCase):
    def test_single_base_path_allows_temporary_lower_price_with_full_financial_proof(self):
        data=source(loot='9.18',item='8.14',cost='.32',bonus='5')
        data['offers']['PS']['Lootbar']['bonus_k']='5'
        rule=dict(id=3,region_id=21,platforms=['PS'],factor='.9055',verified=True,price_semantics='regional_regular_multiplicative',history=dict(basis='pooled_other_promotions_excluding_region_verified'))
        data['region_rules']=[rule]
        data['regional_controls']=[dict(rule,resource='region:21:PS')]
        data['arab_ut_quotes']=[dict(platform='PS',region_id=21,price_usd='8.27',purchase_k='100',bonus_k='0',captured_at=NOW.isoformat(),delivery='normal',selection_verified=True,currency='USD')]
        before=dict(base_prices=dict(console='8.72',pc='8.80'),region_coefficients={'21:PS':'.9055'})
        after=dict(base_prices=dict(console='8.04',pc='7.89'),region_coefficients={'21:PS':'.9995'})
        markets={'console':engine.competition(data,['PS','XBOX'],NOW)}
        regional={'21:PS':engine.competition(data,['PS'],NOW,region=21,resolved_global=markets['console'],base_total='8.04')}
        def transition(a,b):engine.preserve_competitive_state(data,a,b,markets,regional)
        steps=engine.commit_path(before,after,lambda action:engine.financial(data,action,NOW,regions=[rule]),transition)
        self.assertEqual(sum(s['kind']=='base' for s in steps),1)
        self.assertEqual(len(steps),2)
        self.assertEqual(steps[-1]['intermediate'],after)
        for step in steps:self.assertTrue(engine.financial(data,step['intermediate'],NOW,regions=[rule])['pass_all'])
        too_expensive=deepcopy(before);too_expensive['region_coefficients']['21:PS']='1'
        with self.assertRaisesRegex(ValueError,'competitive_commitment_lost'):transition(before,too_expensive)

    def test_all_five_strategies_ignore_retired_zero_and_exhausted_budgets(self):
        data=source(cost='.10');data.update(backlog_k='0',capacity_k_per_block='9999999',
            demand_model=dict(groups={g:dict(orders_per_block='1',reference_regular_usd='20',target_revenue_per_order_usd='20',delivered_k_per_order='100') for g in engine.GROUPS}))
        anchor=dict(base_prices=dict(console='20',pc='20'),region_coefficients={})
        for mode in engine.POLICIES:
            with self.subTest(mode=mode):
                plan=dict(mode=mode,resources=['base:console','base:pc'],price_anchor=anchor)
                before=engine.evaluate(data,mode,now=NOW,plan=plan)
                plan.update(daily_budget='0',total_budget='0')
                old=deepcopy(data);old['budget_snapshot']=dict(groups={g:dict(concession='99999999',negative_contribution='99999999') for g in engine.GROUPS})
                after=engine.evaluate(old,mode,now=NOW,plan=plan)
                self.assertIsNotNone(before['selected'],before['failures'])
                self.assertEqual([c['action_sha256'] for c in before['candidates']],[c['action_sha256'] for c in after['candidates']])
                self.assertFalse(after['selected']['score']['opportunity_cost']['enforced'])

    def test_old_policy_can_be_read_for_migration_but_cannot_write(self):
        import automation_policy as policy
        stored=policy.initial_policy();stored.update(minimum_gross_margin_pct='10',system_enabled=True,mode='auto')
        self.assertEqual(policy.normalize_policy(stored,stored=True)['minimum_gross_margin_pct'],'10')
        quote=dict(automation_policy_revision=stored['revision'],result=dict(minimum_gross_margin_pct='10'))
        with self.assertRaisesRegex(ValueError,'minimum_margin_invalid'):policy.check_write(stored,quote,['PS','XBOX','PC'],automatic=True)

    def test_T21_migration_removes_limits_keeps_historical_records_deadline_and_draw(self):
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            db=Ledger(Path(folder)/'control.db');db.activate_generation('g',[])
            plan=db.create_plan('revenue_sprint',['base:console','base:pc'],dict(base_prices={'console':'20','pc':'20'},region_coefficients={}),ends_at=(NOW+timedelta(hours=6)).isoformat(),daily_budget='100')
            db.activate_plan(plan['plan_id'])
            plan.update(state='SUSPENDED',daily_budget='100',total_budget='25');plan.pop('financial_contract_version');plan['parameters']={'preferred_undercut_pct':'1'}
            db.put('pricing_plans',plan['plan_id'],plan)
            block=int(NOW.timestamp())//21600
            old=dict(assignment_id='original-allocation',action={'old':'action'},seed='original-seed',draw=.41,block=block)
            db.put('experiment_assignments',financial.fingerprint([plan['plan_id'],1,block]),old)
            with db.transaction() as conn:db.reserve('old-operation',{'console':{'concession':'10','negative_contribution':'0'}},plan,NOW,conn,assignment_id=old['assignment_id'])
            migrated=db.migrate_financial_contract(plan['plan_id'],1,'wulv')
            self.assertEqual(migrated['state'],'SUSPENDED');self.assertEqual(migrated['revision'],2)
            self.assertEqual(migrated['ends_at'],plan['ends_at'])
            self.assertNotIn('daily_budget',migrated);self.assertNotIn('total_budget',migrated)
            self.assertEqual(migrated['budget_policy'],'none')
            candidate=dict(action={'new':'action'},score={'objective':'1'})
            allocation=db.assignment(migrated,[candidate],now=NOW)
            self.assertEqual((allocation['seed'],allocation['draw']),(old['seed'],old['draw']))
            self.assertEqual(db.get('reservations','old-operation')['groups']['console']['concession'],'10')
            self.assertEqual(db.migrate_financial_contract(plan['plan_id'],1,'wulv')['revision'],2)
            self.assertEqual(db.get('experiment_assignments',financial.fingerprint([plan['plan_id'],1,block])),old)

    def test_no_budget_cap_or_reservation_blocks_new_execution(self):
        data=source(cost='.56');data['budget_snapshot']={'groups':{'console':{'concession':'999999'}}}
        plan=dict(mode='revenue_sprint',price_anchor={'base_prices':{'console':'20','pc':'20'}},resources=['base:console','base:pc'],daily_budget='0',total_budget='0')
        result=engine.evaluate(data,'revenue_sprint',plan=plan,now=NOW)
        self.assertEqual(result['status'],'READY')
        self.assertFalse(any('budget' in r['code'] for r in result['failures']))
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            db=Ledger(Path(folder)/'control.db');db.activate_generation('g',[])
            created=db.create_plan('daily',['base:pc'],plan['price_anchor']);created=db.activate_plan(created['plan_id'])
            bundle=dict(decision_bundle_id='new-operation',mutable_resources=['base:pc'],resources=['base:pc'],valid_until=(NOW+timedelta(minutes=10)).isoformat(),steps=[],budget_reservation={'pc':{'concession':'999999'}})
            with patch.object(db,'reserve',side_effect=AssertionError('retired_budget_reservation_called')):db.prepare(created,bundle,now=NOW)
            self.assertEqual(db.all('reservations'),[])

    def test_T32_migration_does_not_clear_unknown_operation(self):
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            db=Ledger(Path(folder)/'control.db');db.activate_generation('g',[])
            plan=db.create_plan('daily',['base:pc'],dict(base_prices={'console':'20','pc':'20'},region_coefficients={}))
            plan.pop('financial_contract_version');plan['state']='SUSPENDED';db.put('pricing_plans',plan['plan_id'],plan)
            db.put('operations','original',dict(operation_id='original',status='UNKNOWN',resources=['base:pc']))
            with self.assertRaisesRegex(ValueError,'pricing_resource_unresolved'):db.migrate_financial_contract(plan['plan_id'],1,'wulv')
            self.assertEqual(db.get('operations','original')['status'],'UNKNOWN')
            self.assertEqual(db.get('pricing_plans',plan['plan_id'])['revision'],1)

    def test_T01_T02_defaults_and_versioned_parameter_limits(self):
        self.assertEqual(engine.POLICIES['revenue_sprint']['offsets'],(-5,-6.25,-7.5,-8.75,-10))
        self.assertEqual(engine.sprint_parameters()['preferred_undercut_pct'],'7.5')
        for invalid in ('4.9','10.1','1'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):engine.sprint_parameters(dict(parameters={'preferred_undercut_pct':invalid}))

    def test_T03_T13_candidates_start_at_undiscounted_anchor_and_render_actual_gifts(self):
        data=source(item='10',bonus='5')
        market=engine.competition(data,['PS','XBOX'],NOW)
        self.assertEqual(market['targets']['PS']['undiscounted_comparable_public_total'],'10.5')
        result=engine.evaluate(data,'revenue_sprint',now=NOW)
        self.assertEqual(result['status'],'READY')
        for candidate in result['candidates']:
            for p in engine.PLATFORMS:
                actual=Decimal(candidate['financial_proof']['prices']['global:'+p]['price']['delivered_unit_100k'])
                self.assertTrue(Decimal('9')<=actual<=Decimal('9.5'))
        data=source(loot='9',item='9',bonus='5')
        target=engine.competition(data,['PS'],NOW)['targets']['PS']
        self.assertEqual((target['public_total_low'],target['public_total_high']),('8.51','8.97'))

    def test_T04_T05_lowest_valid_source_is_normal_default(self):
        for loot,item,chosen in [('10','9','ItemD2R'),('9','10','Lootbar')]:
            self.assertEqual(engine.competition(source(loot,item),['PS'],NOW)['anchors']['PS']['source'],chosen)

    def test_T06_T07_T19_common_cost_basis_and_hysteresis(self):
        data=source(loot='10',item='11',cost='.385')
        old=source(loot='10',item='10',cost='.35');at=NOW-timedelta(hours=1)
        for p in engine.PLATFORMS:
            quotes={s:engine.market_quote(old,p,s,NOW) for s in ('Lootbar','ItemD2R')}
            data.setdefault('sprint_anchor_context',{})[p]=dict(baseline=dict(snapshot_id='one-common-basis',created_at=at.isoformat(),quotes=quotes,cost_usd_per_k='.05'))
        selected=engine.competition(data,['PS'],NOW)['anchors']['PS']
        self.assertEqual(selected['reason'],'ITEMD2R_COST_RESPONSE')
        data['sprint_anchor_context']['PS']['previous']=selected
        data['offers']['PS']['Lootbar']['usd_price']='10.8'
        self.assertEqual(engine.competition(data,['PS'],NOW)['anchors']['PS']['source'],'Lootbar')
        data['offers']['PS']['Lootbar']['usd_price']='10'
        data['costs']['PS']['cny_per_1k']=data['costs']['XBOX']['cny_per_1k']='.35'
        self.assertEqual(engine.competition(data,['PS'],NOW)['anchors']['PS']['source'],'Lootbar')

    def test_T08_current_cost_conflict_uses_itemd2r_without_trend_claim(self):
        market=engine.competition(source(loot='10',item='14',cost='.56'),['PS','XBOX'],NOW)
        self.assertEqual(market['decision_type'],'competitive')
        self.assertEqual(market['anchors']['PS']['reason'],'ITEMD2R_CURRENT_COST_CONFLICT')
        self.assertNotIn('baseline',market['anchors']['PS'])

    def test_T10_T12_T25_T27_T28_minimum_floor_keeps_full_dual20_proof(self):
        data=source(loot='10',item='11',cost='.56')
        result=engine.evaluate(data,'revenue_sprint',now=NOW)
        self.assertEqual(result['status'],'READY')
        selected=result['selected'];self.assertEqual(selected['decision_type'],'floor_fallback')
        self.assertEqual(selected['financial_proof']['minimum_pct'],'20')
        self.assertEqual(set(selected['minimum_legal_price_proof']),{'console','pc'})
        for row in selected['market_position']['console'].values():
            self.assertFalse(row['competitive_band_met']);self.assertGreater(Decimal(row['difference_pct']['Lootbar']),0)
        with self.assertRaises(ValueError):financial.prove_price('.115','.7','7','100','100','1')
        self.assertGreater(Decimal(dual10_financial.prove_price('.115','.7','7','100','100','1')['procurement_margin_pct']),10)
        self.assertEqual((Decimal(8)/(Decimal('.8')*Decimal('.9'))).quantize(Decimal('.01'),rounding=ROUND_UP),Decimal('11.12'))

    def test_T11_financial_floor_inside_market_band_is_still_competitive(self):
        data=source(loot='10',item='10',cost='.455')
        result=engine.evaluate(data,'revenue_sprint',now=NOW)
        self.assertEqual(result['status'],'READY')
        self.assertTrue(all(c['decision_type']=='competitive' for c in result['candidates']))
        self.assertTrue(all(Decimal('9')<=Decimal(c['action']['base_prices']['console'])<=Decimal('9.5') for c in result['candidates']))

    def test_uncreated_unchanged_default_region_does_not_inflate_global_floor_without_normal_quote(self):
        data=source(cost='.56');base=engine.required_base_bound(data,'PC',NOW)
        control=dict(id=None,region_id=21,platforms=['PC'],factor='1',resource='region:21:PC',verified=True,
            price_semantics='regional_regular_multiplicative',history=dict(basis='pooled_other_promotions_excluding_region_verified'))
        data['regional_controls']=[control]
        self.assertEqual(engine.required_base_bound(data,'PC',NOW),base)
        result=engine.evaluate(data,'revenue_sprint',now=NOW)
        self.assertEqual(result['status'],'READY')
        self.assertEqual(result['selected']['action']['region_coefficients']['21:PC'],'1')
        self.assertTrue(result['selected']['financial_proof']['pass_all'])
        self.assertEqual(result['selected']['regional_market_comparison']['21:PC']['decision_type'],'regional_follow_global')
        self.assertEqual(result['selected']['financial_proof']['prices']['21:PC']['catalog']['extra_region_rounding_bound_per_k'],'0')
        control['id']=99
        self.assertGreater(engine.required_base_bound(data,'PC',NOW),base)

    def test_T15_T31_missing_or_stale_source_is_never_a_floor_fallback(self):
        for change in ('missing','stale'):
            data=source(cost='.56')
            if change=='missing':data['reference_market']['offers']=[]
            else:
                for row in data['reference_market']['offers']:row['captured_at']=(NOW-timedelta(seconds=901)).isoformat()
            result=engine.evaluate(data,'revenue_sprint',now=NOW)
            self.assertTrue(result['failures'])
            self.assertTrue(all(c['decision_type']!='floor_fallback' for c in result['candidates']))
            self.assertTrue(all(not c['steps'] for c in result['candidates']))

    def test_T17_uk_real_factor_remains_in_financial_bound_until_exit(self):
        data=source(cost='.56')
        uk=dict(id=1,region_id=39,platforms=list(engine.PLATFORMS),factor='.9100',verified=True,price_semantics='regional_regular_multiplicative',history={'basis':'pooled_other_promotions_excluding_region_verified'})
        data['region_rules']=[uk]
        before=engine.required_base_bound(data,'PS',NOW)
        data['region_rules']=[]
        self.assertGreater(before,engine.required_base_bound(data,'PS',NOW))

    def test_T18_saudi_does_not_reintroduce_excluded_lootbar_and_PC_gap_is_real(self):
        data=source(loot='10',item='14',cost='.56')
        global_market=engine.competition(data,['PS','XBOX'],NOW)
        data['arab_ut_quotes']=[dict(platform='PS',region_id=21,price_usd='13',purchase_k='100',bonus_k='0',captured_at=NOW.isoformat(),delivery='normal',selection_verified=True,currency='USD')]
        local=engine.competition(data,['PS'],NOW,region=21,resolved_global=global_market)
        self.assertEqual(Decimal(local['targets']['PS']['anchor_unit_100k']),Decimal('13'))
        missing=engine.competition(data,['PC'],NOW,region=21,base_total='10')
        self.assertEqual(missing['decision_type'],'regional_follow_global')
        self.assertEqual(missing['legal_coefficients'],['1'])
        self.assertEqual(missing['regional_fallbacks']['PC']['reason'],'pricing_required_market_missing:ArabUT:PC')
        self.assertFalse(any(q['source']=='ArabUT' for q in missing['quotes']))

    def test_item_uses_actual_100k_without_lootbar_gift_assumption(self):
        data=source(loot='10',item='9')
        data['offers']['PS']['Lootbar']['bonus_k']='5'
        quote=engine.market_quote(data,'PS','ItemD2R',NOW)
        self.assertEqual((quote['bonus_k'],quote['delivered_k']),('0','100'))
        self.assertEqual(Decimal(quote['unit_100k']),Decimal('9'))
        self.assertNotIn('gift_equivalence_assumed',quote)
        self.assertEqual(data['reference_market']['offers'][0]['bonus_k'],'0')

    def test_stale_saudi_quote_follows_global_but_missing_global_quote_still_blocks(self):
        data=source();data['arab_ut_quotes']=[dict(platform='PS',region_id=21,price_usd='8',purchase_k='100',bonus_k='0',captured_at=(NOW-timedelta(minutes=16)).isoformat(),delivery='normal',selection_verified=True,currency='USD')]
        local=engine.competition(data,['PS'],NOW,region=21,base_total='9')
        self.assertEqual(local['decision_type'],'regional_follow_global')
        self.assertEqual(local['legal_coefficients'],['1'])
        data['reference_market']['offers']=[]
        with self.assertRaisesRegex(ValueError,'pricing_required_market_missing:ItemD2R:PS'):
            engine.competition(data,['PS'],NOW,region=21,base_total='9')

    def test_price_basis_uses_original_catalog_gift_pool_and_actual_history(self):
        data=source(bonus='5')
        basis=engine.price_basis(data,NOW)
        for platform,row in basis['rows'].items():
            self.assertEqual(Decimal(row['delivered_k']),105)
            self.assertEqual(Decimal(row['package_cost_usd']),105*Decimal(row['cost_usd_per_1k']))
            self.assertGreaterEqual(Decimal(row['average_floor_usd']),Decimal(row['regular_floor_usd']))
            self.assertNotIn('current_regular_margin_pct',row)
            self.assertEqual(Decimal(row['regular_floor_usd']),engine.catalog_floor(row['cost_cny_per_1k'],data['fx']['cny_per_usd'],engine.envelope_ratio(data['promotion_envelope'],NOW),engine.HARD_MARGIN,data['promotion_envelope']['packages'][platform])*100)
        self.assertFalse(basis['execution_authorized'])

    def test_missing_saudi_follow_global_survives_runtime_revalidation_and_public_projection(self):
        with tempfile.TemporaryDirectory() as folder,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            root=Path(folder);db=Ledger(root/'control.db');db.activate_generation('g',[])
            plan=db.create_plan('revenue_sprint',['base:console','base:pc','region:21:PC','region:21:PS'],dict(base_prices=dict(console='20',pc='20'),region_coefficients={'21:PC':'1','21:PS':'.91'}),ends_at=(NOW+timedelta(hours=3)).isoformat())
            db.activate_plan(plan['plan_id']);data=source(cost='.56',bonus='5')
            for platform in engine.PLATFORMS:data['offers'][platform]['Lootbar']['bonus_k']='5'
            data['regional_controls']=[dict(id=None,region_id=21,platforms=['PC'],factor='1',resource='region:21:PC',verified=True,price_semantics='regional_regular_multiplicative',history=dict(basis='pooled_other_promotions_excluding_region_verified'),scope={},expected_rule_set_sha256='a'*64)]
            data['regional_controls'].append(dict(data['regional_controls'][0],id=3,platforms=['PS'],factor='.91',resource='region:21:PS'))
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate(data)
                runtime.verify_quote(dict(evidence=data,result=result),dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
            self.assertEqual(result['decision_receipt']['action']['region_coefficients']['21:PC'],'1')
            self.assertEqual(result['decision_receipt']['action']['region_coefficients']['21:PS'],'1')
            self.assertTrue(any(s['kind']=='region' and s['key']=='21:PS' for s in result['decision_receipt']['steps']))
            with patch.object(api,'ledger',return_value=db):market=api.read('market')
            self.assertEqual(market['saudi_missing_price_policy'],'follow_global')
            self.assertEqual(market['price_basis']['status'],'available')
            self.assertNotIn('gift_equivalence_assumed',market['reference']['offers'][0])
            self.assertEqual(market['reference']['offers'][0]['bonus_k'],'0')
            self.assertFalse(market['price_basis']['execution_authorized'])

    def test_T20_T24_fallback_cannot_be_changed_into_an_arbitrary_higher_price(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db');data=source(cost='.56')
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',Path(folder)),patch.object(runtime,'clock',return_value=NOW):result=runtime.calculate(data)
            quote=dict(evidence=data,result=result)
            with patch.object(runtime,'ledger',return_value=db):runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
            with self.assertRaisesRegex(ValueError,'pricing_margin_contract_changed'):runtime.verify_quote(quote,dict(minimum_gross_margin_pct='10'),list(engine.PLATFORMS),now=NOW)
            invalid=deepcopy(quote);receipt=invalid['result']['decision_receipt'];receipt['action']['base_prices']['console']=str(Decimal(receipt['action']['base_prices']['console'])+1)
            receipt['financial_proof']=engine.financial(data,receipt['action'],NOW)
            for row in invalid['result']['rows']:
                if row['platform']!='PC':row['proposal']=format(Decimal(receipt['action']['base_prices']['console'])/100,'.4f')
            receipt['sha256']=financial.fingerprint({k:v for k,v in receipt.items() if k!='sha256'})
            with self.assertRaisesRegex(ValueError,'pricing_fallback_not_minimum_legal_price'):
                runtime.verify_quote(invalid,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)


if __name__=='__main__':unittest.main()

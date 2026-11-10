"""Three native platforms keep separate amount weights and replay/cache evidence."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import json,sys,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import business_source as business,selective_sources as selective,sources
from fc_pricing_v3.financial import fingerprint

NOW=datetime(2026,11,10,12,tzinfo=timezone.utc)
PERIOD={'start':'2026-11-01','end':'2026-11-08'}

def cohort():
    selected={};orders={}
    for key,platform,net,discount,percent in [('private-ps','PS','90','10',90),
        ('private-ps-small','PS','1','1',50),('private-xbox','XBOX','80','20',80),('private-pc','PC','95','5',95)]:
        selected[key]=(dict(salesUsd=net,coupons=[]),dict(discount_usd=discount))
        orders[key]=dict(aid={'PS':21587,'XBOX':21585,'PC':21589}[platform],
            amount_usd_format=net,before_discount=str(Decimal(net)+Decimal(discount)),
            discount=percent,points=0,is_region_price=0,discount_code='private-code')
    orders['private-xbox'].update(is_region_price=1,region_price_factor='.9',region_price_lang_region_id=21)
    proof=dict(status='complete',period=PERIOD,ES_complete=True,missing_product_identity=0,
        canonical_archive_sha256='a'*64,ES_source_sha256='b'*64)
    return selected,orders,proof

def cache():
    selected,orders,proof=cohort()
    with patch.object(business,'_period_population',return_value=(selected,proof)), \
         patch.object(business,'_live_traces',return_value=(orders,{},{})), \
         patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
        result,_=business.build_shared_history_cache(None,None,{},[],'source',NOW,used_templates_only=True)
    return result

class PlatformHistorySources(unittest.TestCase):
    def test_mix_uses_own_native_platform_amounts_and_root_has_no_ratio(self):
        selected,orders,proof=cohort()
        result=business.historical_mix(selected,proof,orders=orders,history_window_contract=selective.HISTORY_WINDOW_CONTRACT)
        self.assertEqual(result['platform_contract'],'fc27_history_platform_v1')
        self.assertNotIn('retained_ratio',result)
        expected={'PS':('91','11','102'), 'XBOX':('80','20','100'), 'PC':('95','5','100')}
        for platform,(net,discount,gross) in expected.items():
            child=result['by_platform'][platform]
            self.assertEqual((child['net_order_usd'],child['actual_discount_usd'],child['undiscounted_order_usd']),(net,discount,gross))
            self.assertEqual(Decimal(child['retained_ratio']),Decimal(net)/Decimal(gross))
            self.assertEqual(child['platform'],platform)
            self.assertEqual(child['sha256'],fingerprint({k:v for k,v in child.items() if k!='sha256'}))
        self.assertEqual(result['aggregate']['net_order_usd'],'266')
        self.assertEqual(result['source_coverage']['unknown_platform_orders'],0)
        self.assertEqual(result['sha256'],fingerprint({k:v for k,v in result.items() if k!='sha256'}))

    def test_unknown_identity_and_missing_amount_never_become_complete_or_pooled(self):
        selected,orders,proof=cohort()
        orders['private-xbox']={'content':'ambiguous unknown'}
        selected['private-ps'][1]['discount_usd']=None
        result=business.historical_mix(selected,proof,orders=orders)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['source_coverage']['unknown_platform_orders'],1)
        self.assertEqual(result['by_platform']['PS']['status'],'partial')
        xbox=result['by_platform']['XBOX'];self.assertEqual(xbox['status'],'unavailable')
        self.assertIsNone(xbox['retained_ratio']);self.assertIsNone(xbox['net_order_usd'])
        with self.assertRaisesRegex(ValueError,'platform_identity_required'):business.historical_mix(selected,proof)

    def test_cache_seals_separate_scenarios_replay_and_region_layers_without_private_ids(self):
        value=cache();mix=value['historical_discount_mix']
        self.assertEqual(value['version'],'fc27-selective-source-platform-100k-v3')
        self.assertEqual(value['package_scope'],'100k_purchased_delivered_100k')
        self.assertEqual(value['financial_contract_version'],selective._math.FINANCIAL_CONTRACT_VERSION)
        self.assertEqual(set(value['promotion_scenarios']['by_platform']),{'PS','XBOX','PC'})
        for p in ('PS','XBOX','PC'):
            replay=value['original_history_replay']['by_platform'][p]
            self.assertEqual(replay['original_mix_sha256'],mix['by_platform'][p]['sha256'])
            self.assertEqual(sum(Decimal(s['weight_usd']) for s in value['promotion_scenarios']['by_platform'][p]),Decimal(mix['by_platform'][p]['undiscounted_order_usd']))
        self.assertIn('21',value['original_history_replay']['by_platform']['XBOX']['region_layers'])
        self.assertNotIn('21',value['original_history_replay']['by_platform']['PS']['region_layers'])
        self.assertNotIn('private-',json.dumps(value))
        self.assertNotIn('paths',value['original_history_replay'])

    def test_cross_platform_weight_or_child_hash_change_is_rejected(self):
        value=cache();scenarios=deepcopy(value['promotion_scenarios'])
        scenarios['by_platform']['PS'][0]['weight_usd']='1'
        with self.assertRaisesRegex(ValueError,'scenario_weight'):
            selective.seal_history_cache(value['historical_discount_mix'],value['original_history_replay'],scenarios,{},'source',NOW)
        value['historical_discount_mix']['by_platform']['PS']['retained_ratio']='1'
        value['cache_sha256']=fingerprint({k:v for k,v in value.items() if k!='cache_sha256'})
        with self.assertRaises(ValueError):selective.checked_history_cache(value,'source',NOW)

    def test_previous_105k_scope_cache_is_rebuilt_and_never_retagged_as_current(self):
        value=cache();value['financial_contract_version']='fc27_dual20_d9_d2_platform_v3'
        value['package_scope']='100k_purchased_plus_5k'
        value['cache_sha256']=fingerprint({k:v for k,v in value.items() if k!='cache_sha256'})
        with self.assertRaisesRegex(ValueError,'financial_scope'):
            selective.checked_history_cache(value,'source',NOW)

    def test_current_hard_source_rejects_retired_100k_gift_without_catalog_gate_on_larger_gifts(self):
        from fixtures import fixture,NOW as captured
        value=fixture()[0];value['source_plan']=selective.source_plan('daily')
        self.assertTrue(selective.validate_current_hard_evidence(value,captured))
        envelope=value['promotion_envelope']
        for rules in envelope['packages'].values():
            for tier in rules['tiers']:
                if Decimal(tier['base_k'])>=1000:tier['bonus_k']=tier['base_k']
            rules['max_delivered_ratio']='2'
        envelope['sha256']=fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
        self.assertTrue(selective.validate_current_hard_evidence(value,captured))
        for platform in ('PS','XBOX','PC'):
            rules=value['promotion_envelope']['packages'][platform]
            next(t for t in rules['tiers'] if Decimal(t['base_k'])==100)['bonus_k']='5'
        envelope['sha256']=fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')})
        with self.assertRaisesRegex(ValueError,'100k_bonus_retired'):
            selective.validate_current_hard_evidence(value,captured)

    def test_old_cache_rebuilds_through_original_path_once_without_pooled_fallback(self):
        current=cache();old=deepcopy(current);old['version']='fc27-selective-source-v1'
        old['cache_sha256']=fingerprint({k:v for k,v in old.items() if k!='cache_sha256'})
        with patch.object(business,'selective_history_signature',return_value='source'), \
             patch.object(business,'build_shared_history_cache',return_value=(current,{})) as build, \
             patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            result=business.collect_selective_business(None,None,{},[],active_mode='daily',history_cache=old,current_templates={},now=NOW)
        build.assert_called_once()
        self.assertEqual(result['private_updates']['history_cache'],current)
        self.assertNotIn('retained_ratio',result['context']['historical_discount_mix'])

    def test_current_coupon_projection_changes_only_own_platform_paths(self):
        value=cache()
        value['promotion_scenarios']['by_platform']['XBOX'][0].update(code_retained_ratio='1',coupon_template_ids=['template'])
        value['cache_sha256']=fingerprint({k:v for k,v in value.items() if k!='cache_sha256'})
        terms={'template':dict(_current_active=True,mode_type=2,reduce=80,attain=0,max_reduce=5,is_open=0)}
        first=selective.project_cached_history(value,terms,NOW)
        terms['template']['max_reduce']=2
        second=selective.project_cached_history(value,terms,NOW)
        self.assertEqual(first['by_platform']['PS']['source_sha256'],second['by_platform']['PS']['source_sha256'])
        self.assertNotEqual(first['by_platform']['XBOX']['source_sha256'],second['by_platform']['XBOX']['source_sha256'])
        self.assertEqual(second['by_platform']['XBOX']['region_layers']['21']['paths'][0]['promotion_path']['cap_usd'],'2')
        self.assertNotIn('paths',second)

    def test_regional_source_preserves_native_platform_histories_instead_of_copying_ps(self):
        replay=cache()['original_history_replay']
        result=sources._regional_history(replay,21,['PS','XBOX'])
        self.assertEqual(set(result['by_platform']),{'PS','XBOX'})
        self.assertEqual(result['by_platform']['XBOX']['source_scope'],'actual_region_21')
        self.assertNotEqual(result['by_platform']['PS']['replay_paths'],result['by_platform']['XBOX']['replay_paths'])

    def test_projection_hash_covers_platforms_but_not_refresh_time(self):
        value=cache()
        first=selective.project_cached_history(value,{},NOW)
        later=selective.project_cached_history(value,{},NOW+timedelta(hours=1))
        self.assertRegex(first['sha256'],r'^[a-f0-9]{64}$')
        self.assertEqual(first['sha256'],later['sha256'])

    def test_real_projection_hash_ignores_nonfinancial_rollups_but_covers_financial_inputs(self):
        value=cache();first=selective.project_cached_history(value,{},NOW)
        updated=deepcopy(value);updated['daily_rollups']['closed_month']={'net_paid_usd':'123'}
        updated['created_at']=(NOW+timedelta(hours=1)).isoformat()
        updated['cache_sha256']=fingerprint({k:v for k,v in updated.items() if k!='cache_sha256'})
        self.assertEqual(first['sha256'],selective.project_cached_history(updated,{},NOW)['sha256'])
        for field in ('mix','replay','scenario'):
            changed=deepcopy(value)
            if field=='mix':changed['historical_discount_mix']['by_platform']['PS']['sha256']='different-mix'
            elif field=='replay':changed['original_history_replay']['by_platform']['PS']['source_sha256']='different-source'
            else:changed['promotion_scenarios']['by_platform']['PS'][0]['code_retained_ratio']='.8'
            self.assertNotEqual(first['sha256'],selective.project_cached_history(changed,{},NOW)['sha256'],field)

    def test_demand_snapshot_uses_own_platform_counts_and_public_reference(self):
        selected,orders,proof=cohort()
        for order in orders.values():order['is_region_price']=0
        public=dict(rows={p:dict(package_usd=v) for p,v in [('PS','10'),('XBOX','12'),('PC','8')]})
        result=business.demand_snapshot(selected,orders,public,proof)
        self.assertEqual(set(result['groups']),{'PS','XBOX','PC'})
        self.assertEqual(result['groups']['PS']['reference_regular_usd'],'10')
        self.assertEqual(result['groups']['XBOX']['reference_regular_usd'],'12')
        self.assertEqual(Decimal(result['groups']['PS']['observed_orders_per_block']),Decimal(2)/32)
        self.assertEqual(Decimal(result['groups']['XBOX']['observed_orders_per_block']),Decimal(1)/32)

    def test_native_window_binding_does_not_merge_xbox_into_ps_and_decodes_old_window_explicitly(self):
        from test_business_source import BusinessSourceTest
        now,ps,old=BusinessSourceTest().window_fixture()
        window=deepcopy(old);window.update(platforms=['PS','XBOX','PC'],mutable_resources=['base:PS','base:XBOX','base:PC'])
        window['action']['base_prices']={'PS':'8.68','XBOX':'12','PC':'6'}
        window['budget_reference']['base_prices']={'PS':'10','XBOX':'13','PC':'7'}
        for p in ('XBOX','PC'):window['catalog'][p]=deepcopy(window['catalog']['PS'])
        xbox=dict(ps,order_no='private-xbox-live',aid=21585,before_discount='12',amount_usd_format='12')
        result=business.bind_price_windows([ps,xbox],[window],now)
        self.assertEqual({r['platform']:r['group'] for r in result['actual_outcomes']},{'PS':'PS','XBOX':'XBOX'})
        training={r['price_group']:r for r in result['training_observations']}
        self.assertEqual(set(training),{'PS','XBOX','PC'})
        self.assertEqual((training['PS']['paid_orders'],training['XBOX']['paid_orders'],training['PC']['paid_orders']),(1,1,0))
        historical=business.bind_price_windows([ps],[old],now)
        self.assertEqual(historical['actual_outcomes'][0]['group'],'console')

    def test_old_pooled_demand_model_is_not_relabelled_as_native(self):
        prior=cache();prior['daily_rollups']['demand_model']={'groups':{'console':{'orders_per_block':'999'},'pc':{'orders_per_block':'888'}}}
        prior['cache_sha256']=fingerprint({k:v for k,v in prior.items() if k!='cache_sha256'})
        selected,orders,proof=cohort()
        with patch.object(business,'_period_population',return_value=(selected,proof)),patch.object(business,'_live_traces',return_value=(orders,{},{})),patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            value,_=business.build_shared_history_cache(None,None,{},[],'source',NOW,prior_cache=prior)
        self.assertEqual(value['daily_rollups']['demand_model']['groups'],{})
        self.assertEqual(value['daily_rollups']['legacy_demand_model'],prior['daily_rollups']['demand_model'])
        with patch.object(business,'_period_population',return_value=(selected,proof)),patch.object(business,'_live_traces',return_value=(orders,{},{})),patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            next_value,_=business.build_shared_history_cache(None,None,{},[],'next-source',NOW,prior_cache=value)
        self.assertEqual(next_value['daily_rollups']['legacy_demand_model'],prior['daily_rollups']['demand_model'])

    def test_native_regional_outcome_keeps_native_group_and_separate_price_group(self):
        from test_business_source import BusinessSourceTest
        now,order,window=BusinessSourceTest().window_fixture()
        window['mutable_resources']=['base:PS','region:21:PS']
        window['action']=dict(base_prices={'PS':'8.68','XBOX':'12','PC':'6'},region_coefficients={'21:PS':'.9'})
        window['budget_reference']=dict(base_prices={'PS':'10','XBOX':'13','PC':'7'},region_coefficients={'21:PS':'.9'})
        order.update(is_region_price=1,region_price_lang_region_id=21,region_price_factor='.9',before_discount='7.81',amount_usd_format='$7.81')
        result=business.bind_price_windows([order],[window],now)
        self.assertEqual(result['actual_outcomes'][0]['group'],'PS')
        self.assertEqual(result['actual_outcomes'][0]['price_group'],'21:PS')

    def test_no_gift_current_window_and_original_gift_history_keep_own_actual_delivery(self):
        from test_business_source import BusinessSourceTest
        now,order,old=BusinessSourceTest().window_fixture()
        current=deepcopy(old);current.update(operation_id='new-no-gift',opened_at='2026-10-26T02:00:00+00:00',mutable_resources=['base:PS'])
        current['action']['base_prices']={'PS':'8.68','XBOX':'12','PC':'6'}
        current['budget_reference']['base_prices']={'PS':'10','XBOX':'13','PC':'7'}
        current['catalog']['PS']['tiers'][0]['bonus_k']='0'
        new_order=dict(order,order_no='new-native-order',timestamp=int(datetime(2026,10,26,3,tzinfo=timezone.utc).timestamp()),timestamp_format='2026-10-26 11:00:00',content='<span class="item">100 K coins x 1 = $8.68</span>')
        self.assertEqual(business._quantity(order)['delivered_k'],'105')
        self.assertEqual(business._quantity(new_order)['delivered_k'],'100')
        result=business.bind_price_windows([order,new_order],[old,current],now)
        self.assertEqual({r['price_window_id']:r['group'] for r in result['actual_outcomes']},{'op':'console','new-no-gift':'PS'})
        self.assertEqual(old['catalog']['PS']['tiers'][0]['bonus_k'],'5')

    def test_native_ps_change_does_not_close_xbox_exposure(self):
        from test_business_source import BusinessSourceTest
        now,_,window=BusinessSourceTest().window_fixture()
        window.update(platforms=['PS','XBOX','PC'],mutable_resources=['base:PS','base:XBOX','base:PC'])
        window['action']['base_prices']={'PS':'8.68','XBOX':'12','PC':'6'}
        later=dict(window,operation_id='ps-next',opened_at='2026-10-26T02:00:00+00:00',mutable_resources=['base:PS'])
        self.assertEqual(business._window_end(window,'PS',[window,later],now),datetime(2026,10,26,2,tzinfo=timezone.utc))
        self.assertEqual(business._window_end(window,'XBOX',[window,later],now),now)

    def test_old_console_window_keeps_real_xbox_orders_after_ps_closes_without_inflating_combined_learning(self):
        from test_business_source import BusinessSourceTest
        now,ps,old=BusinessSourceTest().window_fixture()
        old['platforms']=['PS','XBOX'];old['catalog']['XBOX']=deepcopy(old['catalog']['PS'])
        old['resource_closed_at']={'base:PS':'2026-10-26T02:00:00+00:00','base:XBOX':'2026-10-26T04:00:00+00:00'}
        later=deepcopy(old);later.update(operation_id='native-ps',opened_at='2026-10-26T02:00:00+00:00',platforms=['PS'],mutable_resources=['base:PS'],resource_closed_at={})
        later['action']['base_prices']={'PS':'9','XBOX':'8.68','PC':'6'}
        later['budget_reference']['base_prices']={'PS':'10','XBOX':'10','PC':'7'}
        xbox=dict(ps,order_no='xbox-still-old',aid=21585,timestamp=int(datetime(2026,10,26,3,tzinfo=timezone.utc).timestamp()),timestamp_format='2026-10-26 11:00:00')
        after=dict(xbox,order_no='xbox-after-close',timestamp=int(datetime(2026,10,26,5,tzinfo=timezone.utc).timestamp()),timestamp_format='2026-10-26 13:00:00')
        result=business.bind_price_windows([ps,xbox,after],[old,later],now)
        self.assertEqual([(r['platform'],r['group']) for r in result['actual_outcomes']],[('PS','console'),('XBOX','console')])
        combined=next(r for r in result['training_observations'] if r['price_window_id']=='op' and r['price_group']=='console')
        self.assertEqual((combined['paid_orders'],combined['exposure']),(1,'2.0'))
        self.assertEqual(old['action']['base_prices'],{'console':'8.68'})

    def test_default_business_collection_uses_eight_day_finance_and_independent_seven_day_demand(self):
        selected,orders,proof=cohort();seven={'start':'2026-11-03','end':'2026-11-09'}
        calls=[]
        def population(period):
            calls.append(period)
            return selected,dict(proof,period=period)
        with patch.object(business,'datetime',SimpleNamespace(now=lambda *a:NOW)), \
             patch.object(business,'_period_population',side_effect=population), \
             patch.object(business,'_live_traces',return_value=(orders,{},{})), \
             patch.object(business,'demand_snapshot',return_value=dict(coverage={})) as demand, \
             patch.object(business,'marketing_context',return_value=dict(status='unavailable')), \
             patch.object(business,'fulfillment_context',return_value={}), \
             patch.object(business,'active_backlog_context',return_value={}), \
             patch.object(business,'_today_summary',return_value=dict(status='unavailable')), \
             patch.object(business,'online_window_context',return_value={}), \
             patch.object(business,'historical_attachment',return_value=([],{})), \
             patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            result=business.collect(None,None,{},[])
        self.assertEqual(demand.call_args.args[3]['period'],seven)
        self.assertIn(PERIOD,calls)
        self.assertEqual(result['historical_discount_mix']['period'],PERIOD)
        self.assertEqual(result['history_replay']['period'],PERIOD)
        self.assertEqual(set(result['historical_discount_mix']['by_platform']),{'PS','XBOX','PC'})

if __name__=='__main__':unittest.main()

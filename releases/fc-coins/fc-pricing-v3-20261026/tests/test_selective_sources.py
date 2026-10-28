import importlib.util
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import json
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'source'))
from fc_pricing_v3 import business_source as business,selective_sources as selective,regional_public as regional,sources,runtime
from fc_pricing_v3.ledger import Ledger
NOW=datetime(2026,10,26,13,tzinfo=timezone.utc)
PERIOD=dict(start='2026-10-19',end='2026-10-25')

def cache_fixture():
    selected={'private-raw-order':(dict(salesUsd='9.50',coupons=[],customerType='新客',status='已完成',costCny='30',saleCny='65'),dict(discount_usd='.50'))}
    orders={'private-raw-order':dict(before_discount='10',discount='95',points=0,amount_usd_format='$9.50',is_region_price=0,region_price_factor=0,discount_code='private-code')}
    provenance=dict(status='complete',period=PERIOD,canonical_archive_sha256='a'*64,ES_source_sha256='b'*64,ES_complete=True,missing_product_identity=0)
    mix=business.historical_mix(selected,provenance)
    replay=business.build_replay(selected,orders,{}, {},provenance);replay['original_mix_sha256']=mix['sha256']
    scenarios=[dict(code_retained_ratio='.95',points_credit_usd='0',coupon_template_ids=[],region_id=0,weight_usd='10.00',orders=1)]
    cache=selective.seal_history_cache(mix,replay,scenarios,dict(demand_model={}), 'source-v1',NOW)
    return cache,selected,orders,provenance


class SelectiveSourceTest(unittest.TestCase):
    def test_new_paid_coins_rebuilds_same_window_mix_and_write_boundary(self):
        selected={'old':(dict(salesUsd='100',coupons=[]),dict(discount_usd='0'))}
        native_selected=dict(selected,new=(dict(salesUsd='50',coupons=[]),dict(discount_usd='50')))
        orders={key:dict(order_no=key,site_id=266,gid=1327,pay_status=1,
            before_discount='100',discount=percent,points=0,amount_usd_format=net,
            is_region_price=0,discount_code='code' if percent==50 else '')
            for key,percent,net in [('old',100,'100'),('new',50,'50')]}
        _,_,_,provenance=cache_fixture()
        native=dict(provenance,canonical_archive_sha256='c'*64)
        ES=SimpleNamespace(CoinsEvidence=lambda:SimpleNamespace(archive=None),GOLD='Gold',
            es_metadata=lambda *a:({hashlib.sha256(b'new').hexdigest():dict(product='Gold')},dict(complete=True)))
        storefront=dict(rows={p:dict(package_usd='100') for p in ('PS','XBOX','PC')})
        pages=Mock(side_effect=lambda session,path,*a:list(orders.values()) if path.endswith('order.Order/index') else [])
        with patch.object(business,'_period_population',return_value=(selected,provenance)),patch.object(business,'_historical_native_population',return_value=(native_selected,native,orders,{})) as refresh,patch.dict(sys.modules,{'coins_evidence':ES,'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            cache,_=business.build_shared_history_cache(None,pages,storefront,[],'source-v1',NOW)
        refresh.assert_called_once_with(PERIOD,None,pages)
        self.assertEqual(cache['historical_discount_mix']['retained_ratio'],'0.75')
        self.assertEqual(cache['historical_discount_mix']['observed_orders'],2)
        self.assertEqual(cache['original_history_replay']['original_mix_sha256'],cache['historical_discount_mix']['sha256'])
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder);db=Ledger(store/'control.sqlite3')
            db.put('metadata','seven_day_history_cache',cache)
            with patch.object(runtime,'STORE',store),patch.object(business,'selective_history_signature',return_value='source-v1'):
                self.assertEqual(runtime.current_history_mix(NOW)['retained_ratio'],'0.75')

    def test_new_other_products_unpaid_and_other_sites_do_not_rebuild_coins(self):
        selected={'old':(dict(coupons=[]),{})}
        rows=[dict(order_no=key,site_id=site,gid=1327,pay_status=paid)
              for key,site,paid in [('old',266,1),('item',266,1),('unpaid',266,0),('other-site',267,1)]]
        metadata={hashlib.sha256(b'item').hexdigest():dict(product='Items')}
        ES=SimpleNamespace(CoinsEvidence=lambda:SimpleNamespace(archive=None),GOLD='Gold',
            es_metadata=Mock(return_value=(metadata,dict(complete=True))))
        pages=Mock(side_effect=lambda session,path,*a:rows if path.endswith('order.Order/index') else [])
        with patch.dict(sys.modules,{'coins_evidence':ES}):
            orders,_,_=business._live_traces(None,pages,PERIOD,selected,reconcile_population=True)
        self.assertEqual(set(orders),{'old'})
        ES.es_metadata.assert_called_once_with(PERIOD['start'],PERIOD['end'],None)
        ES.es_metadata.reset_mock()
        rows.remove(rows[1])
        with patch.dict(sys.modules,{'coins_evidence':ES}):
            business._live_traces(None,pages,PERIOD,selected,reconcile_population=True)
        ES.es_metadata.assert_not_called()

    def test_new_paid_unknown_product_cannot_silently_keep_old_mix(self):
        rows=[dict(order_no='new',site_id=266,gid=1327,pay_status=1)]
        for product in (None,'unknown','ambiguous'):
            metadata={} if product is None else {hashlib.sha256(b'new').hexdigest():dict(product=product)}
            ES=SimpleNamespace(CoinsEvidence=lambda:SimpleNamespace(archive=None),GOLD='Gold',
                es_metadata=lambda *a:(metadata,dict(complete=True)))
            with self.subTest(product=product),patch.dict(sys.modules,{'coins_evidence':ES}),self.assertRaisesRegex(ValueError,'history_new_paid_product_identity_missing'):
                business._live_traces(None,lambda *a:rows,PERIOD,{},reconcile_population=True)

    def test_write_boundary_uses_exact_reconciled_mix_and_rejects_changed_archive(self):
        cache,*_=cache_fixture()
        with tempfile.TemporaryDirectory() as folder:
            store=Path(folder);db=Ledger(store/'control.sqlite3')
            db.put('metadata','seven_day_history_cache',cache)
            with patch.object(runtime,'STORE',store),patch.object(business,'selective_history_signature',return_value='source-v1'):
                self.assertEqual(runtime.current_history_mix(NOW),cache['historical_discount_mix'])
            with patch.object(runtime,'STORE',store),patch.object(business,'selective_history_signature',return_value='archive-changed'):
                with self.assertRaisesRegex(ValueError,'source_or_window_changed'):runtime.current_history_mix(NOW)

    def test_changed_payment_state_rebuilds_exact_cohort_from_native_accounting(self):
        _,selected,orders,provenance=cache_fixture()
        native=dict(provenance,canonical_archive_sha256='c'*64)
        storefront=dict(rows={p:dict(package_usd='10') for p in ('PS','XBOX','PC')})
        with patch.object(business,'_period_population',return_value=(selected,provenance)),patch.object(business,'_live_traces',side_effect=ValueError('history_order_state_changed_since_archive')),patch.object(business,'_historical_native_population',return_value=(selected,native,orders,{})) as refresh,patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            cache,_=business.build_shared_history_cache(None,lambda *a,**k:[],storefront,[],'source-v1',NOW)
        refresh.assert_called_once_with(PERIOD,None,unittest.mock.ANY)
        self.assertEqual(cache['historical_discount_mix']['observed_orders'],1)
        self.assertEqual(cache['original_history_replay']['provenance']['prior_archive_sha256'],'a'*64)
        self.assertEqual(cache['original_history_replay']['original_mix_sha256'],cache['historical_discount_mix']['sha256'])
        self.assertNotIn('private-raw-order',json.dumps(cache))
        with patch.object(business,'_period_population',return_value=(selected,provenance)),patch.object(business,'_live_traces',side_effect=ValueError('history_live_order_coverage')),patch.object(business,'_historical_native_population') as refresh:
            with self.assertRaisesRegex(ValueError,'history_live_order_coverage'):
                business.build_shared_history_cache(None,None,storefront,[],'source-v1',NOW)
            refresh.assert_not_called()

    def test_cold_build_preserves_real_hash_and_anonymous_weights(self):
        _,selected,orders,provenance=cache_fixture()
        storefront=dict(rows={p:dict(package_usd='10') for p in ('PS','XBOX','PC')})
        with patch.object(business,'_period_population',return_value=(selected,provenance)),patch.object(business,'_live_traces',return_value=(orders,{},{})),patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            cache,_=business.build_shared_history_cache(None,None,storefront,[],'source-v1',NOW)
        self.assertEqual(sum(Decimal(row['weight_usd']) for row in cache['promotion_scenarios']),Decimal('10'))
        self.assertNotIn('private-raw-order',json.dumps(cache));self.assertNotIn('private-code',json.dumps(cache))
        self.assertEqual(cache['original_history_replay']['original_mix_sha256'],cache['historical_discount_mix']['sha256'])

    def test_source_plan_keeps_only_required_sources_and_fixed_interval(self):
        for mode in selective.MODES:
            plan=selective.source_plan(mode)
            self.assertEqual(plan['price_interval_minutes'],60)
            self.assertEqual(plan['quote_validity_seconds'],900)
            self.assertFalse(set(plan['required_markets'])&set(selective.RETIRED))
            self.assertEqual(plan['required_markets'],['Lootbar','ItemD2R'] if mode=='revenue_sprint' else ['Lootbar'])
        self.assertIn('ItemD2R',selective.source_plan('daily',dict(compare_itemd2r=True))['required_markets'])
        self.assertIn('ArabUT',selective.source_plan('revenue_sprint',dict(region_ids=[21]))['required_markets'])
        self.assertNotIn('ArabUT',selective.source_plan('revenue_sprint',dict(region_ids=[21],platforms=['PC']))['required_markets'])
        self.assertEqual(selective.source_plan('daily',interval_minutes=180)['price_interval_minutes'],180)
        self.assertEqual(selective.source_plan('daily',dict(interval_minutes=60))['quote_validity_seconds'],900)

    def test_warm_cache_does_not_scan_old_orders_or_costs_or_inactive_context(self):
        cache,_,_,_=cache_fixture()
        with patch.object(business,'selective_history_signature',return_value='source-v1'),patch.object(business,'_period_population') as population,patch.object(business,'_live_traces') as traces,patch.object(business,'active_backlog_context') as backlog,patch.object(business,'marketing_context') as ads,patch.object(business,'_today_summary') as today,patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            result=business.collect_selective_business(None,None,{},[],active_mode='daily',history_cache=cache,source_signature='source-v1',current_templates={},now=NOW+timedelta(hours=2))
        for callback in (population,traces,backlog,ads,today):callback.assert_not_called()
        self.assertEqual(result['private_updates'],{})
        self.assertNotIn('historical_orders',result['context'])
        self.assertNotIn('fulfillment_estimates',result['context'])
        self.assertNotIn('monthly_target',result['context'])
        self.assertEqual(result['context']['historical_discount_mix']['sha256'],cache['historical_discount_mix']['sha256'])
        self.assertNotIn('private-raw-order',json.dumps(cache))
        self.assertNotIn('private-code',json.dumps(cache))

    def test_cache_changed_source_or_new_closed_window_requires_real_rebuild(self):
        cache,_,_,_=cache_fixture()
        for signature,now in [('changed',NOW),('source-v1',NOW+timedelta(days=1))]:
            with self.subTest(signature=signature),self.assertRaisesRegex(ValueError,'source_or_window_changed'):
                selective.checked_history_cache(cache,signature,now)
        tampered=deepcopy(cache);tampered['promotion_scenarios'][0]['weight_usd']='1'
        with self.assertRaisesRegex(ValueError,'hash_changed'):selective.checked_history_cache(tampered,'source-v1',NOW)

    def test_provided_old_signature_cannot_bypass_real_source_watch(self):
        cache,_,_,_=cache_fixture()
        with patch.object(business,'selective_history_signature',return_value='actual-source-changed'):
            with self.assertRaisesRegex(ValueError,'source_signature_changed'):
                business.collect_selective_business(None,None,{},[],active_mode='daily',history_cache=cache,source_signature='source-v1',current_templates={},now=NOW)

    def test_current_coupon_cap_or_expiry_reprojects_cached_weights_without_historical_scan(self):
        cache,_,_,_=cache_fixture()
        body={k:deepcopy(v) for k,v in cache.items() if k!='cache_sha256'}
        body['promotion_scenarios'][0].update(code_retained_ratio='1',coupon_template_ids=['template-business-id'])
        cache=dict(body,cache_sha256=selective.fingerprint(body))
        terms={'template-business-id':dict(_current_active=True,mode_type=2,reduce=90,attain=10,max_reduce=2,is_open=0)}
        first=selective.project_cached_history(cache,terms,NOW)
        terms['template-business-id']['max_reduce']=1
        second=selective.project_cached_history(cache,terms,NOW)
        self.assertNotEqual(first['source_sha256'],second['source_sha256'])
        self.assertEqual(second['paths'][0]['promotion_path']['cap_usd'],'1')
        self.assertEqual(second['paths'][0]['weight_usd'],'10.00')
        terms['template-business-id']['_current_active']=False
        third=selective.project_cached_history(cache,terms,NOW)
        self.assertEqual(third['paths'][0]['promotion_path'],dict(kind='none'))
        self.assertEqual(third['original_mix_sha256'],cache['historical_discount_mix']['sha256'])
        same_terms_later=selective.project_cached_history(cache,terms,NOW+timedelta(hours=2))
        self.assertEqual(third['source_sha256'],same_terms_later['source_sha256'])

    def test_retired_modes_never_collect_inactive_context(self):
        cache,*_=cache_fixture()
        with patch.object(business,'selective_history_signature') as signature,patch.object(business,'active_backlog_context') as backlog,patch.object(business,'marketing_context') as ads:
            for mode in ('acquisition','backlog','flash_sale'):
                with self.assertRaisesRegex(ValueError,'selective_active_mode_invalid'):
                    business.collect_selective_business(None,None,{},[],active_mode=mode,history_cache=cache,now=NOW)
            signature.assert_not_called();backlog.assert_not_called();ads.assert_not_called()

    def test_supported_modes_ignore_retired_capacity_cache_without_collecting_it(self):
        cache,*_=cache_fixture()
        body={k:deepcopy(v) for k,v in cache.items() if k!='cache_sha256'}
        body['daily_rollups']['observed_fulfillment']=dict(observed_delivered_k_per_block=None)
        cache=dict(body,cache_sha256=selective.fingerprint(body))
        with patch.object(business,'selective_history_signature',return_value='source-v1'),patch.object(business,'fulfillment_context') as fulfillment,patch.object(business,'active_backlog_context') as backlog,patch.dict(sys.modules,{'pricing_sources':SimpleNamespace(active=lambda *a,**k:True)}):
            result=business.collect_selective_business(None,None,{},[],active_mode='daily',history_cache=cache,source_signature='source-v1',current_templates={},now=NOW)
        fulfillment.assert_not_called();backlog.assert_not_called()
        self.assertNotIn('fulfillment_estimates',result['context'])

    def test_cache_hit_never_waives_current_hard_input_freshness(self):
        plan=selective.source_plan('daily')
        fresh=NOW.isoformat();stale=(NOW-timedelta(hours=3)).isoformat()
        evidence=dict(source_plan=plan,fx=dict(checked_at=fresh),promotion_envelope=dict(checked_at=fresh),
            costs={p:dict(checked_at=fresh) for p in plan['platforms']},storefront=dict(rows={p:dict(checked_at=fresh) for p in plan['platforms']}))
        self.assertTrue(selective.validate_current_hard_evidence(evidence,NOW))
        evidence['costs']['PC']['checked_at']=stale
        with self.assertRaisesRegex(ValueError,'stale'):selective.validate_current_hard_evidence(evidence,NOW)

    def test_replacement_coverage_accepts_Lootbar_only_without_old_missing_placeholders(self):
        plan=selective.source_plan('daily')
        snapshot=dict(run_id='same-run',competitors=[dict(platform=p,source='Lootbar',run_id='same-run',status='valid',currency='USD',purchase_k='100',gross_usd='10',captured_at=NOW.isoformat(),conditional=False,comparable=True) for p in plan['platforms']])
        self.assertTrue(selective.planned_source_coverage(snapshot,plan,NOW)['ready'])
        snapshot['competitors'][0]['run_id']='other-run'
        self.assertFalse(selective.planned_source_coverage(snapshot,plan,NOW)['ready'])

    def test_sprint_coverage_still_requires_fresh_ItemD2R_actual_quote(self):
        plan=selective.source_plan('revenue_sprint',dict(platforms=['PC']))
        base=dict(platform='PC',run_id='same-run',status='valid',currency='USD',purchase_k='100',gross_usd='10',captured_at=NOW.isoformat(),conditional=False,comparable=True)
        snapshot=dict(run_id='same-run',competitors=[dict(base,source='Lootbar')])
        self.assertFalse(selective.planned_source_coverage(snapshot,plan,NOW)['ready'])
        self.assertTrue(selective.planned_source_coverage(snapshot,plan,NOW,reference_market=dict(offers=[dict(base,source='ItemD2R')]))['ready'])

    def test_daily_replay_uses_only_same_day_immutable_stored_snapshots_and_two_pure_calls(self):
        snapshot=dict(snapshot_id='actual-stored',origin='live_collector',mode='production',evidence=dict(checked_at=NOW.isoformat(),historical_ref={'cache_sha256':'cache'}))
        request=selective.daily_shadow_request('2026-10-26',[snapshot,dict(snapshot,snapshot_id='old',evidence=dict(checked_at=(NOW-timedelta(days=1)).isoformat()))])
        self.assertEqual(len(request['snapshot_refs']),1)
        self.assertFalse(request['coverage']['full_day_input_slots_covered'])
        self.assertEqual(request['coverage']['observed_slots'],1)
        self.assertEqual(request['expected_dispatch_at'],'2026-10-27T02:20:00+08:00')
        calls=[]
        def pure(saved,mode,**kwargs):
            calls.append((mode,kwargs['as_of']))
            if mode=='daily':raise KeyError('required_baseline_missing')
            saved['evidence']['mutated']=True
            return dict(value='explicit_initial_assumption',execution_authorized=False)
        result=selective.replay_daily_stored(request,[snapshot],pure)
        self.assertEqual(len(calls),2)
        self.assertEqual([r['strategy'] for r in result['records'] if r['status']=='gap'],['daily'])
        self.assertNotIn('mutated',snapshot['evidence'])
        self.assertFalse(result['external_collection_performed']);self.assertFalse(result['training_eligible'])

    def test_daily_replay_uses_original_decision_time_and_reports_failed_slots(self):
        decision=(NOW+timedelta(minutes=2)).isoformat()
        snapshot=dict(snapshot_id='s',created_at=decision,origin='live_collector',mode='production',evidence=dict(checked_at=NOW.isoformat()))
        failed=dict(snapshot,snapshot_id='failed',status='failed',created_at=(NOW-timedelta(hours=2)).isoformat())
        request=selective.daily_shadow_request('2026-10-26',[snapshot,failed])
        evaluator=Mock(return_value=dict(execution_authorized=False))
        result=selective.replay_daily_stored(request,[snapshot,failed],evaluator)
        self.assertEqual(request['coverage']['failed_snapshot_count'],1)
        self.assertEqual(evaluator.call_args.kwargs['as_of'],decision)
        self.assertEqual(evaluator.call_count,2)
        self.assertEqual(sum(row['status']=='gap' for row in result['records']),1)
        configured=selective.daily_shadow_request('2026-10-26',[snapshot],interval_minutes=180)
        self.assertEqual(configured['coverage']['expected_input_slots'],8)

    def test_timestamp_refresh_is_not_an_economic_condition_change(self):
        evidence=dict(costs={'PC':dict(platform='PC',game='FC27',product='Game Coins',cny_per_1k='0.2',checked_at=NOW.isoformat(),record_id=1)},
            fx=dict(cny_per_usd='7',checked_at=NOW.isoformat()),historical_discount_mix=dict(period=PERIOD,eligible_orders=1,net_order_usd='10',actual_discount_usd='1',retained_ratio='.9',sha256='old'))
        first=selective.economic_source_signature(evidence)
        updated=deepcopy(evidence);updated['costs']['PC'].update(checked_at=(NOW+timedelta(hours=2)).isoformat(),record_id=2)
        updated['historical_discount_mix']['sha256']='new-observation-hash'
        self.assertEqual(first,selective.economic_source_signature(updated))
        updated['costs']['PC']['cny_per_1k']='.21'
        self.assertNotEqual(first,selective.economic_source_signature(updated))

    def test_daily_replay_rejects_changed_snapshot_and_executable_result(self):
        snapshot=dict(snapshot_id='s',origin='live_collector',mode='production',evidence=dict(checked_at=NOW.isoformat()))
        request=selective.daily_shadow_request('2026-10-26',[snapshot])
        pure=Mock(return_value=dict(execution_authorized=True))
        result=selective.replay_daily_stored(request,[snapshot],pure)
        self.assertTrue(all(row['status']=='gap' for row in result['records']))
        changed=deepcopy(snapshot);changed['evidence']['new']='changed'
        pure.reset_mock();result=selective.replay_daily_stored(request,[changed],pure)
        pure.assert_not_called();self.assertEqual(result['records'][0]['status'],'gap')

    def test_light_snapshot_keeps_proof_and_ref_but_no_order_payload(self):
        result=selective.lightweight_snapshot(dict(historical_ref={'cache_sha256':'x'},historical_orders=[{'private':'order'}],private_updates={'cache':'private'},costs={'PC':'current'},promotion_envelope={'sha256':'current'}))
        self.assertNotIn('historical_orders',result);self.assertNotIn('private_updates',result)
        self.assertEqual(result['costs'],{'PC':'current'})

    def test_history_change_signature_ignores_delivery_cost_updates_but_detects_history_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'channel';es=Path(tmp)/'es';(root/'days').mkdir(parents=True);es.mkdir()
            for offset in range(7):
                day=(datetime(2026,10,19)+timedelta(days=offset)).date().isoformat()
                (root/'days'/(day+'.json')).write_text('{}')
            (es/'manifest.json').write_text(json.dumps(dict(query=PERIOD,captured_at=NOW.isoformat(),file_sha256=['a'*64])))
            (es/('a'*64+'.xlsx')).write_bytes(b'original existing file')
            first=business.selective_history_signature(PERIOD,channel_root=root,ES_root=es)
            (root/'order-deliveries.json').write_text('{"new_cost_arrived":true}')
            self.assertEqual(first,business.selective_history_signature(PERIOD,channel_root=root,ES_root=es))
            (root/'days/2026-10-19.json').write_text('{"actual_source_changed":true}')
            self.assertNotEqual(first,business.selective_history_signature(PERIOD,channel_root=root,ES_root=es))

    def test_shared_runtime_collects_missing_sprint_Arab_once_and_returns_actual_quotes(self):
        from test_regional_sources import products,SKUS
        from fc_pricing_v3 import region_source,market_registry
        storefront=dict(rows={p:dict(sku_id=str(sku)) for p,sku in SKUS.items()})
        auth=SimpleNamespace(Session=Mock,admin_token_from_service=lambda:('fixture','ok'))
        channel=SimpleNamespace(pages=lambda *a:list(products().values()),COLLECTOR='/fixture')
        cache,_,_,_=cache_fixture()
        context=selective.context_from_cache(cache,selective.source_plan('revenue_sprint',dict(region_ids=[21])),{},NOW)
        envelope=dict(context=context,private_updates={})
        actual=dict(status='available',offers=[dict(source='ArabUT',platform='PS',delivery='normal')])
        with patch.dict(sys.modules,{'channel_source':channel,'p2pah_auth':auth}),patch.object(region_source,'read_rules',return_value=[]),patch.object(business,'collect_selective_business',return_value=envelope),patch.object(regional,'collect',return_value=dict(offers={})),patch.object(market_registry,'arab_normal',return_value=actual) as arab:
            result=sources.shared_context(storefront,active_mode='revenue_sprint',scope=dict(region_ids=[21]))
        arab.assert_called_once_with()
        self.assertEqual(result['context']['arab_ut_status'],actual)
        self.assertEqual(result['context']['arab_ut_quotes'],actual['offers'])

    def test_shared_selective_context_reads_only_affected_region_platform_and_never_Arab_for_daily(self):
        sys.path.insert(0,str(HERE))
        from test_regional_sources import products,PublicOpener,InlinePool,SKUS
        from fc_pricing_v3 import region_source,market_registry
        storefront=dict(rows={p:dict(sku_id=str(sku)) for p,sku in SKUS.items()})
        rule=dict(id=1,site_id=266,lang_region_id=39,goods_id=0,gid=1327,top_cid=1,cid=0,sid=7645,aid=0,factor='.9100',status=1)
        session=Mock();auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        channel=SimpleNamespace(pages=lambda *a:list(products().values()),COLLECTOR='/fixture')
        cache,_,_,_=cache_fixture()
        context=selective.context_from_cache(cache,selective.source_plan('daily',dict(platforms=['PC'])),{},NOW)
        envelope=dict(context=context,private_updates={})
        original=regional.collect;calls=[]
        def public(code,rid,**kwargs):
            calls.append((code,rid,kwargs.get('platforms')))
            with patch.object(regional,'build_opener',return_value=PublicOpener(code)):
                return original(code,rid,**kwargs)
        with patch.dict(sys.modules,{'channel_source':channel,'p2pah_auth':auth}),patch.object(region_source,'read_rules',return_value=[rule]),patch.object(business,'collect_selective_business',return_value=envelope),patch.object(regional,'collect',side_effect=public),patch('concurrent.futures.ThreadPoolExecutor',InlinePool),patch.object(market_registry,'arab_normal') as arab:
            result=sources.shared_context(storefront,active_mode='daily',scope=dict(platforms=['PC']))
        arab.assert_not_called()
        self.assertEqual(calls,[('uk',39,['PC'])])
        self.assertEqual(result['context']['region_rules'][0]['platforms'],['PC'])
        self.assertTrue(result['context']['region_rules'][0]['verified'])
        self.assertNotIn('admin_products',result['context'])


if __name__=='__main__':unittest.main()

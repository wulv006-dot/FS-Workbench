"""Synthetic multi-quantity evidence; not live competitor acceptance."""
import ast
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
REPO=SOURCE.parents[3]
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3.competitor_offers import POLICY, QUANTITIES, normalize_offers, quantity_coverage, legacy_100k_projection, select_offer
from fc_pricing_v3.selective_sources import source_plan, planned_source_coverage, economic_source_signature
NOW=datetime.now(timezone.utc)


def raw(q='100',**more):
    return dict(dict(source='U7Buy',platform='PS',run_id='same',purchase_k=q,bonus_k='0',
        gross_usd='10',currency='USD',captured_at=NOW.isoformat(),status='valid',
        conditional=False,coupon_excluded=True,comparable=True,delivery_method='comfort_trade',delivery_tier='normal'),**more)


def snapshot_module():
    with patch.dict(sys.modules,{'fc27_quote_engine':SimpleNamespace(source_coverage=lambda _:None)}):
        spec=importlib.util.spec_from_file_location('quantity_snapshot',SOURCE/'snapshot_layer.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class CompetitorOffersV6(unittest.TestCase):
    def test_arab_adapters_preserve_official_100k_quote_identity(self):
        from test_collection_bidirectional import BidirectionalCollection, NOW as source_now, native
        from fc_pricing_v3 import market_registry

        def open_quote(request, **kwargs):
            platform = 'pc' if 'platform=pc' in request.full_url else 'playstation'
            payload = json.dumps(dict(data=native(platform))).encode() if '/coins/quote' in request.full_url else b''
            response = Mock()
            response.read.return_value = payload
            return nullcontext(response)

        with patch.object(market_registry, 'build_opener', return_value=SimpleNamespace(open=open_quote)), \
                patch.object(market_registry, 'datetime', SimpleNamespace(now=lambda _: source_now)):
            local = market_registry.arab_normal()
        remote, _ = BidirectionalCollection().collect()
        plan = source_plan('smart', dict(competitor_policy=POLICY))
        for status in (local, remote):
            coverage = planned_source_coverage(dict(run_id='three-platform', competitor_offers=[],
                arab_ut_status=status), plan, source_now)
            offers = {row['platform']: row for row in coverage['normalized_offers']}
            self.assertEqual(set(offers), {'PS', 'XBOX', 'PC'})
            for platform, row in offers.items():
                pc = platform == 'PC'
                self.assertTrue(row['comparable'])
                self.assertEqual(row['regular_price'], '9.47' if pc else '8.53')
                self.assertEqual(row['purchase_k'], '100')
                self.assertEqual(row['delivered_k'], '100')
                self.assertEqual(row['original_currency'], 'SAR')
                self.assertEqual(row['original_amount_minor'], 3550 if pc else 3200)
                self.assertEqual(row['original_delivery'], None if pc else 'normal')
                self.assertEqual(row['delivery_method'], 'standard' if pc else 'normal')
                self.assertEqual(row['delivery_tier'], 'standard' if pc else 'normal')

    def test_verified_lootbar_100k_compares_without_an_advertised_delivery_tier(self):
        from collection_cases import NOW as remote_now, context, observation
        from fc_collection.contracts import build_job, to_fc_quote_rows
        from fc_collection.lootbar import VERSION, REQUEST_BUDGET, snapshot_offer
        from fc_pricing_v3.engine import quantity_market_quote
        from test_lootbar_fallback import snapshot

        module = snapshot_module()
        offers = {platform: dict(platform=platform, base_k='100', bonus_k='5', usd_price='8.50',
            coupon_excluded=False, price_basis='当前无券商品价') for platform in ('PS', 'XBOX', 'PC')}
        events = [dict(stage='ps_restored'), dict(stage='complete', read_only=True,
            checked_at=NOW.isoformat(), offers=offers)]
        local = module.lootbar_snapshots('same', events)
        task = build_job(dict(run_id='same', created_at=remote_now.isoformat()), 'Lootbar',
            dict(context(), requested_platforms=['PS'], adapter_version=VERSION, total_request_budget=REQUEST_BUDGET),
            (remote_now + timedelta(seconds=110)).isoformat())
        task.update(attempt_id='attempt-1', lease_epoch=1, node_id='183', node_boot_id='boot-1')
        body = observation(task)
        body['offers'] = [snapshot_offer(snapshot(coupon='excluded'), 'PS', remote_now)]
        body.update(request_budget_used=REQUEST_BUDGET, request_accounting=dict(
            basis='reserved_browser_group', charged=REQUEST_BUDGET, browser_requests_allowed=7))
        remote = to_fc_quote_rows([body], task, remote_now)['offers'][0]
        for candidate, stamp, method in ((local[0], NOW, None), (remote, remote_now, 'standard')):
            row = normalize_offers([candidate], 'same', stamp)[0]
            self.assertTrue(row['comparable'])
            self.assertEqual(row['delivery_tier'], None)
            self.assertEqual(row['delivery_method'], method)
            self.assertEqual(row['comparability_basis'], 'lootbar_observed_100k_merchandise_no_delivery_tier')
            self.assertEqual(normalize_offers([row], 'same', stamp), [row])
            self.assertEqual(len(legacy_100k_projection([row])), 1)
            quote = quantity_market_quote(dict(competitor_policy=POLICY, run_id='same', competitor_offers=[row]),
                source='Lootbar', platform='PS', purchase_k='100', promotion_eligibility='all_customers',
                delivery_method=method, delivery_tier=None, currency='USD', now=stamp)
            self.assertEqual(quote['selected_price'], row['regular_price'])
        unproved = raw(source='Lootbar', delivery_tier=None)
        self.assertFalse(normalize_offers([unproved], 'same', NOW)[0]['comparable'])
        self.assertFalse(normalize_offers([dict(remote, purchase_k='1000')], 'same', remote_now)[0]['comparable'])

    def test_four_native_quantities_and_condition_delivery_keys_never_overwrite(self):
        rows=[raw(q,gross_usd=str(i*17+10)) for i,q in enumerate(QUANTITIES)]
        rows.extend([raw(promotion_eligibility='new_customer',conditional=True),raw(delivery_tier='fast')])
        normalized=normalize_offers(rows,'same',NOW)
        self.assertEqual(len(normalized),6)
        self.assertEqual(len({r['offer_key'] for r in normalized}),6)
        self.assertEqual([r['regular_price'] for r in normalized[:4]],['10','27','44','61'])
        selected=select_offer(normalized,source='U7Buy',platform='PS',purchase_k='2000',
            promotion_eligibility='all_customers',delivery_method='comfort_trade',delivery_tier='normal',currency='USD')
        self.assertEqual(selected['regular_price'],'44')

    def test_unknown_net_fees_and_foreign_currency_not_filled_or_converted(self):
        rows=normalize_offers([raw(conditional=True,promotion_eligibility='unknown',eligible_net_price='8',
            currency='SAR',gross_usd=None,regular_price='40',bonus_k=None)],'same',NOW)
        row=rows[0]
        self.assertEqual(row['currency'],'SAR')
        self.assertEqual(row['regular_price'],'40')
        for field in ('eligible_net_price','necessary_fees','tax_bearer','bonus_k','delivered_k','fx'):
            self.assertIsNone(row[field])
        self.assertFalse(row['comparable'])
        self.assertEqual(legacy_100k_projection(rows),[])
        arab=normalize_offers([raw(source='ArabUT',delivery_method='standard',delivery_tier='standard',
            original_currency='SAR',original_amount_minor=3550,settlement_currency='SAR',
            conversion_source='official_display_quote',original_platform='pc',original_delivery=None)],'same',NOW)[0]
        self.assertEqual(arab['original_amount_minor'],3550)
        self.assertEqual(arab['delivery_tier'],'standard')
        self.assertIsNone(arab['original_delivery'])
        self.assertEqual(arab['original_platform'],'pc')
        foreign=normalize_offers([raw(currency='SAR',gross_usd='9.47')],'same',NOW)[0]
        self.assertIsNone(foreign['regular_price'],'USD amount must not be relabelled as SAR')
        self.assertFalse(foreign['comparable'])
        coverage=quantity_coverage([foreign])
        self.assertTrue(coverage['ready'])
        self.assertFalse(coverage['quantity_coverage_complete'])
        self.assertEqual(coverage['comparable_observations'],0)
        self.assertIn(dict(source='U7Buy',platform='PS',purchase_k='100',status='observed_conditions_unverified'),coverage['quantities'])
        unknown_delivery=normalize_offers([raw(delivery_method=None,delivery_tier=None)],'same',NOW)[0]
        self.assertFalse(unknown_delivery['comparable'])
        unknown_eligibility=normalize_offers([raw(promotion_eligibility={'status':'unknown'},eligible_net_price='8')],'same',NOW)[0]
        self.assertFalse(unknown_eligibility['comparable'])
        self.assertIsNone(unknown_eligibility['eligible_net_price'])

    def test_duplicates_and_conflicts_preserve_revision_boundary(self):
        a=raw()
        self.assertEqual(len(normalize_offers([a,deepcopy(a)],'same',NOW)),1)
        with self.assertRaisesRegex(ValueError,'revision_conflict'):
            normalize_offers([a,raw(gross_usd='11')],'same',NOW)
        for changed in (dict(run_id='old'),dict(captured_at=(NOW-timedelta(seconds=901)).isoformat()),dict(purchase_k='200'),dict(gross_usd='NaN')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):normalize_offers([raw(**changed)],'same',NOW)

    def test_legacy_projection_only_unambiguous_100k(self):
        normalized=normalize_offers([raw(q) for q in QUANTITIES],'same',NOW)
        legacy=legacy_100k_projection(normalized)
        self.assertEqual(len(legacy),1)
        self.assertEqual(legacy[0]['compatibility_scope'],'100k_observed_only')
        self.assertEqual(legacy[0]['purchase_k'],'100')
        variants=normalize_offers([raw(),raw(delivery_tier='fast')],'same',NOW)
        self.assertEqual(legacy_100k_projection(variants),[])

    def test_policy_explicit_legacy_unchanged_and_all_missing_optional(self):
        old=source_plan('smart')
        self.assertIn('ItemD2R',old['auxiliary_markets'])
        self.assertIn('U7Buy',old['retired_automatic_sources'])
        plan=source_plan('smart',dict(competitor_policy=POLICY))
        self.assertEqual(plan['required_markets'],['Lootbar','U7Buy','ArabUT'])
        self.assertEqual(plan['auxiliary_markets'],[])
        self.assertNotIn('U7Buy',plan['retired_automatic_sources'])
        coverage=planned_source_coverage(dict(run_id='same',competitors=[]),plan,NOW)
        self.assertTrue(coverage['ready']);self.assertEqual(coverage['missing'],[])
        self.assertEqual(len(coverage['optional_missing']),36)
        self.assertNotIn('floor',coverage['pricing_source_policy'])
        with_one=planned_source_coverage(dict(run_id='same',competitor_offers=[raw()]),plan,NOW)
        self.assertEqual(len(with_one['optional_missing']),35)
        self.assertEqual(with_one['normalized_offers'][0]['purchase_k'],'100')
        self.assertTrue(any(r['source']=='U7Buy' and r['purchase_k']=='5000' for r in with_one['optional_missing']))

    def test_quantity_snapshot_keeps_native_rows_and_rejects_forged_scope(self):
        module=snapshot_module()
        payload=dict(source='U7Buy',status='valid',quantity_scope=list(QUANTITIES),offers=[raw(q) for q in QUANTITIES])
        rows=module.public_snapshots('same','U7Buy',payload)
        self.assertEqual([r['purchase_k'] for r in rows],list(QUANTITIES))
        payload['quantity_scope']=['100']
        with self.assertRaisesRegex(ValueError,'scope'):module.public_snapshots('same','U7Buy',payload)

    def test_snapshot_v6_collects_u7_without_item_or_missing_market_hard_failure(self):
        module=snapshot_module()
        processes=[SimpleNamespace(returncode=1,stdout=b''),SimpleNamespace(returncode=1,stdout=b''),
                   SimpleNamespace(returncode=0,stdout=b''),SimpleNamespace(returncode=0,stdout=b'')]
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),\
             patch.object(module.subprocess,'run',side_effect=processes) as run,\
             patch.object(module,'collector_failure',return_value='fixture_missing'),\
             patch.object(module,'cost_snapshots',return_value=[dict(status='valid',platform=p) for p in module.PLATFORMS]),\
             patch.object(module,'newest_evidence',return_value=dict(status='valid',checked_at=NOW.isoformat(),cny_per_usd='7')),\
             patch.object(module,'atomic_json') as save,patch.object(module.os,'chown',create=True),patch.object(module.os,'chmod'):
            summary,ready=module.collect_once('00000000-0000-4000-8000-000000000099',POLICY)
        self.assertTrue(ready)
        self.assertEqual(run.call_args_list[1].args[0][-2:],['U7Buy',','.join(QUANTITIES)])
        self.assertNotIn('ItemD2R',str(run.call_args_list))
        stored=save.call_args.args[1]
        self.assertEqual(stored['competitor_offers'],[])
        self.assertEqual(stored['legacy_competitor_scope'],'100k_observed_only')
        self.assertEqual(summary['status'],'ready_for_quote')

    def test_snapshot_keeps_native_lootbar_tiers_out_of_the_legacy_offer_list(self):
        module=snapshot_module()
        offers={p:dict(platform=p,base_k='100',bonus_k='5',usd_price='9',coupon_excluded=False) for p in module.PLATFORMS}
        events=[dict(stage='ps_restored'),dict(stage='complete',read_only=True,checked_at=NOW.isoformat(),
            offers=offers,quantity_offers=[
                dict(offers['PS'],base_k='1000',bonus_k='50',usd_price='79.38',coupon_excluded=True,
                     observed_coupon_price='69.86',excluded_coupon_discount='9.52'),
                dict(offers['PC'],base_k='2000',usd_price='160',coupon_excluded=True)])]
        processes=[SimpleNamespace(returncode=code,stdout=b'') for code in (0,1,0,0)]
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),\
             patch.object(module.subprocess,'run',side_effect=processes) as run,\
             patch.object(module.glob,'glob',side_effect=[[],[str(Path(folder)/'lootbar.jsonl')],[],[],[]]),\
             patch.object(module.Path,'read_text',return_value='\n'.join(json.dumps(event) for event in events)),\
             patch.object(module,'collector_failure',return_value='fixture_missing'),\
             patch.object(module,'cost_snapshots',return_value=[dict(status='valid',platform=p) for p in module.PLATFORMS]),\
             patch.object(module,'newest_evidence',return_value=dict(status='valid',checked_at=NOW.isoformat(),cny_per_usd='7')),\
             patch.object(module,'atomic_json') as save,patch.object(module.os,'chown',create=True),patch.object(module.os,'chmod'):
            _,ready=module.collect_once('00000000-0000-4000-8000-000000000099',POLICY)
        self.assertTrue(ready)
        self.assertIn('--native-quantities',run.call_args_list[0].args[0])
        stored=save.call_args.args[1]
        self.assertEqual([row['purchase_k'] for row in stored['competitors']],['100']*3)
        large=[row for row in stored['competitor_offers'] if row['purchase_k']!='100']
        self.assertEqual([(row['platform'],row['purchase_k'],row['regular_price'],row['delivered_k']) for row in large],
                         [('PS','1000','79.38','1050')])
        self.assertTrue(large[0]['comparable'])
        self.assertIsNone(large[0]['eligible_net_price'])

    def test_u7_reader_requests_each_platform_once_preserves_absent_quantities(self):
        file=REPO/'fc27_cloud_browser/collect_competitor_browser.py'
        tree=ast.parse(file.read_text(encoding='utf-8'))
        names={'positive','checked_offer','collect_u7buy_quantities'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        from decimal import Decimal, InvalidOperation
        page=Mock();read=Mock(side_effect=[dict(active=[label],offers=[dict(purchase_k='100',price='10',bonus='0',conditional=False),
             dict(purchase_k='2000',price='135',bonus='50',conditional=True)],
             missing=[dict(purchase_k=q,reason='native_quantity_not_observed') for q in ('1000','5000')]) for label in ('PS4/PS5','XBOX','PC')])
        scope=dict(Decimal=Decimal,InvalidOperation=InvalidOperation,datetime=datetime,timezone=timezone,
            open_page=lambda *_:page,URLS={'U7Buy':'https://www.u7buy.com/fc27/coins'},stable=read,U7BUY_QUANTITIES_READ='reader')
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(file),'exec'),scope)
        result=scope['collect_u7buy_quantities'](object(),QUANTITIES)
        self.assertEqual(len(result['offers']),6)
        self.assertEqual(len(result['missing']),6)
        self.assertEqual(read.call_count,3)
        self.assertEqual([r['purchase_k'] for r in result['offers']],['100','2000']*3)
        normal, newcomer = normalize_offers(result['offers'], 'same', datetime.now(timezone.utc))[:2]
        self.assertEqual(normal['regular_price'], '10')
        self.assertEqual(newcomer['display_price'], '135')
        self.assertIsNone(newcomer['regular_price'])
        self.assertIsNone(newcomer['eligible_net_price'])
        self.assertFalse(newcomer['comparable'])
        self.assertEqual(newcomer['promotion_eligibility'], dict(status='unknown', advertised_for='new_customer'))
        self.assertIsNone(normalize_offers([raw(conditional=True)], 'same', NOW)[0]['regular_price'])
        page.close.assert_called_once()

    def test_v6_observer_does_not_call_item_reader(self):
        from fc_pricing_v3 import observations,runtime
        from fc_pricing_v3.ledger import Ledger
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            db.put('pricing_snapshots','same',dict(evidence=dict(source_plan=source_plan('smart',dict(competitor_policy=POLICY)))))
            with patch.object(runtime,'ledger',return_value=db),patch.object(observations,'collect_reference_market') as collect:
                result=observations.observe('same')
            collect.assert_not_called()
            self.assertIn('ItemD2R',result['retired_automatic_sources'])
            self.assertNotIn('U7Buy',result['retired_automatic_sources'])

    def test_worker_passes_v6_to_snapshot_and_skips_item_without_hiding_cost_failure(self):
        from fc_pricing_v3 import runtime
        tree=ast.parse((SOURCE/'fc27_cloud_worker.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='collect_quote')
        scope=dict(APP=Path('/fixture'),local_collection=SimpleNamespace(pin=lambda _:dict(mode='server')),
            save_job=Mock(),run=Mock(return_value=(1,dict(status='incomplete',reason='P2PAH:missing'))),
            collect_reference_market=Mock())
        exec(compile(ast.Module(body=[node],type_ignores=[]),'fc27_cloud_worker.py','exec'),scope)
        job=dict(job_id='same')
        with patch.object(runtime,'ledger'),patch.object(runtime,'collection_scope',return_value=dict(active_mode='smart',scope=dict(competitor_policy=POLICY))),self.assertRaisesRegex(ValueError,'collection_incomplete'):
            scope['collect_quote'](job)
        self.assertEqual(scope['run'].call_args.args[0][-1],POLICY)
        scope['collect_reference_market'].assert_not_called()
        self.assertEqual(job['error_detail'],'P2PAH:missing')

    def test_economic_signature_includes_high_tiers_eligibility_delivery_and_original_money(self):
        rows=normalize_offers([raw(q) for q in QUANTITIES],'same',NOW)
        evidence=dict(competitor_offers=rows)
        original=economic_source_signature(evidence)
        for key,value in (('regular_price','999'),('promotion_eligibility','new_customer'),
            ('delivery_tier','fast'),('currency','SAR'),('original_amount_minor',3550),('display_price','120'),
            ('necessary_fees',{'amount':'1','currency':'USD'})):
            changed=deepcopy(evidence);changed['competitor_offers'][-1][key]=value
            self.assertNotEqual(original,economic_source_signature(changed),key)
        changed=deepcopy(evidence)
        changed['competitor_offers'].reverse()
        for row in changed['competitor_offers']:
            row['captured_at']=(NOW+timedelta(minutes=3)).isoformat()
            row['observation_id']='new-receipt'
            row['run_id']='next-cycle'
        self.assertEqual(original,economic_source_signature(changed))


if __name__=='__main__':unittest.main()

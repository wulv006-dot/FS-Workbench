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
from fc_pricing_v3.competitor_offers import FOUR_SOURCE_POLICY, LEGACY_POLICY, POLICY, QUANTITIES, normalize_offers, quantity_coverage, legacy_100k_projection, select_offer
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
    def test_market_cards_keep_pricing_coverage_and_observer_rounds_separate(self):
        from fc_pricing_v3.api import _curve_market_quotes
        from fc_pricing_v3.competitor_offers import FOUR_SOURCE_POLICY
        observer = raw('1000', source='IGGM', regular_price='60')
        evidence = dict(competitor_policy=POLICY, competitor_offers=[raw(), observer])
        snapshot = dict(snapshot_id='same', created_at=NOW.isoformat(), evidence=evidence)
        observation = dict(run_id='same', package_offers=[observer, dict(observer, run_id='older')])
        market = _curve_market_quotes(snapshot, observation)
        self.assertEqual(market['competitor_coverage']['optional_sources'], ['Lootbar', 'U7Buy'])
        self.assertEqual([r['source'] for r in market['competitor_offers']], ['U7Buy'])
        self.assertEqual([r['regular_price'] for r in market['monitoring']['IGGM']], ['60'])
        self.assertNotIn('run_id', market['monitoring']['IGGM'][0])
        self.assertFalse(_curve_market_quotes(snapshot, dict(observation, run_id='older'))['monitoring']['IGGM'])
        historical = _curve_market_quotes(dict(snapshot, evidence=dict(evidence, competitor_policy=FOUR_SOURCE_POLICY)))
        self.assertEqual([r['source'] for r in historical['competitor_offers']], ['U7Buy', 'IGGM'])
        self.assertEqual(historical['monitoring'], {})

    def test_lootbar_public_skus_project_only_small_packages_and_reject_foreign_receipts(self):
        module = snapshot_module()
        rows = [raw(q, source='Lootbar', platform='PC', delivery_method=None, delivery_tier=None,
                    auth_state='public', selection_verified=True, price_basis='public_platform_sku',
                    discount_source='public_no_coupon', source_metadata=dict(spu_id=1461, platform='PC',
                    selected_currency='USD', asset_name=name)) for q,name in
                [('100','100K Safe Coins'), ('1000','1M Safe Coins')]]
        event = dict(stage='public_sku_complete', run_id='same', source='Lootbar', read_only=True, offers=rows)
        small, large = module.public_lootbar_packages('same', event)
        self.assertEqual([(r['platform'],r['purchase_k']) for r in small if r['status']=='valid'], [('PC','100')])
        self.assertEqual({r['platform'] for r in small if r['status']=='missing'}, {'PS','XBOX'})
        self.assertEqual([(r['platform'],r['purchase_k']) for r in large], [('PC','1000')])
        for invalid in (dict(event, run_id='earlier'), dict(event, offers=rows+rows),
                        dict(event, offers=[dict(rows[0],source='IGGM')])):
            with self.assertRaises(ValueError):
                module.public_lootbar_packages('same', invalid)

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
        plan = source_plan('smart', dict(competitor_policy=LEGACY_POLICY))
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
        self.assertEqual(plan['required_markets'],['Lootbar','U7Buy'])
        self.assertEqual(plan['auxiliary_markets'],[])
        self.assertNotIn('U7Buy',plan['retired_automatic_sources'])
        coverage=planned_source_coverage(dict(run_id='same',competitors=[]),plan,NOW)
        self.assertTrue(coverage['ready']);self.assertEqual(coverage['missing'],[])
        self.assertEqual(len(coverage['optional_missing']),12)
        historical=source_plan('smart',dict(competitor_policy=FOUR_SOURCE_POLICY))
        old_coverage=planned_source_coverage(dict(run_id='same',competitors=[]),historical,NOW)
        self.assertEqual(len(old_coverage['optional_missing']),24)
        self.assertNotIn('floor',coverage['pricing_source_policy'])
        with_one=planned_source_coverage(dict(run_id='same',competitor_offers=[raw(),raw('5000')]),plan,NOW)
        self.assertEqual(len(with_one['optional_missing']),11)
        self.assertEqual(len(with_one['normalized_offers']),1)
        self.assertEqual(with_one['normalized_offers'][0]['purchase_k'],'100')
        self.assertTrue(all(r['purchase_k'] in ('100','1000') for r in with_one['optional_missing']))

    def test_quantity_snapshot_keeps_native_rows_and_rejects_forged_scope(self):
        module=snapshot_module()
        payload=dict(source='U7Buy',status='valid',quantity_scope=list(QUANTITIES),offers=[raw(q) for q in QUANTITIES])
        rows=module.public_snapshots('same','U7Buy',payload)
        self.assertEqual([r['purchase_k'] for r in rows],list(QUANTITIES))
        payload['quantity_scope']=['100']
        with self.assertRaisesRegex(ValueError,'scope'):module.public_snapshots('same','U7Buy',payload)

    def test_snapshot_v6_collects_u7_without_item_or_missing_market_hard_failure(self):
        module=snapshot_module()
        from threading import Event

        cost_started, fx_started = Event(), Event()

        def run_source(command, **kwargs):
            if command[0] == str(module.COST_COLLECTOR):
                cost_started.set()
                self.assertTrue(fx_started.wait(2), 'the FX read must start before the outstanding Order read finishes')
            elif command[0] == str(module.COLLECTOR):
                self.assertTrue(cost_started.wait(1), 'Order cost should start before the market source finishes')
            elif command[0] == str(module.FX_COLLECTOR):
                fx_started.set()
            return SimpleNamespace(returncode=int(command[0] in (str(module.COLLECTOR), str(module.PUBLIC_COLLECTOR))),
                                   stdout=b'')
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),\
             patch.object(module.subprocess,'run',side_effect=run_source) as run,\
             patch.object(module,'collector_failure',return_value='fixture_missing'),\
             patch('fc_pricing_v3.runtime.ledger'),\
             patch('fc_pricing_v3.runtime._confirmed_cost_references',return_value=dict.fromkeys(module.PLATFORMS,'.4')),\
             patch.object(module,'cost_snapshots',return_value=[dict(status='valid',platform=p) for p in module.PLATFORMS]),\
             patch.object(module,'newest_evidence',return_value=dict(status='valid',checked_at=NOW.isoformat(),cny_per_usd='7')),\
             patch.object(module,'atomic_json') as save,patch.object(module.os,'chown',create=True),patch.object(module.os,'chmod'):
            summary,ready=module.collect_once('00000000-0000-4000-8000-000000000099',POLICY)
        self.assertTrue(ready)
        public_call = next(call for call in run.call_args_list if call.args[0][0] == str(module.PUBLIC_COLLECTOR))
        self.assertEqual(public_call.args[0][-2:],['U7Buy','100,1000'])
        self.assertNotIn('ItemD2R',str(run.call_args_list))
        cost_call = next(call for call in run.call_args_list if call.args[0][0] == str(module.COST_COLLECTOR))
        self.assertEqual(json.loads(cost_call.kwargs['env']['FC_V6_COST_REFERENCES']),
                         {'PS': '.4', 'XBOX': '.4', 'PC': '.4'})
        stored=save.call_args.args[1]
        self.assertEqual(stored['competitor_offers'],[])
        self.assertEqual(stored['legacy_competitor_scope'],'100k_observed_only')
        self.assertEqual(summary['status'],'ready_for_quote')

    def test_snapshot_retries_only_timed_out_fx_after_current_order_completes(self):
        from threading import Event
        module = snapshot_module()
        release_order = Event()
        order_finished = Event()
        run_id = '00000000-0000-4000-8000-000000000099'
        costs = [dict(status='valid', platform=p, run_id=run_id) for p in module.PLATFORMS]
        market_rows = [raw('100')]
        missing = dict(status='missing', reason='fx_collector_failed')
        rate = dict(status='valid', checked_at=NOW.isoformat(), cny_per_usd='7')
        timeout = 'BOC:browser_connection_timeout'

        def collect_cost(*args, **kwargs):
            self.assertTrue(release_order.wait(2))
            order_finished.set()
            return costs, None, None

        for recovered in (True, False):
            with self.subTest(recovered=recovered), tempfile.TemporaryDirectory() as folder:
                release_order.clear()
                order_finished.clear()
                attempts = []
                second_failure = None if recovered else 'BOC:page_read_timeout'
                warnings = ['Lootbar:collector_failed'] if recovered else []

                def collect_fx():
                    attempts.append(order_finished.is_set())
                    if len(attempts) == 1:
                        release_order.set()
                        return missing, timeout
                    return (rate if recovered else missing), second_failure

                with patch.object(module, 'ROOT', Path(folder)), \
                        patch('fc_collection.package_routes.read_node', side_effect=AssertionError('observer in pricing path')), \
                        patch.object(module, 'collect_market_sources', return_value=([], market_rows, list(warnings))) as market, \
                        patch.object(module, 'collect_order_cost', side_effect=collect_cost) as cost, \
                        patch.object(module, 'collect_fx', side_effect=collect_fx), \
                        patch.object(module, 'atomic_json') as save, \
                        patch.object(module.os, 'chown', create=True), patch.object(module.os, 'chmod'):
                    summary, ready = module.collect_once(run_id, POLICY)
                self.assertEqual(attempts, [False, True])
                market.assert_called_once_with(run_id, curve_v6=True)
                cost.assert_called_once_with(run_id, curve_v6=True)
                stored = save.call_args.args[1]
                self.assertEqual(stored['costs'], costs)
                self.assertEqual(stored['competitor_offers'], market_rows)
                self.assertEqual(stored['fx'], rate if recovered else missing)
                self.assertEqual(stored['fx_retry'], dict(first_failure=timeout, retry_failure=second_failure))
                self.assertEqual(stored['fx_retry'], summary['fx_retry'])
                self.assertEqual(stored['source_warnings'], warnings)
                self.assertNotIn('package_attempts',stored)
                self.assertEqual(stored['source_coverage']['optional_sources'], ['Lootbar','U7Buy'])
                self.assertEqual(ready, recovered)
                self.assertEqual(summary['reason'], second_failure)

    def test_snapshot_does_not_retry_fx_for_other_failures_or_legacy(self):
        module = snapshot_module()
        run_id = '00000000-0000-4000-8000-000000000099'
        costs = [dict(status='valid', platform=p, run_id=run_id) for p in module.PLATFORMS]
        timeout = 'BOC:browser_connection_timeout'
        cases = [(POLICY, costs, True, 'BOC:page_read_timeout'),
                 (POLICY, costs, False, timeout),
                 (POLICY, costs[:-1], True, timeout),
                 (None, costs, True, timeout)]
        for mode, platform_costs, market_ready, fx_failure in cases:
            with self.subTest(mode=mode, count=len(platform_costs), market_ready=market_ready, fx=fx_failure), \
                    tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), \
                    patch.object(module, 'collect_market_sources', return_value=([], [], [])), \
                    patch('fc_pricing_v3.competitor_offers.quantity_coverage', return_value={'ready': market_ready}), \
                    patch.object(module, 'collect_order_cost', return_value=(platform_costs, None, None)), \
                    patch.object(module, 'collect_fx', return_value=(dict(status='missing'), fx_failure)) as fx, \
                    patch.object(module, 'atomic_json') as save, \
                    patch.object(module.os, 'chown', create=True), patch.object(module.os, 'chmod'):
                _, ready = module.collect_once(run_id, mode)
                self.assertFalse(ready)
                fx.assert_called_once()
                self.assertNotIn('fx_retry', save.call_args.args[1])

    def test_snapshot_records_verified_1000k_and_keeps_the_legacy_100k_view(self):
        module=snapshot_module()
        offers={p:dict(platform=p,base_k='100',bonus_k='5',usd_price='9',coupon_excluded=False) for p in module.PLATFORMS}
        events=[dict(stage='ps_restored'),dict(stage='complete',read_only=True,checked_at=NOW.isoformat(),
            offers=offers,quantity_offers=[
                dict(offers['PS'],base_k='1000',bonus_k='50',usd_price='79.38',coupon_excluded=True,
                     observed_coupon_price='69.86',excluded_coupon_discount='9.52'),
                dict(offers['PC'],base_k='2000',usd_price='160',coupon_excluded=True)])]
        fixture_evidence = iter(([], ['lootbar.jsonl']))

        def run_source(command, **kwargs):
            return SimpleNamespace(returncode=int(command[0] == str(module.PUBLIC_COLLECTOR)), stdout=b'')

        def fixture_glob(pattern):
            return next(fixture_evidence) if pattern.endswith('lootbar-*.jsonl') else []
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'ROOT',Path(folder)),\
             patch('fc_pricing_v3.runtime.ledger'),\
             patch('fc_pricing_v3.runtime._confirmed_cost_references',return_value=dict.fromkeys(module.PLATFORMS)),\
             patch.object(module.subprocess,'run',side_effect=run_source) as run,\
             patch.object(module.glob,'glob',side_effect=fixture_glob),\
             patch.object(module.Path,'read_text',return_value='\n'.join(json.dumps(event) for event in events)),\
             patch.object(module,'collector_failure',return_value='fixture_missing'),\
             patch.object(module,'cost_snapshots',return_value=[dict(status='valid',platform=p) for p in module.PLATFORMS]),\
             patch.object(module,'newest_evidence',return_value=dict(status='valid',checked_at=NOW.isoformat(),cny_per_usd='7')),\
             patch.object(module,'atomic_json') as save,patch.object(module.os,'chown',create=True),patch.object(module.os,'chmod'):
            _,ready=module.collect_once('00000000-0000-4000-8000-000000000099',POLICY)
        self.assertTrue(ready)
        lootbar_call = next(call for call in run.call_args_list if call.args[0][0] == str(module.COLLECTOR))
        self.assertIn('--native-quantities',lootbar_call.args[0])
        stored=save.call_args.args[1]
        self.assertEqual([row['purchase_k'] for row in stored['competitors']],['100']*3)
        self.assertCountEqual([row['purchase_k'] for row in stored['competitor_offers']], ['100']*3+['1000'])
        self.assertEqual(stored['source_coverage']['quantity_scope'],['100','1000'])

    def test_u7_reader_requests_each_platform_once_preserves_absent_quantities(self):
        file=REPO/'fc27_cloud_browser/collect_competitor_browser.py'
        tree=ast.parse(file.read_text(encoding='utf-8'))
        names={'positive','checked_offer','collect_u7buy_quantities'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        from decimal import Decimal, InvalidOperation
        page=Mock();read=Mock(side_effect=[dict(active=[label],offers=[dict(purchase_k='100',price='10',bonus='0',conditional=False,
             delivery_method='comfort_trade',delivery_estimate='0.5-1Hour'),
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
        self.assertTrue(normal['comparable'])
        self.assertEqual(normal['delivery_method'], 'comfort_trade')
        self.assertEqual(normal['delivery_tier'], 'estimated:0.5-1Hour')
        self.assertEqual(normal['delivery_estimate'], '0.5-1Hour')
        self.assertEqual(normalize_offers([normal], 'same', datetime.now(timezone.utc)), [normal])
        self.assertEqual(newcomer['display_price'], '135')
        self.assertIsNone(newcomer['regular_price'])
        self.assertIsNone(newcomer['eligible_net_price'])
        self.assertFalse(newcomer['comparable'])
        self.assertEqual(newcomer['promotion_eligibility'], dict(status='unknown', advertised_for='new_customer'))
        self.assertIsNone(normalize_offers([raw(conditional=True)], 'same', NOW)[0]['regular_price'])
        page.close.assert_called_once()

    def test_browser_read_retry_preserves_legacy_and_v6_result_contracts(self):
        file = REPO/'fc27_cloud_browser/collect_competitor_browser.py'
        tree = ast.parse(file.read_text(encoding='utf-8'))
        names = {'main', 'timeout_diagnostic'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]

        class CollectorTimeoutError(Exception):
            pass

        for selected, outcome in (
                (None, ('valid', 2, 'Page.goto', 20)),
                (QUANTITIES, ('valid', 2, 'Page.goto', 20)),
                (QUANTITIES, ('missing', 1, 'Page.goto', 48)),
                (QUANTITIES, ('missing', 1, 'Page.close', 20))):
            with self.subTest(selected=selected, outcome=outcome):
                status, calls, method, elapsed = outcome
                platforms = ('PS', 'XBOX', 'PC')
                rows = [dict(platform=p) for p in platforms]
                result = dict(source='U7Buy',status='valid',offers=rows,missing=[],quantity_scope=list(QUANTITIES))
                error = CollectorTimeoutError(method + ': private page details')
                legacy = Mock(side_effect=[error, rows])
                native = Mock(side_effect=[error, result])
                reader = native if selected else legacy
                display = Mock()
                browser = SimpleNamespace(contexts=[object()])
                playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=Mock(return_value=browser)))
                time = SimpleNamespace(monotonic=Mock(side_effect=[0,elapsed]),sleep=Mock())
                argv = ['collector','U7Buy'] + ([','.join(selected)] if selected else [])
                scope = dict(COLLECTORS={'U7Buy':legacy}, PLATFORMS=platforms, collect_u7buy_quantities=native,
                             time=time, sys=SimpleNamespace(argv=argv), os=SimpleNamespace(environ={}), json=json,
                             CollectorTimeoutError=CollectorTimeoutError, print=display,
                             sync_playwright=lambda:nullcontext(playwright))
                exec(compile(ast.Module(body=nodes,type_ignores=[]),str(file),'exec'),scope)
                self.assertEqual(scope['main'](),0 if status=='valid' else 1)
                self.assertEqual(reader.call_count,calls)
                value = json.loads(display.call_args.args[0])
                self.assertEqual(value['status'],status)
                self.assertNotIn('private page details',str(value))
                self.assertEqual(len(value['read_retries']),calls-1)
                if calls==2:
                    self.assertEqual(value['read_retries'][0]['price_actions'],0)
                    time.sleep.assert_called_once_with(1)
                    self.assertEqual(value['offers'],rows)
                    self.assertEqual(value.get('quantity_scope'),list(selected) if selected else None)

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

    def test_observer_keeps_monitoring_quotes_outside_the_price_snapshot(self):
        from fc_pricing_v3.api import _curve_market_quotes
        from fc_pricing_v3 import observations,runtime
        from fc_pricing_v3.ledger import Ledger
        run_id = '00000000-0000-4000-8000-000000000099'
        snapshot = dict(created_at=NOW.isoformat(), evidence=dict(run_id=run_id, competitor_policy=POLICY,
                        competitor_offers=[], source_plan=source_plan('smart',dict(competitor_policy=POLICY))))
        def read(node, request, started):
            source = request['source']
            if source == 'U4GM':
                return dict(request, offers=[], errors=['http_403'] if node == '187' else ['browser_snapshot_unavailable'])
            offers = [raw(q, source=source, run_id=run_id, platform=p) for p,q in request['wanted']]
            return dict(request, offers=offers, errors=[])
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            db.put('pricing_snapshots',run_id,snapshot)
            with patch.object(runtime,'ledger',return_value=db),patch('fc_collection.package_routes.read_node',side_effect=read) as reader:
                result=observations.observe(run_id)
                self.assertEqual(observations.observe(run_id),result)
            self.assertEqual(reader.call_count,3)
            self.assertEqual(result['package_status']['IGGM']['status'],'captured')
            self.assertEqual(result['package_status']['U4GM']['status'],'missing')
            market = _curve_market_quotes(dict(snapshot, snapshot_id=run_id), result)
            attempt, cached = market['monitoring_attempts']['U4GM']
            self.assertEqual(cached['node'], 'local')
            self.assertEqual((attempt['node'], attempt['response_received'], attempt['errors']), ('187', True, ['http_403']))
            self.assertIn(['PC', '1000'], attempt['requested'])
            self.assertEqual(attempt['accepted'], [])
            self.assertEqual(len(result['package_offers']),6)
            self.assertEqual(db.get('pricing_snapshots',run_id),snapshot)

    def test_unexpected_reader_failure_keeps_the_other_site_result(self):
        from fc_pricing_v3.observations import collect_package_observations
        def read(node, req, started):
            if req['source'] == 'U4GM':
                raise RuntimeError('reader failed')
            return dict(req, offers=[raw(q, source='IGGM', platform=p) for p,q in req['wanted']],errors=[])
        with patch('fc_collection.package_routes.read_node',side_effect=read):
            result = collect_package_observations('same', NOW.isoformat())
        self.assertEqual(result['package_status']['U4GM']['errors'], ['RuntimeError'])
        self.assertEqual(result['package_status']['U4GM']['status'], 'missing')
        self.assertEqual(result['package_status']['IGGM']['status'],'captured')
        self.assertEqual(len(result['package_offers']),6)

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

    def test_observer_quotes_do_not_change_the_economic_condition(self):
        anchors = [raw()]
        signature = economic_source_signature(dict(competitor_offers=anchors))
        observed = [raw(source='U4GM', gross_usd='10000'), raw(source='IGGM', gross_usd='.01')]
        self.assertEqual(economic_source_signature(dict(competitor_offers=anchors + observed)), signature)

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

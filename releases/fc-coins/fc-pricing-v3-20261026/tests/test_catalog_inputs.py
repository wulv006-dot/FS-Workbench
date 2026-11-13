"""Actual V3 catalog/legacy boundaries; no live network or business writes."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3 import engine, financial, selective_sources as inputs, business_source, runtime, monitoring
from test_dual20_sprint import source, NOW
from test_selective_sources import cache_fixture
import pricing_sources
import pricing_state
import pricing_v2
import automation_policy

PROMO_FIELDS = {'worst_net_usd', 'promotional_net_usd', 'promotional_gross_usd',
                'promotional_margin_pct', 'rounding_reserve_usd', 'promotional_status'}


def core(value):
    if isinstance(value, dict):
        return {k: core(v) for k, v in value.items() if k not in PROMO_FIELDS}
    if isinstance(value, list):
        return [core(v) for v in value]
    return value


def catalog(data):
    body = dict(contract=inputs.CATALOG_CONTRACT, status='verified', site_id=266, game_id=1327,
                packages=deepcopy(data['promotion_envelope']['packages']), worst_status='unknown')
    return dict(body, sha256=financial.fingerprint(body), checked_at=NOW.isoformat())


def actual_pages():
    # Execute the original shared module, not a reimplemented paging helper.
    path = SOURCE.parents[2] / 'fs-dashboard/channel-effects-20261021/source/channel_source.py'
    spec = importlib.util.spec_from_file_location('catalog_shared_channel', path)
    module = importlib.util.module_from_spec(spec)
    effects = SimpleNamespace(**{k: None for k in ('Attribution', 'EMPTY_COST', 'SITE', 'TZ',
                                                  'delivery_index', 'normalize', 'money')})
    with patch.dict(sys.modules, {'channel_effects': effects}):
        spec.loader.exec_module(module)
    return module.pages


class TemplateSession:
    def __init__(self, identifiers, missing=None, incomplete=False):
        self.ids, self.calls, self.missing, self.incomplete = identifiers, [], missing, incomplete

    def get_admin(self, path, **params):
        self.calls.append(params)
        assert path == '/admin/market.Coupon/index'
        assert params['search[0][field]'] == 'id'
        assert params['search[0][operator]'] == 'IN'
        assert 'search[1][field]' not in params  # inactive/global/relative rows must survive
        ids = params['search[0][val]'].split(',')
        rows = [dict(id=i, status='0' if i == self.ids[0] else '1') for i in ids if i != self.missing]
        total = len(rows)
        start = (params['page']-1)*7
        rows = rows[start:start+7]
        if self.incomplete and params['page'] == 2:
            rows = []
        return 200, dict(code=1, data=dict(list=rows, total=total))


class CatalogInputs(unittest.TestCase):
    def test_old_math_outputs_are_exactly_preserved(self):
        data = source()
        envelope = data['promotion_envelope']
        ratio = financial.envelope_ratio(envelope, NOW)
        self.assertEqual(inputs.input_ratio(envelope, NOW), ratio)
        args = ('0.2', '.35', '7', '105', '100', ratio)
        self.assertEqual(inputs.input_prove_price(*args), financial.prove_price(*args))
        rules = envelope['packages']['PS']
        self.assertEqual(inputs.input_catalog_floor('.35', '7', ratio, '20', rules),
                         financial.catalog_floor('.35', '7', ratio, '20', rules))

    def test_new_catalog_preserves_finance_candidates_scores_and_choice(self):
        old = source(cost='.10')
        new = deepcopy(old)
        new['promotion_envelope'] = catalog(old)
        action = dict(base_prices={p:'20' for p in engine.PLATFORMS}, region_coefficients={})
        before, after = engine.financial(old, action, NOW), engine.financial(new, action, NOW)
        self.assertEqual(core(before), core(after))
        for mode in engine.POLICIES:
            a = engine.evaluate(old, mode, now=NOW)
            b = engine.evaluate(new, mode, now=NOW)
            self.assertEqual(core(a), core(b))
        for row in after['prices'].values():
            proof = json.loads(json.dumps(row['proof']))
            self.assertEqual(proof['promotional_status'], 'unknown')
            for key in PROMO_FIELDS - {'promotional_status'}:
                self.assertIsNone(proof[key])
        self.assertNotIn('minimum_retained_ratio', new['promotion_envelope'])

    def test_missing_cost_history_or_catalog_evidence_still_rejects(self):
        data = source()
        data['promotion_envelope'] = catalog(data)
        for field in ('historical_discount_mix', 'costs'):
            broken = deepcopy(data)
            broken.pop(field)
            with self.assertRaises((ValueError, KeyError)):
                engine.evaluate(broken, 'revenue_sprint', now=NOW)
        broken = deepcopy(data)
        broken['promotion_envelope']['checked_at'] = '2020-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'source_stale'):
            engine.evaluate(broken, 'revenue_sprint', now=NOW)
        broken = deepcopy(data['promotion_envelope'])
        broken['minimum_retained_ratio'] = '1'
        with self.assertRaisesRegex(ValueError, 'catalog_promotional_claim'):
            inputs.input_ratio(broken, NOW)

    def test_v3_source_reads_only_original_goods_ids_and_does_not_write(self):
        data = source()
        storefront = data['storefront']
        goods = []
        for p, row in storefront['rows'].items():
            row.update(sku_id=str(len(goods)+1), bonus_k='0', package_usd='20.00')
            goods.append(dict(id=row['sku_id'], mid='9', site_id='266', gid='1327', top_cid='1',
                unit='K', status='1', discount='100', unit_price='.20',
                more=dict(gold=['100'], give=['0'], discount=['100'])))
        def pages(session, path, filters):
            self.assertEqual(path, '/admin/goods.Goods/index')
            self.assertEqual(filters, [('id', 'IN', '1,2,3')])
            return goods
        session = SimpleNamespace(bind_admin_token=Mock(), close=Mock())
        auth = SimpleNamespace(Session=lambda: session, admin_token_from_service=lambda: ('fixture', ''))
        channel = SimpleNamespace(pages=pages, COLLECTOR='fixture')
        with patch.dict(sys.modules, {'channel_source': channel, 'p2pah_auth': auth}), \
                patch.object(pricing_sources, 'normalize', side_effect=AssertionError('marketing prohibited')):
            result = pricing_sources._collect_shared_admin(storefront, persist=False, catalog_only=True)
        self.assertEqual(result['contract'], inputs.CATALOG_CONTRACT)
        self.assertEqual(result['worst_status'], 'unknown')
        self.assertEqual(set(result['packages']), set(engine.PLATFORMS))
        self.assertTrue(session.close.called)

    def test_dynamic_fifteen_ids_complete_paging_and_inactive_row_survive(self):
        ids = [str(i) for i in range(1, 16)]
        session = TemplateSession(ids)
        rows = business_source.read_used_templates(session, actual_pages(), ids)
        self.assertEqual(set(rows), set(ids))
        self.assertEqual(rows['1']['status'], '0')
        self.assertEqual(len(session.calls), 3)

    def test_missing_id_and_incomplete_paging_reject(self):
        ids = [str(i) for i in range(1, 16)]
        with self.assertRaisesRegex(ValueError, 'coupon_template_missing'):
            business_source.read_used_templates(TemplateSession(ids, missing='15'), actual_pages(), ids)
        with self.assertRaisesRegex(ValueError, 'admin_incomplete_pages'):
            business_source.read_used_templates(TemplateSession(ids, incomplete=True), actual_pages(), ids)

    def test_original_hundred_id_batches_preserve_all_ids(self):
        ids = [str(i) for i in range(1, 206)]
        session = TemplateSession(ids)
        result = business_source.read_used_templates(session, actual_pages(), ids)
        self.assertEqual(set(result), set(ids))
        groups = {p['search[0][val]'] for p in session.calls}
        self.assertEqual(sorted(len(g.split(',')) for g in groups), [5, 100, 100])

    def test_new_source_plan_does_not_wait_on_monthly_or_report_context(self):
        legacy = inputs.source_plan('revenue_sprint')
        current = inputs.source_plan('revenue_sprint', dict(catalog_only=True))
        self.assertTrue(legacy['refresh_monthly_target'])
        self.assertFalse(current['refresh_monthly_target'])
        self.assertIn('current_catalog', current['hard_evidence'])

    def test_real_source_monitor_accepts_old_and_catalog_but_rejects_tampering(self):
        data = source()
        plan = dict(plan_id='p', mode='daily', resources=['base:console', 'base:pc'])
        receipt = dict(plan_id='p', mode='daily', status='INFEASIBLE', execution_authorized=False,
                       snapshot_id=data['run_id'],action=dict(base_prices={p:'20' for p in engine.PLATFORMS},region_coefficients={}))
        snapshot = dict(snapshot_id=data['run_id'], origin='live_collector', mode='production',
            created_at=NOW.isoformat(), evidence=data,
            result=dict(status='INFEASIBLE', decision_receipt=receipt))
        for envelope in (deepcopy(data['promotion_envelope']), catalog(data)):
            data['promotion_envelope'] = envelope
            receipt['snapshot_sha256'] = financial.fingerprint(data)
            self.assertEqual(monitoring.source_coverage([snapshot], [plan], NOW)['status'], 'verified')
        data['promotion_envelope']['packages']['PS']['min_custom_k'] = '1'
        receipt['snapshot_sha256'] = financial.fingerprint(data)
        self.assertEqual(monitoring.source_coverage([snapshot], [plan], NOW)['status'], 'unverified')

    def test_warm_catalog_path_has_no_full_marketing_or_monthly_reads(self):
        cache, _, _, _ = cache_fixture()
        with patch.object(business_source, 'selective_history_signature', return_value='source-v1'), \
                patch.object(business_source, '_today_summary', side_effect=AssertionError('monthly read prohibited')), \
                patch.object(business_source, '_selective_closed_month_rollup', side_effect=AssertionError('monthly archive prohibited')):
            read = Mock(side_effect=AssertionError('no coupon IDs means no marketing reads'))
            value = business_source.collect_selective_business(None, read, {}, {}, active_mode='revenue_sprint',
                scope=dict(catalog_only=True), history_cache=cache, now=datetime(2026, 10, 26, 13, tzinfo=NOW.tzinfo))
        self.assertNotIn('monthly_target', value['context'])
        self.assertEqual(value['context']['historical_discount_mix'], cache['historical_discount_mix'])

    def test_cold_native_reconciliation_preserves_paid_group_without_marketing_catalogs(self):
        effects_path = SOURCE.parents[2]/'fs-dashboard/channel-effects-20261021/source/channel_effects.py'
        spec = importlib.util.spec_from_file_location('catalog_original_accounting', effects_path)
        effects = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(effects)
        period = dict(start='2026-10-21', end='2026-10-27')
        raw = [dict(order_no=n, site_id=266, gid=1327, paytime='2026-10-27 12:00:00',
            amount_usd_format='$18.00', amount_rmb_format='¥120', status_format=status, pay_status=paid,
            game_format='FC27', aid=21587, discount_code='fixture', recommend_uid=0) for n, status, paid in (
                ('gold', '已完成', '1'), ('refund', '已退款', '2'), ('fraud', '验证未通过', '1'), ('test', '已完成', '1'), ('item', '已完成', '1'))]
        logs = [dict(id='7', coupon_id='15', site_id=266, order_no='gold', use_time='2026-10-27 12:00:00', status='1')]
        metadata = {hashlib.sha256(r['order_no'].encode()).hexdigest(): dict(product='Items' if r['order_no']=='item' else 'Gold', discount_usd='2') for r in raw}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'channel_mapping.json').write_text('{"entries":[]}')
            channel = SimpleNamespace(__file__=str(root/'channel_source.py'), SALES=root,
                normalize=effects.normalize, load_costs=Mock(return_value=([], {})),
                apply_cost_overrides=lambda _: dict(sources=dict(accounting={}), costOverrides={},
                    testOrders={'test': dict(gid=1327, salesUsd='18')}))
            es = SimpleNamespace(CoinsEvidence=lambda: SimpleNamespace(archive=root), GOLD='Gold',
                es_metadata=lambda *args: (metadata, dict(complete=True, source_sha256='e'*64)))
            def read(session, path, *args):
                if path.endswith('order.Order/index'):
                    return raw
                if path.endswith('MemberCouponLog/index'):
                    return logs
                raise AssertionError('marketing catalog read prohibited')
            with patch.dict(sys.modules, dict(channel_source=channel, channel_effects=effects, coins_evidence=es)):
                selected, proof, native, actual_logs = business_source._historical_native_population(period, None, read, pricing_only=True)
            self.assertEqual(set(selected), {'gold'})
            self.assertEqual(proof['status'], 'complete')
            self.assertEqual(set(native), {'gold'})
            self.assertEqual(set(actual_logs), {'7'})
            row = selected['gold'][0]
            self.assertEqual(row['coupons'][0]['templateId'], '15')
            self.assertIsNone(row['costCny'])  # uncollected cost is never invented as zero
            mix = business_source.historical_mix(selected, proof,orders=native)['by_platform']['PS']
            self.assertEqual(mix['net_order_usd'], '18.0')
            self.assertEqual(mix['actual_discount_usd'], '2')
            channel.load_costs.assert_not_called()

    def test_changed_population_reuses_complete_native_pages_and_preserves_financial_mix(self):
        from fc_pricing_v3.ledger import Ledger
        spec=importlib.util.spec_from_file_location('reused_native_accounting',SOURCE.parents[2]/'fs-dashboard/channel-effects-20261021/source/channel_effects.py')
        effects=importlib.util.module_from_spec(spec);spec.loader.exec_module(effects)
        period=inputs.history_period(NOW)
        raw=[dict(id=str(i),order_no=name,site_id=266,gid=1327,paytime=period['end']+' 12:00:00',
            amount_usd_format='$18.00',amount_rmb_format='120',status_format=status,pay_status=paid,
            game_format='FC27',aid=21587,discount_code='',recommend_uid=0,before_discount='20',discount='100',points='0',is_region_price=0)
            for i,(name,status,paid) in enumerate((('old','已完成','1'),('new','已完成','1'),
                ('refund','已退款','2'),('fraud','验证未通过','1'),('test','已完成','1'),('item','已完成','1')),1)]
        logs=[dict(id=str(i),coupon_id='15',site_id=266,order_no=name,use_time=period['end']+' 12:00:00',status=1,discount_amount='2') for i,name in ((7,'old'),(8,'new'))]
        template=dict(id='15',site_id=266,game_id=1327,status=1,product_type=1,time_effect=2,
            mode_type=1,reduce='2',attain='0',max_reduce='0',is_open=1)
        metadata={hashlib.sha256(row['order_no'].encode()).hexdigest():dict(product='Items' if row['order_no']=='item' else 'Gold',discount_usd='2') for row in raw}
        class Session:
            def __init__(self):self.calls=[]
            def get_admin(self,path,**params):
                self.calls.append((path,params))
                if path.endswith('order.Order/index'):rows,size=raw,2
                elif path.endswith('MemberCouponLog/index'):rows,size=logs,1
                elif path.endswith('market.Coupon/index'):rows,size=[template],1
                else:raise AssertionError('unexpected_source_read')
                offset=(params['page']-1)*size
                return 200,dict(code=1,data=dict(total=len(rows),list=rows[offset:offset+size]))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pages=actual_pages();session=Session()
            channel=SimpleNamespace(__file__=str(root/'channel_source.py'),SALES=root,normalize=effects.normalize,
                load_costs=Mock(side_effect=AssertionError('history_cost_not_required')),apply_cost_overrides=lambda _:dict(sources=dict(accounting={}),costOverrides={},testOrders={'test':dict(gid=1327,salesUsd='18')}))
            es=SimpleNamespace(CoinsEvidence=lambda:SimpleNamespace(archive=root),GOLD='Gold',es_metadata=lambda *a:(metadata,dict(complete=True,source_sha256='e'*64)))
            prior={'old':(dict(salesUsd='18',coupons=[dict(id='7',templateId='15')]),dict(discount_usd='2'))}
            provenance=dict(status='complete',period=period,canonical_archive_sha256='a'*64,ES_source_sha256='e'*64,ES_complete=True,missing_product_identity=0)
            with patch.dict(sys.modules,dict(channel_source=channel,channel_effects=effects,coins_evidence=es)),patch.object(business_source,'_period_population',return_value=(prior,provenance)),patch.object(business_source,'_historical_provider_now',return_value=NOW):
                cache,_=business_source.build_shared_history_cache(session,pages,{},[],'fixture-source',NOW,used_templates_only=True)
                reference_session=Session()
                reference,reference_proof,reference_native,_=business_source._historical_native_population(period,reference_session,pages,pricing_only=True)
                reference_mix=business_source.historical_mix(reference,reference_proof,orders=reference_native,history_window_contract=financial.HISTORY_WINDOW_CONTRACT)['by_platform']['PS']
            orders=[call for call in session.calls if call[0].endswith('order.Order/index')]
            self.assertEqual(len(orders),3,'one complete three-page native read; changed population must not repeat it')
            self.assertEqual([p['page'] for _,p in orders],[1,2,3])
            coupon_calls=[call for call in session.calls if call[0].endswith('MemberCouponLog/index')]
            self.assertEqual(len(coupon_calls),2,'all original used-coupon log pages remain required')
            self.assertEqual(len(session.calls),6)
            root_mix=cache['historical_discount_mix'];mix=root_mix['by_platform']['PS'];self.assertEqual(mix['observed_orders'],2);self.assertEqual(mix['eligible_orders'],2)
            for field in ('period','status','observed_orders','eligible_orders','net_order_usd','actual_discount_usd','undiscounted_order_usd','retained_ratio'):
                self.assertEqual(mix[field],reference_mix[field])
            self.assertEqual((mix['net_order_usd'],mix['actual_discount_usd'],mix['retained_ratio']),('36.0','4','0.9'))
            self.assertEqual(root_mix['status'],'partial')
            self.assertEqual(root_mix['by_platform']['XBOX']['status'],'unavailable')
            self.assertEqual(root_mix['by_platform']['PC']['status'],'unavailable')
            replay=cache['original_history_replay']['by_platform']['PS'];self.assertEqual(replay['status'],'verified')
            self.assertEqual((replay['original_net_usd'],replay['original_discount_usd']),('36.00','4'))
            self.assertEqual(sum(row['orders'] for row in cache['promotion_scenarios']['by_platform']['PS']),2)
            channel.load_costs.assert_not_called()
            store=root/'v3';db=Ledger(store/'control.sqlite3');db.put('metadata','seven_day_history_cache',cache)
            with patch.object(runtime,'STORE',store),patch.object(business_source,'selective_history_signature',return_value='fixture-source'):
                self.assertEqual(runtime.current_history_mix(NOW),root_mix)

    def test_reused_native_rows_keep_original_scope_checks_and_do_not_fallback_to_http(self):
        period=inputs.history_period(NOW)
        valid=dict(site_id=266,gid=1327,paytime=period['end']+' 12:00:00')
        pages=Mock(side_effect=AssertionError('reused_rows_must_not_trigger_second_order_query'))
        modules=dict(channel_source=SimpleNamespace(),channel_effects=SimpleNamespace(accounting_row=None,fraud=None),
                     coins_evidence=SimpleNamespace(CoinsEvidence=None,es_metadata=None,GOLD='Gold'))
        for change in (dict(site_id=267),dict(gid=1),dict(paytime='2000-01-01 00:00:00')):
            with self.subTest(change=change),patch.dict(sys.modules,modules):
                with self.assertRaisesRegex(ValueError,'historical_native_paid_scope_not_honored'):
                    business_source._historical_native_population(period,None,pages,pricing_only=True,native_rows=[dict(valid,**change)])
        pages.assert_not_called()

    def test_check_write_and_state_accept_only_verified_catalog_without_worst_claim(self):
        data = source()
        data['promotion_envelope'] = catalog(data)
        quote = dict(created_at=NOW.isoformat(), automation_policy_revision=42, evidence=data,
            result=dict(minimum_gross_margin_pct='20', strategy_version=runtime.VERSION,
                decision_receipt=dict(schema_version=runtime.VERSION, margin_basis=financial.MARGIN_BASIS)))
        policy = dict(system_enabled=True, mode='auto', revision=42, platforms=list(engine.PLATFORMS), minimum_gross_margin_pct='20')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'quotes').mkdir()
            (root/'quotes/fixture.json').write_text(json.dumps(quote))
            inputs_path = root/'pricing-inputs.json'
            inputs_path.write_text(json.dumps(data['promotion_envelope']))
            clock = SimpleNamespace(now=lambda *args: NOW)
            with patch.object(automation_policy, 'POLICY_FILE', root/'automation.json'), \
                    patch.object(automation_policy, 'datetime', clock), patch.object(pricing_v2, 'verify_quote') as verify, \
                    patch.object(pricing_state, 'datetime', clock):
                self.assertEqual(automation_policy.check_write(policy, quote, list(engine.PLATFORMS)), [])
                verify.assert_called_once()
                self.assertTrue(pricing_state.state(root)['execution_ready'])
                invalid = deepcopy(data['promotion_envelope'])
                invalid['packages']['PS']['min_custom_k'] = '1'
                inputs_path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, 'catalog_hash_changed'):
                    automation_policy.check_write(policy, quote, list(engine.PLATFORMS))

    def test_new_writer_guard_checks_same_catalog_cohort_and_template_projection(self):
        data = source()
        data['promotion_envelope'] = catalog(data)
        run = '00000000-0000-4000-8000-000000000001'
        preview = '00000000-0000-4000-8000-000000000002'
        cache = dict(cache_sha256='cache', source_signature='signature', historical_discount_mix=data['historical_discount_mix'])
        replay=dict(sha256='projection',by_platform={p:dict(current_coupon_terms_sha256='terms',paths_sha256='paths',region_layers={}) for p in engine.PLATFORMS})
        data.update(historical_ref=dict(cache_sha256='cache', source_signature='signature'), history_replay=replay)
        scalar_receipt = dict(action={'base_prices': {p: '8' for p in engine.PLATFORMS}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('quotes', 'previews', 'monitor'):
                (root/folder).mkdir()
            (root/'quotes'/(run+'.json')).write_text(json.dumps(
                dict(evidence=data, result={'decision_receipt': scalar_receipt})))
            (root/'previews'/(preview+'.json')).write_text(json.dumps(dict(run_id=run)))
            public = dict(data['storefront'], status='ok', source='https://www.mmoexp.com/Fc-27/Coins.html', currency='USD')
            for row in public['rows'].values():
                row['status'] = 'ok'
            (root/'monitor/storefront.json').write_text(json.dumps(public))
            clock = SimpleNamespace(now=lambda *args: NOW)
            with patch.object(pricing_sources, 'datetime', clock), \
                    patch.object(pricing_v2, 'verify_quote', return_value=scalar_receipt), \
                    patch.object(automation_policy, 'load_policy', return_value={}), \
                    patch.object(pricing_sources, 'collect', return_value=data['promotion_envelope']) as read, \
                    patch.object(runtime, 'current_history_cache', return_value=cache), \
                    patch.object(pricing_sources, 'current_template_projection', return_value=deepcopy(replay)) as projection:
                result = pricing_sources.refresh_before_write(dict(preview_id=preview), root)
                self.assertEqual(result['status'], 'current_catalog_rechecked')
                self.assertFalse(result['price_write_performed'])
                self.assertTrue(read.call_args.kwargs['catalog_only'])
                with self.assertRaisesRegex(ValueError, 'pricing_write_protocol_mismatch'):
                    pricing_sources.refresh_before_write(dict(preview_id=preview, write_protocol='fc27_curve_v6'), root)
                cache['cache_sha256']='only_nonfinancial_rollups_changed'
                self.assertEqual(pricing_sources.refresh_before_write(dict(preview_id=preview), root)['status'], 'current_catalog_rechecked')
                projection.return_value['by_platform']['XBOX']['current_coupon_terms_sha256']='changed'
                with self.assertRaisesRegex(ValueError, 'coupon_terms_changed'):
                    pricing_sources.refresh_before_write(dict(preview_id=preview), root)

    def test_null_display_is_not_zeroed_by_current_js_formatters(self):
        script = (SOURCE/'fc-pricing-v3.js').read_text(encoding='utf-8')
        self.assertRegex(script, r"function value\(v\)\{return v==null\?")
        self.assertRegex(script, r"function usd\(v\)\{return v==null\?")
        self.assertNotRegex(script, r'(?:Number|parseFloat)\([^)]*(?:worst_net_usd|promotional_)')


if __name__ == '__main__':
    unittest.main()

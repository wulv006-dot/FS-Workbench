"""Use private source outputs to test payment-window cost diagnostics without live reads."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT.parents[1] / 'fs-dashboard'
sys.path[:0] = [str(ROOT / 'source'), str(DASHBOARD / 'dashboard-refresh-20261025/source'),
                str(DASHBOARD / 'cache-archive-retention-20261025/source')]
from fc_pricing_v3 import business_source
from fc_pricing_v3 import runtime
from fc_pricing_v3.cost_inputs_v6 import BOC_URL, ORDINARY_COST_BASIS, estimate_historical_cost, project_admin_loss_statistics
from order_facts_source import project_order_facts


CUT = datetime.fromisoformat('2026-11-13T00:00:00+08:00')
AS_OF = CUT + timedelta(minutes=30)
LAYER = dict(platform='PS', quantity_bucket='large', offer_version='offer-1', fulfilment_contract='normal')
SCOPE = dict(site_id='266', gid='1327', start='2026-11-06', end='2026-11-12')


class AdminLossStatistics(unittest.TestCase):
    def test_category_loss_statistics_preserve_overlapping_membership_and_do_not_supply_cost(self):
        request=dict(site=266,game=1327,cid=1,pay_status=1,date=['2026-11-11 00:00','2026-11-11 23:59'])
        game=dict(gid=1327,cat={'gold':{'num':256}},
                  dc=dict(n=1,amount='130.09',order_id='912345671'),
                  dc_zhui_no=dict(n=1,amount='130.09',order_id='912345671'),
                  ts=dict(n=2,amount='278.33',order_id='912345672'))
        payload=json.dumps(dict(code=1,data={'data':dict(game_rank={'FC 27':game},
            site_rank={'www.mmoexp.com':{}},total='256')})).encode()
        loss=project_admin_loss_statistics(payload,request,CUT)
        self.assertEqual(loss['multi_bucket_order_ids'],1)
        self.assertEqual(loss['unique_observed_order_ids'],2)
        self.assertEqual(loss['buckets']['dc']['amount_usd'],'130.09')
        self.assertEqual(loss['buckets']['ts']['order_id_coverage'],'partial')
        self.assertNotIn('cb',loss['buckets'])
        self.assertNotIn('912345671',str(loss))
        self.assertIsNone(loss['reshipment_and_recovery_net_cny'])
        opts=dict(as_of=AS_OF,layer_matches={})
        original=estimate_historical_cost([],LAYER,'PURCHASE_K',**opts)
        attached=estimate_historical_cost([],LAYER,'PURCHASE_K',admin_loss_statistics=[loss],**opts)
        self.assertEqual(attached.pop('admin_loss_statistics'),loss)
        self.assertEqual(attached,original)
        with self.assertRaisesRegex(ValueError,'admin_loss_request_scope_invalid'):
            project_admin_loss_statistics(payload,dict(request,cid=2),CUT)


def rows_for(offsets, *, quantity='1000K Coins + 30K Free x1 = $50'):
    for index, hours in enumerate(offsets):
        yield (f'private-order-{index}', CUT - timedelta(hours=hours), quantity)


def attachment(orders, *, observed=AS_OF, cost=None):
    selected, traces = {}, {}
    period = business_source.historical_period('7d', now=observed)['period']
    for identity, paid, quantity in orders:
        date = paid.strftime('%Y-%m-%d %H:%M:%S')
        selected[identity] = (dict(paidAt=date, salesUsd='50', status='已完成', coupons=[],
                                   costCny=cost, deliveryRows=1), {'discount_usd': '0'})
        traces[identity] = dict(aid='21587', before_discount='50', amount_usd_format='50',
                                amount_rmb_format='350', discount='100', points='0',
                                content=f'<span class="item">{quantity}</span>')
    provenance = dict(period=period, status='complete', canonical_archive_sha256='archive-revision',
                      ES_source_sha256='ES-revision', ES_complete=True, missing_product_identity=0)
    with patch.object(business_source, '_historical_provider_now', return_value=observed), \
         patch.object(business_source, '_period_population', return_value=(selected, provenance)), \
         patch.object(business_source, '_live_traces', return_value=(traces, {}, {})), \
         patch.object(business_source, 'historical_mix', return_value={'sha256': 'mix-revision'}):
        return business_source.collect_historical_attachment('7d', None, None)


def facts(orders, *, complete=False, captured=AS_OF, generated=None, cost='350',
          shipment_complete=True, site='266', cost_revision='cost-revision',
          cost_period=None, delivery_fields=None):
    admins, deliveries, completed = [], [], []
    source = 'www.mmoexp.com' if site == '266' else 'www.rsorder.com'
    for i, (identity, paid, _) in enumerate(orders):
        admins.append(dict(site_id=site, order_no=identity, site={'full_title': source}, gid='1327',
                           paytime=paid.strftime('%Y-%m-%d %H:%M:%S'), pay_status='1', status_format='已完成'))
        deliveries.append(dict(dict(source=source, sn=identity, delivery_id=str(i), genre='1',
                                    cost_total=cost, qty='1100', quantity_unit='K',
                                    trade_at=(paid + timedelta(minutes=10)).isoformat()), **(delivery_fields or {})))
        completed.append((site, identity))
    proof = dict(source_revision='Admin-revision', captured_at=captured.isoformat(), admin_complete=True,
                 cost=dict(source_revision=cost_revision, generated_at=(generated or captured).isoformat(),
                           order_cost_complete=complete, shipment_window_complete=shipment_complete,
                           period=SCOPE if cost_period is None else cost_period))
    # Expose actual_cost_cny in the fact to verify that it still requires envelope proof.
    return project_order_facts(admins, None, deliveries, scope=dict(SCOPE, site_id=site), source_coverage=proof,
                               complete_cost_orders=completed)


def fx(at=AS_OF, **overrides):
    return dict(dict(status='valid', cny_per_usd='7', checked_at=at.isoformat(),
                     published_at=at.strftime('%Y/%m/%d'), url=BOC_URL), **overrides)


def run(attachments, *, revisions=(), rate=None, as_of=AS_OF, basis='PURCHASE_K', matches=None,
        ordinary_forecast=False, current_cost=None):
    if matches is None:
        matches = {row['order_key']: dict(layer=LAYER, order_revision=row['source_sha256'],
                    available_at=row['available_at'], evidence_ref='verified-layer')
                   for item in reversed(attachments) for row in item['historical_orders']}
    return estimate_historical_cost(attachments, LAYER, basis, as_of=as_of, paid_cutoff=CUT,
                                    layer_matches=matches, fact_revisions=revisions, fx=rate,
                                    ordinary_forecast=ordinary_forecast, current_cost=current_cost)


class CostInputs(unittest.TestCase):
    def test_v6_delivery_median_uses_the_complete_three_hour_window_per_platform(self):
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost

        rows = [dict(platform='PS', record_id=str(i), status='valid', cny_per_1k=value,
                     trade_at=(AS_OF-timedelta(minutes=i*10)).isoformat())
                for i, value in enumerate(('.37', '.40', '.42', '.40', '.398', '.41', '.30'))]
        source = dict(platform='PS', checked_at=AS_OF.isoformat(),
                      v6_delivery_samples=dict(records=rows, window_complete=True, history_complete=True))
        before = deepcopy(source)
        result = smooth_delivery_cost(source, 'PS', AS_OF, '.40')
        self.assertEqual(result['cny_per_1k'], '0.40')
        self.assertEqual(result['sample_contract'], 'latest_3h_valid_order_delivery_median_v1')
        self.assertEqual(result['selected_count'], 7)
        self.assertEqual(result['window'], 'three_hours')
        self.assertEqual(smooth_delivery_cost(source, 'XBOX', AS_OF, '.4')['status'], 'missing')
        self.assertEqual(source, before)

    def test_current_samples_discard_thousandfold_costs_before_selecting_maximum(self):
        from fc_pricing_v3.cost_inputs_v6 import filter_cost_samples

        rows = [dict(record_id=str(i), cny_per_1k=value, cny_per_k=value)
                for i, value in enumerate(('.39', '.40', '.41', '.40', '390', '398'))]
        cost = dict(platform='PS', status='valid', sample_records=rows, cny_per_1k='398')
        result = filter_cost_samples(cost, '.40')
        self.assertEqual(result['cny_per_1k'], '.41')
        self.assertEqual(len(result['sample_records']), 4)
        self.assertEqual([row['record_id'] for row in result['sample_insurance']['outliers']], ['4', '5'])
        self.assertTrue(all(row['status'] == 'outlier' for row in result['sample_insurance']['outliers']))
        self.assertEqual(cost['cny_per_1k'], '398')

    def test_sparse_platform_falls_back_to_latest_six_after_filtering_and_requires_three(self):
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost

        for platform in ('PS', 'XBOX', 'PC'):
            rows = [dict(platform=platform, status='valid', record_id=str(i), cny_per_1k=value,
                         trade_at=(AS_OF-timedelta(minutes=age)).isoformat())
                    for i, (age, value) in enumerate(zip((0, 60, 120, 181, 200, 240, 260),
                                                        ('.37', '.40', '.42', '.40', '.398', '.41', '.7')))]
            source = dict(platform=platform, checked_at=AS_OF.isoformat(), v6_delivery_samples=dict(
                records=rows, window_complete=True, history_complete=False))
            result = smooth_delivery_cost(source, platform, AS_OF, '.4')
            self.assertEqual((result['cny_per_1k'], result['selected_count'], result['window']), ('0.40', 6, 'latest_six'))
            for count in (0, 2, 4):
                source['v6_delivery_samples']['records'] = rows[:count]
                self.assertEqual(smooth_delivery_cost(source, platform, AS_OF, '.4')['reason'],
                                 'ordinary_delivery_cost_sample_missing')
            source['v6_delivery_samples'].update(records=[], history_complete=True)
            self.assertEqual(smooth_delivery_cost(source, platform, AS_OF, '.4')['reason'],
                             'curve_cost_samples_insufficient')
            source['v6_delivery_samples']['records'] = rows[:2]
            self.assertEqual(smooth_delivery_cost(source, platform, AS_OF, '.4')['reason'], 'curve_cost_samples_insufficient')
            source['v6_delivery_samples']['records'] = rows[:2] + [dict(rows[-1], cny_per_1k='390')]
            rejected = smooth_delivery_cost(source, platform, AS_OF, '.4')
            self.assertEqual(rejected['reason'], 'curve_cost_sample_outlier')
            self.assertEqual(len(rejected['sample_insurance']['outliers']), 1)
            source['v6_delivery_samples'].update(records=rows, window_complete=False)
            self.assertEqual(smooth_delivery_cost(source, platform, AS_OF, '.4')['status'], 'missing')


    def test_insufficient_filtered_samples_make_the_platform_cost_unavailable(self):
        from fc_pricing_v3.cost_inputs_v6 import filter_cost_samples

        rows = [dict(cny_per_1k=value) for value in ('.4', '.4', '390', '398', '400', '400')]
        result = filter_cost_samples(dict(status='valid', sample_records=rows), '.4')
        self.assertEqual(result['status'], 'missing')
        self.assertEqual(result['reason'], 'curve_cost_sample_outlier')
        self.assertEqual(result['sample_insurance']['valid_count'], 2)
        for value, expected in (('.05', 'valid'), ('5', 'valid'), ('.049', 'missing'), ('5.01', 'missing')):
            self.assertEqual(filter_cost_samples(dict(status='valid', cny_per_1k=value))['status'], expected)

    def test_reads_complete_original_delivery_days_and_applies_only_newer_covered_rows(self):
        scope = dict(site_id='266', gid='1327', start='2026-11-06', end='2026-11-08')
        raw = dict(site_id='266', gid='1327', order_no='fixture-order', paytime='2026-11-06 10:00:00',
                   pay_status='1', status_format='已完成', site={'full_title':'www.mmoexp.com'})
        shared = dict(rows=[raw], dataset=None, identity_catalog=None,
                      coverage=dict(admin_complete=True, source_revision='shared-revision',
                                    captured_at='2026-11-09T10:00:00+08:00'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'delivery-days').mkdir()
            for day, rows in (('2026-11-06', [('1','20')]), ('2026-11-07', [('2','30'),('3','40')])):
                path = root/'delivery-days'/(day+'.json')
                data = dict(contract='channel-order-deliveries-v1', complete=True,
                    generatedAt=day+'T23:59:59+08:00', period=dict(start=day,end=day), rows=[
                        dict(source='www.mmoexp.com', sn='fixture-order', delivery_id=ident, genre='1',
                             cost_total=cost, trade_at=day+' 11:00:00') for ident,cost in rows])
                path.write_text(json.dumps(data), encoding='utf-8')
            latest = dict(data, generatedAt='2026-11-09T12:00:00+08:00',
                period=dict(start='2026-11-07',end='2026-11-08',until='2026-11-08 08:00'),
                rows=[dict(data['rows'][0], cost_total='50')])
            (root/'order-deliveries.json').write_text(json.dumps(latest), encoding='utf-8')
            result = runtime.ordinary_delivery_archives(scope, shared, root=root)
            from order_delivery_index import sync
            revision = sync(root)
            indexed = runtime.ordinary_delivery_archives(scope, shared, root=root)
            self.assertEqual(indexed['orders'][0]['observed_cost_cny'],result['orders'][0]['observed_cost_cny'])
            self.assertEqual({x['cost_record_id'] for x in indexed['orders'][0]['cost_records']},
                             {x['cost_record_id'] for x in result['orders'][0]['cost_records']})
            self.assertFalse(indexed['source_coverage']['cost']['order_cost_complete'])
            self.assertEqual(indexed['source_coverage']['cost']['index_revision'],revision)
        proof = result['source_coverage']['cost']
        self.assertEqual(len(proof['shipment_windows']), 3)
        self.assertFalse(proof['order_cost_complete'])
        self.assertEqual(result['orders'][0]['observed_cost_cny'], '70')
        self.assertEqual({item['cost_record_id'] for item in result['orders'][0]['cost_records']}, {'1','2'})

    def test_complete_ordinary_delivery_supports_forecast_without_relabeling_historical_cost(self):
        orders = list(rows_for([2] * 10, quantity='2500K Coins + 60K Free x1 = $200'))
        original = attachment(orders)
        fields = dict(qty='2560', gift='0', cost_unit='0.390000', quantity_unit=None)
        fact = facts(orders, cost='998.40', delivery_fields=fields)
        before = deepcopy(fact)
        result = run([original], revisions=[fact], rate=fx(), basis='PROMISED_DELIVERED_K',
                     ordinary_forecast=True)
        self.assertEqual(result['status'], 'calculated')
        self.assertEqual(result['cost_basis'], ORDINARY_COST_BASIS)
        self.assertEqual(result['selected_window']['ordinary_delivery_orders'], 10)
        self.assertFalse(result['order_cost_source']['order_cost_complete'])
        expected = result['diagnostic_estimate']['expected_unit_usd']
        self.assertAlmostEqual(expected, Decimal('.39') / 7)
        self.assertEqual(result['diagnostic_estimate']['safe_unit_usd'], expected)
        self.assertAlmostEqual(result['diagnostic_estimate']['stress_unit_usd'], expected)
        self.assertEqual(fact, before)
        for kwargs, expected_gap in (
                (dict(shipment_complete=False), 'ordinary_delivery_window_unverified'),
                (dict(delivery_fields=dict(fields, qty='2559')), 'ordinary_delivery_cost_sample_missing'),
                (dict(delivery_fields=dict(fields, trade_at=(CUT + timedelta(hours=1)).isoformat())),
                 'ordinary_delivery_cost_sample_missing')):
            options = dict(cost='998.40', delivery_fields=fields) | kwargs
            failed = run([original], revisions=[facts(orders, **options)], rate=fx(), ordinary_forecast=True)
            self.assertEqual(failed['status'], 'PROOF_INCOMPLETE')
            self.assertIn(expected_gap, failed['gaps'])

    def test_same_layer_upper_covers_missing_cost_and_never_understates_observed_partial(self):
        orders = list(rows_for([2, 3, 4], quantity='2500K Coins + 60K Free x1 = $200'))
        fields = dict(qty='2560', gift='0', cost_unit='0.390000', quantity_unit=None)
        source = attachment(orders)
        fixed = dict(rate=fx(), basis='PROMISED_DELIVERED_K', ordinary_forecast=True)
        subset = facts(orders[:2], cost='998.40', delivery_fields=fields)
        result = run([source], revisions=[subset], **fixed)
        self.assertEqual(result['status'], 'calculated')
        self.assertEqual(result['cost_upper_source']['source'], 'up_to_six_latest_same_layer_ordinary_delivery_cost_max')
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)
        all_orders = facts(orders, cost='998.40', delivery_fields=fields)
        partial = all_orders['orders'][-1]
        partial['observed_cost_cny'] = '1280'
        partial['cost_records'][0].update(quantity='2559', cost_cny='1280')
        blocked = run([source], revisions=[all_orders], **fixed)
        self.assertIn('upper_below_known_partial', blocked['gaps'])
        current = dict(platform='PS', status='valid', game='FC27', product='Game Coins', unit='CNY/K',
                       genre='1', record_id='7', cny_per_1k='.55', checked_at=AS_OF.isoformat(),
                       trade_at=(AS_OF-timedelta(hours=1)).isoformat())
        supported = run([source], revisions=[all_orders], current_cost=current, **fixed)
        self.assertEqual(supported['status'], 'calculated')
        self.assertEqual(supported['cost_upper_source']['record_id'], '7')
        self.assertAlmostEqual(supported['diagnostic_estimate']['safe_unit_usd'], Decimal('.55')/7)
        other = run([source], revisions=[all_orders], current_cost=dict(current, platform='PC'), **fixed)
        self.assertIn('upper_below_known_partial', other['gaps'])
        self.assertIsNone(other['current_cost_source'])

    def test_recent_cost_bound_cannot_fall_below_observed_cohort_mean(self):
        orders = list(rows_for(range(2, 10), quantity='2500K Coins + 60K Free x1 = $200'))
        data = facts(orders, cost='768', delivery_fields=dict(qty='2560', gift='0', cost_unit='.30'))
        older = data['orders'][-1]
        older['observed_cost_cny'] = '1280'
        older['cost_records'][0].update(cost_cny='1280', cost_unit_cny='.50')
        result = run([attachment(orders)], revisions=[data], rate=fx(), basis='PROMISED_DELIVERED_K',
                     ordinary_forecast=True)
        self.assertEqual(result['status'], 'calculated', result['gaps'])
        self.assertEqual(result['cost_upper_source']['source'], 'same_layer_complete_delivery_cohort_max')
        self.assertAlmostEqual(result['diagnostic_estimate']['stress_unit_usd'], Decimal('.50') / 7)

    def test_reconciled_partial_ordinary_shipment_raises_bound_without_becoming_complete(self):
        orders = list(rows_for([2, 3, 4], quantity='6000K Coins + 150K Free x1 = $450'))
        source = attachment(orders)
        data = facts(orders, cost='2583', delivery_fields=dict(qty='6150', gift='0', cost_unit='.42'))
        partial = data['orders'][-1]
        partial.update(status='处理中', observed_cost_cny='2644.50')
        partial['cost_records'][0].update(cost_cny='2644.50', cost_unit_cny='.43')
        result = run([source], revisions=[data], rate=fx(), basis='PROMISED_DELIVERED_K', ordinary_forecast=True)
        self.assertEqual(result['status'], 'calculated', result['gaps'])
        self.assertEqual(result['selected_window']['ordinary_delivery_orders'], 2)
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)
        self.assertEqual(result['diagnostic_estimate']['known_partial_usd'], Decimal('2644.50') / 7)
        self.assertAlmostEqual(result['diagnostic_estimate']['expected_unit_usd'], Decimal('.42') / 7)
        self.assertAlmostEqual(result['diagnostic_estimate']['safe_unit_usd'], ((Decimal('.42') * 2 + Decimal('.43')) / 3) / 7)
        self.assertAlmostEqual(result['diagnostic_estimate']['stress_unit_usd'], Decimal('.43') / 7)
        upper = result['cost_upper_source']
        self.assertEqual(upper['source'], 'same_layer_ordinary_delivery_observed_partial_floor')
        self.assertEqual(upper['base_upper_source']['source'], 'up_to_six_latest_same_layer_ordinary_delivery_cost_max')
        self.assertEqual(upper['cny_per_basis_k'], '0.43')
        self.assertNotIn(orders[-1][0], str(result))

    def test_completed_overdelivery_raises_existing_bound_using_promised_quantity(self):
        orders = list(rows_for([2, 3, 4], quantity='5000K Coins + 250K Free x1 = $400'))
        source = attachment(orders)
        data = facts(orders, cost='1942.50', delivery_fields=dict(qty='5250', gift='0', cost_unit='.37'))
        over = data['orders'][-1]
        over.update(observed_cost_cny='2025')
        over['cost_records'][0].update(quantity='6750', cost_cny='2025', cost_unit_cny='.30')
        before = deepcopy(data)
        options = dict(rate=fx(), basis='PROMISED_DELIVERED_K', ordinary_forecast=True)
        result = run([source], revisions=[data], **options)
        self.assertEqual(result['status'], 'calculated', result['gaps'])
        self.assertEqual(result['selected_window']['ordinary_delivery_orders'], 2)
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)
        self.assertAlmostEqual(result['diagnostic_estimate']['expected_unit_usd'], Decimal('.37') / 7)
        self.assertEqual(result['diagnostic_estimate']['known_partial_usd'], Decimal('2025') / 7)
        self.assertAlmostEqual(result['diagnostic_estimate']['stress_unit_usd'], Decimal('2025') / 5250 / 7)
        self.assertEqual(result['cost_upper_source']['source'], 'same_layer_ordinary_delivery_observed_partial_floor')
        self.assertEqual(data, before)
        for status, unit in [('处理中', '.30'), ('已完成', '.31')]:
            invalid = deepcopy(data)
            invalid['orders'][-1]['status'] = status
            invalid['orders'][-1]['cost_records'][0]['cost_unit_cny'] = unit
            blocked = run([source], revisions=[invalid], **options)
            self.assertIn('upper_below_known_partial', blocked['gaps'])

    def test_completed_single_million_delivery_keeps_its_original_cny_total(self):
        orders = list(rows_for([2, 3, 4], quantity='2000K Coins + 60K Free x1 = $160'))
        source = attachment(orders)
        data = facts(orders, cost='824', delivery_fields=dict(qty='2060', gift='0', cost_unit='.40'))
        old = data['orders'][-1]
        old['observed_cost_cny'] = '865.20'
        old['cost_records'][0].update(quantity='2.06', cost_unit_cny='420', cost_cny='865.20')
        before = deepcopy(data)
        options = dict(rate=fx(), basis='PROMISED_DELIVERED_K', ordinary_forecast=True)
        proven = run([source], revisions=[data], **options)
        self.assertEqual(proven['status'], 'calculated', proven['gaps'])
        self.assertEqual(proven['selected_window']['ordinary_delivery_orders'], 3)
        self.assertAlmostEqual(proven['diagnostic_estimate']['stress_unit_usd'], Decimal('.42') / 7)
        self.assertEqual(data, before)

        for incomplete, split in ((True, False), (False, True)):
            with self.subTest(incomplete=incomplete, split=split):
                unsafe = deepcopy(data)
                order = unsafe['orders'][-1]
                if incomplete:
                    order['status'] = '处理中'
                if split:
                    order['cost_records'].append(dict(order['cost_records'][0],
                        cost_record_id='balancing-record', quantity='2057.94',
                        cost_unit_cny='0.00001', cost_cny='.02'))
                    order['observed_cost_cny'] = '865.22'
                blocked = run([source], revisions=[unsafe], **options)
                self.assertIn('upper_below_known_partial', blocked['gaps'])

    def test_attachment_amount_is_cny_observation_and_never_rewrites_actuals(self):
        orders = list(rows_for([1]))
        original = attachment(orders, cost='70')
        before = deepcopy(original)
        result = run([original])
        self.assertEqual(original, before)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertEqual(result['time_basis'], 'payment_cohort')
        self.assertIn('procurement_time_unverified', result['gaps'])
        self.assertIn('forecast_fx_unavailable_as_of', result['gaps'])
        self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('70'))
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)
        self.assertIsNone(result['diagnostic_estimate']['expected_unit_usd'])

    def test_d2_same_private_order_is_joined_without_counting_source_amount_twice(self):
        orders = list(rows_for([1]))
        original = attachment(orders, cost='100')
        data = facts(orders, cost='140')
        result = run([original], revisions=[data], rate=fx())
        self.assertEqual(result['selected_window']['known_cost_cny'], Decimal('140'))
        self.assertEqual(result['diagnostic_estimate']['known_partial_usd'], Decimal('20'))
        self.assertEqual(result['selected_window']['complete_comparable_orders'], 0)
        self.assertIn('order_cost_completeness_unverified', result['gaps'])
        self.assertNotIn(orders[0][0], str(result))
        result = run([original], revisions=[facts(orders, site='320')], rate=fx())
        self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('100'))

    def test_same_order_coins_quantity_corroborates_cost_without_marking_it_complete(self):
        orders = list(rows_for([1], quantity='2500K Coins + 60K Free x1 = $200'))
        source = attachment(orders)
        inputs = dict(qty='2560', gift='0', cost_unit='0.390000', quantity_unit=None)
        good = run([source], revisions=[facts(orders, cost='998.40', delivery_fields=inputs)], rate=fx())
        self.assertEqual(good['selected_window']['order_delivery_quantity_evidence'], {'matches_promised_delivered_k': 1})
        self.assertEqual(good['selected_window']['known_partial_cost_cny'], Decimal('998.40'))
        self.assertEqual(good['status'], 'PROOF_INCOMPLETE')
        for fields in ({'qty':'1','gift':'2559'}, {'cost_unit':None}, {'qty':'2559'}):
            with self.subTest(fields=fields):
                result = run([source], revisions=[facts(orders, cost='998.40', delivery_fields=dict(inputs, **fields))], rate=fx())
                self.assertEqual(result['selected_window']['order_delivery_quantity_evidence'], {'unverified': 1})
                self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('998.40'))

    def test_window_widens_only_when_complete_comparable_samples_are_short(self):
        for recent_count, expected in [(9, 168), (10, 72)]:
            with self.subTest(recent=recent_count):
                orders = list(rows_for([1] * recent_count + [72, 90, 168, 169]))
                # Unknown denominator does not count as a complete comparable sample.
                orders[0] = (*orders[0][:2], 'not a native quantity')
                if recent_count == 10:
                    orders.append(('extra-recent', CUT - timedelta(hours=2), '1000K Coins x1 = $50'))
                value = run([attachment(orders)], revisions=[facts(orders, complete=True)], rate=fx())
                self.assertEqual(value['window_hours'], expected)
                self.assertEqual(value['recent_72h']['complete_comparable_orders'],
                                 recent_count if expected == 168 else recent_count + 1)
                self.assertEqual(value['diagnostic_estimate']['unknown_quantity_orders'], 1)
                self.assertEqual(value['diagnostic_estimate']['unallocated_known_cost_usd'], Decimal('50'))
                self.assertEqual(value['diagnostic_estimate']['expected_unit_usd'], Decimal('.05'))

    def test_recent_threshold_and_window_start_are_inclusive(self):
        orders = list(rows_for([1] * 9 + [72, 90]))
        result = run([attachment(orders)], revisions=[facts(orders, complete=True)], rate=fx())
        self.assertEqual(result['window_hours'], 72)
        self.assertEqual(result['selected_window']['complete_comparable_orders'], 10)
        self.assertEqual(result['selected_window']['paid_by_beijing_day'], {'2026-11-10': 1, '2026-11-12': 9})
        self.assertEqual(result['diagnostic_estimate']['expected_unit_usd'], Decimal('.05'))

    def test_replay_excludes_future_cost_revision_and_future_fx(self):
        orders = list(rows_for([1]))
        visible = attachment(orders, cost='70')
        late = AS_OF + timedelta(minutes=15)
        future = attachment(orders, observed=late, cost='140')
        original_facts = facts(orders, cost='70', cost_revision='original-cost')
        revised_facts = facts(orders, complete=True, cost='140', captured=late, cost_revision='revised-cost')
        replay = run([visible, future], revisions=[revised_facts, original_facts], rate=fx(late))
        self.assertEqual(replay['attachment_revision'], visible['source_sha256'])
        self.assertEqual(replay['order_cost_source']['source_revision'], 'original-cost')
        self.assertEqual(replay['selected_window']['known_partial_cost_cny'], Decimal('70'))
        self.assertIsNone(replay['forecast_fx'])
        refreshed = run([future, visible], revisions=[original_facts, revised_facts], as_of=late, rate=fx(late),
                        matches={row['order_key']: dict(layer=LAYER, order_revision=row['source_sha256'],
                                 available_at=row['available_at'], evidence_ref='verified-layer')
                                 for row in future['historical_orders']})
        self.assertEqual(refreshed['attachment_revision'], future['source_sha256'])
        self.assertEqual(refreshed['selected_window']['complete_comparable_orders'], 1)
        self.assertEqual(refreshed['diagnostic_estimate']['expected_unit_usd'], Decimal('.02'))

    def test_actual_shipped_quantity_cannot_change_promised_denominator(self):
        orders = list(rows_for([1, 2]))
        result = run([attachment(orders)], revisions=[facts(orders[:1], complete=True)], rate=fx(),
                     basis='PROMISED_DELIVERED_K')
        estimate = result['diagnostic_estimate']
        self.assertEqual(estimate['known_quantity_k'], Decimal(2060))
        self.assertEqual(estimate['alpha'], Decimal('.5'))
        self.assertEqual(estimate['expected_unit_usd'] * Decimal(1030), Decimal('50'))
        self.assertIsNone(estimate['safe_unit_usd'])

    def test_complete_claim_requires_trade_in_source_cost_scope(self):
        orders = list(rows_for([1]))
        original = attachment(orders)
        narrow = dict(start='2026-11-12', end='2026-11-12', until='2026-11-12 23:09')
        result = run([original], revisions=[facts(orders, complete=True, cost_period=narrow)], rate=fx())
        self.assertEqual(result['selected_window']['complete_comparable_orders'], 0)
        self.assertEqual(result['selected_window']['known_partial_cost_cny'], Decimal('350'))

    def test_no_delivery_records_remains_unknown_even_when_d2_observed_sum_is_zero(self):
        orders = list(rows_for([1]))
        source = facts(orders, cost=None)
        self.assertEqual(source['orders'][0]['observed_cost_cny'], '0')
        result = run([attachment(orders)], revisions=[source], rate=fx())
        self.assertIsNone(result['selected_window']['known_partial_cost_cny'])
        self.assertEqual(result['diagnostic_estimate']['incomplete_cost_orders'], 1)

    def test_consumes_existing_archived_boc_evidence_schema(self):
        recorded = json.loads((ROOT / 'tests/fixtures/d8-lowest-anchor.json').read_text(encoding='utf-8'))
        rate = recorded['evidence']['fx']
        captured = datetime.fromisoformat(rate['checked_at'])
        value = estimate_historical_cost([], LAYER, 'PURCHASE_K', as_of=captured, layer_matches={}, fx=rate)
        self.assertEqual(value['forecast_fx']['cny_per_usd'], rate['cny_per_usd'])
        self.assertEqual(value['forecast_fx']['available_at'], captured.isoformat())

    def test_unmapped_layer_and_wrong_fx_stay_unavailable(self):
        orders = list(rows_for([1]))
        original = attachment(orders, cost='350')
        cases = [fx(AS_OF - timedelta(minutes=61)), fx(url='wrong'), fx(published_at='2026/11/14')]
        for rate in cases:
            with self.subTest(rate=rate):
                result = run([original], rate=rate, matches={})
                self.assertIn('cost_layer_unverified', result['gaps'])
                self.assertIn('forecast_fx_unavailable_as_of', result['gaps'])
                self.assertEqual(result['selected_window']['orders_with_known_cny'], 0)


if __name__ == '__main__':
    unittest.main()

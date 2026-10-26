import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3 import business_source as source
from fc_pricing_v3.financial import required_history_ratio

PERIOD = dict(start='2026-10-19', end='2026-10-25')


def fixture():
    archived = dict(salesUsd='9.50', coupons=[], customerType='新客', status='已完成', costCny='30', saleCny='65')
    selected = {'private-order': (archived, dict(discount_usd='.50'))}
    orders = {'private-order': dict(before_discount='10', discount='95', points=0, amount_usd_format='$9.50',
                                   is_region_price=0, region_price_factor=0, discount_code='private-code')}
    provenance = dict(status='complete', period=PERIOD, canonical_archive_sha256='a' * 64,
                      ES_source_sha256='b' * 64, ES_complete=True, missing_product_identity=0)
    return selected, orders, provenance


class BusinessSourceTest(unittest.TestCase):
    def test_private_historical_attachment_uses_actual_CNY_cost_and_current_Admin_snapshot_revenue(self):
        selected, orders, provenance = fixture()
        selected['private-order'][0].update(paidAt='2026-10-23 10:00:00',deliveryRows=2,saleCny='999')
        orders['private-order'].update(amount_rmb_format='¥70.00',aid=21587,
            content='<span class="item">500 K coins+25K Free x 2 = $9.50</span>')
        observed=datetime(2026,10,26,12,tzinfo=timezone.utc)
        rows, coverage=source.historical_attachment(selected,orders,{},provenance,observed)
        row=rows[0]
        self.assertEqual((row['revenue_cny'],row['cost_cny'],row['actual_cny_gross']),('70.00','30','40.00'))
        self.assertIsNone(row['cost_usd'])
        self.assertIsNone(row['historical_fx'])
        self.assertEqual((row['base_k'],row['bonus_k'],row['delivered_k']),('1000','50','1050'))
        self.assertEqual(row['regular_usd'],'10')
        self.assertEqual(row['available_at'],observed.isoformat())
        self.assertNotEqual(row['available_at'],row['paid_at'])
        self.assertNotIn('private-order',json.dumps(rows))
        self.assertNotIn('private-code',json.dumps(rows))
        self.assertEqual(coverage['original_mix_sha256'],source.historical_mix(selected,provenance)['sha256'])

    def test_historical_actual_coupon_deduction_does_not_invent_fixed_counterfactual_terms(self):
        selected, orders, provenance=fixture()
        selected['private-order'][0].update(coupons=[dict(id=1)],salesUsd='8')
        selected['private-order'][1]['discount_usd']='2'
        orders['private-order'].update(discount=100,amount_usd_format='8')
        rows,coverage=source.historical_attachment(selected,orders,{'1':dict(discount_amount='2')},provenance,datetime.now(timezone.utc))
        self.assertIsNone(rows[0]['promotion_path'])
        self.assertEqual(rows[0]['actual_promotion_reconstruction']['actual_coupon_discount_usd'],'2')
        self.assertEqual(coverage['gaps']['historical_counterfactual_promotion_terms_version_missing'],1)

    def test_history_missing_actual_delivery_cost_is_unknown_even_if_archived_amount_exists(self):
        selected,orders,provenance=fixture()
        orders['private-order']['amount_rmb_format']='70'
        rows,_=source.historical_attachment(selected,orders,{},provenance,datetime.now(timezone.utc))
        self.assertIsNone(rows[0]['cost_cny'])
        self.assertIsNone(rows[0]['actual_cny_gross'])
        selected['private-order'][0].update(costCny='0',zeroCost=True)
        rows,_=source.historical_attachment(selected,orders,{},provenance,datetime.now(timezone.utc))
        self.assertEqual(rows[0]['cost_cny'],'0')

    def test_history_preserves_regional_regular_basis_and_unknown_price_version(self):
        selected,orders,provenance=fixture()
        orders['private-order'].update(before_discount='9.1',is_region_price=1,region_price_factor='.91',region_price_lang_region_id=39)
        rows,coverage=source.historical_attachment(selected,orders,{},provenance,datetime.now(timezone.utc))
        self.assertEqual((rows[0]['regular_usd'],rows[0]['original_region_factor'],rows[0]['region_id']),('9.1','0.91',39))
        self.assertIsNone(rows[0]['price_version'])
        self.assertIsNone(rows[0]['package_retained_ratio'])
        self.assertEqual(coverage['period'],PERIOD)
        self.assertIn('14d_28d_month',coverage['longer_window_coverage'])

    def test_fixed_coupon_is_replayed_as_fixed_with_threshold_and_cap(self):
        order = dict(before_discount='9.10', discount='100', points=0)
        logs = [dict(coupon_id=1, discount_amount='2')]
        templates = {'1': dict(mode_type=1, reduce='2', attain='5', max_reduce='0', is_open=0)}
        path = source.promotion_path(order, '2', logs, templates)
        self.assertEqual(path, dict(kind='fixed', discount_usd='2', threshold_usd='5', cap_usd=None))
        templates['1'].update(mode_type=2, reduce='70', max_reduce='50')
        path = source.promotion_path(order, '2', logs, templates)
        self.assertEqual(path['retained_ratio'], '0.7')
        self.assertEqual(path['cap_usd'], '50')

    def test_points_value_cap_and_exclusivity(self):
        path = source.promotion_path(dict(before_discount='10', discount=100, points=100), '1', [], {})
        self.assertEqual(path, dict(kind='points', credit_usd='1', cap_ratio='0.10'))
        with self.assertRaisesRegex(ValueError, 'points_exclusivity_or_cap'):
            source.promotion_path(dict(before_discount='10', discount=100, points=200), '2', [], {})

    def test_guest_unknown_is_not_new_and_missing_cost_is_not_zero(self):
        selected, _, _ = fixture()
        selected['private-order'][0].update(customerType='新老客未提供', costCny=None)
        result = source.summarize(selected)
        self.assertIsNone(result['new_customer_order_ratio'])
        self.assertIsNone(result['effective_new_customers'])
        self.assertNotIn('covered_cost_cny', result)

    def test_same_population_mix_and_identity_free_replay(self):
        selected, orders, provenance = fixture()
        replay = source.build_replay(selected, orders, {}, {}, provenance)
        mix = source.historical_mix(selected, provenance)
        self.assertEqual(replay['eligible_count'], mix['eligible_orders'])
        self.assertEqual(replay['original_amount_weight_usd'], mix['undiscounted_order_usd'])
        self.assertEqual(replay['status'], 'verified')
        self.assertNotIn('private-order', json.dumps(replay))
        self.assertNotIn('private-code', json.dumps(replay))
        self.assertEqual(str(required_history_ratio(dict(historical_discount_mix=mix), datetime(2026, 10, 26, tzinfo=timezone.utc))), '0.95')

    def test_unknown_path_is_visible_and_does_not_claim_complete(self):
        selected, orders, provenance = fixture()
        orders['private-order']['points'] = 50
        result = source.build_replay(selected, orders, {}, {}, provenance)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['failures']['history_discount_layer_mismatch'], 1)

    def test_closed_day_mtd_and_no_quantity_fabrication(self):
        selected, orders, provenance = fixture()
        storefront = dict(rows={p: dict(package_usd='10') for p in ('PS', 'XBOX', 'PC')})
        with patch.object(source, '_period_population', return_value=(selected, provenance)), patch.object(source, '_live_traces', return_value=(orders, {}, {})), patch.object(source, '_today_summary', return_value=dict(status='unavailable', net_paid_usd=None)), patch.dict(sys.modules, {'pricing_sources': SimpleNamespace(active=lambda *a, **k: True)}):
            result = source.collect(None, None, storefront, [])
        self.assertEqual(result['monthly_target']['mtd_status'], 'closed_days_only')
        self.assertIsNone(result['monthly_target']['today']['net_paid_usd'])
        self.assertEqual(result['demand_model']['coverage']['quantity_known_orders'], 0)
        self.assertEqual(result['history_replay']['original_mix_sha256'], result['historical_discount_mix']['sha256'])

    def test_uid_zero_email_is_included_and_new_people_are_not_order_counts(self):
        selected, orders, _ = fixture()
        orders['private-order'].update(email='Guest@Example.com', uid=0)
        selected['private-second'] = selected['private-order']
        orders['private-second'] = dict(orders['private-order'], email='guest@example.com')
        _, assignments, coverage = source._customer_assignments(selected, orders)
        self.assertEqual(coverage['effective_new_customers'], 1)
        self.assertEqual(coverage['eligible_orders'], 2)
        self.assertEqual(len(assignments), 1)
        self.assertEqual(source.summarize(selected)['coverage']['new_customer_orders'], 2)

    def test_inactive_historical_coupon_is_explicit_current_terms_projection(self):
        order = dict(before_discount='10', discount='100', points=0)
        path = source.promotion_path(order, '2', [dict(coupon_id=1, discount_amount='2')],
            {'1': dict(_current_active=False, mode_type=2, reduce=80, attain=0, max_reduce=0, is_open=0)})
        self.assertEqual(path, dict(kind='none'))

    def test_fractional_cent_code_discount_uses_real_round_up_deduction(self):
        selected, orders, provenance = fixture()
        selected['private-order'][0]['salesUsd'] = '271.58'
        selected['private-order'][1]['discount_usd'] = '23.62'
        orders['private-order'].update(before_discount='295.20', discount='92', amount_usd_format='$271.58')
        result = source.build_replay(selected, orders, {}, {}, provenance)
        self.assertTrue(result['basis_lower_bound_sufficient'])
        self.assertEqual(result['residual_minimum_usd'], '0.00')
        self.assertEqual(result['coverage'].get('net_residual_negative', 0), 0)

    def test_region_layer_has_its_own_population_and_original_lower_bound(self):
        selected, orders, provenance = fixture()
        orders['private-order'].update(is_region_price=1, region_price_factor='.91', region_price_lang_region_id=39)
        result = source.build_replay(selected, orders, {}, {}, provenance)
        layer = result['region_layers']['39']
        self.assertEqual(layer['eligible_count'], 1)
        self.assertTrue(layer['basis_lower_bound_sufficient'])
        self.assertEqual(layer['source_scope'], 'actual_region_39')

    def test_partial_closed_day_mtd_is_a_bounded_interval_not_zero_or_unavailable(self):
        selected, orders, provenance = fixture()
        month_source = dict(provenance, status='partial', missing_product_identity=8, unclassified_paid_FC_usd='10.34')
        storefront = dict(rows={p: dict(package_usd='10') for p in ('PS', 'XBOX', 'PC')})
        with patch.object(source, '_period_population', side_effect=[(selected, provenance), (selected, month_source)]), patch.object(source, '_live_traces', return_value=(orders, {}, {})), patch.object(source, '_today_summary', return_value=dict(status='unavailable', net_paid_usd=None)), patch.dict(sys.modules, {'pricing_sources': SimpleNamespace(active=lambda *a, **k: True)}):
            monthly = source.collect(None, None, storefront, [])['monthly_target']
        self.assertEqual(monthly['mtd_status'], 'partial_closed_day_interval')
        self.assertEqual(monthly['mtd_lower_bound'], '9.50')
        self.assertEqual(monthly['mtd_upper_bound'], '19.84')
        self.assertIsNone(monthly['mtd_exact'])
        self.assertIsNone(monthly['today']['net_paid_usd'])

    def test_order_rate_uses_six_hour_blocks_over_actual_period(self):
        selected, orders, provenance = fixture()
        archived, es = selected['private-order']
        selected = {str(i): (archived, es) for i in range(168)}
        orders = {str(i): dict(orders['private-order'], content='PlayStation 4|5') for i in range(168)}
        storefront = dict(rows={p: dict(package_usd='10') for p in ('PS', 'XBOX', 'PC')})
        model = source.demand_snapshot(selected, orders, storefront, provenance)
        self.assertEqual(model['rate_window_hours'], 6)
        self.assertEqual(model['observed_window_hours'], '168.0')
        self.assertEqual(model['groups']['console']['observed_orders_per_block'], '6')

    def test_native_quantity_includes_historical_gift_and_line_multipliers(self):
        value = source._quantity(dict(content='<span class="item">&#12288;☑500 K coins+25K Free x 2 = $89.50, </span><span class="item">☑200 K coins x 3 = $62.64, </span>'))
        self.assertEqual(value['purchase_k'], '1600')
        self.assertEqual(value['bonus_k'], '50')
        self.assertEqual(value['delivered_k'], '1650')
        self.assertEqual(value['lines'][0]['multiplier'], 2)
        self.assertIsNone(source._quantity(dict(content='<span class="item">Player card 500 x 1 = $20</span>')))

    def test_platform_prefers_native_aid_and_accepts_verified_old_native_server_labels(self):
        self.assertEqual(source._platform(dict(aid=21589, content='Xbox Series X|S')), 'PC')
        self.assertEqual(source._platform(dict(content='[Xbox Series X|S]')), 'XBOX')
        self.assertEqual(source._platform(dict(content='FC 27 >>> [PlayStation 5]')), 'PS')
        self.assertEqual(source._platform(dict(aid=21589,content='[PlayStation 5]')), 'PC')
        self.assertIsNone(source._platform(dict(content='[PlayStation 5] [PC Platform]')))
        self.assertIsNone(source._platform(dict(content='PS5 account for sale')))
        self.assertIsNone(source._platform(dict(content='PlayStation 5 account for sale')))
        self.assertEqual(source._platform(dict(content='[<span>PlayStation 5</span>]')), 'PS')
        self.assertIsNone(source._platform(dict(content='unknown platform')))

    def test_ads_fixed_context_never_divides_project_spend_by_coins_customers(self):
        projected = dict(ads_accounts=[dict(coverage=dict(query_range_complete=True), campaigns=dict(calculation_complete=True, rejected_rows=0, rows=[
            dict(game_target='FC27', campaign_scope='project', metrics=dict(cost='10')),
            dict(project_game='FC27', metric_scope='cross_game', metrics=dict(cost='2'))]))], sources={})
        published = SimpleNamespace(read_bytes=lambda: b'{}')
        with patch.dict(sys.modules, {'marketing_snapshot': SimpleNamespace(PUBLISHED=published, LIMIT=1000, projection=lambda *a: projected)}):
            context = source.marketing_context(PERIOD)
        self.assertEqual(context['fc_project_total_cost_usd'], '12')
        self.assertIsNone(context['Coins_attributed_cost_usd'])
        self.assertIsNone(context['incremental_CAC_usd'])

    def test_observed_paid_cohort_throughput_is_not_a_promised_capacity(self):
        selected, orders, provenance = fixture()
        rows = [dict(sn='private-order', trade_at='2026-10-20 12:00:00', qty='500', gift='25'),
                dict(sn='other-cohort', trade_at='2026-10-20 12:00:00', qty='1000', gift='0')]
        with patch.dict(sys.modules, {'channel_source': SimpleNamespace(load_costs=lambda: (rows, {}))}):
            context = source.fulfillment_context(selected, orders, provenance)
        self.assertEqual(context['observed_delivered_k'], '525')
        self.assertEqual(context['observed_delivered_k_per_block'], '18.75')
        self.assertIsNone(context['promised_capacity_k_per_block'])

    def test_backlog_only_normal_delivery_excludes_customer_action_and_problems(self):
        def pages(session, path, filters, limit):
            progress = int(filters[-1][2])
            states = {1: (11, 12), 2: (21, 22), 3: (31, 32, 33, 34)}[progress]
            return [dict(site_id=266, gid=1327, pay_status=1, status=state,
                         order_no='normal' if state != 33 else 'paused',
                         content='<span class="item">500 K coins+25K Free x 1 = $40</span>') for state in states]
        with patch.dict(sys.modules, {'channel_source': SimpleNamespace(apply_cost_overrides=lambda value: {})}), patch.object(source, '_normal_order_queue', return_value=({'normal'}, {})):
            result = source.active_backlog_context(None, pages)
        self.assertEqual(result['counts']['active_Coins_orders'], 3)
        self.assertEqual(result['gross_ordered_delivery_k'], '1575')
        self.assertEqual(set(result['by_status']), {'11', '21', '31'})

    def window_fixture(self):
        now = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
        created = datetime(2026, 10, 26, 0, 30, tzinfo=timezone.utc)
        order = dict(order_no='private-live-order', site_id=266, gid=1327, aid=21587, timestamp=int(created.timestamp()),
                     timestamp_format='2026-10-26 08:30:00', paytime='2026-10-26 09:00:00', pay_status=1,
                     content='<span class="item">100 K coins+5K Free x 1 = $8.68</span>',
                     before_discount='8.68', discount=100, points=0, amount_usd_format='$8.68', is_region_price=0)
        window = dict(operation_id='op', origin='confirmed_public_price_window', mode='production',
                      opened_at='2026-10-26T00:00:00+00:00', closed_at=None, platforms=['PS'], mutable_resources=['base:console'],
                      action=dict(base_prices=dict(console='8.68'), region_coefficients={}),
                      budget_reference=dict(base_prices=dict(console='10'), region_coefficients={}),
                      catalog=dict(PS=dict(tiers=[dict(base_k='100', bonus_k='5', retained_ratio='1')])),
                      assignment_probability='1', randomization_verified=False)
        return now, order, window

    def test_no_window_has_explicit_await_first_exposure_and_no_queries(self):
        now, _, _ = self.window_fixture()
        result = source.online_window_context(None, None, [], now, {})
        self.assertEqual(result['learning_coverage']['status'], 'await_first_confirmed_exposure')
        self.assertEqual(result['budget_settlements'], [])

    def test_live_binding_uses_creation_and_actual_price_with_anonymous_settlement(self):
        now, order, window = self.window_fixture()
        result = source.bind_price_windows([order], [window], now)
        settlement = result['budget_settlements'][0]
        self.assertEqual(settlement['reference_net_usd'], '10.00')
        self.assertEqual(settlement['actual_net_usd'], '8.68')
        self.assertIsNone(settlement['actual_contribution_usd'])
        self.assertNotIn('private-live-order', json.dumps(result))
        self.assertEqual(result['training_observations'][0]['paid_orders'], 1)
        self.assertEqual(result['training_observations'][0]['exposure'], '6.0')
        self.assertFalse(result['training_observations'][0]['randomization_verified'])

    def test_payment_after_open_does_not_reassign_preexisting_order(self):
        now, order, window = self.window_fixture()
        order.update(timestamp=int(datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc).timestamp()), timestamp_format='2026-10-26 07:30:00')
        result = source.bind_price_windows([order], [window], now)
        self.assertEqual(result['budget_settlements'], [])
        self.assertEqual(result['training_observations'][0]['paid_orders'], 0)
        self.assertEqual(result['learning_coverage']['counts']['created_outside_price_windows'], 1)

    def test_price_mismatch_or_ambiguous_windows_never_teach_a_fake_sample(self):
        now, order, window = self.window_fixture()
        wrong = dict(order, before_discount='9.99')
        self.assertEqual(source.bind_price_windows([wrong], [window], now)['training_observations'], [])
        self.assertEqual(source.bind_price_windows([order], [window, dict(window, operation_id='other')], now)['training_observations'], [])

    def test_unknown_cash_residual_keeps_budget_reservation_without_blocking_price_learning(self):
        now, order, window = self.window_fixture()
        order['amount_usd_format'] = '$9.00'
        result = source.bind_price_windows([order], [window], now)
        self.assertEqual(result['budget_settlements'], [])
        self.assertEqual(result['training_observations'][0]['paid_orders'], 1)
        self.assertEqual(result['learning_coverage']['gaps']['budget_reference_cash_residual_unresolved'], 1)

    def test_known_console_price_gap_does_not_discard_independent_pc_learning(self):
        now, order, window = self.window_fixture()
        window.update(platforms=['PS','PC'],mutable_resources=['base:console','base:pc'])
        window['action']['base_prices']['pc']='8.68'
        window['budget_reference']['base_prices']['pc']='10'
        window['catalog']['PC']=window['catalog']['PS']
        wrong_console=dict(order,before_discount='9.99')
        pc=dict(order,order_no='private-pc-order',aid=21589)
        result=source.bind_price_windows([wrong_console,pc],[window],now)
        self.assertEqual([(r['price_group'],r['paid_orders']) for r in result['training_observations']],[('pc',1)])
        self.assertEqual(result['learning_coverage']['gaps']['actual_regular_price_not_window_price'],1)
        unknown=dict(order,aid=0)
        self.assertEqual(source.bind_price_windows([unknown,pc],[window],now)['training_observations'],[])

    def test_inherited_factor_one_does_not_fabricate_a_zero_order_region(self):
        now,order,window=self.window_fixture()
        window['action']['region_coefficients']={'21:PS':'1'}
        result=source.bind_price_windows([order],[window],now)
        self.assertEqual([r['price_group'] for r in result['training_observations']],['console'])
        window['mutable_resources'].append('region:21:PS')
        result=source.bind_price_windows([order],[window],now)
        self.assertEqual([r['price_group'] for r in result['training_observations']],['21:PS','console'])

    def test_pc_only_change_keeps_original_console_exposure_open(self):
        now, order, old = self.window_fixture()
        old.update(platforms=['PS', 'PC'], mutable_resources=['base:console', 'base:pc'],
                   resource_closed_at={'base:pc': '2026-10-26T02:00:00+00:00'})
        old['action']['base_prices']['pc'] = '8.68'
        old['budget_reference']['base_prices']['pc'] = '10'
        old['catalog']['PC'] = old['catalog']['PS']
        new = dict(old, operation_id='pc-next', opened_at='2026-10-26T02:00:00+00:00',
                   platforms=['PC'], mutable_resources=['base:pc'], resource_closed_at={})
        new['action'] = dict(base_prices=dict(console='8.68', pc='9.00'), region_coefficients={})
        order.update(timestamp=int(datetime(2026, 10, 26, 3, tzinfo=timezone.utc).timestamp()), timestamp_format='2026-10-26 11:00:00')
        result = source.bind_price_windows([order], [old, new], now)
        self.assertEqual(result['budget_settlements'][0]['operation_id'], 'op')
        training = {(r['price_window_id'], r['price_group']): r for r in result['training_observations']}
        self.assertEqual(training[('op', 'console')]['exposure'], '6.0')
        self.assertEqual(training[('op', 'console')]['paid_orders'], 1)
        self.assertEqual(training[('op', 'pc')]['exposure'], '2.0')
        self.assertEqual(training[('pc-next', 'pc')]['exposure'], '4.0')

    def test_current_integer_K_custom_trace_replays_next_tier_derived_unit(self):
        now, order, window = self.window_fixture()
        window['catalog']['PS']['tiers'].append(dict(base_k='200', bonus_k='0', retained_ratio='1'))
        order.update(content='<span class="item">120 K coins x 1 = $10.42</span>', before_discount='10.42', amount_usd_format='$10.42')
        result = source.bind_price_windows([order], [window], now)
        self.assertEqual(len(result['budget_settlements']), 1)
        self.assertEqual(result['training_observations'][0]['paid_orders'], 1)
        self.assertEqual(result['learning_coverage']['gaps'], {})

    def test_independent_Order_pause_excludes_an_Admin_normal_status(self):
        def pages(session, path, filters, limit):
            return [dict(site_id=266, gid=1327, pay_status=1, status=31, order_no='paused-order',
                         content='<span class="item">100 K coins x 1 = $8</span>')] if filters[-1][2] == '3' else []
        with patch.dict(sys.modules, {'channel_source': SimpleNamespace(apply_cost_overrides=lambda value: {})}), patch.object(source, '_normal_order_queue', return_value=(set(), dict(status_counts={}))):
            context = source.active_backlog_context(None, pages)
        self.assertEqual(context['gross_ordered_delivery_k'], '0')
        self.assertEqual(context['counts']['excluded_not_Order_normal_1_2'], 1)

    def test_later_region_change_closes_regional_effective_exposure_only(self):
        now, order, old = self.window_fixture()
        old['action']['region_coefficients'] = {'21:PS': '.90'}
        old['budget_reference']['region_coefficients'] = {'21:PS': '.90'}
        new = dict(old, operation_id='regional-next', opened_at='2026-10-26T02:00:00+00:00', mutable_resources=['region:21:PS'], resource_closed_at={})
        new['action'] = dict(base_prices=dict(console='8.68'), region_coefficients={'21:PS': '.85'})
        order.update(timestamp=int(datetime(2026, 10, 26, 3, tzinfo=timezone.utc).timestamp()), timestamp_format='2026-10-26 11:00:00',
                     is_region_price=1, region_price_lang_region_id=21, region_price_factor='.85', before_discount='7.38', amount_usd_format='$7.38')
        result = source.bind_price_windows([order], [old, new], now)
        self.assertEqual(result['budget_settlements'][0]['operation_id'], 'regional-next')
        self.assertEqual(result['budget_settlements'][0]['group'], 'console')
        self.assertEqual(result['budget_settlements'][0]['price_group'], '21:PS')
        rows = {(r['price_window_id'], r['price_group']): r for r in result['training_observations']}
        self.assertEqual(rows[('op', 'console')]['exposure'], '6.0')
        self.assertEqual(rows[('op', '21:PS')]['exposure'], '2.0')
        self.assertEqual(rows[('regional-next', '21:PS')]['exposure'], '4.0')

    def test_budget_facts_hash_is_stable_across_polls_but_changes_with_actual_cost(self):
        now, order, window = self.window_fixture()
        first = source.bind_price_windows([order], [window], now)['budget_settlements'][0]
        later = source.bind_price_windows([order], [window], now.replace(hour=7))['budget_settlements'][0]
        self.assertEqual(first['source_sha256'], later['source_sha256'])
        order['amount_rmb_format'] = '65'
        archived = {order['order_no']: (dict(costCny='30', saleCny='65', salesUsd='8.68', status='已完成'), {})}
        costed = source.bind_price_windows([order], [window], now, archived=archived)['budget_settlements'][0]
        self.assertNotEqual(first['source_sha256'], costed['source_sha256'])
        self.assertIsNotNone(costed['actual_contribution_usd'])


if __name__ == '__main__':
    unittest.main()

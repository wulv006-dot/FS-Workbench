"""Stage 5 margin-band rules through the V6 proof and plan entry points."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import average_discount_v6


class MarginBandProof(unittest.TestCase):
    def test_main_basket_band_uses_weighted_cost_and_retained_cent_receipts(self):
        proof = dict(
            average_discount={'retained_ratio': '.90'},
            paths=[
                dict(path_id='a', purchase_k='100', net_receipt_usd='9.00', safe_cost_usd='6.60'),
                dict(path_id='b', purchase_k='300', net_receipt_usd='27.00', safe_cost_usd='17.85'),
                dict(path_id='c', purchase_k='1000', net_receipt_usd='90.00', safe_cost_usd='85.00'),
            ],
            baskets={'main': {'members': [
                dict(path_id='a', weight='3'), dict(path_id='b', weight='1'),
                dict(path_id='c', weight='8'),
            ]}},
        )
        self.assertEqual(
            average_discount_v6.band_margin(proof, 'small'),
            Decimal('16.35') / Decimal('54'),
        )
        self.assertEqual(
            average_discount_v6.band_target_price(proof, 'small', Decimal('.31'),
                                                  Decimal('9'), Decimal('11')),
            Decimal('10.12'),
        )



class MarginBandCorridor(unittest.TestCase):
    def test_lower_anchor_uses_lootbar_and_existing_ratio_fallback(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters, market_anchor_targets
        from test_curve_strategy_v6 import fixture, position_offers

        now = datetime(2026, 11, 18, 5, 38, tzinfo=timezone.utc)
        current, _, _ = fixture()
        parameters = market_anchor_parameters()
        for bands in parameters.values():
            for terms in bands.values():
                terms.update(p='.15', u='0', p_low='-.10')
        result = market_anchor_targets('PS', current, position_offers(now, '10', '11'), now,
                                       parameters=parameters)
        self.assertEqual(result['anchors']['small'], '11.00')
        self.assertEqual(result['low_anchors']['small'], '9.00')
        earlier = now - timedelta(hours=1)
        history = [dict(as_of=earlier.isoformat(), round_id='prior',
                        offers=position_offers(earlier, '10', '11'))]
        fallback = market_anchor_targets('PS', current, position_offers(now, None, '11'), now,
                                         parameters=parameters, history=history)
        self.assertEqual(fallback['fallback'], 'u7_ratio')
        self.assertEqual(fallback['low_anchors']['small'], '9.00')
        self.assertTrue(market_anchor_targets('PS', current, [], now, parameters=parameters)['floor_only'])
        parameters['PC']['large']['p_low'] = '-.16'
        with self.assertRaisesRegex(ValueError, 'market_anchor_parameters_invalid'):
            market_anchor_parameters(parameters)


class MarginBandDecisions(unittest.TestCase):
    def selection(self, margin, target='.31', low='8', high='12', *, hour=13,
                  cost='.364', samples=6, previous_cost=None):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime

        now = datetime(2026, 11, 18, hour, 38, tzinfo=timezone(timedelta(hours=8)))
        proof = dict(
            average_discount={'retained_ratio': '1'},
            paths=[dict(path_id='100', purchase_k='100', net_receipt_usd='10.00',
                        safe_cost_usd=str(10 * (1 - Decimal(margin))))],
            baskets={'main': {'members': [dict(path_id='100', weight='1')]}},
        )
        position = dict(anchors={'small': high}, low_anchors={'small': low}, floor_only=False)
        decision = runtime.margin_band_round(now, [2, 6, 9, 13, 17, 21])
        return runtime.margin_band_selection(
            proof, position, {'small': '10.00'}, Decimal(target), decision,
            cost_median=cost, cost_sample_count=samples, previous_decision_cost_median=previous_cost,
        )['bands']['small']

    def test_ps_xbox_and_pc_targets_raise_hold_and_lower(self):
        for target, margins in (('.31', ('.29', '.31', '.33')), ('.34', ('.329', '.34', '.351'))):
            for margin, action in zip(margins, ('raise', 'hold', 'lower')):
                with self.subTest(target=target, margin=margin):
                    value = self.selection(margin, target)
                    self.assertEqual(value['action'], action)
                    expected_sign = {'raise': 1, 'hold': 0, 'lower': -1}[action]
                    change = Decimal(value['desired']) - Decimal('10')
                    self.assertEqual((change > 0) - (change < 0), expected_sign)

    def test_off_hour_holds_even_at_35_percent(self):
        band = self.selection('.35', hour=15)
        self.assertEqual(band['action'], 'none')
        self.assertEqual(Decimal(band['desired']), Decimal('10'))

    def test_failed_decision_retries_once_and_never_at_midnight(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime

        local = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 18, 13, 38, tzinfo=local)
        hours = [2, 6, 9, 13, 17, 21]
        initial = runtime.margin_band_round(now, hours)
        self.assertTrue(initial['is_decision_round'])
        self.assertFalse(initial['retry'])
        next_hour = now + timedelta(hours=1)
        self.assertFalse(runtime.margin_band_round(next_hour, hours)['is_decision_round'])
        self.assertTrue(runtime.margin_band_round(next_hour, hours, collection_failed=True)['retry'])
        prior = [dict(decision_round=initial, status='PROOF_INCOMPLETE')]
        retry = runtime.margin_band_round(now + timedelta(hours=1), hours, prior)
        self.assertTrue(retry['is_decision_round'])
        self.assertTrue(retry['retry'])
        self.assertEqual(retry['slot_start'], initial['slot_start'])
        self.assertFalse(runtime.margin_band_round(now + timedelta(hours=2), hours, prior)['is_decision_round'])
        self.assertFalse(runtime.margin_band_round(now + timedelta(hours=1), hours,
                         [dict(decision_round=initial, status='KEEP')])['is_decision_round'])
        self.assertFalse(runtime.margin_band_round(now.replace(hour=0), [1, *hours])['is_decision_round'])

    def test_one_is_a_new_decision_and_failed_eleven_pm_does_not_retry_at_midnight(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime

        local = timezone(timedelta(hours=8))
        previous = datetime(2026, 11, 18, 23, 38, tzinfo=local)
        hours = [1, 23]
        history = [dict(decision_round=runtime.margin_band_round(previous, hours), status='PROOF_INCOMPLETE')]
        midnight = runtime.margin_band_round(previous + timedelta(hours=1), hours, history, collection_failed=True)
        self.assertFalse(midnight['is_decision_round'])
        self.assertFalse(midnight['retry'])
        one = runtime.margin_band_round(previous + timedelta(hours=2), hours, history)
        self.assertTrue(one['is_decision_round'])
        self.assertFalse(one['retry'])
        self.assertEqual(one['slot_start'], '2026-11-19T01:00:00+08:00')

    def test_midnight_decision_starts_after_discount_refresh_window(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime

        local = timezone(timedelta(hours=8))
        day_start = datetime(2026, 11, 19, tzinfo=local)
        hours = [0, 1, 23]
        prior = runtime.margin_band_round(day_start - timedelta(minutes=22), hours)
        history = [dict(decision_round=prior, status='PROOF_INCOMPLETE')]
        for minutes in (0, 14):
            with self.subTest(minutes=minutes):
                held = runtime.margin_band_round(day_start + timedelta(minutes=minutes), hours, history)
                self.assertFalse(held['is_decision_round'])
                self.assertFalse(held['retry'])
        for minutes in (15, 38):
            with self.subTest(minutes=minutes):
                first = runtime.margin_band_round(day_start + timedelta(minutes=minutes), hours, history)
                self.assertTrue(first['is_decision_round'])
                self.assertFalse(first['retry'])
                self.assertEqual(first['slot_start'], '2026-11-19T00:00:00+08:00')

    def test_late_previous_day_round_does_not_decide_during_discount_refresh(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime

        started = datetime(2026, 11, 18, 23, 59, tzinfo=timezone(timedelta(hours=8)))
        decision = runtime.margin_band_round(started, [0, 23], evaluated_at=started + timedelta(minutes=6))
        self.assertFalse(decision['is_decision_round'])

    def test_schedule_parameters_accept_midnight_and_reject_invalid_hours(self):
        from fc_pricing_v3.curve_strategy_v6 import margin_band_parameters, market_anchor_parameters

        anchors = market_anchor_parameters()
        for bands in anchors.values():
            for terms in bands.values():
                terms['p_low'] = '-.10'
        config = dict(schedule_hours=[0, 1, 23], PS={'target': '.31'},
                      XBOX={'target': '.31'}, PC={'target': '.34'})
        self.assertEqual(margin_band_parameters(config, anchors)['schedule_hours'], [0, 1, 23])
        for hour in (-1, 24):
            with self.subTest(hour=hour), self.assertRaisesRegex(ValueError, 'margin_band_parameters_invalid'):
                margin_band_parameters(dict(config, schedule_hours=[0, hour]), anchors)

    def test_caps_at_each_corridor_edge_and_clamps_a_hold(self):
        raise_cap = self.selection('.20', high='10.50')
        self.assertEqual((raise_cap['desired'], raise_cap['capped']), ('10.50', 'capped_by_market'))
        lower_cap = self.selection('.42', low='9.50')
        self.assertEqual((lower_cap['desired'], lower_cap['capped']), ('9.50', 'capped_by_corridor'))
        hold = self.selection('.31', high='9.80')
        self.assertEqual((hold['action'], hold['desired']), ('hold', '9.80'))

    def test_nine_percent_cost_drop_uses_prior_median_only_below_six_samples(self):
        guarded = self.selection('.39', samples=5, previous_cost='.4')
        confirmed = self.selection('.39', samples=6, previous_cost='.4')
        self.assertEqual(guarded['desired'], '9.72')
        self.assertEqual(confirmed['desired'], '8.85')
        self.assertTrue(guarded['cost_drop_unconfirmed'])
        self.assertFalse(confirmed['cost_drop_unconfirmed'])


    def test_unconfirmed_cost_drop_holds_instead_of_turning_a_cut_into_a_raise(self):
        for previous_cost in ('.40', '.50'):
            with self.subTest(previous_cost=previous_cost):
                result = self.selection('.33', samples=5, previous_cost=previous_cost)
                self.assertTrue(result['cost_drop_unconfirmed'])
                self.assertEqual(result['action'], 'hold')
                self.assertEqual(Decimal(result['desired']), Decimal('10.00'))
                self.assertIsNone(result['capped'])

    def test_guarded_cut_cannot_exceed_the_current_price_clamped_to_the_corridor(self):
        result = self.selection('.39', low='9.00', high='9.50', samples=5, previous_cost='.40')
        self.assertTrue(result['cost_drop_unconfirmed'])
        self.assertEqual(result['action'], 'hold')
        self.assertEqual(Decimal(result['desired']), Decimal('9.50'))
        self.assertIsNone(result['capped'])

    def test_both_promotion_band_cuts_still_require_cost_confirmation(self):
        from fc_pricing_v3 import runtime

        guard = dict(campaign='carnival_202611', start_day='2026-11-19', last_redeem_day='2026-11-20',
                     baseline={'PS': '.05', 'XBOX': '.07', 'PC': '.09'}, baseline_revision='a' * 64)
        proof = dict(
            average_discount=dict(platform='PS', retained_ratio='.75', revision='average-fixture',
                                  actual_discount_usd='25', merchandise_before_discount_usd='100',
                                  start='2026-11-17T00:00:00+08:00', end_exclusive='2026-11-20T00:00:00+08:00'),
            paths=[
                dict(path_id='small', purchase_k='100', regular_usd='10',
                     net_receipt_usd='7.50', safe_cost_usd='6.40'),
                dict(path_id='large', purchase_k='1000', regular_usd='100',
                     net_receipt_usd='75.00', safe_cost_usd='64.00'),
            ],
            baskets={'main': {'members': [dict(path_id=band, weight='1') for band in ('small', 'large')]}},
        )
        position = dict(anchors={'small': '12', 'large': '120'}, low_anchors={'small': '8', 'large': '80'})
        recorded = {'small': '10', 'large': '100'}
        for samples, expected in ((5, ('hold', '10', '100')), (6, ('lower', '9.77', '97.65'))):
            with self.subTest(samples=samples):
                result = runtime.margin_band_selection(
                    proof, position, recorded, Decimal('.31'), {'is_decision_round': True},
                    cost_median='.364', cost_sample_count=samples, previous_decision_cost_median='.4',
                    promotion_guard=guard,
                )
                action, small, large = expected
                for band, price in (('small', small), ('large', large)):
                    decision = result['bands'][band]
                    self.assertEqual(decision['action'], action)
                    self.assertEqual(Decimal(decision['desired']), Decimal(price))
                    self.assertEqual(decision['cost_drop_unconfirmed'], samples == 5)

    def test_eight_percent_cost_drop_is_guarded_with_five_samples(self):
        boundary = self.selection('.39', cost='.368', samples=5, previous_cost='.4')
        self.assertTrue(boundary['cost_drop_unconfirmed'])


class MarginBandRuntime(unittest.TestCase):
    def freeze(self, hour, large_cost, *, enabled=True, round_hour=None, offers=True, previous=None,
               day=18, retained='1', promotion_guard=None, stress_cost=None, lootbar='10.4'):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime
        from fc_pricing_v3.average_discount_v6 import MODEL, average_discount_window, forecast_receipt
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters
        from fc_pricing_v3.financial import fingerprint
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT, curve_key, read_curve
        from test_curve_strategy_v6 import fixture, position_offers
        from test_pricing_proof_v6 import fixture as proof_fixture

        current, reference, episode = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        current = read_curve(current['native_payload'], current['identity'], editor)
        row = dict(current['native_payload'], id=163329310, site_id=0)
        before = read_curve(row, dict(current['identity'], id=row['id'], site_id=0), editor)
        now = datetime(2026, 11, day, hour, 38, tzinfo=timezone(timedelta(hours=8)))
        def inputs(curve):
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            amount = next(row['native_price_usd'] for row in curve['tiers'] if row['purchase_k'] == '1000')
            start, end = average_discount_window(now)
            average = dict(contract=MODEL, platform='PS', site_id='266', status='complete', retained_ratio=retained,
                           start=start.isoformat(), end_exclusive=end.isoformat(),
                           actual_discount_usd=str(100 * (1 - Decimal(retained))),
                           merchandise_before_discount_usd='100')
            average['revision'] = fingerprint(average)
            domain.update(curve_key=key, source_revisions=dict(domain['source_revisions'], offers=average['revision']))
            evidence.update(curve_key=key, average_discount=average)
            evidence['paths'][0].update(curve_key=key, regular_usd=amount, quote_basis=MODEL,
                                       net_receipt_usd=str(forecast_receipt(Decimal(amount), Decimal(retained))),
                                       expected_cost_usd=large_cost, safe_cost_usd=large_cost,
                                       stress_cost_usd=stress_cost or large_cost, known_fee_usd='0')
            return dict(baskets=baskets, evidence=evidence, domain=domain)

        parameters = market_anchor_parameters()
        if enabled:
            for bands in parameters.values():
                for terms in bands.values():
                    terms.update(p='.15', u='0', p_low='-.10')
        plan = dict(mode='smart', smart_strategy_version='market-anchor-v1', parameters={'market_anchor': parameters})
        if enabled:
            plan['parameters']['margin_band'] = {'schedule_hours': [2, 6, 9, 13, 17, 21],
                'PS': {'target': '.31'}, 'XBOX': {'target': '.31'}, 'PC': {'target': '.34'}}
            if promotion_guard:
                plan['parameters']['margin_band']['promotion_guard'] = promotion_guard
        entry = dict(primary_curve=current, all_before=before, editor_contract=editor, native_route=None,
            primary_inputs={curve_key(current): inputs(current)}, all_inputs={}, all_targets={},
            margin_band_context=dict(automatic=True, history=[], cost_sample_count=6,
                at=now if round_hour is None else now.replace(hour=round_hour)),
            price_insurance=dict(day_anchors={'small': '10', 'large': '95'},
                                  market_per_100k=['10'], below_margin_rounds=0))
        quotes = position_offers(now, lootbar, '12.5') if offers else []
        runtime._freeze_cost_protection('PS', entry, inputs, dict(reference=reference, episode=episode),
                                        plan, dict(competitor_offers=quotes), now, previous or {})
        return entry['temporary_cost_protection']

    def test_promotion_changes_business_selection_while_real_discount_still_repairs_the_floor(self):
        guard = dict(campaign='carnival_202611', start_day='2026-11-19', last_redeem_day='2026-11-20',
                     baseline={'PS': '.05', 'XBOX': '.07', 'PC': '.09'}, baseline_revision='a' * 64)
        for day, action in ((19, 'raise'), (20, 'lower'), (23, 'lower'), (24, 'raise')):
            with self.subTest(day=day):
                frozen = self.freeze(13, '60', day=day, retained='.75', promotion_guard=guard, lootbar='9.6')
                decision = frozen['preference']['margin_band']
                self.assertEqual(decision['bands']['large']['action'], action)
                self.assertEqual(Decimal(decision['promotion_guard']['actual_discount']), Decimal('.25'))
                business = '.05' if action == 'lower' else '.25'
                self.assertEqual(Decimal(decision['promotion_guard']['business_discount']), Decimal(business))
                self.assertEqual(decision['promotion_guard']['baseline_revision'], guard['baseline_revision'])
                if action == 'lower':
                    self.assertEqual(frozen['status'], 'PROVEN')
                    self.assertLess(Decimal(frozen['normal_anchors']['large']), Decimal('95'))
                    self.assertGreaterEqual(Decimal(frozen['final_anchors']['large']), Decimal('97.57'))

        minimum = self.freeze(13, '60', day=20, retained='.96', promotion_guard=guard, lootbar='9.6')
        audit = minimum['preference']['margin_band']['promotion_guard']
        self.assertEqual(Decimal(audit['business_discount']), Decimal('.04'))
        self.assertEqual(audit['reason'], 'actual_at_or_below_baseline')

        protected = self.freeze(13, '60', day=20, retained='.75', promotion_guard=guard,
                                lootbar='9.6', stress_cost='80')
        self.assertEqual(protected['status'], 'PROVEN')
        self.assertGreaterEqual(Decimal(protected['final_anchors']['large']), Decimal('106.67'))

    def test_nondecision_holds_above_target_but_preserves_the_18_percent_floor(self):
        hold = self.freeze(15, '61.75')
        self.assertEqual(hold['status'], 'PROVEN')
        self.assertEqual(Decimal(hold['final_anchors']['large']), Decimal('95'))
        self.assertEqual(hold['preference']['margin_band']['bands']['large']['action'], 'none')
        protected = self.freeze(15, '85')
        self.assertEqual(protected['status'], 'PROVEN')
        self.assertGreater(Decimal(protected['final_anchors']['large']), Decimal('95'))
        self.assertIn('large', protected['segments'])

    def test_business_price_beyond_fifteen_percent_uses_original_insurance(self):
        frozen = self.freeze(13, '80')
        self.assertEqual(frozen['status'], 'PROVEN')
        self.assertGreater(Decimal(frozen['normal_anchors']['large']), Decimal('109.25'))
        self.assertEqual(Decimal(frozen['final_anchors']['large']), Decimal('109.25'))
        self.assertIn('large', frozen['price_insurance']['clipped'])

    def test_old_market_plan_keeps_hourly_position_behavior_without_margin_fields(self):
        frozen = self.freeze(15, '61.75', enabled=False)
        self.assertEqual(frozen['status'], 'PROVEN')
        self.assertNotIn('margin_band', frozen['preference'])
        self.assertNotEqual(Decimal(frozen['final_anchors']['large']), Decimal('95'))

    def test_early_hour_collection_finishing_after_two_keeps_its_original_slot(self):
        frozen = self.freeze(2, '61.75', round_hour=1)
        self.assertFalse(frozen['preference']['margin_band']['decision_round']['is_decision_round'])
        self.assertEqual(Decimal(frozen['final_anchors']['large']), Decimal('95'))

    def test_frozen_economic_candidate_cannot_authorize_execution_during_midnight_refresh(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        from fc_pricing_v3 import runtime
        from test_curve_runtime_v6 import CurveRuntime
        from test_curve_strategy_v6 import fixture as curve_fixture

        fixture = CurveRuntime()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        plan = fixture.db.get('pricing_plans', 'plan')
        selected = self.freeze(13, '80')['preference']
        local = timezone(timedelta(hours=8))
        started = datetime(2026, 11, 18, 23, 59, tzinfo=local)
        hours = list(range(24))
        selected['margin_band']['decision_round'] = runtime.margin_band_round(started, hours)
        plan.update(mode='smart', write_protocol='fc27_curve_v6', smart_strategy_version='market-anchor-v1',
                    activation_revision='fixture', resources=['base:PS'], parameters=self.margin_parameters(hours))
        bundle = fixture.bundle
        primary, _, _ = curve_fixture()
        frozen = dict(plan_binding=runtime._curve_plan_binding(plan), primary_curve=primary,
                      captured_at=started.isoformat(), valid_until=(started + timedelta(minutes=15)).isoformat(),
                      temporary_cost_protection={'preference': selected})
        candidate = dict(status='READY', before=bundle['before_action']['curves']['PS'],
                         target=bundle['action']['curves']['PS'],
                         proof=bundle['curve_proofs']['PS'], selection=selected,
                         native_route=None, primary_before_hash=None)
        with patch.object(runtime, '_curve_proof_inputs', return_value={'PS': frozen}), \
             patch.object(fixture.db, 'curve_strategy_state', return_value={'present': True}), \
             patch.object(runtime, '_prove_temporary_curve', return_value=candidate):
            for minutes in (6, 15):
                with self.subTest(minutes_since_freeze=minutes):
                    run_id = f'across-midnight-{minutes}'
                    result = runtime.calculate_curve_cycle(fixture.db, {'run_id': run_id}, plan,
                                                           {'v3_operation_id': 'original'},
                                                           started + timedelta(minutes=minutes))
                    self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
                    self.assertFalse(result['execution_authorized'])
                    self.assertNotIn('decision_receipt', result)
                    recorded = fixture.db.get('strategy_decisions', run_id)
                    self.assertFalse(recorded['curve_selection']['PS']['margin_band']['decision_round']['is_decision_round'])

    def margin_parameters(self, hours):
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters

        anchors = market_anchor_parameters()
        for bands in anchors.values():
            for terms in bands.values():
                terms['p_low'] = '-.10'
        return dict(market_anchor=anchors, margin_band=dict(
            schedule_hours=hours, PS={'target': '.31'}, XBOX={'target': '.31'}, PC={'target': '.34'}))

    def test_missing_quotes_in_a_nondecision_round_do_not_release_a_floor_price(self):
        previous = dict(segments={'large': dict(normal='90', target='95', release_rounds=2)})
        frozen = self.freeze(15, '61.75', offers=False, previous=previous)
        self.assertEqual(Decimal(frozen['final_anchors']['large']), Decimal('95'))
        self.assertIn('large', frozen['segments'])

    def test_pc_ten_k_test_order_is_filtered_without_changing_the_median(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost

        now = datetime(2026, 11, 18, 2, 39, tzinfo=timezone.utc)
        batches = [dict(platform='PC', record_id=str(200 + i), status='valid',
                        trade_at=(now - timedelta(minutes=i)).isoformat(), cny_per_1k=cost)
                   for i, cost in enumerate(('.25', '.26', '.26', '.26', '.27', '.28'))]
        def median(records):
            return smooth_delivery_cost(dict(platform='PC', checked_at=now.isoformat(),
                v6_delivery_samples=dict(window_complete=True, history_complete=True, records=records)),
                'PC', now, '.26')
        test_order = dict(platform='PC', record_id='4632464', status='valid', trade_at=now.isoformat(),
                          cny_per_1k='.001', purchase_k='10', amount_cny='.01')
        with_test = median([*batches, test_order])
        self.assertEqual(with_test['cny_per_1k'], median(batches)['cny_per_1k'])
        self.assertEqual(with_test['sample_insurance']['outliers'][0]['record_id'], '4632464')


class MarginBandRevision(unittest.TestCase):
    def test_plan_revision_validates_binds_replays_and_can_remove_margin_band(self):
        from copy import deepcopy
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        from fc_pricing_v3 import api, runtime
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters
        from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL
        from test_curve_runtime_v6 import CurveRuntime

        fixture = CurveRuntime()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.prepare()
        db = fixture.db
        now = datetime.now(timezone.utc)
        plan = db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL, resources=['base:PS'],
                    starts_at=(now - timedelta(hours=2)).isoformat(), last_cycle_at=now.isoformat(),
                    smart_started_at=(now - timedelta(hours=2)).isoformat(),
                    smart_strategy_version='market-anchor-v1', parameters={})
        db.put('pricing_plans', 'plan', plan)
        anchors = market_anchor_parameters()
        for bands in anchors.values():
            for terms in bands.values():
                terms.update(p='.15', u='0', p_low='-.10')
        band = {'PS': {'target': '.31'}, 'XBOX': {'target': '.31'}, 'PC': {'target': '.34'}}
        request = dict(expected_revision=4, snapshot_id='00000000-0000-4000-8000-000000000123',
                       strategy_version='market-anchor-v1', market_anchor=anchors, margin_band=band)
        path = 'plans/plan/revise-curve-strategy'
        with patch.object(api, 'ledger', return_value=db), \
             patch('automation_policy.load_policy', return_value={'interval_minutes': 60}):
            for bad in (dict(band, PC={'target': '.341'}), dict(band, schedule_hours=[-1, 2, 13])):
                with self.assertRaisesRegex(ValueError, 'margin_band_parameters_invalid'):
                    api.post(path, dict(request, margin_band=bad), 'signed-operator')
            with self.assertRaisesRegex(ValueError, 'margin_band_parameters_invalid'):
                api.post(path, dict(request, market_anchor=market_anchor_parameters()), 'signed-operator')
            self.assertEqual(db.get('pricing_plans', 'plan')['revision'], 4)
            revised = api.post(path, request, 'signed-operator')
            self.assertEqual(revised['revision'], 5)
            self.assertEqual(revised['parameters']['margin_band']['schedule_hours'], [2, 6, 9, 13, 17, 21])
            self.assertEqual(revised['parameters']['margin_band']['PC']['target'], '0.34')
            self.assertEqual(api.post(path, request, 'signed-operator'), revised)
            changed = deepcopy(revised)
            changed['parameters']['margin_band']['PC']['target'] = '0.345'
            self.assertNotEqual(runtime._curve_plan_binding(revised), runtime._curve_plan_binding(changed))
            with self.assertRaisesRegex(ValueError, 'request_conflict'):
                api.post(path, dict(request, margin_band=dict(band, PC={'target': '.345'})), 'signed-operator')
            reverted = api.post(path, dict(request, expected_revision=5, margin_band=None), 'signed-operator')
            self.assertEqual(reverted['revision'], 6)
            self.assertNotIn('margin_band', reverted['parameters'])
        fixture.dispatch.assert_not_called()

    def test_promotion_guard_revision_uses_only_pinned_archived_baseline(self):
        from datetime import datetime, timedelta, timezone
        from copy import deepcopy
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from fc_pricing_v3 import api, runtime
        from fc_pricing_v3.admin_readback import PLATFORM_AID
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from test_pricing_proof_v6 import make_curve
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters
        from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL
        from fc_pricing_v3.financial import fingerprint
        from test_curve_runtime_v6 import CurveRuntime

        fixture = CurveRuntime()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.prepare()
        db = fixture.db
        now = datetime.now(timezone.utc)
        plan = db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL, resources=['base:PS'],
                    starts_at=(now - timedelta(hours=2)).isoformat(), last_cycle_at=now.isoformat(),
                    smart_started_at=(now - timedelta(hours=2)).isoformat(),
                    smart_strategy_version='market-anchor-v1', parameters={})
        db.put('pricing_plans', 'plan', plan)
        anchors = market_anchor_parameters()
        for bands in anchors.values():
            for terms in bands.values():
                terms['p_low'] = '-.10'
        baseline = {'PS': '0.08', 'XBOX': '0.1', 'PC': '0.12'}
        guard = dict(campaign='carnival_202611', start_day='2026-11-19',
                     last_redeem_day='2026-11-30', baseline=baseline, baseline_revision='se_' + '1' * 32)
        band = dict(PS={'target': '.31'}, XBOX={'target': '.31'}, PC={'target': '.34'})
        request = dict(expected_revision=4, snapshot_id='00000000-0000-4000-8000-000000000123',
                       strategy_version='market-anchor-v1', market_anchor=anchors,
                       margin_band=dict(band, promotion_guard=guard))
        path = 'plans/plan/revise-curve-strategy'
        snapshot_id = request['snapshot_id']
        start, cutoff = '2026-11-16T00:00:00+08:00', '2026-11-19T00:00:00+08:00'
        coverage = dict(window_complete=True, population_status='complete',
                        shared_publication_id=guard['baseline_revision'], shared_source_revision='shared-archive',
                        paid_window_start=start, paid_window_end_exclusive=cutoff)
        inputs = {}
        curve = make_curve()
        for platform, aid in PLATFORM_AID.items():
            native = read_curve(dict(curve['native_payload'], aid=aid), dict(curve['identity'], aid=aid),
                                curve['native_contract'])
            closed = dict(historical_orders_coverage=coverage, historical_orders=[
                dict(platform=platform, paid_at=start, order_key=platform, merchandise_before_discount_usd='100',
                     actual_es_discount_usd=str(100 * Decimal(baseline[platform])))])
            average = average_discount(closed, platform, cutoff)
            key = curve_key(native)
            inputs[platform] = dict(primary_curve=native, plan_binding=runtime._curve_plan_binding(plan),
                primary_inputs={key: dict(evidence=dict(curve_key=key, average_discount=average),
                    domain=dict(curve_key=key, platform=platform, source_revisions=dict(offers=average['revision'])))})
        evidence = dict(run_id=snapshot_id, competitor_policy=POLICY)
        snapshot = dict(snapshot_id=snapshot_id, plan_id='plan', plan_revision=4, origin='live_collector',
                        mode='production', write_protocol=CURVE_WRITE_PROTOCOL, evidence=evidence)
        attachment = runtime.store_curve_proof_inputs(db, evidence, inputs)
        db.put('pricing_snapshots', snapshot_id, snapshot)
        denied = Mock(side_effect=PermissionError('system API account cannot read ES database'))
        with patch.object(api, 'ledger', return_value=db), \
             patch('automation_policy.load_policy', return_value={'interval_minutes': 60}), \
             patch.dict(sys.modules, {'shared_es_facts': SimpleNamespace(read=denied)}):
            for invalid in (dict(guard, last_redeem_day='2026-11-18'),
                            dict(guard, baseline={'PS': '0.08'}),
                            dict(guard, baseline=dict(baseline, PS='NaN'))):
                with self.assertRaisesRegex(ValueError, 'margin_band_parameters_invalid'):
                    api.post(path, dict(request, margin_band=dict(band, promotion_guard=invalid)), 'signed-operator')
            with self.assertRaisesRegex(ValueError, 'promotion_guard_baseline_unverified'):
                wrong = dict(guard, baseline=dict(baseline, PS='0.01'))
                api.post(path, dict(request, margin_band=dict(band, promotion_guard=wrong)), 'signed-operator')
            for forged in (dict(snapshot, origin='mock'), dict(snapshot, plan_revision=3),
                           dict(snapshot, evidence=dict(evidence, forged=True))):
                db.put('pricing_snapshots', snapshot_id, forged)
                with self.assertRaisesRegex(ValueError, 'promotion_guard_baseline_unverified'):
                    api.post(path, request, 'signed-operator')
            db.put('pricing_snapshots', snapshot_id, snapshot)
            proof_key = 'curve-proof-inputs:' + snapshot_id
            missing = deepcopy(attachment)
            missing['platforms'].pop('PC')
            with self.assertRaisesRegex(ValueError, 'promotion_guard_baseline_unverified'):
                db.put('metadata', proof_key, missing)
                api.post(path, request, 'signed-operator')
            for field, value, resign in (
                ('actual_discount_usd', '80', False),
                ('start', '2026-11-15T00:00:00+08:00', True),
                ('publication_id', 'se_' + '2' * 32, True),
                ('status', 'partial', True),
            ):
                forged = deepcopy(attachment)
                platform = forged['platforms']['PS']
                frozen = platform['primary_inputs'][curve_key(platform['primary_curve'])]
                average = frozen['evidence']['average_discount']
                average[field] = value
                if resign:
                    del average['revision']
                    average['revision'] = fingerprint(average)
                    frozen['domain']['source_revisions']['offers'] = average['revision']
                db.put('metadata', proof_key, forged)
                with self.assertRaisesRegex(ValueError, 'promotion_guard_baseline_unverified'):
                    api.post(path, request, 'signed-operator')
            db.put('metadata', proof_key, attachment)
            self.assertEqual(db.get('pricing_plans', 'plan')['revision'], 4)
            revised = api.post(path, request, 'signed-operator')
            self.assertEqual(revised['parameters']['margin_band']['promotion_guard'], guard)
            db.put('metadata', proof_key, {})
            self.assertEqual(api.post(path, request, 'signed-operator'), revised)
            with self.assertRaisesRegex(ValueError, 'revision_changed'):
                api.post(path, dict(request, expected_revision=3), 'signed-operator')
            revised_band = dict(request['margin_band'], PC={'target': '.35'})
            updated = api.post(path, dict(request, expected_revision=5, margin_band=revised_band), 'signed-operator')
            self.assertEqual(updated['parameters']['margin_band']['promotion_guard'], guard)
            self.assertEqual(updated['parameters']['margin_band']['PC']['target'], '0.35')
            reverted = api.post(path, dict(request, expected_revision=6, margin_band=band), 'signed-operator')
            self.assertNotIn('promotion_guard', reverted['parameters']['margin_band'])
            self.assertEqual(reverted['parameters']['margin_band']['PC']['target'], '0.34')
            denied.assert_not_called()
        fixture.dispatch.assert_not_called()



class MarginBandWeekly(unittest.TestCase):
    def config(self):
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters

        anchors = market_anchor_parameters()
        for bands in anchors.values():
            for terms in bands.values():
                terms.update(p='.15', u='0', p_low='-.10')
        return dict(market_anchor=market_anchor_parameters(anchors), margin_band=dict(
            schedule_hours=[2, 6, 9, 13, 17, 21], PS={'target': '.31'}, XBOX={'target': '.31'}, PC={'target': '.34'}))

    def proposal(self, *, orders=100, gross='2000', delta='0', freeze=False, target='.31'):
        from datetime import timedelta
        from fc_pricing_v3.weekly_ladder import propose_adoption
        from test_weekly_ladder import NOW, weeks

        previous, current = weeks()
        for band in previous['platforms']['PS'].values():
            band['procurement_gross_cny'] = '2000'
        for band in current['platforms']['PS'].values():
            band.update(orders=orders, procurement_gross_cny=gross)
        prior = dict(platform='PS', week_start=(NOW.date() - timedelta(days=7)).isoformat(),
                     status='CONFIRMED', delta_t=delta)
        if freeze:
            prior['freeze_until'] = (NOW.date() + timedelta(days=7)).isoformat()
        params = self.config()
        params['margin_band']['PS']['target'] = target
        result = propose_adoption(previous, current, params['market_anchor'], now=NOW,
                                  history=[prior], margin_band=params['margin_band'])
        self.assertEqual(result['gaps'], [])
        return next(row for row in result['proposals'] if row['platform'] == 'PS')

    def test_weekly_order_protection_precedes_low_margin_even_when_frozen(self):
        row = self.proposal(orders=84, gross='1500', delta='.01', freeze=True)
        self.assertEqual((row['rule'], Decimal(row['delta_t'])), ('protect_orders', Decimal('-.01')))
        self.assertEqual((row['previous_orders'], row['orders']), (200, 168))

    def test_weekly_repairs_margin_even_when_frozen(self):
        row = self.proposal(gross='1500', delta='-.01', freeze=True)
        self.assertEqual((row['rule'], Decimal(row['delta_t'])), ('repair_margin', Decimal('.01')))

    def test_weekly_continues_winning_direction_at_equal_market_adjusted_gross(self):
        row = self.proposal(delta='-.01')
        self.assertEqual((row['rule'], Decimal(row['delta_t'])), ('continue_direction', Decimal('-.01')))
        self.assertEqual(Decimal(row['procurement_gross_cny']), Decimal('4000'))
        self.assertEqual(Decimal(row['previous_procurement_gross_cny']), Decimal('4000'))

    def test_weekly_reverts_losing_direction_and_freezes_for_two_weeks(self):
        row = self.proposal(delta='.01', gross='1900')
        self.assertEqual((row['rule'], Decimal(row['delta_t'])), ('revert_direction', Decimal('-.01')))
        self.assertIsNotNone(row['freeze_until'])

    def test_weekly_probes_each_direction_based_on_thirty_percent(self):
        for gross, expected in (('2000', '-.01'), ('1800', '.01')):
            with self.subTest(gross=gross):
                row = self.proposal(gross=gross)
                self.assertEqual((row['rule'], Decimal(row['delta_t'])), ('probe', Decimal(expected)))

    def test_weekly_holds_while_frozen_above_the_order_and_margin_floors(self):
        row = self.proposal(delta='-.01', freeze=True)
        self.assertEqual((row['rule'], Decimal(row['delta_t'])), ('hold', Decimal(0)))

    def test_weekly_holds_at_target_bounds_when_proposed_change_points_outward(self):
        for target, gross in (('.28', '2000'), ('.35', '1500')):
            with self.subTest(target=target):
                row = self.proposal(target=target, gross=gross)
                self.assertEqual(Decimal(row['after_t']), Decimal(target))
                self.assertTrue(row['t_bound_reached'])

    def test_incomplete_round_stores_margin_band_for_monitoring_and_retry(self):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime
        from test_curve_runtime_v6 import CurveRuntime

        fixture = CurveRuntime()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        plan = fixture.db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol='fc27_curve_v6', smart_strategy_version='market-anchor-v1',
                    resources=['base:PS'], parameters=self.config())
        local = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 18, 13, 38, tzinfo=local)
        result = runtime.calculate_curve_cycle(fixture.db, {'run_id': 'no-proof'}, plan,
                                               {'v3_operation_id': 'original'}, now)
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        audit = result['curve_selection']['PS']['margin_band']
        self.assertEqual(audit['bands']['small']['action'], 'none')
        self.assertIsNone(audit['cost_median'])
        recorded = fixture.db.get('strategy_decisions', 'no-proof')
        self.assertEqual(recorded['curve_selection']['PS']['margin_band'], audit)
        history = runtime._margin_band_history(fixture.db, 'plan')['PS']
        self.assertTrue(runtime.margin_band_round(now + timedelta(hours=1), [2, 6, 9, 13, 17, 21], history)['retry'])

    def test_weekly_confirmation_updates_only_target_using_original_plan_revision(self):
        from fc_pricing_v3 import weekly_ladder as ladder
        from test_weekly_ladder import NOW, WeeklyLadder

        fixture = WeeklyLadder()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan['parameters'] = self.config()
        fixture.db.put('pricing_plans', 'plan', fixture.plan)
        rows = fixture.run_week()
        row = next(row for row in rows if row['platform'] == 'PS')
        confirmed = ladder.confirm_adoption(fixture.db, row['proposal_id'], 'owner', 4, NOW)
        self.assertEqual(confirmed['status'], 'CONFIRMED')
        plan = fixture.db.get('pricing_plans', 'plan')
        self.assertEqual(plan['revision'], 5)
        self.assertEqual(plan['parameters']['market_anchor'], self.config()['market_anchor'])
        self.assertEqual(plan['parameters']['margin_band']['PS']['target'], '0.32')
        self.assertEqual(ladder.confirm_adoption(fixture.db, row['proposal_id'], 'owner', 4, NOW), confirmed)
        self.assertEqual(fixture.db.all('operations'), [])

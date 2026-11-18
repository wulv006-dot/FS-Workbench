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

    def test_failed_decision_retries_once_and_never_at_midnight_or_one(self):
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
        for hour in (0, 1):
            self.assertFalse(runtime.margin_band_round(now.replace(hour=hour), [0, 1, *hours])['is_decision_round'])

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


    def test_eight_percent_cost_drop_is_guarded_with_five_samples(self):
        boundary = self.selection('.39', cost='.368', samples=5, previous_cost='.4')
        self.assertTrue(boundary['cost_drop_unconfirmed'])


class MarginBandRuntime(unittest.TestCase):
    def freeze(self, hour, large_cost, *, enabled=True, round_hour=None, offers=True, previous=None):
        from datetime import datetime, timedelta, timezone
        from fc_pricing_v3 import runtime
        from fc_pricing_v3.average_discount_v6 import MODEL
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
        def inputs(curve):
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            amount = next(row['native_price_usd'] for row in curve['tiers'] if row['purchase_k'] == '1000')
            average = dict(contract=MODEL, platform='PS', site_id='266', status='complete', retained_ratio='1')
            average['revision'] = fingerprint(average)
            domain.update(curve_key=key, source_revisions=dict(domain['source_revisions'], offers=average['revision']))
            evidence.update(curve_key=key, average_discount=average)
            evidence['paths'][0].update(curve_key=key, regular_usd=amount, net_receipt_usd=amount,
                                       expected_cost_usd=large_cost, safe_cost_usd=large_cost,
                                       stress_cost_usd=large_cost, known_fee_usd='0')
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
        now = datetime(2026, 11, 18, hour, 38, tzinfo=timezone(timedelta(hours=8)))
        entry = dict(primary_curve=current, all_before=before, editor_contract=editor, native_route=None,
            primary_inputs={curve_key(current): inputs(current)}, all_inputs={}, all_targets={},
            margin_band_context=dict(automatic=True, history=[], cost_sample_count=6,
                at=now if round_hour is None else now.replace(hour=round_hour)),
            price_insurance=dict(day_anchors={'small': '10', 'large': '95'},
                                  market_per_100k=['10'], below_margin_rounds=0))
        quotes = position_offers(now, '10.4', '12.5') if offers else []
        runtime._freeze_cost_protection('PS', entry, inputs, dict(reference=reference, episode=episode),
                                        plan, dict(competitor_offers=quotes), now, previous or {})
        return entry['temporary_cost_protection']

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
            for bad in (dict(band, PC={'target': '.341'}), dict(band, schedule_hours=[0, 2, 13])):
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

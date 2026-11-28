"""Exercise original-operation coordination against the synthetic F4 transport."""
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import adapters, runtime, smart
from fc_pricing_v3.competitor_offers import POLICY
from fc_pricing_v3.dispatch import CURVE_REJECTED, CURVE_WRITE_PROTOCOL, prewrite_refusal
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger
from test_curve_writer_v6 import OPERATION, PLATFORM, Transport, setup_bundle, writer
from test_price_curve_v6 import EDITOR_CONTRACT


class CurveRuntime(unittest.TestCase):

    def test_observation_sites_cannot_supply_price_insurance_or_authorization_evidence(self):
        from test_curve_strategy_v6 import position_offers

        self.prepare()
        now = datetime.now(timezone.utc)
        market = position_offers(now, '8', '10')
        observers = [dict(market[0], source='IGGM', regular_price='10000'),
                     dict(market[0], source='U4GM', regular_price='.01')]
        def insurance(offers):
            return runtime._curve_insurance_context(self.db, 'PS', {'competitor_offers': offers}, now)

        self.assertEqual(insurance(market + observers), insurance(market))
        self.assertEqual(insurance(observers), insurance([]))

    def test_new_market_policy_requires_existing_plan_revision_for_execution(self):
        from fc_pricing_v3.competitor_offers import POLICY, LEGACY_POLICY

        self.prepare()
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(write_protocol=CURVE_WRITE_PROTOCOL, parameters={'competitor_policy': LEGACY_POLICY})
        self.db.put('pricing_plans', 'plan', plan)
        path = self.root / 'jobs' / 'run.json'
        policy_stub = patch('automation_policy.load_policy', return_value={'revision': 7, 'interval_minutes': 60})
        policy_stub.start()
        self.addCleanup(policy_stub.stop)
        request = dict(v3_plan_id='plan', natural_curve_cycle=True)
        path.write_text(json.dumps(dict(kind='v3_cycle', request=request)))
        with self.assertRaisesRegex(ValueError, 'pricing_curve_market_policy_revision_required'):
            runtime.collection_scope(self.db, 'run')
        with self.assertRaisesRegex(ValueError, 'pricing_curve_market_policy_revision_required'):
            runtime.calculate_curve_cycle(self.db, {'run_id': 'old'}, plan, {'v3_operation_id': 'job'}, runtime.clock())
        path.write_text(json.dumps(dict(kind='collect', request=dict(write_protocol=CURVE_WRITE_PROTOCOL))))
        self.assertEqual(runtime.collection_scope(self.db, 'run')['scope']['competitor_policy'], POLICY)

    def test_old_market_receipts_can_be_read_but_cannot_authorize_new_writes(self):
        from fc_pricing_v3.competitor_offers import FOUR_SOURCE_POLICY, LEGACY_POLICY
        from fc_pricing_v3.pricing_proof_v6 import CONTRACT

        self.prepare()
        for old_policy in (LEGACY_POLICY, FOUR_SOURCE_POLICY):
            with self.subTest(policy=old_policy):
                evidence = dict(run_id='historical', competitor_policy=old_policy)
                quote = dict(evidence=evidence, result=dict(strategy_version=runtime.VERSION))
                receipt = dict(self.bundle, schema_version=runtime.VERSION, financial_contract_version=CONTRACT,
                               snapshot_id='historical', snapshot_sha256=fingerprint(evidence))
                receipt.pop('sha256')
                receipt['sha256'] = fingerprint(receipt)
                args = (quote, receipt, {}, [PLATFORM], runtime.clock())
                self.assertEqual(runtime.verify_curve_quote(*args, False, None), receipt)
                with self.assertRaisesRegex(ValueError, 'pricing_curve_quote_identity_invalid'):
                    runtime.verify_curve_quote(*args, True, None)

    def test_market_activation_requires_the_matching_live_shadow_and_forwards_the_authenticated_actor(self):
        from copy import deepcopy
        from fc_pricing_v3 import api
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters

        self.prepare()
        now = datetime.now(timezone.utc)
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL, resources=['base:PS'],
                    starts_at=(now-timedelta(hours=2)).isoformat(), smart_started_at=(now-timedelta(hours=2)).isoformat(),
                    last_cycle_at=now.isoformat(), smart_strategy_version='smart-three-platform-v3', parameters={})
        self.db.put('pricing_plans', 'plan', plan)
        ident = '00000000-0000-4000-8000-000000000123'
        parameters = market_anchor_parameters()
        prospective = dict(plan, smart_strategy_version='market-anchor-v1', parameters={'market_anchor': parameters})
        evidence = dict(run_id=ident, competitor_policy=POLICY)
        shadow = dict(plan_binding=runtime._curve_plan_binding(prospective), plan_id='plan', plan_revision=4,
            snapshot_id=ident, created_at=now.isoformat(), status='READY', execution_authorized=False,
            target_curve=self.bundle['action']['curves']['PS'], proof=self.bundle['curve_proofs']['PS'])
        snapshot = dict(snapshot_id=ident, created_at=now.isoformat(), mode='production', origin='live_collector',
                        write_protocol=CURVE_WRITE_PROTOCOL, evidence=evidence)
        self.db.put('pricing_snapshots', ident, snapshot)
        def freeze(value):
            self.db.put('metadata', 'curve-proof-inputs:'+ident, dict(run_id=ident,
                collection_sha256=runtime._curve_collection_fingerprint(evidence),
                platforms={'PS': dict(plan_binding=runtime._curve_plan_binding(plan), anchor_shadow=value)}))
        data = dict(expected_revision=4, snapshot_id=ident, strategy_version='market-anchor-v1', market_anchor=parameters)
        with patch.object(api, 'ledger', return_value=self.db), \
             patch('automation_policy.load_policy', return_value={'interval_minutes': 60}):
            bad = deepcopy(shadow)
            bad['proof']['proof_hash'] = 'tampered'
            freeze(bad)
            with self.assertRaisesRegex(ValueError, 'shadow_unverified'):
                api.post('plans/plan/revise-curve-strategy', data, 'signed-operator')
            self.assertEqual(self.db.get('pricing_plans', 'plan')['revision'], 4)
            freeze(shadow)
            changed = api.post('plans/plan/revise-curve-strategy', data, 'signed-operator')
        self.assertEqual(changed['revision'], 5)
        self.assertEqual(changed['parameters']['market_anchor']['PS']['small']['p'], '0.08')
        self.assertEqual(self.db.get('metadata', 'curve-strategy-revision:plan:4')['actor'], 'signed-operator')
        self.dispatch.assert_not_called()
        self.assertEqual(self.transport.posts, [])

    def test_market_plan_revision_is_idempotent_cas_and_keeps_the_queued_hour(self):
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters
        from fc_pricing_v3.scheduler import next_cycle_at

        self.prepare()
        now = datetime.now(timezone.utc)
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL, resources=['base:PS'],
                    starts_at=(now-timedelta(hours=2)).isoformat(), smart_started_at=(now-timedelta(hours=2)).isoformat(),
                    last_cycle_at=now.isoformat(), smart_strategy_version='smart-three-platform-v3', parameters={})
        self.db.put('pricing_plans', 'plan', plan)
        policy = {'interval_minutes': 60}
        due = next_cycle_at(self.db, plan, policy)
        cycle_id = 'cycle:plan:'+str(int(due.timestamp()))+':r0'
        self.db.enqueue('cycle', cycle_id, due, dict(plan_id='plan', revision=4, scheduled_at=due.isoformat()))
        revision = dict(strategy_version='market-anchor-v1', market_anchor=market_anchor_parameters())
        check = lambda conn, current, at: {'PS': 'shadow-proof'}
        with patch('automation_policy.load_policy', return_value=policy):
            changed = self.db.activate_curve_plan('plan', 4, 'signed-operator', 'shadow', check, strategy_revision=revision)
            self.assertEqual(changed['revision'], 5)
            self.assertEqual(changed['smart_strategy_version'], 'market-anchor-v1')
            self.assertEqual(changed['last_cycle_at'], plan['last_cycle_at'])
            self.assertEqual(self.db.activate_curve_plan('plan', 4, 'signed-operator', 'shadow', check,
                                                        strategy_revision=revision), changed)
            other = dict(revision, market_anchor=market_anchor_parameters())
            other['market_anchor']['PS']['small']['p'] = '.09'
            with self.assertRaisesRegex(ValueError, 'request_conflict'):
                self.db.activate_curve_plan('plan', 4, 'signed-operator', 'shadow', check, strategy_revision=other)
        with closing(self.db.connect()) as conn:
            job = conn.execute('SELECT due_at,body FROM durable_jobs WHERE id=?', (cycle_id,)).fetchone()
            self.assertEqual(json.loads(job['body'])['revision'], 5)
            self.assertEqual(job['due_at'], due.isoformat())
            self.db.owns(changed, ['base:PS'], conn)

    def test_market_strategy_preserves_the_original_hourly_schedule(self):
        from fc_pricing_v3.scheduler import next_cycle_at
        from fc_pricing_v3.financial import instant

        for version in ('smart-three-platform-v3', 'market-anchor-v1'):
            plan = dict(plan_id='plan', smart_strategy_version=version, starts_at='2026-11-17T00:00:00+00:00',
                        smart_started_at='2026-11-17T00:15:00+00:00', last_cycle_at='2026-11-17T03:17:00+00:00')
            self.assertEqual(next_cycle_at(self.db, plan, {'interval_minutes': 60}),
                             instant('2026-11-17T04:15:00+00:00'))

    def test_market_plan_cannot_reuse_an_unbound_or_previous_revision_price_proof(self):
        now = datetime.now(timezone.utc)
        plan = dict(plan_id='plan', revision=5, mode='smart', smart_strategy_version='market-anchor-v1')
        for binding in (None, dict(plan_id='plan', revision=4, strategy_version='market-anchor-v1', parameters_sha256='old')):
            inputs = dict(captured_at=now.isoformat(), valid_until=(now+timedelta(minutes=15)).isoformat(),
                          plan_binding=binding)
            result = runtime._prove_curve_inputs('PS', inputs, self.db, now, plan=plan)
            self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
            self.assertEqual(result['gaps'], ['pricing_curve_strategy_revision_changed'])

    def test_readonly_current_preference_without_a_source_keeps_the_proven_current_curve(self):
        from test_curve_strategy_v6 import fixture
        from fc_pricing_v3.price_curve import curve_key
        current,reference,episode=fixture()
        entry=dict(primary_curve=current,all_before=current,editor_contract=current['native_contract'],
                   primary_inputs={curve_key(current):{}},all_inputs={},all_targets={})
        with patch('fc_pricing_v3.curve_strategy_v6.build_candidates',return_value={'candidates':[],
                   'gaps':{'CURRENT':['normal_candidate_unavailable']}}), \
             patch.object(runtime,'_validated_curve',return_value={'status':'PROVEN'}):
            runtime._freeze_cost_protection('PS',entry,Mock(),dict(reference=reference,episode=episode),
                                           None,{'competitor_offers':[]},datetime.now(timezone.utc),{})
        self.assertEqual(entry['temporary_cost_protection']['status'],'PROVEN')
        self.assertEqual(entry['temporary_cost_protection']['final_key'],curve_key(current))

    def test_market_history_keeps_seven_day_quote_evidence_and_identifies_natural_rounds(self):
        from test_curve_strategy_v6 import position_offers

        now = datetime.now(timezone.utc)
        for ident, age, automatic in (('old', 193, True), ('a', 2, True), ('b', 1, True),
                                       ('manual', .5, False), ('future', -1, True)):
            at = now-timedelta(hours=age)
            self.db.put('pricing_snapshots', ident, dict(origin='live_collector', write_protocol=CURVE_WRITE_PROTOCOL,
                created_at=at.isoformat(), evidence=dict(competitor_offers=position_offers(at, '7', '8'))))
            if automatic:
                self.db.put('strategy_decisions', ident, dict(automatic_curve_round=True, curve_round_id='round-'+ident))
        history = runtime._curve_market_history(self.db, now, exclude_snapshot='b')
        self.assertEqual({row['snapshot_id'] for row in history}, {'a', 'manual'})
        self.assertEqual(next(row for row in history if row['snapshot_id']=='a')['round_id'], 'round-a')
        self.assertFalse(next(row for row in history if row['snapshot_id']=='manual')['automatic'])

    def test_market_anchor_is_recompiled_after_caps_and_keeps_a_small_change_in_the_dead_zone(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import MODEL
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT, curve_key, read_curve
        from test_curve_strategy_v6 import fixture, position_offers
        from test_pricing_proof_v6 import fixture as proof_fixture

        self.prepare()
        current, reference, episode = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        stale = read_curve(current['native_payload'], current['identity'], editor)
        current = read_curve(dict(current['native_payload'], unit_price='0.095'), current['identity'], editor)
        all_row = dict(current['native_payload'], id=writer.PRODUCTS[PLATFORM][0], site_id=0)
        before = read_curve(all_row, dict(current['identity'], id=all_row['id'], site_id=0), editor)
        def inputs(curve):
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            amount = next(row['native_price_usd'] for row in curve['tiers'] if row['purchase_k'] == '1000')
            average = dict(contract=MODEL, platform=PLATFORM, site_id='266', status='complete', retained_ratio='1')
            average['revision'] = fingerprint(average)
            domain.update(curve_key=key, version=self.capability['domain_version'],
                          source_revisions=dict(self.capability['source_revisions'], offers=average['revision']))
            self.capability['source_revisions'] = domain['source_revisions']
            evidence.update(curve_key=key, average_discount=average)
            evidence['paths'][0].update(curve_key=key, regular_usd=amount, net_receipt_usd=amount,
                                       expected_cost_usd='40', safe_cost_usd='40', stress_cost_usd='40', known_fee_usd='0')
            return dict(baskets=baskets, evidence=evidence, domain=domain)
        now = datetime.now(timezone.utc)
        for loot, u7, expected in (('7.5', '8.12', {'small': Decimal('8.5'), 'large': Decimal('80.75')}),
                                    ('9.35', '11', {'small': Decimal('10'), 'large': Decimal('99.11')}),
                                    (None, None, {'small': Decimal('10'), 'large': Decimal('95')})):
            entry = dict(primary_curve=current, all_before=before, editor_contract=editor, native_route=None,
                primary_inputs={}, all_inputs={}, all_targets={}, price_insurance=dict(
                    day_anchors={'small': '10', 'large': '95'}, market_per_100k=['10'], below_margin_rounds=0))
            previous = dict(segments={'large': dict(normal='90', target='95', release_rounds=1)}) if loot is None else {}
            runtime._freeze_cost_protection(PLATFORM, entry, inputs, dict(reference=reference, episode=episode),
                dict(mode='smart', smart_strategy_version='market-anchor-v1'),
                dict(competitor_offers=position_offers(now, loot, u7) + [dict(position_offers(now, '7', None)[0], source='U4GM')]), now, previous)
            frozen = entry['temporary_cost_protection']
            self.assertEqual(frozen['status'], 'PROVEN', frozen)
            self.assertEqual({k: Decimal(v) for k, v in frozen['final_anchors'].items()}, expected)
            self.assertEqual(frozen['preference']['source'], 'market_anchor')
            self.assertNotIn('U4GM', frozen['market_anchor']['current_quotes'])
            if loot is None:
                self.assertEqual(frozen['segments']['large']['release_rounds'], 2)
                later = dict(segments=frozen['segments'])
                runtime._freeze_cost_protection(PLATFORM, entry, inputs, dict(reference=reference, episode=episode),
                    dict(mode='smart', smart_strategy_version='market-anchor-v1'),
                    dict(competitor_offers=[]), now, later)
                released = entry['temporary_cost_protection']
                self.assertEqual(Decimal(released['final_anchors']['large']), Decimal('90'))
                self.assertEqual(released['segments'], {})
            if loot == '9.35':
                self.assertIn('small', frozen['stability'], {k: frozen.get(k) for k in
                    ('normal_anchors', 'final_anchors', 'stability', 'market_anchor')})
                self.assertEqual(frozen['stability']['small']['reason'], 'dead_zone')
                self.assertEqual(frozen['segments'], {}, 'market dead zone is not a financial floor')
            from copy import deepcopy
            entry['temporary_cost_protection'] = dict(status='PROVEN', final_anchors={'small': '10', 'large': '95'},
                preference={'source': 'smart_three_hour_block'})
            actual_entry = deepcopy(entry)
            old_plan = dict(plan_id='plan', revision=4, mode='smart', smart_strategy_version='smart-three-platform-v3')
            with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
                runtime._freeze_anchor_shadow(PLATFORM, entry, inputs, dict(reference=reference, episode=episode),
                    old_plan, dict(run_id='source', competitor_offers=position_offers(now, loot, u7)), now, {})
            shadow = entry.pop('anchor_shadow')
            self.assertEqual(entry, actual_entry)
            self.assertEqual(shadow['status'], 'KEEP' if loot is None else 'READY', shadow)
            self.assertEqual(shadow['would_write'], loot is not None)
            self.assertEqual(shadow['plan_revision'], 4)
            if loot is None:
                # Same prices, stale unit_price: the hold round must still write the cheaper band rate.
                stale_all = dict(stale['native_payload'], id=all_row['id'], site_id=0)
                stale_entry = dict(deepcopy(actual_entry), primary_curve=stale, all_before=read_curve(
                    stale_all, dict(stale['identity'], id=all_row['id'], site_id=0), editor))
                with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
                    runtime._freeze_anchor_shadow(PLATFORM, stale_entry, inputs, dict(reference=reference, episode=episode),
                        old_plan, dict(run_id='source', competitor_offers=[]), now, {})
                stale_shadow = stale_entry.pop('anchor_shadow')
                self.assertEqual(stale_shadow['status'], 'READY', stale_shadow)
                self.assertTrue(stale_shadow['would_write'])
                self.assertEqual(stale_shadow['target_curve']['unit_price_usd_per_k'], '0.095')
                self.assertEqual([row['native_price_usd'] for row in stale_shadow['target_curve']['tiers']],
                                 [row['native_price_usd'] for row in stale['tiers']])

        # Re-run the same proof producer for natural off-hour and manual requests.
        from fc_pricing_v3.price_curve import compile_curve
        from fc_pricing_v3.curve_strategy_v6 import market_anchor_parameters
        parameters = market_anchor_parameters()
        for bands in parameters.values():
            for terms in bands.values():
                terms['p_low'] = '-.10'
        reset = compile_curve(current, {'anchor_prices_usd': {1000: '119.49'}}, editor)
        for automatic in (False, True):
            entry = dict(primary_curve=reset, all_before=runtime._all_curve_target(before, reset),
                editor_contract=editor, primary_inputs={}, all_inputs={}, all_targets={},
                margin_band_context=dict(automatic=automatic, at=now.replace(hour=5)), price_insurance=dict(
                    day_anchors={'small': '10', 'large': '70.11'}, recovery_bands=['large'],
                    market_per_100k=['8'], below_margin_rounds=0))
            plan = dict(mode='smart', smart_strategy_version='market-anchor-v1', parameters=dict(
                market_anchor=parameters, margin_band={'schedule_hours': [6], PLATFORM: {'target': '.31'}}))
            runtime._freeze_cost_protection(PLATFORM, entry, inputs, dict(reference=reference, episode=episode),
                plan, dict(competitor_offers=position_offers(now, '7', '8')), now, {})
            frozen = entry['temporary_cost_protection']
            self.assertEqual(frozen['status'], 'PROVEN', frozen['gaps'])
            self.assertEqual(frozen['final_anchors']['large'], '101.57')
            self.assertEqual(frozen['normal_anchors']['small'], '10')
            self.assertEqual(frozen['price_insurance']['continuing_recovery'], ['large'])
            self.assertFalse(frozen['preference']['margin_band']['decision_round']['is_decision_round'])

    def test_market_anchor_plan_selects_both_bands_without_a_three_hour_trial(self):
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        plan = dict(mode='smart', smart_strategy_version='market-anchor-v1')
        selected = runtime._curve_preference('PS', current, {}, {}, datetime.now(timezone.utc),
                                            plan=plan, state=dict(reference=reference, episode=episode))
        self.assertEqual(selected, dict(source='market_anchor', label='A', segment='both'))

    def test_median_cost_replaces_old_cohort_maximum_in_the_actual_curve_proof(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        curve, _, _ = fixture()
        orders = list(rows_for([48] * 3))
        source = attachment(orders)
        source['historical_orders_coverage'].update(shared_publication_id='pin', shared_source_revision='source',
                                                   paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for row in source['historical_orders']:
            row.update(single_line_unit_purchase=True, merchandise_before_discount_usd='100', actual_es_discount_usd='0')
        cost = smooth_delivery_cost(dict(platform='PS', checked_at=AS_OF.isoformat(), v6_delivery_samples=dict(
            window_complete=True, history_complete=True, records=[dict(platform='PS', status='valid', record_id=str(i),
                trade_at=(AS_OF-timedelta(minutes=i)).isoformat(), cny_per_1k=value)
                for i, value in enumerate(('.37', '.40', '.42', '.40', '.398', '.41'))])), 'PS', AS_OF, '.4')
        frozen = runtime._average_discount_proof_input(curve, 'PS', source, source, CUT.isoformat(), AS_OF,
            average=average_discount(source, 'PS', CUT), route={'propagation_revision': 'directory'},
            facts=facts(orders, cost='618', delivery_fields=dict(qty='1030', gift='0', cost_unit='.6')),
            fx=fx(), current_cost=cost)
        path = next(row for row in frozen['evidence']['paths'] if row['purchase_k'] == '1000')
        self.assertEqual(path['cost_status'], 'verified')
        self.assertAlmostEqual(Decimal(path['stress_cost_usd']), Decimal('412') / 7)
        self.assertEqual(path['cost_sample_contract'], 'latest_3h_segmented_quantity_weighted_delivery_median_v2')
        missing = runtime._average_discount_proof_input(curve, 'PS', source, source, CUT.isoformat(), AS_OF,
            average=average_discount(source, 'PS', CUT), route={'propagation_revision': 'directory'},
            facts=facts(orders, cost='412', delivery_fields=dict(qty='1030', gift='0', cost_unit='.4')),
            fx=fx(), current_cost=smooth_delivery_cost(None, 'PS', AS_OF, '.4'))
        self.assertTrue(all(row.get('cost_status') != 'verified' for row in missing['evidence']['paths']))

    def test_quantity_weighted_segment_cost_flows_into_financial_proof(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, fx, rows_for
        from test_curve_strategy_v6 import fixture

        curve, _, _ = fixture()
        source = attachment(list(rows_for([48] * 3)))
        source['historical_orders_coverage'].update(shared_publication_id='pin', shared_source_revision='source',
                                                   paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for row in source['historical_orders']:
            row.update(single_line_unit_purchase=True, merchandise_before_discount_usd='100', actual_es_discount_usd='0')
        rows = [dict(platform='PS', status='valid', record_id=str(i), trade_at=AS_OF.isoformat(),
                     cny_per_1k=price, quantity_evidence=dict(ordered_k=quantity))
                for i, (quantity, price) in enumerate([('100', '.25')] * 6 + [('1000', '.286')] * 6)]
        cost = smooth_delivery_cost(dict(platform='PS', checked_at=AS_OF.isoformat(), v6_delivery_samples=dict(
            window_complete=True, history_complete=True, records=rows)), 'PS', AS_OF, '.25')
        frozen = runtime._average_discount_proof_input(curve, 'PS', source, source, CUT.isoformat(), AS_OF,
            average=average_discount(source, 'PS', CUT), route={'propagation_revision': 'directory'},
            facts=None, fx=fx(), current_cost=cost)
        paths = {row['purchase_k']: row for row in frozen['evidence']['paths']}
        for quantity, price in (('100', '.25'), ('1000', '.286')):
            path = paths[quantity]
            expected = Decimal(path['promised_delivered_k']) * Decimal(price) / 7
            for kind in ('expected', 'safe', 'stress'):
                self.assertEqual(Decimal(path[kind + '_cost_usd']), expected)

    def test_curve_state_omits_stale_promotion_audit_after_plan_revision(self):
        from fc_pricing_v3.api import _curve_decision

        audit = dict(active=True, max_absorb='.045')
        margins = dict(target='.31', bands=dict(small=dict(margin_at_current='.29',
                                                           business_margin_at_current='.315', action='hold')))
        snapshot = dict(plan_id='plan', plan_revision=1, result=dict(status='KEEP',
            rows=[dict(platform='PS', status='KEEP', selection=dict(margin_band=dict(margins, promotion_guard=audit)))]))
        current = _curve_decision(snapshot, dict(plan_id='plan', revision=1))['rows'][0]['selection']
        self.assertEqual(current['promotion_guard'], audit)
        self.assertEqual(current['margin_band'], dict(target='.31', bands=dict(
            small=dict(margin_at_current='.29', business_margin_at_current='.315'))))
        stale = _curve_decision(snapshot, dict(plan_id='plan', revision=2))['rows'][0]['selection']
        self.assertNotIn('promotion_guard', stale)
        self.assertNotIn('margin_band', stale)

    def test_only_automatic_rounds_count_toward_the_two_round_margin_exception(self):
        now = datetime.now(timezone.utc)
        for key, age, automatic, status, insurance in (
                ('second', 1, True, 'READY', {'below_margin': True}),
                ('first', 2, True, 'READY', {'below_margin': True}),
                ('preview', 0, False, 'KEEP', None),
                ('unrelated_failure', 0, True, 'PROOF_INCOMPLETE', None)):
            self.db.put('strategy_decisions', key, dict(created_at=(now-timedelta(hours=age)).isoformat(),
                automatic_curve_round=automatic, curve_round_id=key,
                curve=[dict(platform='PS', status=status, selection={'price_insurance': insurance})]))
        self.assertEqual(runtime._curve_insurance_context(self.db, 'PS', {}, now)['below_margin_rounds'], 2)
        self.db.put('strategy_decisions', 'keep', dict(created_at=now.isoformat(), automatic_curve_round=True,
            curve_round_id='keep', curve=[dict(platform='PS', status='KEEP', selection={'price_insurance': None})]))
        self.assertEqual(runtime._curve_insurance_context(self.db, 'PS', {}, now)['below_margin_rounds'], 0)

    def test_fewer_than_three_distinct_platform_cost_samples_cannot_produce_a_write_proof(self):
        from fc_pricing_v3.average_discount_v6 import average_discount
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        curve, _, _ = fixture()
        current_cost = dict(platform='PS', status='valid', game='FC27', product='Game Coins', unit='CNY/K',
            genre='1', record_id='99', cny_per_1k='.4', checked_at=AS_OF.isoformat(), trade_at=CUT.isoformat())
        for size, expected in ((1, None), (2, 'verified'), (3, 'verified')):
            orders = list(rows_for([48] * size))
            source = attachment(orders)
            source['historical_orders_coverage'].update(shared_publication_id='pin', shared_source_revision='source',
                paid_window_start=(CUT-timedelta(days=8)).isoformat())
            for row in source['historical_orders']:
                row.update(single_line_unit_purchase=True, merchandise_before_discount_usd='100', actual_es_discount_usd='0')
            deliveries = facts(orders, cost='412', delivery_fields=dict(qty='1030', gift='0', cost_unit='.4'))
            if size == 3:
                bad = deliveries['orders'][-1]
                bad['observed_cost_cny'] = '409940'
                bad['cost_records'][0].update(cost_cny='409940', cost_unit_cny='398')
            frozen = runtime._average_discount_proof_input(curve, 'PS', source, source, CUT.isoformat(), AS_OF,
                average=average_discount(source, 'PS', CUT), route={'propagation_revision': 'directory'},
                facts=deliveries, fx=fx(), current_cost=current_cost)
            proof = runtime._validated_curve(curve, frozen)
            path = next(row for row in proof['paths'] if row['purchase_k'] == '1000')
            self.assertEqual(path.get('cost_status'), expected)
            if size == 1:
                self.assertEqual(proof['status'], 'PROOF_INCOMPLETE')
                self.assertIn('curve_cost_samples_insufficient', frozen['domain']['coverage_gaps'])
            else:
                self.assertNotIn('curve_cost_sample_outlier', frozen['domain']['coverage_gaps'])
        missing = runtime._average_discount_proof_input(curve, 'PS', source, source, CUT.isoformat(), AS_OF,
            average=average_discount(source, 'PS', CUT), route={'propagation_revision': 'directory'},
            facts=None, fx=fx(), current_cost=None)
        self.assertIn('ordinary_delivery_cost_sample_missing', missing['domain']['coverage_gaps'])
        self.assertNotIn('curve_cost_sample_outlier', missing['domain']['coverage_gaps'])

    def test_cost_recovery_requires_natural_proven_scope_and_newer_capture(self):
        from fc_pricing_v3 import ledger
        from fc_pricing_v3.cost_inputs_v6 import COST_SAMPLE_OUTLIER, COST_SOURCE_MISSING
        from fc_pricing_v3.price_curve import curve_key
        from test_curve_strategy_v6 import fixture

        self.prepare()
        now = datetime.now(timezone.utc)
        run, operation = 'recovery-snapshot', 'natural-round'
        plan = dict(self.db.get('pricing_plans', 'plan'), resources=['base:PS'],
                    write_protocol=CURVE_WRITE_PROTOCOL)
        self.db.put('pricing_plans', 'plan', plan)
        with patch.object(ledger, 'clock', return_value=now - timedelta(minutes=5)):
            legacy = self.db.incident(COST_SAMPLE_OUTLIER, 'cost', ['PC', 'PS'])
            missing = self.db.incident(COST_SOURCE_MISSING, 'cost', ['PS'])
        curve, _, _ = fixture()
        key = curve_key(curve)
        from fc_pricing_v3.pricing_proof_v6 import CONTRACT
        proof = dict(status='PROVEN', contract=CONTRACT, scope={'platform': 'PS'}, curve_key=key)
        proof['proof_hash'] = fingerprint(proof)
        cost = dict(status='valid', platform='PS', source_platform='PS', selected_count=6,
                    sample_contract='latest_3h_segmented_quantity_weighted_delivery_median_v2',
                    checked_at=(now - timedelta(minutes=2)).isoformat())
        from fc_pricing_v3.competitor_offers import POLICY
        evidence = dict(run_id=run, costs={'PS': cost}, competitor_policy=POLICY)
        data = dict(primary_curve=curve, primary_inputs={key: dict(evidence={'smoothed_delivery_cost': cost},
                    domain={'coverage_gaps': []})}, valid_until=(now + timedelta(minutes=10)).isoformat(),
                    readbacks=[dict(path='/admin/goods.Goods/edit?id=' + curve['identity']['id'],
                                    http_status=200, response_code=1, response_sha256='primary-readback',
                                    received_at=now.isoformat())])
        request = dict(v3_operation_id=operation)

        def collect(*, run_id=run, **flags):
            with patch.object(runtime, '_curve_proof_inputs', return_value={'PS': data}), patch.object(
                    runtime, '_prove_curve_inputs', return_value=dict(status='KEEP', proof=proof)):
                runtime.calculate_curve_cycle(self.db, dict(evidence, run_id=run_id), plan, dict(request, **flags), now)

        def recover(at=now, *, run_id=run):
            with patch.object(ledger, 'clock', return_value=at), self.db.transaction() as conn:
                self.db.recover_curve_cost_incidents(run_id, operation, conn)

        collect(run_id='preview')
        recover(run_id='preview')
        self.assertEqual(self.db.get('incidents', missing['incident_key'])['state'], 'OPEN')
        collect(run_id='manual', natural_curve_cycle=True, manual_requested=True)
        recover(run_id='manual')
        self.assertEqual(self.db.get('incidents', missing['incident_key'])['state'], 'OPEN')
        collect(run_id='rejected', natural_curve_cycle=True)
        recover(run_id='rejected')
        self.assertEqual(self.db.get('incidents', missing['incident_key'])['state'], 'OPEN')
        data['readbacks'][0]['received_at'] = (now + timedelta(seconds=1)).isoformat()
        collect(run_id='superseded', natural_curve_cycle=True)
        newer = (now + timedelta(seconds=2)).isoformat()
        self.db.put('actual_price_windows', 'confirmed-write', dict(
            operation_id='confirmed-write', resources=['base:PS'], opened_at=newer, action={}))
        recover(now + timedelta(seconds=3), run_id='superseded')
        self.assertEqual(self.db.get('incidents', missing['incident_key'])['state'], 'OPEN')
        data['readbacks'][0]['received_at'] = (now + timedelta(seconds=4)).isoformat()
        collect(natural_curve_cycle=True)
        with self.db.connect() as conn:
            queued = {row[0] for row in conn.execute("SELECT id FROM durable_jobs WHERE kind='observe'")}
        self.assertEqual(queued, {'observe:rejected','observe:superseded','observe:'+run})
        recover(now + timedelta(minutes=11))
        self.assertEqual(self.db.get('incidents', missing['incident_key'])['state'], 'OPEN')
        recover(now + timedelta(seconds=5))
        recover(now + timedelta(seconds=5))
        remaining = self.db.get('incidents', legacy['incident_key'])
        self.assertEqual((remaining['state'], remaining['affected_scopes']), ('OPEN', ['PC']))
        closed = self.db.get('incidents', missing['incident_key'])
        self.assertEqual(closed['state'], 'RESOLVED')
        record, = closed['recovery_history']
        self.assertEqual((record['snapshot_id'], record['operation_id'], record['proof_hash']),
                         (run, operation, proof['proof_hash']))
        with patch.object(ledger, 'clock', return_value=now):
            reopened = self.db.incident(COST_SOURCE_MISSING, 'cost', ['PS'])
        recover(now + timedelta(seconds=5))
        self.assertEqual(self.db.get('incidents', missing['incident_key']), reopened)
        self.assertEqual(reopened['recovery_history'], [record])

    def test_protected_target_is_recompiled_and_reproved_after_the_fifteen_percent_cap(self):
        from decimal import Decimal
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT, curve_key, read_curve
        from test_curve_strategy_v6 import fixture
        from test_pricing_proof_v6 import fixture as proof_fixture

        self.prepare()
        current, reference, episode = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        current = read_curve(current['native_payload'], current['identity'], editor)
        all_row = dict(current['native_payload'], id=writer.PRODUCTS[PLATFORM][0], site_id=0)
        before = read_curve(all_row, dict(current['identity'], id=all_row['id'], site_id=0), editor)

        def inputs(curve):
            from fc_pricing_v3.average_discount_v6 import MODEL
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            amount = next(row['native_price_usd'] for row in curve['tiers'] if row['purchase_k'] == '1000')
            domain.update(curve_key=key, version=self.capability['domain_version'],
                          source_revisions=self.capability['source_revisions'])
            average = dict(contract=MODEL, platform=PLATFORM, site_id='266', status='complete', retained_ratio='1')
            average['revision'] = fingerprint(average)
            domain['source_revisions'] = dict(domain['source_revisions'], offers=average['revision'])
            self.capability['source_revisions'] = domain['source_revisions']
            evidence['curve_key'] = key
            evidence['average_discount'] = average
            evidence['paths'][0].update(curve_key=key, regular_usd=amount, net_receipt_usd=amount,
                expected_cost_usd='100', safe_cost_usd='102', stress_cost_usd='102', known_fee_usd='0')
            return dict(baskets=baskets, evidence=evidence, domain=domain)

        entry = dict(primary_curve=current, all_before=before, editor_contract=editor, preferred_label='A',
            segment='large', native_route=None, primary_inputs={}, all_inputs={}, all_targets={},
            price_insurance=dict(day_anchors={'small': '10', 'large': '95'}, market_per_100k=['10'],
                                 below_margin_rounds=0))
        state = dict(reference=reference, episode=episode)
        now = datetime.now(timezone.utc)
        runtime._freeze_cost_protection(PLATFORM, entry, inputs, state, None, {'competitor_offers': []}, now, {})
        frozen = entry['temporary_cost_protection']
        self.assertEqual(frozen['status'], 'PROVEN', frozen)
        self.assertEqual(Decimal(frozen['final_anchors']['large']), Decimal('109.25'))
        with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            decision = runtime._prove_temporary_curve(PLATFORM, entry, current, state, {})
            main_only = runtime._prove_temporary_curve(PLATFORM, dict(entry, all_inputs={}), current, state, {})
        self.assertEqual(decision['status'], 'READY', decision)
        self.assertEqual(main_only['status'], 'PROOF_INCOMPLETE')
        self.assertEqual(main_only['gaps'], ['curve_target_all_proof_unavailable'])
        self.assertTrue(decision['selection']['price_insurance']['below_margin'])
        self.assertEqual(decision['proof']['price_insurance']['round'], 1)
        self.assertEqual(decision['proof']['waived_hard_failures'], ['platform_margin:main', 'platform_margin:recent'])

    def test_capped_margin_exception_is_limited_to_two_rounds_and_never_allows_loss(self):
        from fc_pricing_v3.pricing_proof_v6 import validate_curve
        from test_pricing_proof_v6 import fixture

        curve, baskets, evidence, domain = fixture()
        evidence['paths'][0].update(safe_cost_usd='85', stress_cost_usd='90')
        exception = dict(before_anchors={'small': '10', 'large': '86.96'},
                         clipped={'large': dict(requested='105', bounded='100')}, round=1)
        for round_number, expected in ((1, 'PROVEN'), (2, 'PROVEN'), (3, 'HARD_CONSTRAINT_FAILED')):
            result = validate_curve(curve, baskets, evidence, dict(domain, price_insurance=dict(exception, round=round_number)))
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['minimum_safe_procurement_margin'], '0.15')
        evidence['paths'][0]['stress_cost_usd'] = '101'
        result = validate_curve(curve, baskets, evidence, dict(domain, price_insurance=exception))
        self.assertEqual(result['status'], 'HARD_CONSTRAINT_FAILED')

    def test_restore_skips_move_limits_but_never_skips_market_range(self):
        from coin_all_sync_job import curve_price_insurance
        from fc_pricing_v3.price_curve import compile_curve, TWO_BAND_PRICE_EDIT
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        target = compile_curve(current, {'anchor_prices_usd': {100: '13'}}, editor)
        context = dict(day_anchors={'small': '10', 'large': '95'}, market_per_100k=['10'])
        self.assertEqual(curve_price_insurance(current, target, context, restore=True)['anchors']['small'], '13')
        with self.assertRaisesRegex(ValueError, 'pricing_curve_out_of_market_range'):
            curve_price_insurance(current, target, dict(context, market_per_100k=['1']), restore=True)
        fallback = dict(context, market_per_100k=[])
        self.assertEqual(curve_price_insurance(current, target, fallback, restore=True)['anchors']['small'], '13')

    def test_thousandfold_cost_cannot_generate_the_historical_6842_price(self):
        from fc_pricing_v3.average_discount_v6 import minimum_band_price

        proof = dict(average_discount={'retained_ratio': '.904'},
            paths=[dict(path_id='small', purchase_k='100', net_receipt_usd='7.37',
                        stress_cost_usd='5685.71', known_fee_usd='0', zero_line_status='HARD_CONSTRAINT_FAILED')],
            baskets=dict(main=dict(safe_cost_usd='5685.71', members=[dict(path_id='small', weight='1')]),
                         recent=dict(safe_cost_usd='5685.71', members=[dict(path_id='small', weight='1')])))
        self.assertIsNone(minimum_band_price(proof, 'small', '100', '8.16'))

    def test_price_insurance_caps_twenty_percent_at_fifteen_and_blocks_over_forty_daily(self):
        from coin_all_sync_job import curve_price_insurance
        from fc_pricing_v3.price_curve import compile_curve, TWO_BAND_PRICE_EDIT
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        target = compile_curve(current, {'anchor_prices_usd': {100: '12.00'}}, editor)
        context = dict(day_anchors={'small': '10', 'large': '95'}, market_per_100k=['10'])
        result = curve_price_insurance(current, target, context)
        self.assertEqual(result['anchors']['small'], '11.50')
        self.assertEqual(result['clipped']['small']['requested'], '12')
        with self.assertRaisesRegex(ValueError, 'pricing_curve_daily_move_exceeded'):
            curve_price_insurance(current, target, dict(context, day_anchors={'small': '8', 'large': '95'}))

    def test_admin_drift_compares_last_confirmed_all_and_skips_intervening_writes(self):
        from copy import deepcopy
        from test_curve_writer_v6 import saved

        self.prepare()
        self.assertEqual(self.execute()['status'], 'COMPLETED')
        now = datetime.now(timezone.utc)
        after = self.bundle['action']['curves'][PLATFORM]
        def compare(curve):
            return runtime._external_curve_context(self.db, PLATFORM, curve, now)
        self.assertFalse(compare(after).get('external_change'))
        row = deepcopy(after['native_payload'])
        for field, value in dict(gold='500', give='0', discount='100', price='50', hot='0', delivery_time='10').items():
            row['more'][field].append(value)
        change = compare(saved(row))['external_change']
        self.assertEqual((change['price_changed'], change['structure_changed']), (False, True))
        row['more']['price'][1] = '119.49'
        context = compare(saved(row))
        self.assertEqual(context['recovery_bands'], ['large'])
        self.assertTrue(context['external_change']['price_changed'])
        self.assertEqual(context['external_change']['operation_id'], OPERATION)
        self.db.put('operations', 'in-flight', dict(status='UNKNOWN', resources=['base:PS']))
        self.assertEqual(compare(saved(row)), {})

    def test_external_reset_replay_uses_inward_cent_steps_and_requires_evidence(self):
        from coin_all_sync_job import curve_price_insurance
        from fc_pricing_v3.price_curve import compile_curve, TWO_BAND_PRICE_EDIT
        from test_curve_strategy_v6 import fixture

        source, _, _ = fixture()
        editor = dict(source['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        def curve(price):
            return compile_curve(source, {'anchor_prices_usd': {1000: price}}, editor)
        context = dict(day_anchors={'small': '10', 'large': '70.11'}, market_per_100k=['7'],
                       recovery_bands=['large'], market_high={'large': '70.11'})
        price = '119.49'
        for expected in ('101.57', '86.34', '73.39', '70.11'):
            result = curve_price_insurance(curve(price), curve('70.11'), context)
            self.assertEqual(Decimal(result['anchors']['large']), Decimal(expected))
            self.assertFalse(curve_price_insurance(curve(price), curve(expected), context)['clipped'])
            price = expected
        with self.assertRaisesRegex(ValueError, 'daily_move_exceeded'):
            curve_price_insurance(curve('119.49'), curve('70.11'), dict(context, recovery_bands=[]))
        with self.assertRaisesRegex(ValueError, 'daily_reference_unavailable'):
            curve_price_insurance(curve('119.49'), curve('70.11'), dict(context, day_anchors={'small': '10'}))
        # Low reset moves up, even when requested price stays low. Both sides stop inside the daily corridor.
        context.update(day_anchors={'small': '10', 'large': '100'}, market_per_100k=['8'])
        for current, requested, expected in [('52', '52', '59.80'), ('59', '1', '60'), ('141', '1', '119.85')]:
            with self.subTest(current=current):
                value = curve_price_insurance(curve(current), curve(requested), context)['anchors']['large']
                self.assertEqual(Decimal(value), Decimal(expected))

    def test_insurance_both_directions_daily_boundaries_and_next_round(self):
        from coin_all_sync_job import curve_price_insurance
        from fc_pricing_v3.price_curve import compile_curve, TWO_BAND_PRICE_EDIT
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        def curve(price):
            return compile_curve(current, {'anchor_prices_usd': {100: price}}, editor)
        context = dict(day_anchors={'small': '10', 'large': '95'}, market_per_100k=['10'])
        for target, expected in (('12', '11.50'), ('8', '8.50')):
            with self.subTest(target=target):
                self.assertEqual(curve_price_insurance(current, curve(target), context)['anchors']['small'], expected)
        # Each natural round uses the confirmed current price and a freshly computed target.
        self.assertEqual(curve_price_insurance(curve('11.50'), curve('13'), context)['anchors']['small'], '13')
        self.assertEqual(curve_price_insurance(curve('11.50'), curve('10.50'), context)['anchors']['small'], '10.5')
        for price, allowed in (('14', True), ('14.01', False), ('6', True), ('5.99', False)):
            with self.subTest(price=price):
                before = curve('13' if price.startswith('14') else '6.50')
                if allowed:
                    self.assertEqual(curve_price_insurance(before, curve(price), context)['anchors']['small'], price)
                else:
                    with self.assertRaisesRegex(ValueError, 'pricing_curve_daily_move_exceeded'):
                        curve_price_insurance(before, curve(price), context)

    def test_temporary_floor_releases_on_the_third_cost_retreat_round(self):
        from copy import deepcopy
        from fc_pricing_v3.average_discount_v6 import MODEL
        from fc_pricing_v3.price_curve import curve_key, read_curve, TWO_BAND_PRICE_EDIT
        from test_curve_strategy_v6 import fixture

        live, reference, episode = fixture()
        editor = dict(live['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        make_curve = lambda row, identity: read_curve(row, identity, editor)
        live = make_curve(live['native_payload'], live['identity'])
        evidence = {'competitor_offers': []}
        now = datetime.now(timezone.utc)
        previous = {}
        for high, expected in (('83.804', '102.2'), ('83.7', '102.2'), ('83.7', '102.2'), ('83.7', '102.2'),
                               ('83.804', '102.2'), ('83.9', '102.32'),
                               ('70', '102.32'), ('70', '102.32'), ('70', '95'),
                               ('83.804', '102.2'), ('70', '102.2'), ('70', '102.2'), ('70', '95')):
            all_row = dict(live['native_payload'], id=writer.PRODUCTS[PLATFORM][0], site_id=0)
            all_before = make_curve(all_row, dict(live['identity'], id=all_row['id'], site_id=0))

            def inputs(curve):
                return {'key': curve_key(curve), 'tiers': curve['tiers']}

            def validate(curve, frozen):
                tier = next(r for r in frozen['tiers'] if r['purchase_k'] == '1000')
                from decimal import Decimal
                amount = Decimal(tier['native_price_usd'])
                path = dict(path_id='high', purchase_k='1000', net_receipt_usd=str(amount), stress_cost_usd='72',
                            known_fee_usd='0', zero_line_status='PROVEN')
                status = 'PROVEN' if amount * Decimal('.82') >= Decimal(high) else 'HARD_CONSTRAINT_FAILED'
                basket = dict(safe_cost_usd=high, members=[{'path_id': 'high', 'weight': '1'}])
                return dict(status=status, average_discount={'contract': MODEL, 'retained_ratio': '1'},
                            paths=[path], baskets=dict(main=basket, recent=basket), gaps=[], hard_failures=[])

            entry = dict(primary_curve=live, all_before=all_before, editor_contract=editor, preferred_label='A',
                         segment='large', primary_inputs={}, all_inputs={}, all_targets={})
            with patch.object(runtime, '_validated_curve', side_effect=validate):
                runtime._freeze_cost_protection(PLATFORM, entry, inputs, dict(reference=reference, episode=episode),
                                                None, evidence, now, previous)
            frozen = entry['temporary_cost_protection']
            self.assertEqual(frozen['status'], 'PROVEN', frozen)
            self.assertEqual(frozen['normal_anchors']['large'], '95')
            self.assertEqual(frozen['final_anchors']['large'], expected)
            self.assertEqual(frozen['final_anchors']['small'], frozen['normal_anchors']['small'])
            live = make_curve(deepcopy(frozen['final_curve']['native_payload']), live['identity'])
            previous = {'segments': frozen['segments']}

    def test_small_labels_and_pairs_use_the_confirmed_large_protection_curve(self):
        from decimal import Decimal
        from fc_pricing_v3.price_curve import compile_curve, curve_key, read_curve, TWO_BAND_PRICE_EDIT
        from fc_pricing_v3.smart import paired_exposure
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        editor = dict(current['native_contract'], price_edit_policy=TWO_BAND_PRICE_EDIT)
        current = read_curve(current['native_payload'], current['identity'], editor)

        def observed(label, small, large, *, platform='PS', protected_small=None):
            normal = compile_curve(current, {'anchor_prices_usd': {100: small}}, editor)
            controls = {1000: large}
            segments = {'large': {'target': large}}
            if protected_small is not None:
                controls[100] = protected_small
                segments['small'] = {'target': protected_small}
            final = compile_curve(normal, {'anchor_prices_usd': controls}, editor)
            state = dict(reference=reference, episode=episode)
            previous = {'segments': segments}
            key = curve_key(final)
            frozen = dict(reference_curve_id=reference['reference_curve_id'],
                comparison_episode_id=episode['comparison_episode_id'], previous=previous,
                status='PROVEN', final_key=key, labels=[label], normal_curve=normal,
                final_curve=final, normal_anchors={}, final_anchors={}, segments=segments, gaps=[],
                preference=dict(segment='small', label=label, restore_other_band=True,
                                assignment={'background_curve_key': None}))
            with patch('fc_pricing_v3.pricing_proof_v6.validate_frozen_curve', return_value={'status': 'PROVEN'}):
                row = runtime._prove_temporary_curve(platform, dict(temporary_cost_protection=frozen,
                    primary_inputs={key: {'evidence': {'curve_key': key}}}), final, state, previous)
            self.assertEqual(row['status'], 'KEEP')
            self.assertEqual(row['selection']['cost_protection']['segments'], segments)
            assignment = row['selection']['assignment']
            return dict(label=assignment['actual_label'], prices=[key], intervals=[[0, 10800]],
                        display_regime_key=assignment['background_curve_key'])

        a = observed('A', '10', '103')
        b = observed('B', '9.7', '103')
        self.assertEqual((a['label'], b['label']), ('A', 'B'))
        self.assertEqual(paired_exposure([a], [b])[3], Decimal('3'))
        self.assertIsNone(paired_exposure([a], [observed('B', '9.7', '104')]))
        self.assertEqual(observed('B', '9.7', '103', protected_small='10')['label'], 'CURRENT')
        for platform in ('XBOX', 'PC'):
            self.assertEqual(observed('B', '9.7', '103', platform=platform)['label'], 'B')
            self.assertEqual(observed('B', '9.7', '103', platform=platform, protected_small='10')['label'], 'CURRENT')

    def test_large_reference_scales_price_and_gift_without_scaling_unit_price(self):
        from decimal import Decimal
        from fc_pricing_v3.curve_strategy_v6 import large_market_comparison, large_market_reference
        from test_curve_strategy_v6 import fixture

        curve, _, _ = fixture()
        now = datetime.now(timezone.utc)
        offer = dict(source='U7Buy', platform='PS', purchase_k='100', regular_price='8', bonus_k='3',
                     currency='USD', region_id='0', delivery_method='comfort_trade', captured_at=now.isoformat(),
                     comparable=True, promotion_eligibility='all_customers', eligible_net_price='5')
        references = large_market_reference('PS', [offer, dict(offer, region_id='21'), dict(offer, delivery_method='normal')],
                                            now, region_id='0', delivery_method='comfort_trade')
        self.assertEqual(len(references), 1)
        result = large_market_comparison(references, curve, curve)[0]
        self.assertEqual((result['price_usd'], result['bonus_k'], result['captured_at']), ('80', '30', now.isoformat()))
        self.assertEqual(Decimal(result['usd_per_delivered_100k']), Decimal(8000) / 1030)
        self.assertEqual(result['normal_difference_pct'], result['final_difference_pct'])

    def test_formal_adoption_evidence_carries_forward_cumulative_result(self):
        from decimal import Decimal
        from fc_pricing_v3.smart import curve_adoption_evidence

        def block(label, key, amount, start, end):
            return dict(pair_id='pair', hours=Decimal(2), complete=True, label=label,
                        display_regime_key='same-background', prices=[key], intervals=[(0, 7200)],
                        starts_at=start, ends_at=end, window_ids=[label],
                        events=[dict(offset=60, order_key=label, actual_net_usd=amount,
                                     actual_contribution_usd=amount, new_customer=False)])

        state = dict(reference={'adoption': {'cumulative': dict(initial_reference_curve_id='initial',
            revenue_delta_usd='10', procurement_gross_delta_usd='12', new_customer_delta='2')}},
            episode={'initial_reference_curve_id': 'initial'})
        baseline = block('A', 'a', '8', '2026-11-11T01:00:00+00:00', '2026-11-11T04:00:00+00:00')
        winner = block('C', 'c', '11', '2026-11-12T01:00:00+00:00', '2026-11-12T04:00:00+00:00')
        proof = curve_adoption_evidence([baseline, winner], 'C', state)
        self.assertEqual(proof['winning_curve_key'], 'c')
        self.assertEqual(proof['cumulative']['revenue_delta_usd'], '13')
        self.assertEqual(proof['cumulative']['procurement_gross_delta_usd'], '15')
        self.assertEqual(proof['cumulative']['new_customer_delta'], '2')

    def test_discount_and_basket_pin_wait_for_missing_yesterday(self):
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.financial import instant

        cutoff = instant('2026-11-13T16:38:48+00:00')
        pin = 'fixed-shared-publication'

        def read(scope, *, publication_id=None):
            if publication_id is not None:
                self.assertEqual(publication_id, pin)
            complete = False
            return {'scope': scope, 'coverage': {'publication_id': pin, 'complete': complete}}

        def attachment(shared, scope, **kwargs):
            complete = shared['coverage']['complete']
            return dict(historical_orders=[
                dict(order_key=platform, platform=platform, paid_at='2026-11-13T23:59:59+08:00',
                     merchandise_before_discount_usd='20', actual_es_discount_usd='2')
                for platform in ('PS', 'XBOX', 'PC')
            ], historical_orders_coverage=dict(
                window_complete=complete, population_status='complete' if complete else 'partial',
                paid_window_start=scope['start'] + ' 00:00:00',
                paid_window_end_exclusive=(instant(scope['end'] + ' 00:00:00') + timedelta(days=1)).isoformat(),
                shared_publication_id=pin, shared_source_revision=scope['end']))

        reader = Mock(side_effect=read)
        with patch.dict(sys.modules, {'shared_es_facts': SimpleNamespace(read=reader)}), \
                patch('fc_pricing_v3.business_source.shared_curve_attachment', side_effect=attachment), \
                patch.object(runtime, 'ordinary_delivery_archives', return_value='structure-costs') as costs:
            closed, facts, discount_source = runtime._shared_curve_inputs(cutoff, cutoff, code_names=None)

        for platform in ('PS', 'XBOX', 'PC'):
            result = average_discount(discount_source, platform, cutoff)
            self.assertEqual(result['status'], 'partial', result)
            self.assertIsNone(result['retained_ratio'])
        self.assertFalse(closed['historical_orders_coverage']['window_complete'])
        self.assertEqual(facts, 'structure-costs')
        self.assertEqual(costs.call_args.args[0]['end'], '2026-11-13')
        self.assertEqual(reader.call_args.kwargs, {'publication_id': pin})
        self.assertEqual(reader.call_args.args[0], dict(start='2026-11-11', end='2026-11-13',
                                                       site_id='266', gid='1327'))

    def test_large_band_smart_trial_uses_own_orders_without_competitor_quotes(self):
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        now = datetime.fromisoformat('2026-11-13T12:00:00+00:00')
        plan = dict(plan_id='plan', mode='smart', revision=1, starts_at='2026-11-13T09:00:00+00:00')
        state = dict(reference=reference, episode=dict(episode, opened_at=plan['starts_at']))
        performance = {'small': {'current': {'paid_orders': 8}}, 'large': {'current': {'paid_orders': 30}}}
        stale_large_offer = dict(source='Lootbar', platform='PS', purchase_k='1000', regular_price='10',
                                delivered_k='1000', captured_at=now.isoformat(), currency='USD',
                                promotion_eligibility='all_customers', comparable=True, conditional=False)
        no_market = runtime._curve_preference('PS', current, {}, {'performance': performance},
                                              now, plan=plan, state=state)
        old_market = runtime._curve_preference('PS', current, {'competitor_offers':[stale_large_offer]},
                                               {'performance': performance}, now, plan=plan, state=state)
        self.assertEqual(old_market, no_market)
        self.assertEqual((no_market['segment'], no_market['source']), ('large', 'smart_three_hour_block'))
        self.assertIn(no_market['label'], 'ABC')

    def test_v6_learning_uses_confirmed_full_curves_and_changes_later_assignments(self):
        from copy import deepcopy
        from fc_pricing_v3.curve_strategy_v6 import comparison_background_key
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from fc_pricing_v3.smart import curve_learning, curve_slot, observed_curve_blocks
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        start = datetime.fromisoformat('2026-11-13T00:00:00+00:00')
        now = start + timedelta(hours=49)
        plan = dict(plan_id='plan', revision=1, mode='smart', starts_at=start.isoformat())
        state = dict(reference=reference, episode=dict(episode, opened_at=start.isoformat()))
        row = deepcopy(current['native_payload'])
        row['more']['price'][4] = '97.85'
        higher = read_curve(row, current['identity'], current['native_contract'])
        self.assertEqual(current['tiers'][2], higher['tiers'][2])
        self.assertNotEqual(curve_key(current), curve_key(higher))
        slots = [curve_slot(plan, PLATFORM, state, start + timedelta(hours=3 * block)) for block in range(16)]
        pairs = [slot['slot'] for slot in slots[:8] if slot['segment'] == 'large'][:2]
        windows, outcomes = [], []
        for first in pairs:
            for label, slot, curve in (('A', slots[first], current), ('C', slots[first + 8], higher)):
                opened = datetime.fromisoformat(slot['starts_at'])
                ident = 'window-' + str(slot['block'])
                key = curve_key(curve)
                decision_key = 'all-' + key
                info = dict(slot, actual_label=label, decision_curve_key=decision_key, primary_curve_key=key,
                            background_curve_key=comparison_background_key(curve, 'large'))
                windows.append(dict(operation_id=ident, action={'curves': {PLATFORM: curve}},
                    origin='confirmed_public_price_window', mode='production', write_protocol=CURVE_WRITE_PROTOCOL,
                    opened_at=slot['starts_at'], resource_closed_at={'base:PS': slot['ends_at']},
                    mutable_resources=['base:PS'], curve_selection={PLATFORM: {'assignment': info}},
                    decision_curve_keys={PLATFORM: decision_key}, curve_confirmations={PLATFORM: dict(
                        operation_id=ident, target_curve_key=decision_key, actual_site266_curve_key=key,
                        basis='full_prices_and_tier_specs_readback')},
                    continuations=[dict(resources=['base:PS'], at=(opened + timedelta(hours=1)).isoformat(),
                                        curve_selection={PLATFORM: {'assignment': info}})]))
                for index in range(5):
                    outcomes.append(dict(order_key=f'{ident}:{index}', platform=PLATFORM, price_window_id=ident,
                        occurred_at=(opened + timedelta(minutes=25 + 30 * index)).isoformat(),
                        curve_key=key, decision_curve_key=decision_key, actual_net_usd='100',
                        actual_contribution_usd='22' if label == 'C' else '20',
                        cost_basis='same_order_Order_shipping_CNY_margin_at_actual_USD_receipt',
                        purchase_k='1000', promised_bonus_k='20', promised_delivered_k='1020',
                        new_customer=True, customer_key=f'{ident}:{index}'))
        coverage = dict(query_complete=True, unscoped_time_gaps=False, gap_events=[],
                        source_sha256='test-source', observed_at=now.isoformat())
        online = dict(smart_plan_id='plan', smart_revision=1, learning_coverage=coverage, actual_outcomes=outcomes)
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertEqual(learned['large']['policy']['winner'], 'C')
        self.assertFalse(learned['large']['policy']['causal_effect_estimated'])
        blocks = observed_curve_blocks(plan, PLATFORM, state, online, windows, now)
        self.assertEqual([(block['hours'], len(block['events'])) for block in blocks], [(3, 5)] * 4)
        self.assertEqual(len({key for block in blocks for key in block['prices']}), 2)
        scheduled_at = [now + timedelta(hours=3 * i) for i in range(16)]
        def choices(evidence):
            selected = [runtime._curve_preference(PLATFORM, current, {}, {'learning': evidence}, at,
                                                  plan=plan, state=state) for at in scheduled_at]
            return [row for row in selected if row['segment'] == 'large']
        self.assertNotEqual([row['label'] for row in choices(learned)], [row['label'] for row in choices({})])
        self.assertTrue(all(row['source'] == 'observed_curve_policy' for row in choices(learned)))
        # A later same-order cost revision updates the original exposures and corrects C.
        for order in outcomes:
            if order['curve_key'] == curve_key(higher):
                order['actual_contribution_usd'] = '16'
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertIsNone(learned['large']['policy']['winner'])
        self.assertIn('C', learned['large']['correction']['effective_blocks'])
        self.assertNotIn('C', {row['label'] for row in choices(learned)})
        # A separate small-band change is a different background for large.
        mixed = deepcopy(current['native_payload'])
        mixed['more']['price'][2] = '10.02'
        mixed = read_curve(mixed, current['identity'], current['native_contract'])
        other_background = curve_learning(plan, PLATFORM, state, online, windows, now, mixed)
        self.assertEqual(other_background['large']['correction']['effective_blocks'], {})
        # Complete paid coverage can report zero. Incomplete membership is unavailable.
        online['actual_outcomes'] = []
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertEqual(learned['large']['blocks'][-1]['platform']['orders'], 0)
        self.assertEqual(learned['large']['blocks'][-1]['platform']['procurement_gross_usd'], '0')
        self.assertIsNone(learned['large']['blocks'][-1]['platform']['procurement_margin'])
        coverage['gap_events'] = [dict(occurred_at=windows[-1]['opened_at'], group=PLATFORM)]
        learned = curve_learning(plan, PLATFORM, state, online, windows, now, current)
        self.assertIsNone(learned['large']['blocks'][-1]['platform']['orders'])
        coverage['query_complete'] = False
        self.assertEqual(curve_learning(plan, PLATFORM, state, online, windows, now, current), {})

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        enter = stack.enter_context
        folder = enter(tempfile.TemporaryDirectory())
        self.root = Path(folder)
        for name in ('quotes', 'jobs', 'executions', 'previews'):
            (self.root / name).mkdir()
        self.db = Ledger(self.root / 'v3' / 'control.sqlite3')
        enter(patch.object(runtime, 'ROOT', self.root))
        enter(patch.object(runtime, 'ledger', return_value=self.db))
        enter(patch('automation_policy.load_policy', return_value={'revision': 7}))
        self.legacy_nochange = enter(patch.object(adapters, 'verify_nochange'))
        self.legacy_postwrite = enter(patch.object(adapters, 'reconcile_postwrite'))
        self.legacy_close = enter(patch.object(runtime, 'close_on_order_admin'))
        self.preview = dict(status='review_only', preview_id='fixture-preview')
        self.worker = SimpleNamespace(APP=self.root, run=Mock(return_value=(0, self.preview)))
        enter(patch.dict(sys.modules, {'fc27_cloud_worker': self.worker}))
        self.dispatch = enter(patch.object(adapters, 'dispatch_base'))
        self.reconcile = enter(patch.object(adapters, 'reconcile_base'))

    def tearDown(self):
        self.legacy_nochange.assert_not_called()
        self.legacy_postwrite.assert_not_called()
        self.legacy_close.assert_not_called()

    def prepare(self, *, small='10', large='103', propagate=True):
        bundle, capability, before, recipient = setup_bundle(small, large)
        bundle.update(assignment_id='fixture-assignment', resources=['base:PS'])
        bundle['steps'] = [dict(step_id='base:all', kind='base', state='PENDING')]
        bundle['created_at'] = datetime.now(timezone.utc).isoformat()
        if small == '10' and large == '100':
            bundle['steps'] = []
        for action, total in ((bundle['before_action'], '10'), (bundle['action'], small)):
            action['base_prices'] = {'PS': total}
        bundle.pop('sha256')
        bundle['sha256'] = fingerprint(bundle)
        self.bundle = bundle
        plan = dict(plan_id='plan', generation='generation', revision=4, state='ACTIVE', ends_at=None,
                    parameters={'competitor_policy': POLICY})
        self.db.put('metadata', 'generation', {'id': 'generation'})
        self.db.put('pricing_plans', 'plan', plan)
        with self.db.transaction() as conn:
            conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)', ('base:PS', 'plan', 4, 'generation'))
        quote = dict(result=dict(decision_receipt=bundle), snapshot_sha256='fixture-run',
                     quote_engine_sha256='fixture-engine')
        (self.root / 'quotes' / 'run.json').write_text(json.dumps(quote))
        (self.root / 'jobs' / 'run.json').write_text(json.dumps(dict(request={})))
        self.transport = Transport(before, recipient, propagate=propagate)
        capability['order_projection'] = self.transport.projection()
        self.capabilities = {PLATFORM: capability}
        self.capability = capability
        self.reconcile.side_effect = self.read_original
        self.dispatch.side_effect = self.send_original

    @property
    def audit_path(self):
        return self.root / 'executions' / (OPERATION + '.json')

    def save_audit(self, audit):
        self.audit_path.write_text(json.dumps(audit))

    def send_original(self, operation, before_send=lambda _: None):
        item = writer.curve_catalog_plan(self.bundle, PLATFORM, self.capability)
        audit = dict(execution_id=OPERATION, write_protocol=CURVE_WRITE_PROTOCOL,
                     pricing_decision_receipt=self.bundle, selected=operation['dispatch_context']['selected'],
                     curve_results={PLATFORM: dict(item, operation_id=OPERATION)}, status='RUNNING',
                     sync_confirmed=False, changed=[], business_dispatch_started=False)
        return writer.drive_curve_catalog(self.transport, audit, self.save_audit,
                                          before_send, self.capabilities)

    def read_original(self, operation):
        self.assertEqual(operation['operation_id'], OPERATION)
        return writer.reconcile_curve_catalog(self.transport, json.loads(self.audit_path.read_text()),
                                              self.save_audit, self.capabilities)

    def execute(self):
        with patch.object(runtime, 'verify_quote', return_value=self.bundle):
            return runtime.execute_run('run')

    def leased(self):
        with closing(self.db.connect()) as conn:
            return conn.execute('SELECT operation_id FROM resource_leases').fetchall() != []

    def test_high_tier_only_dispatches_exact_platform_and_freezes_full_readback(self):
        self.prepare()
        result = self.execute()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['dispatch_context']['selected'], ['PS'])
        self.assertEqual(result['readback']['execution_id'], OPERATION)
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])
        window = self.db.get('actual_price_windows', OPERATION)
        actual = window['action']['curves']['PS']
        self.assertEqual(actual['identity']['site_id'], '266')
        self.assertEqual(actual['tiers'][1]['native_price_usd'], '103')
        self.assertEqual(json.loads(self.audit_path.read_text())['status'], 'CONFIRMED')
        self.assertFalse(self.leased())
        self.reconcile.assert_not_called()

    def test_partial_original_confirms_after_propagation_without_reposting(self):
        from fc_pricing_v3 import ledger
        from fc_pricing_v3.cost_inputs_v6 import COST_SAMPLE_OUTLIER

        self.prepare(propagate=False)
        now = datetime.now(timezone.utc)
        with patch.object(ledger, 'clock', return_value=now - timedelta(minutes=5)):
            incident = self.db.incident(COST_SAMPLE_OUTLIER, 'cost', [PLATFORM])
        run = self.bundle['snapshot_id']
        evidence = dict(run_id=run)
        self.bundle['snapshot_sha256'] = fingerprint(evidence)
        self.bundle['sha256'] = fingerprint({k: v for k, v in self.bundle.items() if k != 'sha256'})
        self.db.put('pricing_snapshots', run, dict(snapshot_id=run, evidence=evidence, origin='live_collector',
                                                 mode='production', write_protocol=CURVE_WRITE_PROTOCOL))
        self.db.put('strategy_decisions', run, dict(automatic_curve_round=True, curve_round_id=OPERATION,
                    cost_recovery={PLATFORM: dict(status='READY', snapshot_sha256=fingerprint(evidence),
                        source_captured_at=(now-timedelta(minutes=2)).isoformat(),
                        valid_until=(now+timedelta(minutes=10)).isoformat(),
                        proof_hash=self.bundle['curve_proofs'][PLATFORM]['proof_hash'])}))
        with self.db.transaction() as conn:
            self.db.recover_curve_cost_incidents(run, OPERATION, conn)
        self.assertEqual(self.db.get('incidents', incident['incident_key'])['state'], 'OPEN')
        first = self.execute()
        self.assertEqual(first['status'], 'PARTIALLY_APPLIED')
        self.assertEqual(self.db.get('incidents', incident['incident_key'])['state'], 'OPEN')
        self.assertTrue(self.leased())
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))
        self.transport.apply_recipient()
        with patch.object(self.db, 'recover_curve_cost_incidents', side_effect=ValueError('bad recovery evidence')), \
                self.assertLogs('fc_pricing_v3.runtime', level='ERROR') as recovery_log:
            recovered = runtime.reconcile(OPERATION)
        self.assertIn('curve_cost_incident_recovery_failed', recovery_log.output[0])
        self.assertEqual(recovered['status'], 'COMPLETED')
        self.assertEqual(self.db.get('operations', OPERATION)['status'], 'COMPLETED')
        self.assertEqual(self.db.get('incidents', incident['incident_key'])['state'], 'OPEN')
        self.assertEqual(recovered['readback']['execution_id'], OPERATION)
        self.assertFalse(self.leased())
        self.assertEqual(runtime.reconcile(OPERATION), recovered)
        closed = self.db.get('incidents', incident['incident_key'])
        self.assertEqual(closed['state'], 'RESOLVED')
        self.assertEqual([row['operation_id'] for row in closed['recovery_history']], [OPERATION])
        self.assertEqual(len(self.transport.posts), 1)
        self.reconcile.assert_called_once()
        self.dispatch.assert_called_once()

    def test_manual_restore_uses_confirmed_non_linear_before_and_rechecks_current_proof(self):
        from copy import deepcopy
        from fc_pricing_v3 import api, scheduler
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import IDENTITY_FIELDS, TWO_BAND_PRICE_EDIT, curve_key, read_curve
        from test_pricing_proof_v6 import basket, quote

        self.prepare()
        contract = dict(EDITOR_CONTRACT, price_edit_policy=TWO_BAND_PRICE_EDIT)

        def read(row):
            return read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, contract)

        all_id, site_id, _ = writer.PRODUCTS[PLATFORM]
        for row in self.transport.rows.values():
            row['more']['gold'].append('1500')
            row['more']['price'].append('149.95')
            row['more']['give'].append('55')
            row['more']['discount'].append('100')
            row['more']['delivery_time'].append('10')
            row['more']['hot'].append('0')
        self.transport.rows[all_id]['unit_price'] = '0.12'
        old = read(self.transport.rows[all_id])
        changed_row = deepcopy(old['native_payload'])
        changed_row['more']['price'] = ['10', '103', '154.50']
        changed_row['unit_price'] = '0.1'
        changed = read(changed_row)
        self.bundle['before_action']['curves'][PLATFORM] = old
        self.bundle['action']['curves'][PLATFORM] = changed

        def frozen(curve, cost):
            key = curve_key(curve)
            domain = dict(self.bundle['curve_proofs'][PLATFORM]['scope'], curve_key=key,
                          coverage_status='complete', coverage_gaps=[])
            path = quote('ordinary', key, regular_usd='149.95', net_receipt_usd='149.95',
                         safe_cost_usd=cost, expected_cost_usd='115', stress_cost_usd='130')
            return dict(baskets=dict(main=basket('closed_bjt_7d', [('ordinary', '50')]),
                                     recent=basket('latest_24h', [('ordinary', '30')])),
                        evidence=dict(curve_key=key, paths=[path]), domain=domain)

        self.bundle['curve_proofs'][PLATFORM] = runtime._validated_curve(changed, frozen(changed, '120'))
        self.bundle['sha256'] = fingerprint({key: value for key, value in self.bundle.items() if key != 'sha256'})
        quote_path = self.root / 'quotes/run.json'
        original_quote = json.loads(quote_path.read_text())
        original_quote['result']['decision_receipt'] = self.bundle
        quote_path.write_text(json.dumps(original_quote))
        self.assertEqual(self.execute()['status'], 'COMPLETED')
        self.assertEqual(len(self.transport.posts), 1)

        now = datetime.now(timezone.utc)
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL, activation_revision=1,
                    resources=['base:PS'], starts_at=(now - timedelta(hours=1)).isoformat())
        self.db.put('pricing_plans', 'plan', plan)
        preview_body = dict(request_key='restore-before', plan_id='plan', reason='Restore exact prior table',
                            restore_source_execution_id=OPERATION)
        with patch.object(api, 'ledger', return_value=self.db):
            preview = api.post('manual-previews', preview_body, 'wulv')
            self.assertEqual(preview, api.post('manual-previews', preview_body, 'wulv'))
            self.assertEqual(preview['restore_tiers']['PS'][-1]['native_price_usd'], '149.95')
            self.assertFalse(preview['execution_authorized'])
            execute = dict(request_key='restore-confirm', plan_id='plan', manual_preview_id=preview['manual_preview_id'])
            accepted = api.post('execute', execute, 'wulv')
            self.assertEqual(api.post('execute', execute, 'wulv'), accepted)
        with closing(self.db.connect()) as conn:
            queue = json.loads(conn.execute('SELECT body FROM durable_jobs WHERE id=?', (accepted['job_key'],)).fetchone()[0])
        run_id = '00000000-0000-4000-8000-000000000085'
        evidence = dict(run_id=run_id, competitor_policy=POLICY)
        primary = read(self.transport.rows[site_id])
        before = read(self.transport.rows[all_id])
        after = runtime._curve_restore_target(before, old)
        self.assertEqual(after['unit_price_usd_per_k'], '0.1')
        inputs = dict(captured_at=now.isoformat(), valid_until=(now + timedelta(minutes=10)).isoformat(),
                      primary_curve=primary, all_before=before,
                      price_insurance=dict(market_per_100k=['10']),
                      all_inputs={curve_key(after): frozen(after, '120')})
        with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            proved = runtime._prove_curve_restore('PS', inputs, old, OPERATION, now)
            self.assertEqual(proved['status'], 'READY', proved)
        drifted = deepcopy(before['native_payload'])
        drifted['more']['give'][2] = '99'
        with self.assertRaisesRegex(ValueError, 'pricing_restore_quantity_or_offer_changed'):
            runtime._curve_restore_target(read(drifted), old)
        unsafe = dict(inputs, all_inputs={curve_key(after): frozen(after, '130')})
        self.assertEqual(runtime._prove_curve_restore('PS', unsafe, old, OPERATION, now)['status'],
                         'HARD_CONSTRAINT_FAILED')
        runtime.store_curve_proof_inputs(self.db, evidence, {'PS': inputs})
        (self.root/'config').mkdir()
        (self.root/'config/v3-control.json').write_text(json.dumps(dict(generation='generation', enabled=True)))
        policy = dict(revision=7, interval_minutes=60, system_enabled=True, mode='manual', platforms=['PS'])

        def collect(job):
            self.assertEqual(job['actor'], 'wulv')
            self.assertEqual(job['request']['v3_operation_id'], preview['operation_id'])
            (self.root/'jobs'/(run_id+'.json')).write_text(json.dumps(job))
            result = runtime.calculate(evidence)
            self.assertEqual(result['status'], 'READY', result)
            self.bundle = result['decision_receipt']
            curve_quote = dict(result=result, evidence=evidence, automation_policy_revision=7,
                               snapshot_sha256='restore-fixture-run', quote_engine_sha256='fixture-engine')
            (self.root/'quotes'/(run_id+'.json')).write_text(json.dumps(curve_quote))
            self.assertEqual(runtime.verify_quote(curve_quote, policy, ['PS'], for_execution=True), self.bundle)
            return dict(run_id=run_id)

        def send(operation):
            ident = operation['operation_id']
            item = writer.curve_catalog_plan(self.bundle, PLATFORM, self.capability)
            audit = dict(execution_id=ident, write_protocol=CURVE_WRITE_PROTOCOL,
                         pricing_decision_receipt=self.bundle, selected=['PS'],
                         curve_results={'PS': dict(item, operation_id=ident)}, status='RUNNING',
                         sync_confirmed=False, changed=[], business_dispatch_started=False)
            path = self.root/'executions'/(ident+'.json')
            return writer.drive_curve_catalog(self.transport, audit, lambda value: path.write_text(json.dumps(value)),
                                              lambda _: None, self.capabilities)

        self.worker.save_job = Mock()
        self.worker.collect_quote = Mock(side_effect=collect)
        self.dispatch.side_effect = send
        with patch.object(scheduler, 'ledger', return_value=self.db), patch.object(scheduler, 'ROOT', self.root), \
                patch('automation_policy.load_policy', return_value=policy), \
                patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            outcome = scheduler.cycle(queue)
            self.assertEqual(outcome['status'], 'confirmed')
            self.assertEqual(outcome['execution_id'], preview['operation_id'])
            self.assertEqual(scheduler.cycle(queue)['status'], 'COMPLETED')
        self.assertEqual(self.worker.collect_quote.call_count, 1)
        self.assertEqual(len(self.transport.posts), 2)
        self.assertEqual(self.transport.projection_writes, [])
        posted = self.transport.posts[-1][1]
        self.assertEqual(posted['more']['price'], ['10', '100', '149.95'])
        for key in ('gold', 'give', 'discount'):
            self.assertEqual(posted['more'][key], old['native_payload']['more'][key])
        operation = self.db.get('operations', preview['operation_id'])
        self.assertEqual(operation['bundle']['restore_source_execution_id'], OPERATION)
        self.assertEqual(operation['readback']['curve_results']['PS']['actual_site266_curve']['tiers'][-1]['native_price_usd'],
                         '149.95')
        self.assertIsNone(self.db.get('metadata', 'latest_snapshot:plan'))
        self.assertEqual(self.dispatch.call_count, 2)

    def test_original_admin_rejection_closes_only_after_exact_no_change_readback(self):
        self.prepare()
        self.transport.rejection_code = 0
        original_request = self.transport.request
        recipient_id = writer.PRODUCTS[PLATFORM][1]

        def drift_after_send(path, *, data, token):
            if data is None and self.transport.posts and path.endswith('=' + str(recipient_id)):
                raise TimeoutError
            return original_request(path, data=data, token=token)

        with patch.object(self.transport, 'request', side_effect=drift_after_send):
            self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertTrue(self.leased())
        original = json.loads(self.audit_path.read_text())['curve_results'][PLATFORM]['catalog']['post_response']
        closed = runtime.reconcile(OPERATION)
        self.assertEqual(closed['status'], CURVE_REJECTED)
        self.assertEqual(closed['readback']['curve_results'][PLATFORM]['catalog']['post_response'], original)
        self.assertEqual(closed['steps'][0]['receipt_history'][-1]['state'], 'UNKNOWN')
        self.assertFalse(self.leased())
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))
        self.assertEqual(runtime.reconcile(OPERATION), closed)
        self.assertEqual(len(self.transport.posts), 1)
        self.assertEqual(self.transport.projection_writes, [])
        self.reconcile.assert_called_once()

    def test_undocumented_reply_and_unchanged_prices_stay_unknown(self):
        self.prepare()
        self.transport.rejection_code = '0'
        self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.assertTrue(self.leased())
        self.assertEqual(len(self.transport.posts), 1)

    def test_unknown_with_matching_current_prices_is_only_read_on_original_id(self):
        self.prepare()
        self.transport.response_lost = True
        first = self.execute()
        self.assertEqual(first['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.assertEqual(len(self.transport.posts), 1)
        self.dispatch.assert_called_once()
        self.reconcile.assert_called_once()
        self.assertTrue(self.leased())
        self.assertIsNone(self.db.get('actual_price_windows', OPERATION))

    def test_mismatched_audit_cannot_close_or_trigger_readback(self):
        self.prepare()
        def mismatched(operation):
            result = self.send_original(operation)
            audit = json.loads(self.audit_path.read_text())
            audit.update(execution_id='different', sync_confirmed=True, sync_message='legacy success')
            self.save_audit(audit)
            return result
        self.dispatch.side_effect = mismatched
        self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.reconcile.assert_not_called()
        self.assertTrue(self.leased())

    def test_nochange_needs_complete_current_readback_and_does_not_write(self):
        self.prepare(large='100')
        first = self.execute()
        self.assertEqual(first['dispatch_context']['selected'], [])
        self.assertEqual(first['status'], 'PUBLIC_PENDING')
        self.assertEqual(first['readback']['reason'], 'pricing_curve_current_full_readback_unavailable')
        self.assertFalse(first['readback']['write_performed'])
        self.assertEqual(runtime.reconcile(OPERATION), first)
        self.dispatch.assert_not_called()
        self.reconcile.assert_not_called()
        self.assertTrue(self.leased())

    def test_proven_prewrite_refusal_cancels_original_without_retry(self):
        self.prepare()
        self.dispatch.side_effect = None
        self.dispatch.return_value = dict(prewrite_refusal('{}'), write_protocol=CURVE_WRITE_PROTOCOL)
        result = self.execute()
        self.assertEqual(result['status'], 'CANCELLED_NOT_SENT')
        self.assertFalse(self.leased())
        self.assertEqual(runtime.reconcile(OPERATION), result)
        self.dispatch.assert_called_once()

    def test_original_writer_lock_busy_is_proven_zero_dispatch(self):
        self.prepare()
        self.dispatch.side_effect = None
        self.dispatch.return_value = dict(status='NOT_SENT', write_protocol=CURVE_WRITE_PROTOCOL, exit_code=75)
        self.assertEqual(self.execute()['status'], 'CANCELLED_NOT_SENT')
        self.assertFalse(self.leased())
        self.dispatch.assert_called_once()

    def test_original_f4_audit_proves_send_intent_was_not_dispatched(self):
        self.prepare()
        def refuse(_):
            raise ValueError('pricing_curve_resource_fence_changed')
        self.dispatch.side_effect = lambda op: self.send_original(op, before_send=refuse)
        self.assertEqual(self.execute()['status'], 'CANCELLED_NOT_SENT')
        self.assertEqual(json.loads(self.audit_path.read_text())['status'], 'FAILED_BEFORE_WRITE')
        self.assertEqual(self.transport.posts, [])
        self.assertFalse(self.leased())

    def test_readback_failure_cannot_erase_confirmed_catalog_or_release_lease(self):
        self.prepare(propagate=False)
        self.assertEqual(self.execute()['status'], 'PARTIALLY_APPLIED')
        self.reconcile.side_effect = OSError('readback transport failed')
        recovered = runtime.reconcile(OPERATION)
        self.assertEqual(recovered['status'], 'PARTIALLY_APPLIED')
        receipt = recovered['steps'][0]['receipt']
        self.assertEqual(receipt['curve_results']['PS']['catalog']['status'], 'confirmed')
        self.assertEqual(receipt['recovery']['reason'], 'pricing_curve_original_audit_unavailable')
        self.assertTrue(self.leased())
        self.dispatch.assert_called_once()

    def test_bare_not_sent_without_original_transport_evidence_stays_unknown(self):
        self.prepare()
        self.dispatch.side_effect = None
        self.dispatch.return_value = dict(status='NOT_SENT', write_protocol=CURVE_WRITE_PROTOCOL)
        self.assertEqual(self.execute()['status'], 'UNKNOWN')
        self.assertEqual(runtime.reconcile(OPERATION)['status'], 'UNKNOWN')
        self.dispatch.assert_called_once()
        self.reconcile.assert_not_called()
        self.assertTrue(self.leased())

    def test_existing_legacy_financial_verifier_does_not_authorize_v6(self):
        self.prepare()
        quote = json.loads((self.root / 'quotes' / 'run.json').read_text())
        with self.assertRaisesRegex(ValueError, 'pricing_curve_quote_identity_invalid'):
            runtime.verify_quote(quote, {}, ['PS'], for_execution=True)

    def test_inconsistent_dirty_curve_cannot_use_empty_steps(self):
        self.prepare()
        self.bundle['steps'] = []
        with self.assertRaisesRegex(ValueError, 'pricing_curve_original_dispatch_scope_changed'):
            self.execute()
        self.dispatch.assert_not_called()
        self.worker.run.assert_not_called()

    def test_monitor_uses_curve_contract_and_keeps_optional_sources_optional(self):
        from fc_pricing_v3.monitoring import source_coverage

        now = datetime.now(timezone.utc)
        plan = dict(plan_id='curve-plan', revision=2, write_protocol=CURVE_WRITE_PROTOCOL)
        snapshot = dict(plan_id='curve-plan', plan_revision=2, write_protocol=CURVE_WRITE_PROTOCOL,
                        snapshot_id='fixture-run', created_at=now.isoformat(),
                        evidence=dict(checked_at=now.isoformat(),
                                      source_coverage=dict(optional_missing=['Lootbar','U7Buy','ArabUT'])),
                        result=dict(status='KEEP',
                                    rows=[dict(platform='PS', status='KEEP')]))
        coverage = source_coverage([snapshot], [plan], now)
        self.assertEqual(coverage['issues'], [])
        self.assertEqual(coverage['plans'][0]['curve_proof_status'], 'KEEP')
        snapshot['result']['rows'][0]['status'] = 'HARD_CONSTRAINT_FAILED'
        self.assertEqual(source_coverage([snapshot], [plan], now)['issues'],
                         [dict(level='critical', platform='PS', code='coin_v3_curve_hard_constraint_failed:PS')])

    def test_newer_diagnostic_collection_does_not_supersede_legacy_run(self):
        from fc_pricing_v3.competitor_offers import POLICY

        folder = self.root / 'runs'
        folder.mkdir()
        legacy = folder / 'legacy.json'
        candidate = folder / 'candidate.json'
        legacy.write_text('{}')
        candidate.write_text(json.dumps(dict(competitor_policy=POLICY)))
        self.assertEqual(runtime.latest_collection(self.root, curve=False), legacy)
        self.assertEqual(runtime.latest_collection(self.root, curve=True), candidate)

    def test_native_candidate_activation_and_execution_use_actual_verifier(self):
        self.run_verified_curve_cycle()

    def test_cost_repair_does_not_adopt_the_protected_price(self):
        self.run_verified_curve_cycle(cost_repair=True)

    def test_initial_activation_adopts_current_and_authorizes_verified_repair(self):
        self.run_verified_curve_cycle(cost_repair=True, initial_activation=True)

    def test_proven_keep_opens_and_extends_only_readback_window(self):
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
        from test_pricing_proof_v6 import fixture

        self.prepare(large='100')
        now = datetime.now(timezone.utc)
        plan = self.db.get('pricing_plans', 'plan')
        plan.update(mode='smart', write_protocol=CURVE_WRITE_PROTOCOL,
                    starts_at=(now - timedelta(hours=1)).isoformat(), resources=['base:PS'])
        self.db.put('pricing_plans', 'plan', plan)
        row = self.transport.rows[writer.PRODUCTS[PLATFORM][1]]
        curve = read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, EDITOR_CONTRACT)
        self.db.start_curve_episode(PLATFORM, 'fixture-rules', 'Adopted readback', initial_curve=curve,
                                    readback_ref='fixture-initial')
        now = datetime.now(timezone.utc)
        _, baskets, evidence, domain = fixture()
        key = curve_key(curve)
        domain['curve_key'] = evidence['curve_key'] = evidence['paths'][0]['curve_key'] = key
        proof = dict(baskets=baskets, evidence=evidence, domain=domain)
        first = '00000000-0000-4000-8000-000000000092'
        second = '00000000-0000-4000-8000-000000000093'
        for run, at in ((first, now), (second, now + timedelta(hours=1))):
            source = dict(run_id=run, competitor_policy=POLICY)
            observed = dict(captured_at=at.isoformat(), valid_until=(at + timedelta(minutes=10)).isoformat(),
                            primary_curve=curve, primary_inputs={key: proof},
                            anchor_shadow=dict(status='KEEP', would_write=False, execution_authorized=False,
                                               snapshot_id=run),
                            readbacks=[dict(path='/admin/goods.Goods/edit?id=' + curve['identity']['id'],
                                            http_status=200, response_code=1, response_sha256='fixture-site266')])
            runtime.store_curve_proof_inputs(self.db, source, {PLATFORM: observed})
            for _ in range(2):
                result = runtime.calculate_curve_cycle(self.db, source, plan, {'v3_operation_id': OPERATION}, at)
                self.assertEqual(result['status'], 'NO_PRICE_CHANGE')
                self.assertNotIn('decision_receipt', result)
                self.assertEqual(result['anchor_shadow'][PLATFORM], observed['anchor_shadow'])
                self.assertEqual(self.db.get('strategy_decisions', run)['anchor_shadow'][PLATFORM],
                                 observed['anchor_shadow'])
        windows = self.db.all('actual_price_windows')
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual(window['origin'], 'observed_native_curve_window')
        self.assertFalse(window['write_performed'])
        self.assertFalse(window['randomization_verified'])
        self.assertEqual(window['opened_at'], now.isoformat())
        self.assertEqual(curve_key(window['action']['curves'][PLATFORM]), key)
        self.assertEqual(len(window['continuations']), 1)
        self.assertFalse(window['continuations'][0]['write_performed'])
        self.assertIn('assignment', window['curve_selection'][PLATFORM])
        self.assertIn('assignment', window['continuations'][0]['curve_selection'][PLATFORM])
        self.assertNotIn('B', (window['curve_selection'][PLATFORM]['assignment']['actual_label'],
                              window['continuations'][0]['curve_selection'][PLATFORM]['assignment']['actual_label']))
        self.assertEqual(self.db.all('operations'), [])
        self.assertEqual(self.db.all('readback_receipts'), [])
        self.assertEqual(self.transport.posts, [])

    def run_verified_curve_cycle(self, *, cost_repair=False, initial_activation=False):
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import IDENTITY_FIELDS, curve_key, read_curve
        from fc_pricing_v3.pricing_proof_v6 import FAILED
        from test_pricing_proof_v6 import basket, quote

        self.prepare()
        now = datetime.now(timezone.utc)
        old = self.db.get('pricing_plans', 'plan')
        old.update(mode='daily', starts_at=(now - timedelta(minutes=30)).isoformat(), resources=['base:PS'],
                   parameters={'competitor_policy': 'lootbar_primary_arabut_secondary_v1'})
        self.db.put('pricing_plans', 'plan', old)
        next_slot = datetime.fromisoformat(old['starts_at']) + timedelta(hours=1)
        cycle_key = 'cycle:plan:' + str(int(next_slot.timestamp())) + ':r0'
        self.db.enqueue('cycle', cycle_key, next_slot, dict(plan_id='plan', revision=4,
                                                           scheduled_at=next_slot.isoformat()))
        current_row = self.transport.rows[writer.PRODUCTS[PLATFORM][1]]
        current = read_curve(current_row, {k: current_row[k] for k in IDENTITY_FIELDS}, EDITOR_CONTRACT)
        target_row = dict(current['native_payload'], more=dict(current['native_payload']['more'], price=['10', '103']))
        target = read_curve(target_row, current['identity'], EDITOR_CONTRACT)
        if not initial_activation:
            self.db.start_curve_episode(PLATFORM, 'fixture-current-rules', 'Previously adopted A',
                                        initial_curve=current if cost_repair else target,
                                        readback_ref='fixture-site266-readback')
        reference_before = self.db.curve_strategy_state(PLATFORM)
        all_before = self.bundle['before_action']['curves'][PLATFORM]
        all_target = self.bundle['action']['curves'][PLATFORM]
        def inputs(curve, *, total='103', safe_cost='76'):
            key = curve_key(curve)
            domain = dict(self.bundle['curve_proofs'][PLATFORM]['scope'], curve_key=key,
                          coverage_status='complete', coverage_gaps=[])
            path = quote('ordinary', key, regular_usd=total, net_receipt_usd=total, safe_cost_usd=safe_cost,
                         expected_cost_usd='75', stress_cost_usd='84')
            return dict(baskets=dict(main=basket('closed_bjt_7d', [('ordinary', '50')]),
                                     recent=basket('latest_24h', [('ordinary', '30')])),
                        evidence=dict(curve_key=key, paths=[path]), domain=domain)
        platform_inputs = dict(captured_at=now.isoformat(), valid_until=(now + timedelta(minutes=10)).isoformat(),
                               primary_curve=current, segment='large', preferred_label='A',
                               primary_inputs={curve_key(target): inputs(target),
                                               curve_key(current): inputs(current, total='100')},
                               all_before=all_before, all_targets={curve_key(target): all_target},
                               all_inputs={curve_key(all_target): inputs(all_target)})
        if initial_activation:
            self.assertIsNone(reference_before)
            platform_inputs.update(preferred_label='CURRENT',
                readbacks=[dict(path='/admin/goods.Goods/edit?id=' + current['identity']['id'],
                                http_status=200, response_code=1, response_sha256='fixture-site266-readback')])
        if cost_repair:
            failed_input = inputs(current, total='100', safe_cost='83')
            failed = runtime._validated_curve(current, failed_input)
            self.assertEqual(failed['status'], FAILED)
            repair = dict(current_proof_hash=failed['proof_hash'], domain_status='complete',
                          domain_ref='fixture-native-domain', affected_segments=['large'],
                          candidates=[dict(curve=target, inputs=inputs(target, safe_cost='83'),
                                           all_target=all_target, all_inputs=inputs(all_target, safe_cost='83'))])
            platform_inputs['primary_inputs'][curve_key(current)] = failed_input
            platform_inputs['repair'] = repair
        candidate_id = '00000000-0000-4000-8000-000000000090'
        run_id = '00000000-0000-4000-8000-000000000091'
        collection = dict(kind='collect', request=dict(write_protocol=CURVE_WRITE_PROTOCOL))
        (self.root/'jobs'/(candidate_id+'.json')).write_text(json.dumps(collection))
        evidence = dict(run_id=candidate_id, competitor_policy=POLICY)
        policy = dict(revision=7, interval_minutes=60, system_enabled=True, mode='auto', platforms=['PS'])
        with patch('automation_policy.load_policy', return_value=policy), \
                patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            self.assertEqual(runtime.collection_scope(self.db, candidate_id)['scope']['competitor_policy'], POLICY)
            self.assertEqual(runtime.calculate(evidence)['status'], 'PROOF_INCOMPLETE')
            with closing(self.db.connect()) as conn:
                from fc_pricing_v3.api import _latest_snapshot
                self.assertIsNone(_latest_snapshot(conn))
                self.assertEqual(_latest_snapshot(conn, curve=True)['snapshot_id'], candidate_id)
            with self.assertRaisesRegex(ValueError, 'pricing_curve_activation_proof_incomplete'):
                runtime.activate_curve_plan(self.db, 'plan', 4, 'wulv', candidate_id)
            self.assertEqual(self.db.get('pricing_plans', 'plan'), old)
            runtime.store_curve_proof_inputs(self.db, evidence, {'PS': platform_inputs})
            activated = runtime.activate_curve_plan(self.db, 'plan', 4, 'wulv', candidate_id)
            self.assertEqual(activated['revision'], 5)
            self.assertEqual(runtime.activate_curve_plan(self.db, 'plan', 4, 'wulv', candidate_id), activated)
            self.assertEqual(activated['parameters']['competitor_policy'], POLICY)
            if initial_activation:
                reference_before = self.db.curve_strategy_state(PLATFORM)
                self.assertEqual(curve_key(reference_before['reference']['reference_curve']),curve_key(current))
                self.assertEqual(self.transport.posts, [])
            with closing(self.db.connect()) as conn:
                cycle = conn.execute('SELECT body FROM durable_jobs WHERE id=?', (cycle_key,)).fetchone()
                self.assertEqual(json.loads(cycle[0]), dict(plan_id='plan', revision=5,
                                                          scheduled_at=next_slot.isoformat()))
            request = dict(v3_plan_id='plan', v3_operation_id=OPERATION)
            (self.root/'jobs'/(run_id+'.json')).write_text(json.dumps(dict(actor='system-automation', request=request)))
            self.assertEqual(runtime.collection_scope(self.db, run_id)['scope']['competitor_policy'], POLICY)
            evidence = dict(run_id=run_id, competitor_policy=POLICY)
            platform_inputs['plan_binding'] = runtime._curve_plan_binding(activated)
            runtime.store_curve_proof_inputs(self.db, evidence, {'PS': platform_inputs})
            result = runtime.calculate(evidence)
            self.assertEqual(result['status'], 'READY')
            self.bundle = result['decision_receipt']
            if not cost_repair:
                frozen = runtime._curve_proof_inputs(self.db, evidence)[PLATFORM]
                preview = runtime._preview_curve_candidates(
                    current, curve_key(current), PLATFORM, reference_before, 'large', None,
                    now.isoformat(), now.isoformat(), now, frozen['primary_inputs'], editor=EDITOR_CONTRACT)
                primary = next(row['financial_proof'] for row in preview['candidates'] if 'A' in row['labels'])
                all_proof = self.bundle['curve_proofs'][PLATFORM]
                self.assertEqual(primary, runtime._validated_curve(target, frozen['primary_inputs'][curve_key(target)]))
                self.assertEqual(primary['status'], 'PROVEN')
                self.assertEqual(all_proof, runtime._validated_curve(all_target, frozen['all_inputs'][curve_key(all_target)]))
                self.assertNotEqual(primary['curve_key'], all_proof['curve_key'])
                self.assertNotEqual(primary['proof_hash'], all_proof['proof_hash'])
                preview_current = next(row['financial_proof'] for row in preview['candidates'] if 'CURRENT' in row['labels'])
                keep = runtime._prove_curve_inputs(PLATFORM, dict(frozen, preferred_label='CURRENT'), self.db, now,
                                                   evidence=evidence, plan=activated)
                self.assertEqual(keep['status'], 'KEEP')
                self.assertEqual(keep['proof'], preview_current)

                for when, plan, gap in (
                    (datetime.fromisoformat(frozen['valid_until']), activated,
                     'curve_reference_or_fresh_execution_inputs_unavailable'),
                    (now, dict(activated, revision=activated['revision'] + 1),
                     'pricing_curve_strategy_revision_changed'),
                ):
                    with self.subTest(execution_gap=gap):
                        denied = runtime._prove_curve_inputs(PLATFORM, frozen, self.db, when, evidence=evidence, plan=plan)
                        self.assertEqual(denied, dict(status='PROOF_INCOMPLETE', gaps=[gap]))
                without_all = dict(frozen, all_inputs={})
                denied = runtime._prove_curve_inputs(PLATFORM, without_all, self.db, now, evidence=evidence, plan=activated)
                self.assertEqual(denied, dict(status='PROOF_INCOMPLETE', gaps=['curve_target_all_proof_unavailable']))
                malformed = dict(frozen, primary_inputs=dict(frozen['primary_inputs']))
                malformed['primary_inputs'][curve_key(current)] = {}
                denied = runtime._prove_curve_inputs(PLATFORM, malformed, self.db, now, evidence=evidence, plan=activated)
                self.assertEqual(denied['status'], 'PROOF_INCOMPLETE')
                self.assertEqual(denied['gaps'], ['curve_current_proof_unavailable'])
            self.assertEqual(self.db.curve_strategy_state(PLATFORM), reference_before)
            if cost_repair:
                self.assertEqual(self.bundle['curve_selection'][PLATFORM]['label'], 'COST_REPAIR')
            for folder in ('config',):
                (self.root/folder).mkdir()
            (self.root/'config/v3-control.json').write_text(json.dumps(dict(generation='generation', enabled=True)))
            quote = dict(result=result, evidence=evidence, automation_policy_revision=7,
                         snapshot_sha256='original-run-hash', quote_engine_sha256='original-engine-hash')
            (self.root/'quotes'/(run_id+'.json')).write_text(json.dumps(quote))
            self.assertEqual(runtime.verify_quote(quote, policy, ['PS'], for_execution=True), self.bundle)
            if not cost_repair:
                deadline = datetime.fromisoformat(platform_inputs['valid_until'])
                with self.assertRaisesRegex(ValueError, 'pricing_authorization_expired_or_unowned'):
                    runtime.verify_quote(quote, policy, ['PS'], now=deadline, for_execution=True)
                self.db.put('pricing_plans', 'plan', dict(activated, revision=activated['revision'] + 1))
                try:
                    with self.assertRaisesRegex(ValueError, 'pricing_curve_plan_revision_changed'):
                        runtime.verify_quote(quote, policy, ['PS'], for_execution=True)
                finally:
                    self.db.put('pricing_plans', 'plan', activated)
            self.assertEqual(self.transport.posts, [])
            tampered = dict(self.bundle, curve_proofs={'PS': dict(self.bundle['curve_proofs']['PS'], status='PROOF_INCOMPLETE')})
            tampered['sha256'] = fingerprint({k: v for k, v in tampered.items() if k != 'sha256'})
            with self.assertRaisesRegex(ValueError, 'pricing_curve_execution_proof_unverified'):
                runtime.verify_quote(dict(quote, result=dict(result, decision_receipt=tampered)),
                                     policy, ['PS'], for_execution=True)
            completed = runtime.execute_run(run_id)
            self.assertEqual(completed['status'], 'COMPLETED', completed['steps'])
            self.assertEqual(completed['readback']['execution_id'], OPERATION)
            self.assertEqual(len(self.transport.posts), 1)
            self.assertEqual(runtime.execute_run(run_id)['status'], 'COMPLETED')
            self.assertEqual(len(self.transport.posts), 1)
            after = self.db.curve_strategy_state(PLATFORM)
            if cost_repair:
                self.assertEqual(after, reference_before)
                self.assertEqual(completed['readback']['curve_results'][PLATFORM]['actual_site266_curve']['tiers'][1]['native_price_usd'], '103')
            else:
                self.assertEqual(after, reference_before)

    def test_closed_clock_hour_source_and_existing_three_hour_schedule_select_native_segment(self):
        from test_curve_strategy_v6 import fixture

        current, reference, episode = fixture()
        now = datetime(2026, 11, 13, 6, 7, tzinfo=timezone.utc)
        closed = now.replace(minute=0)
        available = dict(query_complete=True, observed_at=now.isoformat(), source_sha256='fixture-outcomes')

        def order(at, quantity, net):
            return dict(platform='PS', occurred_at=at.isoformat(), purchase_k=quantity, actual_net_usd=net,
                        actual_contribution_usd='8',
                        cost_basis='same_order_Order_shipping_CNY_margin_at_actual_USD_receipt')

        rows = [order(closed - timedelta(minutes=30), '1000', '91'),
                order(closed - timedelta(days=1, minutes=30), '1000', '95'),
                order(closed + timedelta(minutes=2), '100', '10')]
        performance = runtime._same_hour_curve_performance(
            'PS', dict(actual_outcomes=rows, learning_coverage=available), now)
        self.assertEqual(list(performance), ['large'])
        self.assertEqual(performance['large']['current']['net_paid_usd'], '91')
        self.assertEqual(performance['large']['previous']['net_paid_usd'], '95')
        self.assertEqual(runtime._same_hour_curve_performance(
            'PS', dict(actual_outcomes=rows, learning_coverage=dict(available, query_complete=False)), now), {})
        start = (closed - timedelta(hours=2)).isoformat()
        plan = dict(plan_id='plan', mode='smart', starts_at=start, revision=5)
        state = dict(reference=reference, episode=dict(episode, opened_at=start))
        inputs = dict(performance=performance)
        current_slot = runtime._curve_preference('PS', current, {}, inputs, now, plan=plan, state=state)
        same_slot = runtime._curve_preference(
            'PS', current, {}, inputs, now + timedelta(minutes=15), plan=plan, state=state)
        self.assertEqual((current_slot['label'], current_slot['segment'], current_slot['block']),
                         (same_slot['label'], same_slot['segment'], same_slot['block']))
        self.assertEqual(current_slot['source'], 'smart_three_hour_block')
        self.assertIn(current_slot['label'], 'ABC')
        slots = [runtime._curve_preference('PS', current, {}, {}, now + timedelta(hours=3 * block),
                                         plan=plan, state=state)['assignment'] for block in range(16)]
        self.assertEqual([slot['segment'] for slot in slots[:8]], [slot['segment'] for slot in slots[8:]])
        self.assertEqual([slot['pair_id'] for slot in slots[:8]], [slot['pair_id'] for slot in slots[8:]])
        self.assertTrue(all(a['segment'] != b['segment'] for a, b in zip(slots[:7], slots[1:8])))
        self.assertEqual(runtime._curve_preference('PS', current, {}, inputs, now,
                         plan=dict(plan, mode='revenue_sprint'), state=state)['label'], 'B')

    def test_bounded_trial_falls_back_to_independently_proven_intermediate_price(self):
        from fc_pricing_v3.curve_strategy_v6 import build_candidates, intermediate_candidates
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from test_curve_strategy_v6 import candidate, fixture
        from test_pricing_proof_v6 import fixture as proof_fixture

        self.prepare()
        now = datetime.now(timezone.utc)
        current, _, _ = fixture()
        all_id = writer.PRODUCTS[PLATFORM][0]
        before = read_curve(dict(current['native_payload'], id=all_id, site_id=0),
                            dict(current['identity'], id=all_id, site_id=0), EDITOR_CONTRACT)
        state = self.db.start_curve_episode(PLATFORM, 'test', 'A', initial_curve=current, readback_ref='fixture')
        comparison = build_candidates(current, state['reference'], state['episode'], 'large')
        outer = candidate(comparison, 'B')['curve']
        points = intermediate_candidates(comparison, 'B', EDITOR_CONTRACT)
        skipped, eligible = (next(points)['curve'] for _ in range(2))
        all_target = runtime._all_curve_target(before, eligible)
        refs = self.capability['source_revisions']
        self.capability['tier_price_factors'] = True

        def proof_input(curve, *, safe):
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            total = next(row['native_price_usd'] for row in curve['tiers'] if row['purchase_k'] == '1000')
            domain.update(curve_key=key, source_revisions=refs, version=self.capability['domain_version'])
            evidence['curve_key'] = key
            evidence['paths'][0].update(curve_key=key, regular_usd=total, net_receipt_usd=total,
                                         expected_cost_usd='74', safe_cost_usd=safe)
            return dict(baskets=baskets, evidence=evidence, domain=domain)

        data = dict(primary_curve=current, editor_contract=EDITOR_CONTRACT, preferred_label='B', segment='large',
                    captured_at=now.isoformat(), valid_until=(now + timedelta(minutes=10)).isoformat(),
                    all_before=before, all_targets={curve_key(eligible): all_target},
                    primary_inputs={curve_key(current): proof_input(current, safe='76'),
                                    curve_key(outer): proof_input(outer, safe='76'),
                                    curve_key(skipped): proof_input(skipped, safe='74'),
                                    curve_key(eligible): proof_input(eligible, safe='74')},
                    all_inputs={curve_key(all_target): proof_input(all_target, safe='74')})
        with patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities):
            result = runtime._prove_curve_inputs(PLATFORM, data, self.db, now)
        self.assertEqual(result['status'], 'READY', result)
        self.assertEqual(result['selection']['price_step'], 'bounded_intermediate')
        self.assertEqual(curve_key(result['target']), curve_key(all_target))
        self.assertEqual(self.transport.posts, [])

    def test_live_collection_freezes_viable_intermediate_for_automatic_selection(self):
        self.assert_live_collection_selects_intermediate(primary_safe_cost='81', proof_builds=12)

    def test_live_collection_checks_all_before_accepting_proven_primary_outer_trial(self):
        self.assert_live_collection_selects_intermediate(primary_safe_cost='79.5', proof_builds=13)

    def assert_live_collection_selects_intermediate(self, *, primary_safe_cost, proof_builds):
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import (EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, IDENTITY_FIELDS,
                                               TWO_BAND_PRICE_EDIT, curve_key, read_curve)
        from test_pricing_proof_v6 import fixture as proof_fixture
        from test_curve_writer_v6 import goods

        self.prepare()
        now = datetime.now(timezone.utc)
        all_id, primary_id, _ = writer.PRODUCTS[PLATFORM]
        rows = {0: goods(all_id, 0), 266: goods(primary_id, 266)}
        primary = rows[266]
        editor = dict(price_edit_policy=TWO_BAND_PRICE_EDIT, editor_asset_sha256=EDITOR_ASSET_SHA256,
                      editor_handler_sha256=EDITOR_HANDLER_SHA256, source='Admin Goods edit read only',
                      verified_domain='native stored tiers only')
        adopted = read_curve(primary, {key: primary[key] for key in IDENTITY_FIELDS}, editor)
        self.db.put('actual_price_windows', 'previous-day', dict(operation_id='previous-day',
            write_protocol=CURVE_WRITE_PROTOCOL, opened_at=(now-timedelta(hours=25)).isoformat(),
            action={'curves': {PLATFORM: adopted}}, resources=['base:PS']))
        self.db.start_curve_episode(PLATFORM, 'test', 'A', initial_curve=adopted, readback_ref='fixture')
        plan = dict(self.db.get('pricing_plans', 'plan'), mode='revenue_sprint')
        self.db.put('pricing_plans', 'plan', plan)
        run_id = '00000000-0000-4000-8000-000000000075'
        (runtime.ROOT / 'jobs' / (run_id + '.json')).write_text(json.dumps(
            {'request': {'v3_plan_id': 'plan', 'v3_operation_id': OPERATION}}))
        evidence = dict(run_id=run_id, checked_at=now.isoformat(), competitor_policy=POLICY)
        self.capability['tier_price_factors'] = True
        route = {'propagation_revision': self.capability['source_revisions']['propagation']}
        performance = {'large': {'current': {'paid_orders': 8}}}

        def freeze(curve, *args, **kwargs):
            _, baskets, evidence, domain = proof_fixture()
            key = curve_key(curve)
            total = next(tier['native_price_usd'] for tier in curve['tiers'] if tier['purchase_k'] == '1000')
            domain.update(curve_key=key, source_revisions=self.capability['source_revisions'],
                          version=self.capability['domain_version'])
            evidence['curve_key'] = key
            safe_cost = primary_safe_cost if curve['identity']['site_id'] == '266' else '81'
            evidence['paths'][0].update(curve_key=key, regular_usd=total, net_receipt_usd=total,
                                         expected_cost_usd='79', safe_cost_usd=safe_cost, stress_cost_usd='81')
            return dict(baskets=baskets, evidence=evidence, domain=domain)

        with patch.object(runtime, 'clock', return_value=now), \
                patch.object(writer, 'read_row', side_effect=lambda _, p, site, observer: rows[site]) as read, \
                patch.object(writer, 'read_curve_routes', return_value={PLATFORM: route}) as routes, \
                patch.object(writer, 'curve_writer_capabilities', return_value=self.capabilities), \
                patch.object(runtime, '_shared_curve_inputs', return_value=(None, None, None)) as shared, \
                patch('fc_pricing_v3.business_source.collect_recent_curve_population', return_value=None) as recent, \
                patch('fc_shared_admin.SessionManager'), \
                patch.object(runtime, '_same_hour_curve_performance', return_value=performance), \
                patch.object(runtime, '_average_discount_proof_input', side_effect=freeze) as inputs:
            collected = runtime.collect_curve_catalogues(evidence, [PLATFORM])
            runtime.store_curve_proof_inputs(self.db, evidence, collected)
            frozen = runtime._curve_proof_inputs(self.db, evidence)[PLATFORM]
            result = runtime._prove_curve_inputs(PLATFORM, frozen, self.db, now, evidence=evidence, plan=plan)
        self.assertEqual(result['status'], 'READY', result)
        self.assertEqual(result['selection']['price_step'], 'bounded_intermediate')
        self.assertEqual([tier['native_price_usd'] for tier in result['target']['tiers']], ['10', '99'])
        self.assertEqual(result['proof']['status'], 'PROVEN')
        self.assertEqual(read.call_count, 2)
        routes.assert_called_once()
        shared.assert_called_once()
        recent.assert_called_once()
        self.assertEqual(len(frozen['primary_inputs']), 6)
        self.assertEqual(inputs.call_count, proof_builds)
        self.assertEqual(self.transport.posts, [])

    def test_native_catalogue_retries_only_the_failed_get(self):
        from socket import timeout as SocketTimeout
        from urllib.error import URLError
        from fc_pricing_v3.competitor_offers import POLICY
        from test_curve_writer_v6 import goods

        self.prepare()
        now = datetime.now(timezone.utc)
        all_id, primary_id, _ = writer.PRODUCTS[PLATFORM]
        evidence = dict(run_id='00000000-0000-4000-8000-000000000080',
                        checked_at=now.isoformat(), competitor_policy=POLICY)
        calls = []

        def read(_, platform, site, observer):
            self.assertEqual(platform, PLATFORM)
            calls.append(site)
            if calls == [266, 0]:
                observer({'transport_error': 'URLError'})
                raise URLError(SocketTimeout('private connection data'))
            observer({'response_sha256': 'success-' + str(site)})
            return goods(primary_id if site == 266 else all_id, site)

        with patch.object(writer, 'read_row', side_effect=read), \
                patch.object(writer, 'read_curve_routes', return_value={}) as routes, \
                patch.object(runtime, '_shared_curve_inputs', return_value=(None, None, None)), \
                patch('fc_pricing_v3.business_source.collect_recent_curve_population', return_value=None), \
                patch('fc_shared_admin.SessionManager'):
            collected = runtime.collect_curve_catalogues(evidence, [PLATFORM])
        routes.assert_called_once()
        self.assertEqual(calls, [266, 0, 0])
        self.assertEqual(collected[PLATFORM]['readbacks'], [
            {'response_sha256': 'success-266'}, {'response_sha256': 'success-0'}])
        self.assertNotIn('curve_catalogue_gaps', evidence)
        self.assertEqual(self.transport.posts, [])

    def test_native_catalogue_timeout_retry_budget_is_shared_across_platforms(self):
        from urllib.error import HTTPError
        from fc_pricing_v3.competitor_offers import POLICY

        self.prepare()
        now = datetime.now(timezone.utc)
        evidence = dict(run_id='00000000-0000-4000-8000-000000000081',
                        checked_at=now.isoformat(), competitor_policy=POLICY)
        failures = [HTTPError('https://private.invalid', 503, 'private response', None, None),
                    TimeoutError('private response'), TimeoutError('private response'),
                    TimeoutError('private response')]
        with patch.object(writer, 'read_row', side_effect=failures) as get, \
                patch.object(writer, 'read_curve_routes', return_value={}) as routes, \
                patch('fc_shared_admin.SessionManager'):
            collected = runtime.collect_curve_catalogues(evidence, ['PS', 'XBOX', 'PC'])
        self.assertEqual(collected, {})
        routes.assert_called_once()
        self.assertEqual([call.args[1:] for call in get.call_args_list],
                         [('PS', 266), ('XBOX', 266), ('XBOX', 266), ('PC', 266)])
        cycle = runtime.calculate_curve_cycle(self.db, evidence, None, {}, now)
        self.assertFalse(cycle['execution_authorized'])
        record = self.db.get('strategy_decisions', evidence['run_id'])
        for row in record['curve']:
            with self.subTest(platform=row['platform']):
                self.assertEqual(row['status'], 'PROOF_INCOMPLETE')
                category = 'source_rejected' if row['platform'] == 'PS' else 'source_timeout'
                self.assertIn('native_catalogue:primary:' + category, row['gaps'])
                self.assertIn('curve_reference_or_fresh_execution_inputs_unavailable', row['gaps'])
        self.assertNotIn('private', json.dumps(record))
        self.assertEqual(self.transport.posts, [])

    def test_native_catalogue_does_not_retry_invalid_or_non_timeout_responses(self):
        from urllib.error import URLError
        from fc_pricing_v3.competitor_offers import POLICY
        from test_curve_writer_v6 import goods

        self.prepare()
        now = datetime.now(timezone.utc)
        evidence = dict(run_id='00000000-0000-4000-8000-000000000082',
                        checked_at=now.isoformat(), competitor_policy=POLICY)
        primary_id = writer.PRODUCTS['PC'][1]
        failures = [ValueError('coin_product_scope_changed'), ValueError('coin_backend_response_invalid'),
                    goods(primary_id, 266), URLError(OSError('private connection data'))]
        with patch.object(writer, 'read_row', side_effect=failures) as get, \
                patch.object(writer, 'read_curve_routes', return_value={}), \
                patch('fc_shared_admin.SessionManager'):
            self.assertEqual(runtime.collect_curve_catalogues(evidence, ['PS', 'XBOX', 'PC']), {})
        self.assertEqual([call.args[1:] for call in get.call_args_list],
                         [('PS', 266), ('XBOX', 266), ('PC', 266), ('PC', 0)])
        self.assertEqual(evidence['curve_catalogue_gaps'], {
            'PS': 'native_catalogue:primary:source_identity_invalid',
            'XBOX': 'native_catalogue:primary:source_evidence_invalid',
            'PC': 'native_catalogue:all:source_transport_failed',
        })
        self.assertEqual(self.transport.posts, [])

    def test_native_catalogue_collection_produces_real_tiers_without_fabricating_checkout(self):
        from fc_pricing_v3.business_source import RecentCurveReadFailure
        from fc_pricing_v3.competitor_offers import POLICY
        from fc_pricing_v3.price_curve import curve_key, read_curve
        from test_curve_strategy_v6 import fixture

        self.prepare()
        now = datetime.now(timezone.utc)
        all_id, primary_id, _ = writer.PRODUCTS[PLATFORM]
        catalogue, _, _ = fixture()
        primary_row = catalogue['native_payload']
        rows = {0: dict(primary_row, id=all_id, site_id=0),
                266: dict(primary_row, id=primary_id, site_id=266)}
        adopted = read_curve(primary_row, catalogue['identity'], dict(source='fixture saved readback'))
        self.db.start_curve_episode(PLATFORM, 'test-rules', 'Adopted readback', initial_curve=adopted,
                                    readback_ref='fixture-same-platform')
        run_id = '00000000-0000-4000-8000-000000000079'
        evidence = dict(run_id=run_id, checked_at=(now - timedelta(seconds=5)).isoformat(), competitor_policy=POLICY,
                        storefront={'rows': {PLATFORM: {'sku_id': primary_id}}})
        plan = dict(self.db.get('pricing_plans', 'plan'), mode='smart', starts_at=(now - timedelta(hours=3)).isoformat())
        self.db.put('pricing_plans', 'plan', plan)
        self.db.put('metadata', 'curve-online-context:plan', {'smart_plan_id': 'plan'})
        self.db.put('actual_price_windows', 'window', {'operation_id': 'window'})
        job = runtime.ROOT / 'jobs' / (run_id + '.json')
        job.parent.mkdir(parents=True, exist_ok=True)
        job.write_text(json.dumps({'request': {'v3_plan_id': 'plan', 'v3_operation_id': 'op'}}))
        def read(_, platform, site, observer):
            self.assertEqual(platform, PLATFORM)
            observer({'response_sha256': 'fixture-' + str(site)})
            return rows[site]

        with patch.object(writer, 'read_row', side_effect=read) as get, \
                patch.object(writer, 'read_curve_routes', return_value={}), \
                patch('fc_pricing_v3.business_source.collect_recent_curve_population',
                      side_effect=RecentCurveReadFailure('source_timeout')), \
                patch('fc_pricing_v3.smart.curve_learning', return_value={'large': {'blocks': []}}) as learning, \
                patch('fc_shared_admin.SessionManager'):
            found = runtime.collect_curve_catalogues(evidence, [PLATFORM])[PLATFORM]
        learning.assert_called_once()
        self.assertEqual(learning.call_args.args[0], plan)
        self.assertEqual(found['learning'], {'large': {'blocks': []}})
        self.assertEqual(get.call_count, 2)
        curve = found['primary_curve']
        proof_input = found['primary_inputs'][curve_key(curve)]
        self.assertEqual([p['regular_usd'] for p in proof_input['evidence']['paths']],
                         [tier['native_price_usd'] for tier in curve['tiers']])
        self.assertEqual(runtime._validated_curve(curve, proof_input)['status'], 'PROOF_INCOMPLETE')
        self.assertIn('average_discount_window_unavailable', proof_input['domain']['coverage_gaps'])
        self.assertIn('curve_native_route_unavailable', proof_input['domain']['coverage_gaps'])
        recent = proof_input['baskets']['recent']
        self.assertEqual(recent['population_status'], 'partial')
        self.assertEqual(recent['coverage_gaps'], ['source_timeout'])
        runtime.store_curve_proof_inputs(self.db, evidence, {PLATFORM: found})
        cycle = runtime.calculate_curve_cycle(self.db, evidence, plan, {'v3_operation_id': OPERATION}, runtime.clock())
        decision = self.db.get('strategy_decisions', run_id)
        self.assertFalse(cycle['execution_authorized'])
        self.assertEqual(decision['curve_round_id'], OPERATION)
        self.assertIn('recent:source_timeout', decision['curve'][0]['gaps'])
        self.assertTrue(found['all_targets'])
        for key, target in found['all_targets'].items():
            self.assertEqual(target['identity']['site_id'], '0')
            self.assertIn(key, found['primary_inputs'])
            self.assertEqual(runtime._validated_curve(target, found['all_inputs'][curve_key(target)])['status'],
                             'PROOF_INCOMPLETE')

    def test_d3_d1_weighted_amount_and_custom_quantity_drive_current_proof(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import MODEL, average_discount
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        small = list(rows_for([48] * 10, quantity='123K Coins + 0K Free x1 = $100'))
        large = [(key + '-large', paid, quantity) for key, paid, quantity in
                 rows_for([72] * 10, quantity='1500K Coins + 30K Free x1 = $100')]
        included = small + large
        source = attachment(included)
        coverage = source['historical_orders_coverage']
        coverage.update(shared_publication_id='fixed-pin',shared_source_revision='fixed-source',
                        paid_window_start=(CUT - timedelta(days=8)).isoformat())
        for row in source['historical_orders']:
            gross, off = ('20','4') if row['base_k']=='123' else ('100','4')
            row.update(merchandise_before_discount_usd=gross, actual_es_discount_usd=off,
                       single_line_unit_purchase=True, promotion_path=None)
        source['historical_orders'].append(dict(source['historical_orders'][0], order_key='d4-excluded',
            paid_at=(CUT - timedelta(days=4)).isoformat(), merchandise_before_discount_usd='999',
            actual_es_discount_usd='999'))
        average = average_discount(source,'PS',CUT)
        self.assertEqual((average['matched_orders'],average['actual_discount_usd'],
                          average['merchandise_before_discount_usd']), (20,'80','1200'))
        self.assertEqual(average['retained_ratio'], str(Decimal(1120) / Decimal(1200)))
        self.assertEqual(average['start'], (CUT - timedelta(days=3)).isoformat())
        self.assertEqual(average['end_exclusive'], CUT.isoformat())

        small_facts = facts(small, cost='6.15', delivery_fields={'qty':'123','gift':'0','cost_unit':'.05'})
        large_facts = facts(large, cost='76.50', delivery_fields={'qty':'1530','gift':'0','cost_unit':'.05'})
        combined = dict(small_facts, orders=small_facts['orders'] + large_facts['orders'])
        # The paid population excludes unresolved quantity only from modelling.
        source['historical_orders'].pop()
        quote = runtime._average_discount_proof_input(current,'PS',source,source,CUT.isoformat(),AS_OF,
            average=average,route={'propagation_revision':'native-directory'},facts=combined,fx=fx(),current_cost=None)
        path = next(row for row in quote['evidence']['paths'] if row['purchase_k']=='123')
        self.assertEqual((path['regular_usd'],path['net_receipt_usd'],path['quote_basis']),('12.30','11.47',MODEL))
        self.assertEqual(path['receipt_status'],'forecast_under_average_discount')
        proof = runtime._validated_curve(current,quote)
        self.assertEqual(proof['status'],'PROVEN',proof['gaps'])
        self.assertEqual(proof['average_discount']['revision'],average['revision'])
        self.assertEqual(proof['baskets']['main']['selection'],'closed_bjt_7d')

        # Reuse actual verifier and old writer-compatible native factor, even
        # when an unchanged small catalogue needs a higher global unit.
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT, curve_key, read_curve
        from test_price_curve_v6 import EDITOR_CONTRACT
        editor = dict(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT)
        all_row = dict(current['native_payload'],id=writer.PRODUCTS['PS'][0],site_id=0)
        all_before = read_curve(all_row,dict(current['identity'],id=all_row['id'],site_id=0),editor)
        higher = facts(large, cost='1025.10', delivery_fields={'qty':'1530','gift':'0','cost_unit':'.67'})
        combined = dict(small_facts,orders=small_facts['orders'] + higher['orders'])
        def proof_for(curve):
            return runtime._average_discount_proof_input(curve,'PS',source,source,CUT.isoformat(),AS_OF,
                average=average,route={'propagation_revision':'native-directory'},facts=combined,fx=fx(),current_cost=None)
        current_proof = runtime._validated_curve(current,proof_for(current))
        self.assertEqual(current_proof['status'],'HARD_CONSTRAINT_FAILED')
        repair = runtime._average_discount_repair(current,all_before,editor,current_proof,proof_for)
        self.assertIsNotNone(repair)
        answer = runtime._curve_repair(current,current_proof,repair)
        self.assertEqual(answer['status'],'COST_REPAIR',answer)
        candidate = answer['candidate']['curve']
        self.assertEqual([p['native_price_usd'] for p in candidate['tiers'] if int(p['purchase_k'])<1000],
                         [p['native_price_usd'] for p in current['tiers'] if int(p['purchase_k'])<1000])
        preview = runtime._preview_curve_candidates(current, curve_key(current), 'PS', None, 'large', source,
            CUT.isoformat(), AS_OF.isoformat(), AS_OF, {curve_key(current):proof_for(current)},
            editor=editor, repair=repair)
        self.assertEqual([(item['labels'], item['financial_proof']['status']) for item in preview['candidates']],
                         [(['CURRENT'], 'HARD_CONSTRAINT_FAILED'), (['COST_REPAIR'], 'PROVEN')])
        self.assertEqual(preview['candidates'][1]['curve_key'], curve_key(candidate))

        source['historical_orders'][0]['actual_es_discount_usd'] = None
        incomplete = average_discount(source,'PS',CUT)
        self.assertIsNone(incomplete['retained_ratio'])
        self.assertEqual(incomplete['gap_counts'],{'average_discount_amount_unknown':1})

    def test_combined_basket_margin_repair_when_every_quantity_breaks_even(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import average_discount
        from fc_pricing_v3.price_curve import FORWARD_TIER_EDIT, read_curve
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture
        from test_price_curve_v6 import EDITOR_CONTRACT

        original, _, _ = fixture()
        editor = dict(EDITOR_CONTRACT, price_edit_policy=FORWARD_TIER_EDIT)
        native = original['native_payload']
        quantities = native['more']['gold']
        rates = dict(native['more'], discount=[100] * len(quantities),
                     price=[str((Decimal(q)*Decimal('.0816')).quantize(Decimal('.01'))) for q in quantities])
        current = read_curve(dict(native,unit_price='.0816',more=rates),original['identity'],editor)
        all_id = writer.PRODUCTS['PS'][0]
        all_before = read_curve(dict(current['native_payload'],id=all_id,site_id=0),
                                dict(current['identity'],id=all_id,site_id=0),editor)
        large = list(rows_for([48] * 20, quantity='1000K Coins + 30K Free x1 = $81.60'))
        small = [(key+'-small', paid, quantity) for key, paid, quantity in
                 rows_for([48] * 10, quantity='100K Coins + 0K Free x1 = $8.16')]
        source = attachment(large + small)
        source['historical_orders_coverage'].update(shared_publication_id='fixed-pin',
            shared_source_revision='fixed-source', paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for row in source['historical_orders']:
            row.update(single_line_unit_purchase=True, merchandise_before_discount_usd='100', actual_es_discount_usd='9')
        large_facts = facts(large, cost='427.45', delivery_fields=dict(qty='1030', gift='0', cost_unit='.415'))
        small_facts = facts(small, cost='41.50', delivery_fields=dict(qty='100', gift='0', cost_unit='.415'))
        combined = dict(large_facts, orders=large_facts['orders'] + small_facts['orders'])
        average = average_discount(source,'PS',CUT)

        def inputs_for(curve):
            return runtime._average_discount_proof_input(curve,'PS',source,source,CUT.isoformat(),AS_OF,
                average=average,route={'propagation_revision':'native-directory'},facts=combined,fx=fx(),current_cost=None)

        before = runtime._validated_curve(current,inputs_for(current))
        self.assertEqual(before['status'], 'HARD_CONSTRAINT_FAILED')
        self.assertTrue(all(path['zero_line_status']=='PROVEN' for path in before['paths']))
        self.assertEqual(before['hard_failures'], ['platform_margin:main', 'platform_margin:recent'])
        repair = runtime._average_discount_repair(current,all_before,editor,before,inputs_for)
        selected = runtime._curve_repair(current,before,repair)
        self.assertEqual(selected['status'], 'COST_REPAIR')
        candidate = selected['candidate']
        self.assertEqual(runtime._validated_curve(candidate['curve'],candidate['inputs'])['status'],'PROVEN')
        self.assertEqual(runtime._validated_curve(candidate['all_target'],candidate['all_inputs'])['status'],'PROVEN')
        self.assertTrue(all(Decimal(old['native_price_usd'])<=Decimal(new['native_price_usd'])
                            for old,new in zip(current['tiers'],candidate['curve']['tiers'])))

    def test_unallocated_multi_unit_cost_increases_missing_quantity_share(self):
        from decimal import Decimal
        from fc_pricing_v3.average_discount_v6 import average_discount
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        current, _, _ = fixture()
        large = list(rows_for([48] * 11, quantity='1000K Coins + 30K Free x1 = $100'))
        small = [(key+'-small', paid, quantity) for key, paid, quantity in
                 rows_for([48] * 10, quantity='100K Coins + 0K Free x1 = $10')]
        source = attachment(large + small)
        source['historical_orders_coverage'].update(shared_publication_id='fixed-pin',
            shared_source_revision='fixed-source', paid_window_start=(CUT-timedelta(days=8)).isoformat())
        for index, row in enumerate(source['historical_orders']):
            allocated = index < 2 or index >= len(large)
            row.update(single_line_unit_purchase=allocated, merchandise_before_discount_usd='100',
                       actual_es_discount_usd='0', cost_cny=None if allocated else '100000')
        lower = facts(large[:1], cost='350', delivery_fields=dict(qty='1030', gift='0', cost_unit=str(Decimal(350)/1030)))
        higher = facts(large[1:2], cost='630', delivery_fields=dict(qty='1030', gift='0', cost_unit=str(Decimal(630)/1030)))
        small_facts = facts(small, cost='5', delivery_fields=dict(qty='100', gift='0', cost_unit='.05'))
        facts_value = dict(lower, orders=lower['orders'] + higher['orders'] + small_facts['orders'])
        result = runtime._average_discount_proof_input(current,'PS',source,source,CUT.isoformat(),AS_OF,
            average=average_discount(source,'PS',CUT),route={'propagation_revision':'native-directory'},
            facts=facts_value,fx=fx(),current_cost=None)
        path = next(row for row in result['evidence']['paths'] if row['purchase_k']=='1000')
        self.assertEqual(path['cost_status'], 'verified')
        self.assertAlmostEqual(Decimal(path['expected_cost_usd']), Decimal(70))
        self.assertAlmostEqual(Decimal(path['safe_cost_usd']), Decimal(950)/11)
        self.assertAlmostEqual(Decimal(path['stress_cost_usd']), Decimal(90))
        self.assertEqual(next(row['weight'] for row in result['baskets']['main']['members'] if row['path_id']=='average:1000'),'11')
        self.assertEqual(runtime._validated_curve(current,result)['baskets']['main']['status'],'HARD_CONSTRAINT_FAILED')

    def test_same_round_native_path_preserves_checkout_scope_and_ordinary_cost(self):
        from decimal import Decimal
        from fc_pricing_v3.price_curve import curve_key
        from test_cost_inputs_v6 import AS_OF, CUT, attachment, facts, fx, rows_for
        from test_curve_strategy_v6 import fixture

        curve, _, _ = fixture()
        self.assertEqual(curve['identity']['aid'], '21587')
        tier = next(row for row in curve['tiers'] if row['purchase_k'] == '1000')
        purchase = tier['purchase_k']
        bonus = tier['promised_bonus_k']
        total = str(Decimal(purchase) + Decimal(bonus))
        ordinary_orders = list(rows_for([48] * 10, quantity=f'{purchase}K Coins + {bonus}K Free x1 = $100'))
        source = attachment(ordinary_orders)
        for row in source['historical_orders']:
            row['region_id'] = 0
        source['historical_orders'][0]['promotion_path'] = dict(kind='coupon', template_id='1327',
            evidence_ref='same-order-redemption', historical_regular_usd='10.22', historical_discount_usd='5.00')
        source['historical_orders'][1]['promotion_path'] = dict(kind='code', code_ref='code-one-ref')
        source['historical_orders'][2]['promotion_path'] = dict(kind='code', code_ref='code-two-ref')
        recent = dict(source, historical_orders_coverage=dict(source['historical_orders_coverage'],
                                                              paid_window_end_exclusive=CUT.isoformat()))
        cost_facts = facts(ordinary_orders, cost=str(Decimal(total) * Decimal('.39')),
                           delivery_fields={'qty':total, 'gift':'0', 'cost_unit':'.39'})
        checkout = dict(curve_key=curve_key(curve), platform='PS', site_id='266',
                        coverage_gaps=['member_and_discount_allocation_unverified'], lines=[
            dict(purchase_k=purchase, gift_k=bonus, promised_delivered_k=total, regular_usd=tier['native_price_usd'],
                 proof_status='verified', offer_path='anonymous_no_coupon', quote_basis='observed_native_cart',
                 net_goods_usd=tier['native_price_usd'], quote_ref='checkout-ref', eligibility_ref='eligibility-ref',
                 offer_version='current-guest-offer', fulfilment_contract='native-guest-cart',
                 native_tier_or_rule='native-1000', rounding_contract='native-cent', path_id='catalogue:1000')])
        def terms(identity, rule):
            return dict(path=rule, eligibility='eligible-member', source_revision='template-' + identity)

        coupons = dict(terms={
            '1327': terms('1327', dict(kind='fixed', threshold_usd='10', discount_usd='5', cap_usd=None)),
            '1323': terms('1323', dict(kind='ratio', threshold_usd='0', retained_ratio='.8', cap_usd='50')),
            '1331': terms('1331', dict(kind='fixed', threshold_usd='999', discount_usd='20', cap_usd=None)),
        })
        code_rule = dict(kind='ratio', threshold_usd='0', retained_ratio='.92', cap_usd=None)
        codes = {ref: dict(terms(ref, code_rule), aid='0') for ref in ('code-one-ref', 'code-two-ref')}
        proof_input = runtime._catalogue_proof_input(curve, 'PS', source, CUT.isoformat(), AS_OF,
            recent=recent, checkout=checkout, facts=cost_facts, fx=fx(), coupons=coupons, codes=codes)
        path = next(row for row in proof_input['evidence']['paths'] if row['purchase_k'] == purchase)
        self.assertEqual(path.get('cost_status'), 'verified', path)
        self.assertEqual(path['quote_basis'], 'observed_native_cart')
        self.assertAlmostEqual(Decimal(path['stress_cost_usd']), Decimal(total) * Decimal('.39') / 7)
        self.assertEqual(proof_input['baskets']['main']['matched_orders'], 10, proof_input['baskets']['main'])
        self.assertEqual(proof_input['baskets']['recent']['selection'], 'main_fallback')
        result = runtime._validated_curve(curve, proof_input)
        receipt_paths = {row.get('coupon_template_id'): row for row in result['paths'] if row.get('coupon_template_id')}
        self.assertEqual(set(receipt_paths), {'1327', '1323', '1331'})
        fixed = receipt_paths['1327']
        self.assertEqual(Decimal(fixed['net_receipt_usd']), Decimal(path['regular_usd']) - 5)
        self.assertEqual(fixed['cost_ref'], path['cost_ref'])
        self.assertEqual(fixed['quote_basis'], 'derived_eligible_single_line_coupon_net_lower_bound')
        self.assertEqual(receipt_paths['1331']['net_receipt_usd'], str(Decimal(path['regular_usd']).normalize()))
        self.assertFalse(receipt_paths['1331']['coupon_subtotal_eligible'])
        code_paths = [row for row in result['paths'] if row.get('discount_code_terms_revision')]
        self.assertEqual(len(code_paths), 1)
        self.assertEqual(code_paths[0]['discount_code_rule'], code_rule)
        weights = {row['path_id']: row['weight'] for row in proof_input['baskets']['main']['members']}
        self.assertEqual(weights, {'catalogue:1000': '7', 'catalogue:1000:coupon:1327': '1', code_paths[0]['path_id']: '2'})
        self.assertEqual(result['status'], 'PROOF_INCOMPLETE')
        self.assertIn('member_and_discount_allocation_unverified', result['scope']['coverage_gaps'])
        self.assertNotIn('procurement_time_unverified', result['gaps'])

    def test_candidate_coupon_money_bounds_use_each_rule_and_candidate_subtotal(self):
        path = dict(path_id='catalogue:100', curve_key='candidate', regular_usd='9.99')
        native = dict(quote_ref='guest-quote', offer_version='guest-version')
        terms = dict(source_revision='current-template', eligibility='eligible-voucher',
                     path=dict(kind='fixed', threshold_usd='10', discount_usd='5', cap_usd=None))
        below = runtime._coupon_quote_path(path, native, '1327', terms)
        reached = runtime._coupon_quote_path(dict(path, regular_usd='10.00'), native, '1327', terms)
        self.assertEqual((below['net_receipt_usd'], below['coupon_subtotal_eligible']), ('9.99', False))
        self.assertEqual((reached['net_receipt_usd'], reached['coupon_subtotal_eligible']), ('5.00', True))
        self.assertNotEqual(below['quote_ref'], reached['quote_ref'])
        share = dict(terms, path=dict(kind='ratio', threshold_usd='0', retained_ratio='.8', cap_usd='50'))
        cap = runtime._coupon_quote_path(dict(path, regular_usd='300.01'), native, '1323', share)
        rounded = runtime._coupon_quote_path(dict(path, regular_usd='10.01'), native, '1323', share)
        self.assertEqual((cap['net_receipt_usd'], rounded['net_receipt_usd']), ('250.01', '8.00'))


if __name__ == '__main__':
    unittest.main()

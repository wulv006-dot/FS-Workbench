import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3 import simulation
from fc_pricing_v3 import legacy_simulation


def actual_financial_fixture():
    return json.loads(Path(__file__).with_name('legacy-replay-fixture.json').read_text(encoding='utf-8')), None, None


START = datetime(2026, 10, 26, tzinfo=timezone.utc)


def evidence(at, mtd='100'):
    return dict(checked_at=at.isoformat(), storefront=dict(rows={p: dict(package_usd='10') for p in ('PS', 'XBOX', 'PC')}),
                historical_discount_mix=dict(retained_ratio='.9', net_order_usd='630', undiscounted_order_usd='700'),
                promotion_envelope=dict(packages={p: dict(tiers=[dict(base_k=100, bonus_k=0, retained_ratio='1')]) for p in ('PS', 'XBOX', 'PC')}),
                region_rules=[], monthly_target=dict(amount='1000', mtd=mtd),
                demand_model=dict(groups={g: dict(orders_per_block='1', reference_regular_usd='10',
                                                  new_customer_ratio='.2', delivered_k_per_order='100') for g in ('console', 'pc')}),
                daily_net_revenue_7d=dict(console='100', pc='100'), backlog_k='0', capacity_k_per_block='200')


def fake_evaluate(own, mode, **kwargs):
    action = dict(base_prices=dict(console='10', pc='10'), region_coefficients={})
    groups = {g: dict(orders='1', revenue='10', contribution='5', concession='0',
                      negative_contribution='0', new_customers='.2') for g in ('console', 'pc')}
    candidate = dict(action=action, score=dict(groups=groups, regional_predictions=[], absolute_forecast_available=True))
    return dict(status='READY', candidates=[candidate], selected=candidate, failures=[])


class ShadowBehavior(unittest.TestCase):
    def test_prune_pages_large_history_without_skipping_retained_rows(self):
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            with shadow.connect() as db:
                for index in range(250):
                    stamp = '2026-01-01T00:00:00+00:00' if index % 2 else now.isoformat()
                    db.execute('INSERT INTO runs (id,body) VALUES (?,?)',
                               (f'{index:04}', json.dumps(dict(as_of=stamp, payload='x' * 1000))))
            self.assertEqual(shadow.prune(now)['removed'], 125)
            with shadow.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 125)
                self.assertEqual(db.execute("SELECT count(*) FROM runs WHERE id LIKE '%1'").fetchone()[0], 0)

    def test_shadow_anchor_rebases_real_orders_and_aov_once(self):
        source = evidence(START)
        source['demand_model']['groups']['console'].update(orders_per_block='10',reference_regular_usd='10',
                                                         target_revenue_per_order_usd='5',elasticity='2')
        path = simulation.initial_path('daily',source,START)
        path['price_anchor']['base_prices']['console'] = '8'
        path['action'] = json.loads(json.dumps(path['price_anchor']))
        own = simulation.own_evidence(path,source,START)
        model = own['demand_model']['groups']['console']
        self.assertEqual(Decimal(model['orders_per_block']),Decimal('15.625'))
        self.assertEqual(model['reference_regular_usd'],'8')
        self.assertEqual(Decimal(model['target_revenue_per_order_usd']),Decimal('4'))
        self.assertEqual(simulation.demand('8',model['reference_regular_usd'],model['orders_per_block'],'2'),Decimal('15.625'))

    def test_real_order_basket_uses_score_usd_and_region_concession_once(self):
        source = evidence(START)
        source['demand_model']['groups']['console'].update(delivered_k_per_order='40',target_revenue_per_order_usd='4')
        source['demand_model']['segments'] = [dict(region_id=21,platform='PS',delivered_k_per_order='20',new_customer_ratio='.1')]
        candidate = dict(action=dict(base_prices=dict(console='10',pc='10'),region_coefficients={'21:PS':'.8'}),
                         financial_proof=dict(prices={'21:PS':dict(price=dict(regular_usd='8'))}),
                         score=dict(groups={'console':dict(orders='2',revenue='8',contribution='5',concession='2',new_customers='.4'),
                                            'pc':dict(orders='0',revenue='0',contribution='0',concession='0',new_customers='0')},
                                    regional_predictions=[dict(key='21:PS',orders='1',revenue='3',contribution='2',concession='.4')],
                                    absolute_forecast_available=True))
        rows = simulation.components(candidate,source,{'console':'12','pc':'10','21:PS':'9'})
        self.assertEqual(sum(Decimal(r['revenue']) for r in rows),Decimal('11'))
        self.assertEqual(sum(Decimal(r['contribution']) for r in rows),Decimal('7'))
        self.assertEqual(sum(Decimal(r['concession']) for r in rows),Decimal('2'))
        self.assertEqual(Decimal(rows[0]['concession']),Decimal('1.6'))
        self.assertEqual(Decimal(rows[0]['list_usd']),Decimal('8')/Decimal('.9'))
        lower_discount_ratio = json.loads(json.dumps(candidate))
        lower_discount_ratio['score']['groups']['console']['revenue'] = str(Decimal('8')*Decimal('.8')/Decimal('.9'))
        lower_discount_ratio['score']['regional_predictions'][0]['revenue'] = str(Decimal('3')*Decimal('.8')/Decimal('.9'))
        shifted = simulation.components(lower_discount_ratio,dict(source,shadow_retained_ratio='.8'),{'console':'12','pc':'10','21:PS':'9'})
        self.assertEqual(Decimal(shifted[0]['list_usd']),Decimal(rows[0]['list_usd']))
        self.assertEqual(shifted[0]['list_usd_basis'],'projected_score_net_divided_by_shadow_path_retained_ratio_frozen_basket')
        self.assertEqual(Decimal(rows[0]['delivered_k_per_order']),Decimal('40'))
        path = simulation.initial_path('daily',source,START)
        path.update(action=candidate['action'],last_as_of=START.isoformat(),last_components=rows,
                    last_forecast_absolute=True,last_capacity_k_per_block='200',effective_mode='daily')
        simulation.advance(path,START+timedelta(hours=6))
        self.assertEqual(Decimal(path['revenue']),Decimal('11'))
        self.assertEqual(Decimal(path['contribution']),Decimal('7'))
        self.assertEqual(Decimal(path['paid_orders']),Decimal('3'))
        self.assertEqual(Decimal(path['delivered_k']),Decimal('100'))
        self.assertEqual(Decimal(path['budget_used']),Decimal('2'))

    def test_frozen_legacy_replay_uses_real_asof_evidence_and_distinct_sources(self):
        actual, _, _ = actual_financial_fixture()
        with tempfile.TemporaryDirectory() as folder:
            outcomes = simulation.Shadow(Path(folder) / 'shadow.db').legacy_actions(dict(evidence=actual))
        weighted = outcomes['legacy_80_15_5']
        parity = outcomes['legacy_itemd2r_parity']
        self.assertEqual(weighted['status'], 'available')
        self.assertEqual(parity['status'], 'available')
        self.assertEqual(weighted['action']['base_prices']['console'], '19.99')
        self.assertEqual(parity['action']['base_prices']['console'], '20.00')
        self.assertNotEqual(weighted['source_sha256'], parity['source_sha256'])
        self.assertFalse(weighted['execution_authorized'])
        with patch.dict(legacy_simulation.SOURCES,{'legacy_80_15_5':('weighted_80_15_5.py','0'*64)}):
            self.assertEqual(legacy_simulation.replay(dict(evidence=actual),'legacy_80_15_5')['status'],'legacy_source_version_mismatch')

    def test_legacy_replay_uses_saved_decision_time_after_sources_finish(self):
        actual, _, _ = actual_financial_fixture()
        started = datetime.fromisoformat(actual['checked_at'].replace('Z', '+00:00'))
        actual['fx']['checked_at'] = (started + timedelta(seconds=30)).isoformat()
        captured = (started + timedelta(seconds=60)).isoformat()
        for name in legacy_simulation.SOURCES:
            result = legacy_simulation.replay(dict(evidence=actual, created_at=captured), name)
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['as_of'], captured)
            self.assertFalse(result['execution_authorized'])

    def test_legacy_replay_cannot_move_asof_forward_to_include_future_sources(self):
        actual, _, _ = actual_financial_fixture()
        started = datetime.fromisoformat(actual['checked_at'].replace('Z', '+00:00'))
        actual['fx']['checked_at'] = (started + timedelta(seconds=90)).isoformat()
        for name in legacy_simulation.SOURCES:
            result = legacy_simulation.replay(dict(evidence=actual, created_at=(started + timedelta(seconds=60)).isoformat()), name)
            self.assertEqual(result['status'], 'legacy_replay_gap')
            self.assertEqual(result['reason'], 'pricing_source_stale')

    def test_real_engine_missing_baseline_does_not_crash_shadow(self):
        actual, _, _ = actual_financial_fixture()
        from fixtures import set_console_cost
        set_console_cost(actual)
        actual.pop('demand_model', None)
        with tempfile.TemporaryDirectory() as folder:
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            shadow.snapshot(dict(snapshot_id='no-baseline', evidence=actual))
            with shadow.connect() as db:
                paths = [json.loads(raw) for raw, in db.execute('SELECT body FROM paths')]
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(not p.get('last_components') for p in paths))
            self.assertTrue(all(Decimal(p['revenue']) == 0 for p in paths))

    def test_previous_action_advances_own_state_before_next_decision(self):
        seen = []

        def capture(own, mode, **kwargs):
            if own.get('mode') == 'shadow' and mode == 'daily':
                seen.append((own['monthly_target']['mtd'], own['backlog_k'], kwargs['evaluation_context']['origin']))
            return fake_evaluate(own, mode, **kwargs)

        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=capture):
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            shadow.snapshot(dict(snapshot_id='first', evidence=evidence(START)))
            shadow.snapshot(dict(snapshot_id='second', evidence=evidence(START + timedelta(hours=6), '999')))
            with shadow.connect() as db:
                path = json.loads(db.execute("SELECT body FROM paths WHERE id='daily'").fetchone()[0])
            self.assertEqual([Decimal(r[0]) for r in seen], [Decimal(100), Decimal(120)])
            self.assertEqual([Decimal(r[1]) for r in seen], [Decimal(0), Decimal(0)])
            self.assertTrue(all(r[2] == 'simulated_path' for r in seen))
            self.assertEqual(Decimal(path['monthly_revenue']['2026-10']), Decimal(120))
            self.assertEqual(Decimal(path['paid_orders']), Decimal(2))
            self.assertEqual(Decimal(path['new_customers']), Decimal('.4'))
            self.assertEqual(len(path['simulated_customer_cohorts']), 2)
            self.assertEqual(path['order_batches'][0]['origin'], 'expected_simulated_batch')
            self.assertFalse(path['last_result']['execution_authorized'])
            self.assertFalse(path['last_result']['simulation_context']['verified_actual'])
            summary = shadow.summary(START + timedelta(hours=6))
            self.assertEqual(Decimal(next(r for r in summary if r['policy'] == 'daily' and r['period'] == 'daily')['revenue']), Decimal(20))
            self.assertEqual(shadow.prune(START + timedelta(hours=6))['active_paths_preserved'], True)

    def test_unknown_real_mtd_stays_unknown_and_future_source_is_excluded(self):
        def no_identity(own, mode, **kwargs):
            result = fake_evaluate(own, mode, **kwargs)
            for row in result['selected']['score']['groups'].values():
                row['new_customers'] = None
            return result

        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=no_identity):
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            shadow.snapshot(dict(snapshot_id='unknown', evidence=evidence(START, None)))
            shadow.snapshot(dict(snapshot_id='unknown-next', evidence=evidence(START + timedelta(hours=6), '999')))
            with shadow.connect() as db:
                path = json.loads(db.execute("SELECT body FROM paths WHERE id='daily'").fetchone()[0])
            self.assertIsNone(path['monthly_revenue']['2026-10'])
            self.assertIsNone(path['new_customers'])
            self.assertIsNone(next(r for r in shadow.summary(START + timedelta(hours=6)) if r['policy'] == 'daily' and r['period'] == 'daily')['new_customers'])
            later = evidence(START)
            later['fx'] = dict(checked_at=(START + timedelta(hours=1)).isoformat())
            historical = shadow.historical([dict(snapshot_id='historical', evidence=later)], kind='actual_reconstruction')
            self.assertEqual(historical['records'][0]['status'], 'missing_at_historical_asof')

    def test_historical_results_keep_real_fixed_and_causal_meanings_separate(self):
        order = dict(order_key='o1', base_k='100', bonus_k='0', platform='PS', region_id=0,
                     regular_usd='10', paid_usd='9', cost_usd='5', package_retained_ratio='1',promotion_path=dict(kind='fixed', discount_usd='1'),
                     price_version='original', available_at=START.isoformat())
        snapshot = dict(snapshot_id='historical', evidence=evidence(START), historical_orders=[order])
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=fake_evaluate):
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            actual = shadow.historical([snapshot], kind='actual_reconstruction')
            fixed = shadow.historical([snapshot], kind='fixed_orders_reprice')
            causal = shadow.historical([snapshot], kind='causal_evaluation')
            self.assertEqual(actual['records'][0]['actual']['net_revenue_usd'], '9')
            self.assertEqual(fixed['records'][0]['alternatives']['daily']['totals']['net_revenue_usd'], '9.00')
            self.assertEqual(fixed['records'][0]['alternatives']['legacy_80_15_5']['status'], 'legacy_replay_gap')
            self.assertEqual(causal['records'][0]['status'], 'causal_identification_unavailable')
            self.assertFalse(all(result['training_eligible'] for result in (actual, fixed, causal)))

    def test_missing_historical_orders_never_become_zero_dollar_alternatives(self):
        snapshot = dict(snapshot_id='missing', evidence=evidence(START))
        with tempfile.TemporaryDirectory() as folder:
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            actual = shadow.historical([snapshot], kind='actual_reconstruction')['records'][0]
            fixed = shadow.historical([snapshot], kind='fixed_orders_reprice')['records'][0]
        self.assertEqual(actual['status'], 'historical_orders_missing')
        self.assertIsNone(actual['actual']['net_revenue_usd'])
        self.assertEqual(fixed['status'], 'historical_orders_missing')
        self.assertTrue(all(value.get('totals') is None for value in fixed['alternatives'].values()))
        self.assertIn('historical_orders_missing', [gap['reason'] for gap in fixed['gaps']])

    def test_actual_revenue_and_cny_gross_survive_missing_usd_cost_and_fixed_price_terms(self):
        first=dict(order_key='first',paid_usd='9',available_at=START.isoformat(),
                   revenue_cny='80',cost_cny='45',cost_usd=None)
        second=dict(order_key='second',paid_usd='5',available_at=START.isoformat(),
                    platform='PS',region_id=0,base_k='100',bonus_k='0',regular_usd='10',
                    package_retained_ratio='1',promotion_path=dict(kind='none'),price_version='confirmed_original',cost_usd='2')
        snapshot=dict(snapshot_id='partial',evidence=evidence(START),historical_orders=[first,second])
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation,'evaluate',side_effect=fake_evaluate):
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            actual=shadow.historical([snapshot],kind='actual_reconstruction')['records'][0]
            fixed=shadow.historical([snapshot],kind='fixed_orders_reprice')['records'][0]
        totals=actual['actual']
        self.assertEqual((totals['order_count'],totals['net_revenue_usd']),(2,'14'))
        self.assertIsNone(totals['procurement_contribution_usd'])
        self.assertEqual((totals['historical_cost_covered_orders'],totals['covered_procurement_contribution_usd']),(1,'3'))
        self.assertEqual((totals['cny_covered_orders'],totals['covered_procurement_gross_cny']),(1,'35'))
        self.assertIsNone(totals['actual_cny_gross'])
        self.assertIsNone(totals['delivered_k'])
        self.assertEqual(fixed['alternatives']['daily']['status'],'partial')
        self.assertEqual(fixed['alternatives']['daily']['totals']['order_count'],1)
        self.assertIsNone(fixed['alternatives']['daily']['totals']['covered_procurement_gross_cny'])
        self.assertIn('fixed_order_fields_missing', [gap['reason'] for gap in fixed['alternatives']['daily']['gaps']])

    def test_fixed_order_reprice_keeps_usd_revenue_when_historical_usd_cost_is_missing(self):
        order=dict(order_key='one',paid_usd='9',available_at=START.isoformat(),cost_usd=None,
                   revenue_cny='80',cost_cny='45',platform='PS',region_id=0,base_k='100',bonus_k='0',
                   regular_usd='10',package_retained_ratio='1',promotion_path=dict(kind='none'),price_version='confirmed_original')
        snapshot=dict(snapshot_id='cost-gap',evidence=evidence(START),historical_orders=[order])
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation,'evaluate',side_effect=fake_evaluate):
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            actual=shadow.historical([snapshot],kind='actual_reconstruction')['records'][0]
            fixed=shadow.historical([snapshot],kind='fixed_orders_reprice')['records'][0]
        self.assertEqual(actual['actual']['actual_cny_gross'],'35')
        self.assertIsNone(actual['actual']['procurement_contribution_usd'])
        alternative=fixed['alternatives']['daily']
        self.assertEqual(alternative['totals']['order_count'],1)
        self.assertEqual(alternative['totals']['net_revenue_usd'],'10.00')
        self.assertIsNone(alternative['totals']['procurement_contribution_usd'])
        self.assertIsNone(alternative['totals']['covered_procurement_gross_cny'])

    def test_fixed_order_never_borrows_current_package_retention_for_old_sale(self):
        order=dict(order_key='one',paid_usd='9',available_at=START.isoformat(),cost_usd='5',
                   platform='PS',region_id=0,base_k='100',bonus_k='0',regular_usd='10',
                   promotion_path=dict(kind='none'),price_version='confirmed_original')
        snapshot=dict(snapshot_id='retention-gap',evidence=evidence(START),historical_orders=[order])
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation,'evaluate',side_effect=fake_evaluate):
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            actual=shadow.historical([snapshot],kind='actual_reconstruction')['records'][0]
            fixed=shadow.historical([snapshot],kind='fixed_orders_reprice')['records'][0]
        self.assertEqual(actual['status'],'available')
        self.assertEqual(actual['actual']['net_revenue_usd'],'9')
        self.assertEqual(fixed['alternatives']['daily']['status'],'historical_orders_missing')
        self.assertIsNone(fixed['alternatives']['daily']['totals'])
        self.assertIn('package_retained_ratio',fixed['alternatives']['daily']['gaps'][0]['fields'])

    def test_late_cost_and_refund_revise_original_order_only_at_later_asof(self):
        later=START+timedelta(hours=1)
        first=dict(order_key='same',paid_usd='9',available_at=START.isoformat(),
                   paid_is_net_of_refunds=False,refund_usd='0',cost_usd=None)
        corrected=dict(first,paid_usd='8',refund_usd='1',cost_usd='5',
                       revenue_cny='80',cost_cny='45',available_at=later.isoformat())
        snapshots=[dict(snapshot_id='first',evidence=evidence(START),historical_orders=[first]),
                   dict(snapshot_id='later',evidence=evidence(later),historical_orders=[corrected])]
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation,'evaluate',side_effect=fake_evaluate):
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            result=shadow.historical(snapshots,kind='actual_reconstruction')
            fixed=shadow.historical(snapshots,kind='fixed_orders_reprice')
        before,after=result['records']
        self.assertEqual((before['actual']['order_count'],before['cumulative_actual']['net_revenue_usd']),(1,'9'))
        self.assertIsNone(before['cumulative_actual']['procurement_contribution_usd'])
        self.assertEqual(after['actual']['order_count'],0)
        self.assertEqual(after['revised_order_count'],1)
        self.assertEqual(after['cumulative_actual']['net_revenue_usd'],'7')
        self.assertEqual(after['cumulative_actual']['procurement_contribution_usd'],'2')
        self.assertEqual(result['reconciled_actual']['actual']['actual_cny_gross'],'35')
        self.assertEqual(result['reconciled_actual']['revised_order_count'],1)
        self.assertEqual(fixed['records'][1]['status'],'late_order_revision_not_repriced')
        self.assertEqual(fixed['records'][1]['alternatives'],{})

    def test_demand_counterfactual_is_independent_projection(self):
        snapshots = [dict(snapshot_id=str(i), evidence=evidence(START + timedelta(hours=i*6))) for i in range(2)]
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=fake_evaluate):
            result = simulation.Shadow(Path(folder) / 'shadow.db').historical(snapshots, kind='demand_counterfactual')
        self.assertEqual(result['simulation_kind'], 'demand_counterfactual')
        self.assertEqual(len(result['records']), 2)
        self.assertTrue(all(r['status'] == 'scenario_projection' for r in result['records']))
        self.assertTrue(all(Decimal(r['path']['revenue']) == Decimal(20) for r in result['records']))

    def test_region_and_new_month_follow_own_path(self):
        start = datetime(2026, 10, 31, 15, tzinfo=timezone.utc)
        seen = []

        def regional(own, mode, **kwargs):
            if own.get('mode') == 'shadow' and mode == 'daily':
                seen.append((own['monthly_target']['mtd'], [r['factor'] for r in own['region_rules']]))
            result = fake_evaluate(own, mode, **kwargs)
            result['selected']['action']['region_coefficients'] = {'21:PS': '.8', '21:XBOX': '.8'}
            return result

        first, second = evidence(start), evidence(start + timedelta(hours=6), '999')
        for source in (first, second):
            source['region_rules'] = [dict(region_id=21, platforms=['PS', 'XBOX'], factor='.91')]
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=regional):
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            shadow.snapshot(dict(snapshot_id='oct', evidence=first))
            shadow.snapshot(dict(snapshot_id='nov', evidence=second))
            with shadow.connect() as db:
                path = json.loads(db.execute("SELECT body FROM paths WHERE id='daily'").fetchone()[0])
        self.assertEqual(seen[0][1], ['.91', '.91'])
        self.assertEqual(seen[1][1], ['.8', '.8'])
        self.assertGreater(Decimal(path['monthly_revenue']['2026-11']), 0)
        self.assertEqual(Decimal(seen[1][0]), Decimal(path['monthly_revenue']['2026-11']))

    def test_incomplete_new_month_and_duplicate_history_remain_explicit(self):
        start = datetime(2026, 10, 31, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=fake_evaluate):
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            shadow.snapshot(dict(snapshot_id='oct', evidence=evidence(start)))
            shadow.snapshot(dict(snapshot_id='nov-gap', evidence=evidence(start + timedelta(hours=12), '999')))
            with shadow.connect() as db:
                path = json.loads(db.execute("SELECT body FROM paths WHERE id='daily'").fetchone()[0])
            self.assertIsNone(path['monthly_revenue']['2026-11'])
            order = dict(order_key='same-order', base_k='100', bonus_k='0', platform='PS', region_id=0,
                         regular_usd='10', paid_usd='9', cost_usd='5', package_retained_ratio='1',promotion_path=dict(kind='none'),
                         price_version='original', available_at=start.isoformat(), refund_usd='2', paid_is_net_of_refunds=False)
            snapshots = [dict(snapshot_id=str(i), evidence=evidence(start + timedelta(hours=i)), historical_orders=[order]) for i in range(2)]
            actual = shadow.historical(snapshots, kind='actual_reconstruction')
            fixed = shadow.historical(snapshots, kind='fixed_orders_reprice')
            self.assertEqual([r['actual']['order_count'] for r in actual['records']], [1, 0])
            self.assertEqual(actual['records'][0]['actual']['net_revenue_usd'], '7')
            self.assertIn('payment_fee_scope_unverified', actual['records'][0]['actual']['revenue_basis'])
            self.assertEqual(Decimal(fixed['records'][0]['alternatives']['daily']['totals']['net_revenue_usd']), Decimal(8))
            self.assertEqual(fixed['records'][1]['fixed_order_count'], 0)

    def test_causal_treatment_probability_uses_control_complement(self):
        rows = [dict(assignment_id='t', unit_key='t', block_id='b', arm='treatment', treatment_probability='.2',
                     outcome_revenue_usd='100', outcome_matured=True, available_at=START.isoformat()),
                dict(assignment_id='c', unit_key='c', block_id='b', arm='control', treatment_probability='.8',
                     outcome_revenue_usd='40', outcome_matured=True, available_at=START.isoformat())]
        snapshot = dict(snapshot_id='experiment', evidence=evidence(START), causal_design=dict(kind='randomized_block',
                        all_assignments_included=True, unit='affected_resource_bundle'), experiment_observations=rows)
        with tempfile.TemporaryDirectory() as folder:
            result = simulation.Shadow(Path(folder) / 'shadow.db').historical([snapshot], kind='causal_evaluation')
        estimate = result['records'][0]
        self.assertEqual(estimate['status'], 'identified_randomized_estimate')
        self.assertEqual(Decimal(estimate['effect_usd']), Decimal(150))
        self.assertEqual(estimate['propensity_basis'], 'treatment_probability_for_both_arms')

    def test_sprint_stays_continuous_without_implicit_calendar_deadlines(self):
        times = [datetime(2026, 10, 31, 15, tzinfo=timezone.utc),
                 datetime(2026, 10, 31, 16, tzinfo=timezone.utc),
                 datetime(2026, 11, 5, 16, tzinfo=timezone.utc),
                 datetime(2026, 11, 23, 16, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as folder, patch.object(simulation, 'evaluate', side_effect=fake_evaluate):
            shadow = simulation.Shadow(Path(folder) / 'shadow.db')
            paths = []
            for i, at in enumerate(times):
                shadow.snapshot(dict(snapshot_id=f'sprint-{i}', evidence=evidence(at, '999')))
                with shadow.connect() as db:
                    paths.append(json.loads(db.execute("SELECT body FROM paths WHERE id='revenue_sprint'").fetchone()[0]))
        self.assertTrue(all(p['active_deadline'] is None for p in paths))
        self.assertTrue(all(p['effective_mode']=='revenue_sprint' for p in paths))
        self.assertTrue(all(p['window_started_at']==paths[0]['window_started_at'] for p in paths))
        self.assertEqual(paths[1]['monthly_revenue']['2026-11'], '0')
        self.assertNotIn('window_history',paths[3])


if __name__ == '__main__':
    unittest.main()

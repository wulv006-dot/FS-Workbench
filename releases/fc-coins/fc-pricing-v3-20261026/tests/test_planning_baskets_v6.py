"""Payment-window and quote-revision tests using the existing attachment schema."""
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3 import business_source
from fc_pricing_v3.planning_baskets_v6 import PAID_SCOPE, build_planning_baskets


CUTOFF = datetime.fromisoformat('2026-11-13T10:00:00+08:00')
AS_OF = CUTOFF + timedelta(minutes=5)
CURVE = 'frozen-curve'


def paid(key, at, *, platform='PS', purchase='1000', cost=None, available_at=AS_OF):
    return dict(order_key=key, paid_at=at.isoformat(), available_at=available_at.isoformat(),
                platform=platform, base_k=purchase, cost_cny=cost, source_sha256='source-' + key)


def attachment(rows, start, end, *, revision='original', complete=True, available_at=AS_OF):
    return dict(historical_orders=rows, source_sha256=revision, available_at=available_at.isoformat(),
                historical_orders_coverage=dict(source_sha256=revision, population_scope=PAID_SCOPE,
                    paid_window_start=start.isoformat(), paid_window_end_exclusive=end.isoformat(),
                    population_status='complete' if complete else 'partial', window_complete=complete,
                    refund_revision_coverage='complete'))


def matches(rows, path='current-1000'):
    return {row['order_key']: dict(order_revision=row['source_sha256'], curve_key=CURVE,
                                 available_at=AS_OF.isoformat(), purchase_k=row['base_k'],
                                 path_id=path, quote_ref='native-quote', eligibility_ref='current-eligibility',
                                 fulfilment_ref='actual-fulfilment') for row in rows}


def buckets(closed, recent, matched):
    return build_planning_baskets('PS', CURVE, closed, recent, matched,
                                  paid_cutoff=CUTOFF, as_of=AS_OF)


def closed_source(rows):
    window = business_source.historical_period('7d', now=CUTOFF)
    return attachment(rows, datetime.fromisoformat(window['paid_window_start']),
                      datetime.fromisoformat(window['paid_window_end_exclusive']))


def recent_source(rows, days=3, **extra):
    return attachment(rows, CUTOFF - timedelta(days=days), CUTOFF, revision='recent', **extra)


class PlanningBaskets(unittest.TestCase):
    def test_shared_attachment_uses_pinned_projection_and_preserves_future_or_missing_fields(self):
        names = ['old-order', 'future-order', 'discount-order', 'coupon-order', 'mixed-coupon-order', 'stacked-order']
        hashes = [hashlib.sha256(name.encode()).hexdigest() for name in names]
        observations = dict(platform='PS', purchase_k='100', bonus_k='0', delivered_k='100',
                            single_line_unit_purchase=True, region_id=0, regular_usd='10',
                            retained_percent='100', points='0', observed_at=AS_OF.isoformat(), source_sha256='quantity')
        rows = [dict(site_id='266', gid='1327', order_no=name, paytime='2026-11-12 11:00:00',
                     pay_status='1', amount_usd_format='9.99', status_format='已完成',
                     tracking={'coupons': []}, fc27_coins=observations) for name in names]
        rows[1]['fc27_coins'] = dict(observations, observed_at=(AS_OF+timedelta(minutes=1)).isoformat())
        log = dict(id='42', templateId='1327', status='1', usedAt='2026-11-12 11:01:00')
        for row in rows[3:]:
            row.update(amount_usd_format='5', tracking={'coupons':[log]})
        rows[4]['fc27_coins'] = dict(observations, single_line_unit_purchase=False)
        rows[5]['discount_code'] = 'STACKED'
        dataset = {'rows': [{'订单号': token, '产品类型': '货币(Gold)', '折扣金额': str(discount)}
                            for token, discount in zip(hashes, (0, 0, 1, 5, 5, 5))]}
        shared = dict(rows=rows, dataset=dataset, identity_catalog=dict(complete=True, rows=rows),
                      coverage=dict(admin_complete=True, missing_days=[], publication_id='shared-original',
                                    captured_at=CUTOFF.isoformat(), source_revision='shared-days',
                                    fc27_projection_revision='shared-quantities'))
        channel = SimpleNamespace(apply_cost_overrides=lambda data: {
            'sources': {'accounting': {'status':'available'}}, 'testOrders': {}})
        effects = SimpleNamespace(fraud=lambda row: False)
        scope = dict(site_id='266', gid='1327', start='2026-11-06', end='2026-11-12')
        with patch.dict(sys.modules, channel_source=channel, channel_effects=effects):
            result = business_source.shared_curve_attachment(shared, scope, as_of=AS_OF)
        proof = result['historical_orders_coverage']
        self.assertEqual(proof['population_status'], 'complete')
        self.assertEqual(proof['fc27_projection_revision'], 'shared-quantities')
        self.assertEqual(proof['coverage_gaps'], {'shared_native_coin_quantity_unavailable':1})
        self.assertEqual([row['base_k'] for row in result['historical_orders']], ['100', None, '100', '100', '100', '100'])
        promotions = [row['promotion_path'] for row in result['historical_orders']]
        self.assertEqual(promotions[:3], [{'kind':'none'},None,None])
        self.assertEqual(promotions[3]['template_id'], '1327')
        self.assertEqual(len(promotions[3]['evidence_ref']), 64)
        self.assertEqual(promotions[4:], [None, None])
        self.assertTrue(all(name not in str(result) for name in names))

    def test_curve_coupon_terms_read_once_and_respect_scope_exclusivity_and_expiry(self):
        row = dict(status=1, site_id=0, game_id=0, product_type=0, goods_id=0, is_open=0, fetch_scene=3,
                   mode_type=1, reduce='5', attain='10', max_reduce='0', time_effect=1,
                   start_time='2026-11-01 00:00:00', end_time='2026-12-31 00:00:00')
        rows = [dict(row, id=1327), dict(row, id=1329, end_time='2026-11-12 00:00:00'),
                dict(row, id=1331, is_open=1), dict(row, id=1323, mode_type=2, reduce='80', max_reduce='50'),
                dict(row, id=1343, fetch_scene=1, mode_type=2, reduce='85', max_reduce='50', time_effect=2, days=7,
                     scope_bindings='[{"game_id":1327,"category_ids":[]}]')]
        calls = []

        def pages(session, path, filters, limit):
            calls.append((path, filters, limit))
            return rows

        with patch.dict(sys.modules, channel_source=SimpleNamespace(pages=pages)):
            result = business_source.collect_curve_coupon_terms(None, clock=lambda: AS_OF)
        self.assertEqual(calls, [('/admin/market.Coupon/index', [('id', 'IN', '1323,1327,1329,1331,1343')], 100)])
        self.assertEqual(set(result['terms']), {'1327', '1323', '1343'})
        self.assertEqual(result['terms']['1327']['path'],
                         dict(kind='fixed', threshold_usd='10', cap_usd=None, discount_usd='5'))
        self.assertEqual(result['terms']['1323']['path']['retained_ratio'], '0.8')
        self.assertEqual(result['terms']['1343']['path']['cap_usd'], '50')
        self.assertIsNone(result['terms']['1343']['valid_until'])
        self.assertEqual(result['coverage_gaps'], ['current_coupon_terms_unverified:1331'])

    def test_recent_combines_saved_days_and_only_the_current_day_native_read(self):
        historical = paid('closed-order', CUTOFF - timedelta(days=1))
        native = dict(site_id='266', gid='1327', pay_status='1', status_format='已完成',
                      order_no='today-order', aid='21587', paytime='2026-11-13 09:00:00',
                      is_region_price='0', discount='100', points='0', amount_usd_format='10',
                      before_discount='10', content='<span class="item">100K Coins x1 = $10</span>')
        calls = []

        def pages(session, path, filters, limit):
            calls.append((path, dict((key, value) for key, _, value in filters), limit))
            return [native]

        channel = SimpleNamespace(pages=pages, apply_cost_overrides=lambda data: {
            'sources': {'accounting': {'status':'available'}}, 'testOrders': {}})
        effects = SimpleNamespace(fraud=lambda row: False)
        with patch.dict(sys.modules, channel_source=channel, channel_effects=effects), \
                patch.object(business_source, '_historical_provider_now', return_value=AS_OF):
            recent = business_source.collect_recent_curve_population(None, closed_source([historical]), CUTOFF)
            partial = business_source.collect_recent_curve_population(None, None, CUTOFF)
        self.assertEqual(calls, [('/admin/order.Order/index', dict(site_id='266', gid='1327', pay_status='1',
            paytime='2026-11-13 00:00:00,2026-11-13 10:00:00', cid='1'), 100)] * 2)
        self.assertEqual(recent['historical_orders_coverage']['population_status'], 'complete')
        self.assertEqual(recent['historical_orders_coverage']['closed_archive_revision'], 'original')
        self.assertEqual(partial['historical_orders_coverage']['population_status'], 'partial')
        first, today = recent['historical_orders']
        self.assertEqual(first, historical)
        self.assertEqual(today['base_k'], '100')
        self.assertTrue(today['single_line_unit_purchase'])
        self.assertEqual(today['promotion_path'], {'kind':'none'})
        self.assertNotIn('today-order', str(recent))

    def test_uses_complete_paid_population_while_preserving_original_refund_gap(self):
        key = 'private-order'
        period = business_source.historical_period('7d', now=CUTOFF)['period']
        row = dict(paidAt='2026-11-11 10:00:00', salesUsd='10', status='未发货', coupons=[])
        admin = dict(aid='21587', before_discount='10', amount_usd_format='10', discount='100',
                     points='0', content='<span class="item">1000K Coins + 30K Free x1 = $10</span>')
        scope = dict(period=period, status='complete', canonical_archive_sha256='archive-revision',
                     ES_source_sha256='ES-revision', ES_complete=True, missing_product_identity=0)
        with patch.object(business_source, '_historical_provider_now', return_value=AS_OF), \
             patch.object(business_source, '_period_population', return_value=({key: (row, {'discount_usd': '0'})}, scope)), \
             patch.object(business_source, '_live_traces', return_value=({key: admin}, {}, {})), \
             patch.object(business_source, 'historical_mix', return_value={'sha256': 'mix-revision'}):
            historical = business_source.collect_historical_attachment('7d', None, None)
        main = buckets(historical, None, matches(historical['historical_orders']))['main']
        self.assertEqual(main['members'], [{'path_id': 'current-1000', 'weight': '1', 'quote_ref': 'native-quote'}])
        self.assertEqual(main['source_sha256'], historical['source_sha256'])
        self.assertEqual(main['orders_without_historical_cost'], 1)
        self.assertEqual(main['coverage_status'], 'complete')
        self.assertEqual(main['coverage_gaps'], [])
        self.assertIn('not_collected', historical['historical_orders_coverage']['refund_revision_coverage'])
        self.assertEqual(historical['historical_orders_coverage']['gaps']['historical_refund_revision_chain_not_collected'], 1)
        self.assertNotIn(historical['historical_orders'][0]['order_key'], str(main))

    def test_beijing_closed_seven_days_and_same_platform_with_unknown_cost(self):
        window = business_source.historical_period('7d', now=CUTOFF)
        start = datetime.fromisoformat(window['paid_window_start'])
        end = datetime.fromisoformat(window['paid_window_end_exclusive'])
        rows = [paid('first', start), paid('last', end - timedelta(seconds=1), cost='600'),
                paid('early', start - timedelta(seconds=1)), paid('today', end),
                paid('xbox', end - timedelta(seconds=2), platform='XBOX')]
        main = buckets(closed_source(rows), None, matches(rows))['main']
        self.assertEqual(main['coverage_status'], 'complete')
        self.assertEqual(main['paid_orders'], 2)
        self.assertEqual(main['orders_without_historical_cost'], 1)
        self.assertEqual(main['members'], [{'path_id': 'current-1000', 'weight': '2', 'quote_ref': 'native-quote'}])
        self.assertEqual(main['window']['start'], '2026-11-06T00:00:00+08:00')

    def test_recent_prefers_twenty_four_hours_with_thirty_same_platform_orders(self):
        rows = [paid(f'order-{i}', CUTOFF - timedelta(hours=1)) for i in range(30)]
        rows.extend([paid('older', CUTOFF - timedelta(hours=25)),
                     paid('other-platform', CUTOFF - timedelta(hours=1), platform='PC')])
        recent = buckets(None, recent_source(rows, days=1), matches(rows))['recent']
        self.assertEqual(recent['selection'], 'latest_24h')
        self.assertEqual(recent['paid_orders'], 30)
        self.assertEqual(recent['members'][0]['weight'], '30')

    def test_recent_widens_to_three_days_and_falls_back_only_when_short(self):
        rows = [paid('today', CUTOFF - timedelta(hours=1))]
        rows.extend(paid(f'older-{i}', CUTOFF - timedelta(hours=48)) for i in range(29))
        recent = buckets(None, recent_source(rows), matches(rows))['recent']
        self.assertEqual(recent['selection'], 'latest_3d')
        self.assertEqual(recent['previous_attempt']['paid_orders'], 1)
        self.assertEqual(recent['members'][0]['weight'], '30')

        rows.pop()
        baseline = [paid('main-order', CUTOFF - timedelta(days=4))]
        result = buckets(closed_source(baseline), recent_source(rows), matches(rows + baseline))
        self.assertEqual(result['recent']['selection'], 'main_fallback')
        self.assertEqual(result['recent']['previous_attempt']['paid_orders'], 29)
        self.assertEqual(result['recent']['members'], result['main']['members'])
        self.assertTrue(result['recent']['weak_structure'])

    def test_missing_or_partial_recent_never_passes_as_sample_shortage(self):
        row = paid('main', CUTOFF - timedelta(days=4))
        sources = [(None, 'latest_24h', 'paid_source_unavailable'),
                   (recent_source([], complete=False), 'latest_24h', 'paid_source_population_incomplete'),
                   (recent_source([], days=1), 'latest_3d', 'paid_source_window_uncovered'),
                   (recent_source([paid('unknown', CUTOFF - timedelta(hours=1), platform=None)]),
                    'latest_24h', 'platform_unknown'),
                   (recent_source([paid('missing-quote', CUTOFF - timedelta(hours=1))]),
                    'latest_3d', 'current_quote_or_eligibility_unverified')]
        for source, selection, gap in sources:
            with self.subTest(selection=selection, gap=gap):
                recent = buckets(closed_source([row]), source, matches([row]))['recent']
                self.assertEqual(recent['selection'], selection)
                self.assertEqual(recent['coverage_status'], 'partial')
                self.assertIn(gap, recent['coverage_gaps'])

    def test_reprice_matches_order_curve_quantity_and_frozen_eligibility_and_fulfilment(self):
        rows = [paid('sample', CUTOFF - timedelta(days=4)),
                paid('unknown-quantity', CUTOFF - timedelta(days=4), purchase=None)]
        for field, value in [('curve_key', 'old'), ('order_revision', 'stale'), ('purchase_k', '100'),
                             ('eligibility_ref', None), ('fulfilment_ref', None),
                             ('available_at', (AS_OF + timedelta(minutes=1)).isoformat())]:
            with self.subTest(field=field):
                priced = matches(rows)
                priced['sample'][field] = value
                main = buckets(closed_source(rows), None, priced)['main']
                self.assertEqual(main['paid_orders'], 2)
                self.assertEqual(main['members'], [])
                self.assertEqual(main['gap_counts'], {'current_quote_or_eligibility_unverified': 1,
                                                     'purchase_quantity_unknown': 1})

    def test_later_order_revision_is_not_backdated_into_frozen_basket(self):
        row = paid('sample', CUTOFF - timedelta(days=4), cost='500',
                   available_at=AS_OF + timedelta(hours=1))
        main = buckets(closed_source([row]), None, matches([row]))['main']
        self.assertEqual(main['gap_counts'], {'order_not_available_at_as_of': 1})
        self.assertEqual(main['paid_orders'], 0)
        self.assertEqual(main['members'], [])

    def test_exact_duplicates_count_once_and_conflicts_do_not_choose_latest(self):
        row = paid('sample', CUTOFF - timedelta(days=4))
        main = buckets(closed_source([row, dict(row)]), None, matches([row]))['main']
        self.assertEqual(main['paid_orders'], 1)
        for conflict in (dict(row, base_k='100'), dict(row, platform='XBOX'),
                         dict(row, paid_at=CUTOFF.isoformat())):
            with self.subTest(conflict=conflict):
                main = buckets(closed_source([row, conflict]), None, matches([row]))['main']
                self.assertEqual(main['gap_counts'], {'order_revision_conflict': 1})
                self.assertEqual(main['members'], [])

    def test_same_path_cannot_merge_different_quote_revisions(self):
        rows = [paid(key, CUTOFF - timedelta(days=4)) for key in ('first', 'second')]
        priced = matches(rows)
        priced['second']['quote_ref'] = 'different-quote'
        main = buckets(closed_source(rows), None, priced)['main']
        self.assertEqual(main['paid_orders'], 2)
        self.assertEqual(main['members'], [])
        self.assertEqual(main['gap_counts'], {'current_quote_path_revision_conflict': 2})


if __name__ == '__main__':
    unittest.main()

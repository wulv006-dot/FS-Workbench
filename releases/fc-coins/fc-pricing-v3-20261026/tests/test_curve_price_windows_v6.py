"""Frozen V6 merchandise curves bind at creation, independently of payment."""
from copy import deepcopy
import unittest

import test_business_source as legacy
from fc_pricing_v3 import business_source as source
from fc_pricing_v3.price_curve import read_curve, curve_key, IDENTITY_FIELDS


def curve(high='75', bonus='30'):
    goods = dict(id=163329311, mid=41217957, gid=1327, cid=9623, site_id=266,
                 aid=21587, unit='K', status=1, unit_price='.1',
                 more=dict(gold=['100', '1000'], give=['5', bonus],
                           discount=['100', '75'], price=['10', high]))
    return read_curve(goods, {k: goods[k] for k in IDENTITY_FIELDS},
                      {'version': 'fixture-saved-native'})


def fixture():
    now, order, window = legacy.BusinessSourceTest().window_fixture()
    order.update(content='<span class="item">1000 K coins+30K Free x 1 = $75</span>',
                 before_discount='75', amount_usd_format='$75')
    window.update(mutable_resources=['base:PS'], price_scope_contract='fc27_three_platform_v1',
                  action=dict(base_prices={'PS': '10'}, region_coefficients={}, curves={'PS': curve()}),
                  budget_reference=dict(base_prices={'PS': '10'}, region_coefficients={}, curves={'PS': curve('80')}))
    return now, order, window


class CurveWindows(unittest.TestCase):
    def test_saved_high_tier_binds_without_linear_reconstruction(self):
        now, order, window = fixture()
        result = source.bind_price_windows([order], [window], now)
        outcome = result['actual_outcomes'][0]
        self.assertEqual(outcome['curve_key'], curve_key(window['action']['curves']['PS']))
        self.assertEqual(outcome['purchase_k'], '1000')
        self.assertEqual(outcome['promised_bonus_k'], '30')
        self.assertEqual(result['budget_settlements'][0]['reference_net_usd'], '80.00')
        self.assertEqual(result['training_observations'], [])
        self.assertEqual(result['curve_training_observations'][0]['curve_key'], outcome['curve_key'])
        self.assertNotIn('private-live-order', str(result))

    def test_production_curve_only_window_binds_and_reaches_daily_profit(self):
        from fc_pricing_v3 import daily
        now, order, window = fixture()
        del window['action']['base_prices']
        window['origin'] = 'observed_native_curve_window'
        window['plan_id'] = 'curve-plan'
        window['curve_selection'] = {'PS': {'assignment': dict(
            platform='PS', segment='large', plan_id='curve-plan',
            primary_curve_key=curve_key(window['action']['curves']['PS']),
            starts_at=window['opened_at'], ends_at=now.isoformat(),
            label='C', actual_label='CURRENT')}}
        actual = source.bind_price_windows([order], [window], now)
        self.assertEqual(actual['actual_outcomes'][0]['group'], 'PS')
        self.assertEqual(actual['curve_training_observations'][0]['effective_price_usd'], '10')
        date = daily.instant(actual['actual_outcomes'][0]['occurred_at']).astimezone(source.TZ).date().isoformat()
        summary = daily.profit_summary(actual, [window], [], date, 'curve-plan')
        self.assertEqual(summary['active_plan']['totals']['orders'], 1)
        group = summary['review_day']['groups'][0]
        self.assertEqual((group['group'], group['segment'], group['label']), ('PS', 'large', 'CURRENT'))

    def test_daily_review_reuses_shared_paid_day_and_hourly_outcomes(self):
        import hashlib
        from types import SimpleNamespace
        from unittest.mock import patch
        from fc_pricing_v3 import daily
        date = '2026-11-14'
        def make(number, paid='1'):
            return dict(order_no=number, site_id=266, gid=1327, pay_status=paid,
                        paytime=date+' 12:23:44', amount_usd_format='8.25')
        orders = [make('coin'), make('items'), make('unpaid', '2')]
        product = '货币(Gold)'
        lines = [{'订单号': hashlib.sha256(row['order_no'].encode()).hexdigest(),
                  '产品类型': product if row['order_no']!='items' else 'Items'} for row in orders]
        shared = dict(rows=orders, dataset=dict(rows=lines), coverage=dict(admin_complete=True))
        online = dict(actual_outcomes=[dict(price_window_id='saved')])
        with patch.dict('sys.modules', {'shared_es_facts': SimpleNamespace(read=lambda scope: shared)}):
            result = daily.curve_review_outcomes(date, online)
        self.assertIs(result['online'], online)
        self.assertEqual(result['actual']['hourly'][12], dict(hour=12, orders=1, net_paid_usd='8.25'))
        self.assertEqual(len(result['payment_days']), 1)

    def test_payment_after_change_keeps_creation_curve(self):
        now, order, first = fixture()
        second = deepcopy(first)
        second.update(operation_id='later', opened_at='2026-10-26T01:00:00+00:00')
        second['action']['curves']['PS'] = curve('78')
        order['paytime'] = '2026-10-26 10:00:00'
        result = source.bind_price_windows([order], [first, second], now)
        self.assertEqual(result['actual_outcomes'][0]['price_window_id'], 'op')
        observations = result['curve_training_observations']
        self.assertEqual(len({o['curve_key'] for o in observations}), 2)

    def test_same_100k_does_not_bind_wrong_high_tier(self):
        now, order, window = fixture()
        window['action']['curves']['PS'] = curve('78')
        result = source.bind_price_windows([order], [window], now)
        self.assertEqual(result['actual_outcomes'], [])
        self.assertIn('actual_regular_price_not_window_price', result['learning_coverage']['gaps'])

    def test_unproven_quantity_region_and_gift_do_not_bind(self):
        now, order, window = fixture()
        changes = [dict(is_region_price=1, region_price_lang_region_id=21),
                   dict(content='<span class="item">500 K coins x 1 = $75</span>'),
                   dict(content='<span class="item">1000 K coins+20K Free x 1 = $75</span>'),
                   dict(content='<span class="item">500 K coins+15K Free x 2 = $75</span>'),
                   dict(site_id=999), dict(gid=999), dict(is_region_price=1),
                   dict(is_region_price=1, region_price_lang_region_id=0),
                   dict(before_discount='75.01')]
        for change in changes:
            with self.subTest(change=change):
                result = source.bind_price_windows([dict(order, **change)], [window], now)
                self.assertEqual(result['actual_outcomes'], [])

    def test_candidate_or_cross_platform_curve_cannot_create_zero_order_training(self):
        now, order, original = fixture()
        for change in ('candidate', 'candidate_origin', 'platform', 'site'):
            with self.subTest(change=change):
                window = deepcopy(original)
                frozen = window['action']['curves']['PS']
                if change == 'candidate':
                    frozen['compilation_status'] = 'EDITOR_CANDIDATE'
                elif change == 'candidate_origin':
                    from fc_pricing_v3.price_curve import CATALOGUE_ORIGIN_FIELD, EDITOR_CATALOGUE_ORIGIN
                    frozen['native_contract'][CATALOGUE_ORIGIN_FIELD] = EDITOR_CATALOGUE_ORIGIN
                else:
                    field, value = ('aid', '21585') if change == 'platform' else ('site_id', '0')
                    frozen['identity'][field] = value
                    frozen['native_payload'][field] = value
                for rows in ([], [order]):
                    result = source.bind_price_windows(rows, [window], now)
                    self.assertEqual(result['actual_outcomes'], [])
                    self.assertEqual(result['curve_training_observations'], [])

    def test_missing_curve_does_not_fall_back_to_scalar(self):
        now, order, window = fixture()
        window['action']['curves'] = {}
        result = source.bind_price_windows([order], [window], now)
        self.assertEqual(result['actual_outcomes'], [])

    def test_old_windows_keep_old_training_contract(self):
        now, order, window = legacy.BusinessSourceTest().window_fixture()
        result = source.bind_price_windows([order], [window], now)
        self.assertEqual(len(result['training_observations']), 1)
        self.assertNotIn('curve_key', result['actual_outcomes'][0])
        self.assertEqual(result.get('curve_training_observations', []), [])


if __name__ == '__main__':
    unittest.main()

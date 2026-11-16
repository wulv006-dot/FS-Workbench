import copy
import unittest
from datetime import datetime, timedelta, timezone

from bridge import handle
from campaign_backend.core import ContractError
from campaign_backend.discount_revenue import FC_COUPON, read_coupon_usage, summarize_coupon_usage, coupon_record, query_window

COUPON = dict(id=1395, site_id=266, game_id=1327, param_code='carnival_202611', title='FC27 Event 10% Coupon',
              fetch_qty=16, used_qty=4, limit_qty=0, days=7)


def log(number='D1', **changes):
    base = dict(id=1, site_id=266, coupon_id=1395, status=1, member_id=501, use_time='2026-11-16 10:00:00',
                discount_amount='10.08', order_no=number, order=dict(before_discount='126.05', amount='119.52'))
    base.update(changes)
    return base


def order(number='D1', **changes):
    base = dict(order_no=number, site_id=266, pay_status=1, paytime='2026-11-16 10:05:00', amount_usd_format='$ 119.52',
                currency_code='USD', pay_money_format2=['USD', '119.52'])
    base.update(changes)
    return base


class Reader:
    """Records every read so a test can see the exact filters, like the real Admin reader would receive."""

    def __init__(self, coupon=COUPON, logs=(), orders=()):
        self.coupon, self.logs, self.orders, self.calls, self.closed = coupon, list(logs), list(orders), [], False

    def detail(self, resource, object_id):
        self.calls.append(('detail', resource, str(object_id)))
        return copy.deepcopy(self.coupon)

    def pages(self, resource, filters, **kw):
        self.calls.append((resource, filters))
        if resource == 'coupon_logs':
            return copy.deepcopy(self.logs)
        if resource == 'orders':
            wanted = set(dict((f[0], f[2]) for f in filters)['order_no'].split(','))
            rows = [o for o in self.orders if o['order_no'] in wanted]
            validate = kw.get('validate')
            assert all(validate(r) for r in rows)
            return copy.deepcopy(rows)
        raise AssertionError(resource)

    def close(self):
        self.closed = True


class CouponUsageTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(action='coupon_usage', site_id='266', activity='fc27-season2', game='all', **{'from': '2026-11-16', 'to': '2026-11-16'})
        self.start, self.end, _ = query_window(self.request)
        self.coupon = coupon_record(COUPON)

    def summary(self, logs, orders):
        return summarize_coupon_usage(self.coupon, logs, orders, self.start, self.end)

    def test_only_the_approved_coupon_is_read(self):
        self.assertEqual(self.coupon['issued_total'], 16)
        self.assertEqual(self.coupon['used_total'], 4)
        for changes in [dict(id=1396), dict(site_id=0), dict(game_id=891), dict(param_code='other')]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ContractError, 'ACTIVITY_COUPON_IDENTITY_MISMATCH'):
                coupon_record(dict(COUPON, **changes))
        for key in ('fetch_qty', 'used_qty'):
            with self.subTest(key=key), self.assertRaisesRegex(ContractError, 'COUPON_COUNTER_INVALID'):
                coupon_record(dict(COUPON, **{key: -1}))

    def test_use_joins_the_paid_order_and_converts(self):
        value = self.summary([log('D1'), log('D2', id=2, member_id=502, discount_amount='5.00', order=dict(before_discount='60.00', amount='55.50')),
                              log('D3', id=3, member_id=502, use_time='2026-11-16 12:00:00')],
                             [order('D1'), order('D2', amount_usd_format='$ 55.50', pay_money_format2=['USD', '55.50']), order('D3', pay_status=0)])
        self.assertEqual(value['totals'], dict(used_orders=3, paid_orders=2, refunded_orders=0, unpaid_orders=1, paid_usd_minor=17502,
                                               discount_usd_minor=1508, repurchase_orders=0, repurchase_usd_minor=0, unique_buyers=2))
        self.assertEqual(value['conversion']['claim_to_use'], 0.25)
        self.assertEqual(value['conversion']['claim_to_use_scope'], 'cumulative')
        self.assertEqual(value['conversion']['paid_per_use'], round(2 / 3, 6))
        self.assertEqual(value['conversion']['issued_in_window'], 'not_available')
        self.assertEqual(value['daily'], [dict(date='2026-11-16', used_orders=3, paid_orders=2, paid_usd_minor=17502)])
        self.assertTrue(value['coverage']['complete'])

    def test_refunded_stays_paid_and_unpaid_is_never_revenue(self):
        value = self.summary([log('D1'), log('D2', id=2)], [order('D1', pay_status='2'), order('D2', pay_status=0)])
        self.assertEqual((value['totals']['paid_orders'], value['totals']['refunded_orders'], value['totals']['unpaid_orders']), (1, 1, 1))
        self.assertEqual(value['totals']['paid_usd_minor'], 11952)

    def test_no_issuance_means_no_rate_and_no_use_means_no_ratio(self):
        coupon = coupon_record(dict(COUPON, fetch_qty=0, used_qty=0))
        value = summarize_coupon_usage(coupon, [], [], self.start, self.end)
        self.assertIsNone(value['conversion']['claim_to_use'])
        self.assertIsNone(value['conversion']['paid_per_use'])
        self.assertEqual(value['totals']['used_orders'], 0)
        self.assertEqual(value['daily'], [])

    def test_duplicates_collapse_and_conflicts_fail_closed(self):
        self.assertEqual(self.summary([log('D1'), log('D1')], [order('D1')])['totals']['used_orders'], 1)
        with self.assertRaisesRegex(ContractError, 'CONFLICTING_DUPLICATE_COUPON_USE'):
            self.summary([log('D1'), log('D1', discount_amount='99.00')], [order('D1')])
        with self.assertRaisesRegex(ContractError, 'CONFLICTING_DUPLICATE_ORDER'):
            self.summary([log('D1')], [order('D1'), order('D1', pay_status=0)])

    def test_scope_state_time_and_missing_order_fail_closed(self):
        cases = [(log(site_id=0), 'COUPON_LOG_SCOPE_MISMATCH'), (log(coupon_id=1241), 'COUPON_LOG_SCOPE_MISMATCH'),
                 (log(status=2), 'COUPON_LOG_STATE_UNKNOWN'), (log(status='x'), 'COUPON_LOG_STATE_UNKNOWN'), (log(use_time='2026-11-17 08:00:00'), 'COUPON_USE_TIME_SCOPE_MISMATCH'),
                 (log(use_time='2026-11-16 07:59:59'), 'COUPON_USE_TIME_SCOPE_MISMATCH'), (log(use_time='bad'), 'COUPON_USE_TIME_SCOPE_MISMATCH')]
        for row, code in cases:
            with self.subTest(code=code, row=row), self.assertRaisesRegex(ContractError, code):
                self.summary([row], [order('D1')])
        with self.assertRaisesRegex(ContractError, 'PAYMENT_STATE_UNKNOWN'):
            self.summary([log('D1')], [order('D1', pay_status=7)])

    def test_a_logged_order_missing_from_admin_falls_back_to_the_log_status_and_amount(self):
        value = self.summary([log('D9'), log('D8', id=2, status=0)], [])
        self.assertEqual((value['totals']['used_orders'], value['totals']['paid_orders'], value['totals']['unpaid_orders']), (2, 1, 1))
        self.assertEqual(value['totals']['paid_usd_minor'], 11952)
        self.assertEqual(value['totals']['discount_usd_minor'], 1008)
        self.assertEqual((value['coverage']['orders_unmatched'], value['coverage']['amounts_from_log']), (2, 1))
        with self.assertRaisesRegex(ContractError, 'COUPON_LOG_AMOUNT_INVALID'):
            self.summary([log('D9', order=dict(amount='?'))], [])

    def test_unpaid_log_with_a_paid_order_counts_as_paid_and_refund_comes_from_the_order(self):
        value = self.summary([log('D1', status=0)], [order('D1', pay_status=2)])
        self.assertEqual((value['totals']['paid_orders'], value['totals']['refunded_orders'], value['totals']['unpaid_orders']), (1, 1, 0))

    def test_repurchase_is_admin_90_day_figures_of_paid_uses_only(self):
        value = self.summary([log('D1', repurchase_count=2, repurchase_amount='35.17'),
                              log('D2', id=2, repurchase_count=1, repurchase_amount='22.60', status=0)],
                             [order('D1'), order('D2', pay_status=0)])
        self.assertEqual((value['totals']['repurchase_orders'], value['totals']['repurchase_usd_minor']), (2, 3517))
        none = self.summary([log('D1', repurchase_count=0, repurchase_amount='0.00')], [order('D1')])
        self.assertEqual((none['totals']['repurchase_orders'], none['totals']['repurchase_usd_minor']), (0, 0))

    def test_log_amounts_are_used_only_when_they_match_the_order(self):
        value = self.summary([log('D1', order=dict(before_discount='126.05', amount='1.00'))], [order('D1')])
        self.assertEqual(value['totals']['discount_usd_minor'], 0)
        self.assertEqual(value['totals']['paid_usd_minor'], 11952)

    def test_read_asks_for_exact_coupon_window_and_batches_orders(self):
        logs = [log('D%d' % i, id=i) for i in range(1, 86)]
        reader = Reader(logs=logs, orders=[order('D%d' % i) for i in range(1, 86)])
        value = read_coupon_usage(reader, self.request)
        self.assertEqual(value['totals']['used_orders'], 85)
        kinds = [c[0] for c in reader.calls]
        self.assertEqual(kinds[:2], ['detail', 'coupon_logs'])
        self.assertEqual(kinds.count('orders'), 3)  # 85 orders in chunks of 40
        filters = dict((f[0], (f[1], f[2])) for f in reader.calls[1][1])
        self.assertEqual(filters['coupon_id'], ('=', FC_COUPON['id']))
        self.assertEqual(filters['use_time'], ('RANGE', '2026-11-16 08:00:00,2026-11-17 07:59:59'))

    def test_window_over_28_days_is_split(self):
        request = dict(self.request, **{'from': '2026-10-02', 'to': '2026-11-01'})
        reader = Reader()
        read_coupon_usage(reader, request)
        self.assertEqual([c[0] for c in reader.calls].count('coupon_logs'), 2)

    def test_other_activity_and_bad_windows_are_rejected(self):
        for request in [dict(self.request, activity='mmoexp-seasonal'), dict(self.request, **{'to': '2027-01-01'}), dict(self.request, site_id='267')]:
            with self.subTest(request=request), self.assertRaises(ContractError):
                read_coupon_usage(Reader(), request)

    def test_bridge_action_reads_through_the_factory_and_closes(self):
        reader = Reader(logs=[log('D1')], orders=[order('D1')])
        value = handle(self.request, reader_factory=lambda: reader)
        self.assertEqual(value['totals']['paid_orders'], 1)
        self.assertTrue(reader.closed)
        self.assertNotIn('D1', str(value))
        self.assertNotIn('member_id', str(value))


if __name__ == '__main__':
    unittest.main()

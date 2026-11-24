import unittest
from datetime import datetime, timedelta, timezone

from black_friday_orders import OrderHistory, OrderLookupError, lookup_order_history


EMAIL = 'member@example.test'
NOW = datetime(2026, 11, 24, 12)
SHANGHAI = timezone(timedelta(hours=8))


def order(ident, paid, status=101, **updates):
    created = datetime.fromisoformat(paid) if paid else NOW
    return dict({'id': ident, 'uid': 42, 'email': EMAIL, 'site_id': 266,
                 'timestamp': int(created.replace(tzinfo=SHANGHAI).timestamp()),
                 'paytime': paid, 'pay_status': 1, 'status': status}, **updates)


def page(rows, total=None):
    return {'code': 1, 'data': {'list': rows, 'total': len(rows) if total is None else total}}


class TestOrderHistory(unittest.TestCase):
    def test_paid_and_completed_use_all_games_and_inclusive_start(self):
        def fetch(path, query):
            self.assertEqual(path, '/admin/order.Order/index')
            self.assertEqual(query['quick_search'], EMAIL)
            self.assertEqual(query['search[0][val]'], '266')
            self.assertEqual(query['search[1][val]'], EMAIL)
            self.assertEqual(query['search[2][field]'], 'timestamp')
            self.assertEqual(query['search[2][operator]'], 'RANGE')
            self.assertEqual(query['search[2][val]'], '2025-11-24 12:00:00,2026-11-24 12:00:00')
            self.assertNotIn('gid', query.values())
            return page([
                order(5, 0, status=0, pay_status=0, uid=0),
                order(4, '2026-10-10 13:00:00', status=83, pay_status=2),
                order(3, '2026-10-05 13:00:00', status=21, gid=891),
                order(2, '2026-10-01 00:00:00', gid=1327),
                order(1, '2026-09-30 23:59:59'),
            ])

        self.assertEqual(lookup_order_history(' Member@EXAMPLE.test ', fetch=fetch, now=NOW),
                         OrderHistory(member_id=42, paid=2, completed=1))

    def test_empty_history_counts_as_zero_without_member_directory(self):
        def fetch(path, query):
            self.assertEqual(path, '/admin/order.Order/index')
            return page([])

        self.assertEqual(lookup_order_history(EMAIL, fetch=fetch, now=NOW), OrderHistory(None, 0, 0))
        with self.assertRaises(OrderLookupError):
            lookup_order_history(EMAIL, fetch=lambda *_: {'code': 401}, now=NOW)

    def test_guest_orders_can_count_without_member_id(self):
        rows = [order(1, '2026-10-20 09:00:00', uid=0)]
        self.assertEqual(lookup_order_history(EMAIL, fetch=lambda *_: page(rows), now=NOW),
                         OrderHistory(None, 1, 1))

    def test_does_not_treat_out_of_range_response_as_zero(self):
        with self.assertRaises(OrderLookupError):
            lookup_order_history(EMAIL, fetch=lambda *_: page([
                order(1, '2025-11-24 11:59:59')]), now=NOW)

    def test_older_orders_identify_member_without_affecting_reward(self):
        self.assertEqual(lookup_order_history(EMAIL, fetch=lambda *_: page([
            order(1, '2026-09-30 23:59:59')]), now=NOW), OrderHistory(42, 0, 0))

    def test_pagination_traverses_and_rejects_scope_drift_or_missing_rows(self):
        rows = [order(i, '2026-11-12 00:00:00') for i in range(51, 1, -1)]
        second = order(1, '2026-10-01 00:00:00', gid=891)

        def run(tail):
            return lookup_order_history(EMAIL, fetch=lambda _, query: (
                page(rows, 51) if query['page'] == 1 else tail), now=NOW)

        self.assertEqual(run(page([second], 51)), OrderHistory(42, 51, 51))
        self.assertEqual(run(page([dict(second, uid=43)], 51)), OrderHistory(None, 51, 51))
        for result in (page([], 51), page([second], 52), page([rows[-1]], 51),
                       page([dict(second, email='other@example.test')], 51),
                       page([dict(second, site_id=99)], 51)):
            with self.subTest(result=result), self.assertRaises(OrderLookupError):
                run(result)

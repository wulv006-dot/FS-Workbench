"""Regress the hourly Admin retry on real paging, without external requests."""
from copy import deepcopy
from contextlib import redirect_stderr
from io import StringIO
import json
from unittest.mock import patch
import unittest

import test_hourly_admin_ranges as fixture
from fc_pricing_v3 import business_source as source
from fc_pricing_v3 import daily

AdminFixture = fixture.AdminFixture
at = fixture.at


class FaultingAdmin(AdminFixture):
    def __init__(self, orders=(), *, faults=()):
        super().__init__(orders)
        self.faults = list(faults)
        self.calls = []

    def get_admin(self, path, **params):
        self.calls.append((path, deepcopy(params)))
        if self.faults:
            match, status, payload = self.faults[0]
            if match(path, params):
                self.faults.pop(0)
                return status, payload
        return super().get_admin(path, **params)


def order_page(page):
    return lambda path, params: path.endswith('.Order/index') and params['page'] == page


def coupon_page(path, params):
    return path.endswith('.MemberCouponLog/index')


def bad(status):
    return status, {'_raw': 'private-response-body'}


class HourlyAdminRetryTests(unittest.TestCase):
    inputs = fixture.HourlyAdminRangeTests.inputs
    row = fixture.HourlyAdminRangeTests.row

    @classmethod
    def setUpClass(cls):
        fixture.HourlyAdminRangeTests.setUpClass()
        cls.pages = staticmethod(fixture.HourlyAdminRangeTests.pages)

    def run_hourly(self, admin, window, now, prior, events):
        with patch.object(source, 'hourly_accounting', return_value=dict(archived={}, cost_source={})):
            return source.incremental_window_context(
                admin, self.pages, [window], at(now), prior,
                progress=lambda stage, event, **details: events.append((stage, event, details)),
            )

    def orders(self):
        return [self.row(i, '2026-11-19 23:59:59') for i in range(1001)]

    def test_second_page_502_is_retried_in_place_and_keeps_all_orders(self):
        window, prior = self.inputs()
        admin = FaultingAdmin(self.orders(), faults=[(order_page(2), *bad(502))])
        events = []
        result = self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, events)
        calls = [(path, params) for path, params in admin.calls if path.endswith('.Order/index')]
        self.assertEqual([params['page'] for _, params in calls], [1, 2, 2])
        self.assertEqual(calls[1], calls[2])
        self.assertEqual(len(result['state']['rows']), 1001)
        self.assertEqual(len({row['id'] for row in result['state']['rows'].values()}), 1001)
        self.assertIn(('admin_paging', 'retry', {'source': 'orders', 'http_status': 502}), events)
        self.assertNotIn('private-response-body', repr(events))

    def test_second_page_persistent_502_keeps_original_failure_and_state(self):
        window, prior = self.inputs()
        before = deepcopy(prior)
        admin = FaultingAdmin(self.orders(), faults=[(order_page(2), *bad(502)), (order_page(2), *bad(502))])
        events = []
        with self.assertRaisesRegex(ValueError, '^admin_page_failed$'):
            self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, events)
        calls = [params['page'] for path, params in admin.calls if path.endswith('.Order/index')]
        self.assertEqual(calls, [1, 2, 2])
        self.assertEqual(prior, before)
        self.assertFalse(admin.coupon_batches)
        self.assertEqual(events[-1], ('admin_paging', 'failed',
                         {'source': 'orders', 'reason': 'admin_page_failed', 'http_status': 502}))

    def test_non_502_and_business_failure_never_retry(self):
        for status in (401, 429, 500, 503, 200):
            with self.subTest(status=status):
                window, prior = self.inputs()
                admin = FaultingAdmin(self.orders(), faults=[(order_page(2), *bad(status))])
                events = []
                with self.assertRaisesRegex(ValueError, '^admin_page_failed$'):
                    self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, events)
                self.assertEqual([params['page'] for path, params in admin.calls
                                  if path.endswith('.Order/index')], [1, 2])
                self.assertFalse(any(event == 'retry' for _, event, _ in events))

    def test_transport_timeout_is_not_retried(self):
        window, prior = self.inputs()
        admin = FaultingAdmin(self.orders())
        original = admin.get_admin
        def get_admin(path, **params):
            if path.endswith('.Order/index') and params['page'] == 2:
                admin.calls.append((path, deepcopy(params)))
                raise TimeoutError('private transport details')
            return original(path, **params)
        admin.get_admin = get_admin
        events = []
        with self.assertRaises(TimeoutError):
            self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, events)
        self.assertEqual([params['page'] for path, params in admin.calls
                          if path.endswith('.Order/index')], [1, 2])
        self.assertFalse(any(event == 'retry' for _, event, _ in events))
        self.assertEqual(events[-1], ('admin_paging', 'failed',
                         {'source': 'orders', 'reason': 'source_timeout', 'http_status': None}))
        self.assertNotIn('private transport details', repr(events))

    def test_coupon_502_is_not_retried(self):
        window, prior = self.inputs()
        admin = FaultingAdmin([self.row(0, '2026-11-19 23:59:59')],
                              faults=[(coupon_page, *bad(502))])
        events = []
        with self.assertRaisesRegex(ValueError, '^admin_page_failed$'):
            self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, events)
        self.assertEqual(sum(path.endswith('.MemberCouponLog/index') for path, _ in admin.calls), 1)
        self.assertFalse(any(event == 'retry' for _, event, _ in events))

    def test_duplicate_ids_still_fail_after_page_retry(self):
        window, prior = self.inputs()
        orders = self.orders()
        orders[-1]['id'] = orders[0]['id']
        admin = FaultingAdmin(orders, faults=[(order_page(2), *bad(502))])
        with self.assertRaisesRegex(ValueError, '^admin_duplicate_page$'):
            self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, [])
        self.assertEqual([params['page'] for path, params in admin.calls
                          if path.endswith('.Order/index')], [1, 2, 2])

    def test_only_one_extra_order_read_across_disjoint_ranges(self):
        window, prior = self.inputs(start='2026-11-18 13:15:00')
        admin = FaultingAdmin(faults=[(order_page(1), *bad(502)), (order_page(1), *bad(502))])
        # Second 502 occurs after the first retried request succeeded.
        first = True
        original = admin.get_admin
        def get_admin(path, **params):
            nonlocal first
            if first and path.endswith('.Order/index') and params['page'] == 1 and len(admin.calls) == 1:
                first = False
                saved = admin.faults.pop(0)
                try:
                    return original(path, **params)
                finally:
                    admin.faults.insert(0, saved)
            return original(path, **params)
        admin.get_admin = get_admin
        events = []
        with self.assertRaisesRegex(ValueError, '^admin_page_failed$'):
            self.run_hourly(admin, window, '2026-11-20 00:20:00', prior, events)
        order_calls = [(p, q) for p, q in admin.calls if p.endswith('.Order/index')]
        self.assertEqual(len(order_calls), 3)
        self.assertEqual(order_calls[0], order_calls[1])
        self.assertNotEqual(order_calls[1][1]['search[2][val]'], order_calls[2][1]['search[2][val]'])
        self.assertEqual(sum(event == 'retry' for _, event, _ in events), 1)


    def test_retry_progress_forwarding_accepts_only_orders_502_and_strips_details(self):
        reports = [
            dict(stage='admin_paging', event='retry', source='orders', http_status=502,
                 request='private request', order_no='private order', message='private body'),
            dict(stage='admin_paging', event='retry', source='coupons', http_status=502),
            dict(stage='admin_paging', event='retry', source='orders', http_status=401),
            dict(stage='admin_paging', event='retry', source='orders', http_status='502'),
            dict(stage='admin_paging', event='retry', source='orders', http_status=True),
            dict(stage='admin_paging', event='retry', source='orders', http_status=503),
            dict(stage='admin_paging', event='retry', source='other', http_status=502),
        ]
        stderr = StringIO()
        with redirect_stderr(stderr):
            daily.forward_hourly_timings('\n'.join(
                daily.HOURLY_TIMING_PREFIX + json.dumps(record) for record in reports
            ))
        lines = stderr.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(daily.HOURLY_TIMING_PREFIX))
        self.assertEqual(json.loads(lines[0][len(daily.HOURLY_TIMING_PREFIX):]),
                         dict(stage='admin_paging', event='retry', source='orders', http_status=502))


if __name__ == '__main__':
    unittest.main()

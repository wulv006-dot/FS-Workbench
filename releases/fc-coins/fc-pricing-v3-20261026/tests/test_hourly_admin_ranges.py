"""Exercise the hourly Admin range boundaries and original pagination."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_business_source
from fc_pricing_v3 import business_source as source


CHANNEL_SOURCE = (Path(__file__).resolve().parents[3]
                  / 'fs-dashboard/channel-effects-20261021/source/channel_source.py')


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=source.TZ)


class AdminFixture:
    def __init__(self, orders=(), *, empty_last_page=False):
        self.orders = sorted(orders, key=lambda row: int(row['id']), reverse=True)
        self.empty_last_page = empty_last_page
        self.order_pages = []
        self.coupon_batches = []

    def get_admin(self, path, *, page, limit, order, **params):
        assert order == 'id,desc'
        assert params['search[0][val]'] == '266'
        if path.endswith('.Order/index'):
            assert params['search[1][val]'] == '1327'
            assert limit == 1000
            begin, end = params['search[2][val]'].split(',')
            self.order_pages.append((begin, end, page))
            matched = [row for row in self.orders if begin <= row['paytime'] <= end]
            rows = matched[(page-1)*limit:page*limit]
            if self.empty_last_page and page > 1:
                rows = []
            total = len(matched)
        else:
            assert path.endswith('.MemberCouponLog/index')
            names = params['search[1][val]'].split(',')
            self.coupon_batches.append(names)
            rows = [dict(id='new-coupon', order_no='T0000', site_id=266, coupon_id='revised')] if 'T0000' in names else []
            total = len(rows)
        return 200, {'code':1,'data':{'total':total,'list':rows}}


class HourlyAdminRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('hourly_admin_native_paging', CHANNEL_SOURCE)
        channel = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(CHANNEL_SOURCE.parent), *sys.path]):
            spec.loader.exec_module(channel)
        cls.pages = staticmethod(channel.pages)

    def inputs(self, start='2026-11-19 13:15:00', cursor='2026-11-20 00:01:00'):
        _, self.template, window = test_business_source.BusinessSourceTest().window_fixture()
        window['opened_at'] = at(start).isoformat()
        prior = dict(cursor_at=at(cursor).isoformat(), rows={},
                     coupon_logs={'T0000':[dict(coupon_id='old')]}, rechecked_days={})
        return window, prior

    def row(self, index, paid):
        created = at(paid) - timedelta(seconds=60)
        return dict(self.template, id=str(index+1), order_no=f'T{index:04d}',
                    timestamp=int(created.timestamp()), timestamp_format=created.isoformat(sep=' '),
                    paytime=paid, status=0, status_format='处理中')

    def refresh(self, admin, window, now, prior):
        with patch.object(source, 'hourly_accounting', return_value=dict(archived={}, cost_source={})):
            return source.incremental_window_context(admin, self.pages, [window], at(now), prior)

    def test_midnight_orders_keep_deep_paging_and_coupon_rechecks(self):
        window, prior = self.inputs()
        now = '2026-11-20 00:20:00'
        orders = [self.row(index, '2026-11-19 23:59:59') for index in range(1000)]
        orders.append(self.row(1000, '2026-11-20 00:00:00'))
        admin = AdminFixture(orders)
        result = self.refresh(admin, window, now, prior)
        self.assertEqual(len(result['state']['rows']), 1001)
        self.assertEqual([name for batch in admin.coupon_batches for name in batch],
                         [f'T{index:04d}' for index in range(1001)])
        self.assertEqual(result['state']['coupon_logs']['T0000'][0]['coupon_id'], 'revised')
        self.assertEqual(admin.order_pages, [
            ('2026-11-19 13:15:00', now, 1), ('2026-11-19 13:15:00', now, 2)])

    def test_non_consecutive_days_keep_the_gap(self):
        window, prior = self.inputs(start='2026-11-18 13:15:00')
        now = '2026-11-20 00:20:00'
        admin = AdminFixture()
        self.refresh(admin, window, now, prior)
        self.assertEqual(admin.order_pages, [
            ('2026-11-18 13:15:00', '2026-11-18 23:59:59', 1),
            ('2026-11-20 00:00:00', now, 1)])

    def test_continuous_days_keep_native_28_day_limit(self):
        window, prior = self.inputs(start='2026-11-01 13:15:00', cursor='2026-11-29 00:01:00')
        rows = [self.row(index, f'2026-11-{index+1:02d} 14:00:00') for index in range(28)]
        prior['rows'] = {row['id']:row for row in rows}
        now = '2026-11-29 00:20:00'
        admin = AdminFixture(rows)
        self.refresh(admin, window, now, prior)
        self.assertEqual(admin.order_pages, [
            ('2026-11-01 13:15:00', '2026-11-28 23:59:59', 1),
            ('2026-11-29 00:00:00', now, 1)])

    def test_incomplete_joined_page_keeps_original_state(self):
        window, prior = self.inputs()
        orders = [self.row(index, '2026-11-19 23:59:59') for index in range(1000)]
        orders.append(self.row(1000, '2026-11-20 00:00:00'))
        admin = AdminFixture(orders, empty_last_page=True)
        before = deepcopy(prior)
        with self.assertRaisesRegex(ValueError, '^admin_incomplete_pages$'):
            self.refresh(admin, window, '2026-11-20 00:20:00', prior)
        self.assertEqual(prior, before)
        self.assertEqual(admin.coupon_batches, [])

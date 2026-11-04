"""Reuse the current MMOEXP Admin native summary, including its customer_price."""
import datetime as dt
import sys

from .contracts import game, make_daily_context, GAME_IDS, SITE_ID
from .metrics import number
from .sources import SourceError


class NativeSummaryReader:
    def __init__(self, clock=lambda: dt.datetime.now(dt.timezone.utc)):
        self.clock, self.calls = clock, 0

    def __call__(self, scope, day):
        game(scope)
        if not make_daily_context(self.clock()).publication_allowed:
            raise SourceError('NIGHT_DEADLINE')
        sys.path[:0] = [p for p in ('/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc', '/opt/sales-dashboard/collector') if p not in sys.path]
        from site_summary import collect
        self.calls += 1
        return collect(dict(profile=scope, profit_site='main', period=dict(start=day+' 00:00', end=day+' 23:59')),
                       ('', '', '', GAME_IDS[scope]))


class AdminSummarySource:
    name = 'admin'
    timezone = 'Asia/Shanghai'

    def __init__(self, read):
        self.read = read

    def pages(self, scope, day, cursor=0):
        game(scope)
        dt.date.fromisoformat(day)
        if cursor:
            raise SourceError('ADMIN_SUMMARY_CURSOR_INVALID')
        value = self.read(scope, day)
        filters = value.get('filters', {})
        if (value.get('status') != 'available' or value.get('normalisedScope') != 'main-website'
            or value.get('currency') != 'USD' or str(filters.get('site')) != SITE_ID
            or str(filters.get('game')) != GAME_IDS[scope] or str(filters.get('pay_status')) != '1'
            or value.get('period') != dict(start=day+' 00:00', end=day+' 23:59')):
            raise SourceError('ADMIN_SUMMARY_SCOPE_MISMATCH')
        metrics = value.get('metrics', {})
        def native(key, field=None):
            item = metrics.get(key, {})
            if item.get('status') != 'available' or item.get('value') is None:
                return None
            if field and item.get('field') != field:
                raise SourceError('ADMIN_NATIVE_PRICE_FIELD_MISMATCH')
            return str(number(item['value']))
        projected = dict(paid_orders=native('orders'), paid_revenue_usd=native('revenueUsd'),
                         admin_customer_price_usd=native('averageCustomerUsd', 'customer_price'))
        if projected['paid_orders'] is None or projected['paid_revenue_usd'] is None:
            raise SourceError('ADMIN_SUMMARY_REQUIRED_METRIC_MISSING')
        yield dict(rows=[dict(key=day, metrics=projected)], next_cursor=None,
                   source_timezone=self.timezone, status='available',
                   quality=dict(pagination_complete=True, payment_basis='admin_pay_status_1',
                                price_field='customer_price', price_basis='native_paying_customer_mean',
                                endpoint=value.get('endpoint'), currency='USD'))

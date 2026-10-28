"""Native predicates imply active(); remaining FC rules stay in original normalize()."""
import importlib.util
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

RELEASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE / 'source'))
import pricing_sources


def real_channel():
    path = RELEASE.parents[1] / 'fs-dashboard/channel-effects-20261021/source/channel_source.py'
    spec = importlib.util.spec_from_file_location('filtered_real_channel_source', path)
    module = importlib.util.module_from_spec(spec)
    effects = SimpleNamespace(**{name: None for name in (
        'Attribution', 'EMPTY_COST', 'SITE', 'TZ', 'delivery_index', 'normalize', 'money')})
    with patch.dict(sys.modules, {'channel_effects': effects}):
        spec.loader.exec_module(module)
    return module


NOW = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)


def discount(ident, **changes):
    return dict(dict(id=ident, status='1', site_id='266', gid='1327', exclude_gids='0',
                     type='1', discount='90', timestart='0', timeend='0'), **changes)


def coupon(ident, **changes):
    return dict(dict(id=ident, status='1', site_id='266', game_id='1327', product_type='1',
                     type='1', mode_type='2', is_open='0', reduce='70', time_effect='2',
                     start_time='0', end_time='1', fetch_qty='0', used_qty='0', fetch_scene='1'), **changes)


def fixtures():
    discounts = [discount('fc'), discount('global', site_id=0, gid=0),
        discount('list', gid='999,1327'), discount('inactive', status='0', type='unsupported'),
        discount('other_site', site_id='999', type='unsupported'),
        discount('excluded', exclude_gids='1327'), discount('other_game', gid='999'),
        discount('json_gid', gid='[1327]'), discount('expired', timeend='1')]
    coupons = [coupon('fc'), coupon('global', site_id=0, game_id=0, product_type='0'),
        coupon('list', game_id='999,1327'), coupon('inactive', status='0', type='unsupported'),
        coupon('other_site', site_id='999', type='unsupported'), coupon('other_game', game_id='999'),
        coupon('other_product', product_type='2'), coupon('json_gid', game_id='[1327]'),
        coupon('absolute_expired', time_effect='1'),
        coupon('unissued', fetch_scene='4', mode_type='1'),
        coupon('1259', title='Compensation coupon', fetch_scene='4', mode_type='1',
               fetch_qty='10', used_qty='1', reduce='5')]
    goods, storefront = [], dict(rows={})
    for ident, platform in enumerate(('PS', 'XBOX', 'PC'), 1):
        goods.append(dict(id=str(ident), mid=str(10+ident), site_id='266', gid='1327',
            top_cid='1', unit='K', status='1', discount='100', unit_price='0.0738',
            more=dict(gold=['100'], give=['5'], discount=['100'])))
        storefront['rows'][platform] = dict(sku_id=str(ident), bonus_k='5', package_usd='7.38')
    return discounts, coupons, goods, storefront


class Session:
    def __init__(self, discounts, coupons, goods, fail=None):
        self.tables = dict(Discount=discounts, Coupon=coupons, Goods=goods)
        self.calls, self.fail, self.closed = [], fail, False

    def bind_admin_token(self, token):
        return True

    def close(self):
        self.closed = True

    def get_admin(self, path, **params):
        self.calls.append((path, params))
        kind = path.split('.')[-1].split('/')[0]
        rows = deepcopy(self.tables[kind])
        for i in range(10):
            field = params.get('search[%d][field]' % i)
            if field is None:
                break
            operator, val = params['search[%d][operator]' % i], params['search[%d][val]' % i]
            values = str(val).split(',') if operator == 'IN' else [str(val)]
            rows = [row for row in rows if str(row[field]) in values]
        total = len(rows)
        start = (params['page']-1)*params['limit']
        rows = rows[start:start+params['limit']]
        if self.fail == 'missing' and kind == 'Coupon' and params['page'] == 2:
            rows = []
        return 200, dict(code=401 if self.fail == 'denied' and kind == 'Coupon' else 1,
                         data=dict(list=rows, total=total))


class PromotionScopeFilters(unittest.TestCase):
    def collect(self, session, storefront):
        auth = SimpleNamespace(Session=lambda: session, admin_token_from_service=lambda: ('fixture', ''))
        normalize = pricing_sources.normalize
        with patch.dict(sys.modules, {'channel_source': real_channel(), 'p2pah_auth': auth}), \
                patch.object(pricing_sources, 'normalize', side_effect=lambda d, c, g, s: normalize(d, c, g, s, now=NOW)):
            return pricing_sources._collect_shared_admin(storefront, persist=False)

    def test_actual_pages_to_original_normalize_is_exactly_equivalent(self):
        discounts, coupons, goods, storefront = fixtures()
        expected = pricing_sources.normalize(discounts, coupons, goods, storefront, now=NOW)
        session = Session(discounts, coupons, goods)
        actual = self.collect(session, storefront)
        self.assertEqual(actual, expected)
        self.assertEqual(actual['code_count'], 3)
        self.assertEqual(actual['coupon_count'], 3)
        self.assertEqual({r['id'] for r in actual['coupons']}, {'fc', 'global', 'list'})
        self.assertEqual([r['id'] for r in actual['unissued_directed_templates']], ['unissued'])
        self.assertEqual([r['id'] for r in actual['after_sales_compensation']], ['1259'])
        self.assertEqual(set(actual['packages']), {'PS', 'XBOX', 'PC'})
        for path, params in session.calls:
            self.assertEqual(params['limit'], 200)
            if 'market.' in path:
                self.assertEqual(params['search[0][field]'], 'status')
                self.assertEqual(params['search[0][val]'], '1')
                self.assertEqual(params['search[1][field]'], 'site_id')
                self.assertEqual(params['search[1][operator]'], 'IN')
                self.assertEqual(params['search[1][val]'], '0,266')
                self.assertNotIn('search[2][field]', params)
        self.assertTrue(session.closed)

    def test_global_relative_coupons_keep_expired_dates_and_zero_quota_semantics(self):
        row = coupon('relative', site_id=0, game_id='999,1327', end_time='1', fetch_qty='0')
        self.assertTrue(pricing_sources.active(row, NOW, coupon=True))
        self.assertFalse(pricing_sources.active(dict(row, time_effect='1'), NOW, coupon=True))
        for changes in (dict(status='0'), dict(site_id='999')):
            self.assertFalse(pricing_sources.active(dict(row, **changes), NOW, coupon=True))

    def test_filtered_results_larger_than_one_default_page_remain_complete(self):
        discounts, coupons, goods, storefront = fixtures()
        coupons = [coupon(str(i)) for i in range(401)]
        session = Session(discounts, coupons, goods)
        result = self.collect(session, storefront)
        self.assertEqual(result['coupon_count'], 401)
        self.assertEqual([p['page'] for path, p in session.calls if 'Coupon' in path], [1, 2, 3])
        self.assertEqual(result, pricing_sources.normalize(discounts, coupons, goods, storefront, now=NOW))

    def test_incomplete_filtered_pages_cannot_become_verified(self):
        discounts, coupons, goods, storefront = fixtures()
        session = Session(discounts, [coupon(str(i)) for i in range(401)], goods, 'missing')
        with self.assertRaisesRegex(ValueError, 'admin_incomplete_pages'):
            self.collect(session, storefront)
        self.assertTrue(session.closed)

    def test_filtered_permission_failure_cannot_become_empty_success(self):
        discounts, coupons, goods, storefront = fixtures()
        with self.assertRaisesRegex(ValueError, 'admin_page_failed'):
            self.collect(Session(discounts, coupons, goods, 'denied'), storefront)


if __name__ == '__main__':
    unittest.main()

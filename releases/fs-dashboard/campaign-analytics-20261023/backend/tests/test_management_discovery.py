import json
import unittest

from bridge import handle
from campaign_backend.adapters import AdminRead, payment_observation
from campaign_backend.catalog import discover_product, read_product_metadata
from campaign_backend.core import ContractError


def goods(**changes):
    row = dict(id=170014917, site_id=266, gid=1327, mid=43167385, aid=21587,
        sid=7645, cid=9627, title='Example Player', min_qty=1, unit='', sku_switch=0,
        attr_switch=1, status=1, buy_status=0, price='SECRET_PRICE', cost='SECRET_COST',
        more={'saleprop': [], 'skuTableSet': [], 'internal_cost': 'SECRET_NESTED'})
    row.update(changes)
    return row


def model(**changes):
    row = dict(id=43167385, gid=1327, title='Example Model',
               more={'saleprop': [], 'skuTableSet': [], 'private': 'SECRET_MODEL'})
    row.update(changes)
    return row


def response(rows, total):
    return 200, {'code': 1, 'data': {'list': rows, 'total': total}}


def detail(row):
    return 200, {'code': 1, 'data': {'row': row}}


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def get_admin(self, route, **params):
        self.calls.append((route, params))
        return next(self.responses)

    def close(self):
        self.closed = True


class DiscoveryTests(unittest.TestCase):
    def test_discovery_uses_verified_fields_beyond_baseline_without_manual_map(self):
        fresh = goods(id=99999999, title='New Product')
        result = handle({'action': 'catalog_discover', 'site_id': '266', 'game_id': 1327},
                        lambda: AdminRead(Session([response([fresh], 1)])))
        self.assertEqual(result['products'][0]['product_ref']['goods_id'], '99999999')
        self.assertEqual(result['products'][0]['unit'], '')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['completeness'], 'complete')
        self.assertFalse(result['checkout_enabled'])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertTrue(result['products'][0]['purchase_mapping_required'])

    def test_all_pages_are_read_with_concrete_site_and_game_filters(self):
        first = [goods(id=1000 + n) for n in range(100)]
        session = Session([response(first, 101), response([goods(id=2000)], 101)])
        result = handle({'action': 'catalog_discover', 'site_id': '266', 'game_id': '1327'},
                        lambda: AdminRead(session))
        self.assertEqual(result['total'], 101)
        self.assertEqual(session.calls[1][1]['page'], 2)
        self.assertEqual(session.calls[0][1]['search[0][val]'], '266')
        self.assertEqual(session.calls[0][1]['search[1][val]'], '1327')
        self.assertTrue(session.closed)

    def test_invalid_scope_rejected_before_session_and_all_sites_never_queried(self):
        for request in ({'site_id': '0', 'game_id': '1327'},
                        {'site_id': '266', 'game_id': 0},
                        {'site_id': '266', 'game_id': True},
                        {'site_id': '266', 'game_id': '-1'}):
            with self.assertRaises(ContractError):
                handle(dict(request, action='catalog_discover'), lambda: self.fail('no session'))

    def test_unknown_switch_or_wrong_returned_scope_fails_closed(self):
        for row in (goods(site_id=0), goods(gid=99), goods(sku_switch=2), goods(attr_switch=True)):
            session = Session([response([row], 1)])
            with self.assertRaises(ContractError):
                handle({'action': 'catalog_discover', 'site_id': '266', 'game_id': '1327'},
                       lambda: AdminRead(session))
            self.assertTrue(session.closed)

    def test_product_read_validates_goods_then_related_model_scope(self):
        session = Session([detail(goods()), detail(model())])
        result = handle(dict(action='product_read', site_id='266', game_id='1327', goods_id='170014917'),
                        lambda: AdminRead(session))
        product = result['product']
        self.assertFalse(product['purchase_mapping_required'])
        self.assertEqual(product['attr_switch'], 1)
        self.assertEqual(product['model_title'], 'Example Model')
        self.assertFalse(product['authoritative'])
        self.assertFalse(product['checkout_enabled'])
        self.assertNotIn('SECRET', json.dumps(product))
        self.assertEqual(session.calls[1], ('/admin/goods.GoodsMould/edit', {'id': '43167385'}))

    def test_wrong_goods_scope_does_not_fetch_model_or_disclose_metadata(self):
        session = Session([detail(goods(site_id=0))])
        with self.assertRaisesRegex(ContractError, 'PRODUCT_SCOPE_MISMATCH'):
            handle(dict(action='product_read', site_id='266', game_id='1327', goods_id='170014917'),
                   lambda: AdminRead(session))
        self.assertEqual(len(session.calls), 1)

    def test_model_mismatch_fails_even_when_goods_scope_is_correct(self):
        for bad in (model(id=99), model(gid=99)):
            with self.assertRaises(ContractError):
                handle(dict(action='product_read', site_id='266', game_id='1327', goods_id='170014917'),
                       lambda: AdminRead(Session([detail(goods()), detail(bad)])))

    def test_unknown_nonempty_specs_are_bounded_metadata_without_prices_or_fake_ids(self):
        raw = goods(sku_switch=1, more={'saleprop': [{'unexpected': 'SECRET_SPEC', 'price': 'SECRET_PRICE'}],
                                      'skuTableSet': [{'cost': 'SECRET_SKU'}]})
        product = read_product_metadata(model(), raw, '266', '1327')
        self.assertTrue(product['purchase_mapping_required'])
        self.assertEqual(product['specification_sources']['goods']['saleprop']['entry_count'], 1)
        self.assertIn('SKU_SELECTION_MAPPING_REQUIRED', product['purchase_mapping_reasons'])
        self.assertNotIn('SECRET', json.dumps(product))

    def test_absent_or_wrong_type_specs_do_not_claim_purchase_mapping_complete(self):
        for raw in (goods(more={}), goods(more=None), goods(more={'saleprop': 'unknown'})):
            product = read_product_metadata(model(more={}), raw, '266', '1327')
            self.assertTrue(product['purchase_mapping_required'])

    def test_zero_optional_reference_retains_real_value_without_inventing_platform(self):
        product = discover_product(goods(aid=0, sid=0, cid=0), '266', '1327')
        self.assertEqual(product['platform_attribute_id'], '0')
        self.assertEqual(product['server_id'], '0')
        self.assertTrue(product['purchase_mapping_required'])


class PaymentObservationTests(unittest.TestCase):
    def test_current_ui_paid_enum_one_without_money_or_customer_leak(self):
        for value in (1, '1'):
            row = dict(site_id=266, order_no='order-1', pay_status=value,
                paytime='2026-10-24 17:00:00', email='SECRET_EMAIL', amount_usd_format='SECRET_AMOUNT')
            result = payment_observation(row, '266')
            self.assertEqual(result['payment_state'], 'paid')
            self.assertEqual(result['refund_state'], 'unknown')
            self.assertFalse(result['attribution_ready'])
            self.assertNotIn('SECRET', json.dumps(result))

    def test_other_paid_enums_are_unknown_and_refunds_never_inferred(self):
        for value in (0, 2, 99, 'refunded'):
            result = payment_observation(dict(site_id=266, order_no='A', pay_status=value,
                paytime='2026-10-24 17:00:00'), '266')
            self.assertEqual(result['payment_state'], 'unknown')
            self.assertEqual(result['refund_state'], 'unknown')

    def test_wrong_scope_unknown_type_and_missing_time_fail(self):
        base = dict(site_id=266, order_no='A', pay_status=1, paytime='2026-10-24 17:00:00')
        for changes in ({'site_id': 0}, {'pay_status': True}, {'pay_status': None}, {'paytime': None}):
            with self.assertRaises(ContractError):
                payment_observation(dict(base, **changes), '266')


if __name__ == '__main__':
    unittest.main()

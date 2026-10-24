import json
import contextlib
import io
import unittest
from dataclasses import replace
from unittest.mock import patch

from campaign_backend.adapters import AdminRead
from campaign_backend.catalog import CatalogMapping, project_product
from campaign_backend.core import ContractError
from bridge import benefit_projection, handle, main


class Session:
    def __init__(self, pages):
        self.responses = iter(pages)
        self.calls = []
        self.closed = False

    def get_admin(self, route, **params):
        self.calls.append((route, params))
        return next(self.responses)

    def close(self):
        self.closed = True


def page(rows, total):
    return 200, {'code': 1, 'data': {'list': rows, 'total': total}}


class ReadTests(unittest.TestCase):
    def test_full_pagination_not_first_page(self):
        session = Session([page([{'id': 1}], 2), page([{'id': 2}], '2')])
        self.assertEqual([r['id'] for r in AdminRead(session).pages('coupons', limit=1)], [1, 2])
        self.assertEqual(session.calls[1][1]['page'], 2)

    def test_duplicate_changed_and_partial_pages_fail(self):
        for responses in ([page([{'id': 1}], 2), page([{'id': 1}], 2)],
                          [page([{'id': 1}], 2), page([{'id': 2}], 3)],
                          [page([{'id': 1}], 2), page([], 2)]):
            with self.assertRaises(ContractError):
                AdminRead(Session(responses)).pages('goods', limit=1)

    def test_route_allowlist_and_scope_enforced(self):
        session = Session([])
        with self.assertRaisesRegex(ContractError, 'READ_ROUTE_NOT_ALLOWED'):
            AdminRead(session).pages('/admin/market.Coupon/add')
        self.assertEqual(session.calls, [])
        session = Session([page([{'id': 1, 'site_id': 0, 'paytime': '2026-10-24'}], 1)])
        with self.assertRaisesRegex(ContractError, 'UPSTREAM_SCOPE_MISMATCH'):
            AdminRead(session).orders('266', '2026-10-01', '2026-11-01')

    def test_raw_upstream_errors_do_not_escape(self):
        with self.assertRaisesRegex(ContractError, '^UPSTREAM_UNAVAILABLE$'):
            AdminRead(Session([(401, {'token': 'secret', 'msg': 'sensitive'})])).pages('coupons')

    def test_detail_id_must_match(self):
        session = Session([(200, {'code': 1, 'data': {'row': {'id': 2}}})])
        with self.assertRaisesRegex(ContractError, 'DETAIL_ID_MISMATCH'):
            AdminRead(session).detail('goods', '1')

    def test_shared_token_reuse_without_login(self):
        class Shared(Session):
            def bind_admin_token(self, token):
                self.bound = token
                return True
        session = Shared([])
        reader = AdminRead.from_shared_session(lambda: session, lambda: ('test-only', None))
        self.assertEqual(session.bound, 'test-only')
        reader.close()
        self.assertTrue(session.closed)
        with self.assertRaisesRegex(ContractError, 'SHARED_ADMIN_UNAVAILABLE'):
            AdminRead.from_shared_session(lambda: session, lambda: (None, 'unavailable'))

    def test_coupon_log_order_scope_checked(self):
        session = Session([page([dict(id=1, site_id=266, order_no='other')], 1)])
        with self.assertRaisesRegex(ContractError, 'UPSTREAM_SCOPE_MISMATCH'):
            AdminRead(session).coupon_logs('266', ['expected'])


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.model = {'id': 10, 'title': 'Example Player', 'internal_cost': 'secret'}
        self.goods = {'id': 20, 'mid': 10, 'gid': 1327, 'site_id': 266, 'aid': 21587,
                      'price': '85.50', 'currency': 'USD', 'status': 1, 'attr_switch': 1, 'sku_switch': 1}
        self.mapping = CatalogMapping('fixture-only',
            dict(site_id='site_id', game_id='gid', model_id='mid', goods_id='id',
                 platform_attribute_id='aid', price='price', currency='currency', sale_state='status'),
            dict(model_id='id', title='title'), ((1, True), (0, False)), {'USD': 2})
        self.purchase = dict(platform=dict(code='ps', attribute_id='21587', label='PlayStation'),
            quantity=dict(unit='item', minimum=1, step=1, group='1'),
            attributes=[dict(attribute_id='spec', required=True, values=[dict(value_id='v1', label='Version 1')])],
            captured_at='2026-10-24T09:00:00+00:00', catalog_version='v1', verification_ref='fixture-only')

    def test_explicit_specs_and_separate_namespaces_public_projection(self):
        product = project_product(self.model, self.goods, self.mapping, self.purchase)
        self.assertEqual(product['product_ref']['model_id'], '10')
        self.assertEqual(product['product_ref']['goods_id'], '20')
        self.assertNotIn('sku_id', product['product_ref'])
        self.assertEqual(product['attributes'][0]['values'][0]['value_id'], 'v1')
        self.assertFalse(product['authoritative'])
        self.assertNotIn('secret', json.dumps(product))

    def test_wrong_model_site_platform_or_unknown_status_fails(self):
        for changes in ({'mid': 99}, {'site_id': 0}, {'aid': 999}, {'status': 99}, {'id': None}):
            with self.assertRaises(ContractError):
                project_product(self.model, dict(self.goods, **changes), self.mapping, self.purchase)

    def test_explicit_currency_constant_supported_without_assuming_usd(self):
        fields = dict(self.mapping.goods_fields)
        del fields['currency']
        mapping = replace(self.mapping, goods_fields=fields, currency_code='USD')
        self.assertEqual(project_product(self.model, self.goods, mapping, self.purchase)['price']['minor'], 8550)
        with self.assertRaises(ContractError):
            project_product(self.model, self.goods, replace(mapping, currency_code=None), self.purchase)

    def test_unverified_specs_or_url_credentials_fail(self):
        for purchase in (dict(self.purchase, attributes=None),
                         dict(self.purchase, image_url='https://token:secret@assets.example/img.png')):
            with self.assertRaises(ContractError):
                project_product(self.model, self.goods, self.mapping, purchase)


class BridgeTests(unittest.TestCase):
    def test_capabilities_never_claim_code_is_real_verification(self):
        result = handle({'action': 'capabilities'}, lambda: self.fail('No session for capabilities'))
        self.assertFalse(any(result['capabilities'].values()))

    def test_benefit_projection_drops_code_param_code_and_nested_data(self):
        row = dict(id=1, title='Example', status=1, site_id='266', code='private-code',
                   param_code='private-param', customer_email='private-email', game={'secret': 1})
        projected = benefit_projection(row, 'coupons')
        self.assertEqual(projected['raw_status'], 1)
        self.assertEqual(projected['status_semantics'], 'unknown')
        self.assertNotIn('private', json.dumps(projected))

    def test_cli_json_only_and_no_raw_request_echo(self):
        def invoke(request):
            output = io.StringIO()
            with patch('sys.stdin', io.TextIOWrapper(io.BytesIO(request.encode('utf-8')))), contextlib.redirect_stdout(output):
                main()
            return json.loads(output.getvalue())
        self.assertEqual(invoke('{"action":"capabilities"}')['status'], 'ok')
        self.assertEqual(invoke('{"action":"write","token":"secret"}'),
                         {'status': 'error', 'error': 'ACTION_NOT_ALLOWED'})


if __name__ == '__main__':
    unittest.main()

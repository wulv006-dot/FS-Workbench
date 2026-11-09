from copy import deepcopy
import json
import unittest

from fs_mcp_connector.backend import Backend, BackendError
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, ValidationError
from fs_mcp_connector.evolutions import project
from fs_mcp_connector.portal import Principal


class EvolutionsTests(unittest.TestCase):
    def state(self):
        return dict(version='existing-version', stale=False, writable=True, blocked=True,
            cache_pending=True, next_auto_at=1234,
            config=dict(revision=4, automatic=True, premium='1.10', interval_minutes=120,
                overrides={'12': dict(enabled=False, coins='100000', premium='1.20',
                    prices={'PS': '12.34', 'XBOX': '12.34', 'PC': '13.45'})}),
            snapshot=dict(at=100, models=[dict(id=12, gid=1327, cid=9, title='Evolution', unit='100000',
                status=1, sku_switch=0, attr_switch=0, password='raw-secret')],
                products=[dict(id=22, gid=1327, cid=9, mid=12, aid=1, site_id=0, sid=7645, top_cid=2,
                    title='Evolution', price='12.34', unit_price='12.34', discount='0', unit='100000',
                    num=1, status=1, sku_switch=0, attr_switch=0, access_token='raw-secret')],
                rates={'PS': '1.01', 'XBOX': '1.01', 'PC': '1.02'}, authorization='raw-secret'),
            rows=[dict(model_id=12, product_id=22, cid=9, title='Evolution', platform='PS', coins='100000',
                model_coins='100000', premium='1.10', rate='1.01', current='12.34', target='12.50',
                fixed=None, enabled=True, error='ALL三平台产品缺失或重复')],
            job=dict(id='job-1', action='apply', actor='alice', at=100, finished_at=120, status='needs_review',
                results=[dict(product_id=22, action='unknown', operation_id='job-1-22')],
                error='raw-opaque-sensitive-body', payload={'cookie': 'raw-secret'}),
            history=[dict(id='job-0', action='refresh', actor='alice', at=90, status='failed',
                results=[dict(product_id=20, action='skipped_invalid', error='模型或产品已禁用')], error='raw-secret')])

    def test_config_snapshot_and_task_business_values_are_preserved_without_backend_payload(self):
        original = self.state()
        unchanged = deepcopy(original)
        value = project(original)
        self.assertEqual(value['config'], original['config'])
        for name in ('version', 'stale', 'writable', 'blocked', 'cache_pending', 'next_auto_at', 'rows'):
            self.assertEqual(value[name], original[name])
        self.assertEqual(value['snapshot']['models'][0]['unit'], '100000')
        self.assertEqual(value['snapshot']['products'][0]['unit_price'], '12.34')
        self.assertEqual(value['snapshot']['rates'], original['snapshot']['rates'])
        self.assertEqual(value['job']['status'], 'needs_review')
        self.assertEqual(value['job']['results'], original['job']['results'])
        self.assertTrue(value['job']['error_present'])
        self.assertTrue(value['job']['error_detail_withheld'])
        self.assertEqual(value['history'][0]['results'][0]['error'], '模型或产品已禁用')
        self.assertNotIn('raw-secret', json.dumps(value))
        self.assertNotIn('raw-opaque-sensitive-body', json.dumps(value))
        self.assertEqual(original, unchanged)

    def test_empty_state_preserves_none_and_missing_without_fabricating_fresh_results(self):
        value = project(dict(config={}, snapshot=None, job=None, history=[], blocked=False, rows=[], stale=True))
        self.assertIsNone(value['snapshot'])
        self.assertIsNone(value['job'])
        self.assertEqual(value['rows'], [])
        self.assertTrue(value['stale'])
        self.assertNotIn('next_auto_at', value)

    def test_unknown_error_text_is_not_returned_even_in_row_or_result(self):
        original = self.state()
        original['rows'][0]['error'] = 'upstream-secret-body'
        original['history'][0]['results'][0]['error'] = 'other-opaque-secret'
        value = project(original)
        self.assertTrue(value['rows'][0]['error_detail_withheld'])
        self.assertNotIn('upstream-secret-body', json.dumps(value))
        self.assertNotIn('other-opaque-secret', json.dumps(value))

    def test_actual_registered_state_route_and_current_permission(self):
        calls, allowed = [], [200]
        catalog = Catalog(lambda *args: allowed[0])
        def transport(*args):
            calls.append(args)
            return 200, json.dumps(self.state()).encode()
        backend = Backend(catalog, 'https://fs.example', transport=transport)
        principal = Principal('alice', 'MMOEXP_AUTH=synthetic')
        value = backend.query(principal, 'evolutions.state', {})['data']
        self.assertEqual(value['config']['revision'], 4)
        self.assertEqual(value['history'][0]['status'], 'failed')
        self.assertNotIn('raw-secret', json.dumps(value))
        self.assertEqual(calls[0][0:2], ('GET', '/dashboard/fc27-evolutions/api/state'))
        with self.assertRaises(ValidationError):
            backend.query(principal, 'evolutions.state', {'refresh': 1})
        allowed[0] = 403
        with self.assertRaises(CatalogPermissionError):
            backend.query(principal, 'evolutions.state', {})
        self.assertEqual(len(calls), 1)

    def test_invalid_public_shapes_fail_explicitly(self):
        for value in [[], dict(config=[], snapshot=None, job=None, history=[], rows=[]),
                      dict(config={'overrides': []}, snapshot=None, job=None, history=[], rows=[])]:
            with self.subTest(value=value), self.assertRaises(BackendError):
                project(value)


if __name__ == '__main__':
    unittest.main()

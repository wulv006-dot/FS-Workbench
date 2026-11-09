import json
import unittest

from fs_mcp_connector.backend import Backend, BackendError
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, ValidationError
from fs_mcp_connector.portal import Principal


class SalesTests(unittest.TestCase):
    def setUp(self):
        self.allowed, self.calls = 200, []
        self.snapshot = {'meta': {'generated_at': 'fixture', 'counts': {'orders': 3}},
            'orders': [{'id': i, 'amount_usd': 1.25, 'profit_cny': -2,
                'email': 'private@example.test', 'cookie': 'private'} for i in range(3)]}
        def transport(*args):
            self.calls.append(args)
            return 200, json.dumps(self.snapshot).encode()
        self.backend = Backend(Catalog(lambda *_: self.allowed), 'https://fs.example', transport=transport)
        self.user = Principal('alice', 'MMOEXP_AUTH=synthetic')

    def read(self, **args):
        return self.backend.query(self.user, 'sales.snapshot', {'dataset': 'orders', **args})['data']

    def test_pages_preserve_figures_and_require_same_snapshot(self):
        first = self.read(limit=2)
        self.assertEqual(self.calls[0][:2], ('GET', '/sales/data/dashboard.json'))
        self.assertEqual(first['rows'][0], {'id': 0, 'amount_usd': 1.25, 'profit_cny': -2, 'email': 'private@example.test'})
        self.assertEqual(first['next_offset'], 2)
        self.assertFalse(first['complete'])
        last = self.read(offset=2, snapshot_sha256=first['snapshot_sha256'])
        self.assertEqual([row['id'] for row in last['rows']], [2])
        self.assertIsNone(last['next_offset'])
        self.snapshot['meta']['generated_at'] = 'changed'
        with self.assertRaises(BackendError) as error:
            self.read(offset=2, snapshot_sha256=first['snapshot_sha256'])
        self.assertEqual(error.exception.code, 'snapshot_changed_restart_query')

    def test_missing_snapshot_invalid_parameters_and_permission_never_succeed(self):
        with self.assertRaises(BackendError) as error:
            self.read(offset=1)
        self.assertEqual(error.exception.code, 'snapshot_required_for_continuation')
        for args in ({'limit': 101}, {'dataset': 'credentials'}, {'owner': 'admin'}):
            with self.assertRaises(ValidationError):
                self.read(**args)
        self.allowed = 403
        with self.assertRaises(CatalogPermissionError):
            self.read()

    def test_missing_data_is_not_reported_as_empty(self):
        del self.snapshot['orders']
        with self.assertRaises(BackendError) as error:
            self.read()
        self.assertEqual(error.exception.code, 'unexpected_sales_shape')


if __name__ == '__main__':
    unittest.main()

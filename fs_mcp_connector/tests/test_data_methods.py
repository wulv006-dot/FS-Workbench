"""Discovery exposes existing business semantics, with the same resource permissions."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fs_mcp_connector.catalog import Catalog, CatalogUnavailable, CatalogPermissionError
from fs_mcp_connector.portal import Principal


class DataMethodsTests(unittest.TestCase):
    principal = Principal('alice', 'MMOEXP_AUTH=fixture')

    def test_method_sources_and_operations_are_real_and_scope_is_business_data(self):
        catalog = Catalog(lambda *_: 200)
        listing = catalog.list(self.principal)
        self.assertEqual(len(listing['operations']), 113)
        self.assertFalse(any(name.startswith(('conversations.', 'reports.')) for name in catalog.operations))
        self.assertFalse({'hermes-conversation', 'brain', 'weekly'} & {row['module'] for row in listing['coverage']})
        for name in ('customer_tracking.detail', 'campaigns.report', 'knowledge.read'):
            self.assertIn(name, catalog.operations)
        methods = listing['data_methods']
        root = Path(__file__).resolve().parents[2]
        sources = {row['id'] for row in methods['sources']}
        for row in methods['guides']:
            self.assertTrue(row['operations'])
            self.assertFalse(set(row['operations']) - catalog.operations.keys())
            self.assertFalse(set(row['sources']) - sources)
        for row in methods['sources']:
            contents = (root/row['path']).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(contents).hexdigest(), row['sha256'])
            self.assertEqual(row['kind'], 'repository_method_reference_not_live_data')

    def test_discovery_filters_method_operation_references_and_sources(self):
        full = Catalog(lambda *_: 200)
        path = full.operation('orders.customer')['permission_path']
        restricted = Catalog(lambda _, candidate, method: 200 if candidate == path and method == 'POST' else 403)
        listing = restricted.list(self.principal)
        names = {row['name'] for row in listing['operations']}
        self.assertEqual(names, {'orders.customer'})
        methods = listing['data_methods']
        for row in methods['guides']:
            self.assertEqual(row['operations'], ['orders.customer'])
        referenced = {source for row in methods['guides'] for source in row['sources']}
        self.assertEqual({row['id'] for row in methods['sources']}, referenced)
        denied = Catalog(lambda *_: 403).list(self.principal)
        self.assertEqual(denied['data_methods']['guides'], [])
        self.assertEqual(denied['data_methods']['sources'], [])

    def test_method_discovery_does_not_hide_authentication_or_outage(self):
        for status, error in ((401, CatalogPermissionError), (503, CatalogUnavailable)):
            with self.subTest(status=status), self.assertRaises(error):
                Catalog(lambda *_: status).list(self.principal)

    def test_unregistered_method_operation_fails_catalog_load(self):
        document = Catalog(lambda *_: 200).document
        document['data_methods']['guides'][0]['operations'].append('reports.generate')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'catalog.json'
            path.write_text(json.dumps(document), 'utf-8')
            with self.assertRaisesRegex(ValueError, 'unknown_method_operation'):
                Catalog(lambda *_: 200, path)


if __name__ == '__main__':
    unittest.main()

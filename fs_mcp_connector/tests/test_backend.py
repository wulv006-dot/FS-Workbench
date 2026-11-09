from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from fs_mcp_connector.backend import Backend, BackendError
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, CatalogUnavailable, ValidationError
from fs_mcp_connector.portal import Principal


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.allowed = 200
        self.calls = []
        self.response = (206, b'{"status":"partial","complete":false,"next_cursor":"next"}')
        self.catalog = Catalog(lambda *args: self.allowed)
        def transport(*args):
            self.calls.append(args)
            return self.response
        self.backend = Backend(self.catalog, 'https://fs.example', transport=transport)
        self.principal = Principal('alice', 'MMOEXP_AUTH=fixture')
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        self.query = {'site_id': '266', 'game_id': '1327', 'start': str(today-timedelta(days=1)),
                      'end_exclusive': str(today)}

    def test_partial_and_cursor_preserved(self):
        out = self.backend.query(self.principal, 'orders.live', self.query)
        self.assertEqual(out['status_code'], 206)
        self.assertFalse(out['data']['complete'])
        self.assertEqual(out['data']['next_cursor'], 'next')
        self.assertNotIn('MMOEXP_AUTH', json.dumps(out))

    def test_customer_email_is_post_body_only(self):
        self.backend.query(self.principal, 'orders.customer', dict(self.query, customer_email='fixture@example.test'))
        method, target, headers, body, limits = self.calls[0]
        self.assertEqual(method, 'POST')
        self.assertNotIn('?', target)
        self.assertNotIn('fixture@example.test', target)
        self.assertEqual(json.loads(body)['customer_email'], 'fixture@example.test')
        self.assertEqual(headers['Origin'], 'https://fs.example')
        self.assertEqual(limits['response_bytes'], 262144)

    def test_unknown_fields_operations_and_date_boundary(self):
        for operation, arguments in [('https://attacker.example', {}),
            ('orders.live', dict(self.query, owner='admin')),
            ('orders.live', dict(self.query, customer_email='fixture@example.test')),
            ('orders.live', dict(self.query, start='2000-01-01'))]:
            with self.subTest(operation=operation, arguments=arguments), self.assertRaises(ValidationError):
                self.backend.query(self.principal, operation, arguments)
        self.assertEqual(self.calls, [])

    def test_get_search_cannot_put_customer_email_in_url(self):
        with self.assertRaises(ValidationError):
            self.backend.query(self.principal, 'orders.live', dict(self.query, cursor='fixture@example.test'))
        self.assertEqual(self.calls, [])

    def test_authorized_customer_identifiers_are_returned_to_model(self):
        row = self.catalog.operation('users.detail')
        args = {name: 'fixture-customer' for name in row['input_schema'].get('required', [])}
        self.response = (200, b'{"email":"fixture@example.test","customer_id":"fixture-customer","orders":[]}')
        result = self.backend.query(self.principal, 'users.detail', args)
        self.assertIn('fixture@example.test', json.dumps(result))
        self.assertEqual(result['data']['customer_id'], 'fixture-customer')

    def test_generic_nested_text_removes_credentials_and_keeps_query_identifiers(self):
        self.response = (200, json.dumps({'rows': [{'email': 'fixture@example.test',
            'uid': 42, 'order_no': 'ORDER-123',
            'note': 'Authorization: Bearer SYNTHETIC_TOKEN', 'details': ['csrf=synthetic-csrf']}]}).encode())
        result = self.backend.query(self.principal, 'business.catalog', {})['data']['rows'][0]
        self.assertEqual((result['email'], result['uid'], result['order_no']),
                         ('fixture@example.test', 42, 'ORDER-123'))
        self.assertNotIn('SYNTHETIC_TOKEN', json.dumps(result))
        self.assertNotIn('synthetic-csrf', json.dumps(result))

    def test_authorized_tracking_identifiers_are_returned_to_model(self):
        self.response = (200, b'{"items":[{"email":"fixture@example.test","tracking_id":"fixture"}]}')
        result = self.backend.query(self.principal, 'customer_tracking.tracked', {})
        self.assertEqual(result['data']['items'], [{'email': 'fixture@example.test', 'tracking_id': 'fixture'}])

    def test_fixed_response_projection_excludes_unapproved_fields(self):
        self.catalog.operations['orders.live']['response_fields'] = ['rows', 'complete', 'next_cursor']
        self.response = (200, b'{"rows":[],"complete":false,"next_cursor":"next","config":{"token":"secret"}}')
        result = self.backend.query(self.principal, 'orders.live', self.query)
        self.assertEqual(result['data'], {'rows': [], 'complete': False, 'next_cursor': 'next'})
        self.response = (200, b'[]')
        with self.assertRaises(BackendError):
            self.backend.query(self.principal, 'orders.live', self.query)

    def test_published_knowledge_dispatch_never_becomes_arbitrary_http(self):
        with self.assertRaises(BackendError) as raised:
            self.backend.query(self.principal, 'knowledge.index', {})
        self.assertEqual(raised.exception.code, 'published_knowledge_not_configured')
        class Knowledge:
            def index(self, principal, **args):
                return {'subject': principal.subject, 'history': args.get('history', False)}
        self.backend.knowledge = Knowledge()
        result = self.backend.query(self.principal, 'knowledge.index', {'history': True})
        self.assertEqual(result['data'], {'subject': 'alice', 'history': True})
        for args in ({'history': 1}, {'path': '/etc/private'}, {'owner': 'administrator'}):
            with self.assertRaises(ValidationError):
                self.backend.query(self.principal, 'knowledge.index', args)
        self.assertEqual(self.calls, [])

    def test_order_identifiers_preserved_without_losing_pagination(self):
        self.response = (206, json.dumps({'rows': [{'order_id': 'fixture-order',
            'customer_email': 'fixture@example.test', 'amount': 12}],
            'query': {'customer_email': 'fixture@example.test'},
            'complete': False, 'next_cursor': 'next'}).encode())
        for operation, args in [('orders.live', self.query), ('orders.customer',
                dict(self.query, customer_email='fixture@example.test'))]:
            with self.subTest(operation=operation):
                result = self.backend.query(self.principal, operation, args)
                self.assertIn('fixture@example.test', json.dumps(result))
                self.assertEqual(result['data']['rows'], [{'order_id': 'fixture-order', 'customer_email': 'fixture@example.test', 'amount': 12}])
                self.assertFalse(result['data']['complete'])
                self.assertEqual(result['data']['next_cursor'], 'next')

    def test_error_reason_and_backoff_preserved_without_raw_body(self):
        self.response = (429, b'{"error":"source_busy","retryAfter":5,"debug":"SECRET"}')
        with self.assertRaises(BackendError) as raised:
            self.backend.query(self.principal, 'orders.live', self.query)
        self.assertEqual((raised.exception.code, raised.exception.retry_after), ('source_busy', 5))
        self.assertNotIn('SECRET', str(raised.exception))

    def test_denied_and_unavailable_not_empty_data(self):
        self.allowed = 403
        with self.assertRaises(CatalogPermissionError):
            self.backend.query(self.principal, 'orders.live', self.query)
        self.allowed = 503
        with self.assertRaises(CatalogUnavailable):
            self.catalog.list(self.principal)
        self.assertEqual(self.calls, [])

    def test_sensitive_structured_fields_and_invalid_json_rejected(self):
        for raw in (b'{"csrf":"private"}', b'{"rows":[{"access_token":"private"}]}',
                    b'{"email":"fixture@example.test","password_hash":"private"}', b'<html>login</html>'):
            self.response = (200, raw)
            with self.subTest(raw=raw), self.assertRaises(BackendError):
                self.backend.query(self.principal, 'orders.live', self.query)

    def test_rechecks_permission_after_read(self):
        def revoke_during_read(*args):
            self.allowed = 403
            return self.response
        self.backend.transport = revoke_during_read
        with self.assertRaises(CatalogPermissionError):
            self.backend.query(self.principal, 'orders.live', self.query)

    def test_catalog_does_not_hide_authorized_unmapped_modules(self):
        self.catalog.document['coverage'].append({'module': 'unmapped_fixture',
            'status': 'not_yet_mapped', 'operations': 0, 'permission_path': '/fixture/'})
        catalog = self.catalog.list(self.principal)
        self.assertTrue(any(x['module'] == 'unmapped_fixture' and x['status'] == 'not_yet_mapped'
                            for x in catalog['coverage']))
        self.assertNotIn('tasks.session', [x['name'] for x in catalog['operations']])

    def test_fixed_paths_schemas_and_provenance_are_reviewable(self):
        root = Path(__file__).resolve().parents[2]
        for row in self.catalog.operations.values():
            with self.subTest(operation=row['name']):
                self.assertTrue(row['path'].startswith('/'))
                self.assertNotIn('/api/api/', row['path'])
                self.assertFalse(set(row.get('fixed', {})) & set(row['input_schema']['properties']))
                self.assertEqual(row['input_schema']['additionalProperties'], False)
                for source in row['provenance']['source'].split('; '):
                    self.assertTrue((root/source).is_file(), source)

    def test_fixed_origin_requires_validated_https(self):
        for url in ('http://fs.example', 'https://fs.example/path', 'https://user:pass@fs.example'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Backend(self.catalog, url)

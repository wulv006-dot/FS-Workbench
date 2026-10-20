"""Execute the changed policy loader and controller method with private-free fixtures."""
import ast
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import http.client
import threading

HERE = Path(__file__).resolve().parent
DAILY = HERE / 'source/fc_daily.py'
CONTROLLER = HERE / 'source/controller.py'
ROOT = next(p for p in HERE.parents if (p / 'AGENTS.md').exists())


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        model = types.ModuleType('fc_daily_model')
        model.configured = model.explain = model.projection = lambda *a: None
        spec = importlib.util.spec_from_file_location('recovery_daily', DAILY)
        self.daily = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'fc_daily_model': model}):
            spec.loader.exec_module(self.daily)
        self.policy = self.root / 'access_policy.py'
        self.daily._POLICY_PATH = self.policy
        self.counter = self.root / 'loads'

    def write_policy(self, extra=''):
        self.policy.write_text('from pathlib import Path\n'
            f'with Path({str(self.counter)!r}).open("a") as out: out.write("x")\n'
            'ADMINS = {"wulv"}\n'
            'def is_admin(user): return user in ADMINS\n' + extra, encoding='utf-8')

    def test_concurrent_requests_load_once(self):
        self.write_policy()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertTrue(all(pool.map(self.daily.admin, ['wulv'] * 24)))
        self.assertEqual(self.counter.read_text(), 'x')
        denied = self.daily.admin_status('viewer')
        self.assertTrue(denied['verified'])
        self.assertEqual(denied['reason'], 'not_admin')

    def test_source_change_invalidates_cache_and_revokes(self):
        self.write_policy()
        self.assertTrue(self.daily.admin('wulv'))
        previous = self.policy.stat()
        self.write_policy('ADMINS = {"DY"}\n')
        os.utime(self.policy, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1))
        self.assertFalse(self.daily.admin('wulv'))
        self.assertTrue(self.daily.admin('DY'))
        self.assertEqual(self.counter.read_text(), 'xx')

    def test_atomic_same_mtime_replacement_invalidates_inode(self):
        self.write_policy()
        self.assertTrue(self.daily.admin('wulv'))
        info = self.policy.stat()
        replacement = self.root / 'replacement.py'
        replacement.write_text(self.policy.read_text().replace('wulv', 'nope'))
        os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(replacement, self.policy)
        self.assertFalse(self.daily.admin('wulv'))

    def test_cached_module_still_refreshes_live_policy(self):
        state = self.root / 'admins'
        state.write_text('wulv')
        self.write_policy(f'def is_admin(user): return user == Path({str(state)!r}).read_text()\n')
        self.assertTrue(self.daily.admin('wulv'))
        state.write_text('DY')
        self.assertFalse(self.daily.admin('wulv'))
        self.assertTrue(self.daily.admin('DY'))
        self.assertEqual(self.counter.read_text(), 'x')

    def test_load_errors_deny_and_recover_without_stale_admin(self):
        self.write_policy()
        self.assertTrue(self.daily.admin('wulv'))
        for source, kind in [(None, 'FileNotFoundError'), ('import missing_fs_recovery_fixture', 'ModuleNotFoundError'), ('def !!!', 'SyntaxError')]:
            with self.subTest(kind=kind):
                if source is None:
                    self.policy.unlink()
                else:
                    self.policy.write_text(source)
                result = self.daily.admin_status('wulv')
                self.assertFalse(result['verified'])
                self.assertFalse(result['is_admin'])
                self.assertEqual(result['error'], kind)
                self.assertEqual(result['reason'], 'admin_unverified')
        self.write_policy()
        self.assertTrue(self.daily.admin('wulv'))

    def test_policy_degraded_is_reported(self):
        self.write_policy('def status(): return {"degraded": "private error details"}\n')
        result = self.daily.admin_status('wulv')
        self.assertEqual(result['error'], 'policy_degraded')
        self.assertFalse(result['is_admin'])
        self.assertNotIn('private error details', json.dumps(result))

    def service(self, authorizer=None):
        tree = ast.parse(CONTROLLER.read_text('utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HermesService')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'get')
        imported = Mock()
        imported.return_value.listed.return_value = []
        self.env = {'json': json, 'date': date, 're': __import__('re'),
                    'spending_hold': lambda *a: None, 'load_bundle': lambda *a: {'version': 'fixture'},
                    'ImportedReports': imported, 'can_continue': lambda *a: True}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(CONTROLLER), 'exec'), self.env)
        connection = sqlite3.connect(':memory:', check_same_thread=False)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        connection.executescript('CREATE TABLE requests(id,owner,state,error,body);'
            'CREATE TABLE report_trash(id,deleted_by,deleted_at);'
            'INSERT INTO requests VALUES("own","wulv","COMPLETED",NULL,"{}");'
            'INSERT INTO requests VALUES("other","DY","COMPLETED",NULL,"{}");')
        @contextmanager
        def db():
            yield connection
        nightly = Mock()
        nightly.status.side_effect = PermissionError('nightly_owner_not_authorized')
        return types.SimpleNamespace(authorizer=authorizer or self.daily.admin, daily=None,
            tasks=types.SimpleNamespace(db=db), source_root=self.root, root=self.root, nightly=nightly)

    def get(self, service, **params):
        return self.env['get'](service, {'mode': ['hermes'], **params}, 'wulv')

    def test_unverified_list_returns_only_owned_reports_and_disables_writes(self):
        service = self.service()
        code, data = self.get(service)
        self.assertEqual(code, 200)
        self.assertEqual(data['pool_scope'], 'mine')
        self.assertEqual([r['id'] for r in data['items']], ['own'])
        self.assertFalse(data['can_generate'])
        self.assertFalse(data['items'][0]['can_delete'])
        self.assertFalse(data['items'][0]['can_continue'])
        self.assertEqual(data['admission']['reason'], 'admin_unverified')
        self.assertFalse(self.env['ImportedReports'].return_value.listed.call_args.args[1])

    def test_verified_non_admin_stays_mine(self):
        self.write_policy('ADMINS = {"DY"}\n')
        service = self.service()
        code, data = self.get(service)
        self.assertEqual(code, 200)
        self.assertEqual(data['authorization']['reason'], 'not_admin')
        self.assertEqual([r['id'] for r in data['items']], ['own'])
        self.assertFalse(data['can_generate'])

    def test_healthy_admin_keeps_shared_pool(self):
        self.write_policy()
        service = self.service()
        service.nightly.status.side_effect = None
        service.nightly.status.return_value = {'enabled': True}
        code, data = self.get(service)
        self.assertEqual(code, 200)
        self.assertEqual(data['pool_scope'], 'shared')
        self.assertEqual(len(data['items']), 2)
        self.assertTrue(data['can_generate'])

    def test_throwing_authorizer_degrades_safely(self):
        service = self.service()
        service.authorizer = lambda user: (_ for _ in ()).throw(ImportError('private detail'))
        code, data = self.get(service)
        self.assertEqual(code, 200)
        self.assertEqual(data['admission']['reason'], 'admin_unverified')

    def test_detail_and_artifact_bypass_nightly(self):
        service = self.service()
        service.visible_job = lambda user, key: {'id': key, 'state': 'COMPLETED', 'task_id': 'fixture'}
        self.assertEqual(self.get(service, id=['own'])[0], 200)
        self.env['read_file'] = lambda *a: {'content': 'original artifact'}
        self.assertEqual(self.get(service, id=['own'], artifact=['html']), (200, {'content': 'original artifact'}))
        service.nightly.status.assert_not_called()

    def test_login_and_query_validation_preserved(self):
        service = self.service()
        self.assertEqual(self.env['get'](service, {'mode': ['hermes']}, '')[0], 401)
        self.assertEqual(self.get(service, scope=['bad'])[0], 422)

    def test_existing_http_handler_returns_200_during_policy_failure(self):
        service = self.service()
        service.get = types.MethodType(self.env['get'], service)
        path = ROOT / 'releases/fs-dashboard/hermes-customer-tracking-20261018/source/range_api.py'
        if not path.exists():
            path = ROOT / 'fs_customer_tracking_20261018/source/range_api.py'
        handler = next(n for n in ast.parse(path.read_text('utf-8')).body
                       if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        env = {'BaseHTTPRequestHandler': BaseHTTPRequestHandler, 'HERMES': service,
               'urlsplit': urlsplit, 'parse_qs': parse_qs, 'CONVERSATION_PREFIX': '/api/hermes/conversations',
               'encoded': lambda value: json.dumps(value).encode(), 'CUSTOMER_TRACKING': None}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), 'exec'), env)
        server = ThreadingHTTPServer(('127.0.0.1', 0), env['Handler'])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = http.client.HTTPConnection(*server.server_address, timeout=5)
            try:
                client.request('GET', '/advisor?mode=hermes', headers={'X-Auth-User': 'wulv'})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload['admission']['reason'], 'admin_unverified')
                self.assertEqual(payload['pool_scope'], 'mine')
            finally:
                client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()

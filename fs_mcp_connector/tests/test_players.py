import concurrent.futures
import json
import threading
import unittest

import httpx

from fs_mcp_connector.catalog import CatalogPermissionError, ValidationError
from fs_mcp_connector.portal import Principal
from fs_mcp_connector.players import PlayersService, PlayersError, OPERATIONS


ORIGIN = 'https://fs.example'
ROOT = '/tools/fc27-players'
CSRF = 'c'*43


class PlayersTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.permits = [], []
        self.bootstrap_count, self.auth_count = 0, 0
        self.clock = 100.0
        self.allowed = 200
        self.override = None
        self.principal = Principal('alice', 'MMOEXP_AUTH=alice')
        self.service = PlayersService(ORIGIN, self.authorize,
            transport=httpx.MockTransport(self.respond), clock=lambda: self.clock)

    def authorize(self, principal, path, method):
        self.permits.append((principal.subject, path, method))
        return self.allowed

    def respond(self, request):
        self.calls.append(request)
        if self.override:
            response = self.override(request)
            if response is not None:
                return response
        path = request.url.path
        if path == ROOT+'/api/bootstrap':
            self.bootstrap_count += 1
            subject = request.headers['cookie'].split('=', 1)[1].split(';', 1)[0].split('-')[0]
            headers = {} if 'FC27PLAYER_SID=' in request.headers['cookie'] else {
                'Set-Cookie': f'FC27PLAYER_SID={str(self.bootstrap_count)*43}; Path={ROOT}/; Secure; HttpOnly'}
            return httpx.Response(200, json={'owner': subject, 'role': 'admin', 'csrf': CSRF,
                'root_path': ROOT, 'shared_backend_session': True, 'backend_authenticated': False},
                headers=headers)
        if path == ROOT+'/api/auth/shared':
            self.auth_count += 1
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.headers['Origin'], ORIGIN)
            self.assertEqual(request.headers['X-CSRF-Token'], CSRF if self.auth_count == 1 else 'r'*43)
            self.assertEqual(json.loads(request.content), {})
            return httpx.Response(200, json={'authenticated': True, 'csrf': 'r'*43})
        return httpx.Response(206, json={'complete': False, 'next_cursor': 'next', 'items': [{'model_id': 1}]})

    def test_status_reuses_sid_without_backend_login_or_identity_headers(self):
        for _ in range(2):
            result = self.service.query(self.principal, 'players.status', {})
            self.assertEqual(result['status_code'], 206)
            self.assertFalse(result['data']['complete'])
            self.assertNotIn('csrf', json.dumps(result))
            self.assertNotIn('MMOEXP_AUTH', json.dumps(result))
        self.assertEqual((self.bootstrap_count, self.auth_count), (1, 0))
        self.assertIn('FC27PLAYER_SID=', self.calls[-1].headers['cookie'])
        for request in self.calls:
            self.assertNotIn('X-FC27-User', request.headers)
            self.assertNotIn('X-Auth-User', request.headers)
        self.assertGreaterEqual(self.permits.count(('alice', ROOT+'/api/status', 'GET')), 4)

    def test_models_tags_use_shared_login_once_and_no_business_writes(self):
        self.service.query(self.principal, 'players.models', {'page': 2, 'per_page': 200, 'is_rec': 1})
        self.service.query(self.principal, 'players.tags', {})
        self.assertEqual((self.bootstrap_count, self.auth_count), (1, 1))
        self.assertEqual([(r.method, r.url.path) for r in self.calls if r.method != 'GET'], [('POST', ROOT+'/api/auth/shared')])
        self.assertIn(('alice', ROOT+'/api/auth/shared', 'POST'), self.permits)
        self.assertEqual(self.calls[-2].url.params['per_page'], '200')

    def test_free_text_credentials_are_removed_without_anonymizing_business_identity(self):
        def override(request):
            if request.url.path.endswith('/api/status'):
                return httpx.Response(200, json={'email': 'fixture@example.test', 'uid': 42,
                    'order_no': 'ORDER-123', 'event': {'detail': 'Authorization: Bearer SYNTHETIC_TOKEN'}})
        self.override = override
        data = self.service.query(self.principal, 'players.status', {})['data']
        self.assertEqual((data['email'], data['uid'], data['order_no']), ('fixture@example.test', 42, 'ORDER-123'))
        self.assertNotIn('SYNTHETIC_TOKEN', json.dumps(data))

    def test_sessions_are_isolated_by_subject_and_original_fs_session(self):
        principals = [self.principal, Principal('bob', 'MMOEXP_AUTH=bob'), Principal('alice', 'MMOEXP_AUTH=alice-new')]
        for principal in principals:
            self.service.query(principal, 'players.status', {})
        self.assertEqual(self.bootstrap_count, 3)
        sid_cookies = [r.headers['cookie'] for r in self.calls if r.url.path.endswith('/api/status')]
        self.assertEqual(len(set(sid_cookies)), 3)

    def test_concurrent_queries_share_one_bootstrap_and_auth(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.query(self.principal, 'players.models', {}), range(8)))
        self.assertEqual(len(results), 8)
        self.assertEqual((self.bootstrap_count, self.auth_count), (1, 1))

    def test_slow_session_does_not_lock_another_users_bootstrap(self):
        entered, release = threading.Event(), threading.Event()
        def slow(request):
            if request.url.path.endswith('/api/bootstrap') and request.headers['cookie'] == 'MMOEXP_AUTH=alice':
                entered.set()
                self.assertTrue(release.wait(3))
        self.override = slow
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            alice = pool.submit(self.service.query, self.principal, 'players.status', {})
            self.assertTrue(entered.wait(2))
            try:
                bob = pool.submit(self.service.query, Principal('bob', 'MMOEXP_AUTH=bob'), 'players.status', {})
                self.assertEqual(bob.result(timeout=2)['status_code'], 206)
            finally:
                release.set()
            alice.result(timeout=2)

    def test_permission_denial_and_revocation_do_not_return_data(self):
        self.allowed = 403
        with self.assertRaises(CatalogPermissionError):
            self.service.query(self.principal, 'players.status', {})
        self.assertEqual(self.calls, [])
        self.allowed = 200
        def revoke(request):
            if request.url.path.endswith('/api/status'):
                self.allowed = 403
        self.override = revoke
        with self.assertRaises(CatalogPermissionError):
            self.service.query(self.principal, 'players.status', {})

    def test_unknown_operations_fields_and_invalid_ids_fail_before_network(self):
        for operation, arguments in [('players.bootstrap', {}), ('players.status', {'subject': 'bob'}),
            ('players.job', {'job_id': '../private'}), ('players.models', {'page': 0}),
            ('players.models', {'status': True}), ('players.tags', {'url': 'https://attacker.example'})]:
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                self.service.query(self.principal, operation, arguments)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(OPERATIONS), 7)

    def test_shared_auth_unknown_is_reconciled_without_post_replay(self):
        def timeout(request):
            if request.url.path.endswith('/api/auth/shared'):
                self.auth_count += 1
                raise httpx.ReadTimeout('private error')
        self.override = timeout
        with self.assertRaises(PlayersError) as first:
            self.service.query(self.principal, 'players.models', {})
        self.assertNotIn('private', str(first.exception))
        with self.assertRaises(PlayersError):
            self.service.query(self.principal, 'players.models', {})
        self.assertEqual(self.auth_count, 1)
        bootstraps = [r for r in self.calls if r.url.path.endswith('/api/bootstrap')]
        self.assertIn('FC27PLAYER_SID=1', bootstraps[-1].headers['cookie'])

    def test_unknown_post_that_succeeded_recovers_by_reading_same_sid(self):
        committed = False
        def uncertain(request):
            nonlocal committed
            if request.url.path.endswith('/api/auth/shared'):
                committed = True
                self.auth_count += 1
                raise httpx.ReadTimeout('lost reply')
            if request.url.path.endswith('/api/bootstrap') and committed:
                self.bootstrap_count += 1
                self.assertIn('FC27PLAYER_SID=1', request.headers['cookie'])
                return httpx.Response(200, json={'owner': 'alice', 'role': 'admin', 'csrf': 'r'*43,
                    'root_path': ROOT, 'shared_backend_session': True, 'backend_authenticated': True})
        self.override = uncertain
        with self.assertRaises(PlayersError):
            self.service.query(self.principal, 'players.models', {})
        self.assertEqual(self.service.query(self.principal, 'players.models', {})['status_code'], 206)
        self.assertEqual(self.auth_count, 1)

    def test_shared_auth_500_after_commit_reconciles_without_post_replay(self):
        committed = False
        def uncertain(request):
            nonlocal committed
            if request.url.path.endswith('/api/auth/shared'):
                committed = True
                self.auth_count += 1
                return httpx.Response(500, json={'error': 'OPERATION_FAILED'})
            if request.url.path.endswith('/api/bootstrap') and committed:
                self.bootstrap_count += 1
                self.assertIn('FC27PLAYER_SID=1', request.headers['cookie'])
                return httpx.Response(200, json={'owner': 'alice', 'role': 'admin', 'csrf': 'r'*43,
                    'root_path': ROOT, 'shared_backend_session': True, 'backend_authenticated': True})
        self.override = uncertain
        with self.assertRaises(PlayersError) as raised:
            self.service.query(self.principal, 'players.models', {})
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(self.service.query(self.principal, 'players.models', {})['status_code'], 206)
        self.assertEqual(self.auth_count, 1)

    def test_expired_backend_session_refreshes_only_after_explicit_auth_required(self):
        self.service.query(self.principal, 'players.models', {})
        count = 0
        def expired(request):
            nonlocal count
            if request.url.path.endswith('/api/models'):
                count += 1
                if count == 1:
                    return httpx.Response(409, json={'error': 'AUTH_REQUIRED'})
        self.override = expired
        self.service.query(self.principal, 'players.models', {})
        self.assertEqual((self.bootstrap_count, self.auth_count, count), (1, 2, 2))

    def test_server_restart_recovers_known_missing_browser_session_once(self):
        self.service.query(self.principal, 'players.status', {})
        count = 0
        def restarted(request):
            nonlocal count
            if request.url.path.endswith('/api/status'):
                count += 1
                if count == 1:
                    return httpx.Response(403, json={'error': 'BROWSER_SESSION_REQUIRED'})
        self.override = restarted
        self.assertEqual(self.service.query(self.principal, 'players.status', {})['status_code'], 206)
        self.assertEqual((self.bootstrap_count, count), (2, 2))

    def test_missing_snapshot_remains_error_without_refresh_or_retry(self):
        self.override = lambda r: httpx.Response(409, json={'error': 'MODEL_SNAPSHOT_REQUIRED'}) if r.url.path.endswith('/api/models') else None
        with self.assertRaises(PlayersError) as raised:
            self.service.query(self.principal, 'players.models', {})
        self.assertEqual((raised.exception.code, raised.exception.status_code), ('players_model_snapshot_required', 409))
        self.assertEqual((self.bootstrap_count, self.auth_count), (1, 1))

    def test_readonly_cannot_prepare_admin_backend_session(self):
        def deny_post(principal, path, method):
            return 403 if method == 'POST' else 200
        self.service.authorize = deny_post
        with self.assertRaises(CatalogPermissionError):
            self.service.query(self.principal, 'players.tags', {})
        self.assertEqual(self.auth_count, 0)

    def test_secret_payload_rejected_and_job_artifact_paths_are_not_exposed(self):
        self.override = lambda r: httpx.Response(200, json={'csrf': 'private'}) if r.url.path.endswith('/api/status') else None
        with self.assertRaises(PlayersError):
            self.service.query(self.principal, 'players.status', {})
        self.override = lambda r: httpx.Response(200, json={'items': [{'planned_json': '{"artifact_path":"/private/path"}',
            'planned': {'artifact_path': '/private/path', 'model_id': 1}}]}) if '/api/jobs/' in r.url.path else None
        out = self.service.query(self.principal, 'players.job', {'job_id': 'a'*32})
        self.assertEqual(out['data']['items'], [{'planned': {'model_id': 1}}])

    def test_redirect_and_oversized_response_are_rejected(self):
        for response in [httpx.Response(302, headers={'Location': 'https://attacker.example'}),
            httpx.Response(200, content=b'x'*(4194304+1))]:
            self.override = lambda r, response=response: response
            with self.subTest(status=response.status_code), self.assertRaises(PlayersError):
                self.service.query(self.principal, 'players.status', {})

    def test_wrong_bootstrap_subject_is_rejected(self):
        self.override = lambda r: httpx.Response(200, json={'owner': 'bob', 'csrf': 'private',
            'root_path': ROOT, 'shared_backend_session': True, 'backend_authenticated': False},
            headers={'Set-Cookie': f'FC27PLAYER_SID={"a"*43}'})
        with self.assertRaises(PlayersError):
            self.service.query(self.principal, 'players.status', {})

    def test_origin_is_fixed_https_and_rejects_paths_or_credentials(self):
        for value in ['http://fs.example', 'https://user:pass@fs.example', 'https://fs.example/private']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                PlayersService(value, self.authorize)


if __name__ == '__main__':
    unittest.main()

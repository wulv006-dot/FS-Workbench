import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import os
import sqlite3
from pathlib import Path
import tempfile
from threading import Event
import unittest

from fs_mcp_connector.auth import AuthError, AuthStore
from fs_mcp_connector.portal import PortalError, Principal


RESOURCE = 'https://fs.example/connector/mcp'
REDIRECT = 'https://client.example/callback'
VERIFIER = 'v' * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b'=').decode()


class FakePortal:
    subject = 'alice'
    allowed = True

    def verify(self, cookie, resource_path, method='GET'):
        if not self.allowed:
            raise PortalError(401)
        return Principal(self.subject, cookie)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'oauth.sqlite3'
        self.now = 1000
        self.portal = FakePortal()
        self.store = AuthStore(self.path, RESOURCE, self.portal, clock=lambda: self.now)
        self.client = self.store.register_client([REDIRECT], 'Example')['client_id']

    def tearDown(self):
        self.temp.cleanup()

    def code(self, **changes):
        args = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                    code_challenge=CHALLENGE, principal=Principal('alice', 'fs_session=private-cookie'))
        args.update(changes)
        return self.store.issue_code(**args)

    def exchange(self, code, **changes):
        args = dict(code=code, client_id=self.client, redirect_uri=REDIRECT,
                    resource=RESOURCE, code_verifier=VERIFIER)
        args.update(changes)
        return self.store.exchange_code(**args)

    def test_pkce_and_redirect_resource_client_binding(self):
        code = self.code()
        for changes in [dict(code_verifier='x' * 43), dict(redirect_uri=REDIRECT + '/'),
                        dict(resource=RESOURCE + '/'), dict(client_id='forged')]:
            with self.subTest(changes=changes), self.assertRaises(AuthError):
                self.exchange(code, **changes)
        tokens = self.exchange(code)
        self.assertEqual(tokens['scope'], 'fs.read')
        self.assertEqual(self.store.authenticate(tokens['access_token'], RESOURCE).subject, 'alice')
        with self.assertRaises(AuthError):
            self.store.authenticate(tokens['access_token'], RESOURCE + '/wrong')

    def test_token_payload_and_persistence_do_not_expose_session_or_raw_secrets(self):
        code = self.code()
        tokens = self.exchange(code)
        self.assertNotIn('private-cookie', str(tokens))
        self.assertNotIn('private-cookie', repr(self.store.authenticate(tokens['access_token'], RESOURCE)))
        raw = self.path.read_bytes()
        for secret in [code, tokens['access_token'], tokens['refresh_token']]:
            self.assertNotIn(secret.encode(), raw)
        reopened = AuthStore(self.path, RESOURCE, self.portal, clock=lambda: self.now)
        self.assertEqual(reopened.authenticate(tokens['access_token'], RESOURCE).subject, 'alice')

    def test_code_replay_revokes_issued_tokens(self):
        code = self.code()
        tokens = self.exchange(code)
        with self.assertRaises(AuthError):
            self.exchange(code)
        with self.assertRaises(AuthError):
            self.store.authenticate(tokens['access_token'], RESOURCE)

    def test_code_is_consumed_atomically_across_store_connections(self):
        code = self.code()
        def run(_):
            try:
                return self.exchange(code)
            except AuthError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_expiry(self):
        code = self.code()
        self.now += 301
        with self.assertRaises(AuthError):
            self.exchange(code)
        tokens = self.exchange(self.code())
        self.now += 3601
        with self.assertRaises(AuthError):
            self.store.authenticate(tokens['access_token'], RESOURCE)
        self.assertIn('access_token', self.store.refresh(tokens['refresh_token'], self.client, RESOURCE))

    def test_refresh_rotation_replay_revokes_entire_grant(self):
        tokens = self.exchange(self.code())
        refreshed = self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)
        self.assertNotEqual(refreshed['refresh_token'], tokens['refresh_token'])
        with self.assertRaises(AuthError):
            self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)
        with self.assertRaises(AuthError):
            self.store.authenticate(refreshed['access_token'], RESOURCE)

    def test_refresh_binding_and_revocation(self):
        tokens = self.exchange(self.code())
        for client, resource in [('forged', RESOURCE), (self.client, RESOURCE + '/wrong')]:
            with self.assertRaises(AuthError):
                self.store.refresh(tokens['refresh_token'], client, resource)
        self.store.revoke(tokens['access_token'], 'forged')
        self.store.authenticate(tokens['access_token'], RESOURCE)
        self.store.revoke(tokens['refresh_token'], self.client)
        for token in [tokens['access_token'], tokens['refresh_token']]:
            with self.assertRaises(AuthError):
                self.store.authenticate(token, RESOURCE)

    def test_current_portal_session_is_required_on_exchange_refresh_and_use(self):
        code = self.code()
        self.portal.allowed = False
        with self.assertRaises(AuthError):
            self.exchange(code)
        self.portal.allowed = True
        tokens = self.exchange(code)
        self.portal.allowed = False
        with self.assertRaises(AuthError):
            self.store.authenticate(tokens['access_token'], RESOURCE)
        with self.assertRaises(AuthError):
            self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)

    def test_subject_change_cannot_rebind_existing_grant(self):
        tokens = self.exchange(self.code())
        self.portal.subject = 'bob'
        with self.assertRaises(AuthError):
            self.store.authenticate(tokens['access_token'], RESOURCE)

    def test_invalid_registration_and_authorization_inputs(self):
        for redirects in [[], ['http://public.example/callback'], ['https://a.example/cb#fragment'],
                          ['https://a.example/cb#'],
                          ['https://@a.example/cb'],
                          ['https://user:pass@a.example/callback'], ['javascript:alert(1)']]:
            with self.subTest(redirects=redirects), self.assertRaises(AuthError):
                self.store.register_client(redirects)
        for changes in [dict(code_challenge=''), dict(code_challenge='v' * 44),
                        dict(scope='fs.write'), dict(redirect_uri=REDIRECT + '?other=1'),
                        dict(resource=RESOURCE + '?other=1')]:
            with self.subTest(changes=changes), self.assertRaises(AuthError):
                self.code(**changes)

    def test_pending_is_bound_to_session_csrf_subject_and_expires(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code',
                      state='client-state')
        principal = Principal('alice', 'cookie=session-one')
        pending, csrf = self.store.create_pending(params, principal)
        for supplied_csrf, supplied_principal in [
                ('wrong', principal), (csrf, Principal('bob', principal.session_cookie)),
                (csrf, Principal('alice', 'cookie=session-two'))]:
            with self.assertRaises(AuthError):
                self.store.consume_pending(pending, supplied_csrf, supplied_principal)
        self.assertEqual(self.store.consume_pending(pending, csrf, principal), params)
        with self.assertRaises(AuthError):
            self.store.consume_pending(pending, csrf, principal)
        pending, csrf = self.store.create_pending(params, principal)
        self.now += 301
        with self.assertRaises(AuthError):
            self.store.consume_pending(pending, csrf, principal)

    def test_pending_rejects_extra_parameters_and_pkce_downgrade(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code')
        for extra in [dict(username='admin'), dict(session_cookie='x'),
                      dict(code_challenge_method='plain'), dict(response_type='token')]:
            with self.subTest(extra=extra), self.assertRaises(AuthError):
                self.store.create_pending(dict(params, **extra), Principal('alice', 'cookie=x'))

    def test_invalid_client_type_is_an_oauth_error(self):
        with self.assertRaises(AuthError):
            self.store.get_client(['not-a-client'])

    def test_service_unavailability_is_distinct_from_bad_credentials(self):
        def unavailable(*args):
            raise PortalError(503)
        self.portal.verify = unavailable
        with self.assertRaises(AuthError) as caught:
            self.code()
        self.assertEqual(caught.exception.error, 'temporarily_unavailable')

    def test_pending_is_consumed_atomically(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code')
        principal = Principal('alice', 'cookie=session')
        pending, csrf = self.store.create_pending(params, principal)
        def consume(_):
            try:
                return self.store.consume_pending(pending, csrf, principal)
            except AuthError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(consume, range(4)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_refresh_is_rotated_atomically(self):
        tokens = self.exchange(self.code())
        def refresh(_):
            try:
                return self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)
            except AuthError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(refresh, range(4)))
        self.assertEqual(sum(result is not None for result in results), 1)
        # Competing reuse revokes the grant, including the winner's descendant token.
        with self.assertRaises(AuthError):
            self.store.authenticate(next(result for result in results if result)['access_token'], RESOURCE)

    def test_refresh_expires_with_original_grant(self):
        tokens = self.exchange(self.code())
        self.now += self.store.REFRESH_TTL
        with self.assertRaises(AuthError):
            self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)

    def test_slow_portal_read_does_not_hold_database_writer_lock(self):
        tokens = self.exchange(self.code())
        entered, release = Event(), Event()
        original = self.portal.verify
        def slow_portal(cookie, path, method='GET'):
            entered.set()
            if not release.wait(3):
                raise PortalError(503)
            return original(cookie, path, method)
        self.portal.verify = slow_portal
        with ThreadPoolExecutor(max_workers=2) as pool:
            authentication = pool.submit(self.store.authenticate, tokens['access_token'], RESOURCE)
            self.assertTrue(entered.wait(1))
            registration = pool.submit(self.store.register_client, [REDIRECT])
            try:
                self.assertIn('client_id', registration.result(timeout=1))
            finally:
                release.set()
                authentication.result(timeout=3)

    def test_revocation_during_portal_check_is_not_lost(self):
        tokens = self.exchange(self.code())
        entered, release = Event(), Event()
        original = self.portal.verify
        def slow_portal(cookie, path, method='GET'):
            entered.set()
            if not release.wait(3):
                raise PortalError(503)
            return original(cookie, path, method)
        self.portal.verify = slow_portal
        with ThreadPoolExecutor(max_workers=2) as pool:
            authentication = pool.submit(self.store.authenticate, tokens['access_token'], RESOURCE)
            self.assertTrue(entered.wait(1))
            revocation = pool.submit(self.store.revoke, tokens['access_token'], self.client)
            try:
                revocation.result(timeout=1)
            finally:
                release.set()
            with self.assertRaises(AuthError):
                authentication.result(timeout=3)

    def test_cookie_only_verifies_known_subject_and_dashboard_session(self):
        calls = []
        original = self.portal.verify
        def verify(cookie, path, method='GET'):
            calls.append((path, method))
            return original(cookie, path, method)
        self.portal.verify = verify
        with self.assertRaises(AuthError):
            self.code(principal=Principal('admin', 'fs_session=private-cookie'))
        tokens = self.exchange(self.code())
        self.store.authenticate(tokens['access_token'], RESOURCE)
        self.assertTrue(calls)
        self.assertEqual(set(calls), {('/dashboard/', 'GET')})

    def test_client_with_only_authorization_code_gets_no_refresh_token(self):
        client = self.store.register_client([REDIRECT], 'Code only', ['authorization_code'])
        tokens = self.exchange(self.code(client_id=client['client_id']), client_id=client['client_id'])
        self.assertNotIn('refresh_token', tokens)
        self.assertEqual(client['grant_types'], ['authorization_code'])
        self.assertEqual(self.store.authenticate(tokens['access_token'], RESOURCE).subject, 'alice')
        reopened = AuthStore(self.path, RESOURCE, self.portal, clock=lambda: self.now)
        self.assertEqual(reopened.get_client(client['client_id'])['grant_types'], ['authorization_code'])

    def test_client_grant_types_validate_and_allow_any_supported_order(self):
        client = self.store.register_client([REDIRECT], '', ['refresh_token', 'authorization_code'])
        tokens = self.exchange(self.code(client_id=client['client_id']), client_id=client['client_id'])
        self.assertIn('refresh_token', tokens)
        for grants in [[], ['refresh_token'], ['client_credentials'], ['authorization_code', 'authorization_code'], 'authorization_code']:
            with self.subTest(grants=grants), self.assertRaises(AuthError):
                self.store.register_client([REDIRECT], '', grants)

    def test_existing_client_schema_migrates_without_changing_grant_semantics(self):
        legacy = Path(self.temp.name) / 'legacy.sqlite3'
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute('CREATE TABLE clients (id TEXT PRIMARY KEY, redirects TEXT NOT NULL, name TEXT NOT NULL)')
            db.execute('INSERT INTO clients VALUES (?,?,?)', ('legacy-client', '["https://client.example/callback"]', 'Legacy'))
        if os.name == 'posix':
            legacy.chmod(0o600)
        migrated = AuthStore(legacy, RESOURCE, self.portal, clock=lambda: self.now)
        with closing(sqlite3.connect(legacy)) as db:
            self.assertIn('grant_types', [row[1] for row in db.execute('PRAGMA table_info(clients)')])
        self.assertEqual(migrated.get_client('legacy-client')['grant_types'], ['authorization_code', 'refresh_token'])
        self.assertEqual(migrated.get_client('legacy-client')['client_name'], 'Legacy')

    def test_login_continuation_is_short_persistent_one_use_and_hashed(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code',
                      state='long-state-' + 's' * 1500)
        request_id = self.store.create_login_request(params)
        self.assertLessEqual(len(request_id), 64)
        self.assertNotIn(request_id.encode(), self.path.read_bytes())
        reopened = AuthStore(self.path, RESOURCE, self.portal, clock=lambda: self.now)
        self.assertEqual(reopened.consume_login_request(request_id), params)
        with self.assertRaises(AuthError):
            self.store.consume_login_request(request_id)
        request_id = self.store.create_login_request(params)
        self.now += 301
        with self.assertRaises(AuthError):
            self.store.consume_login_request(request_id)

    def test_login_continuation_validates_before_persisting(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code')
        for changes in [dict(redirect_uri='https://other.example/cb'), dict(username='admin'),
                        dict(code_challenge_method='plain'), dict(resource=RESOURCE + '/wrong')]:
            with self.subTest(changes=changes), self.assertRaises(AuthError):
                self.store.create_login_request(dict(params, **changes))

    def test_login_continuation_is_consumed_atomically(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code')
        request_id = self.store.create_login_request(params)
        def consume(_):
            try:
                return self.store.consume_login_request(request_id)
            except AuthError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(consume, range(4)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_cleanup_removes_expired_state_and_cookies_but_retains_clients(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code')
        self.store.create_login_request(params)
        self.store.create_pending(params, Principal('alice', 'cookie=session'))
        self.code()
        self.exchange(self.code())
        self.now += self.store.REFRESH_TTL + 1
        self.store.cleanup()
        with self.store._db(write=False) as db:
            for table in ('codes', 'grants', 'tokens', 'pending', 'login_requests'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)
        self.assertEqual(self.store.get_client(self.client)['client_id'], self.client)

    def test_cleanup_keeps_valid_code_and_refresh_replay_detection(self):
        code = self.code()
        tokens = self.exchange(self.code())
        self.store.cleanup()
        self.exchange(code)
        rotated = self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)
        self.store.cleanup()
        with self.assertRaises(AuthError):
            self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)
        with self.assertRaises(AuthError):
            self.store.authenticate(rotated['access_token'], RESOURCE)

    def test_code_only_cookie_is_released_after_its_access_expires(self):
        client = self.store.register_client([REDIRECT], 'Code only', ['authorization_code'])['client_id']
        self.exchange(self.code(client_id=client), client_id=client)
        self.now += self.store.ACCESS_TTL + 1
        self.store.cleanup()
        with self.store._db(write=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM grants').fetchone()[0], 0)
        self.store.get_client(client)

    def test_client_capacity_is_atomic_and_does_not_revoke_existing_access(self):
        tokens = self.exchange(self.code())
        self.store.TABLE_LIMITS = dict(self.store.TABLE_LIMITS, clients=3)
        def register(_):
            try:
                return self.store.register_client([REDIRECT])
            except AuthError as error:
                self.assertEqual(error.error, 'temporarily_unavailable')
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(register, range(8)))
        self.assertEqual(sum(value is not None for value in results), 2)
        self.assertEqual(self.store.authenticate(tokens['access_token'], RESOURCE).subject, 'alice')
        self.store.get_client(self.client)

    def test_login_capacity_recovers_after_expiry_without_consuming_current_requests(self):
        params = dict(client_id=self.client, redirect_uri=REDIRECT, resource=RESOURCE,
                      code_challenge=CHALLENGE, code_challenge_method='S256', response_type='code')
        self.store.TABLE_LIMITS = dict(self.store.TABLE_LIMITS, login_requests=1)
        pending = self.store.create_login_request(params)
        with self.assertRaises(AuthError) as error:
            self.store.create_login_request(params)
        self.assertEqual(error.exception.error, 'temporarily_unavailable')
        self.assertEqual(self.store.consume_login_request(pending), params)
        self.store.create_login_request(params)
        self.now += self.store.CODE_TTL + 1
        self.assertTrue(self.store.create_login_request(params))

    def test_token_capacity_failure_does_not_consume_refresh_or_revoke_current_access(self):
        tokens = self.exchange(self.code())
        self.store.TABLE_LIMITS = dict(self.store.TABLE_LIMITS, tokens=3)
        with self.assertRaises(AuthError) as error:
            self.store.refresh(tokens['refresh_token'], self.client, RESOURCE)
        self.assertEqual(error.exception.error, 'temporarily_unavailable')
        self.store.authenticate(tokens['access_token'], RESOURCE)
        self.store.TABLE_LIMITS = dict(self.store.TABLE_LIMITS, tokens=4)
        self.assertIn('access_token', self.store.refresh(tokens['refresh_token'], self.client, RESOURCE))

    @unittest.skipUnless(os.name == 'posix', 'POSIX storage mode test requires Linux')
    def test_database_and_parent_must_be_private(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            AuthStore(self.path, RESOURCE, self.portal)
        self.path.chmod(0o600)
        self.path.parent.chmod(0o755)
        try:
            with self.assertRaises(ValueError):
                AuthStore(self.path, RESOURCE, self.portal)
        finally:
            self.path.parent.chmod(0o700)


if __name__ == '__main__':
    unittest.main()

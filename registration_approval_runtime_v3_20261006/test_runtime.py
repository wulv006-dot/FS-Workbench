"""Synthetic accounts only, dedicated temp storage, no production transport."""
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import io
import types
import unittest
from unittest.mock import patch
import runtime as r
from native_integration import bind_functions, taskboard_role


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-registration-runtime-')
        self.root = Path(self.temp.name)
        groups = {'dashboard': str(self.root / 'synthetic-members')}
        self.portal = bind_functions({'secret': 'Synthetic-secret-for-isolated-QA',
            'cookie': 'SYNTHETIC_CUSTOM_AUTH', 'secure': True}, groups)
        encoded = self.portal.apr1_md5('Synthetic-password-42', 'qa123456')
        (self.root / 'synthetic-members').write_text('\n'.join(
            name + ':' + encoded for name in (*self.portal._fs_policy.ADMINS, 'oldreader')) + '\n')
        r.RuntimeStore.initialize_fresh(self.root, self.portal, isolated=True)
        self.store, self.adapter, self.app = r.build(self.root, self.portal, 'https://synthetic.invalid', isolated=True)

    def tearDown(self): self.temp.cleanup()

    def register(self, name='newreader'):
        return self.store.register(name, 'Synthetic-password-42', 'QA', 'Read dashboards')

    def admin(self):
        token, proof = self.adapter.native_login('fstech', 'Synthetic-password-42')
        return token, proof

    def test_import_inert(self):
        with patch.object(r.RuntimeStore, '__init__', side_effect=AssertionError('import wrote DB')):
            importlib.reload(r)

    def test_explicit_temp_boundary(self):
        with self.assertRaises(ValueError): r.RuntimeStore(self.root.parent, self.portal, isolated=True)

    def test_restart_preserves_registration_and_epoch(self):
        request = self.register()
        with self.store.connection() as db:
            before = tuple(db.execute('SELECT id,state,epoch FROM users').fetchone())
        restarted = r.RuntimeStore(self.root, self.portal, isolated=True)
        with restarted.connection() as db:
            self.assertEqual(before, tuple(db.execute('SELECT id,state,epoch FROM users').fetchone()))
            self.assertEqual(3, db.execute('PRAGMA user_version').fetchone()[0])

    def test_unknown_schema_not_repaired(self):
        with self.store.connection() as db:
            db.execute('CREATE TABLE unexpected(secret TEXT)'); db.commit()
        with self.assertRaises(ValueError): r.RuntimeStore(self.root, self.portal, isolated=True)

    def test_db_missing_does_not_create_empty(self):
        self.store.path.unlink()
        with self.assertRaises(FileNotFoundError): self.store.session('x' * 43)
        self.assertFalse(self.store.path.exists())

    def test_pending_cannot_read(self):
        self.register()
        token, csrf = self.store.login('newreader', 'Synthetic-password-42')
        self.assertEqual(403, self.adapter.verify({r.core.COOKIE: token}, 'GET', '/dashboard/')[0])

    def test_approval_readonly_revocation(self):
        request = self.register(); native, proof = self.admin()
        self.store.decide(proof, request['request_id'], 0, 'approve', 'QA approval')
        token, csrf = self.store.login('newreader', 'Synthetic-password-42')
        cookies = {r.core.COOKIE: token}
        code, headers = self.adapter.verify(cookies, 'GET', '/dashboard/')
        self.assertEqual((200, 'readonly'), (code, headers['X-Auth-Role']))
        self.assertTrue(headers['X-Auth-User'].startswith('reg:'))
        self.assertEqual(headers['X-Auth-User'], headers['X-Fc27-User'])
        self.assertEqual(403, self.adapter.verify(cookies, 'POST', '/dashboard/tasks/api/tasks')[0])
        self.store.decide(proof, request['request_id'], 1, 'revoke', 'QA revoke')
        self.assertEqual(401, self.adapter.verify(cookies, 'GET', '/dashboard/')[0])
        restarted = r.RuntimeStore(self.root, self.portal, isolated=True)
        self.assertIsNone(restarted.session(token))

    def test_reserved_native_name_no_upgrade(self):
        for name in ('OLDREADER', 'fstech', 'wulv'):
            with self.assertRaises(r.core.Denied): self.register(name)

    def test_four_admins_custom_cookie_preserved(self):
        for name in self.portal._fs_policy.ADMINS:
            token, proof = self.adapter.native_login(name, 'Synthetic-password-42')
            self.assertEqual('admin', proof.role)
            self.assertEqual(200, self.adapter.verify({'SYNTHETIC_CUSTOM_AUTH': token}, 'POST', '/dashboard/tasks/api/tasks')[0])
        self.assertIn('Secure', self.adapter.native_cookie(token))

    def test_old_fc_cookie_never_identity(self):
        self.assertEqual(401, self.adapter.verify({'fc27sess': 'synthetic-old-session'}, 'GET', '/dashboard/')[0])

    def test_duplicate_approval_and_concurrent_registration(self):
        request = self.register(); _, proof = self.admin()
        self.store.decide(proof, request['request_id'], 0, 'approve', 'QA')
        with self.assertRaises(r.core.Denied): self.store.decide(proof, request['request_id'], 0, 'approve', 'QA')
        results = []
        def register():
            try: self.register('concurrent'); results.append(200)
            except r.core.Denied as exc: results.append(exc.code)
        threads = [threading.Thread(target=register) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual([200, 409], sorted(results))

    def test_csrf_and_failed_registration_no_user(self):
        code, body, headers = self.app.dispatch('GET', '/api/bootstrap')
        token = headers['Set-Cookie'].split(';')[0].split('=', 1)[1]
        cookies = {r.core.COOKIE: token}
        form = json.dumps({'username': 'newreader', 'password': 'short', 'team': 'QA', 'purpose': 'QA'}).encode()
        self.assertEqual(403, self.app.dispatch('POST', '/api/register', cookies=cookies, body=form)[0])
        self.assertEqual(400, self.app.dispatch('POST', '/api/register', cookies=cookies, body=form,
            headers={'Origin': 'https://synthetic.invalid', 'X-CSRF-Token': body['csrf'], 'Content-Type': 'application/json'})[0])
        with self.store.connection() as db: self.assertEqual(0, db.execute('SELECT count(*) FROM users').fetchone()[0])

    def test_native_logout_ledger_all_verifiers(self):
        token, proof = self.admin()
        session, csrf = self.store.new_session(legacy_user=proof.user)
        cookies = {r.core.COOKIE: session, self.portal.CFG['cookie']: token}
        code, body, headers = self.app.dispatch('POST', '/api/logout', cookies=cookies, body=b'{}',
            headers={'Origin': 'https://synthetic.invalid', 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'})
        self.assertEqual(200, code)
        self.assertIsNone(self.adapter.ledger_read_token(token))
        self.assertEqual(401, self.adapter.verify(cookies, 'GET', '/dashboard/')[0])
        self.assertIn('Secure', headers['Set-Cookie'][0])

    def test_https_origin_only(self):
        for origin in ('http://synthetic.invalid', 'https://synthetic.invalid/path', 'https://user@synthetic.invalid'):
            with self.assertRaises(ValueError): r.RuntimeApp(self.adapter, origin)

    def test_insecure_native_configuration_cannot_issue_unsafe_cookie(self):
        self.portal.CFG['secure'] = False
        with self.assertRaises(ValueError): r.RuntimeApp(self.adapter, 'https://synthetic.invalid')
        with self.assertRaises(ValueError): r.build(self.root, self.portal, 'https://synthetic.invalid', isolated=True)
        # Defense in depth, even direct cookie helper does not downgrade attributes.
        for attr in ('Secure','HttpOnly','SameSite=Strict','Path=/'):
            self.assertIn(attr,self.adapter.native_cookie('synthetic-only-token'))

    def test_canonical_read_guard(self):
        for path in ('/dashboard/../admin', '/dashboard/?execute=1', '/dashboard/%252e%252e/admin', '/dashboard/api/arbitrary'):
            self.assertFalse(self.adapter._verify_bound.__func__.__globals__['readonly_allowed']('GET', path, 'dashboard'))

    def test_boot_hook_replaces_fallback_and_old_logout(self):
        from portal_bridge import install
        class Handler:
            def _route(self): return 'old route'
            def _do_verify(self, group=''): raise AssertionError('old FC fallback')
            def _send(self, code, body='', ctype='', headers=None): return code, body, headers
            def _redirect(self, location): return 302, location
        portal = types.SimpleNamespace(**self.portal.__dict__)
        portal.CFG = dict(portal.CFG, data_dir=str(self.root))
        portal.Handler = Handler
        store, adapter, app = install(portal, 'https://synthetic.invalid', isolated=True)
        h = Handler(); h.headers = {'Cookie': 'fc27sess=old', 'X-Original-URI': '/dashboard/'}
        self.assertEqual(401, h._do_verify('dashboard')[0])
        h.command = 'GET'; h.path = '/logout'
        self.assertEqual((302, '/__auth/access/'), h._route())
        h.command = 'POST'; self.assertEqual(405, h._route()[0])
        h.command = 'GET'; h.path = '/access/api/bootstrap'; h.ip = 'synthetic'; h.rfile = io.BytesIO()
        self.assertEqual(200, h._route()[0])
        h.command = 'POST'; h.headers = {'Content-Length': '5000'}
        self.assertEqual(400, h._route()[0])
        with self.assertRaises(ValueError): install(portal, 'https://synthetic.invalid', isolated=True)

    def test_boot_hook_native_denylist_visible_to_old_parser(self):
        from portal_bridge import install
        class Handler:
            def _route(self): pass
            def _do_verify(self, group=''): pass
        portal = types.SimpleNamespace(**self.portal.__dict__)
        portal.CFG = dict(portal.CFG, data_dir=str(self.root)); portal.Handler = Handler
        store, adapter, app = install(portal, 'https://synthetic.invalid', isolated=True)
        token, proof = adapter.native_login('fstech', 'Synthetic-password-42')
        session, csrf = store.new_session(legacy_user=proof.user)
        self.assertIsNotNone(portal.read_token(token))
        adapter.logout(session, {portal.CFG['cookie']: token})
        self.assertIsNone(portal.read_token(token))

    def test_registration_never_grants_admin(self):
        request = self.register()
        with self.assertRaises(r.core.Denied):
            self.store.decide('fstech', request['request_id'], 0, 'approve', 'forged proof')
        with self.store.connection() as db:
            self.assertEqual('pending', db.execute('SELECT state FROM users').fetchone()[0])


if __name__ == '__main__': unittest.main()

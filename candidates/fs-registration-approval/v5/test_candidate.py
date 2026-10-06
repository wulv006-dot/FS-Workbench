import concurrent.futures
from http.cookies import SimpleCookie
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import sqlite3
import unittest
from unittest.mock import patch

from auth_candidate import (ADMINS, Adapter, App, COOKIE, CONTROL, READ_ROUTES, Denied, ITERATIONS,
                            LegacyIdentity, Store, password_hash, password_matches, readonly_allowed)

PASSWORD = 'Synthetic-passphrase-42'


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fs-registration-')
        self.addCleanup(self.tmp.cleanup)
        self.now = 10000
        self.names = set(ADMINS) | {'ExistingReader'}
        self.store = Store(self.tmp.name, reserved_names=lambda: self.names, clock=lambda: self.now)
        self.legacy = None
        self.adapter = Adapter(self.store, legacy_resolver=lambda cookies:
            self.legacy if self.legacy and cookies.get('fixture') == self.legacy.user else None,
            legacy_authorize=lambda identity, method, uri, group: 200 if identity.role == 'admin' or method in ('GET', 'HEAD') and group != 'deploy' else 403)
        self.app = App(self.adapter, 'http://127.0.0.1:18000')
        self.cookies = {}
        self.csrf = ''
        self.boot()

    def call(self, method, path, data=None, headers=None, raw=None):
        h = {'Origin': self.app.origin, 'X-CSRF-Token': self.csrf, 'Content-Type': 'application/json'}
        h.update(headers or {})
        code, result, response = self.app.dispatch(method, path, headers=h, cookies=self.cookies,
            body=raw if raw is not None else json.dumps(data or {}).encode())
        if 'Set-Cookie' in response:
            jar = SimpleCookie(); jar.load(response['Set-Cookie'])
            self.cookies[COOKIE] = jar[COOKIE].value
        if 'csrf' in result:
            self.csrf = result['csrf']
        return code, result, response

    def boot(self):
        code, result, _ = self.call('GET', '/api/bootstrap')
        self.assertEqual(code, 200)
        return result

    def register(self, name='new.reader'):
        code, result, _ = self.call('POST', '/api/register', {
            'username': name, 'password': PASSWORD, 'team': 'Synthetic team', 'purpose': 'Synthetic review'})
        self.assertEqual(code, 200, result)
        return result['request_id']

    def login(self, name='new.reader'):
        code, result, _ = self.call('POST', '/api/login', {'username': name, 'password': PASSWORD})
        self.assertEqual(code, 200, result)
        return result

    def admin(self, name='fstech'):
        self.cookies = {'fixture': name}
        self.legacy = LegacyIdentity(name, ('dashboard', 'deploy'), 'admin')
        self.boot()

    def decision(self, rid, version=0, action='approve', **extra):
        data = {'request_id': rid, 'version': version, 'action': action, 'reason': 'Synthetic manual identity checked'}
        data.update(extra)
        return self.call('POST', '/api/decision', data)

    def test_pending_cannot_read_business_and_no_auto_login(self):
        self.register()
        self.assertEqual(self.boot()['account']['role'], 'guest')
        result = self.login()
        self.assertEqual(result['account']['state'], 'pending')
        for method in ('GET', 'HEAD', 'POST'):
            self.assertEqual(self.adapter.verify(self.cookies, method, '/dashboard/')[0], 403)
        self.assertEqual(self.call('GET', '/api/requests')[0], 403)
        self.assertEqual(self.call('GET', '/api/audit')[0], 403)

    def test_approve_current_session_readonly_then_immediate_revoke(self):
        rid = self.register(); self.login()
        user_cookies = self.cookies.copy()
        self.admin()
        self.assertEqual(self.decision(rid)[0], 200)
        code, headers = self.adapter.verify(user_cookies, 'GET', '/dashboard/index.html')
        self.assertEqual(code, 200)
        self.assertTrue(headers['X-Auth-User'].startswith('reg:'))
        self.assertEqual(headers['X-Auth-Role'], 'readonly')
        self.assertEqual(headers['X-Auth-Groups'], 'dashboard')
        for method, uri, group in [('POST', '/dashboard/', ''), ('GET', '/dashboard/', 'deploy'),
                                  ('GET', '/dashboard/admin/', ''), ('GET', '/dashboard/collect/', ''),
                                  ('GET', '/dashboard/marketing/?action=refresh', '')]:
            self.assertEqual(self.adapter.verify(user_cookies, method, uri, group)[0], 403)
        code = self.call('POST', '/api/revoke', {'request_id': rid, 'version': 1, 'reason': 'Synthetic revoked'})[0]
        self.assertEqual(code, 200)
        self.assertIsNone(self.store.session(user_cookies[COOKIE]))
        self.legacy = None
        self.assertEqual(self.adapter.verify(user_cookies, 'GET', '/dashboard/')[0], 401)

    def test_all_four_admins_kept_without_registration_rows(self):
        self.assertEqual(ADMINS, {'wulv', 'chenchao', 'DY', 'fstech'})
        for name in ADMINS:
            self.admin(name)
            self.assertEqual(self.call('GET', '/api/requests')[0], 200)
            code, headers = self.adapter.verify(self.cookies, 'POST', '/dashboard/admin/', 'deploy')
            self.assertEqual(code, 200)
            self.assertEqual(headers['X-Auth-User'], name)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_existing_readonly_kept_not_approver(self):
        self.legacy = LegacyIdentity('ExistingReader', ('dashboard',), 'readonly')
        self.cookies = {'fixture': 'ExistingReader'}; self.boot()
        self.assertEqual(self.adapter.verify(self.cookies, 'GET', '/dashboard/')[0], 200)
        self.assertEqual(self.adapter.verify(self.cookies, 'POST', '/dashboard/')[0], 403)
        self.assertEqual(self.call('GET', '/api/requests')[0], 403)

    def test_reserved_names_casefold_cannot_register_or_login(self):
        for name in ('WULV', 'ChenChao', 'dy', 'FSTECH', 'existingreader'):
            with self.assertRaises(Denied) as failure:
                self.store.register(name, PASSWORD, 'team', 'purpose')
            self.assertIn(failure.exception.code, (400, 409))
            with self.assertRaises(Denied):
                self.store.login(name, PASSWORD)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_duplicate_name_no_overwrite_password_or_role(self):
        self.register('New.Reader')
        with self.assertRaises(Denied):
            self.store.register('new.reader', 'Other-synthetic-password', 'evil', 'fake')
        self.login('NEW.READER')
        status = self.boot()['account']
        self.assertEqual(status['state'], 'pending')
        self.assertEqual(status['team'], 'Synthetic team')

    def test_client_cannot_assign_admin_or_identity_header(self):
        data = {'username': 'imposter', 'password': PASSWORD, 'team': 'team', 'purpose': 'reason', 'role': 'admin'}
        self.assertEqual(self.call('POST', '/api/register', data)[0], 400)
        self.register(); self.login()
        self.assertEqual(self.call('GET', '/api/requests', headers={
            'X-Auth-User': 'fstech', 'X-Auth-Role': 'admin', 'X-Fc27-Role': 'admin'})[0], 403)
        with self.assertRaises(Denied):
            self.store.decide('fstech', 'a'*36, 0, 'approve', 'fake')

    def test_no_fc_session_or_same_name_identity_fallback(self):
        self.cookies = {'fc27sess': 'synthetic-old-cookie', 'MMOEXP_AUTH': 'synthetic-invalid-cookie'}
        self.assertEqual(self.adapter.verify(self.cookies, 'GET', '/dashboard/')[0], 401)
        self.assertEqual(self.call('GET', '/api/requests')[0], 401)

    def test_duplicate_and_stale_approval_no_second_audit(self):
        rid = self.register(); self.admin()
        self.assertEqual(self.decision(rid)[0], 200)
        self.assertEqual(self.decision(rid)[0], 409)
        self.assertEqual(self.decision(rid, 1, 'reject')[0], 409)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action='approve'").fetchone()[0], 1)

    def test_concurrent_approval_only_one_winner(self):
        rid = self.register()
        actor = LegacyIdentity('fstech', ('dashboard',), 'admin')
        def approve(_):
            try:
                self.store.decide(actor, rid, 0, 'approve', 'concurrent synthetic check')
                return 200
            except Denied as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(approve, range(4)))
        self.assertEqual(sorted(results), [200, 409, 409, 409])
        self.assertEqual(len(self.store.listing('audit')), 2)

    def test_concurrent_registration_unique_identity(self):
        def register(_):
            try:
                self.store.register('same.person', PASSWORD, 'team', 'reason')
                return 200
            except Denied as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(sorted(pool.map(register, range(3))), [200, 409, 409])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)

    def test_csrf_and_origin_registration_login_approval_logout(self):
        rid = self.register()
        data = {'username': 'new.reader', 'password': PASSWORD}
        for headers in ({'X-CSRF-Token': ''}, {'Origin': 'https://evil.invalid'}, {'Origin': ''}):
            self.assertEqual(self.call('POST', '/api/login', data, headers=headers)[0], 403)
        self.admin()
        self.assertEqual(self.decision(rid, extra='admin')[0], 400)
        payload = {'request_id': rid, 'version': 0, 'action': 'approve', 'reason': 'Synthetic check'}
        self.assertEqual(self.call('POST', '/api/decision', payload, headers={'X-CSRF-Token':'bad'})[0], 403)
        self.assertEqual(self.call('POST', '/api/logout', headers={'Origin':''})[0], 403)
        self.legacy = None; self.cookies = {}; self.boot()
        reg = {'username':'other.user', 'password':PASSWORD, 'team':'team', 'purpose':'reason'}
        self.assertEqual(self.call('POST', '/api/register', reg, headers={'X-CSRF-Token':'bad'})[0], 403)

    def test_csrf_bound_session_and_login_rotation(self):
        self.register()
        guest_cookie, guest_csrf = self.cookies[COOKIE], self.csrf
        self.login()
        self.assertNotEqual(guest_cookie, self.cookies[COOKIE])
        self.assertNotEqual(guest_csrf, self.csrf)
        self.assertIsNone(self.store.session(guest_cookie))
        self.assertEqual(self.call('POST', '/api/logout', headers={'X-CSRF-Token':guest_csrf})[0], 403)

    def test_logout_revokes_and_cookie_expires(self):
        self.register(); self.login(); old = self.cookies[COOKIE]
        code, _, response = self.call('POST', '/api/logout')
        self.assertEqual(code, 200)
        self.assertIsNone(self.store.session(old))
        self.assertIn('Max-Age=0', response['Set-Cookie'])

    def test_fixed_session_expiry(self):
        self.register(); self.login()
        old = self.cookies[COOKIE]
        self.now += 43200
        self.assertIsNone(self.store.session(old))
        self.assertEqual(self.adapter.verify(self.cookies, 'GET', '/dashboard/')[0], 401)

    def test_password_salted_safe_hash_and_wrong_password(self):
        first, second = password_hash(PASSWORD), password_hash(PASSWORD)
        self.assertNotEqual(first, second)
        self.assertEqual(first.split('$')[1], str(ITERATIONS))
        self.assertNotIn(PASSWORD, first)
        self.assertTrue(password_matches(PASSWORD, first))
        self.assertFalse(password_matches('Wrong-synthetic-password', first))
        self.assertFalse(password_matches(PASSWORD, 'malformed'))

    def test_invalid_input_and_json_duplicate_keys(self):
        for name in ('ab', 'ＦSTECH', '../admin', 'reg:123', 'a\nxx', 42):
            with self.assertRaises(Denied):
                self.store.register(name, PASSWORD, 'team', 'reason')
        for password in ('short', 'a'*129, None):
            with self.assertRaises(Denied):
                self.store.register('valid.user', password, 'team', 'reason')
        for purpose in ('', 'a\x00b', 'x'*241):
            with self.assertRaises(Denied):
                self.store.register('valid.user', PASSWORD, 'team', purpose)
        for raw in (b'{"username":"abc","username":"wulv"}', b'[]', b'\xff', b'{' , b'x'*4097):
            self.assertEqual(self.call('POST', '/api/register', raw=raw)[0], 400)

    def test_registration_and_approval_audit_failure_atomic(self):
        with patch.object(self.store, 'audit', side_effect=OSError('synthetic-fault')):
            with self.assertRaises(OSError):
                self.store.register('atomic.user', PASSWORD, 'team', 'reason')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 0)
        rid = self.register(); self.admin()
        with patch.object(self.store, 'audit', side_effect=OSError('synthetic-fault')):
            self.assertEqual(self.decision(rid)[0], 503)
        rows = self.store.listing('requests')
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertEqual(rows[0]['version'], 0)

    def test_reserved_source_failure_closes_registration_and_verify(self):
        self.store.reserved_names = lambda: None
        data = {'username':'new.user','password':PASSWORD,'team':'team','purpose':'reason'}
        self.assertEqual(self.call('POST', '/api/register', data)[0], 503)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_later_name_collision_denies_business(self):
        rid = self.register(); self.login(); user_cookies = self.cookies.copy()
        self.admin(); self.decision(rid)
        self.legacy = None
        self.names.add('NEW.READER')
        self.assertEqual(self.adapter.verify(user_cookies, 'GET', '/dashboard/')[0], 403)

    def test_legacy_revocation_invalidates_approval_csrf_context(self):
        rid = self.register(); self.admin()
        self.legacy = None
        self.assertEqual(self.decision(rid)[0], 401)
        self.boot()
        self.assertEqual(self.decision(rid)[0], 403)

    def test_unknown_admin_and_two_principals_fail_closed(self):
        self.legacy = LegacyIdentity('unknown.admin', ('dashboard',), 'admin')
        self.cookies['fixture'] = 'unknown.admin'
        self.assertEqual(self.call('GET', '/api/bootstrap')[0], 503)
        self.legacy = None; self.cookies = {}; self.boot(); rid = self.register(); self.login()
        self.legacy = LegacyIdentity('fstech', ('dashboard',), 'admin')
        self.cookies['fixture'] = 'fstech'
        self.assertEqual(self.call('GET', '/api/bootstrap')[0], 403)
        self.assertEqual(self.adapter.verify(self.cookies, 'GET', '/dashboard/')[0], 403)

    def test_reject_and_reapply_preserve_history(self):
        rid = self.register(); self.login(); old = self.cookies.copy()
        self.admin(); self.assertEqual(self.decision(rid, action='reject')[0], 200)
        self.legacy = None; self.cookies = old; self.boot()
        self.assertEqual(self.boot()['account']['state'], 'rejected')
        code, result, _ = self.call('POST', '/api/apply', {'purpose':'Synthetic revised use'})
        self.assertEqual(code, 200)
        self.assertNotEqual(result['request_id'], rid)
        self.assertEqual(self.call('POST', '/api/apply', {'purpose':'double'})[0], 409)
        self.assertEqual(len(self.store.listing('requests')), 2)
        self.assertEqual([r['action'] for r in self.store.listing('audit')], ['register', 'reject', 'apply'])

    def test_revoke_relogin_reapply_requires_new_approval(self):
        rid = self.register(); self.admin(); self.decision(rid)
        self.call('POST', '/api/revoke', {'request_id':rid,'version':1,'reason':'Synthetic revoked'})
        self.legacy = None; self.cookies = {}; self.boot(); self.login()
        self.assertEqual(self.adapter.verify(self.cookies, 'GET', '/dashboard/')[0], 403)
        code, result, _ = self.call('POST', '/api/apply', {'purpose':'new synthetic purpose'})
        self.assertEqual(code, 200)
        self.assertEqual(self.adapter.verify(self.cookies, 'GET', '/dashboard/')[0], 403)
        self.assertNotEqual(result['request_id'], rid)

    def test_approval_parameters_strict(self):
        rid = self.register(); self.admin()
        for version in (True, '0', -1, 0.0):
            self.assertEqual(self.decision(rid, version=version)[0], 400)
        for action in ('admin', 'deploy', 'revoke', 'readonly'):
            self.assertEqual(self.decision(rid, action=action)[0], 400)
        self.assertEqual(self.decision(rid, reason='')[0], 400)
        self.assertEqual(self.decision('malformed')[0], 400)

    def test_login_and_register_rate_limited(self):
        for _ in range(6):
            self.assertEqual(self.call('POST', '/api/login', {'username':'missing.user','password':PASSWORD})[0], 401)
        self.assertEqual(self.call('POST', '/api/login', {'username':'missing.user','password':PASSWORD})[0], 429)
        self.now += 301
        self.assertEqual(self.call('POST', '/api/login', {'username':'missing.user','password':PASSWORD})[0], 401)
        for _ in range(6):
            self.assertEqual(self.call('POST', '/api/register', {'username':'wulv','password':PASSWORD,'team':'t','purpose':'p'})[0], 409)
        self.assertEqual(self.call('POST', '/api/register', {'username':'wulv','password':PASSWORD,'team':'t','purpose':'p'})[0], 429)

    def test_readonly_encoded_paths_controls_unknown_routes(self):
        rid = self.register(); self.login(); cookies = self.cookies.copy()
        self.admin(); self.decision(rid); self.legacy = None
        for uri in ('/dashboard/marketing/%61dmin/', '/dashboard/marketing/%252e%252e/admin',
                    '/dashboard/marketing/%255cadmin', '//evil.invalid/dashboard/',
                    '/dashboard/marketing/%0a', '/unreviewed-api/', '/dashboard/marketing/?CMD=run',
                    '/dashboard/marketing/%2525252561dmin', 'https://evil.invalid/dashboard/',
                    '/dashboard/marketing/unreviewed-get-api'):
            self.assertEqual(self.adapter.verify(cookies, 'GET', uri)[0], 403, uri)
        for uri in ('/dashboard/', '/dashboard/index.html', '/dashboard/analytics/', '/dashboard/marketing/data.json', '/dashboard/weekly/'):
            self.assertEqual(self.adapter.verify(cookies, 'HEAD', uri)[0], 200, uri)

    def test_audit_and_admin_listing_no_secrets(self):
        rid = self.register(); self.admin(); self.decision(rid)
        for route in ('/api/requests', '/api/audit'):
            code, result, _ = self.call('GET', route)
            self.assertEqual(code, 200)
            output = json.dumps(result)
            for secret in (PASSWORD, self.cookies[COOKIE], self.csrf, 'pbkdf2_sha256', 'token_hash'):
                self.assertNotIn(secret, output)
            self.assertEqual(self.call('GET', route + '?after=-1')[0], 400)

    def test_methods_cookie_and_error_contract(self):
        self.assertEqual(self.call('GET', '/api/decision')[0], 405)
        self.assertEqual(self.call('POST', '/api/requests')[0], 405)
        self.assertEqual(self.call('GET', '/api/verify')[0], 404)
        code, _, headers = self.call('GET', '/api/bootstrap')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertIn('Path=/', headers['Set-Cookie'])

    def test_import_inert_and_production_path_rejected(self):
        code = "import socket, sqlite3; from unittest.mock import patch; " \
               "p1=patch.object(socket.socket,'bind',side_effect=AssertionError('bind')); " \
               "p2=patch.object(sqlite3,'connect',side_effect=AssertionError('db')); " \
               "p1.start();p2.start();import auth_candidate;import preview"
        run = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        with self.assertRaises(ValueError):
            Store(Path(__file__).parent, reserved_names=lambda: set())
        with self.assertRaises(ValueError):
            Store(self.tmp.name, reserved_names=lambda: set())

    def test_v2_blank_bare_case_encoded_repeated_control_query_matrix(self):
        # 4 control names x 3 casings x 8 representations x 9 routes x 2 methods.
        count = 0
        for name in ('action', 'op', 'cmd', 'command'):
            for key in (name, name.upper(), name.title()):
                encoded = ''.join('%%%02x' % ord(c) for c in key)
                forms = (key, key+'=', key+'=run', key+'=&'+key+'=run',
                         'mode=business&'+key, encoded+'=', '%25'+encoded[1:]+'=',
                         'mode=business%26'+encoded+'%3D')
                for query in forms:
                    for path in READ_ROUTES:
                        for method in ('GET', 'HEAD'):
                            with self.subTest(method=method,path=path,query=query):
                                self.assertFalse(readonly_allowed(method, path+'?'+query))
                            count += 1
        self.assertEqual(count, 4 * 3 * 8 * len(READ_ROUTES) * 2)

    def test_v2_full_control_keys_unknown_duplicate_and_nested_paths(self):
        for key in CONTROL:
            for query in (key, key+'=', key.upper()+'=1', 'mode=google&'+key, 'filter['+key+']=1'):
                for path in READ_ROUTES:
                    self.assertFalse(readonly_allowed('GET', path+'?'+query), (path,query))
        for path in ('/dashboard/marketing/admin/', '/dashboard/marketing/%61dmin/',
                     '/dashboard/marketing/%252e%252e/', '/dashboard/marketing/%25252e%25252e/',
                     '/dashboard/marketing/%2Fadmin/', '/dashboard/marketing/%255cadmin/'):
            for query in ('action', 'CMD=', 'mode=business'):
                self.assertFalse(readonly_allowed('HEAD',path+'?'+query))
        for query in ('collect=1','unknown=', 'mode=business&mode=google',
                      'MODE=business&mode=google','mode', 'mode=', 'mode=google;cmd',
                      'mode=google%26cmd', 'mode=google%2526cmd', 'mode=google%23cmd=run'):
            self.assertFalse(readonly_allowed('GET','/dashboard/marketing/?'+query), query)
        for query in ('mode=business', 'mode=google&brand=rsorder&days=7',
                      'scope=all-sites&period=7d&category=trend', 'MODE=google',
                      '%6dode=business'):
            for path in READ_ROUTES:
                for method in ('GET','HEAD'):
                    self.assertTrue(readonly_allowed(method,path+'?'+query), (path,query))

    def test_v2_adapter_enforces_blank_controls_for_approved_user(self):
        rid=self.register(); self.login(); cookies=self.cookies.copy()
        self.admin(); self.decision(rid); self.legacy=None
        for query in ('action','action=','CMD=','op=','command=','%2563md=', 'collect=1'):
            for method in ('GET','HEAD'):
                self.assertEqual(self.adapter.verify(cookies,method,'/dashboard/marketing/?'+query)[0],403)
        self.assertEqual(self.adapter.verify(cookies,'GET','/dashboard/marketing/?mode=google&brand=rsorder')[0],200)

    def test_v2_rejected_request_and_audit_keep_original_snapshot(self):
        rid=self.register(); self.login(); user_cookies=self.cookies.copy()
        uid=self.boot()['account']['id']
        self.admin(); self.decision(rid,action='reject',reason='Synthetic reason A')
        self.legacy=None; self.cookies=user_cookies; self.boot()
        self.assertEqual(self.call('POST','/api/apply',{'purpose':'Purpose B'})[0],200)
        rows=self.store.listing('requests')
        self.assertEqual([r['purpose'] for r in rows],['Synthetic review','Purpose B'])
        self.assertEqual([r['team'] for r in rows],['Synthetic team','Synthetic team'])
        self.assertEqual([r['name'] for r in rows],['new.reader','new.reader'])
        audit=self.store.listing('audit')
        self.assertEqual([a['purpose'] for a in audit],['Synthetic review','Synthetic review','Purpose B'])
        self.assertEqual(audit[1]['reason'],'Synthetic reason A')
        self.assertEqual(self.store.status(uid)['request']['purpose'],'Purpose B')

    def test_v2_approve_revoke_reapply_and_snapshot_sql_immutable(self):
        rid=self.register(); self.admin(); self.decision(rid,reason='Synthetic approve A')
        self.call('POST','/api/revoke',{'request_id':rid,'version':1,'reason':'Synthetic revoke A'})
        self.legacy=None; self.cookies={}; self.boot(); self.login()
        self.call('POST','/api/apply',{'purpose':'Purpose B after revocation'})
        audit=self.store.listing('audit')
        self.assertEqual([r['purpose'] for r in audit],['Synthetic review']*3+['Purpose B after revocation'])
        self.assertEqual([r['reason'] for r in audit][1:3],['Synthetic approve A','Synthetic revoke A'])
        for statement, args in (
            ('UPDATE requests SET purpose=? WHERE id=?',('tampered',rid)),
            ('UPDATE requests SET team=? WHERE id=?',('tampered',rid)),
            ('UPDATE requests SET applicant_name=? WHERE id=?',('tampered',rid)),
            ('DELETE FROM requests WHERE id=?',(rid,)),
            ('UPDATE audit SET reason=? WHERE request_id=?',('tampered',rid)),
            ('DELETE FROM audit WHERE request_id=?',(rid,))):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.store.transaction() as db:
                    db.execute(statement,args)
        self.assertEqual(self.store.listing('requests')[0]['purpose'],'Synthetic review')
        self.assertEqual(len(self.store.listing('audit')),4)

    def test_v2_concurrent_reapply_and_decisions_keep_snapshots(self):
        rid=self.register(); self.login()
        session=self.store.session(self.cookies[COOKIE]); uid=session['user_id']; proof=session['token_hash']
        actor=LegacyIdentity('fstech',('dashboard',),'admin')
        self.store.decide(actor,rid,0,'reject','Synthetic rejected A')
        barrier=threading.Barrier(3)
        def apply(index):
            barrier.wait(timeout=5)
            try:
                result=self.store.apply(uid,'Concurrent purpose '+str(index),proof)
                return 200,result['request_id']
            except Denied as exc:
                return exc.code,None
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(apply,range(3)))
        self.assertEqual(sorted(code for code,_ in results),[200,409,409])
        new_rid=next(r for code,r in results if code==200)
        barrier=threading.Barrier(2)
        def decide(action):
            barrier.wait(timeout=5)
            try:
                self.store.decide(actor,new_rid,0,action,'Concurrent decision '+action)
                return 200
            except Denied as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(decide,('approve','reject'))),[200,409])
        rows=self.store.listing('requests'); audit=self.store.listing('audit')
        self.assertEqual(rows[0]['purpose'],'Synthetic review')
        self.assertEqual([r['purpose'] for r in audit[:2]],['Synthetic review','Synthetic review'])
        self.assertEqual(audit[2]['purpose'],rows[1]['purpose'])
        self.assertEqual(audit[3]['purpose'],rows[1]['purpose'])
        self.assertEqual(len(audit),4)

    def test_v2_concurrent_revoke_and_reapply_old_session_fail_closed(self):
        rid=self.register(); self.login()
        session=self.store.session(self.cookies[COOKIE]); uid=session['user_id']; proof=session['token_hash']
        actor=LegacyIdentity('fstech',('dashboard',),'admin')
        self.store.decide(actor,rid,0,'approve','Synthetic approve')
        barrier=threading.Barrier(2)
        def change(action):
            barrier.wait(timeout=5)
            try:
                if action=='revoke': self.store.decide(actor,rid,1,'revoke','Synthetic revoke')
                else: self.store.apply(uid,'Old session purpose',proof)
                return action,200
            except Denied as exc:
                return action,exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=dict(pool.map(change,('revoke','apply')))
        self.assertEqual(results['revoke'],200)
        self.assertIn(results['apply'],(401,409))
        self.assertEqual(len(self.store.listing('requests')),1)
        self.assertEqual([a['action'] for a in self.store.listing('audit')],['register','approve','revoke'])
        self.assertTrue(all(a['purpose']=='Synthetic review' for a in self.store.listing('audit')))

    def test_v2_inflight_reapply_rechecks_session_after_revoke(self):
        rid=self.register(); self.login()
        uid=self.store.session(self.cookies[COOKIE])['user_id']
        actor=LegacyIdentity('fstech',('dashboard',),'admin')
        self.store.decide(actor,rid,0,'reject','Synthetic reject')
        entered,release=threading.Event(),threading.Event()
        original=self.store.apply
        def paused(*args):
            entered.set()
            if not release.wait(timeout=5): raise RuntimeError('test synchronization timeout')
            return original(*args)
        with patch.object(self.store,'apply',side_effect=paused):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.call,'POST','/api/apply',{'purpose':'Stale inflight purpose'})
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    # Simulate session revocation after transport validation but before the write lock.
                    self.store.logout(self.cookies[COOKIE])
                finally:
                    release.set()
                self.assertEqual(future.result(timeout=5)[0],401)
        self.assertEqual(self.store.status(uid)['state'],'rejected')
        self.assertEqual(len(self.store.listing('requests')),1)

    def test_v2_reapply_audit_failure_rolls_back_current_and_snapshot(self):
        rid=self.register(); self.login()
        session=self.store.session(self.cookies[COOKIE]); uid=session['user_id']
        actor=LegacyIdentity('fstech',('dashboard',),'admin')
        self.store.decide(actor,rid,0,'reject','Synthetic reject')
        with patch.object(self.store,'audit',side_effect=OSError('Synthetic audit failure')):
            self.assertEqual(self.call('POST','/api/apply',{'purpose':'Purpose B rollback'})[0],503)
        self.assertEqual(self.store.status(uid)['purpose'],'Synthetic review')
        self.assertEqual(self.store.status(uid)['state'],'rejected')
        self.assertEqual(len(self.store.listing('requests')),1)
        self.assertEqual(len(self.store.listing('audit')),2)

    def test_v2_verify_one_snapshot_and_revoke_reapproval_no_old_session_revival(self):
        rid=self.register(); self.login(); old_cookies=self.cookies.copy()
        session=self.store.session(old_cookies[COOKIE]); uid=session['user_id']
        self.assertEqual(session['live_state'],'pending')
        actor=LegacyIdentity('fstech',('dashboard',),'admin')
        self.store.decide(actor,rid,0,'approve','Synthetic A approve')
        # No separate status read can mix the old token with a new authorization epoch.
        with patch.object(self.store,'status',side_effect=AssertionError('must not perform second state read')):
            self.assertEqual(self.adapter.verify(old_cookies,'GET','/dashboard/')[0],200)
        self.store.decide(actor,rid,1,'revoke','Synthetic A revoke')
        token,_=self.store.login('new.reader',PASSWORD)
        new_session=self.store.session(token)
        new_rid=self.store.apply(uid,'Purpose B with new session',new_session['token_hash'])['request_id']
        self.store.decide(actor,new_rid,0,'approve','Synthetic B approve')
        self.assertEqual(self.adapter.verify(old_cookies,'GET','/dashboard/')[0],401)
        self.assertEqual(self.adapter.verify({COOKIE:token},'GET','/dashboard/')[0],200)
        self.assertEqual([r['purpose'] for r in self.store.listing('requests')],
                         ['Synthetic review','Purpose B with new session'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

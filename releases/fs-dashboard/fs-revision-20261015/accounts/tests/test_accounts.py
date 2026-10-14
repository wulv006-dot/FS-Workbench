"""Synthetic accounts and HTTP dispatcher; never opens production storage."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'candidate/runtime'), str(HERE / 'candidate/runtime/vendor')]
import runtime
import account_management
import module_permissions
import consumer_seams
from native_integration import bind_functions
import native_access_policy as policy

OLD = 'Synthetic-password-42'
NEW = 'Synthetic-new-password-91'


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-registration-accounts-')
        self.root = Path(self.temp.name)
        self.file = self.root / 'members'
        self.gate = self.root / 'gate.sqlite3'
        self.portal = bind_functions({'secret': 'Synthetic-only-accounts-QA', 'cookie': 'SYNTHETIC_AUTH', 'secure': True,
            'data_dir': str(self.root), 'account_gate_db': str(self.gate)}, {'dashboard': str(self.file)}, policy)
        encoded = self.portal.apr1_md5(OLD, 'qa123456')
        self.file.write_text(''.join(name + ':' + encoded + '\n' for name in (*policy.ADMINS, 'mmoexp')), encoding='utf-8')
        with closing(sqlite3.connect(self.gate)) as db:
            db.execute('CREATE TABLE users(username TEXT PRIMARY KEY,pw_scheme TEXT,salt TEXT,pwhash TEXT,is_banned INTEGER)')
            db.executemany('INSERT INTO users VALUES(?,?,?,?,?)', [(name, 'pbkdf2', 'synthetic', 'synthetic', 0) for name in ('fc27admin', 'chenchao', 'wulv', 'DY', 'mmoexp', 'dongwenxin')])
            db.commit()
        runtime.RuntimeStore.initialize_fresh(self.root, self.portal, isolated=True)
        self.store, self.adapter, self.app = runtime.build(self.root, self.portal, 'https://synthetic.invalid', isolated=True)
        self.token, self.actor = self.adapter.native_login('wulv', OLD)

    def tearDown(self):
        self.temp.cleanup()

    def form(self, subject, **changes):
        row = self.store.accounts.row(subject)
        return dict(subject=subject, revision=row['revision'], admin_password=OLD, reason='Synthetic QA', **changes)

    def reset(self, subject, **changes):
        form = self.form(subject, new_password=NEW, confirm_password=NEW)
        form.update(changes)
        return self.store.accounts.mutate(self.actor, 'password', form)

    def grants(self, subject, enabled=True, **changes):
        modules = dict(module_permissions.DEFAULT, **changes)
        return self.store.accounts.mutate(self.actor, 'permissions', self.form(subject, enabled=enabled, modules=modules))

    def denied(self, code, callback):
        with self.assertRaises(runtime.core.Denied) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)

    def http(self, route, form=None, *, token=None, origin='https://synthetic.invalid', csrf=True):
        cookies = {'SYNTHETIC_AUTH': self.token if token is None else token}
        status, bootstrap, headers = self.app.dispatch('GET', '/api/bootstrap', cookies=cookies)
        if status != 200:
            return status, bootstrap, headers
        session = headers['Set-Cookie'].split(';', 1)[0].split('=', 1)[1]
        cookies[runtime.core.COOKIE] = session
        return self.app.dispatch('GET' if form is None else 'POST', route, cookies=cookies,
            headers={'origin': origin, 'content-type': 'application/json', 'x-csrf-token': bootstrap['csrf'] if csrf else 'invalid'},
            body=b'' if form is None else json.dumps(form).encode())

    def register(self):
        req = self.store.register('newreader', OLD, 'QA', 'Read')
        token, _ = self.store.login('newreader', OLD)
        self.assertTrue(token)  # Pending applicant can still view progress.
        self.store.decide(self.actor, req['request_id'], 0, 'approve', 'QA')
        return 'reg:' + self.store.listing('requests')[0]['user_id']

    def test_complete_seven_account_inventory_without_credentials(self):
        rows = self.store.accounts.listing()
        self.assertEqual(7, len(rows))
        self.assertEqual({'wulv', 'chenchao', 'DY', 'fstech'}, {row['name'] for row in rows if row['role'] == 'admin'})
        self.assertEqual({'fc27admin', 'dongwenxin'}, {row['name'] for row in rows if not row['enabled']})
        for row in rows:
            self.assertFalse(any(key.startswith('_') or key in ('password', 'salt', 'pwhash') for key in row))
        self.assertNotIn(OLD, json.dumps(rows))

    def test_reset_native_blocks_old_password_and_all_old_signed_sessions(self):
        before = self.file.read_bytes(), self.gate.read_bytes()
        first, _ = self.adapter.native_login('mmoexp', OLD)
        second, _ = self.adapter.native_login('mmoexp', OLD)
        self.reset('native:mmoexp')
        self.assertFalse(self.store.accounts.authenticate('mmoexp', OLD))
        self.assertTrue(self.store.accounts.authenticate('mmoexp', NEW))
        for token in (first, second):
            self.assertEqual(401, self.adapter.verify({'SYNTHETIC_AUTH': token}, 'GET', '/dashboard/')[0])
        current, _ = self.adapter.native_login('mmoexp', NEW)
        self.assertEqual(200, self.adapter.verify({'SYNTHETIC_AUTH': current}, 'GET', '/dashboard/')[0])
        self.assertEqual(before, (self.file.read_bytes(), self.gate.read_bytes()))

    def test_self_password_reset_http_clears_both_cookies(self):
        form = self.form('native:wulv', new_password=NEW, confirm_password=NEW)
        code, result, headers = self.http('/api/account-password', form)
        self.assertEqual(200, code)
        self.assertTrue(result['self_changed'])
        self.assertEqual(2, len(headers['Set-Cookie']))
        self.assertTrue(all('Max-Age=0' in cookie for cookie in headers['Set-Cookie']))
        self.assertEqual(401, self.adapter.verify({'SYNTHETIC_AUTH': self.token}, 'GET', '/dashboard/')[0])
        self.assertTrue(self.adapter.native_login('wulv', NEW))

    def test_legacy_only_requires_password_then_explicit_activation(self):
        self.denied(400, lambda: self.grants('native:dongwenxin'))
        self.reset('native:dongwenxin')
        self.assertFalse(self.store.accounts.authenticate('dongwenxin', NEW))
        self.grants('native:dongwenxin')
        token, _ = self.adapter.native_login('dongwenxin', NEW)
        self.assertEqual(200, self.adapter.verify({'SYNTHETIC_AUTH': token}, 'GET', '/dashboard/')[0])

    def test_native_module_none_readonly_and_own_task_editor(self):
        old, _ = self.adapter.native_login('mmoexp', OLD)
        self.grants('native:mmoexp', business='none', tasks='editor')
        self.assertEqual(401, self.adapter.verify({'SYNTHETIC_AUTH': old}, 'GET', '/dashboard/')[0])
        token, _ = self.adapter.native_login('mmoexp', OLD)
        cookies = {'SYNTHETIC_AUTH': token}
        self.assertEqual(403, self.adapter.verify(cookies, 'GET', '/dashboard/')[0])
        code, headers = self.adapter.verify(cookies, 'PATCH', '/dashboard/tasks/api/tasks/1')
        self.assertEqual((200, 'editor'), (code, headers['X-Auth-Role']))
        self.assertEqual(('editor', True), consumer_seams.taskboard_member(None, 'mmoexp', 'editor', None, policy))
        self.assertEqual(403, self.adapter.verify(cookies, 'DELETE', '/dashboard/tasks/api/tasks/1')[0])
        self.assertEqual(403, self.adapter.verify(cookies, 'POST', '/tools/fc27-players/api/execute')[0])
        self.assertEqual(200, self.adapter.verify(cookies, 'GET', '/d4/')[0])

    def test_registration_password_and_grants_survive_restart(self):
        subject = self.register()
        old, _ = self.store.login('newreader', OLD)
        self.reset(subject)
        self.denied(401, lambda: self.store.login('newreader', OLD))
        self.assertIsNone(self.store.session(old))
        self.grants(subject, business='none', green_plan='editor')
        store, adapter, _ = runtime.build(self.root, self.portal, 'https://synthetic.invalid', isolated=True)
        token, _ = store.login('newreader', NEW)
        self.assertEqual(403, adapter.verify({runtime.core.COOKIE: token}, 'GET', '/dashboard/')[0])
        self.assertEqual(200, adapter.verify({runtime.core.COOKIE: token}, 'PATCH', '/dashboard/tasks/api/green-plan/tasks/G01')[0])
        self.assertEqual('none', store.status(subject[4:])['permissions']['modules']['business'])

    def test_unapproved_registration_is_not_activated_by_permissions(self):
        request = self.store.register('newreader', OLD, 'QA', 'Read')
        subject = 'reg:' + self.store.listing('requests')[0]['user_id']
        self.denied(403, lambda: self.grants(subject))
        self.reset(subject)
        self.assertTrue(self.store.login('newreader', NEW))

    def test_password_validation_reauthentication_and_stale_cas(self):
        form = self.form('native:mmoexp', new_password=NEW, confirm_password=NEW)
        self.denied(401, lambda: self.store.accounts.mutate(self.actor, 'password', dict(form, admin_password='wrong')))
        self.denied(400, lambda: self.store.accounts.mutate(self.actor, 'password', dict(form, new_password='short', confirm_password='short')))
        self.denied(400, lambda: self.store.accounts.mutate(self.actor, 'password', dict(form, confirm_password='different')))
        self.store.accounts.mutate(self.actor, 'password', form)
        self.denied(409, lambda: self.store.accounts.mutate(self.actor, 'password', form))
        self.assertEqual(1, len(self.store.accounts.audit(0)))

    def test_external_source_change_invalidates_revision(self):
        form = self.form('native:mmoexp', new_password=NEW, confirm_password=NEW)
        self.file.write_text(self.file.read_text().replace(self.portal.apr1_md5(OLD, 'qa123456'), self.portal.apr1_md5(OLD, 'qa876543')), encoding='utf-8')
        self.denied(409, lambda: self.store.accounts.mutate(self.actor, 'password', form))

    def test_last_administrator_and_admin_scope_are_protected(self):
        for name in ('chenchao', 'DY', 'fstech'):
            self.grants('native:' + name, enabled=False)
        self.denied(409, lambda: self.grants('native:wulv', enabled=False))
        self.denied(400, lambda: self.grants('native:wulv', business='none'))
        self.assertTrue(self.store.accounts.authenticate('wulv', OLD))

    def test_readonly_identity_cannot_mutate_or_list(self):
        token, identity = self.adapter.native_login('mmoexp', OLD)
        self.denied(403, lambda: self.store.accounts.mutate(identity, 'password', self.form('native:wulv', new_password=NEW, confirm_password=NEW)))
        self.assertEqual(403, self.http('/api/accounts', token=token)[0])

    def test_origin_csrf_unknown_fields_methods_and_query_are_rejected(self):
        form = self.form('native:mmoexp', new_password=NEW, confirm_password=NEW)
        self.assertEqual(403, self.http('/api/account-password', form, origin='https://other.invalid')[0])
        self.assertEqual(403, self.http('/api/account-password', form, csrf=False)[0])
        self.assertEqual(400, self.http('/api/account-password', dict(form, extra=True))[0])
        self.assertEqual(405, self.http('/api/account-password')[0])
        self.assertEqual(400, self.http('/api/accounts?after=0')[0])

    def test_concurrent_requests_one_success_one_conflict(self):
        form = self.form('native:mmoexp', new_password=NEW, confirm_password=NEW)
        def attempt(_):
            try:
                self.store.accounts.mutate(self.actor, 'password', form)
                return 200
            except runtime.core.Denied as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([200, 409], sorted(pool.map(attempt, range(2))))

    def test_schema5_audit_is_append_only_and_old_runtime_is_rejected(self):
        self.reset('native:mmoexp')
        with self.store.connection() as db:
            self.assertEqual(5, db.execute('PRAGMA user_version').fetchone()[0])
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE account_events SET reason='changed'")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute('DELETE FROM account_events')
        import importlib.util
        source = HERE / 'baseline/runtime.py'
        spec = importlib.util.spec_from_file_location('old_accounts_runtime', source)
        old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
        with self.assertRaises(ValueError):
            old.RuntimeStore(self.root, self.portal, isolated=True)

    def test_missing_or_redirected_sources_fail_closed(self):
        self.gate.rename(self.gate.with_suffix('.moved'))
        self.assertEqual(503, self.http('/api/accounts')[0])

    def test_new_registration_cannot_reuse_legacy_only_name(self):
        self.denied(409, lambda: self.store.register('dongwenxin', OLD, 'QA', 'Reuse'))

    def test_disabled_native_and_registered_accounts_cannot_login(self):
        subject = self.register()
        self.grants('native:mmoexp', enabled=False)
        self.assertFalse(self.store.accounts.authenticate('mmoexp', OLD))
        self.grants(subject, enabled=False)
        self.denied(401, lambda: self.store.login('newreader', OLD))

    def test_no_secret_in_password_response_or_audit(self):
        code, result, _ = self.http('/api/account-password', self.form('native:mmoexp', new_password=NEW, confirm_password=NEW))
        self.assertEqual(200, code)
        rendered = json.dumps([result, self.store.accounts.audit(0), self.store.accounts.listing()])
        for value in (NEW, OLD, 'pbkdf2_sha256$', '$apr1$'):
            self.assertNotIn(value, rendered)

    def test_malformed_subject_and_revision_rejected_before_mutation(self):
        form = self.form('native:mmoexp', new_password=NEW, confirm_password=NEW)
        for subject, revision in [({}, form['revision']), (form['subject'], '非ASCII'), ('native:../wulv', form['revision'])]:
            self.denied(400, lambda: self.store.accounts.mutate(self.actor, 'password', dict(form, subject=subject, revision=revision)))
        self.assertEqual([], self.store.accounts.audit(0))

    def test_native_editor_keeps_actual_task_ownership_guard(self):
        import importlib.util
        source = HERE / 'baseline/taskboard_server.py'
        spec = importlib.util.spec_from_file_location('accounts_taskboard_source', source)
        board = importlib.util.module_from_spec(spec); spec.loader.exec_module(board)
        role, registered = consumer_seams.taskboard_member(None, 'mmoexp', 'editor', None, policy)
        context = board.Ctx('mmoexp', role, registered=registered)
        self.assertTrue(board.can_edit_task(context, {'assignee': 'mmoexp'}))
        self.assertFalse(board.can_edit_task(context, {'assignee': 'another_user'}))
        with self.assertRaises(board.ApiError):
            board.require_admin(context)


if __name__ == '__main__':
    unittest.main()

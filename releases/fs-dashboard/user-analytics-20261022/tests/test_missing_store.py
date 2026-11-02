"""Portable data-loss checks; no mocked filesystem permissions or production I/O."""
import sqlite3
import json
import os
from contextlib import closing
import sys
import tempfile
import unittest
import ast
import re
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from user_store import Store, StoreUnavailable, require_database
from user_runtime import load_store
import user_http


def replay_live_bootstrap(builder):
    """Keep the captured build/catch; omit host imports/path mutation, never start it."""
    fixture=json.loads((Path(__file__).parent/'fixtures/live_user_bootstrap-20261101.json').read_text('utf-8'))
    block=ast.parse(fixture['snippet']).body[0]
    calls=[n for n in block.body if isinstance(n,ast.Assign)]
    if len(calls)!=1 or not isinstance(calls[0].value,ast.Call) or not isinstance(calls[0].value.func,ast.Name) or calls[0].value.func.id!='build_user_analytics':
        raise AssertionError('captured_user_bootstrap_changed')
    block.body=calls
    state=dict(USERS=None,USERS_ERROR=None,build_user_analytics=builder,re=re)
    exec(compile(ast.Module(body=[block],type_ignores=[]),'captured-live-user-bootstrap','exec'),state)
    return state


class MissingStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'

    def test_cold_start_missing_root_does_not_create_key_lock_or_db(self):
        with self.assertRaisesRegex(StoreUnavailable, 'users_store_missing'):
            load_store(self.root, {})
        self.assertFalse(self.root.exists())

    def test_existing_key_missing_database_preserves_key(self):
        self.root.mkdir()
        key = self.root / 'identity.key'
        key.write_bytes(b'fixture-only-key')
        with self.assertRaises(StoreUnavailable):
            load_store(self.root, {})
        self.assertEqual(key.read_bytes(), b'fixture-only-key')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['identity.key'])

    def test_empty_and_unrelated_database_are_not_facts(self):
        self.root.mkdir()
        path = self.root / 'customers.sqlite3'
        path.touch()
        with self.assertRaises(StoreUnavailable):
            require_database(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE unrelated(id INTEGER)')
            db.commit()
        before = path.read_bytes()
        with self.assertRaisesRegex(StoreUnavailable, 'users_store_incomplete'):
            require_database(path)
        self.assertEqual(before, path.read_bytes())

    def test_runtime_loss_does_not_recreate_database(self):
        self.root.mkdir()
        store = Store.__new__(Store)
        store.path = self.root / 'customers.sqlite3'
        store.read_only = False
        with self.assertRaises(StoreUnavailable):
            with store.db():
                self.fail('missing database connected')
        self.assertFalse(store.path.exists())

    def test_no_create_constructor_rejects_database_removed_after_precheck(self):
        self.root.mkdir()
        path = self.root / 'customers.sqlite3'
        path.write_bytes(b'prechecked fixture placeholder')
        path.rename(self.root / 'moved.sqlite3')
        with self.assertRaisesRegex(StoreUnavailable, 'users_store_missing'):
            Store(self.root, b'x'*32, {}, create=False)
        self.assertFalse(path.exists())

    @unittest.skipUnless(os.name == 'posix', 'requires real POSIX permissions and fcntl; run Linux validation')
    def test_real_loader_precheck_then_database_rename_keeps_key_and_never_creates(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'source/user_config.json').read_text('utf-8'))
        store=load_store(self.root,config,initialize=True)
        original_key=(self.root/'identity.key').read_bytes()
        real_check=require_database
        def lose_after_check(path):
            real_check(path)
            Path(path).rename(self.root/'moved.sqlite3')
        with patch('user_runtime.require_database',side_effect=lose_after_check):
            with self.assertRaisesRegex(StoreUnavailable,'users_store_missing'):
                load_store(self.root,config)
        self.assertFalse(store.path.exists())
        self.assertEqual((self.root/'identity.key').read_bytes(),original_key)

    def test_http_is_503_not_empty_or_snapshot_404(self):
        service = Mock()
        service.query.side_effect = StoreUnavailable('users_store_missing')
        service.search.side_effect = StoreUnavailable('users_store_missing')
        self.assertEqual(user_http.get(service, '/users', {}, 'fixture-user'),
                         (503, {'error': 'users_store_unavailable', 'recovery_required': True}))
        self.assertEqual(user_http.search(service, {}, 'fixture-user')[0], 503)
        self.assertEqual(user_http.get(service, '/users', {}, '')[0], 401)

    def test_live_host_missing_store_stays_available_without_bootstrapping_facts(self):
        for key_present in (False,True):
            root=self.root/str(key_present)
            if key_present:
                root.mkdir(parents=True);(root/'identity.key').write_bytes(b'fixture-preserved-key')
            try:
                state=replay_live_bootstrap(lambda:load_store(root,{}))
            except StoreUnavailable as error:
                self.fail('live bootstrap leaked storage-unavailable exception: '+str(error))
            self.assertIsNone(state['USERS']);self.assertEqual(state['USERS_ERROR'],'StoreUnavailable')
            self.assertEqual(user_http.get(state['USERS'],'/users',{},'fixture-user')[0],503)
            self.assertEqual(user_http.search(state['USERS'],{},'fixture-user')[0],503)
            if key_present:
                self.assertEqual((root/'identity.key').read_bytes(),b'fixture-preserved-key')
                self.assertEqual([p.name for p in root.iterdir()],['identity.key'])
            else:self.assertFalse(root.exists())

    def test_live_host_normal_builder_is_retained_and_unexpected_bug_still_escapes(self):
        sentinel=object();state=replay_live_bootstrap(lambda:sentinel)
        self.assertIs(state['USERS'],sentinel);self.assertIsNone(state['USERS_ERROR'])
        def bug():raise RuntimeError('unexpected_application_bug')
        with self.assertRaisesRegex(RuntimeError,'unexpected_application_bug'):
            replay_live_bootstrap(bug)

    def test_real_hot_store_loss_returns_503_without_creating_database(self):
        store=Store.__new__(Store);store.path=self.root/'customers.sqlite3';store.read_only=False
        class Service:
            def query(self,args,user):
                with store.db():return {'unexpected_empty_success':True}
            search=query
        self.assertEqual(user_http.get(Service(),'/users',{},'fixture-user'),
                         (503,{'error':'users_store_unavailable','recovery_required':True}))
        self.assertEqual(user_http.search(Service(),{},'fixture-user')[0],503)
        self.assertFalse(self.root.exists())

    @unittest.skipUnless(os.name=='posix','requires real POSIX ownership/fcntl; Linux must run normal load')
    def test_live_host_normal_existing_store_load_preserves_identity_and_revision(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'source/user_config.json').read_text('utf-8'))
        original=load_store(self.root,config,initialize=True)
        key=(self.root/'identity.key').read_bytes();revision=original.revision()
        state=replay_live_bootstrap(lambda:load_store(self.root,config))
        self.assertIsInstance(state['USERS'],Store);self.assertIsNone(state['USERS_ERROR'])
        self.assertEqual(state['USERS'].revision(),revision);self.assertEqual((self.root/'identity.key').read_bytes(),key)


if __name__ == '__main__':
    unittest.main()

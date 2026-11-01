"""Portable data-loss checks; no mocked filesystem permissions or production I/O."""
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from user_store import Store, StoreUnavailable, require_database
from user_runtime import load_store
import user_http


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

    def test_http_is_503_not_empty_or_snapshot_404(self):
        service = Mock()
        service.query.side_effect = StoreUnavailable('users_store_missing')
        service.search.side_effect = StoreUnavailable('users_store_missing')
        self.assertEqual(user_http.get(service, '/users', {}, 'fixture-user'),
                         (503, {'error': 'users_store_unavailable', 'recovery_required': True}))
        self.assertEqual(user_http.search(service, {}, 'fixture-user')[0], 503)
        self.assertEqual(user_http.get(service, '/users', {}, '')[0], 401)


if __name__ == '__main__':
    unittest.main()

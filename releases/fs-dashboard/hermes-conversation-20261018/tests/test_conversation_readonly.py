"""Synthetic persisted material records; never instantiate a runner or provider."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(MODULE / 'source'), str(MODULE.parent / 'hermes-fc-pilot-20261013')]
from conversation_store import ConversationStore
from pilot import TaskStore
from conversation_readonly import files_list, material_metadata
import conversation_http


class ReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = ConversationStore(root / 'conversation')
        self.cid = self.store.create('alice')['conversation_id']
        self.tasks = TaskStore(root / 'tasks.sqlite3')
        self.allowed = True
        self.authorized = lambda user: self.allowed and user == 'alice'
        self.service = SimpleNamespace(store=self.store, hermes=SimpleNamespace(tasks=self.tasks))
        self.request_id, self.task_id, self.fid = 'material-request-1', 'a' * 32, 'b' * 32
        with self.tasks.db() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,0,NULL,NULL,0,0)',
                       (self.task_id, 'alice', 'f' * 64, '{}', 'QUEUED'))
            db.execute('''CREATE TABLE conversation_material_selections_v1 (
                owner TEXT,cid TEXT,request_id TEXT,selection TEXT)''')
            db.execute('INSERT INTO conversation_material_selections_v1 VALUES (?,?,?,?)',
                       ('alice', self.cid, self.request_id, '{"goal_id":"material-goal"}'))
            db.execute('''CREATE TABLE conversation_material_runs_v1 (
                owner TEXT,cid TEXT,request_id TEXT,goal_id TEXT,task_id TEXT,run_id TEXT,
                attempted INTEGER,generated TEXT,coverage TEXT,context_receipt TEXT,
                official_status TEXT,runtime_error TEXT,observed_at TEXT)''')
            db.execute('INSERT INTO conversation_material_runs_v1 VALUES (?,?,?,?,?,?,0,?,?,?,?,NULL,?)',
                ('alice', self.cid, self.request_id, 'material-goal', self.task_id, None,
                 json.dumps([dict(file_id=self.fid, sha256='c' * 64, version=1, size=4, parent_id=None)]),
                 '[]', None, None, '2026-11-09T01:00:00+00:00'))

    def read(self, user='alice', cid=None, rid=None):
        return material_metadata(self.service, user, cid or self.cid,
                                 rid or self.request_id, self.authorized)

    def snapshots(self):
        return {str(p.relative_to(self.store.root.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.store.root.parent.rglob('*') if p.is_file()}

    def test_metadata_reads_existing_records_without_creating_file_directories(self):
        before = self.snapshots()
        with patch.object(Path, 'mkdir', side_effect=AssertionError('must not create directory')):
            value = self.read()
        self.assertEqual(value['task_id'], self.task_id)
        self.assertEqual(value['status'], 'queued')
        self.assertEqual(value['files'][0]['status'], 'missing')
        self.assertTrue(value['stored_only'])
        self.assertFalse(value['refreshed'])
        self.assertFalse(value['result_available'])
        self.assertEqual(self.snapshots(), before)

    def test_expired_file_is_reported_without_deleting_its_content(self):
        directory = self.store.root / 'files' / self.cid
        directory.mkdir(parents=True)
        (directory / self.fid).write_bytes(b'test')
        receipt = dict(file_id=self.fid, filename='test.csv', mime='text/csv', size=4,
                       sha256='c' * 64, version=1, generated=True, parent_id=None,
                       created_at=1, expires_at=2, recipe={'token': 'must-not-be-returned'})
        (directory / (self.fid + '.json')).write_text(json.dumps(receipt), 'utf-8')
        before = self.snapshots()
        with patch.object(Path, 'unlink', side_effect=AssertionError('must not delete file')):
            value = self.read()
        self.assertEqual(value['files'][0]['status'], 'expired')
        self.assertNotIn('recipe', value['files'][0])
        self.assertEqual(self.snapshots(), before)

    def test_ownership_current_authorization_and_missing_records(self):
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.read()
        self.allowed = True
        with self.assertRaises(LookupError):
            material_metadata(self.service, 'bob', self.cid, self.request_id, lambda user: True)
        with self.assertRaises(LookupError):
            self.read(rid='missing-request')
        calls = []
        def revoke_during_read(user):
            calls.append(user)
            return len(calls) == 1
        with self.assertRaises(PermissionError):
            material_metadata(self.service, 'alice', self.cid, self.request_id, revoke_during_read)

    def test_running_record_never_reconciles_or_stops_original_run(self):
        class Forbidden:
            def __getattr__(self, name):
                raise AssertionError('no material runtime: ' + name)
        self.service.materials = Forbidden()
        with self.tasks.db() as db:
            db.execute("UPDATE tasks SET state='RUNNING',run_id=?", ('run_' + 'd' * 32,))
            db.execute('UPDATE conversation_material_runs_v1 SET attempted=1,run_id=?,official_status=?',
                       ('run_' + 'd' * 32, '{"status":"running","token":"not-public"}'))
        before = self.snapshots()
        value = self.read()
        self.assertEqual(value['status'], 'running')
        self.assertNotIn('not-public', json.dumps(value))
        self.assertEqual(self.snapshots(), before)

    def test_missing_database_is_not_created(self):
        self.service.hermes.tasks = SimpleNamespace(path=self.store.root.parent / 'absent.sqlite3')
        with self.assertRaises(OSError):
            self.read()
        self.assertFalse(Path(self.service.hermes.tasks.path).exists())

    def test_files_list_without_directory_does_not_create_it(self):
        before = self.snapshots()
        with patch.object(Path, 'mkdir', side_effect=AssertionError('must not create directory')):
            value = files_list(self.service, 'alice', self.cid, self.authorized)
        self.assertEqual(value['items'], [])
        self.assertTrue(value['stored_only'])
        self.assertFalse(value['refreshed'])
        self.assertFalse((self.store.root / 'files').exists())
        self.assertEqual(self.snapshots(), before)

    def test_files_list_preserves_expired_and_current_attachments_without_cleanup(self):
        directory = self.store.root / 'files' / self.cid
        directory.mkdir(parents=True)
        for fid, expires in ((self.fid, 1), ('c' * 32, 9999999999)):
            (directory / fid).write_bytes(b'test')
            receipt = dict(file_id=fid, filename='test.csv', mime='text/csv', size=4,
                           sha256='d' * 64, version=1, generated=True, parent_id=None,
                           created_at=1, expires_at=expires, recipe={'token': 'must-not-return'})
            (directory / (fid + '.json')).write_text(json.dumps(receipt), 'utf-8')
        before = self.snapshots()
        with patch.object(Path, 'unlink', side_effect=AssertionError('must not delete file')):
            value = files_list(self.service, 'alice', self.cid, self.authorized)
        self.assertEqual([row['status'] for row in value['items']], ['expired', 'metadata_only'])
        self.assertTrue(all(row['content_verified'] is False for row in value['items']))
        self.assertEqual(value['items'][0]['sha256'], 'd' * 64)
        self.assertNotIn('must-not-return', json.dumps(value))
        self.assertEqual(self.snapshots(), before)

    def test_files_list_rechecks_owner_and_current_permission(self):
        self.allowed = False
        with self.assertRaises(PermissionError):
            files_list(self.service, 'alice', self.cid, self.authorized)
        with self.assertRaises(LookupError):
            files_list(self.service, 'bob', self.cid, lambda user: True)
        calls = []
        def revoke_during_read(user):
            calls.append(user)
            return len(calls) == 1
        with self.assertRaises(PermissionError):
            files_list(self.service, 'alice', self.cid, revoke_during_read)

    def test_files_route_is_get_only_and_has_no_query_parameters(self):
        class Handler:
            headers = {}
            wfile = io.BytesIO()
            close_connection = False
            def send_response(inner, code): inner.code = code
            def send_header(inner, *args): pass
            def end_headers(inner): pass
        path = '/api/hermes/conversations/' + self.cid + '/connector/files'
        handler = Handler()
        with patch.object(Path, 'mkdir', side_effect=AssertionError('must not create directory')):
            self.assertTrue(conversation_http.handle(handler, 'GET', urlsplit(path), 'alice',
                                                   self.service, self.authorized))
        self.assertEqual(handler.code, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue())['items'], [])
        for method, suffix in [('POST', ''), ('GET', '?request_id=fixture-request')]:
            handler.wfile = io.BytesIO()
            conversation_http.handle(handler, method, urlsplit(path + suffix), 'alice',
                                     self.service, self.authorized)
            self.assertNotEqual(handler.code, 200)

    def test_route_get_only_uses_pure_adapter(self):
        class Handler:
            headers = {}
            wfile = io.BytesIO()
            close_connection = False
            def send_response(inner, code): inner.code = code
            def send_header(inner, *args): pass
            def end_headers(inner): pass
        handler = Handler()
        path = '/api/hermes/conversations/' + self.cid + '/connector/materials/' + self.request_id
        self.assertTrue(conversation_http.handle(handler, 'GET', urlsplit(path), 'alice',
                                               self.service, self.authorized))
        self.assertEqual(handler.code, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue())['request_id'], self.request_id)
        handler.wfile = io.BytesIO()
        conversation_http.handle(handler, 'POST', urlsplit(path), 'alice', self.service, self.authorized)
        self.assertNotEqual(handler.code, 200)


if __name__ == '__main__':
    unittest.main()

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('exact_delete',HERE/'delete_old_review.py')
cleanup=importlib.util.module_from_spec(spec);spec.loader.exec_module(cleanup)


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.owner='fixture-admin';self.owner_patch=patch.object(cleanup,'OWNER_SHA',hashlib.sha256(self.owner.encode()).hexdigest())
        self.owner_patch.start();self.addCleanup(self.owner_patch.stop)
        # Schema only; all rows below are synthetic and require no production preview.
        schema={'conversations': ['id', 'owner', 'session_id', 'updated_at'], 'turns': ['id', 'conversation_id', 'request_id', 'input_sha256', 'text', 'state', 'run_id', 'task_id', 'lease'], 'events': ['seq', 'turn_id', 'upstream_seq', 'type', 'payload'], 'artifacts': ['id', 'turn_id', 'filename', 'mime', 'sha256', 'size'], 'actions': ['turn_id', 'request_id', 'kind', 'input_sha256', 'state'], 'synthetic_turn_archives': ['turn_id', 'conversation_id', 'receipt', 'receipt_sha256'], 'native_workspace_files': ['cid', 'path', 'file_id', 'sha256'], 'native_file_exports': ['cid', 'run_id', 'path', 'file_id'], 'native_collected_runs': ['cid', 'run_id'], 'native_conversation_runs': ['turn_id', 'binding', 'body', 'idempotency_key', 'fingerprint', 'schemas', 'stopped', 'pricing_context'], 'native_pending_sources': ['owner', 'cid', 'turn_id', 'session_id', 'run_id', 'profile_key', 'lease', 'subsystem', 'pending_id', 'record_sha256']}
        for table,columns in schema.items():
            fields=[]
            for name in columns:
                kind='INTEGER PRIMARY KEY AUTOINCREMENT' if table=='events' and name=='seq' else 'INTEGER' if name=='stopped' else 'TEXT'
                fields.append(name+' '+kind)
            self.db.execute('CREATE TABLE '+table+'('+','.join(fields)+')')
        self.db.execute('CREATE INDEX original_turn_index ON turns(conversation_id)')
        self.db.execute('INSERT INTO conversations VALUES(?,?,?,?)',(cleanup.CID,self.owner,'fixture-session','2026-11-07T18:26:50Z'))
        self.db.execute('INSERT INTO conversations VALUES(?,?,?,?)',('other-cid',self.owner,'other-session','2026-11-09T01:00:00Z'))
        self.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?)',(cleanup.TID,cleanup.CID,cleanup.REQUEST,'input-sha','private fixture text','dispatch_unknown',cleanup.RUN,cleanup.TID,'lease'))
        self.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?)',('other-turn','other-cid','other-request','input-sha','unrelated','dispatch_unknown','other-run','other-task','other-lease'))
        binding={'owner':self.owner,'conversation_id':cleanup.CID,'turn_id':cleanup.TID,'request_id':cleanup.REQUEST,'run_id':cleanup.RUN,'session_id':'fixture-session','lease':'lease'}
        self.db.execute('INSERT INTO native_conversation_runs VALUES(?,?,?,?,?,?,?,?)',(cleanup.TID,json.dumps(binding),'body','idempotency','fingerprint',None,1,None))
        for i in range(74):self.db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(438+i,cleanup.TID,i,'run.completed' if i==73 else 'tool.completed','private fixture output'))
        self.db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(999,'other-turn',0,'run.completed','unrelated output'))
        self.expected=cleanup.digest(cleanup.selected(self.db))
        self.db.commit()

    def test_only_approved_four_sets_are_removed_with_schema_sequence_and_other_unknown_preserved(self):
        before=tuple(self.db.execute('SELECT * FROM turns WHERE id=?',('other-turn',)).fetchone())
        sequence=[tuple(r) for r in self.db.execute('SELECT * FROM sqlite_sequence')]
        deleted=cleanup.delete_rows(self.db,self.expected)
        self.assertEqual(deleted,{'events':74,'native_conversation_runs':1,'turns':1,'conversations':1})
        self.assertEqual(tuple(self.db.execute('SELECT * FROM turns WHERE id=?',('other-turn',)).fetchone()),before)
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM sqlite_sequence')],sequence)
        self.assertEqual(self.db.execute('SELECT payload FROM events WHERE turn_id=?',('other-turn',)).fetchone()[0],'unrelated output')
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='original_turn_index'").fetchone())

    def test_changed_record_or_wrong_hash_does_not_delete(self):
        with self.assertRaisesRegex(ValueError,'CAS'):cleanup.delete_rows(self.db,'0'*64)
        self.db.execute('UPDATE turns SET text=? WHERE id=?',('changed',cleanup.TID))
        with self.assertRaisesRegex(ValueError,'CAS'):cleanup.delete_rows(self.db,self.expected)
        self.assertEqual(self.db.execute('SELECT count(*) FROM turns').fetchone()[0],2)

    def test_new_artifact_extra_turn_and_unfenced_binding_are_rejected(self):
        self.db.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?)',('artifact',cleanup.TID,'file.html','text/html','sha',1))
        with self.assertRaisesRegex(ValueError,'counts'):cleanup.delete_rows(self.db,self.expected)
        self.db.execute('DELETE FROM artifacts')
        self.db.execute('UPDATE native_conversation_runs SET stopped=0')
        with self.assertRaisesRegex(ValueError,'stopped'):cleanup.delete_rows(self.db,self.expected)

    def test_delete_triggers_cannot_change_other_records(self):
        self.db.execute("CREATE TRIGGER unexpected AFTER DELETE ON turns BEGIN UPDATE conversations SET updated_at='changed'; END")
        with self.assertRaisesRegex(ValueError,'trigger'):cleanup.delete_rows(self.db,self.expected)
        self.assertEqual(self.db.execute('SELECT count(*) FROM turns').fetchone()[0],2)

    def test_existing_644_file_inside_original_private_ancestors_is_accepted_without_chmod(self):
        p=cleanup.DATABASE
        metadata={p:SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFREG|0o644,st_nlink=1),
            p.parent:SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o700,st_nlink=5),
            p.parent.parent:SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFDIR|0o700,st_nlink=21),
            p.parent.parent.parent:SimpleNamespace(st_uid=0,st_gid=9876,st_mode=stat.S_IFDIR|0o750,st_nlink=8)}
        with patch.object(Path,'lstat',lambda item:metadata[item]),patch.object(cleanup.os,'chmod',side_effect=AssertionError('must not change live permissions')):
            cleanup.store_boundary()
            metadata[p.parent].st_mode=stat.S_IFDIR|0o755
            with self.assertRaisesRegex(ValueError,'boundary_changed'):cleanup.store_boundary()
            metadata[p.parent].st_mode=stat.S_IFDIR|0o700
            metadata[p].st_nlink=2
            with self.assertRaisesRegex(ValueError,'hardlink'):cleanup.store_boundary()


if __name__=='__main__':unittest.main()

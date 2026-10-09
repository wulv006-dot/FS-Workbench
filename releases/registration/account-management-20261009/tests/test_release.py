"""Exact eight-file release in a temporary root; no live service or user data."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release', Path(__file__).parents[1]/'source/release_navigation.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
def sha(value): return hashlib.sha256(value).hexdigest()

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root/'stage'
        files = []
        for rel, target in sorted(r.PERMISSION_TARGETS.items()):
            old = None if rel.endswith('/module_permissions.py') else ('before:'+rel).encode()
            new = ('after:'+rel).encode()
            path = r.rooted(self.root,target); path.parent.mkdir(parents=True,exist_ok=True)
            if old is not None: path.write_bytes(old)
            path = self.stage/'candidate'/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(new)
            files.append(dict(candidate=rel,target=target,beforeSha256=sha(old) if old else None,sha256=sha(new)))
        self.manifest = dict(schemaVersion=1,scope=r.PERMISSION_SCOPE,releaseReady=True,files=files,
            unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256=sha(b'protected'))],
            runtimeRequired={'auth-portal.service':{'ActiveState':'active'}})
        self.payload = json.dumps(self.manifest).encode(); self.approval = sha(self.payload)
        self.auth_db = r.rooted(self.root,'/opt/auth-portal/data/registration-approval/registration.sqlite3')
        self.task_db = r.rooted(self.root,'/opt/mmoexp-taskboard/data/taskboard.db')
        for path, script in ((self.auth_db,"CREATE TABLE audit(action TEXT); PRAGMA user_version=3;"),
                (self.task_db,"CREATE TABLE members(username TEXT); INSERT INTO members VALUES('existing'); CREATE TABLE green_tasks(progress INTEGER); INSERT INTO green_tasks VALUES(7);")):
            path.parent.mkdir(parents=True,exist_ok=True)
            with contextlib.closing(sqlite3.connect(str(path))) as db: db.executescript(script); db.commit()
        self.platform = contextlib.ExitStack(); self.addCleanup(self.platform.close)
        if os.name != 'posix':
            self.platform.enter_context(patch.object(r,'locks',lambda root:contextlib.nullcontext()))
            self.platform.enter_context(patch.object(r,'directory_sync'))
        self.platform.enter_context(patch.object(r,'guards'))
        self.platform.enter_context(patch.object(r,'retirement'))
        self.restart = self.platform.enter_context(patch.object(r,'restart_for'))

    def apply(self):
        return r.apply(self.manifest,self.stage,self.approval,self.payload,'nav-20261009T000003Z',self.root)

    def test_exact_scope_and_cas(self):
        self.assertEqual(8,len(r.validate(self.manifest,self.stage)))
        for mutation in ('extra','target','baseline','scope','runtime'):
            m=json.loads(self.payload)
            if mutation=='extra':m['files'].append(m['files'][0])
            elif mutation=='target':m['files'][0]['target']='/unapproved'
            elif mutation=='baseline':m['files'][0]['beforeSha256']=None
            elif mutation=='scope':m['scope']='other'
            else:m['runtimeRequired']={}
            with self.assertRaises(ValueError):r.validate(m,self.stage)
        row=self.manifest['files'][0];r.rooted(self.root,row['target']).write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError,'baseline drift'):self.apply()
        self.assertEqual(b'drift',r.rooted(self.root,row['target']).read_bytes())

    def test_apply_and_legacy_rollback_preserve_data(self):
        db_sha=(sha(self.auth_db.read_bytes()),sha(self.task_db.read_bytes()))
        result=self.apply()
        self.assertTrue(all(r.digest(r.rooted(self.root,x['target']))==x['sha256'] for x in self.manifest['files']))
        r.rollback(Path(result['backup']),self.approval,self.root)
        self.assertTrue(all(r.digest(r.rooted(self.root,x['target']))==x['beforeSha256'] for x in self.manifest['files']))
        self.assertEqual(db_sha,(sha(self.auth_db.read_bytes()),sha(self.task_db.read_bytes())))
        self.assertEqual(2,self.restart.call_count)

    def test_active_permissions_block_legacy_rollback(self):
        result=self.apply()
        with contextlib.closing(sqlite3.connect(str(self.auth_db))) as db:
            db.execute('PRAGMA user_version=4');db.execute("INSERT INTO audit VALUES('permissions')");db.commit()
        before=sha(self.auth_db.read_bytes())
        with self.assertRaisesRegex(ValueError,'legacy rollback refused'):r.rollback(Path(result['backup']),self.approval,self.root)
        self.assertEqual(before,sha(self.auth_db.read_bytes()))
        self.assertTrue(all(r.digest(r.rooted(self.root,x['target']))==x['sha256'] for x in self.manifest['files']))
        self.assertEqual(1,self.restart.call_count)
        with contextlib.closing(sqlite3.connect(str(self.auth_db))) as db:db.execute('PRAGMA user_version=3')
        with self.assertRaisesRegex(ValueError,'legacy rollback refused'):r.rollback(Path(result['backup']),self.approval,self.root)

    def test_failure_after_write_restores_only_code(self):
        calls=[0]
        def changed(*args):
            calls[0]+=1
            if calls[0]==3:raise ValueError('protected source drift')
        before=sha(self.auth_db.read_bytes())
        with patch.object(r,'guards',changed),self.assertRaisesRegex(ValueError,'protected source drift'):self.apply()
        self.assertTrue(all(r.digest(r.rooted(self.root,x['target']))==x['beforeSha256'] for x in self.manifest['files']))
        self.assertEqual(before,sha(self.auth_db.read_bytes()))

if __name__=='__main__':unittest.main(verbosity=2)

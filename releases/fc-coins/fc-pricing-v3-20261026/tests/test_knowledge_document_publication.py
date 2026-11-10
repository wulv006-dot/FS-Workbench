"""Real frozen publisher and existing reader leases; isolated Linux files only."""
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
DEPLOY=ROOT/'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

adapter=load('document_knowledge_adapter',DEPLOY/'release.py')
legacy=load('document_original_reader_fixture',ROOT/'releases/fs-dashboard/knowledge-layering-20261023/tests/test_knowledge_reader_fence.py')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
encoded=lambda value:(json.dumps(value,sort_keys=True)+'\n').encode()


@unittest.skipUnless(os.name=='posix','real Linux publication/reader leases required')
class DocumentPublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid()!=0:raise RuntimeError('real publisher fixture requires root; never silently skip')

    @contextmanager
    def fixture(self):
        # Reuse the already-tested original publisher databases, retirement,
        # protected source and cost-reader fixture; only the V3 scope differs.
        with legacy.ReaderFence().fixture() as f:
            release,prefix=adapter.release_identity('a'*40)
            manifest=copy.deepcopy(f.manifest)
            manifest.update(scope=adapter.SCOPE,knowledgeRelease=release)
            manifest.pop('knowledgeOnly',None)
            index=json.loads((f.stage/'candidate/artifact/index.json').read_bytes())
            index.update(release=release,source_root='knowledge-releases/'+release)
            (f.stage/'candidate/artifact/index.json').write_bytes(encoded(index))
            f.new_policy=encoded(dict(catalog='knowledge-releases/'+release+'/index.json',sha256=sha(encoded(index))))
            (f.stage/'candidate/runtime/knowledge-load-policy.json').write_bytes(f.new_policy)
            for row in manifest['files']:
                if row['candidate'].startswith('artifact/'):
                    row['target']=prefix+row['candidate'][len('artifact/'):]
                row['sha256']=sha((f.stage/'candidate'/row['candidate']).read_bytes())
            f.baseline=f.root/'opt/fs-hermes-fc/business-baseline.md'
            f.old_baseline=b'original full baseline';f.new_baseline=b'new FC paragraphs; protected non-FC unchanged'
            f.baseline.parent.mkdir(parents=True,exist_ok=True);f.baseline.write_bytes(f.old_baseline)
            source=f.stage/'candidate/runtime/business-baseline.md';source.write_bytes(f.new_baseline)
            manifest['files'].append(dict(candidate='runtime/business-baseline.md',target=adapter.RUNTIME['runtime/business-baseline.md'],
                sha256=sha(f.new_baseline),beforeSha256=sha(f.old_baseline),owner='0:0',mode='0o644'))
            manifest['unchangedRequired']=[r for r in manifest['unchangedRequired'] if r['path']!=adapter.RUNTIME['runtime/business-baseline.md']]
            base=(DEPLOY/'release_navigation_base.py').read_bytes().replace(b'\r\n',b'\n')
            self.assertEqual(sha(base),adapter.BASE_SHA)
            (f.stage/'release_navigation_base.py').write_bytes(base)
            f.raw=encoded(manifest);f.manifest=manifest;f.release=release
            (f.stage/'approved-manifest.json').write_bytes(f.raw)
            with patch.object(adapter,'HERE',f.stage):f.publisher=adapter.load_base()
            yield f

    def apply(self,f):
        return f.publisher.apply(f.manifest,f.stage,sha(f.raw),f.raw,'nav-20261111T000001Z',f.root)

    def assert_old(self,f):
        self.assertEqual(f.policy.read_bytes(),f.old_policy)
        self.assertEqual(f.baseline.read_bytes(),f.old_baseline)
        self.assertEqual(f.old_rule.read_bytes(),b'old rule')

    def test_real_apply_preserves_running_cost_read_and_collector_lock_but_fences_new_session(self):
        import fcntl
        with self.fixture() as f,patch.dict(sys.modules,{'cache_retention':legacy.retention}):
            submit,queued=legacy.ReaderFence().submitter(f);cid=f.store.create('alice')['conversation_id']
            guard=legacy.ReaderFence().guard();atomic=f.publisher.atomic;writes=[]
            def observe(path,payload,mode):
                if path==f.policy:
                    self.assertEqual(f.policy.read_bytes(),f.old_policy)
                    self.assertEqual(f.baseline.read_bytes(),f.new_baseline)
                    self.assertTrue((f.fs/'knowledge-releases'/f.release/'rule.md').is_file())
                    with guard(f.fs/'admission.lock') as admitted:self.assertFalse(admitted)
                    with self.assertRaisesRegex(RuntimeError,'release_in_progress'):submit(cid,'during_documents_1')
                    with legacy.retention.maintenance_reader(f.fs):self.assertEqual(f.old_rule.read_bytes(),b'old rule')
                result=atomic(path,payload,mode);writes.append(path);return result
            lock=f.root/'var/www/dashboard/fs-home/transactions/collector.lock';inode=lock.stat().st_ino
            with lock.open('r+b') as collector,legacy.retention.maintenance_reader(f.fs):
                fcntl.flock(collector.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(f.publisher,'atomic',side_effect=observe):result=self.apply(f)
                self.assertEqual(lock.stat().st_ino,inode)
            self.assertEqual(result['status'],'applied-awaiting-actual-http-role-acceptance')
            self.assertEqual(f.policy.read_bytes(),f.new_policy);self.assertFalse(queued)
            targets=[p for p in writes if p==f.policy or p==f.baseline or str(p).startswith(str(f.fs/'knowledge-releases'/f.release))]
            self.assertEqual(targets[-1],f.policy)
            with patch('subprocess.run',side_effect=AssertionError('document restart must perform no systemctl')):
                f.publisher.restart_for(f.manifest)
            f.publisher.rollback(f.root/'var/backups/fs-navigation-20261006/nav-20261111T000001Z',sha(f.raw),f.root)
            self.assert_old(f)
            self.assertFalse((f.fs/'knowledge-releases'/f.release/'index.json').exists())

    def test_real_failure_before_and_after_policy_restores_both_runtime_documents(self):
        for phase in ('before_baseline','after_policy'):
            with self.subTest(phase=phase),self.fixture() as f,patch.dict(sys.modules,{'cache_retention':legacy.retention}):
                atomic=f.publisher.atomic;failed=[];guard=legacy.ReaderFence().guard()
                def fail(path,payload,mode):
                    target=(path==f.baseline and payload==f.new_baseline) if phase=='before_baseline' else (path==f.policy and payload==f.new_policy)
                    if target and not failed:
                        failed.append(True)
                        if phase=='after_policy':atomic(path,payload,mode)
                        with guard(f.fs/'admission.lock') as admitted:self.assertFalse(admitted)
                        raise OSError('isolated publication boundary failure')
                    return atomic(path,payload,mode)
                with legacy.retention.maintenance_reader(f.fs),patch.object(f.publisher,'atomic',side_effect=fail):
                    with self.assertRaisesRegex(OSError,'isolated publication boundary failure'):self.apply(f)
                self.assertTrue(failed);self.assert_old(f)
                self.assertFalse((f.fs/'knowledge-releases'/f.release/'index.json').exists())
                with guard(f.fs/'admission.lock') as admitted:self.assertTrue(admitted)

    def test_real_policy_cas_race_preserves_foreign_policy_and_rolls_back_our_baseline(self):
        with self.fixture() as f:
            atomic=f.publisher.atomic;foreign=b'foreign concurrent policy'
            def race(path,payload,mode):
                result=atomic(path,payload,mode)
                if path==f.fs/'knowledge-releases'/f.release/'rule.md':f.policy.write_bytes(foreign)
                return result
            with patch.object(f.publisher,'atomic',side_effect=race):
                with self.assertRaisesRegex(ValueError,'target drift'):self.apply(f)
            self.assertEqual(f.policy.read_bytes(),foreign)
            self.assertEqual(f.baseline.read_bytes(),f.old_baseline)
            self.assertEqual(f.old_rule.read_bytes(),b'old rule')

    def test_active_model_turn_tracking_learning_and_original_locks_still_block_before_backup(self):
        import fcntl
        cases=('model','turn','tracking','learning','provider_lock','publication_lock')
        for case in cases:
            with self.subTest(case=case),self.fixture() as f:
                if case in ('model','tracking','learning'):
                    path=f.fs/('customer-tracking/tracking.db' if case=='tracking' else 'tasks.sqlite3')
                    with sqlite3.connect(path) as db:
                        if case=='model':db.execute("INSERT INTO requests VALUES ('RUNNING')")
                        elif case=='tracking':db.execute("INSERT INTO scan_jobs VALUES ('pending')")
                        else:db.execute('CREATE TABLE learning_events(state TEXT)');db.execute("INSERT INTO learning_events VALUES ('unknown')")
                if case=='turn':
                    cid=f.store.create('alice')['conversation_id'];f.store.reserve_turn('alice',cid,'question','pending_turn',native=True)
                lock=None
                if case.endswith('_lock'):
                    path=f.root/('var/lib/fs-business-ranges/fc-daily/provider.lock' if case=='provider_lock' else 'var/lock/fs-navigation-release.lock')
                    path.parent.mkdir(parents=True,exist_ok=True);lock=path.open('a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                try:
                    with self.assertRaises((ValueError,BlockingIOError)):self.apply(f)
                finally:
                    if lock:lock.close()
                self.assert_old(f)
                self.assertFalse((f.root/'var/backups/fs-navigation-20261006/nav-20261111T000001Z').exists())

    def test_scope_still_rejects_runtime_code_missing_runtime_cas_and_old_scope(self):
        with self.fixture() as f:
            for kind in ('code','cas','old_scope'):
                bad=copy.deepcopy(f.manifest)
                if kind=='code':bad['files'].append(dict(candidate='runtime/controller.py',target='/opt/fs-hermes-fc/controller.py',sha256='a'*64,beforeSha256='b'*64,owner='0:0',mode='0o644'))
                elif kind=='cas':next(r for r in bad['files'] if r['candidate']=='runtime/business-baseline.md')['beforeSha256']=None
                else:bad['scope']='knowledge-layering-20261023'
                (f.stage/'approved-manifest.json').write_bytes(encoded(bad))
                with self.subTest(kind=kind),patch.object(adapter,'HERE',f.stage),self.assertRaises(ValueError):adapter.load_base()


if __name__=='__main__':unittest.main()

"""Native pending provenance stays bound to the original conversation ledger."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import review_queue


class NativeReview(unittest.TestCase):
    def module(self):
        path = Path(__file__).with_name('native_review.py')
        self.assertTrue(path.is_file(), 'native review ledger consumer is missing')
        spec = importlib.util.spec_from_file_location('native_review_tested',path)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'conversations.db'
            binding = dict(owner='alice',conversation_id='cid-a',turn_id='turn-a',request_id='request-a',
                           session_id='native-a',lease='lease-a',run_id='run-a')
            key = hashlib.sha256(b'alice').hexdigest()
            record = dict(id='ab1234cd',subsystem='memory',action='add',summary='preference',origin='tool',
                          created_at=1,payload=dict(action='add',target='user',content='Prefer Chinese'))
            sha = hashlib.sha256(review_queue.canonical(record)).hexdigest()
            connection = sqlite3.connect(str(path))
            connection.execute('CREATE TABLE native_conversation_runs (turn_id TEXT PRIMARY KEY,binding TEXT,body TEXT,idempotency_key TEXT,fingerprint TEXT,schemas TEXT,stopped INTEGER)')
            connection.execute('CREATE TABLE native_pending_sources (owner TEXT,cid TEXT,turn_id TEXT,session_id TEXT,run_id TEXT,profile_key TEXT,lease TEXT,subsystem TEXT,pending_id TEXT,record_sha256 TEXT,PRIMARY KEY(owner,subsystem,pending_id,record_sha256))')
            connection.execute('INSERT INTO native_conversation_runs VALUES(?,?,?,?,?,?,?)',('turn-a',json.dumps(binding),'{}','key','fingerprint','[]',1))
            connection.execute('INSERT INTO native_pending_sources VALUES(?,?,?,?,?,?,?,?,?,?)',('alice','cid-a','turn-a','native-a','run-a',key,'lease-a','memory','ab1234cd',sha))
            connection.commit()
            try:
                yield path,connection,binding,record
            finally:
                connection.close()

    def test_ledger_join_is_read_only_and_owner_profile_is_derived(self):
        m = self.module()
        with self.fixture() as (path,db,binding,record):
            before = path.read_bytes()
            scope = m.load_scope(path,'alice')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(scope['profile_root'],'/var/lib/fs-hermes-fc/native/profiles/'+hashlib.sha256(b'alice').hexdigest())
            self.assertEqual(scope['sources'][0]['session_id'],'native-a')
            self.assertEqual(scope['sources'][0]['run_id'],'run-a')
            self.assertEqual(m.load_scope(path,'bob')['sources'],[])
            self.assertEqual(m.load_scope(path,'alice','other-session')['sources'],[])
            self.assertEqual(m.bind_source(scope,scope['sources'][0],record),scope['sources'][0])

    def test_mismatch_null_binding_or_wrong_profile_is_not_provenance(self):
        m = self.module()
        for column,value in [('run_id','other'),('lease','old'),('profile_key','0'*64),('subsystem','commands'),('record_sha256','bad')]:
            with self.subTest(column=column), self.fixture() as (path,db,binding,record):
                db.execute('UPDATE native_pending_sources SET '+column+'=?',(value,));db.commit()
                with self.assertRaises(ValueError):m.load_scope(path,'alice')
        with self.fixture() as (path,db,binding,record):
            binding['run_id'] = None
            db.execute('UPDATE native_conversation_runs SET binding=?',(json.dumps(binding),));db.commit()
            with self.assertRaises(ValueError):m.load_scope(path,'alice')

    def test_candidate_mutation_and_unmapped_record_cannot_be_approved(self):
        m = self.module()
        with self.fixture() as (path,db,binding,record):
            scope = m.load_scope(path,'alice');source = scope['sources'][0]
            for changed in (dict(record,summary='changed'),dict(record,id='deadbeef')):
                with self.assertRaises(ValueError):m.bind_source(scope,source,changed)
            with self.assertRaises(ValueError):m.bind_source(scope,dict(source,owner='bob'),record)
            db.execute('DELETE FROM native_pending_sources');db.commit()
            with self.assertRaises(ValueError):m.bind_source(m.load_scope(path,'alice'),source,record)

    def test_missing_database_is_not_created(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'missing.db'
            with self.assertRaises(OSError):m.load_scope(path,'alice')
            self.assertFalse(path.exists())

    def test_native_worker_program_sets_profile_before_import_and_always_resets(self):
        m = self.module()
        with self.fixture() as (path,db,binding,record):
            scope = m.load_scope(path,'alice')
            code = m.worker_script('print("done")',{},scope,review_queue.HEADER,review_queue.SKILL_HELPERS)
            compile(code,'native-review-operation','exec')
            self.assertLess(code.index('set_hermes_home_override('), code.index('from tools import write_approval'))
            self.assertIn('finally:',code)
            self.assertIn('reset_hermes_home_override(',code)
            self.assertNotIn('/profile/memories/',code)

    def test_original_ledger_receipts_are_separate_per_owner(self):
        self.assertTrue(callable(getattr(review_queue,'native_context',None)), 'native review context is missing')
        m=self.module()
        with self.fixture() as (path,db,binding,record), tempfile.TemporaryDirectory() as temp:
            with patch.object(review_queue,'ROOT',Path(temp)):
                original=review_queue.receipt_root()
                with review_queue.native_context(m.load_scope(path,'alice')):
                    self.assertEqual(review_queue.receipt_root(),original/'native'/hashlib.sha256(b'alice').hexdigest())
                self.assertEqual(review_queue.receipt_root(),original)


    def test_original_decide_backup_replay_and_unknown_work_in_native_scope(self):
        from types import SimpleNamespace
        import sys
        m=self.module()
        with self.fixture() as (path,db,binding,record), tempfile.TemporaryDirectory() as temp:
            scope=m.load_scope(path,'alice');source=scope['sources'][0]
            decision=dict(id='native:ab1234cd',decision='approve',expected_sha=source['record_sha256'],target_sha='a'*64,
                          reason='Confirmed preference from this owner',evidence='original user message',native_source=source)
            root=Path(temp);file=root/'decision.input';file.write_text(json.dumps(decision),encoding='utf-8')
            calls=[]
            def run(code,data=None):
                calls.append(code)
                if code==review_queue.LIST:return dict(native=[dict(id=decision['id'],sha256=decision['expected_sha'],target_sha256='a'*64)],skills=[],experiences=[])
                if code==review_queue.SNAPSHOT:return dict(bytes_base64='b3JpZ2luYWw=',sha256='a'*64)
                self.assertEqual(code,review_queue.NATIVE)
                durable=json.loads(next(review_queue.receipt_root().glob('*.json')).read_text('utf-8'))
                self.assertEqual(durable['status'],'applying')
                self.assertEqual(durable['backup']['bytes_base64'],'b3JpZ2luYWw=')
                return dict(success=True,applied=True)
            lock=SimpleNamespace(flock=lambda *args:None,LOCK_EX=1)
            with patch.object(review_queue,'ROOT',root),patch.object(review_queue,'run',run),patch.object(review_queue,'export_reviews'),patch.dict(sys.modules,{'fcntl':lock}),patch.object(sys,'argv',['review_queue.py','decide','--decision-file',str(file)]),review_queue.native_context(scope):
                review_queue.main();count=len(calls)
                review_queue.main();self.assertEqual(len(calls),count)
                self.assertEqual(calls.count(review_queue.NATIVE),1)
                self.assertEqual(json.loads(next(review_queue.receipt_root().glob('*.json')).read_text('utf-8'))['decision']['native_source'],source)
                self.assertEqual(list(root.glob('*.json')),[])

    def test_worker_memory_fixture_applies_only_selected_profile_and_resets_on_failure(self):
        from io import StringIO
        from types import SimpleNamespace
        import sys
        from pathlib import PurePosixPath
        m=self.module()
        with self.fixture() as (path,db,binding,record), tempfile.TemporaryDirectory() as temp:
            with patch.object(m,'PROFILE_BASE',PurePosixPath(Path(temp).as_posix())):
                scope=m.load_scope(path,'alice')
                profile=Path(scope['profile_root']);memories=profile/'memories';memories.mkdir(parents=True)
                target=memories/'USER.md';target.write_text('old preference',encoding='utf-8')
                home=['original-profile'];pending={record['id']:record};applied=[]
                def override(value):
                    old=home[0];home[0]=str(value);return old
                def reset(token):home[0]=token
                def apply(payload,store):
                    self.assertEqual(home[0],str(profile));applied.append(payload)
                    target.write_text(payload['content'],encoding='utf-8');return dict(success=True)
                approval=SimpleNamespace(MEMORY='memory',SKILLS='skills',get_pending=lambda kind,key:pending.get(key),
                                         discard_pending=lambda kind,key:pending.pop(key,None) is not None,
                                         write_approval_enabled=lambda kind:True)
                memory=SimpleNamespace(load_on_disk_store=lambda:object(),apply_memory_pending=apply)
                constants=SimpleNamespace(set_hermes_home_override=override,reset_hermes_home_override=reset)
                data=dict(id='native:ab1234cd',decision='approve',expected_sha=scope['sources'][0]['record_sha256'],
                          target_sha=hashlib.sha256(target.read_bytes()).hexdigest())
                modules={'hermes_constants':constants,'tools':SimpleNamespace(write_approval=approval,skill_manager_tool=SimpleNamespace()),'tools.memory_tool':memory}
                with patch.dict(sys.modules,modules),patch.object(sys,'path',list(sys.path)),patch('sys.stdout',StringIO()) as output:
                    exec(m.worker_script(m.MEMORY,data,scope,review_queue.HEADER,review_queue.SKILL_HELPERS),{})
                    self.assertEqual(json.loads(output.getvalue())['applied'],True)
                    self.assertEqual(home[0],'original-profile')
                    with self.assertRaisesRegex(RuntimeError,'fixture failure'):
                        exec(m.worker_script('raise RuntimeError("fixture failure")',{},scope,review_queue.HEADER,review_queue.SKILL_HELPERS),{})
                self.assertEqual(home[0],'original-profile');self.assertEqual(len(applied),1)
                self.assertEqual(target.read_text('utf-8'),'Prefer Chinese');self.assertEqual(pending,{})


    def test_native_receipt_projection_is_readable_by_actual_profile_uid(self):
        import os
        from unittest.mock import call
        m=self.module()
        with self.fixture() as (path,db,binding,record), tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'root-review';root.mkdir()
            profile=Path(temp)/'owner-profile';profile.mkdir()
            scope=m.load_scope(path,'alice');scope['profile_root']=str(profile)
            actual_stat=Path.stat
            def stat(target,*args,**kwargs):
                value=actual_stat(target,*args,**kwargs)
                if target==profile:
                    fields=list(value);fields[4]=9876;fields[5]=9876
                    return os.stat_result(fields)
                return value
            with patch.object(review_queue,'ROOT',root),review_queue.native_context(scope),patch.object(Path,'stat',stat),patch.object(os,'fchown',create=True) as file_owner,patch.object(os,'chown',create=True) as directory_owner:
                review_queue.receipt_root().mkdir(parents=True)
                review_queue.export_reviews()
                self.assertEqual(file_owner.call_count,1,'native projection must retain worker read access')
                self.assertEqual(file_owner.call_args.args[1:],(9876,9876))
                directory_owner.assert_called_once_with(str(profile/'memory-review'),9876,9876)
                self.assertEqual(json.loads((profile/'memory-review/approval-receipts.json').read_text('utf-8')),[])
                self.assertTrue((review_queue.receipt_root()/'approved-skills.json').is_file())
                self.assertEqual(list((profile/'memory-review').glob('*.tmp')),[])


if __name__ == '__main__':unittest.main()

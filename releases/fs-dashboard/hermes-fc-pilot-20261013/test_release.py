import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.stage=Path(self.tmp.name)/'stage';self.root=Path(self.tmp.name)/'root';self.stage.mkdir();self.root.mkdir()
        path=Path(__file__).parent/'shared_candidate/release_navigation.py'
        spec=importlib.util.spec_from_file_location('hermes_publisher',path);self.publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.publisher)
        files=[]
        for rel,target in self.publisher.HERMES_TARGETS.items():
            p=self.stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'reviewed fixture')
            before=None
            if rel.startswith('hermes/shared/'):
                old=self.root/target.lstrip('/');old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes(b'old fixture');before=hashlib.sha256(b'old fixture').hexdigest()
            files.append({'candidate':rel,'target':target,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'beforeSha256':before})
        protected=['/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')]
        protected+=['/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py']
        self.manifest={'schemaVersion':1,'scope':self.publisher.HERMES_SCOPE,'releaseReady':True,'files':files,
            'unchangedRequired':[{'path':p,'sha256':'a'*64} for p in protected],'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'}},
            'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544','businessWrites':False,'timersChanged':False}

    def test_exact_scope_keeps_other_publishers_unchanged(self):
        self.assertEqual(len(self.publisher.validate(self.manifest,self.stage)),34)
        self.assertEqual(self.publisher.expected_files({'scope':self.publisher.DEEP_SCOPE}),set(self.publisher.DEEP_TARGETS))
        with self.assertRaises(ValueError):self.publisher.target_for('hermes/shared/boss_insights.py')

    def test_hash_target_baseline_and_consumer_omissions_refused(self):
        for change in ('hash','target','baseline','protected','scope'):
            value=json.loads(json.dumps(self.manifest))
            if change=='hash':value['files'][0]['sha256']='b'*64
            if change=='target':value['files'][0]['target']='/etc/passwd'
            if change=='baseline':value['files'][0]['beforeSha256']=None
            if change=='protected':value['unchangedRequired']=[r for r in value['unchangedRequired'] if not r['path'].endswith('boss_insights.py')]
            if change=='scope':value['files'].pop()
            with self.assertRaises(ValueError):self.publisher.validate(value,self.stage)

    def update_manifest(self):
        value=json.loads(json.dumps(self.manifest));value['scope']=self.publisher.HERMES_UPDATE_SCOPE
        value['files']=[r for r in value['files'] if r['candidate'] in self.publisher.HERMES_UPDATE_TARGETS]
        for row in value['files']:row['beforeSha256']='b'*64
        value['runtimeRequired']['fs-hermes-fc.service']={'ActiveState':'active'}
        value['unchangedRequired'] += [{'path':p,'sha256':'c'*64} for p in set(self.publisher.HERMES_TARGETS.values())-set(self.publisher.HERMES_UPDATE_TARGETS.values())]
        return value

    def test_history_scope_exact_three_existing_sources_and_45_protected(self):
        value=json.loads(json.dumps(self.manifest));value['scope']=self.publisher.HERMES_HISTORY_SCOPE
        value['files']=[r for r in value['files'] if r['candidate'] in self.publisher.HERMES_HISTORY_TARGETS]
        for row in value['files']:row['beforeSha256']='b'*64
        value['runtimeRequired']['fs-hermes-fc.service']={'ActiveState':'active'}
        value['unchangedRequired'] += [{'path':p,'sha256':'c'*64} for p in set(self.publisher.HERMES_TARGETS.values())-set(self.publisher.HERMES_HISTORY_TARGETS.values())]
        self.assertEqual(len(self.publisher.validate(value,self.stage)),3);self.assertEqual(len(value['unchangedRequired']),45)
        for change in ('baseline','protected','extra'):
            bad=json.loads(json.dumps(value))
            if change=='baseline':bad['files'][0]['beforeSha256']=None
            if change=='protected':bad['unchangedRequired'].pop()
            if change=='extra':bad['files'].append(next(r for r in self.manifest['files'] if r['candidate']=='hermes/shared/range_api.py'))
            with self.assertRaises(ValueError):self.publisher.validate(bad,self.stage)

    def worker_manifest(self):
        value=json.loads(json.dumps(self.manifest));value['scope']=self.publisher.HERMES_WORKER_SCOPE
        value['files']=[r for r in value['files'] if r['candidate'] in self.publisher.HERMES_WORKER_TARGETS]
        value['files'][0]['beforeSha256']='b'*64
        value['runtimeRequired']['fs-hermes-fc.service']={'ActiveState':'active'}
        value['unchangedRequired'] += [{'path':p,'sha256':'c'*64} for p in set(self.publisher.HERMES_TARGETS.values())-set(self.publisher.HERMES_WORKER_TARGETS.values())]
        return value

    def test_worker_update_is_one_existing_target_and_all_47_other_files_protected(self):
        value=self.worker_manifest();self.assertEqual(len(self.publisher.validate(value,self.stage)),1)
        self.assertEqual(len(value['unchangedRequired']),47)
        for change in ('baseline','omission','extra'):
            bad=json.loads(json.dumps(value))
            if change=='baseline':bad['files'][0]['beforeSha256']=None
            if change=='omission':bad['unchangedRequired'].pop()
            if change=='extra':bad['files'].append(next(r for r in self.manifest['files'] if r['candidate']=='hermes/shared/range_api.py'))
            with self.assertRaises(ValueError):self.publisher.validate(bad,self.stage)

    def test_worker_restart_stays_inside_admission_fence_and_does_not_restart_range(self):
        class Fence:root=self.root
        key=self.root/'run/fs-hermes-fc/api-key';key.parent.mkdir(parents=True);key.write_text('synthetic-control-only')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*unused):pass
            def read(self,_):return b'{"status":"ready"}'
        events=[]
        with patch.object(self.publisher.subprocess,'run',side_effect=lambda args,**unused:events.append(args)),patch.object(self.publisher.urllib.request,'urlopen',return_value=Response()):
            with self.assertRaisesRegex(ValueError,'fence required'):self.publisher.restart_for(self.worker_manifest())
            self.publisher.restart_for(self.worker_manifest(),Fence())
        self.assertEqual(events,[['systemctl','restart','fs-hermes-fc.service'],['systemctl','is-active','--quiet','fs-hermes-fc.service']])

    def test_update_scope_is_exact_five_and_preserves_initial_gate(self):
        value=self.update_manifest();self.assertEqual(len(self.publisher.validate(value,self.stage)),5)
        self.assertEqual(len(self.publisher.validate(self.manifest,self.stage)),34)
        attempted=json.loads(json.dumps(self.manifest))
        for row in attempted['files']:row['beforeSha256']='b'*64
        with self.assertRaisesRegex(ValueError,'initial target baselines'):self.publisher.validate(attempted,self.stage)
        for change in ('baseline','omitted_target','extra_target','omitted_protected','unit','image','business_write'):
            changed=json.loads(json.dumps(value))
            if change=='baseline':changed['files'][0]['beforeSha256']=None
            if change=='omitted_target':changed['files'].pop()
            if change=='extra_target':changed['files'].append(next(r for r in self.manifest['files'] if r['candidate']=='hermes/shared/range_api.py'))
            if change=='omitted_protected':changed['unchangedRequired']=[r for r in changed['unchangedRequired'] if not r['path'].endswith('/range_api.py')]
            if change=='unit':del changed['runtimeRequired']['fs-hermes-fc.service']
            if change=='image':changed['imageId']='unreviewed'
            if change=='business_write':changed['businessWrites']=True
            with self.assertRaises(ValueError):self.publisher.validate(changed,self.stage)

    def test_update_waits_for_pending_running_and_unreconciled_hermes(self):
        import sqlite3
        from contextlib import closing
        path=self.root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(state TEXT)')
        self.publisher.hermes_quiescent(self.root)
        for state in ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE'):
            with closing(sqlite3.connect(path)) as db,db:db.execute('DELETE FROM requests');db.execute('INSERT INTO requests VALUES(?)',(state,))
            with self.assertRaisesRegex(ValueError,'defer update'):self.publisher.hermes_quiescent(self.root)
        with closing(sqlite3.connect(path)) as db,db:db.execute('DELETE FROM requests');db.execute("INSERT INTO requests VALUES('FAILED')")
        self.publisher.hermes_quiescent(self.root)

    def test_uses_original_locks_and_active_report_guard(self):
        import inspect
        source=inspect.getsource(self.publisher.apply)
        self.assertIn('with locks(root),live_lock(manifest,root),hermes_admission_fence(manifest,root) as admission_fence,model_release_lock(manifest,root)',source)
        self.assertIn('target drift before replacement',source)
        self.assertIn('rollback_journal(backup,journal,root)',source)

    @unittest.skipUnless(os.name=='posix','actual publisher flock is a Linux deployment gate')
    def test_legacy_sqlite_writer_is_blocked_by_bootstrap_fence(self):
        from contextlib import closing
        import sqlite3,threading
        from controller import admission_guard
        path=self.root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(state TEXT)')
        errors=[]
        def old_writer():
            try:
                with closing(sqlite3.connect(path,timeout=0)) as db,db:db.execute("INSERT INTO requests VALUES('PREPARING')")
            except sqlite3.OperationalError as error:errors.append(str(error))
        with self.publisher.hermes_admission_fence(self.update_manifest(),self.root):
            thread=threading.Thread(target=old_writer);thread.start();thread.join(timeout=5)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,['database is locked'])
            with admission_guard(path.with_name('admission.lock')) as allowed:self.assertFalse(allowed)
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)
        with closing(sqlite3.connect(path)) as db,db:db.execute("INSERT INTO requests VALUES('FAILED')")

    @unittest.skipUnless(os.name=='posix','actual publisher flock is a Linux deployment gate')
    def test_uncertain_mutation_stops_old_process_before_releasing_sqlite_fence(self):
        from contextlib import closing
        import sqlite3
        path=self.root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(state TEXT)')
        events=[]
        with patch.object(self.publisher.subprocess,'run',side_effect=lambda args,**unused:events.append(args)):
            with self.assertRaisesRegex(RuntimeError,'unconfirmed rollback'):
                with self.publisher.hermes_admission_fence(self.update_manifest(),self.root) as fence:
                    fence.modified=True;raise RuntimeError('unconfirmed rollback')
        self.assertEqual(events,[['systemctl','stop','fs-business-range.service']])
        with closing(sqlite3.connect(path)) as db,db:db.execute("INSERT INTO requests VALUES('FAILED')")

    @unittest.skipUnless(os.name=='posix','actual publisher flock is a Linux deployment gate')
    def test_failed_rollback_after_startup_stops_new_process_before_reopening_admission(self):
        from contextlib import closing
        import sqlite3
        from controller import admission_guard
        path=self.root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(state TEXT)')
        events=[]
        def control(args,**unused):
            with admission_guard(path.with_name('admission.lock')) as allowed:self.assertFalse(allowed)
            events.append(args)
        with patch.object(self.publisher.subprocess,'run',side_effect=control):
            with self.assertRaisesRegex(RuntimeError,'rollback CAS drift'):
                with self.publisher.hermes_admission_fence(self.update_manifest(),self.root) as fence:
                    fence.modified=True;fence.stop_then_unlock_database()
                    self.assertIsNone(fence.db)
                    raise RuntimeError('rollback CAS drift')
        self.assertEqual(events,[['systemctl','stop','fs-business-range.service']]*2)
        with admission_guard(path.with_name('admission.lock')) as allowed:self.assertTrue(allowed)

    @unittest.skipUnless(os.name=='posix','actual publisher flock is a Linux deployment gate')
    def test_confirmed_release_does_not_stop_service_on_fence_exit(self):
        from contextlib import closing
        import sqlite3
        path=self.root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(state TEXT)')
        events=[]
        with patch.object(self.publisher.subprocess,'run',side_effect=lambda args,**unused:events.append(args)):
            with self.publisher.hermes_admission_fence(self.update_manifest(),self.root) as fence:
                fence.modified=True;fence.stop_then_unlock_database();fence.confirmed=True
        self.assertEqual(events,[['systemctl','stop','fs-business-range.service']])

    def test_uid_firewall_policy_never_exposes_other_service_or_key(self):
        import network_guard
        self.assertEqual(network_guard.UID,9876)
        self.assertEqual([r[r.index('--dport')+1] for r in network_guard.rules('iptables') if '--dport' in r],['8940','8941'])
        self.assertEqual(network_guard.rules('ip6tables'),[['-j','REJECT']])
        replies=[r for r in network_guard.rules('iptables') if '--sport' in r]
        self.assertEqual(replies,[['-d','127.0.0.1/32','-p','tcp','--sport','8941','-m','conntrack','--ctstate','ESTABLISHED','-j','ACCEPT']])
        unit=(Path(__file__).parent/'fs-hermes-fc.service').read_text('utf-8')
        self.assertIn('--user 9876:9876',unit);self.assertIn('--read-only',unit)
        for denied in ('FS_DAILY_MODEL_KEY_FILE','docker.sock','/var/lib/fs-business-ranges','DEEPSEEK_API_KEY'):self.assertNotIn(denied,unit)


if __name__=='__main__':unittest.main()

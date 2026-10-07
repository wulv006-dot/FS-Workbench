"""New-diff tests. Model cases are not POSIX acceptance; native cases require Linux root."""
import contextlib
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import launch
import verified_loader as loader
import probe
from storage import Storage
from fixture import Fixture
import runner


class ModelMutex:
    """Nonblocking scheduler model; no claim of POSIX flock/permission coverage."""
    def __init__(self,busy_type):self.lock=threading.Lock();self.busy_type=busy_type
    @contextlib.contextmanager
    def __call__(self):
        if not self.lock.acquire(False):raise self.busy_type('queue_mutation_busy')
        try:yield
        finally:self.lock.release()


class LoaderTests(unittest.TestCase):
    def test_mutable_file_entrypoint_refused_before_artifact_access(self):
        with patch.object(launch,'collect') as collect:
            with self.assertRaisesRegex(ValueError,'approved_inline_launcher_required'):launch.main()
            collect.assert_not_called()
    def binding(self):
        schema=json.loads((SOURCE/'BINDING-SCHEMA.json').read_bytes())
        defaults={'str':'synthetic','int':1,'bool':False,'dict':{},'list':[]}
        scope={k:defaults[t].copy() if isinstance(defaults[t],(dict,list)) else defaults[t] for k,t in schema['required_types'].items()}
        pid='00000000-0000-4000-8000-000000000001';cid='00000000-0000-4000-8000-000000000002'
        scope.update(binding_version=4,binding_status='APPROVED',source_manifest_sha256='a'*64,artifact_root='/synthetic/artifact',state_root='/var/lib/fc27-cloud/state',rollback_root='/var/lib/fc27-cloud/rollback',player_job_id=pid,coin_execution_id=cid,service_gid=11028)
        scope['allowed_metadata_targets']=['player-sync/'+pid+'.json','jobs/'+pid+'.json']
        scope['expected_files']={p:'a'*64 for p in ['player-sync/'+pid+'.json','jobs/'+pid+'.json','executions/'+cid+'.json','jobs/'+cid+'.json','all-coin-sync/'+cid+'.json','config/automation.json','config/player-sync.json','/var/lib/fc27-gallery/settings.json']}
        scope['file_metadata']={p:{} for p in scope['expected_files']}
        scope['expected_sources']={'/opt/fc27-cloud-browser/'+n+'.py':'a'*64 for n in launch.APP_MODULES-{'p2pah_session_service'}}
        scope['source_metadata']={p:{} for p in scope['expected_sources']}
        meta={'uid':0,'gid':0,'mode':'0o644','device':1,'inode':2,'nlink':1}
        scope['lock_metadata']={'automation-tick.lock':meta.copy()}
        scope['policy_lock_metadata']={'/var/lib/fc27-cloud/config/'+n+'.lock':meta.copy() for n in ['automation','player-sync']}
        scope['writer_protocol_evidence']={role:{'protocol':'existing-tick-inode-v4','pid':i+100,'start_ticks':str(i+1)} for i,role in enumerate(['api','worker','timer'])}
        scope['host_python']={'executable_sha256':'b'*64}
        at=datetime.now(timezone.utc).isoformat()
        api=scope['writer_protocol_evidence']['api']
        api['health_receipt']={'source':'resident-api-http','captured_at':at,'method':'GET','endpoint_path':'/health','http_status':200,'pid':api['pid'],'start_ticks':api['start_ticks'],'response':{'api_pid':api['pid'],'queue_protocol':'existing-tick-inode-v4'}}
        timer=scope['writer_protocol_evidence']['timer']
        argv=['/usr/bin/python3','/opt/fc27-cloud-browser/automation_tick.py']
        timer['effective_unit_receipt']={'source':'systemd-effective-unit','captured_at':at,'unit_id':'fc27-automation-tick.service','load_state':'loaded','exec_start_argv':argv,'source_sha256':'a'*64,'interpreter_sha256':'b'*64,'fragment':{'path':'/etc/systemd/system/fc27-automation-tick.service','sha256':'c'*64},'drop_ins':[]}
        timer['protocol_probe_receipt']={'source':'effective-unit-readonly-probe','captured_at':at,'argv':argv+['--queue-protocol'],'returncode':0,'source_sha256':'a'*64,'interpreter_sha256':'b'*64,'result':{'read_only':True,'status':'ready','queue_protocol':'existing-tick-inode-v4'}}
        scope['proof_provenance']={'loader':'sealed-memory-v1','modules':{n:{'path':'/usr/local/bin/p2pah_session_service.py' if n=='p2pah_session_service' else '/opt/fc27-cloud-browser/'+n+'.py','sha256':'a'*64} for n in ['player_sync_job','coin_all_sync_job','storefront_monitor','p2pah_session_service']}}
        return scope,schema
    def test_binding_is_schema_plus_exact_cas_not_placeholder_runtime(self):
        scope,schema=self.binding();launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_draft_binding_refused(self):
        scope,schema=self.binding();scope['binding_status']='DRAFT_NOT_APPROVED'
        with self.assertRaisesRegex(ValueError,'fresh_v4_binding_required'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_missing_runtime_cas_refused(self):
        scope,schema=self.binding();scope['expected_files'].pop('config/player-sync.json')
        with self.assertRaisesRegex(ValueError,'cas_closure_incomplete'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_missing_policy_inode_refused(self):
        scope,schema=self.binding();next(iter(scope['policy_lock_metadata'].values())).pop('inode')
        with self.assertRaisesRegex(ValueError,'lock_metadata_invalid'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_unproven_resident_writer_refused(self):
        scope,schema=self.binding();scope['writer_protocol_evidence']['api']['protocol']='legacy'
        with self.assertRaisesRegex(ValueError,'writer_protocol_not_proven'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_omitted_probe_transitive_origin_refused(self):
        scope,schema=self.binding();scope['proof_provenance']['modules'].pop('p2pah_session_service')
        with self.assertRaisesRegex(ValueError,'proof_closure_incomplete'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_binding_cannot_approve_different_source_than_frozen_artifact(self):
        scope,schema=self.binding();files={'app/'+n+'.py':b'synthetic' for n in launch.APP_MODULES}
        with self.assertRaisesRegex(ValueError,'source_artifact_mismatch'):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact',files)
    def bundle(self):
        files={str(p.relative_to(SOURCE)).replace('\\','/'):p.read_bytes() for p in SOURCE.rglob('*') if p.is_file() and p.name!='SOURCE-MANIFEST.json'}
        manifest={'version':4,'files':{n:loader.digest(v) for n,v in files.items()}}
        raw=json.dumps(manifest,sort_keys=True).encode();files['SOURCE-MANIFEST.json']=raw
        dirs={str(p.relative_to(SOURCE)).replace('\\','/') for p in SOURCE.rglob('*') if p.is_dir()}
        return files,dirs,loader.digest(raw)
    def test_exact_source_closure(self):
        self.assertEqual(launch.validate_bundle(*self.bundle())['version'],4)
    def test_extra_shadow_file_rejected(self):
        files,dirs,sha=self.bundle();files['datetime.py']=b'raise RuntimeError()'
        with self.assertRaisesRegex(ValueError,'extra_or_missing'):launch.validate_bundle(files,dirs,sha)
    def test_extra_directory_rejected(self):
        files,dirs,sha=self.bundle();dirs.add('leftovers')
        with self.assertRaisesRegex(ValueError,'extra_or_missing'):launch.validate_bundle(files,dirs,sha)
    def test_changed_candidate_before_exec(self):
        files,dirs,sha=self.bundle();files['probe.py']+=b'\nraise RuntimeError()'
        with self.assertRaisesRegex(ValueError,'hash_changed'):launch.validate_bundle(files,dirs,sha)
    def test_transitive_hash_failure_executes_nothing(self):
        names={'synthetic_a','synthetic_b'};sources={n:b'raise RuntimeError("executed")' for n in names}
        expected={n:loader.digest(v) for n,v in sources.items()};expected['synthetic_b']='0'*64
        with self.assertRaisesRegex(ValueError,'before_import'):loader.install(sources,expected,{n:'synthetic' for n in names},names)
        self.assertTrue(names.isdisjoint(sys.modules))
    def test_sealed_bytes_survive_input_mutation(self):
        name='synthetic_snapshot';raw=bytearray(b'value=7\n');sources={name:raw}
        finder=loader.install(sources,{name:loader.digest(raw)},{name:'synthetic'}, {name})
        try:
            raw[:]=b'raise RuntimeError("changed")';module=importlib.import_module(name)
            self.assertEqual(module.value,7);self.assertTrue(module.__file__.startswith('verified-memory:'))
        finally:sys.meta_path.remove(finder);sys.modules.pop(name,None)
    def test_preloaded_dependency_rejected(self):
        name='synthetic_loaded';sys.modules[name]=object()
        try:
            with self.assertRaisesRegex(ValueError,'loaded_before'):loader.install({name:b''},{name:loader.digest(b'')},{name:'synthetic'},{name})
        finally:sys.modules.pop(name,None)
    def test_probe_refuses_runtime_drift_before_business_import(self):
        base={'python':sys.version,'executable':sys.executable,'executable_sha256':loader.digest(Path(sys.executable).resolve().read_bytes()),'loader':'sealed-memory-v1','modules':{}}
        with patch.object(probe,'read_verified_sources',side_effect=ValueError('runtime_source_changed_before_import')):
            with self.assertRaisesRegex(ValueError,'before_import'):probe.main({'proof_provenance':base})
    def test_probe_refuses_wrong_interpreter_before_source_read(self):
        with patch.object(probe,'read_verified_sources') as read:
            with self.assertRaisesRegex(ValueError,'interpreter_changed_before_import'):probe.main({'proof_provenance':{}})
            read.assert_not_called()


class AdoptionReceiptTests(unittest.TestCase):
    def binding(self):return LoaderTests().binding()
    def refused(self,change,reason):
        scope,schema=self.binding();change(scope['writer_protocol_evidence'])
        with self.assertRaisesRegex(ValueError,reason):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_api_receipt_missing_even_with_new_disk_and_declared_protocol(self):
        self.refused(lambda e:e['api'].pop('health_receipt'),'missing_or_wrong_origin')
    def test_api_old_resident_with_new_disk_rejected_before_storage_access(self):
        scope,_=self.binding();scope['writer_protocol_evidence']['api']['health_receipt']['response']['queue_protocol']='legacy'
        storage=types.SimpleNamespace(fs=unittest.mock.Mock())
        with self.assertRaisesRegex(ValueError,'resident_health_protocol'):runner.validate_writers(scope,storage,launch.validate_writer_receipts)
        storage.fs.read_path.assert_not_called()
    def test_api_receipt_wrong_pid(self):
        self.refused(lambda e:e['api']['health_receipt']['response'].update(api_pid=999),'resident_health_protocol')
    def test_api_receipt_wrong_start(self):
        self.refused(lambda e:e['api']['health_receipt'].update(start_ticks='999'),'resident_identity')
    def test_api_selftest_origin_refused(self):
        self.refused(lambda e:e['api']['health_receipt'].update(source='candidate-api-function'),'wrong_origin')
    def test_api_self_pid_refused(self):
        def change(e):
            api=e['api'];api['pid']=os.getpid();api['health_receipt']['pid']=os.getpid();api['health_receipt']['response']['api_pid']=os.getpid()
        self.refused(change,'resident_identity')
    def test_api_stale_receipt_refused(self):
        self.refused(lambda e:e['api']['health_receipt'].update(captured_at=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat()),'stale')
    def test_timer_missing_effective_unit_even_with_new_probe(self):
        self.refused(lambda e:e['timer'].pop('effective_unit_receipt'),'missing_or_wrong_origin')
    def test_timer_old_effective_unit_with_new_script_rejected_before_storage_access(self):
        scope,_=self.binding();scope['writer_protocol_evidence']['timer']['effective_unit_receipt']['exec_start_argv']=['/usr/bin/python3','/opt/old/automation_tick.py']
        storage=types.SimpleNamespace(fs=unittest.mock.Mock())
        with self.assertRaisesRegex(ValueError,'effective_unit_command'):runner.validate_writers(scope,storage,launch.validate_writer_receipts)
        storage.fs.read_path.assert_not_called()
    def test_timer_missing_probe(self):
        self.refused(lambda e:e['timer'].pop('protocol_probe_receipt'),'missing_or_wrong_origin')
    def test_timer_old_probe_protocol(self):
        self.refused(lambda e:e['timer']['protocol_probe_receipt']['result'].update(queue_protocol='legacy'),'effective_unit_probe')
    def test_timer_probe_uses_different_interpreter(self):
        self.refused(lambda e:e['timer']['protocol_probe_receipt'].update(argv=['/usr/bin/python3.9','/opt/fc27-cloud-browser/automation_tick.py','--queue-protocol']),'effective_unit_probe')
    def test_timer_dropin_provenance_required(self):
        self.refused(lambda e:e['timer']['effective_unit_receipt'].pop('drop_ins'),'effective_unit_provenance')
    def test_timer_stale_effective_unit(self):
        self.refused(lambda e:e['timer']['effective_unit_receipt'].update(captured_at=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat()),'stale')
    def test_timer_stale_protocol_probe(self):
        self.refused(lambda e:e['timer']['protocol_probe_receipt'].update(captured_at=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat()),'stale')
    def test_receipt_continuity_revalidated_each_context(self):
        scope,_=self.binding();e=scope['writer_protocol_evidence'];heartbeat={'at':datetime.now(timezone.utc).isoformat(),'pid':e['worker']['pid'],'queue_protocol':'existing-tick-inode-v4'}
        storage=types.SimpleNamespace(root='/var/lib/fc27-cloud',fs=types.SimpleNamespace(read_path=lambda *a:json.dumps(heartbeat).encode()))
        command=lambda p:types.SimpleNamespace(read_bytes=lambda:('/opt/fc27-cloud-browser/fc27_cloud_'+('api' if '/100/' in str(p) else 'worker')+'.py\0').encode())
        with patch.object(runner,'process_identity',side_effect=lambda p:str(p-99)),patch.object(runner,'Path',side_effect=command):
            runner.validate_writers(scope,storage,launch.validate_writer_receipts)
            e['api']['health_receipt']['captured_at']=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat()
            with self.assertRaisesRegex(ValueError,'stale'):runner.validate_writers(scope,storage,launch.validate_writer_receipts)
    def test_runner_refuses_missing_approved_validator_before_runtime(self):
        with self.assertRaisesRegex(ValueError,'approved_writer_receipt_validator_required'):runner.run({},'a'*64,'b'*64,{})


class QueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names=launch.APP_MODULES
        sources={n:(SOURCE/'app'/(n+'.py')).read_bytes() for n in names}
        cls.finder=loader.install(sources,{n:loader.digest(v) for n,v in sources.items()}, {n:'synthetic/'+n+'.py' for n in names}, names)
        with patch.dict(os.environ,{},clear=True):
            cls.api=importlib.import_module('fc27_cloud_api');cls.worker=importlib.import_module('fc27_cloud_worker');cls.tick=importlib.import_module('automation_tick')
    @classmethod
    def tearDownClass(cls):
        sys.meta_path.remove(cls.finder)
        for name in launch.APP_MODULES:sys.modules.pop(name,None)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        for n in ['queue','jobs','state','config']:(self.root/n).mkdir()
        self.patches=[];self.mutex=ModelMutex(self.tick.QueueBusy);self.syncs=[]
        for m in [self.api,self.worker,self.tick]:
            self.add(patch.object(m,'ROOT',self.root));self.add(patch.object(m,'queue_mutation',self.mutex));self.add(patch.object(m,'sync_directory',lambda p:self.syncs.append(Path(p).name)))
        self.add(patch.object(self.worker,'QUEUE',self.root/'queue'));self.add(patch.object(self.worker,'JOBS',self.root/'jobs'))
        self.add(patch.object(self.tick,'POLICY_FILE',self.root/'config/automation.json'))
        self.add(patch.object(self.worker,'save_job',lambda j:(self.root/'jobs'/(j['job_id']+'.json')).write_text(json.dumps(j),encoding='utf-8')))
        self.add(patch.object(self.worker.os,'chown',lambda *args:None,create=True))
        self.add(patch.object(self.worker,'load_player_sync_policy',lambda:{'enabled':True,'revision':8}))
        self.handler=object.__new__(self.api.Handler)
    def add(self,p):p.start();self.patches.append(p)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def post(self,path,payload):
        h=self.handler;h.path=path;h.headers={'X-Forwarded-Proto':'https'}
        h.actor=lambda:'wulv';h.body=lambda:payload;responses=[];h.respond=lambda status,data:responses.append((status,data))
        with patch.object(self.api,'writer_status',return_value='ready'),patch.object(self.api,'load_policy',return_value={'revision':28}):h.do_POST()
        return responses[-1]
    def test_all_six_api_entrypoints_busy_without_accepted_job(self):
        uid='00000000-0000-4000-8000-000000000003';event='00000000-0000-4000-8000-000000000004'
        routes=[('/collect',{}),('/reprice/preview',{'run_id':uid}),('/reprice/recalculate',{'run_id':uid}),('/reprice/execute',{'preview_id':uid,'client_event_id':event,'selected_platforms':['PS']}),('/reprice/'+uid+'/restore/preview',{}),('/reprice/'+uid+'/restore',{'restore_preview_id':uid,'client_event_id':event,'selected_platforms':['PS']})]
        with self.mutex():
            for path,payload in routes:
                status,data=self.post(path,payload);self.assertEqual(status,503,path);self.assertTrue(data['retryable']);self.assertFalse(data['accepted'])
        self.assertEqual(list((self.root/'queue').iterdir()),[])
    def test_event_dedup_after_worker_claim_preserves_response_and_job(self):
        event='00000000-0000-4000-8000-000000000004'
        for kind in ['execute','restore']:
            with self.subTest(kind=kind):
                self.assertEqual(self.handler.enqueue(kind,'synthetic',{},event,idempotent=True),(event,True))
                claimed=self.worker.claim_next_job();original=(self.root/'jobs'/(event+'.json')).read_bytes()
                self.assertEqual(self.handler.enqueue(kind,'synthetic',{},event,idempotent=True),(event,False))
                self.assertFalse((self.root/'queue'/(event+'.json')).exists());self.assertEqual(original,(self.root/'jobs'/(event+'.json')).read_bytes())
                (self.root/'jobs'/(event+'.json')).unlink()
    def test_worker_claim_busy_preserves_accepted_task(self):
        self.handler.enqueue('collect','synthetic',{},'synthetic')
        before=(self.root/'queue/synthetic.json').read_bytes()
        with self.mutex():
            with self.assertRaises(self.tick.QueueBusy):self.worker.claim_next_job()
        self.assertEqual(before,(self.root/'queue/synthetic.json').read_bytes());self.assertEqual(list((self.root/'jobs').iterdir()),[])
    def test_claim_persists_running_before_queue_unlink(self):
        self.handler.enqueue('collect','synthetic',{},'synthetic')
        self.syncs.clear();self.assertEqual(self.worker.claim_next_job()['status'],'running')
        self.assertEqual(self.syncs,['jobs','queue'])
    def test_claim_unknown_keeps_queue_and_never_replays(self):
        self.handler.enqueue('collect','synthetic',{},'synthetic')
        with patch.object(self.worker,'sync_directory',side_effect=OSError('synthetic_sync_failure')):
            with self.assertRaises(OSError):self.worker.claim_next_job()
        self.assertTrue((self.root/'queue/synthetic.json').exists());self.assertEqual(json.loads((self.root/'jobs/synthetic.json').read_text())['status'],'running')
        with self.assertRaisesRegex(ValueError,'needs_reconcile'):self.worker.claim_next_job()
    def test_followup_busy_retains_parent_and_retries_without_nested_lock(self):
        parent={'job_id':'synthetic-parent','kind':'auto_cycle','status':'ready','result':{'status':'confirmed'},'player_sync_intent':{'enabled':True,'revision':8}}
        path=self.root/'jobs/synthetic-parent.json';path.write_text(json.dumps(parent),encoding='utf-8');before=path.read_bytes()
        with self.mutex():
            with self.assertRaises(self.tick.QueueBusy):self.worker.retry_player_followups()
        self.assertEqual(before,path.read_bytes());self.worker.retry_player_followups();self.worker.retry_player_followups()
        self.assertEqual(len(list((self.root/'queue').glob('*.json'))),1);self.assertEqual(json.loads(path.read_text())['player_sync']['status'],'queued')
    def test_user_off_prevents_pending_followup(self):
        parent={'job_id':'synthetic-parent','kind':'auto_cycle','status':'ready','result':{'status':'confirmed'},'player_sync_intent':{'enabled':True,'revision':8}}
        path=self.root/'jobs/synthetic-parent.json';path.write_text(json.dumps(parent),encoding='utf-8')
        with patch.object(self.worker,'load_player_sync_policy',return_value={'enabled':False,'revision':9}):self.worker.retry_player_followups()
        self.assertEqual(list((self.root/'queue').iterdir()),[]);self.assertEqual(json.loads(path.read_text()),parent)
    def test_timer_busy_is_bounded_retryable(self):
        with self.mutex(), patch.dict(sys.modules,{'fcntl':types.SimpleNamespace()}):
            start=time.monotonic();result=self.tick.tick();self.assertLess(time.monotonic()-start,.5)
        self.assertTrue(result['retryable']);self.assertEqual(list((self.root/'queue').iterdir()),[])
    def test_nested_mutex_fails_without_waiting(self):
        with self.mutex():
            with self.assertRaises(self.tick.QueueBusy):
                with self.mutex():self.fail('nested acquisition bypass')
    def test_two_threads_cannot_bypass_same_process_mutex(self):
        results=[]
        def publish():
            try:self.handler.enqueue('collect','synthetic',{},'other');results.append('accepted')
            except self.tick.QueueBusy:results.append('busy')
        with self.mutex():
            thread=threading.Thread(target=publish);thread.start();thread.join(1);self.assertFalse(thread.is_alive())
        self.assertEqual(results,['busy'])
    def test_reconcile_holds_mutex_across_two_proofs_and_unknown_terminal(self):
        f=Fixture();f.setUp();observed=[]
        def probe_call(ledger,raw):
            with self.assertRaises(self.tick.QueueBusy):self.handler.enqueue('collect','synthetic',{},'other')
            observed.append('blocked');return f.probe(ledger,raw)
        recovery=f.recovery();recovery.probe=probe_call;f.store.failure='jobs/'+f.pid+'.json'
        with self.mutex():result=recovery.run(apply=True)
        self.assertEqual(observed,['blocked','blocked']);self.assertEqual(result['status'],'metadata_may_be_committed_needs_readback')
        self.handler.enqueue('collect','synthetic',{},'after-unknown')
    def test_timer_due_and_retry_due_publish_inside_shared_mutex(self):
        fake=types.SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)
        for status in ['due','retry_due']:
            with self.subTest(status=status):
                for p in (self.root/'queue').glob('*.json'):p.unlink()
                last={'job_id':'synthetic-previous'};policy={'revision':28}
                locks=contextlib.ExitStack()
                for name in self.tick.RETRY_LOCKS:(self.root/'state'/name).write_bytes(b'')
                def publish(path,payload):
                    self.assertTrue(self.mutex.lock.locked());path.write_text(json.dumps(payload),encoding='utf-8')
                with patch.dict(sys.modules,{'fcntl':fake}),patch.object(self.tick,'load_policy',return_value=policy),patch.object(self.tick,'latest_cycle',return_value=last),patch.object(self.tick,'due',return_value=status),patch.object(self.tick,'retry_plan',return_value={'status':'retry_due','next_attempt':1,'retry_of':'synthetic-previous','root_job_id':'synthetic-root'}),patch.object(self.tick,'exclusive_json',side_effect=publish):
                    self.assertEqual(self.tick.tick()['status'],'queued')
                self.assertEqual(len(list((self.root/'queue').glob('*.json'))),1)


@unittest.skipUnless(sys.platform=='linux' and hasattr(os,'geteuid') and os.geteuid()==0,
                     'requires real Linux root; Windows/model tests cannot certify flock or API uid')
class NativeMutexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):QueueTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):QueueTests.tearDownClass.__func__(cls)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fc-v4-native-',dir='/run');self.root=Path(self.temp.name)
        os.chown(self.root,0,11028);os.chmod(self.root,0o750)
        for name in ['queue','jobs','state','config']:
            p=self.root/name;p.mkdir();os.chown(p,0,11028);os.chmod(p,0o750)
        os.chmod(self.root/'queue',0o2770)
        lock=self.root/'state/automation-tick.lock';lock.write_bytes(b'');os.chown(lock,0,0);os.chmod(lock,0o644)
        self.patches=[patch.object(m,'ROOT',self.root) for m in [self.api,self.worker,self.tick]]
        self.patches += [patch.object(self.worker,'QUEUE',self.root/'queue'),patch.object(self.worker,'JOBS',self.root/'jobs'),patch.object(self.tick,'POLICY_FILE',self.root/'config/automation.json')]
        for p in self.patches:p.start()
        self.handler=object.__new__(self.api.Handler)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def test_api_actual_uid_994_flocks_existing_root_readonly_inode(self):
        import multiprocessing
        ctx=multiprocessing.get_context('fork');recv,send=ctx.Pipe(False)
        def child():
            os.setgroups([11028]);os.setgid(11028);os.setuid(994)
            try:self.handler.enqueue('collect','synthetic',{},'synthetic');send.send('accepted')
            except self.tick.QueueBusy:send.send('busy')
            except Exception as exc:send.send(type(exc).__name__)
        with self.tick.queue_mutation():
            process=ctx.Process(target=child);process.start();self.assertTrue(recv.poll(3));self.assertEqual(recv.recv(),'busy');process.join(3);self.assertFalse(process.is_alive())
        self.assertEqual(list((self.root/'queue').iterdir()),[])
    def test_real_api_uid_publishes_after_release_then_worker_claims(self):
        import multiprocessing
        ctx=multiprocessing.get_context('fork');recv,send=ctx.Pipe(False)
        def child():
            os.setgroups([11028]);os.setgid(11028);os.setuid(994)
            try:send.send(self.handler.enqueue('collect','synthetic',{},'synthetic'))
            except Exception as exc:send.send(type(exc).__name__)
        process=ctx.Process(target=child);process.start();self.assertTrue(recv.poll(3));self.assertEqual(recv.recv(),'synthetic');process.join(3);self.assertFalse(process.is_alive())
        self.assertEqual(self.worker.claim_next_job()['status'],'running');self.assertFalse((self.root/'queue/synthetic.json').exists())
    def test_real_candidate_symlink_rejected_before_execution(self):
        artifact=self.root/'artifact';artifact.mkdir(mode=0o700);os.chown(artifact,0,0)
        target=self.root/'outside.py';target.write_text('raise RuntimeError("executed")',encoding='utf-8')
        (artifact/'datetime.py').symlink_to(target)
        with self.assertRaises(OSError):launch.collect(str(artifact))
    def test_real_candidate_hardlink_rejected_before_execution(self):
        artifact=self.root/'artifact';artifact.mkdir(mode=0o700);os.chown(artifact,0,0)
        target=artifact/'runner.py';target.write_text('raise RuntimeError("executed")',encoding='utf-8');os.chown(target,0,11028);os.chmod(target,0o640)
        os.link(target,artifact/'shadow.py')
        with self.assertRaisesRegex(ValueError,'metadata_untrusted'):launch.collect(str(artifact))
    def test_real_threads_and_nested_flock_do_not_bypass(self):
        results=[]
        def other():
            try:
                with self.tick.queue_mutation():results.append('bypass')
            except self.tick.QueueBusy:results.append('busy')
        with self.tick.queue_mutation():
            with self.assertRaises(self.tick.QueueBusy):
                with self.tick.queue_mutation():self.fail('nested bypass')
            thread=threading.Thread(target=other);thread.start();thread.join(2);self.assertFalse(thread.is_alive())
        self.assertEqual(results,['busy'])
    def test_real_worker_claim_and_followup_blocked(self):
        self.handler.enqueue('collect','synthetic',{},'synthetic')
        with self.tick.queue_mutation():
            with self.assertRaises(self.tick.QueueBusy):self.worker.claim_next_job()
            with self.assertRaises(self.tick.QueueBusy):self.worker.enqueue_player_sync({})
        self.assertTrue((self.root/'queue/synthetic.json').exists())
    def test_real_timer_returns_without_deadlock(self):
        with self.tick.queue_mutation():
            start=time.monotonic();self.assertTrue(self.tick.tick()['retryable']);self.assertLess(time.monotonic()-start,.5)
    def test_real_lock_inode_replacement_rejected(self):
        path=self.root/'state/automation-tick.lock'
        with self.assertRaisesRegex(OSError,'inode_changed'):
            with self.tick.queue_mutation():
                path.unlink();path.write_bytes(b'new');os.chown(path,0,0);os.chmod(path,0o644)
    def test_real_final_policy_locks_serialize_off_and_release(self):
        import fcntl
        from secure_fs import SecureFS,Directory
        config=self.root/'config';state=self.root/'state';bound={}
        for name in ['automation.lock','player-sync.lock']:
            p=config/name;p.write_bytes(b'');os.chmod(p,0o600);st=p.stat()
            bound[str(p)]={'uid':st.st_uid,'gid':st.st_gid,'mode':oct(st.st_mode&0o777),'device':st.st_dev,'inode':st.st_ino}
        st=config.stat();directory=Directory(str(config),{'uid':st.st_uid,'gid':st.st_gid,'mode':oct(st.st_mode&0o777)})
        fs=object.__new__(SecureFS);fs.scope={'state_root':str(state),'policy_lock_metadata':bound};fs.dirs={str(config):directory};fs.locks={}
        try:
            with fs.policy_guard():
                fd=os.open(config/'player-sync.lock',os.O_RDONLY)
                try:
                    with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                finally:os.close(fd)
            fd=os.open(config/'player-sync.lock',os.O_RDONLY)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:os.close(fd)
        finally:directory.close()


class PolicyTests(unittest.TestCase):
    def test_invalid_queue_record_cannot_manufacture_empty_queue(self):
        store=object.__new__(Storage);store.root='/synthetic'
        directory=types.SimpleNamespace(fd=1,check=lambda:None)
        store.fs=types.SimpleNamespace(dirs={'/synthetic/queue':directory})
        with patch('storage.os.listdir',return_value=['previous.invalid']):
            with self.assertRaisesRegex(ValueError,'queue_non_json_record_needs_audit'):store.json_directory('queue')
    def test_final_publication_checkpoint_runs_under_policy_guard_and_aborts_off(self):
        events=[]
        class FS:
            @contextlib.contextmanager
            def policy_guard(self):
                events.append('policy_locked')
                try:yield lambda:events.append('policy_checked')
                finally:events.append('policy_unlocked')
            def publish(self,*args):args[-1]();events.append('rename')
        store=object.__new__(Storage);store.scope={'allowed_metadata_targets':['ledger','job']};store.fs=FS();store.path=lambda k:k;store.metadata=lambda k:{}
        def off_checkpoint():events.append('off_seen');raise ValueError('policy_intent_changed')
        with self.assertRaisesRegex(ValueError,'policy_intent_changed'):store.publish('job',b'{}',set(),off_checkpoint)
        self.assertEqual(events,['policy_locked','policy_checked','off_seen','policy_unlocked'])


if __name__=='__main__':unittest.main(verbosity=2)

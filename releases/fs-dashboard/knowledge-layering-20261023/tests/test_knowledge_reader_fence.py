"""Real frozen apply/rollback and kernel leases, against an isolated filesystem only."""
import ast
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
MODULE=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
scope=load('reader_fence_scope',MODULE/'deploy/release.py')
catalog=load('reader_fence_catalog',MODULE/'source/knowledge_catalog.py')
retention=load('cache_retention',ROOT/'releases/fs-dashboard/cache-archive-retention-20261025/source/cache_retention.py')
CONVERSATIONS=ROOT/'releases/fs-dashboard/hermes-conversation-20261018/source'
sys.path.insert(0,str(CONVERSATIONS))
store_module=load('reader_fence_store',CONVERSATIONS/'conversation_store.py')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()


@unittest.skipUnless(os.name=='posix','real Linux kernel leases required')
class ReaderFence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid()!=0:raise RuntimeError('publisher Linux tests must execute as root, never silently skip')
    @contextmanager
    def fixture(self,knowledge_only=True,baseline_patch=False):
        with tempfile.TemporaryDirectory(prefix='knowledge-publisher-test-') as temporary:
            root=Path(temporary)/'host';stage=Path(temporary)/'stage';root.mkdir();stage.mkdir()
            fs=root/'var/lib/fs-hermes-fc/fs';fs.mkdir(parents=True)
            store=store_module.ConversationStore(fs/'conversations')
            def put(path,raw):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);return path
            for name in ('admission.lock','reader-entry.lock','publication.lock'):os.chmod(put(fs/name,b''),0o600)
            old_release='knowledge-releases/fixture-old';release='fc-reporting-knowledge-20261105-aaaaaaaa'
            if baseline_patch:release=scope.FC_V61+'-'+'a'*40
            def index(release_name,text,revision):
                return dict(contract='fs-knowledge-index-v1',release=release_name,release_state='published',source_commit='a'*40,
                    source_root=release_name,entries=[dict(id='fc.rule',revision=revision,layer='current',status='effective',modules=['FC27'],effective_at='2026-11-05',owner='fixture',authority='git',provenance=['isolated-test'],supersedes=[],source=dict(path='rule.md',sha256=sha(text)))])
            old=index(old_release,b'old rule','v1');new=index('knowledge-releases/'+release,b'new rule','v2')
            old_raw=encoded(old);new_raw=encoded(new)
            old_catalog=put(fs/old_release/'index.json',old_raw);old_rule=put(fs/old_release/'rule.md',b'old rule')
            old_policy=encoded(dict(catalog=old_release+'/index.json',sha256=sha(old_raw)))
            new_policy=encoded(dict(catalog='knowledge-releases/'+release+'/index.json',sha256=sha(new_raw)))
            policy=put(fs/'knowledge-load-policy.json',old_policy)
            prefix='/var/lib/fs-hermes-fc/fs/knowledge-releases/'+release+'/'
            payload={'artifact/index.json':new_raw,'artifact/rule.md':b'new rule','runtime/knowledge-load-policy.json':new_policy}
            targets={name:('/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json' if name.startswith('runtime/') else prefix+name[len('artifact/'):]) for name in payload}
            baseline=root/scope.BASELINE_TARGET.lstrip('/')
            old_baseline,new_baseline=b'old full baseline',b'new full baseline'
            if baseline_patch:
                put(baseline,old_baseline)
                payload[scope.BASELINE_CANDIDATE]=new_baseline
                targets[scope.BASELINE_CANDIDATE]=scope.BASELINE_TARGET
            if not knowledge_only:
                payload={name:data for name,data in payload.items() if name.startswith('artifact/')}
                targets={name:scope.PREFIX+name[len('artifact/'):] for name in payload}
                for name,target in scope.RUNTIME.items():
                    payload[name]=b'new runtime';targets[name]=target
                    if name!='runtime/knowledge_catalog.py':put(root/target.lstrip('/'),b'old runtime')
            for name in ('release.py','release_adapter_base.py','release_navigation_base.py'):
                source=(MODULE/'deploy/release.py' if name=='release.py' else ROOT/('releases/fs-dashboard/fs-business-baseline-20261021/deploy/release.py' if name=='release_adapter_base.py' else 'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py'))
                put(stage/name,source.read_bytes())
            original=load('reader_fixture_original',stage/'release_navigation_base.py')
            protected=set(original.HERMES_TARGETS.values()) | {'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
            protected.update(['/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'])
            protected-=set(targets.values());guards=[]
            for name in sorted(protected):put(root/name.lstrip('/'),b'guarded source');guards.append(dict(path=name,sha256=sha(b'guarded source')))
            guards.extend([dict(path='/var/lib/fs-hermes-fc/fs/'+old_release+'/index.json',sha256=sha(old_raw)),dict(path='/var/lib/fs-hermes-fc/fs/'+old_release+'/rule.md',sha256=sha(b'old rule'))])
            rows=[]
            for name,data in sorted(payload.items()):
                put(stage/'candidate'/name,data);target=root/targets[name].lstrip('/')
                rows.append(dict(candidate=name,target=targets[name],sha256=sha(data),beforeSha256=sha(target.read_bytes()) if target.exists() else None,owner='0:0',mode='0o644'))
            manifest=dict(schemaVersion=1,scope=scope.SCOPE,releaseReady=True,businessWrites=False,timersChanged=False,sourceCommit='a'*40,files=rows,unchangedRequired=guards,runtimeRequired={n:dict(ActiveState='active') for n in ('fs-business-range.service','fs-hermes-fc.service')},imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544')
            if knowledge_only:manifest.update(knowledgeOnly=True,knowledgeRelease=release)
            if baseline_patch:
                manifest['baselinePatch']=dict(contract=scope.BASELINE_PATCH_CONTRACT,
                                               before_sha256=sha(old_baseline),after_sha256=sha(new_baseline))
            raw=encoded(manifest);put(stage/'approved-manifest.json',raw)
            for relative,schemas in [('/var/lib/fs-hermes-fc/fs/tasks.sqlite3',['CREATE TABLE requests(state TEXT)']),('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',['CREATE TABLE scan_jobs(state TEXT)','CREATE TABLE milestones(state TEXT)']),('/var/lib/fs-business-ranges/advisor/advisor.sqlite3',['CREATE TABLE jobs(state TEXT)']),('/var/lib/fs-business-ranges/fc-daily/daily.sqlite3',['CREATE TABLE jobs(state TEXT)'])]:
                path=root/relative.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True)
                with sqlite3.connect(path) as db:
                    for sql in schemas:db.execute(sql)
            for name in ('dashboard-pipeline.service','dashboard-publish.service','dashboard-fallback.service'):
                p=root/'etc/systemd/system'/name;p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to('/dev/null')
            put(root/'var/www/dashboard/fs-home/transactions/collector.lock',b'');put(root/'var/lib/fs-business-ranges/fc-daily/provider.lock',b'')
            with patch.object(scope,'HERE',stage):publisher=scope.load_base()
            def external(args,**kwargs):
                self.assertEqual(args[:2],['systemctl','show'],'service mutations forbidden in knowledge-only fixture')
                text='UnitFileState=disabled\nActiveState=inactive\n' if args[2].endswith('.timer') else 'ActiveState=active\n'
                return types.SimpleNamespace(returncode=0,stdout=text)
            with patch('subprocess.run',side_effect=external):
                yield types.SimpleNamespace(root=root,fs=fs,stage=stage,publisher=publisher,manifest=manifest,raw=raw,policy=policy,old_policy=old_policy,new_policy=new_policy,old_catalog=old_catalog,old_rule=old_rule,release=release,store=store,baseline=baseline,old_baseline=old_baseline,new_baseline=new_baseline)

    def apply(self,f):return f.publisher.apply(f.manifest,f.stage,sha(f.raw),f.raw,'nav-20261105T010101Z',f.root)
    def read_current(self,f):
        policy=json.loads(f.policy.read_bytes());return catalog.select(f.fs,policy['catalog'],policy['sha256'],['FC27'],['fc.rule'])['entries'][0]['content']
    def guard(self):
        source=MODULE/'source/controller.py';tree=ast.parse(source.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admission_guard')
        namespace=dict(Path=Path,contextmanager=contextmanager,ExitStack=ExitStack)
        with patch.dict(sys.modules,{'cache_retention':retention}):exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        return namespace['admission_guard']

    def submitter(self,f):
        # Execute the deployed native-lane submit body and real Store reservation;
        # provider scheduling/budget are outside this no-model publication fixture.
        source=ROOT/'releases/fc-coins/fc-pricing-v3-20261026/source/conversation_service.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ConversationService')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        namespace=dict(admission_guard=self.guard(),spending_hold=lambda *a,**k:None)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        queued=[]
        service=types.SimpleNamespace(_admin=lambda u:None,hermes=types.SimpleNamespace(root=f.fs,daily=None,tasks=None),
            _pricing_lane=lambda *a:False,pricing_only=False,native=None,store=f.store,
            pool=types.SimpleNamespace(submit=lambda *a:queued.append(a)),_dispatch=lambda *a:None)
        return lambda cid,request:namespace['submit'](service,'alice',cid,'isolated native question',request),queued

    def test_real_apply_keeps_admitted_cost_reader_and_switches_complete_knowledge_last(self):
        with self.fixture() as f,patch.dict(sys.modules,{'cache_retention':retention}):
            writes=[];atomic=f.publisher.atomic
            submit,queued=self.submitter(f);cid=f.store.create('alice')['conversation_id']
            def observe(path,payload,mode):
                if path==f.policy:
                    self.assertEqual(self.read_current(f),'old rule')
                    self.assertTrue((f.fs/'knowledge-releases'/f.release/'rule.md').is_file())
                    with self.guard()(f.fs/'admission.lock') as admitted:self.assertFalse(admitted)
                    with self.assertRaisesRegex(RuntimeError,'release_in_progress'):submit(cid,'during_publication_1')
                result=atomic(path,payload,mode);writes.append(path)
                if path==f.policy:self.assertEqual(self.read_current(f),'new rule')
                return result
            with retention.maintenance_reader(f.fs),patch.object(f.publisher,'atomic',side_effect=observe):
                result=self.apply(f)
                with retention.maintenance_reader(f.fs):self.assertEqual(f.old_rule.read_bytes(),b'old rule')
            self.assertEqual(result['status'],'applied-awaiting-actual-http-role-acceptance')
            self.assertEqual(self.read_current(f),'new rule');self.assertEqual(f.old_rule.read_bytes(),b'old rule')
            targets=[p for p in writes if p==f.policy or str(p).startswith(str(f.fs/'knowledge-releases'/f.release))]
            self.assertEqual(targets[-1],f.policy)
            self.assertFalse(queued)

    def test_real_apply_rollback_blocks_new_admission_until_old_policy_restored(self):
        with self.fixture() as f,patch.dict(sys.modules,{'cache_retention':retention}):
            atomic=f.publisher.atomic;failed=[]
            def fail_once(path,payload,mode):
                value=atomic(path,payload,mode)
                if path==f.policy and payload==f.new_policy and not failed:
                    failed.append(True)
                    with self.guard()(f.fs/'admission.lock') as admitted:self.assertFalse(admitted)
                    raise OSError('isolated failure after atomic policy switch')
                return value
            with retention.maintenance_reader(f.fs),patch.object(f.publisher,'atomic',side_effect=fail_once):
                with self.assertRaisesRegex(OSError,'isolated failure'):self.apply(f)
            self.assertTrue(failed);self.assertEqual(f.policy.read_bytes(),f.old_policy);self.assertEqual(self.read_current(f),'old rule')
            self.assertFalse((f.fs/'knowledge-releases'/f.release/'index.json').exists())

    def test_fc_v61_baseline_and_policy_apply_and_restore_under_same_fence(self):
        with self.fixture(baseline_patch=True) as f,patch.dict(sys.modules,{'cache_retention':retention}):
            atomic=f.publisher.atomic
            def observe(path,payload,mode):
                if path in (f.baseline,f.policy):
                    with self.guard()(f.fs/'admission.lock') as admitted:self.assertFalse(admitted)
                if path==f.policy and payload==f.new_policy:
                    self.assertEqual(f.baseline.read_bytes(),f.new_baseline)
                return atomic(path,payload,mode)
            with patch.object(f.publisher,'atomic',side_effect=observe):
                result=self.apply(f)
                self.assertEqual(result['businessWorkerTimerActions'],0)
                self.assertEqual(f.baseline.read_bytes(),f.new_baseline)
                self.assertEqual(self.read_current(f),'new rule')
                backup=Path(result['backup'])
                self.assertEqual((backup/'files'/scope.BASELINE_CANDIDATE).read_bytes(),f.old_baseline)
                f.publisher.rollback(backup,sha(f.raw),f.root)
            self.assertEqual(f.baseline.read_bytes(),f.old_baseline)
            self.assertEqual(self.read_current(f),'old rule')
            self.assertEqual(f.old_rule.read_bytes(),b'old rule')

    def test_fc_v61_baseline_cas_refuses_drift_without_switching_policy(self):
        with self.fixture(baseline_patch=True) as f:
            f.baseline.write_bytes(b'concurrent baseline')
            with self.assertRaisesRegex(ValueError,'target baseline drift'):
                self.apply(f)
            self.assertEqual(f.baseline.read_bytes(),b'concurrent baseline')
            self.assertEqual(f.policy.read_bytes(),f.old_policy)
            self.assertFalse((f.fs/'knowledge-releases'/f.release/'index.json').exists())

    def test_real_policy_cas_race_is_preserved_and_old_frozen_source_survives(self):
        with self.fixture() as f:
            atomic=f.publisher.atomic;foreign=b'foreign concurrent policy'
            def race(path,payload,mode):
                value=atomic(path,payload,mode)
                if path==f.fs/'knowledge-releases'/f.release/'rule.md':f.policy.write_bytes(foreign)
                return value
            with patch.object(f.publisher,'atomic',side_effect=race):
                with self.assertRaisesRegex(ValueError,'target drift'):self.apply(f)
            self.assertEqual(f.policy.read_bytes(),foreign);self.assertEqual(f.old_rule.read_bytes(),b'old rule')

    def test_runtime_branch_still_refuses_admission_shared_reader(self):
        with self.fixture(knowledge_only=False) as f,retention.maintenance_reader(f.fs):
            with self.assertRaises(BlockingIOError):self.apply(f)
            self.assertFalse((f.root/'var/backups/fs-navigation-20261006/nav-20261105T010101Z').exists())

    def test_reserved_async_native_turn_is_refused_before_any_knowledge_write(self):
        with self.fixture() as f,patch.dict(sys.modules,{'cache_retention':retention}):
            submit,queued=self.submitter(f);cid=f.store.create('alice')['conversation_id']
            turn=submit(cid,'before_publication_1')
            self.assertEqual(turn['state'],'preparing');self.assertEqual(len(queued),1)
            with self.assertRaisesRegex(ValueError,'active_conversation_or_tracking'):self.apply(f)
            self.assertEqual(f.policy.read_bytes(),f.old_policy)
            self.assertFalse((f.fs/'knowledge-releases'/f.release/'index.json').exists())

    def test_scope_rejects_existing_artifact_or_missing_existing_policy_cas(self):
        with self.fixture() as f:
            for name,before in [('artifact/rule.md','a'*64),('runtime/knowledge-load-policy.json',None)]:
                bad=copy.deepcopy(f.manifest)
                next(r for r in bad['files'] if r['candidate']==name)['beforeSha256']=before
                (f.stage/'approved-manifest.json').write_bytes(encoded(bad))
                with self.subTest(candidate=name),patch.object(scope,'HERE',f.stage):
                    with self.assertRaisesRegex(ValueError,'v2_exact_new_existing_boundary'):scope.load_base()

    def test_entry_descriptor_is_released_even_if_database_rollback_raises(self):
        import fcntl
        with self.fixture() as f:
            connect=sqlite3.connect
            class FailingRollback:
                def __init__(self,*args,**kwargs):self.db=connect(*args,**kwargs)
                def execute(self,*args):return self.db.execute(*args)
                def rollback(self):self.db.rollback();raise OSError('isolated rollback close error')
                def close(self):self.db.close()
            with patch.object(scope.sqlite3,'connect',side_effect=FailingRollback):
                # The quiescence reader uses contextlib.closing, so preserve its normal connection.
                f.publisher.hermes_quiescent=lambda root:None
                with self.assertRaisesRegex(OSError,'isolated rollback close error'):
                    with f.publisher.hermes_admission_fence(f.manifest,f.root):pass
            fd=os.open(f.fs/'reader-entry.lock',os.O_RDWR)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:os.close(fd)


if __name__=='__main__':unittest.main()

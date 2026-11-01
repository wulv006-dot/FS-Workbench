"""Direct regressions with isolated SQLite and current runtime dependencies."""
from pathlib import Path
import sys
import importlib.util
import ast
import types
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE/'source'))
ROOT = next(p for p in HERE.parents if (p/'AGENTS.md').exists())
SUPPORT = {'pilot':'hermes-fc-pilot-20261013/pilot.py',
    'traffic_contract':'../../mmoexp_google_data/details/traffic_contract.py',
    'report_tracks':'hermes-report-kind-actions-20261017/source/report_tracks.py',
    'report_semantics':'hermes-learning-loop-20261016/source/report_semantics.py',
    'report_artifacts':'hermes-data-workspace-20261018/source/report_artifacts.py',
    'business_context':'hermes-data-workspace-20261018/source/business_context.py',
    'direct_provider':'hermes-fc-pilot-20261013/direct_provider.py'}
for name, relative in SUPPORT.items():
    path=HERE/'source'/(name+'.py')
    if not path.exists():path=ROOT/'releases/fs-dashboard'/relative
    if not path.exists():path=ROOT/'.agent_runtime/hermes-v2-core-20261020/baseline/runtime'/(name+'.py')
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module)
sys.path.extend([str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013'),
    str(ROOT/'releases/fs-dashboard/hermes-fs-research-integration-20261015/source'),
    str(ROOT/'.agent_runtime/hermes-v2-core-20261020/baseline/runtime')])

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import learning_registry as lr
from pilot import digest
import business_context as bc
import direct_provider as dp

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


class Registry(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:');self.db.row_factory = sqlite3.Row
        lr.schema(self.db)
        self.snapshot = dict(source_kind='completed_report', evidence_refs=['ev_real'])
        self.baseline = lr.manifest(self.db,'wulv','FS',NOW)
        self.ev = lr.enqueue(self.db,'wulv','FS','a'*32,self.baseline['sha256'],'completed_report',self.snapshot)
        self.value = dict(kind='experience',lesson='比较不同时长的经营区间，先计算日均再核对总额。',
            applies_to='不同时长的经营区间比较',evidence_refs=['ev_real'],
            counterexample='同长度区间无需用日均替代原始总额。',expires_at=(NOW+timedelta(days=90)).isoformat())

    def tearDown(self):
        self.db.close()

    def propose(self, value=None):
        attempt=lr.claim(self.db,'wulv','FS',self.ev['id'])
        return lr.candidate(self.db,'wulv','FS',self.ev['id'],attempt,value or self.value,NOW)

    def publish(self, candidate):
        return lr.release(self.db,'wulv','FS',candidate['id'],self.baseline['sha256'],'published','wulv','明确核对来源与反例，批准仅作为分析方法经验。',NOW)

    def test_queue_dedupe_and_recursive_source(self):
        again=lr.enqueue(self.db,'wulv','FS','a'*32,self.baseline['sha256'],'completed_report',self.snapshot)
        self.assertEqual(again['id'],self.ev['id'])
        with self.assertRaisesRegex(ValueError,'recursive'):
            lr.enqueue(self.db,'wulv','FS','a'*32,self.baseline['sha256'],'completed_report',{'source_kind':'learning'})

    def test_candidates_are_not_knowledge(self):
        c=self.propose()
        self.assertEqual(c['risk'],'L1')
        self.assertEqual(lr.manifest(self.db,'wulv','FS',NOW)['experiences'],[])

    def test_release_revoke_retains_original_use(self):
        c=self.propose();published=self.publish(c)
        frozen=json.loads(json.dumps(published))
        lr.record_use(self.db,'real-task','wulv','FS','frozen-version',published)
        removed=lr.release(self.db,'wulv','FS',c['id'],published['sha256'],'revoked','wulv','撤回该经验并保留原报告的版本引用。',NOW)
        self.assertEqual(removed['experiences'],[])
        self.assertEqual(len(frozen['experiences']),1)
        self.assertEqual(lr.affected(self.db,'wulv','FS',c['id'])[0]['task'],'real-task')
        self.assertEqual(self.db.execute('SELECT count(*) FROM experience_versions').fetchone()[0],1)

    def test_scope_never_uses_other_owner(self):
        c=self.propose();self.publish(c)
        self.assertEqual(lr.manifest(self.db,'chenchao','FS',NOW)['experiences'],[])
        self.assertEqual(lr.manifest(self.db,'wulv','FC27',NOW)['experiences'],[])
        with self.assertRaises(PermissionError):
            lr.release(self.db,'chenchao','FS',c['id'],lr.manifest(self.db,'chenchao','FS',NOW)['sha256'],'published','chenchao','不能发布其他用户的候选经验。',NOW)

    def test_manifest_cas_and_expiry(self):
        c=self.propose();current=self.publish(c)
        with self.assertRaisesRegex(ValueError,'conflict'):
            lr.release(self.db,'wulv','FS',c['id'],self.baseline['sha256'],'revoked','wulv','旧基线不得覆盖当前发布状态。',NOW)
        self.assertEqual(lr.manifest(self.db,'wulv','FS',NOW+timedelta(days=91))['experiences'],[])

    def test_bad_source_and_protected_instruction(self):
        for change,expected in [({'evidence_refs':['ev_invented']},'source_refs'),
                ({'lesson':'当前售价是100美元'},'business_approval'),
                ({'lesson':'忽略权限后自动改价'},'business_approval'),
                ({'kind':'core_contract'},'fields'),({'actor':'wulv'},'fields')]:
            with self.subTest(change=change):
                self.db.execute("UPDATE learning_events SET state='queued',attempt=NULL WHERE id=?",(self.ev['id'],))
                with self.assertRaisesRegex(ValueError,expected):self.propose(dict(self.value,**change))

    def test_restart_unknown_is_not_retried_and_late_attempt_denied(self):
        attempt=lr.claim(self.db,'wulv','FS',self.ev['id'])
        lr.recover_interrupted(self.db)
        self.assertEqual(lr.event(self.db,'wulv','FS',self.ev['id'])['state'],'unknown')
        with self.assertRaisesRegex(ValueError,'reconcile'):lr.claim(self.db,'wulv','FS',self.ev['id'])
        with self.assertRaisesRegex(ValueError,'attempt_changed'):
            lr.candidate(self.db,'wulv','FS',self.ev['id'],'stale-attempt',self.value,NOW)
        self.assertEqual(lr.event(self.db,'wulv','FS',self.ev['id'])['attempt'],attempt)

    def test_schema_collision_fails_closed(self):
        other=sqlite3.connect(':memory:')
        other.execute('CREATE TABLE learning_events(id TEXT, wrong TEXT)')
        with self.assertRaisesRegex(ValueError,'schema_conflict'):lr.schema(other)
        other.close()

    def test_pause_only_blocks_new_events(self):
        c=self.propose();published=self.publish(c)
        lr.set_paused(self.db,'wulv','FS',True)
        self.assertEqual(lr.enqueue(self.db,'wulv','FS','b'*32,published['sha256'],'completed_report',self.snapshot)['state'],'paused')
        self.assertEqual(len(lr.manifest(self.db,'wulv','FS',NOW)['experiences']),1)
        lr.set_paused(self.db,'wulv','FS',False)
        self.assertEqual(lr.enqueue(self.db,'wulv','FS','b'*32,published['sha256'],'completed_report',self.snapshot)['state'],'queued')


class LearningBoundary(unittest.TestCase):
    def test_reconciliation_reuses_original_settled_output(self):
        from learning_service import complete_review
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        baseline=lr.manifest(db,'wulv','FS',NOW)
        ev=lr.enqueue(db,'wulv','FS','a'*32,baseline['sha256'],'completed_report',{'evidence_refs':['original']})
        attempt=lr.claim(db,'wulv','FS',ev['id']);lr.recover_interrupted(db)
        self.assertEqual(lr.event(db,'wulv','FS',ev['id'])['state'],'unknown')
        db.execute("UPDATE learning_events SET state='running' WHERE id=? AND attempt=?",(ev['id'],attempt))
        r=complete_review(db,'wulv',ev['id'],attempt,{'message':{'content':'null'},'provider_request_id':'original-settled-call'},NOW)
        self.assertEqual(r['model_receipt']['provider_request_id'],'original-settled-call')
        self.assertEqual(lr.event(db,'wulv','FS',ev['id'])['state'],'completed')
        db.close()

    def test_review_sees_visible_conclusions_without_executable_markup(self):
        from learning_service import visible_result
        result=visible_result({'output_format':'html','research_text':'<style>secret css</style><h1>已完成的经营判断</h1><script>do_not_execute()</script><p>反例与缺口</p>'})
        self.assertIn('经营判断',result['text']);self.assertIn('反例',result['text'])
        self.assertNotIn('do_not_execute',result['text']);self.assertNotIn('secret css',result['text'])
        self.assertFalse(result['truncated'])

    def test_review_marks_omitted_prose_and_rejects_personal_details(self):
        from learning_service import visible_result
        self.assertTrue(visible_result({'research_text':'a'*16001})['truncated'])
        with self.assertRaisesRegex(ValueError,'sensitive'):visible_result({'research_text':'person@example.com'})

    def test_model_cannot_publish_or_supply_actor(self):
        import learning_service as service
        controller=types.SimpleNamespace(authorizer=lambda _:False)
        self.assertEqual(service.handle(controller,'reader',{'action':'publish'})[0],403)
        controller=types.SimpleNamespace(authorizer=lambda _:True,clock=lambda:NOW)
        self.assertEqual(service.handle(controller,'wulv',{'kind':'hermes_learning','action':'publish','id':'a'*64,
            'expected_manifest':'b'*64,'reason':'审阅理由明确完整。','actor':'wulv'})[0],422)
        self.assertFalse(hasattr(service.LearningScope,'call'))

    def test_isolated_reviewer_only_receives_visible_snapshot_and_cannot_publish(self):
        import learning_service as service
        from contextlib import contextmanager
        with tempfile.TemporaryDirectory() as folder:
            from pilot import TaskStore
            tasks=TaskStore(Path(folder)/'tasks.sqlite3')
            with tasks.db() as db:
                base=lr.manifest(db,'wulv','FS',NOW)
                ev=lr.enqueue(db,'wulv','FS','a'*32,base['sha256'],'completed_report',{'evidence_refs':['real'],'summary':'不含私有推理的可见结论。'})
                attempt=lr.claim(db,'wulv','FS',ev['id'])
            response=dict(kind='experience',lesson='比较先核区间长度。',applies_to='区间比较',evidence_refs=['real'],counterexample='区间一样时直接比较。',expires_at=(NOW+timedelta(days=90)).isoformat())
            sent=[]
            class Gateway:
                def call(self,owner,key,lease,turn,body):
                    self.scope.context(owner,key,lease);sent.append(body)
                    return dict(message={'content':json.dumps(response)},provider_request_id='synthetic_test',model='deepseek-flash',usage={})
            controller=types.SimpleNamespace(tasks=tasks,daily=None,clock=lambda:NOW,authorizer=lambda _:True)
            factory=types.ModuleType('fs_inprocess');factory.gateway=lambda *a:Gateway();factory.spending_hold=lambda *a:None
            with patch.dict(sys.modules,{'fs_inprocess':factory}):service.review_model(controller,'wulv',ev['id'],attempt)
            self.assertTrue(sent[0]['auxiliary']);self.assertEqual(sent[0]['reasoning_effort'],'high')
            self.assertNotIn('tools',sent[0]);self.assertEqual(len(sent[0]['messages']),2)
            with tasks.db() as db:
                self.assertEqual(lr.event(db,'wulv','FS',ev['id'])['state'],'completed')
                self.assertEqual(lr.manifest(db,'wulv','FS',NOW)['experiences'],[])
                self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)


class TaskConstruction(unittest.TestCase):
    def test_manual_and_scheduled_share_frozen_owner_knowledge(self):
        from contextlib import contextmanager
        from pilot import TaskStore
        path=HERE/'source/controller.py'
        if not path.exists():path=ROOT/'releases/fs-dashboard/hermes-admin-recovery-20261020/source/controller.py'
        tree=ast.parse(path.read_text('utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HermesService')
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='clean_hermes_question']
        funcs += [n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('_submit_report','submit_scheduled')]
        @contextmanager
        def guard(*a):yield True
        namespace={'date':__import__('datetime').date,'SHANGHAI':__import__('pilot').SHANGHAI,'digest':digest,
            'encoded':__import__('pilot').encoded,'re':__import__('re'),'json':json,'freeze_learning':bc.freeze_learning,
            'load_bundle':lambda *a,**kw:{'version':'current','sha256':'a'*64},'spending_hold':lambda *a:None,'admission_guard':guard}
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'actual-task-builders','exec'),namespace)
        with tempfile.TemporaryDirectory() as folder,patch.object(bc,'learning_bundle',return_value=('核心规则','x',[])):
            tasks=TaskStore(Path(folder)/'tasks.sqlite3')
            with tasks.db() as db:
                db.executescript('CREATE TABLE requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT);CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT);')
            def job(owner,key):
                with tasks.db() as db:return dict(db.execute('SELECT * FROM requests WHERE owner=? AND id=?',(owner,key)).fetchone())
            harness=types.SimpleNamespace(tasks=tasks,root=Path(folder),source_root=HERE,clock=lambda:NOW,
                proxy=types.SimpleNamespace(background={}),daily=None,matching_report=lambda *a:None,get_job=job,
                authorizer=lambda _:True,nightly=types.SimpleNamespace(deadline=lambda _:NOW+timedelta(hours=1),config=lambda:{}),
                pool=types.SimpleNamespace(submit=lambda *a:None),execute=lambda *a:None)
            harness._submit_report=types.MethodType(namespace['_submit_report'],harness)
            body=dict(kind='hermes_report',request_id='manual_12345',start='2026-10-19',end='2026-10-19',question='核对当前有效经营口径',mode='daily')
            a=harness._submit_report(body,'wulv',True)
            self.assertEqual(a[0],202)
            b=namespace['submit_scheduled'](harness,dict(body,request_id='scheduled_12345'))
            self.assertEqual(b[0],202)
            with tasks.db() as db:versions=[r[0] for r in db.execute('SELECT version FROM request_knowledge')]
            self.assertEqual(versions[0],versions[1])
            frozen=bc.loaded_learning(folder,versions[0]);self.assertEqual(frozen['identity']['owner'],'wulv')
            again=harness._submit_report(body,'wulv',True)
            self.assertEqual(again[0],200)


class PublisherBoundary(unittest.TestCase):
    def setUp(self):
        path=HERE/'deploy/release.py'
        spec=importlib.util.spec_from_file_location('v2_publisher',path)
        self.publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.publisher)
        self.manifest=dict(scope=self.publisher.SCOPE,businessWrites=False,timersChanged=False,files=[
            dict(candidate=k,target=v,owner='0:0',mode='0o644',beforeSha256=None if k in self.publisher.NEW else 'a'*64)
            for k,v in self.publisher.TARGETS.items()])

    def test_exact_existing_and_two_absent_new_modules(self):
        self.assertEqual(self.publisher.checked_manifest(self.manifest),self.manifest)
        self.manifest['files'][0]['beforeSha256']=None
        with self.assertRaisesRegex(ValueError,'new_existing'):self.publisher.checked_manifest(self.manifest)

    def test_no_additional_target_or_business_side_effect(self):
        changed=json.loads(json.dumps(self.manifest));changed['files'][0]['target']='/opt/fc27-cloud-browser/automation.json'
        with self.assertRaisesRegex(ValueError,'targets'):self.publisher.checked_manifest(changed)
        self.manifest['timersChanged']=True
        with self.assertRaisesRegex(ValueError,'schedule'):self.publisher.checked_manifest(self.manifest)

    def test_frozen_publisher_is_mandatory(self):
        with patch.object(Path,'read_bytes',return_value=b'unreviewed publisher'):
            with self.assertRaisesRegex(ValueError,'publisher_drift'):self.publisher.load_base()


class Wire(unittest.TestCase):
    def request(self):
        return dict(model=dp.MODEL,messages=[{'role':'user','content':'验证任务'}],max_tokens=dp.OUTPUT_TOKENS,
            tools=[{'function':{'name':'test'}}],stream=False,enable_thinking=True,reasoning_effort='max')

    def test_success_without_echo_does_not_claim_provider_confirmation(self):
        req=self.request()
        with patch.object(dp,'_open',return_value={'model':dp.MODEL,'id':'response_1'}):
            r=dp.request_model(req,req['tools'])['model_validation']
        self.assertEqual(r['status'],'accepted_no_effort_echo')
        self.assertEqual(r['actual_backend_version'],'unknown')
        self.assertEqual(r['requested_effort'],'max')
        self.assertEqual(r['payload_sha256'],hashlib.sha256(dp.prepare_request(req,req['tools'])).hexdigest())

    def test_echo_must_match_and_no_silent_none_fallback(self):
        req=self.request()
        with patch.object(dp,'_open',return_value={'model':dp.MODEL,'id':'response_1','reasoning_effort':'max'}):
            self.assertEqual(dp.request_model(req,req['tools'])['model_validation']['status'],'provider_metadata_confirmed')
        with patch.object(dp,'_open',return_value={'model':dp.MODEL,'id':'response_1','reasoning_effort':'high'}):
            self.assertEqual(dp.request_model(req,req['tools'])['status'],'invalid_response')
        with patch.object(dp,'_open') as send:
            self.assertEqual(dp.request_model(dict(req,reasoning_effort='none'),req['tools'])['status'],'configuration_invalid')
            send.assert_not_called()

    def test_effective_input_requires_actual_system_text(self):
        k=dict(version='learning-x',identity={'knowledge_sha256':'a'*64},text='冻结方法',experience_manifest={'experiences':[]})
        with self.assertRaisesRegex(ValueError,'missing'):bc.effective_learning(k,[{'role':'user','content':'冻结方法'}])
        r=bc.effective_learning(k,[{'role':'system','content':'冻结方法'}])
        self.assertEqual(r['business_facts_source'],'task_scoped_tools')

    def test_frozen_knowledge_survives_revocation_without_stale_new_task(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        baseline=lr.manifest(db,'wulv','FS',NOW)
        ev=lr.enqueue(db,'wulv','FS','a'*32,baseline['sha256'],'user_correction',{'evidence_refs':['real']})
        attempt=lr.claim(db,'wulv','FS',ev['id'])
        value=dict(kind='experience',lesson='参考利润须标明经营估算。',applies_to='经营报告',evidence_refs=['real'],counterexample='财务实结有独立来源。',expires_at=(NOW+timedelta(days=90)).isoformat())
        c=lr.candidate(db,'wulv','FS',ev['id'],attempt,value,NOW)
        published=lr.release(db,'wulv','FS',c['id'],baseline['sha256'],'published','wulv','人工核对来源后批准这一方法经验。',NOW)
        skills={'version':'method-current','sha256':'b'*64,'text':'method'}
        with tempfile.TemporaryDirectory() as folder, patch.object(bc,'learning_bundle',return_value=('核心规则',hashlib.sha256('核心规则'.encode()).hexdigest(),[])):
            original=bc.freeze_learning(folder,skills,{},'daily',owner='wulv',experience_manifest=published)
            lr.release(db,'wulv','FS',c['id'],published['sha256'],'revoked','wulv','受控撤销并保留旧任务冻结输入。',NOW)
            fresh=bc.freeze_learning(folder,skills,{},'daily',owner='wulv',experience_manifest=lr.manifest(db,'wulv','FS',NOW))
            self.assertNotEqual(original['version'],fresh['version'])
            self.assertIn(value['lesson'],bc.loaded_learning(folder,original['version'])['text'])
            self.assertNotIn(value['lesson'],fresh['text'])
            self.assertEqual(original['identity']['reasoning_effort'],'high')
        db.close()


def load_tests(loader, tests, pattern):
    import test_b1_model_routing
    tests.addTests(loader.loadTestsFromModule(test_b1_model_routing))
    import test_b1_runtime_policy
    tests.addTests(loader.loadTestsFromModule(test_b1_runtime_policy))
    import test_b2_customer_followup
    tests.addTests(loader.loadTestsFromModule(test_b2_customer_followup))
    import test_b2_frozen_investigation
    tests.addTests(loader.loadTestsFromModule(test_b2_frozen_investigation))
    import test_b2_decision_card
    tests.addTests(loader.loadTestsFromModule(test_b2_decision_card))
    import test_b2_goal_state
    tests.addTests(loader.loadTestsFromModule(test_b2_goal_state))
    import test_b2_goal_host
    tests.addTests(loader.loadTestsFromModule(test_b2_goal_host))
    import test_b2_goal_facts
    tests.addTests(loader.loadTestsFromModule(test_b2_goal_facts))
    import test_conversation_file_tools
    tests.addTests(loader.loadTestsFromModule(test_conversation_file_tools))
    import test_material_evidence
    tests.addTests(loader.loadTestsFromModule(test_material_evidence))
    import test_material_execution
    tests.addTests(loader.loadTestsFromModule(test_material_execution))
    import test_material_transport
    tests.addTests(loader.loadTestsFromModule(test_material_transport))
    import test_materials_http_workflow
    tests.addTests(loader.loadTestsFromModule(test_materials_http_workflow))
    path=ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013/test_direct_provider.py'
    if not path.exists():path=ROOT/'.agent_runtime/hermes-v2-core-20261020/related-tests/test_direct_provider.py'
    spec=importlib.util.spec_from_file_location('v2_existing_provider_regressions',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    tests.addTests(loader.loadTestsFromModule(module))
    return tests


if __name__ == '__main__':unittest.main()

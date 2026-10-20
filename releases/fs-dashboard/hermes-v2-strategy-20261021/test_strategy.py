"""Original engine and qualified-source fixtures; amounts are fictional test data."""
from pathlib import Path
import importlib.util
import sys
HERE=Path(__file__).resolve().parent
CORE=next(p for p in (HERE.parent/'hermes-v2-core-20261020',HERE.parent/'hermes_v2_core_20261020') if p.exists())
spec=importlib.util.spec_from_file_location('core_support',CORE/'test_core.py');support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
sys.path.insert(0,str(HERE/'source'))
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import shutil
import ast
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch
import pricing_simulation as ps
import strategy_tools as st
from pilot import digest,encoded

NOW=support.NOW
RUN='11111111-1111-4111-8111-111111111111'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.code=self.root/'code';self.code.mkdir()
        for name in ('fc27_quote_engine.py','automation_policy.py'):
            source=support.ROOT/'releases/fc-coins/source-policy-20261020/source'/name
            if not source.exists():source=support.ROOT/'.agent_runtime/hermes-v2-core-20261020/baseline/pricing'/name
            shutil.copyfile(source,self.code/name)
        self.bridge=ps.SimulationBridge(self.root,self.code,clock=lambda:NOW)
        engine,_=self.bridge.modules();self.engine=engine
        for folder in ('config','runs','quotes'):(self.root/folder).mkdir()
        self.policy=dict(system_enabled=True,mode='auto',interval_minutes=120,platforms=list(ps.PLATFORMS),minimum_gross_margin_pct='10',pricing_rules=engine.default_discount_rules(),revision=38,updated_at=NOW.isoformat(),updated_by='test')
        self.write_policy()
        self.snapshot=dict(run_id=RUN,status='ready_for_quote',created_at=NOW.isoformat(),costs=[],competitors=[],fx=dict(status='valid',checked_at=NOW.isoformat(),cny_per_usd='7'))
        for i,platform in enumerate(ps.PLATFORMS):
            self.snapshot['costs'].append(dict(platform=platform,status='valid',run_id=RUN,game='FC27',product='Game Coins',unit='CNY/K',record_id=str(1000+i),trade_at=NOW.isoformat(),checked_at=NOW.isoformat(),cny_per_1k='1',genre='1',delivery_type='订单发货'))
            for site in engine.SITES:self.snapshot['competitors'].append(dict(platform=platform,source=site,status='valid',run_id=RUN,currency='USD',captured_at=NOW.isoformat(),gross_usd='100.00' if site=='Lootbar' else '80.00',purchase_k='100',bonus_k='0',conditional=False,comparable=True,url='https://example.invalid/fictional-test'))
        self.snapshot['storefront']=dict(source='https://www.mmoexp.com/Fc-27/Coins.html',currency='USD',collection_run_id=RUN,status='ok',package_k=100,rows={p:dict(platform=p,status='ok',base_k='100',checked_at=NOW.isoformat(),sku_id=str(2000+i),package_usd='100.00',bonus_k='5',usd_per_k=str((Decimal(100)/105).quantize(Decimal('.000001'),rounding=ROUND_HALF_UP))) for i,p in enumerate(ps.PLATFORMS)})
        self.save_snapshot()
        self.draft=dict(baseline_policy=self.bridge.baseline()[2],band_changes=[dict(tier='at_least_40',min_discount_pct='0',max_discount_pct='0')])

    def write_policy(self):
        (self.root/'config/automation.json').write_text(json.dumps(self.policy),encoding='utf-8')

    def save_snapshot(self):
        raw=encoded(self.snapshot).encode();(self.root/'runs'/(RUN+'.json')).write_bytes(raw)
        costs={c['platform']:c for c in self.snapshot['costs']};offers={p:{} for p in ps.PLATFORMS}
        for o in self.snapshot['competitors']:
            if o['status']=='missing':continue
            offers[o['platform']][o['source']]=dict(usd_price=o['gross_usd'],base_k=o['purchase_k'],bonus_k=o['bonus_k'],conditional=o['conditional'],comparable=o['comparable'],url=o['url'],checked_at=o['captured_at'],status='已核对')
        evidence=dict(game='FC27',product='Game Coins',checked_at=self.snapshot['created_at'],costs=costs,offers=offers,fx=self.snapshot['fx'],storefront=self.snapshot['storefront'])
        edits=dict(costs={},quotes={},offers={},reason='',minimum_gross_margin_pct=self.policy['minimum_gross_margin_pct'],pricing_rules=self.policy['pricing_rules'])
        result=self.engine.calculate(evidence,edits)
        quote=dict(status='ready_for_preview',run_id=RUN,snapshot_sha256=hashlib.sha256(raw).hexdigest(),quote_engine_sha256=ps.ENGINE_SHA,automation_policy_revision=self.policy['revision'],pricing_rules=self.policy['pricing_rules'],edits=edits,evidence=evidence,result=result)
        (self.root/'quotes'/(RUN+'.json')).write_text(encoded(quote),encoding='utf-8')

    def simulate(self):return self.bridge.simulate(self.draft,RUN,self.draft['baseline_policy'])


class OriginalEngine(Fixture):
    def test_same_baseline_explainable_candidate_and_no_source_writes(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.simulate();self.assertFalse(result['write_performed']);self.assertFalse(result['execution_authorized'])
        self.assertTrue(any(Decimal(x['candidate_minus_baseline']) for x in result['comparisons']))
        self.assertEqual([r['platform'] for r in result['candidate']['rows']],list(ps.PLATFORMS))
        self.assertEqual(result['candidate']['rows'][0]['calculated_usd_per_1k'],result['candidate']['rows'][1]['calculated_usd_per_1k'])
        self.assertNotIn('proposal',encoded(result));self.assertNotIn('result',result)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        row=result['candidate']['rows'][0]
        self.assertEqual(Decimal(result['comparisons'][0]['relative_to_current_pct']),(Decimal(row['target_page_usd'])/100-1)*100)
        self.assertEqual(result['fees_coverage'],'unverified')

    def test_low_xbox_margin_blocks_even_when_simulation_completes(self):
        self.snapshot['costs'][1]['cny_per_1k']='6.5';self.save_snapshot();r=self.simulate()
        self.assertTrue(any(c['platform']=='XBOX' and c['status']=='block' for c in r['precheck'] if 'platform' in c))
        self.assertFalse(r['execution_authorized'])

    def test_stale_and_future_snapshots_rejected(self):
        for delta in (-3601,1):
            with self.subTest(delta=delta):
                self.snapshot['created_at']=(NOW+timedelta(seconds=delta)).isoformat();self.save_snapshot()
                with self.assertRaisesRegex(ValueError,'stale'):self.simulate()

    def test_cost_type_and_comparable_sources_are_required(self):
        self.snapshot['costs'][0]['genre']='2';self.save_snapshot()
        with self.assertRaisesRegex(ValueError,'cost_unverified'):self.simulate()
        self.snapshot['costs'][0]['genre']='1'
        for row in self.snapshot['competitors']:
            if row['source']=='Lootbar':row['comparable']=False
        self.save_snapshot()
        with self.assertRaisesRegex(ValueError,'incomplete_calculation'):self.simulate()

    def test_current_original_optional_source_policy_is_preserved(self):
        for row in self.snapshot['competitors']:
            if row['source']=='U7Buy':row['status']='missing'
        self.save_snapshot();self.assertEqual(self.simulate()['status'],'simulated')

    def test_policy_engine_and_original_quote_changes_rejected(self):
        self.policy['revision']+=1;self.write_policy()
        with self.assertRaisesRegex(ValueError,'policy_changed'):self.simulate()
        self.policy['revision']-=1;self.write_policy()
        p=self.root/'quotes'/(RUN+'.json');q=json.loads(p.read_text('utf-8'));q['result']['rows'][0]['proposal']='0.0001';p.write_text(encoded(q),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'disagrees'):self.simulate()
        p=self.code/'fc27_quote_engine.py';p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'engine_changed'):self.simulate()

    def test_paths_manual_overrides_and_unknown_tiers_denied(self):
        with self.assertRaises(ValueError):self.bridge.load('../secret',self.engine,self.policy,self.draft['baseline_policy'])
        for changes in ([dict(tier='PC',min_discount_pct='0',max_discount_pct='1')],[dict(tier='at_least_40',min_discount_pct='2',max_discount_pct='1')],[dict(tier='at_least_40',min_discount_pct='0',max_discount_pct='100')]):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.bridge.rules(self.engine,self.policy,changes)
        p=self.root/'quotes'/(RUN+'.json');q=json.loads(p.read_text('utf-8'));q['edits']['costs']={'PS':'0.1'};p.write_text(encoded(q),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'manual_source'):self.simulate()

    def test_extended_research_discounts_leave_production_rules_and_floor_intact(self):
        before=(self.root/'config/automation.json').read_bytes()
        self.draft['band_changes']=[dict(tier=t,min_discount_pct='25',max_discount_pct='25') for t in self.policy['pricing_rules']['bands']]
        result=self.simulate()
        self.assertEqual(result['candidate_evaluator'],ps.CANDIDATE_EVALUATOR)
        self.assertTrue(any(Decimal(x['candidate_minus_baseline']) for x in result['comparisons']))
        self.assertEqual(before,(self.root/'config/automation.json').read_bytes())
        for row in result['candidate']['rows']:self.assertEqual(Decimal(row['minimum_gross_margin_pct']),Decimal(self.policy['minimum_gross_margin_pct']))
        rules=self.bridge.rules(self.engine,self.policy,self.draft['band_changes'])
        with self.assertRaises(ValueError):self.engine.normalize_discount_rules(rules)
        for value in ('-1','100','NaN','1.001'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.bridge.rules(self.engine,self.policy,[dict(tier='at_least_40',min_discount_pct='0',max_discount_pct=value)])


class Records(Fixture):
    def setUp(self):
        super().setUp();self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.args=dict(project='FC27',intent='draft_only',question='虚构测试研究',evidence_refs=['ev_real'],baseline_policy=self.draft['baseline_policy'],band_changes=self.draft['band_changes'],hypothesis='固定输入下比较折扣，不预测需求。',risk_notes='共用规则影响全部平台。',review_plan='实际执行另行核回执与成熟窗口。')

    def create(self,args=None):return st.create(self.db,'wulv','task',args or self.args,{'ev_real':{}},self.bridge,NOW)

    def test_persistent_dedupe_and_scope(self):
        first=self.create();self.assertEqual(first,self.create());self.assertEqual(self.db.execute('SELECT count(*) FROM strategy_drafts').fetchone()[0],1)
        with self.assertRaises(PermissionError):st.get_draft(self.db,'other',first['id'])
        for extra in ('actor','approved','costs','manual','minimum_gross_margin_pct','platforms'):
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.create(dict(self.args,**{extra:True}))
        with self.assertRaisesRegex(ValueError,'evidence_scope'):self.create(dict(self.args,evidence_refs=['forged']))

    def test_simulation_cache_requires_same_current_versions_and_task(self):
        draft=self.create();args=dict(project='FC27',intent='simulate_only',proposal_id=draft['id'],snapshot_id=RUN,expected_policy=self.draft['baseline_policy'])
        first=st.simulate(self.db,'wulv','task',args,self.bridge,NOW);second=st.simulate(self.db,'wulv','task',args,self.bridge,NOW)
        self.assertEqual(first['id'],second['id']);self.assertTrue(second['reused'])
        with self.assertRaises(PermissionError):st.simulate(self.db,'wulv','other_task',args,self.bridge,NOW)
        self.policy['revision']+=1;self.write_policy()
        with self.assertRaisesRegex(ValueError,'policy_changed'):st.simulate(self.db,'wulv','task',args,self.bridge,NOW)

    def test_readback_time_does_not_create_duplicate_simulation(self):
        draft=self.create();args=dict(project='FC27',intent='simulate_only',proposal_id=draft['id'],snapshot_id=RUN,expected_policy=self.draft['baseline_policy'])
        with patch.object(self.bridge,'execution_checks',side_effect=[[{'status':'pass','observed_at':'first'}],[{'status':'block','observed_at':'second'}]]):
            first=st.simulate(self.db,'wulv','task',args,self.bridge,NOW)
            second=st.simulate(self.db,'wulv','task',args,self.bridge,NOW)
        self.assertEqual(first['id'],second['id']);self.assertTrue(second['reused'])
        self.assertEqual(second['current_precheck'][0]['status'],'block')
        self.assertEqual(self.db.execute('SELECT count(*) FROM strategy_simulations').fetchone()[0],1)

    def test_review_axes_do_not_invent_execution_or_effect(self):
        draft=self.create();args=dict(decision_id=draft['id'],start='2026-10-01',end='2026-10-19')
        result=st.read_review(self.db,'wulv',args,[]);self.assertEqual(result['execution_state'],'NOT_EXECUTED');self.assertEqual(result['outcome_state'],'NOT_ELIGIBLE')
        event=dict(report='a'*32,action='action-1',status='executed',note='human statement',review_at=NOW.isoformat())
        args['decision_id']=event['report']+':action-1';result=st.read_review(self.db,'wulv',args,[event]);self.assertEqual(result['execution_state'],'UNKNOWN');self.assertEqual(result['outcome_state'],'INCONCLUSIVE')
        with self.assertRaises(PermissionError):st.read_review(self.db,'wulv',args,[])

    def test_registered_schemas_and_wire_allowlist_are_exact(self):
        import runs_contract as runs
        # Directly load the candidate, irrespective of earlier support module imports.
        spec=importlib.util.spec_from_file_location('candidate_runs',HERE/'source/runs_contract.py');runs=importlib.util.module_from_spec(spec);spec.loader.exec_module(runs)
        for item in st.schemas():self.assertIn(item['function']['name'],runs.WIRE_TOOLS)
        self.assertEqual(len(st.schemas()),5);self.assertTrue(all(s['function']['parameters']['additionalProperties'] is False for s in st.schemas()))
        self.assertEqual(set(runs.SEMANTIC_TOOLS[-5:]),set(st.NAMES))

    def test_new_algorithm_remains_reviewable_idea_without_fabricated_prices(self):
        idea=dict(name='分阶段试价',description='先验证可比样本。',entry_conditions='来源齐备。',pricing_formula='根据成熟样本调整步幅。',stop_conditions='触及利润底线即停止。')
        draft=self.create(dict(self.args,band_changes=[],rule_idea=idea))
        self.assertEqual(draft['research_state'],'DRAFT')
        args=dict(project='FC27',intent='simulate_only',proposal_id=draft['id'],snapshot_id=RUN,expected_policy=self.draft['baseline_policy'])
        self.assertEqual(st.simulate(self.db,'wulv','task',args,self.bridge,NOW)['status'],'unsupported_capability')
        self.assertEqual(self.db.execute('SELECT count(*) FROM strategy_simulations').fetchone()[0],0)
        self.assertEqual(st.read_review(self.db,'wulv',dict(decision_id=draft['id'],start='2026-10-01',end='2026-10-19'),[])['research_state'],'DRAFT')
        with self.assertRaises(ValueError):self.create(dict(self.args,band_changes=[]))
        with self.assertRaises(ValueError):self.create(dict(self.args,band_changes=[],rule_idea=dict(idea,approved=True)))


class TaskBoundary(Fixture):
    def setUp(self):
        super().setUp()
        from pilot import TaskStore
        self.tasks=TaskStore(self.root/'tasks.sqlite3')
        spec=dict(period={'start':'2026-10-19','end_exclusive':'2026-10-20','timezone':'Asia/Shanghai'},snapshot_id='fc-detail-test',template_version='test',knowledge_version='test',budget_policy_id='test')
        self.task=self.tasks.create('wulv',spec);self.tasks.reserve_dispatch(self.task['id'],'wulv','lease');self.tasks.bind_run(self.task['id'],'wulv','lease','run_test')
        self.book=types.SimpleNamespace(capture_id='fc-detail-test',evidence={'ev_real':{}},action_history=[])
        spec=importlib.util.spec_from_file_location('candidate_proxy',HERE/'source/proxy_gateway.py');proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)
        self.scope=proxy.ScopedTools(self.tasks,self.book,lambda:NOW)
        self.args=dict(project='FC27',intent='draft_only',question='合成边界测试',evidence_refs=['ev_real'],baseline_policy=self.draft['baseline_policy'],band_changes=self.draft['band_changes'],hypothesis='不预言需求。',risk_notes='不执行业务。',review_plan='按原回执复查。')

    def test_actual_scoped_tool_dispatch_and_cancellation(self):
        with patch.object(st,'SimulationBridge',return_value=self.bridge):
            value=self.scope.call('wulv',self.task['id'],'lease','mcp__fcro__fs_strategy_propose',self.args)
            self.assertFalse(value['data']['execution_authorized'])
            with self.assertRaises(PermissionError):self.scope.call('other',self.task['id'],'lease','mcp__fcro__fs_strategy_capabilities',{})
            self.tasks.cancel(self.task['id'],'wulv')
            with self.assertRaises(PermissionError):self.scope.call('wulv',self.task['id'],'lease','mcp__fcro__fs_strategy_propose',self.args)

    def test_management_task_cannot_self_declare_FC_scope(self):
        spec=deepcopy(self.task['spec']);spec['snapshot_id']='management-test'
        task=self.tasks.create('wulv',spec);self.tasks.reserve_dispatch(task['id'],'wulv','lease2');self.tasks.bind_run(task['id'],'wulv','lease2','run_management')
        book=types.SimpleNamespace(capture_id='management-test',evidence={'ev_real':{}},action_history=[])
        scope=type(self.scope)(self.tasks,book,lambda:NOW)
        with patch.object(st,'SimulationBridge',return_value=self.bridge),self.assertRaisesRegex(PermissionError,'project_denied'):st.call(scope,'wulv',task['id'],'lease2','fs.strategy.propose',self.args)

    def test_post_scope_failure_rolls_back_new_research_record(self):
        calls=[]
        def guard(*args):
            calls.append(args)
            if len(calls)==2:raise PermissionError('inactive_task')
        fake=types.SimpleNamespace(tasks=self.tasks,book=self.book,clock=lambda:NOW,context=guard)
        with patch.object(st,'SimulationBridge',return_value=self.bridge),self.assertRaises(PermissionError):st.call(fake,'wulv',self.task['id'],'lease','fs.strategy.propose',self.args)
        with self.tasks.db() as db:
            st.schema(db);self.assertEqual(db.execute('SELECT count(*) FROM strategy_drafts').fetchone()[0],0)

    def test_new_simulation_switch_does_not_touch_original_policy(self):
        import strategy_workspace as workspace
        service=types.SimpleNamespace(authorizer=lambda _:True,tasks=self.tasks,clock=lambda:NOW,action_history=lambda _:[])
        before=(self.root/'config/automation.json').read_bytes()
        self.assertEqual(workspace.handle(service,'wulv',{'kind':'hermes_strategy','action':'set_enabled','enabled':False})[0],200)
        with patch.object(st,'SimulationBridge',return_value=self.bridge),self.assertRaises(PermissionError):st.call(self.scope,'wulv',self.task['id'],'lease','fs.strategy.propose',self.args)
        self.assertEqual(before,(self.root/'config/automation.json').read_bytes())
        self.assertEqual(workspace.handle(service,'other',{'kind':'hermes_strategy','action':'list'})[0],403)

    def completed_source(self):
        source='c'*32
        with self.tasks.db() as db:
            db.execute('CREATE TABLE requests(id TEXT,owner TEXT,body TEXT,state TEXT,task_id TEXT,result TEXT)')
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?)',(source,'wulv',encoded({'question':'合成可见来源'}),'COMPLETED',self.task['id'],encoded({'artifact':'test'})))
            db.execute('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT)')
            db.execute('INSERT INTO evidence VALUES(?,?,?)',(self.task['id'],'ev_real',encoded({'evidence_id':'ev_real','source':'test','query':{}})))
        from report_artifacts import save_raw,save_result
        save_raw(self.root,self.task['id'],'可见结论',{'ev_real':{}},{})
        save_result(self.root,self.task['id'],{'summary':'可见结论','research_text':'可见结论','html_design':{'fixture':True}},'<p>可见结论</p>')
        self.tasks.change(self.tasks.get(self.task['id'],'wulv'),'VALIDATING')
        self.tasks.change(self.tasks.get(self.task['id'],'wulv'),'SUCCEEDED')
        return source

    def test_learning_proposal_is_owned_completed_candidate_not_publication(self):
        source=self.completed_source();value=dict(kind='experience',lesson='核实原始标记。',applies_to='经营复盘',evidence_refs=['ev_real'],counterexample='关联身份不能替代新老客分类。',expires_at=(NOW+timedelta(days=30)).isoformat())
        first=st.learning_propose(self.tasks,'wulv',{'source':source,'candidate':value},NOW,lambda:None)
        second=st.learning_propose(self.tasks,'wulv',{'source':source,'candidate':value},NOW,lambda:None)
        self.assertTrue(second['reused'])
        with self.tasks.db() as db:self.assertEqual(support.lr.manifest(db,'wulv','FS',NOW)['experiences'],[])
        with self.assertRaisesRegex(ValueError,'conflict'):st.learning_propose(self.tasks,'wulv',{'source':source,'candidate':dict(value,lesson='另一条候选。')},NOW,lambda:None)
        with self.assertRaises(PermissionError):st.learning_propose(self.tasks,'other',{'source':source,'candidate':value},NOW,lambda:None)

    def test_method_diff_requires_exact_current_base_and_remains_l2_candidate(self):
        source=self.completed_source()
        from report_method import HTML_DESIGN_MANIFEST_SHA256
        value=dict(kind='method_diff',base_manifest_sha256='0'*64,lesson_diff='仅建议补充检查，需人工审核。')
        with self.assertRaisesRegex(ValueError,'base_conflict'):st.learning_propose(self.tasks,'wulv',{'source':source,'candidate':value},NOW,lambda:None)
        value['base_manifest_sha256']=HTML_DESIGN_MANIFEST_SHA256
        result=st.learning_propose(self.tasks,'wulv',{'source':source,'candidate':value},NOW,lambda:None)
        self.assertEqual(result['risk'],'L2');self.assertEqual(result['publication_state'],'NOT_PUBLISHED')

    def test_existing_http_dispatch_keeps_authentication_and_same_origin(self):
        import threading,urllib.request,urllib.error
        from http.server import BaseHTTPRequestHandler,HTTPServer
        import strategy_workspace as workspace
        tree=ast.parse((HERE/'source/controller.py').read_text('utf-8'))
        fn=next(n for cls in tree.body if isinstance(cls,ast.ClassDef) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_post')
        namespace={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<existing-controller-dispatch>','exec'),namespace)
        controller=types.SimpleNamespace(tasks=self.tasks,authorizer=lambda u:u=='wulv',clock=lambda:NOW,action_history=lambda _:[])
        dispatch=namespace['_post']
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                body=json.loads(inner.rfile.read(int(inner.headers['Content-Length'])))
                code,result=dispatch(controller,body,inner.headers.get('X-Auth-User',''),inner.headers)
                raw=encoded(result).encode();inner.send_response(code);inner.send_header('Content-Length',str(len(raw)));inner.end_headers();inner.wfile.write(raw)
            def log_message(*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def post(headers):
            request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port),data=encoded({'kind':'hermes_strategy','action':'list'}).encode(),headers=headers)
            try:
                with urllib.request.urlopen(request) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:
                with error:return error.code,json.load(error)
        try:
            self.assertEqual(post({})[0],401)
            self.assertEqual(post({'X-Auth-User':'wulv'})[0],403)
            headers={'X-Auth-User':'wulv','X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}
            with patch.object(workspace,'SimulationBridge',return_value=self.bridge):status,result=post(headers)
            self.assertEqual(status,200);self.assertEqual(result['drafts'],[]);self.assertFalse(result['execution_authorized'])
        finally:server.shutdown();server.server_close();thread.join()


class FrontendContract(unittest.TestCase):
    def test_publisher_is_exact_nine_targets_with_original_guards(self):
        spec=importlib.util.spec_from_file_location('strategy_release',HERE/'deploy/release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        self.assertEqual(len(release.TARGETS),9);self.assertEqual(len(release.NEW),4)
        sha=hashlib.sha256((HERE/'frontend/strategy.js').read_bytes()).hexdigest()
        self.assertTrue(release.TARGETS['frontend/strategy.js'].endswith('/hermes-v2-'+sha[:12]+'.js'))
        self.assertFalse(any('/fc27-cloud' in p for p in release.TARGETS.values()))
        manifest=dict(scope=release.SCOPE,businessWrites=False,timersChanged=False,files=[dict(candidate=k,target=v,beforeSha256=None if k in release.NEW else 'a'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()])
        self.assertEqual(release.checked_manifest(manifest),manifest)
        manifest['files'][0]['beforeSha256']=None
        with self.assertRaises(ValueError):release.checked_manifest(manifest)

    def test_only_the_new_views_navigation_and_immutable_script_change(self):
        p=support.ROOT/'releases/fs-dashboard/hermes-ops-20261020/repairs/346ef40d8ab4baa7/source/brain-index.html'
        if p.exists():original=p.read_bytes()
        else:
            import base64
            v=json.loads((support.ROOT/'.agent_runtime/hermes-v2-core-20261020/brain-active-source.json').read_text('utf-8-sig'));original=base64.b64decode(v['b64'])
        candidate=(HERE/'source/brain.html').read_bytes().decode('utf-8');js=(HERE/'frontend/strategy.js').read_bytes();sha=hashlib.sha256(js).hexdigest()
        script='<script defer src="hermes-v2-'+sha[:12]+'.js"></script>'
        self.assertEqual(candidate.count(script),1);restored=candidate.replace(script,'',1)
        added='<a href="#strategy-review">策略与复查</a><a href="#experience-method">经验与方法</a>'
        self.assertEqual(restored.count(added),1);restored=restored.replace(added,'',1)
        lo=restored.index('<section id="strategy-review"');hi=restored.index('<footer>',lo);restored=restored[:lo]+restored[hi:]
        self.assertEqual(restored.encode('utf-8'),original)


if __name__=='__main__':unittest.main()

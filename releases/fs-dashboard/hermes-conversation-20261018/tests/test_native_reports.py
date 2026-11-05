"""Offline report integration: real SQLite stores and original report functions."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import patch
import ast
import os
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import types
import re

HERE=Path(__file__).resolve().parents[4]
REF=Path(os.environ.get('FS_NATIVE_TEST_REFERENCE_ROOT',str(HERE)))
C='releases/fs-dashboard/hermes-conversation-20261018/source'
K='releases/fs-dashboard/knowledge-layering-20261023/source'
F='releases/fs-dashboard/fc-coins-workflow-20261022/source'
P='releases/fc-coins/fc-pricing-v3-20261026/source'
R='releases/fc-coins/fc-review-channel-20261026/source'
V='releases/fs-dashboard/hermes-v2-core-20261020/source'
W='releases/fs-dashboard/hermes-data-workspace-20261018/source'
PILOT='releases/fs-dashboard/hermes-fc-pilot-20261013'
paths=[K,P,R,F,V,C,W,PILOT,'releases/fs-dashboard/nightly-reschedule-20261025/source',
       'releases/fs-dashboard/hermes-admin-recovery-20261020/source','releases/fs-dashboard/fc-daily-20261013/source',
       'releases/fs-dashboard/traffic-hermes-20261017/source','releases/fs-dashboard/management-all-sites-20261025/source',
       'mmoexp_google_data/details','releases/fs-dashboard/cache-archive-retention-20261025/source',
       'releases/fs-dashboard/fc-coins-evidence-20261021/source',
       'releases/fs-dashboard/hermes-report-import-20261015/source',
       'releases/fs-dashboard/hermes-generic-data-20261018/source',
       'releases/fs-dashboard/user-analytics-20261022/source',
       'releases/fs-dashboard/hermes-report-repair-20261019/source',
       'releases/fs-dashboard/hermes-market-sources-20261015/source',
       'releases/fs-dashboard/hermes-fs-research-integration-20261015/source',
       'releases/fs-dashboard/management-november-20261103/source']
sys.path[:0]=[str(HERE/p) for p in paths]+[str(REF/p) for p in paths]
sys.path.insert(len(paths)*2,str(REF))
sys.dont_write_bytecode=True

from pilot import TaskStore, encoded
from conversation_store import ConversationStore
from conversation_native import NativeConversation, canonical
NOW=datetime(2026,11,6,tzinfo=timezone.utc)

def load(name,rel):
    path=HERE/rel
    if not path.exists():path=REF/rel
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def original_function(rel,name):
    path=HERE/rel
    if not path.exists():path=REF/rel
    tree=ast.parse(path.read_text('utf-8'))
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    return namespace[name]

class ReportRoute(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tasks=TaskStore(self.root/'tasks.sqlite3')
        self.h=SimpleNamespace(root=self.root,tasks=self.tasks,authorizer=lambda owner:owner=='alice',clock=lambda:NOW,
            lock=threading.RLock(),books={},tokens={},gateways={},source_root=self.root)
        self.store=ConversationStore(self.root/'conversations')
        self.service=SimpleNamespace(store=self.store,hermes=self.h,lock=threading.RLock(),run_root=self.root/'run')
        self.native=NativeConversation(self.service)
        update=original_function(K+'/controller.py','update')
        update.__globals__['encoded']=encoded
        self.h.update=MethodType(update,self.h)
        self.spec=dict(period=dict(start='2026-11-04',end_exclusive='2026-11-05',timezone='Asia/Shanghai'),
            snapshot_id='fc-detail-real-source',template_version='report-real-input',knowledge_version=self.helper().prepare_knowledge(self.h,dict(kind='hermes_report',mode='daily',request_id='report_original_01'),'alice')['version'],budget_policy_id='original')
        self.task=self.tasks.create('alice',self.spec)
        self.cid=self.store.create('alice')['conversation_id'];self.lease='c'*32
    def helper(self):
        path=HERE/K/'native_reports.py'
        self.assertTrue(path.exists(),'native report host bridge is missing')
        return load('native_reports',K+'/native_reports.py')
    def prepare(self):
        bridge=self.helper()
        with self.tasks.db() as db:
            db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT)')
            db.execute('CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT NOT NULL)')
            db.execute('INSERT INTO request_knowledge(id,version) VALUES(?,?)',('a'*32,self.spec['knowledge_version']))
            db.execute('INSERT INTO requests(id,owner,request_id,body,state,task_id) VALUES(?,?,?,?,?,?)',
                ('a'*32,'alice','report_original_01',encoded(dict(kind='hermes_report',mode='daily',start='2026-11-04',end='2026-11-04',question='Why?',request_id='report_original_01')),'DISPATCH_UNKNOWN',self.task['id']))
        self.tasks.reserve_dispatch(self.task['id'],'alice',self.lease)
        turn=self.store.reserve_report_turn('alice','Why?','report_original_01',self.task['id'])
        self.cid=turn['conversation_id']
        bound=dict(owner='alice',conversation_id=self.cid,turn_id=turn['turn_id'],request_id='report_original_01',session_id=turn['session_id'],lease=self.lease,run_id=None)
        with self.store.db() as db:
            db.execute('INSERT INTO native_conversation_runs(turn_id,binding,body,idempotency_key,fingerprint) VALUES(?,?,?,?,?)',
                (turn['turn_id'],canonical(bound),'{}','hn-'+'b'*64,'d'*64))
        self.store.bind_task('alice',self.cid,turn['turn_id'],turn['turn_id'],self.lease)
        return bridge,bound
    def admit(self):
        bridge,bound=self.prepare();bound['run_id']='run_'+'e'*32
        self.store.bind_run('alice',self.cid,bound['turn_id'],bound['run_id'])
        with self.store.db() as db:db.execute('UPDATE native_conversation_runs SET binding=?',(canonical(bound),))
        bridge.admitted(self.native,bound)
        return bridge,bound
    def test_real_task_reserved_as_the_real_native_turn_not_alias(self):
        self.assertTrue(hasattr(self.store,'reserve_report_turn'),'private report reservation is missing')
        turn=self.store.reserve_report_turn('alice','Why?','report_original_01',self.task['id'])
        self.assertEqual(turn['turn_id'],self.task['id'])
        repeated=self.store.reserve_report_turn('alice','Why?','report_original_01',self.task['id'])
        self.assertTrue(repeated['reused'])
        with self.assertRaises(ValueError):self.store.reserve_report_turn('alice','Changed','report_original_01',self.task['id'])
        with self.assertRaises(LookupError):self.store.reserve_report_turn('bob','Why?','report_original_02',self.task['id'])
    def test_native_binding_rechecks_real_task_state_lease_run_and_scope(self):
        bridge,bound=self.admit()
        self.assertTrue(self.native.authorized(bound))
        self.assertEqual(bridge.context(self.native,bound)['task']['id'],bound['turn_id'])
        for col,value in [('lease','f'*32),('run_id','run_'+'f'*32),('state','CANCEL_REQUESTED')]:
            with self.subTest(column=col):
                with self.tasks.db() as db:old=db.execute('SELECT '+col+' FROM tasks').fetchone()[0];db.execute('UPDATE tasks SET '+col+'=?',(value,))
                self.assertFalse(self.native.authorized(bound))
                with self.tasks.db() as db:db.execute('UPDATE tasks SET '+col+'=?',(old,))
    def test_same_id_active_union_and_original_usage_identity(self):
        bridge,bound=self.admit()
        active=original_function(R+'/fs_inprocess.py','active_model_tasks')(self.tasks)
        self.assertEqual(active,{('alice',self.task['id'])})
        self.tasks.fence(self.task['id'],'alice');self.native.fence('alice',self.cid,bound['turn_id'])
        self.assertEqual(original_function(R+'/fs_inprocess.py','active_model_tasks')(self.tasks),set())
    def test_report_deadline_and_iam_revoke_actual_authority(self):
        bridge,bound=self.admit();self.h.nightly=SimpleNamespace(deadline=lambda key:NOW-timedelta(seconds=1))
        self.assertFalse(self.native.authorized(bound))
        self.h.nightly=SimpleNamespace(deadline=lambda key:None);self.h.authorizer=lambda owner:False
        self.assertFalse(self.native.authorized(bound))
    def test_report_host_denies_direct_coupon_goal_pricing_and_live_orders_bypasses(self):
        bridge,bound=self.admit()
        for name,args in [('fs.native.user_data',dict(binding=bound,name='fs_create_coupon',arguments={})),
                          ('fs.native.read',dict(binding=bound,path='/users/live-orders',params={})),
                          ('fs.native.pricing',dict(binding=bound,arguments={'action':'capabilities'}))]:
            with self.subTest(name=name),self.assertRaises(PermissionError):self.native.host_tool(bound,name,args)
    def test_finance_shipping_keeps_same_response_and_actual_missing_does_not_block(self):
        bridge,bound=self.admit()
        shipping=dict(status='available',currency='CNY',metrics={'profitCny':{'value':20,'unit':'CNY'}},filters={'gid':'1322'})
        self.h.read_range=lambda params:(200,dict(profile=dict(shipping=shipping),scopeContractId='actual-contract'))
        value=bridge.finance(self.native,bound,'shipping',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))
        self.assertEqual(value['shipping'],shipping)
        missing=bridge.finance(self.native,bound,'actual_profit',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))
        self.assertEqual(missing['status'],'not_available')
        with self.assertRaises(ValueError):bridge.finance(self.native,bound,'shipping',dict(email='private@example.test'))
        self.h.read_range=lambda params:(200,dict(status='available',profile={}))
        self.assertEqual(bridge.finance(self.native,bound,'shipping',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))['status'],'not_available')
    def test_actual_profit_uses_original_authenticated_service_and_projects_only_aggregates(self):
        bridge,bound=self.admit()
        seen=[]
        class ExistingService:
            def get(_,params,owner):
                seen.append((params,owner))
                return 200,dict(status='partial',actualContract='same-order-actual-profit-v1',currency='CNY',
                    denominator=dict(profitCny=20,missingCostOrders=3,coverageStatus='partial',email='do-not-leak'),
                    trend=[dict(key='2026-11-04',profitCny=20,orderNo='do-not-leak')],orders=[{'email':'do-not-leak'}],rawMembership=['do-not-leak'])
        self.h.actual_profits=ExistingService()
        result=bridge.finance(self.native,bound,'actual_profit',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))
        self.assertEqual(seen[0][1],'alice');self.assertEqual(seen[0][0]['mode'],['actual-profit'])
        self.assertEqual(result['denominator']['missingCostOrders'],3)
        self.assertNotIn('do-not-leak',json.dumps(result))
    def archive_host(self):
        artifacts=load('report_artifacts',W+'/report_artifacts.py');sys.modules['report_artifacts']=artifacts
        # This is the original module with only its Linux OS import substituted.
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace()}):
            management=load('report_management','releases/fs-dashboard/management-all-sites-20261025/source/management_context.py')
        publish=original_function(K+'/controller.py','publish_report')
        publish.__globals__.update(json=json,re=re,encoded=encoded,directory=artifacts.directory,read_file=artifacts.read_file,
            save_result=artifacts.save_result,management_context=management,request_report_kind=lambda body:'daily',
            decode_output=lambda text:(_ for _ in ()).throw(ValueError()),
            deliver_output=lambda *a,**k:(_ for _ in ()).throw(AssertionError('legacy presentation coercion')),
            render_report=lambda *a,**k:(_ for _ in ()).throw(AssertionError('legacy renderer')))
        self.h.publish_report=MethodType(publish,self.h)
        get=original_function(K+'/controller.py','get_job');get.__globals__['json']=json
        self.h.get_job=MethodType(get,self.h);self.h.usage=lambda *a:{}
        recover=original_function(K+'/controller.py','recover_reports');recover.__globals__.update(json=json,time=__import__('time'),read_file=artifacts.read_file)
        self.h.recover_reports=MethodType(recover,self.h);self.h.delivery_retries={}
        with self.tasks.db() as db:db.execute('CREATE TABLE IF NOT EXISTS evidence(task_id TEXT,evidence_id TEXT,content TEXT,PRIMARY KEY(task_id,evidence_id))')
        # Enqueue is a downstream optional external consumer; no model/provider is installed.
        self.addCleanup(lambda:sys.modules.pop('learning_service',None))
        sys.modules['learning_service']=SimpleNamespace(enqueue_completed=lambda *a:None)
        return artifacts
    def actual_service(self):
        # OS flock is the only unavailable Windows dependency. No model, worker,
        # SDK process or network transport is constructed or invoked.
        # Other existing tests load the old Core reference under the same module
        # names. Resolve this actual maintained chain independently, then restore
        # the caller's module cache and path after this case.
        path_patch=patch.object(sys,'path',[str(HERE/p) for p in paths]+list(sys.path))
        path_patch.start();self.addCleanup(path_patch.stop)
        module_patch=patch.dict(sys.modules)
        module_patch.start();self.addCleanup(module_patch.stop)
        for name in ('controller','transport','proxy_gateway','fs_inprocess','fs_evidence',
                     'research','continuation','report_artifacts','conversation_service',
                     'native_reports','business_context','knowledge_catalog','fc_daily'):
            sys.modules.pop(name,None)
        self.os_patch=patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,LOCK_UN=8,LOCK_SH=1,flock=lambda *a:None)})
        self.os_patch.start();self.addCleanup(self.os_patch.stop)
        import controller,conversation_service
        from fc_daily import DailyReports
        from transport import Grants
        host=controller.HermesService.__new__(controller.HermesService)
        host.__dict__.update(self.h.__dict__)
        host.update=MethodType(controller.HermesService.update,host)
        host.daily=DailyReports(None,self.root/'daily');host.grants=Grants()
        host.nightly=SimpleNamespace(deadline=lambda key:None)
        host.report_books={};host.report_budget_policy_id='original'
        host.run_root=self.root/'run';(host.run_root/'admissions').mkdir(parents=True)
        self.h=host
        service=conversation_service.ConversationService(host,self.root/'conversations',host.run_root)
        self.addCleanup(lambda:service.pool.shutdown(wait=True))
        self.addCleanup(lambda:service.pricing_pool.shutdown(wait=True))
        self.addCleanup(lambda:service.pricing.pool.shutdown(wait=True))
        host.conversation=service;self.service=service;self.store=service.store;self.native=service.native
        self.addCleanup(lambda:sys.modules.pop('learning_service',None))
        sys.modules['learning_service']=SimpleNamespace(enqueue_completed=lambda *a:None)
        return service
    def test_original_native_dispatch_single_post_original_lease_and_budget_ledger(self):
        service=self.actual_service();bridge,bound=self.prepare()
        with self.tasks.db() as db:db.execute('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT)')
        # prepare inserted the durable native reservation to test authorization;
        # this test begins immediately before the original dispatch reserves it.
        with self.store.db() as db:db.execute('DELETE FROM native_conversation_runs');db.execute("UPDATE turns SET task_id=NULL,lease=NULL")
        calls=[];ready=[]
        def request(method,path,body=None,idempotency=None,**kwargs):
            calls.append((method,path,body,idempotency))
            self.assertEqual(self.tasks.get(self.task['id'],'alice')['state'],'DISPATCH_UNKNOWN')
            return 202,{'run_id':'run_'+'e'*32}
        service._request=request
        service._monitor=lambda *args:ready.append(self.tasks.get(self.task['id'],'alice'))
        self.native.dispatch('alice',self.cid,bound['turn_id'],bound['session_id'],'Why?',bound['request_id'],report_key='a'*32)
        actual=self.native.row('alice',self.cid,self.task['id'])['binding']
        self.assertEqual(actual['lease'],self.lease);self.assertEqual(actual['turn_id'],self.task['id'])
        self.assertEqual(ready[0]['run_id'],actual['run_id']);self.assertEqual(ready[0]['state'],'RUNNING')
        self.native.dispatch('alice',self.cid,bound['turn_id'],bound['session_id'],'Why?',bound['request_id'],report_key='a'*32)
        self.assertEqual(len(calls),1)
        gateway=self.h.gateways[self.task['id']]
        request_body={'messages':[{'role':'user','content':'Why?'}],'max_tokens':10,'tools':[],'enable_thinking':True,'reasoning_effort':'high'}
        fingerprint,_=gateway.budget.reserve('alice',self.task['id'],0,request_body,50)
        gateway.budget.settle(fingerprint,{'id':'response1','usage':dict(prompt_tokens=2,completion_tokens=3,total_tokens=5),
            'choices':[{'message':{'role':'assistant','content':'Costs rose.'},'finish_reason':'stop'}]},request_body,50)
        self.assertEqual(self.h.usage(self.task['id'],'alice')['calls'],1)
        with self.h.daily.db() as db:self.assertEqual(db.execute('SELECT task FROM hermes_reservations').fetchall()[0][0],self.task['id'])
    def test_lost_202_only_looks_up_original_session_and_preserves_task(self):
        service=self.actual_service();bridge,bound=self.prepare()
        with self.tasks.db() as db:db.execute('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT)')
        with self.store.db() as db:db.execute('DELETE FROM native_conversation_runs');db.execute("UPDATE turns SET task_id=NULL,lease=NULL")
        calls=[]
        def request(method,path,body=None,idempotency=None,**kwargs):
            calls.append((method,path,idempotency))
            if method=='POST':raise TimeoutError('lost202')
            return 200,dict(run_id='run_'+'e'*32,session_id=bound['session_id'],status='queued')
        service._request=request
        with self.assertRaises(TimeoutError):self.native.dispatch('alice',self.cid,bound['turn_id'],bound['session_id'],'Why?',bound['request_id'],report_key='a'*32)
        bridge.abandon(self.native,self.native.row('alice',self.cid,bound['turn_id'])['binding'])
        found=[];service._recover=lambda *args:found.append(args)
        self.native.reconcile_unknown('alice',self.cid,bound['turn_id'])
        self.assertEqual([x[0] for x in calls],['POST','GET'])
        self.assertEqual(calls[1][1],'/v1/native/'+bound['session_id'])
        self.assertEqual(self.tasks.get(self.task['id'],'alice')['run_id'],'run_'+'e'*32)
        self.assertEqual(len(found),1)
    def test_original_submit_reuses_identical_native_report_before_any_dispatch(self):
        service=self.actual_service();bridge=self.helper()
        with self.tasks.db() as db:
            db.executescript('CREATE TABLE requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT,UNIQUE(owner,request_id));CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT);CREATE TABLE report_trash(id TEXT PRIMARY KEY)')
        body=dict(kind='hermes_report',mode='daily',start='2026-11-04',end='2026-11-04',question='Why?',request_id='submit_original_01')
        code,job,_=self.h._submit_report(body,'alice',defer_submit=True)
        self.assertEqual(code,202)
        other=dict(body,request_id='submit_original_02')
        code,reused=self.h._submit_report(other,'alice',defer_submit=True)
        self.assertEqual(code,200);self.assertEqual(reused['id'],job['id'])
        code,conflict=self.h._submit_report(dict(body,question='Changed'),'alice',defer_submit=True)
        self.assertEqual(code,409)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM turns').fetchone()[0],0)
    def test_report_relays_original_research_calculation_and_denies_workflow(self):
        bridge,bound=self.admit()
        from research import ResearchBook
        book=ResearchBook(dict(snapshot_id=self.spec['snapshot_id'],as_of=NOW.isoformat(),coverage=dict(period=dict(start='2026-11-04',end='2026-11-04')),orders=[],backlog=[]),{},dict(start='2026-11-04',end='2026-11-04'),skills=None)
        evidence=book.register('test',{},dict(amount='20'))
        self.h.report_books={self.task['id']:book}
        with patch('zoneinfo.ZoneInfo',return_value=timezone(timedelta(hours=8))):
            capabilities=self.native.host_tool(bound,'fs.native.report',dict(binding=bound,name='capabilities',arguments={}))
            names={s['function']['name'] for s in capabilities['tool_schemas']}
            self.assertIn('mcp__fcro__fc_calculate',names);self.assertIn('mcp__fcro__fc_query_shipping_profit',names)
            self.assertNotIn('mcp__fcro__fc_run_pricing_workflow',names)
            args=dict(operation='sum',values=['20'],evidence_ids=[evidence['evidence_id']],value_paths=[dict(evidence_id=evidence['evidence_id'],path='/data/amount')],assumptions=[''])
            result=self.native.host_tool(bound,'fs.native.report',dict(binding=bound,name='mcp__fcro__fc_calculate',arguments=args))
            self.assertEqual(result['data']['result']['sum'],'20.00')
            with self.assertRaises(PermissionError):self.native.host_tool(bound,'fs.native.report',dict(binding=bound,name='mcp__fcro__fc_run_pricing_workflow',arguments={}))
            args['values']=['99']
            with self.assertRaisesRegex(ValueError,'calculation_operand_mismatch'):self.native.host_tool(bound,'fs.native.report',dict(binding=bound,name='mcp__fcro__fc_calculate',arguments=args))
    def test_report_knowledge_uses_saved_catalog_without_freezing_document_text(self):
        bridge=self.helper();folder=self.root/'knowledge-releases/v1';folder.mkdir(parents=True)
        raw=b'Current report method: read source evidence as needed.';(folder/'note.md').write_bytes(raw)
        index=dict(contract='fs-knowledge-index-v1',release_state='published',release='v1',source_commit='1'*40,source_root='knowledge-releases/v1',entries=[dict(id='fc.reporting.methods',revision='1',layer='current',status='effective',modules=['FC'],owner='alice',provenance='source',effective_at=NOW.isoformat(),authority='git',supersedes=[],source=dict(path='note.md',sha256=hashlib.sha256(raw).hexdigest()))])
        data=encoded(index).encode();(folder/'index.json').write_bytes(data)
        route=dict(owner='alice',project='FS',channel='fs',task_types=['report','data'],catalog='knowledge-releases/v1/index.json',sha256=hashlib.sha256(data).hexdigest(),modules=['FC'],baseline_compatibility=dict(mode='retain_full_baseline',sha256='2'*64))
        policy=dict(contract='fs-knowledge-load-policy-v1',task_routes=dict(enabled=True,routes=[route]))
        (self.root/'knowledge-load-policy.json').write_text(encoded(policy),'utf-8')
        body=dict(kind='hermes_report',mode='daily',request_id='knowledge_original_01')
        selected=bridge.prepare_knowledge(self.h,body,'alice')
        self.assertNotIn(raw.decode(),encoded(selected))
        with self.tasks.db() as db:
            db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY)');db.execute('CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT)')
            db.execute('INSERT INTO request_knowledge VALUES(?,?)',('a'*32,selected['version']))
        policy['task_routes']['routes']=[];(self.root/'knowledge-load-policy.json').write_text(encoded(policy),'utf-8')
        restored=bridge.saved_selection(self.h,'a'*32)
        self.assertEqual(restored['release'],'v1')
        knowledge=load('report_knowledge','releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/knowledge.py')
        reader=knowledge.NativeKnowledge(self.root,self.root/'profile',self.root/'approved',receipt_root=self.root/'receipts')
        info=dict(owner='alice',session_id='hc_'+'3'*64,platform='api_server',profile_name='profile')
        pin=reader.pin_fs_task(info,self.task['id'],authorize=lambda scope,task:scope==info and task==self.task['id'],selection=restored)
        self.assertEqual(pin['release'],'v1');self.assertEqual(pin['native_task_id'],self.task['id'])
        with self.assertRaises(PermissionError):reader.pin_fs_task(info,self.task['id'],authorize=lambda *a:False,selection=restored)
    def test_original_submit_execute_native_monitor_and_archive_short_output(self):
        service=self.actual_service();bridge=self.helper()
        self.h.detail=SimpleNamespace(config={'enabled':False},pool=None)
        self.h.diagnostics=lambda:(_ for _ in ()).throw(AssertionError('eager diagnostics'))
        self.h.read_range=lambda *a:(_ for _ in ()).throw(AssertionError('eager business range'))
        with self.tasks.db() as db:
            db.executescript('CREATE TABLE requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT,UNIQUE(owner,request_id));CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT);CREATE TABLE report_trash(id TEXT PRIMARY KEY);CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT,PRIMARY KEY(task_id,evidence_id))')
        body=dict(kind='hermes_report',mode='daily',start='2026-11-04',end='2026-11-04',question='Give the material direction. Short text is enough.',request_id='execute_original_01')
        code,job,_=self.h._submit_report(body,'alice',defer_submit=True)
        calls=[]
        def request(method,path,body=None,idempotency=None,**kwargs):
            calls.append((method,path))
            return (202,dict(run_id='run_'+'e'*32)) if method=='POST' else (200,dict(status='completed',output='Costs rose. Review the margin.'))
        service._request=request
        with patch('zoneinfo.ZoneInfo',return_value=timezone(timedelta(hours=8))):self.h.execute(job['id'],'alice',body)
        result=self.h.get_job('alice',job['id'])
        self.assertEqual(result['state'],'COMPLETED',result.get('error'))
        self.assertEqual(calls,[('POST','/v1/runs'),('GET','/v1/runs/run_'+'e'*32)])
        self.assertEqual(result['result']['research_text'],'Costs rose. Review the margin.')
        with self.tasks.db() as db:
            row=dict(db.execute('SELECT id,task_id FROM requests').fetchone())
        row['native_cid']=bridge.conversation_for(self.h,'alice',row['task_id'],body['request_id'])
        with self.store.db() as db:
            turn=db.execute('SELECT id,task_id FROM turns WHERE conversation_id=?',(row['native_cid'],)).fetchone()
        self.assertEqual(turn['id'],row['task_id']);self.assertEqual(turn['task_id'],row['task_id'])
    def test_original_cancel_fences_native_once_and_stops_after_iam_revocation(self):
        service=self.actual_service();bridge,bound=self.admit()
        with self.tasks.db() as db:db.execute('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT)')
        calls=[]
        service._request=lambda method,path,*a,**k:calls.append((method,path)) or (200,{})
        self.h.authorizer=lambda owner:False
        self.h.cancel_job('alice','a'*32)
        self.h.cancel_job('alice','a'*32)
        self.assertEqual(calls,[('POST','/v1/runs/'+bound['run_id']+'/stop')])
        self.assertEqual(self.native.row('alice',self.cid,bound['turn_id'])['stopped'],1)
        self.assertEqual(self.tasks.get(self.task['id'],'alice')['state'],'CANCEL_REQUESTED')
    def test_cancel_before_original_post_never_dispatches(self):
        service=self.actual_service();bridge,bound=self.prepare()
        with self.tasks.db() as db:db.execute('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT)')
        with self.store.db() as db:db.execute('DELETE FROM native_conversation_runs');db.execute('UPDATE turns SET task_id=NULL,lease=NULL')
        self.tasks.cancel(self.task['id'],'alice');self.h.update('a'*32,state='CANCEL_REQUESTED')
        service._request=lambda *a,**k:(_ for _ in ()).throw(AssertionError('POST after predispatch cancel'))
        self.native.dispatch('alice',self.cid,bound['turn_id'],bound['session_id'],'Why?',bound['request_id'],report_key='a'*32)
        self.assertEqual(self.h.get_job('alice','a'*32)['state'],'CANCELLED')
    def test_cancel_survives_unknown_status_and_original_completed_recovery(self):
        service=self.actual_service();bridge,bound=self.admit();artifacts=self.archive_host()
        calls=[]
        def request(method,path,*args,**kwargs):
            calls.append((method,path))
            return (200,dict(status='completed',output='Original late completion.')) if method=='GET' else (200,{})
        service._request=request
        self.h.cancel_job('alice','a'*32)
        self.assertEqual(self.tasks.get(self.task['id'],'alice')['state'],'CANCEL_REQUESTED')
        service._abandon_task('alice',self.cid,bound['turn_id'],None)
        service._recover('alice',self.cid,bound['turn_id'],bound['run_id'])
        self.assertEqual(self.h.get_job('alice','a'*32)['state'],'CANCELLED')
        self.assertEqual(self.tasks.get(self.task['id'],'alice')['state'],'CANCELLED')
        self.assertFalse((artifacts.directory(self.root,self.task['id'])/'result.json').exists())
        self.assertEqual(calls,[('POST','/v1/runs/'+bound['run_id']+'/stop'),('GET','/v1/runs/'+bound['run_id'])])
    def test_post202_task_bind_failure_recovers_original_run_without_repost(self):
        service=self.actual_service();bridge,bound=self.prepare()
        with self.tasks.db() as db:db.execute('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT)')
        with self.store.db() as db:db.execute('DELETE FROM native_conversation_runs');db.execute('UPDATE turns SET task_id=NULL,lease=NULL')
        calls=[]
        def request(method,path,*a,**k):
            calls.append((method,path));return (202,{'run_id':'run_'+'e'*32}) if path=='/v1/runs' else (200,{})
        service._request=request;bind=self.tasks.bind_run
        with patch.object(self.tasks,'bind_run',side_effect=OSError('final task bind disk failure')):
            with self.assertRaises(OSError):self.native.dispatch('alice',self.cid,bound['turn_id'],bound['session_id'],'Why?',bound['request_id'],report_key='a'*32)
        bridge.abandon(self.native,self.native.row('alice',self.cid,bound['turn_id'])['binding'])
        recovered=[];service._recover=lambda *args:recovered.append(args)
        self.native.reconcile_unknown('alice',self.cid,bound['turn_id'])
        self.assertEqual(self.tasks.get(self.task['id'],'alice')['run_id'],'run_'+'e'*32)
        self.assertEqual(calls,[('POST','/v1/runs'),('POST','/v1/runs/run_'+'e'*32+'/stop')])
        self.assertEqual(len(recovered),1)
    def test_installed_old_positional_writers_remain_usable_after_native_schema_setup(self):
        service=self.actual_service();bridge=self.helper()
        with self.tasks.db() as db:
            db.executescript('CREATE TABLE requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT);CREATE TABLE request_knowledge(id TEXT PRIMARY KEY,version TEXT);CREATE TABLE report_trash(id TEXT PRIMARY KEY)')
        body=dict(kind='hermes_report',mode='daily',start='2026-11-04',end='2026-11-04',question='Why?',request_id='compatibility_original_01')
        self.assertEqual(self.h._submit_report(body,'alice',defer_submit=True)[0],202)
        with self.tasks.db() as db:
            db.execute("INSERT INTO requests VALUES(?,?,?,?,'PREPARING',NULL,NULL,NULL)",('b'*32,'alice','old_original_01','{}'))
            db.execute('INSERT INTO request_knowledge VALUES(?,?)',('b'*32,'old-frozen-version'))
            self.assertEqual(len(list(db.execute('PRAGMA table_info(requests)'))),8)
            self.assertEqual(len(list(db.execute('PRAGMA table_info(request_knowledge)'))),2)
    def test_installed_old_learning_loader_cannot_execute_a_native_attempt(self):
        snapshot=self.helper().prepare_knowledge(self.h,dict(kind='hermes_report',mode='daily',request_id='old_rollback_01'),'alice')
        original=load('old_report_business_context','releases/fs-dashboard/nightly-reschedule-20261025/source/business_context.py')
        with self.assertRaises((KeyError,ValueError)):original.loaded_learning(self.root,snapshot['version'])
    def test_real_actual_profit_service_preserves_missing_cost_and_owner_permission(self):
        bridge,bound=self.admit()
        d='releases/fs-dashboard/dashboard-refresh-20261025/source/'
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:None)}):
            summary=load('actual_live_summary',d+'live_summary.py')
            rs=load('actual_rs_admin','releases/fs-dashboard/rs-adapter-20261024/source/rs_admin.py')
            with patch.dict(sys.modules,{'rs_admin':rs}):
                shipping=load('actual_business_shipping','releases/fs-dashboard/management-november-20261103/source/business_shipping.py')
            channels_module=load('actual_channel_effects',d+'channel_effects.py')
            with patch.dict(sys.modules,{'live_summary':summary,'rs_admin':rs,'channel_effects':channels_module,'business_shipping':shipping}):
                actual=load('actual_original_profit',d+'actual_profit.py')
                rows=actual.normalized([dict(id=5,order_no='FictionalA',gid=506,site_id=266,site={'full_title':'www.mmoexp.com'},amount_usd_format='$ 10',amount_rmb_format='¥ 70',paytime='2026-11-04 12:00:00',status_format='已完成',pay_status=1)],[])
                # Final source read is fictional; selection/cache/authentication
                # and aggregation below are the original service implementations.
                def source(period):return dict(period=period,generatedAt=NOW.isoformat(),orders=rows,sources=dict(orders={'status':'complete'},cost={'status':'complete'}),costOverrides={},testOrders={})
                channels=channels_module.ChannelService(self.root/'actual-finance',lambda owner:owner=='alice',source=source)
                self.addCleanup(lambda:channels.pool.shutdown(wait=True))
                self.h.actual_profits=actual.ActualProfitService(channels,{'RS':(None,'RS','506','506')})
                query=dict(profile='RS',start='2026-11-04',end='2026-11-04',rs_site='mmoexp')
                bridge.finance(self.native,bound,'actual_profit',query)
                channels.pool.shutdown(wait=True)
                result=bridge.finance(self.native,bound,'actual_profit',query)
                self.assertEqual(result['http_status'],200,result)
                self.assertEqual(result['denominator']['missingCostOrders'],1)
                self.assertIsNone(result['denominator']['profitCny'])
                self.assertNotIn('FictionalA',json.dumps(result))
                channels.authorizer=lambda owner:False
                self.assertEqual(bridge.finance(self.native,bound,'actual_profit',query)['http_status'],403)
    def test_short_answer_preserves_raw_without_forced_chapters_html_or_download(self):
        bridge,bound=self.admit();artifacts=self.archive_host()
        from report_delivery import private_report
        self.assertFalse(private_report('Costs rose. Review the margin.'))
        bridge.finish(self.native,bound,'completed','Costs rose. Review the margin.')
        job=self.h.get_job('alice','a'*32)
        self.assertEqual(job['state'],'COMPLETED')
        result=json.loads(artifacts.read_file(self.root,self.task['id'],'json')['content'])
        self.assertEqual(result['research_text'],'Costs rose. Review the margin.')
        self.assertEqual(result['output_format'],'text')
        self.assertEqual(result['html_design']['contract'],'native-original-output-v1')
        self.assertFalse((self.root/'reports'/self.task['id']/'report.html').exists())
        self.assertEqual(list(self.root.glob('conversations/artifacts/**/*')),[])
        bridge.finish(self.native,bound,'completed','Costs rose. Review the margin.')
        self.assertEqual(self.h.get_job('alice','a'*32)['state'],'COMPLETED')
    def test_saved_raw_delivery_retry_never_reruns_research_or_model(self):
        bridge,bound=self.admit();artifacts=self.archive_host()
        publish=self.h.publish_report
        self.h.publish_report=lambda *a:(_ for _ in ()).throw(OSError('final archive write unavailable'))
        bridge.finish(self.native,bound,'completed','An ordinary short answer.')
        self.assertEqual(self.h.get_job('alice','a'*32)['state'],'REPORT_PENDING')
        self.h.publish_report=publish
        self.h.recover_reports()
        self.assertEqual(self.h.get_job('alice','a'*32)['state'],'COMPLETED')
        self.assertEqual(artifacts.read_file(self.root,self.task['id'],'raw')['content'],'An ordinary short answer.')

if __name__=='__main__':unittest.main(verbosity=2)

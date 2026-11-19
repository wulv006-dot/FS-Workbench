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
RP='releases/fs-dashboard/hermes-report-repair-20261019/source'
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
       'releases/fs-dashboard/management-november-20261103/source',
       'releases/fs-dashboard/dashboard-refresh-20261025/source']
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
    def test_report_tool_compact_serialization_preserves_evidence_and_arguments(self):
        register=original_function('releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py','register_report_scope')
        register.__globals__.update(json=json,CUSTOMER_TOOLS={},TOOLS={})
        name='mcp__fcro__fc_query_native_statistics'
        schema=dict(type='function',function=dict(name=name,parameters=dict(type='object')))
        result=dict(evidence_id='frozen-1',source='Admin',timezone='Asia/Shanghai',
            period=dict(start='2026-11-04',end='2026-11-05'),
            data=dict(revenue=dict(value=0,unit='USD',status='available'),
                      cost=dict(value=None,status='missing'),coverage='partial',stale=True),
            authoritative_fact_table=[dict(value=0,value_path='/data/revenue/value',evidence_id='frozen-1')])
        calls=[];installed=[]
        def report_call(tool,args,task):
            calls.append((tool,args,task));return result
        backend=SimpleNamespace(report_call=report_call)
        registry=SimpleNamespace(get_entry=lambda *a,**kw:None,register=lambda **kw:installed.append(kw))
        toolsets=SimpleNamespace(create_custom_toolset=lambda *a,**kw:None,resolve_toolset=lambda *a,**kw:[])
        import conversation_native
        with patch.dict(sys.modules,{'toolsets':toolsets}),patch.object(conversation_native,'current_native_backend',return_value=backend):
            register(registry,'owner-profile',dict(tool_schemas=[schema]))
            args=dict(start='2026-11-04');text=installed[0]['handler'](args,task_id='original-turn')
        self.assertEqual(calls,[(name,args,'original-turn')])
        self.assertEqual(json.loads(text),result)
        self.assertLess(len(text),len(json.dumps(result,ensure_ascii=False,allow_nan=False)))
        self.assertNotIn('unit',json.loads(text)['data']['cost'])

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
        if not path.exists():path=REF/K/'native_reports.py'
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
    def finance_evidence(self,bridge,bound,kind,query):
        from research import ResearchBook
        if not getattr(self.h,'report_books',None):
            book=ResearchBook(dict(snapshot_id=self.spec['snapshot_id'],as_of=NOW.isoformat()),{},dict(start='2026-11-04',end='2026-11-04'))
            self.h.report_books={self.task['id']:book}
        with patch('zoneinfo.ZoneInfo',return_value=timezone(timedelta(hours=8))):
            return bridge.call(self.native,bound,dict(binding=bound,name='mcp__fcro__fc_query_'+kind+'_profit',arguments=query))['data']
    def test_shipping_real_cache_failure_retains_values_with_quality_in_model_evidence(self):
        bridge,bound=self.admit()
        summary=load('finance_summary','releases/fs-dashboard/dashboard-refresh-20261025/source/live_summary.py')
        q=dict(profile='FC27',period=dict(start='2026-11-04 00:00',end='2026-11-05 00:00'),cacheSeconds=600,cachePolicy='historical',profit_basis='shipping')
        cache=summary.SummaryCache(lambda q:self.fail('unexpected read'),lambda q:self.fail('unexpected read'),{'FC27':(None,'FC27')},clock=lambda:1000,shipping_read=lambda q:self.fail('unexpected read'))
        self.addCleanup(cache.close)
        record=dict(status='available',period=q['period'],capturedAt=NOW.isoformat(),currency='CNY',metrics={'profitCny':dict(value=20,unit='CNY')})
        entry={name:dict(state='available',at=1000,valueAt=1000,value=dict(record),phase='available') for name in ('Admin','Order','Shipping')}
        entry['Shipping'].update(state='unavailable',valueAt=390,phase='failed',error='source_read_failed')
        cache.entries[summary.key_of(q)]=entry
        self.h.read_range=lambda params:cache.get_live(q)
        value=self.finance_evidence(bridge,bound,'shipping',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))
        self.assertEqual(value['shipping']['metrics']['profitCny']['value'],20)
        self.assertTrue(value['shipping']['stale']);self.assertEqual(value['shipping']['readPhase'],'failed')
        self.assertEqual(value['source_status']['Shipping']['error'],'source_read_failed')
        self.assertIn('stale',value);self.assertEqual(value['origin'],'live-cache')
        self.assertEqual(value['refreshSeconds'],600);self.assertEqual(value['generatedAt'],NOW.isoformat())
        # Existing archive fallback retains its old values and its expired marker.
        archived=dict(cache.get_live(q)[1],stale=True,refreshing=False,expiresInSeconds=0)
        archived['sources']['Shipping'].update(error='private@example.test /internal/path',raw={'orders':['private']})
        self.h.read_range=lambda params:(200,archived)
        retained=self.finance_evidence(bridge,bound,'shipping',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))
        self.assertTrue(retained['stale']);self.assertEqual(retained['expiresInSeconds'],0)
        self.assertEqual(retained['shipping']['metrics']['profitCny']['value'],20)
        self.assertNotIn('private',json.dumps(retained));self.assertNotIn('/internal',json.dumps(retained))
    def test_actual_real_services_keep_refresh_failures_and_coverage_in_model_evidence(self):
        bridge,bound=self.admit();d='releases/fs-dashboard/dashboard-refresh-20261025/source/'
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:None)}):
            summary=load('quality_summary',d+'live_summary.py')
            rs=load('quality_rs','releases/fs-dashboard/rs-adapter-20261024/source/rs_admin.py')
            with patch.dict(sys.modules,{'rs_admin':rs}):shipping=load('quality_shipping','releases/fs-dashboard/management-november-20261103/source/business_shipping.py')
            channels_module=load('quality_channels',d+'channel_effects.py')
            with patch.dict(sys.modules,{'live_summary':summary,'rs_admin':rs,'channel_effects':channels_module,'business_shipping':shipping}):
                actual=load('quality_actual',d+'actual_profit.py')
                rows=actual.normalized([dict(id=i,order_no='PrivateOrder'+str(i),gid=506,site_id=266,site={'full_title':'www.mmoexp.com'},amount_usd_format='$ 10',amount_rmb_format='70',paytime='2026-11-04 12:00:00',status_format='已完成',pay_status=1) for i in (1,2)],[])
                rows[0]['costCny']=50
                data=dict(period=dict(start='2026-11-04',end='2026-11-04'),generatedAt=NOW.isoformat(),orders=rows,sources=dict(orders=dict(status='complete',generatedAt=NOW.isoformat(),coverage=dict(complete=True,sourceScanned=2,uniqueOrders=2,rawMembership=['PrivateOrder1'])),cost=dict(status='pending',generatedAt=NOW.isoformat())),costOverrides={},testOrders={})
                channels=channels_module.ChannelService(self.root/'quality-finance',lambda owner:owner=='alice',source=lambda p:self.fail('unexpected read'))
                self.addCleanup(lambda:channels.pool.shutdown(wait=True))
                service=actual.ActualProfitService(channels,{'RS':(None,'RS','506','506')})
                self.h.actual_profits=service
                for site in ('mmoexp','all'):
                    query=dict(profile='RS',start='2026-11-04',end='2026-11-04',rs_site=site)
                    params={k:[v] for k,v in query.items()};params.update(mode=['actual-profit'],grain=['day'])
                    q=actual.selection(params,service.profiles)
                    if site=='mmoexp':
                        key=hashlib.sha256((channels_module.VERSION+json.dumps(data['period'],sort_keys=True)).encode()).hexdigest()[:24]
                        target=channels.root/(key+'.json');payload=data;jobs=channels.jobs;starts=channels.starts;clock=channels_module.time.monotonic
                    else:
                        key=hashlib.sha256(json.dumps({k:v for k,v in q.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
                        target=service.root/(key+'.json');payload=dict(data=data,query=q,capturedAt=0);jobs=service.jobs;starts=service.starts;clock=service.clock
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(payload),encoding='utf-8')
                    for state in ('pending','cost_pending','cost_failed','source_failed' if site=='mmoexp' else 'orders_failed'):
                        with self.subTest(site=site,state=state):
                            jobs[key]=state;starts[key]=clock()
                            value=self.finance_evidence(bridge,bound,'actual',query)
                            self.assertEqual(value['status'],'available');self.assertTrue(value['stale'])
                            self.assertEqual(value['refreshing'],state in ('pending','cost_pending'))
                            self.assertEqual(value['costRefreshing'],state=='cost_pending')
                            self.assertEqual(value['costError'],state=='cost_failed')
                            self.assertEqual(value['sourceError'],state in ('source_failed','orders_failed'))
                            self.assertEqual(value['denominator']['profitCny'],20)
                            self.assertEqual(value['denominator']['missingCostOrders'],1)
                            self.assertEqual(value['sources']['cost']['status'],'pending')
                            self.assertTrue(value['sources']['orders']['coverage']['complete'])
                            self.assertNotIn('PrivateOrder',json.dumps(value));self.assertNotIn('rawMembership',json.dumps(value))
    def test_actual_profit_uses_original_authenticated_service_and_projects_only_aggregates(self):
        bridge,bound=self.admit()
        seen=[]
        class ExistingService:
            def get(_,params,owner):
                seen.append((params,owner))
                return 200,dict(status='partial',actualContract='same-order-actual-profit-v1',currency='CNY',error={'detail':'do-not-leak'},
                    denominator=dict(profitCny=20,missingCostOrders=3,coverageStatus='partial',email='do-not-leak'),
                    trend=[dict(key='2026-11-04',profitCny=20,orderNo='do-not-leak')],orders=[{'email':'do-not-leak'}],rawMembership=['do-not-leak'])
        self.h.actual_profits=ExistingService()
        result=bridge.finance(self.native,bound,'actual_profit',dict(profile='FC27',start='2026-11-04',end='2026-11-04'))
        self.assertEqual(seen[0][1],'alice');self.assertEqual(seen[0][0]['mode'],['actual-profit'])
        self.assertEqual(result['denominator']['missingCostOrders'],3)
        self.assertEqual(result['error'],'source_read_failed')
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
        # Resolve the verified runtime continuation source, independently of sys.path.
        sys.modules['continuation']=load('continuation',RP+'/continuation.py')
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
        calls=[];ready=[];admissions=[]
        admission_writer=self.native.write_admission
        def write_admission(sid,item):
            admissions.append(json.loads(json.dumps(item)))
            return admission_writer(sid,item)
        self.native.write_admission=write_admission
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
        self.assertEqual(admissions[-1]['model'],'gpt-6.2-sol')
        gateway=self.h.gateways[self.task['id']]
        self.assertEqual(gateway.budget.policy['model'],'gpt-6.2-sol')
        self.assertEqual(gateway.budget.policy['id'],'openai-sol-responses-tokens-only-v1')
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

    def active_continuation(self):
        research=load('runtime_research',F+'/research.py')
        with patch.dict(sys.modules,{'research':research}):
            module=load('runtime_continuation',RP+'/continuation.py')
        expected=HERE/RP/'continuation.py'
        if not expected.exists():expected=REF/RP/'continuation.py'
        self.assertEqual(Path(module.__file__),expected)
        self.assertEqual(module.ResearchBook,research.ResearchBook)
        return module

    def continuation_fixture(self,completed=False,legacy=False):
        self.prepare()
        module=self.active_continuation()
        book=module.ResearchBook(dict(snapshot_id=self.spec['snapshot_id'],as_of=NOW.isoformat()),{},
                          dict(start='2026-11-04',end='2026-11-04'))
        book.register('fc.get_data_catalog',{},dict(main_source='Admin'),'Admin FC支付明细')
        version='legacy-version' if legacy else self.spec['knowledge_version']
        spec=dict(self.spec,knowledge_version=version)
        with self.tasks.db() as db:
            db.executescript('CREATE TABLE evidence(task_id TEXT,evidence_id TEXT,content TEXT);CREATE TABLE report_trash(id TEXT PRIMARY KEY)')
            db.execute('UPDATE tasks SET state=?,spec=? WHERE id=?',('SUCCEEDED' if completed else 'FAILED',encoded(spec),self.task['id']))
            db.execute('UPDATE requests SET state=?,error=?',('COMPLETED' if completed else 'FAILED',None if completed else 'provider_outcome_unknown'))
            for ref,value in book.evidence.items():db.execute('INSERT INTO evidence VALUES(?,?,?)',(self.task['id'],ref,encoded(value)))
            if legacy:db.execute('DELETE FROM request_knowledge')
        if completed:
            artifacts=load('report_artifacts',W+'/report_artifacts.py')
            artifacts.save_raw(self.root,self.task['id'],'Original answer.',book.evidence,dict(native_report=True))
            artifacts.save_result(self.root,self.task['id'],dict(native_report=True,output_format='text',research_text='Original answer.'),'')
            module_patch=patch.dict(sys.modules,{'report_artifacts':artifacts})
            module_patch.start();self.addCleanup(module_patch.stop)
        return module,book.evidence

    def test_active_continuation_uses_native_metadata_without_skill_preload(self):
        module,evidence=self.continuation_fixture()
        supplied=dict(version='current-native-selection',sha256='saved-selection-reference')
        with patch.object(module,'load_bundle',side_effect=AssertionError('full Skill preload')):
            for metadata in (supplied,None):
                with self.subTest(explicit_metadata=metadata is not None):
                    book=module.load_continuation(self.tasks,'a'*32,'alice','2026-11-04','2026-11-04',self.root,skills=metadata)
                    self.assertEqual(book.evidence,evidence)
                    self.assertEqual(book.skills['version'],supplied['version'] if metadata else self.spec['knowledge_version'])

    def test_active_followup_uses_native_metadata_and_preserves_evidence_hash(self):
        module,evidence=self.continuation_fixture(completed=True)
        supplied=dict(version='current-native-selection',sha256='saved-selection-reference')
        with patch.object(module,'load_bundle',side_effect=AssertionError('full Skill preload')):
            for metadata in (supplied,None):
                with self.subTest(explicit_metadata=metadata is not None):
                    book=module.load_report_followup(self.tasks,'a'*32,'2026-11-04','2026-11-04',self.root,self.root,skills=metadata)
                    self.assertEqual(book.evidence,evidence)
                    self.assertEqual(json.loads(book.continuation_context)['original_report'],'Original answer.')
            path=self.root/'reports'/self.task['id']/'evidence.json'
            path.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'followup_evidence_changed'):
                module.load_report_followup(self.tasks,'a'*32,'2026-11-04','2026-11-04',self.root,self.root,skills=supplied)

    def test_active_legacy_continuation_keeps_owner_period_state_and_version_checks(self):
        module,evidence=self.continuation_fixture(legacy=True)
        with patch.object(module,'load_bundle',return_value=dict(version='incompatible')) as bundle:
            with self.assertRaisesRegex(PermissionError,'continuation_owner_or_state'):
                module.load_continuation(self.tasks,'a'*32,'bob','2026-11-04','2026-11-04',self.root)
            with self.assertRaisesRegex(ValueError,'continuation_period'):
                module.load_continuation(self.tasks,'a'*32,'alice','2026-11-03','2026-11-04',self.root)
            self.assertEqual(bundle.call_count,0)
            with self.assertRaisesRegex(ValueError,'continuation_skill_mismatch'):
                module.load_continuation(self.tasks,'a'*32,'alice','2026-11-04','2026-11-04',self.root)
            bundle.return_value=dict(version='legacy-version',sha256='original-bundle')
            self.assertEqual(module.load_continuation(self.tasks,'a'*32,'alice','2026-11-04','2026-11-04',self.root).evidence,evidence)
            with self.tasks.db() as db:db.execute("UPDATE tasks SET state='RUNNING'")
            with self.assertRaisesRegex(ValueError,'continuation_runtime_unsettled'):
                module.load_continuation(self.tasks,'a'*32,'alice','2026-11-04','2026-11-04',self.root)

    def test_active_legacy_followup_keeps_period_version_and_trash_checks(self):
        module,evidence=self.continuation_fixture(completed=True,legacy=True)
        with patch.object(module,'load_bundle',return_value=dict(version='incompatible')) as bundle:
            with self.assertRaisesRegex(ValueError,'followup_period'):
                module.load_report_followup(self.tasks,'a'*32,'2026-11-03','2026-11-04',self.root,self.root)
            self.assertEqual(bundle.call_count,0)
            with self.assertRaisesRegex(ValueError,'followup_skill_mismatch'):
                module.load_report_followup(self.tasks,'a'*32,'2026-11-04','2026-11-04',self.root,self.root)
            bundle.return_value=dict(version='legacy-version',sha256='original-bundle')
            self.assertEqual(module.load_report_followup(self.tasks,'a'*32,'2026-11-04','2026-11-04',self.root,self.root).evidence,evidence)
            with self.tasks.db() as db:db.execute('INSERT INTO report_trash VALUES(?)',('a'*32,))
            with self.assertRaisesRegex(PermissionError,'followup_source_unavailable'):
                module.load_report_followup(self.tasks,'a'*32,'2026-11-04','2026-11-04',self.root,self.root)

    def frozen_record(self,source,query,data,project='FC27',anchor=None,captured_at=None):
        anchor=anchor or self.spec['snapshot_id']
        value=dict(source=source,query=query,data=data,project=project,snapshot_id=anchor,
                   analysis_anchor_id=anchor,captured_at=captured_at or NOW.isoformat())
        value['evidence_id']='ev_'+hashlib.sha256(encoded(value).encode()).hexdigest()[:24]
        return value

    def test_active_continuation_preserves_management_nonfc_and_connected_purchase_evidence(self):
        module=self.active_continuation()
        with patch.dict(sys.modules,{'fcntl':types.SimpleNamespace()}):
            management=load('runtime_management',RP+'/management_context.py')
        anchor='management-'+'d'*24
        facts=dict(snapshotId=anchor,generatedAt=NOW.isoformat(),projects=[])
        context=self.frozen_record('FS 经营管理台已冻结的全项目汇总；Admin 主站 + 显式 Order 参考',{},facts,'ALL_MANAGEMENT_PROJECTS',anchor)
        native_query=dict(profile='D4',start='2026-11-04',end='2026-11-04')
        native=self.frozen_record('Admin原生统计优先、Order补缺；管理台按已登记profile补查',native_query,dict(status='available',total=9),'D4',anchor)
        connected=self.frozen_record('FS购买客户事实的冻结聚合',dict(kind='retention'),dict(status='available',customers=3),'CONNECTED_PURCHASE_CUSTOMERS',anchor)
        original=management.ManagementBook(facts,dict(start='2026-11-04',end='2026-11-04'))
        finance=[]
        for kind,name in (('shipping','shipping_profit'),('actual_profit','actual_profit')):
            finance.append(original.register('fc.query_'+name,native_query,dict(status='partial',profitCny=10),source='FS report '+kind+' aggregate'))
        self.assertEqual({v['project'] for v in finance},{'ALL_MANAGEMENT_PROJECTS'})
        records={v['evidence_id']:v for v in (context,native,connected,*finance)}
        task=dict(spec=dict(self.spec,snapshot_id=anchor),request_id='a'*32,end='2026-11-04')
        with patch.dict(sys.modules,{'management_context':management}):
            book=module.FrozenEvidenceBook(task,records,dict(version='native'))
        self.assertEqual(book.facts,facts)
        self.assertEqual(book.call('fc.query_native_statistics',native_query),native)
        self.assertEqual(book.call('fc.query_user_analytics',dict(kind='retention')),connected)
        for name,record in zip(('shipping_profit','actual_profit'),finance):
            self.assertEqual(book.call('fc.query_'+name,native_query),record)
        self.assertEqual(book.call('fc.read_evidence',dict(evidence_id=native['evidence_id'],path='/data/total'))['value'],9)
        self.assertEqual(book.call('fc.check_report_html',dict(html='<!doctype html><html><body>report</body></html>'))['issue_count'],0)
        with self.assertRaises(PermissionError):book.call('fc.read_evidence',dict(evidence_id='ev_'+'f'*24))
        for bad in (dict(native,project='UNRELATED'),dict(native,analysis_anchor_id='management-'+'f'*24)):
            invalid=dict(records);invalid[native['evidence_id']]=bad
            with self.subTest(invalid_scope=bad),patch.dict(sys.modules,{'management_context':management}),self.assertRaises(ValueError):
                module.FrozenEvidenceBook(task,invalid,dict(version='native'))

    def test_active_continuation_keeps_terminal_cache_rank_query_and_deepcopy(self):
        module=self.active_continuation()
        query=dict(start='2026-11-04',end='2026-11-04',group_by=[],filters={},page=1)
        complete=self.frozen_record('Admin FC支付明细',query,dict(status='available',orders=5),captured_at='2026-11-04T00:00:00+00:00')
        pending=self.frozen_record('Admin FC支付明细',query,dict(status='pending'),captured_at='2026-11-05T00:00:00+00:00')
        newer=self.frozen_record('Admin FC支付明细',query,dict(status='available',orders=8),captured_at='2026-11-06T00:00:00+00:00')
        task=dict(spec=self.spec,request_id='a'*32,end='2026-11-04')
        book=module.FrozenEvidenceBook(task,{v['evidence_id']:v for v in (newer,pending,complete)},dict(version='native'))
        value=book.query(query)
        self.assertEqual(value,newer)
        value['data']['orders']=100
        self.assertEqual(book.query(query)['data']['orders'],8)
        self.assertEqual(book.trace[-1]['basis'],'cached_original_source_evidence')

    def test_active_continuation_finance_aliases_reuse_frozen_values_and_missing_reads_stay_frozen(self):
        module=self.active_continuation()
        query=dict(profile='FC27',start='2026-11-04',end='2026-11-04')
        records=[self.frozen_record('FS report '+kind+' aggregate',query,dict(status='partial',profitCny=10)) for kind in ('shipping','actual_profit')]
        task=dict(spec=self.spec,request_id='a'*32,end='2026-11-04')
        book=module.FrozenEvidenceBook(task,{v['evidence_id']:v for v in records},dict(version='native'))
        for kind,record in zip(('shipping_profit','actual_profit'),records):
            with self.subTest(kind=kind):
                self.assertEqual(book.call('fc.query_'+kind,query),record)
                missing=book.call('fc.query_'+kind,dict(query,profile='D4'))
                self.assertEqual(missing['data']['status'],'not_available')
                self.assertFalse(missing['data']['new_source_reads'])
        resumed=module.FrozenEvidenceBook(task,book.evidence,dict(version='native'))
        self.assertEqual(resumed.call('fc.query_shipping_profit',dict(query,profile='D4'))['data']['status'],'not_available')

if __name__=='__main__':unittest.main(verbosity=2)

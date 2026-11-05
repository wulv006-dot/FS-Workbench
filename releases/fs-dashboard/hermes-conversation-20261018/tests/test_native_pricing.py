"""Pricing native boundaries use actual SQLite stores and original host functions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import threading
import unittest
import sys
HERE=Path(__file__).resolve().parents[1]
RELEASES=HERE.parents[1]
sys.path[:0]=[str(RELEASES/'fc-coins/fc-pricing-v3-20261026/source'),
              str(RELEASES/'fc-coins/fc-review-channel-20261026/source'),
              str(HERE.parent/'hermes-v2-core-20261020/source'),
              str(HERE.parent/'hermes-fc-pilot-20261013'),
              str(HERE.parent/'hermes-admin-recovery-20261020/source')]
sys.path.append(str(RELEASES/'fs-dashboard/fc-daily-20261013/source'))
from unittest.mock import patch

from conversation_store import ConversationStore
from conversation_native import NativeConversation, canonical
from pilot import TaskStore
import pricing_operations as operations

NOW=datetime(2026,11,5,tzinfo=timezone.utc)
SOURCE='human_authorized_fc_pricing_v3_daily_effect_review_readonly'

class NativePricingBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.tasks=TaskStore(self.root/'tasks.sqlite3')
        self.hermes=SimpleNamespace(root=self.root,tasks=self.tasks,authorizer=lambda u:u=='alice',clock=lambda:NOW)
    def native(self,name):
        service=SimpleNamespace(store=ConversationStore(self.root/name),hermes=self.hermes,lock=threading.RLock(),run_root=self.root/'run')
        return NativeConversation(service)
    def context(self,cid):
        return dict(conversation=cid,mode='daily_review',runs=['00000000-0000-4000-8000-000000000001'],
                    expires_at=(NOW+timedelta(hours=2)).isoformat(),source=SOURCE,
                    source_quote_run='00000000-0000-4000-8000-000000000002',source_quote_sha256='a'*64)
    def bind(self,native,pricing=True):
        store=native.store;cid=store.create('alice')['conversation_id']
        turn=store.reserve_turn('alice',cid,'review','pricing_native_01',native=True)
        binding=dict(owner='alice',conversation_id=cid,turn_id=turn['turn_id'],request_id='pricing_native_01',session_id=turn['session_id'],lease='c'*32,run_id='run_'+'d'*32)
        store.bind_task('alice',cid,turn['turn_id'],turn['turn_id'],binding['lease']);store.bind_run('alice',cid,turn['turn_id'],binding['run_id'])
        context=self.context(cid) if pricing else None
        with self.tasks.db() as db:
            operations.tables(db)
            if pricing:operations.grant(db,'alice',cid,context['runs'][0],context['mode'],context['expires_at'],context['source'],source_quote_run=context['source_quote_run'],source_quote_sha256=context['source_quote_sha256'])
        with store.db() as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(native_conversation_runs)')}
            self.assertIn('pricing_context',columns,'Native rows must persist nullable host-derived pricing context')
            db.execute('INSERT INTO native_conversation_runs(turn_id,binding,body,idempotency_key,fingerprint,pricing_context) VALUES(?,?,?,?,?,?)',(turn['turn_id'],canonical(binding),'{}','hn-'+turn['turn_id']*2,'f'*64,canonical(context) if context else None))
        return binding,context
    def test_two_native_stores_and_legacy_are_in_the_original_union(self):
        general=self.native('conversations');pricing=self.native('pricing-reviews')
        one,_=self.bind(general,False);two,_=self.bind(pricing)
        with self.tasks.db() as db:db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,0,?,?,0,0)',('legacy','alice','legacy-fingerprint','{}','RUNNING','run_'+'e'*32,'f'*32))
        from fs_inprocess import active_model_tasks
        self.assertEqual(active_model_tasks(self.tasks),{('alice','legacy'),('alice',one['turn_id']),('alice',two['turn_id'])})
        self.native('conversations');self.native('pricing-reviews')
        self.assertEqual(active_model_tasks(self.tasks),{('alice','legacy'),('alice',one['turn_id']),('alice',two['turn_id'])})
        with general.store.db() as db:db.execute("UPDATE native_conversation_runs SET binding='{}'")
        with self.assertRaises((ValueError,PermissionError,KeyError)):active_model_tasks(self.tasks)
    def test_liveness_registration_refuses_recursive_union_callback(self):
        native=self.native('conversations')
        self.tasks._native_active_model_tasks=native.active_tasks
        with self.assertRaisesRegex(RuntimeError,'native_liveness_store_conflict'):
            self.native('pricing-reviews')

    def test_pricing_checks_current_iam_binding_lease_stopped_expiry_and_entire_grant(self):
        native=self.native('pricing-reviews');bound,ctx=self.bind(native)
        self.assertTrue(native.authorized(bound))
        for column,value in [('mode','operator_workflow'),('runs','[]'),('source','changed'),('source_quote_run','00000000-0000-4000-8000-000000000003'),('source_quote_sha256','b'*64),('expires_at',(NOW+timedelta(hours=3)).isoformat()),('expires_at',(NOW-timedelta(seconds=1)).isoformat())]:
            with self.subTest(column=column,value=value):
                table='pricing_grant_sources' if column.startswith('source_quote_') else 'pricing_grants'
                with self.tasks.db() as db:old=db.execute('SELECT '+column+' FROM '+table).fetchone()[0];db.execute('UPDATE '+table+' SET '+column+'=?',(value,))
                self.assertFalse(native.authorized(bound))
                with self.tasks.db() as db:db.execute('UPDATE '+table+' SET '+column+'=?',(old,))
        for field in ('owner','conversation_id','turn_id','lease','run_id','session_id','request_id'):
            bad=dict(bound,**{field:'bad'})
            try:allowed=native.authorized(bad)
            except (LookupError,PermissionError,ValueError):allowed=False
            self.assertFalse(allowed)
        self.hermes.authorizer=lambda u:False;self.assertFalse(native.authorized(bound));self.hermes.authorizer=lambda u:True
        with self.tasks.db() as db:db.execute('DELETE FROM pricing_grants')
        self.assertFalse(native.authorized(bound))
    def test_capabilities_comes_from_original_schema_and_all_writes_stay_denied(self):
        native=self.native('pricing-reviews');bound,ctx=self.bind(native)
        call=lambda args:native.host_tool(bound,'fs.native.pricing',dict(binding=bound,arguments=args))
        result=call({'action':'capabilities'})
        expected=operations.schema();expected['function']['parameters']['properties']['action']['enum']=result['allowed_actions']
        self.assertEqual(result['tool_schema'],expected)
        for action in operations.MUTATING:
            args={field:'test' for field in operations.FIELDS[action]};args['action']=action
            with self.subTest(action=action),self.assertRaises(PermissionError):call(args)
        for name in ('fs_track_customer','fs_create_coupon','fs_list_customer_goals'):
            with self.subTest(name=name),self.assertRaises(PermissionError):native.host_tool(bound,'fs.native.user_data',dict(binding=bound,name=name,arguments={}))
        with native.store.db() as db:db.execute('UPDATE native_conversation_runs SET stopped=1')
        with self.assertRaises(PermissionError):call({'action':'capabilities'})
    def test_general_does_not_gain_pricing_rpc_and_nullable_legacy_row_stays_general(self):
        native=self.native('conversations');bound,_=self.bind(native,False)
        self.assertTrue(native.authorized(bound))
        with self.assertRaises(PermissionError):native.host_tool(bound,'fs.native.pricing',dict(binding=bound,arguments={'action':'capabilities'}))
    def test_saved_compare_uses_original_http_get_and_grant_race_cannot_evaluate(self):
        native=self.native('pricing-reviews');bound,ctx=self.bind(native)
        calls=[]
        def request(path,owner,body=None):
            calls.append((path,owner,body))
            return dict(snapshot_id=ctx['source_quote_run'],snapshot_sha256=ctx['source_quote_sha256'],results={'daily':{'status':'saved'}})
        payload=dict(binding=bound,arguments={'action':'compare_strategies','mode':'daily'})
        with patch.object(operations,'native',side_effect=request):
            result=native.host_tool(bound,'fs.native.pricing',payload)
            self.assertEqual(result['results'],{'daily':{'status':'saved'}})
            self.assertEqual(calls,[('/pricing/v3/strategy-decisions/'+ctx['source_quote_run'],'alice',None)])
            original=operations.authorization
            def race(scope,owner,task,now):
                with self.tasks.db() as db:db.execute('DELETE FROM pricing_grants')
                return original(scope,owner,task,now)
            with patch.object(operations,'authorization',side_effect=race),self.assertRaises(PermissionError):
                native.host_tool(bound,'fs.native.pricing',payload)
            self.assertEqual(len(calls),1)

    def test_admission_preserves_seven_field_binding_and_validates_optional_pricing(self):
        from conversation_native import validate_native_admission, execution_workspace, NATIVE_ROOT, sha
        native=self.native('pricing-reviews');bound,ctx=self.bind(native)
        item=dict(session_id=bound['session_id'],run_id=bound['run_id'],ready=True,reasoning_effort='high',
                  native_chat=dict(binding=bound,pricing=ctx,key='hn-'+'e'*64,fingerprint='f'*64,
                                   environment=dict(profile=NATIVE_ROOT+'/profiles/'+sha(bound['owner'].encode()),
                                                    workspace=execution_workspace(bound),files=[])))
        self.assertEqual(validate_native_admission(item),bound)
        self.assertEqual(len(bound),7)
        for change in (dict(ctx,extra=True),dict(ctx,conversation='b'*32),dict(ctx,mode='automatic_review'),
                       dict(ctx,source_quote_run=None),dict(ctx,runs='invalid')):
            bad=deepcopy(item);bad['native_chat']['pricing']=change
            with self.subTest(context=change),self.assertRaises(PermissionError):validate_native_admission(bad)
        bad=deepcopy(item);bad['reasoning_effort']='none'
        with self.assertRaises(PermissionError):validate_native_admission(bad)
        general=deepcopy(item);general['native_chat'].pop('pricing');general.pop('reasoning_effort')
        self.assertEqual(validate_native_admission(general),bound)

    def test_backend_rechecks_around_original_pricing_rpc(self):
        from conversation_native import NativeDockerBackend
        backend=object.__new__(NativeDockerBackend);backend.binding={'turn_id':'turn'};active=[True];calls=[]
        backend.authorize=lambda:active[0]
        def rpc(args):calls.append(args);active[0]=False;return {'result':'discard'}
        backend.pricing_rpc=rpc
        with self.assertRaises(PermissionError):backend.pricing_call({'action':'capabilities'})
        self.assertEqual(calls,[{'action':'capabilities'}])


class NativePricingService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_conversation_native import NativeDispatchTests
        from test_conversation_file_loop import load
        cls.fixtures=NativeDispatchTests
        paths=list(sys.path)
        cls.fixtures.setUpClass()
        sys.path[:]=paths
        # Use the exact current installed-source roles, regardless of legacy
        # test module import order. P1 transport requires the matching proxy.
        review=RELEASES/'fc-coins/fc-review-channel-20261026/source'
        core=HERE.parent/'hermes-v2-core-20261020/source'
        cls.proxy=load('native_pricing_current_proxy',review/'proxy_gateway.py')
        cls.daily_reports=load('native_pricing_current_daily',HERE.parent/'hermes-admin-recovery-20261020/source/fc_daily.py')
        with patch.dict(sys.modules,{'proxy_gateway':cls.proxy,'fc_daily':cls.daily_reports}):
            cls.transport=load('native_pricing_current_transport',core/'transport.py')
            cls.inprocess=load('native_pricing_current_inprocess',review/'fs_inprocess.py')
    def test_real_service_daily_dispatch_keeps_pool_grant_store_and_high(self):
        DailyReports=self.daily_reports.DailyReports
        Grants=self.transport.Grants
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tasks=TaskStore(root/'tasks.sqlite3')
            modules=dict(self.fixtures.modules,fs_inprocess=self.inprocess,proxy_gateway=self.proxy,transport=self.transport,fc_daily=self.daily_reports)
            with patch.dict(__import__('sys').modules,modules):
                fixture=self.fixtures();service,_=fixture.fixture(root,tasks)
                service.hermes.clock=lambda:datetime.now(timezone.utc)
                service.hermes.grants=Grants();service.hermes.daily=DailyReports(None,root/'daily')
                pricing=service.pricing
                self.assertIsNotNone(pricing.native,'Existing pricing store must construct native before recovery')
                self.assertIs(pricing.pricing_pool,pricing.pool)
                self.assertIsNot(service.pool,service.pricing_pool)
                pending=[];pricing.pricing_pool=pricing.pool=SimpleNamespace(submit=lambda *a:pending.append(a))
                pricing._monitor=lambda *args:None
                cid=pricing.store.create('alice')['conversation_id']
                expires=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
                daily='00000000-0000-4000-8000-000000000001'
                with tasks.db() as db:operations.grant(db,'alice',cid,daily,'daily_review',expires,SOURCE)
                posts=[]
                def request(method,path,body=None,key=None):
                    posts.append((method,path,body,key));return 202,{'run_id':'run_'+'a'*32}
                pricing._request=request
                result=pricing.submit_pricing('alice',cid,'review daily','pricing_dispatch_01',daily)
                self.assertEqual(len(pending),1)
                fn,*args=pending.pop();fn(*args)
                row=pricing.native.row('alice',cid,result['turn_id']);bound=row['binding']
                self.assertEqual(bound['turn_id'],pricing.store.task_binding('alice',cid,bound['turn_id'])[0])
                self.assertEqual(row['pricing_context']['runs'],[daily])
                self.assertEqual(len(posts),1);self.assertEqual(posts[0][:2],('POST','/v1/runs'))
                admission=self.fixtures.admissions[-1]
                self.assertEqual(admission['native_chat']['pricing'],row['pricing_context'])
                self.assertEqual(admission['reasoning_effort'],'high')
                self.assertEqual(service.hermes.grants.resolve(admission['token']).reasoning_effort,'high')
                gateway=service.hermes.gateways[bound['turn_id']]
                with gateway.slot() as acquired:self.assertTrue(acquired)
                self.assertTrue((service.hermes.daily.root/'pricing-review/provider.lock').exists())
                self.assertFalse((service.hermes.daily.root/'provider.lock').exists())
                with tasks.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)
                reused=pricing.submit_pricing('alice',cid,'review daily','pricing_dispatch_01',daily)
                self.assertTrue(reused['reused']);self.assertEqual(len(posts),1);self.assertEqual(pending,[])
                measured=dict(binding=bound,model_schemas=[],catalog_sha256='e'*64,registry_generation=1,reasoning_effort='none')
                with self.assertRaises(PermissionError):pricing.native.register_schemas(bound,measured)
                measured['reasoning_effort']='high';pricing.native.register_schemas(bound,measured)
                self.assertEqual(pricing.native.reasoning_effort(bound),'high')
                with tasks.db() as db:db.execute('UPDATE pricing_grants SET expires_at=? WHERE conversation=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),cid))
                with self.assertRaises(PermissionError):pricing._dispatch('alice',cid,bound['turn_id'],bound['session_id'],'review daily','pricing_dispatch_01',True)
                self.assertEqual(pricing.store.detail('alice',cid)['turns'][0]['state'],'queued')
                self.assertFalse(pricing.native.row('alice',cid,bound['turn_id'])['stopped'])
                self.assertEqual(len(posts),1)
                with tasks.db() as db:db.execute('UPDATE pricing_grants SET expires_at=? WHERE conversation=?',(expires,cid))
                pricing.store.set_state('alice',cid,bound['turn_id'],'completed')
                pricing._finish_task('alice',cid,bound['turn_id'],pricing.live[bound['turn_id']],'completed')
                self.assertTrue(pricing.native.row('alice',cid,bound['turn_id'])['stopped'])
                with self.assertRaises(PermissionError):service.hermes.grants.resolve(admission['token'])
                self.assertNotIn(cid,[item['conversation_id'] for item in service.store.listed('alice')['items']])
    def test_expired_grant_before_post_finishes_reserved_turn_without_blocking_next(self):
        for expire_on in (1,2,3):
            with self.subTest(expire_on=expire_on),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);tasks=TaskStore(root/'tasks.sqlite3')
                modules=dict(self.fixtures.modules,fs_inprocess=self.inprocess,proxy_gateway=self.proxy,transport=self.transport,fc_daily=self.daily_reports)
                with patch.dict(sys.modules,modules):
                    fixture=self.fixtures();service,_=fixture.fixture(root,tasks)
                    service.hermes.clock=lambda:datetime.now(timezone.utc)
                    service.hermes.grants=self.transport.Grants()
                    service.hermes.daily=self.daily_reports.DailyReports(None,root/'daily')
                    pricing=service.pricing;pending=[];posts=[]
                    pricing.pricing_pool=pricing.pool=SimpleNamespace(submit=lambda *a:pending.append(a))
                    pricing._request=lambda *a:posts.append(a)
                    cid=pricing.store.create('alice')['conversation_id']
                    daily='00000000-0000-4000-8000-000000000001'
                    with tasks.db() as db:operations.grant(db,'alice',cid,daily,'daily_review',(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),SOURCE)
                    result=pricing.submit_pricing('alice',cid,'review daily','pricing_expiry_01',daily)
                    original=pricing.native.pricing_context;calls=[]
                    def expire(*args):
                        calls.append(True)
                        if len(calls)==expire_on:
                            with tasks.db() as db:db.execute('UPDATE pricing_grants SET expires_at=? WHERE conversation=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),cid))
                        return original(*args)
                    with patch.object(pricing.native,'pricing_context',side_effect=expire):
                        fn,*args=pending.pop()
                        with self.assertRaises(PermissionError):fn(*args)
                    self.assertEqual(posts,[])
                    turn=pricing.store.detail('alice',cid)['turns'][0]
                    self.assertEqual(turn['state'],'failed')
                    self.assertIsNone(turn['run_id'])
                    self.assertEqual(pricing.live,{})
                    with tasks.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)
                    row=pricing.native.row('alice',cid,result['turn_id'])
                    if row is not None:self.assertTrue(row['stopped'])
                    next_turn=pricing.store.reserve_turn('alice',cid,'later request','pricing_expiry_02',native=True)
                    self.assertEqual(next_turn['state'],'preparing')

    def test_real_gateway_rejects_pricing_lane_without_current_host_context(self):
        DailyReports=self.daily_reports.DailyReports
        from native_chat import NativeChatScope
        with tempfile.TemporaryDirectory() as temp,patch.dict(sys.modules,{'proxy_gateway':self.proxy,'transport':self.transport,'fc_daily':self.daily_reports}):
            daily=DailyReports(None,Path(temp)/'daily')
            binding=dict(owner='alice',conversation_id='a'*32,turn_id='b'*32,request_id='pricing_lane_test',session_id='s',lease='c'*32,run_id='run_'+'d'*32)
            scope=NativeChatScope(binding,lambda:True,model_schemas=lambda:[])
            with self.assertRaises((ValueError,PermissionError)):
                self.inprocess.native_gateway(daily,scope,active_tasks=lambda:set(),provider_lane='pricing')
            ctx=dict(conversation=binding['conversation_id'],mode='daily_review',runs=['00000000-0000-4000-8000-000000000001'],expires_at=(NOW+timedelta(hours=1)).isoformat(),source=SOURCE,source_quote_run=None,source_quote_sha256=None)
            active=[True]
            scope=NativeChatScope(binding,lambda:active[0],model_schemas=lambda:[],pricing_context=ctx)
            gateway=self.inprocess.native_gateway(daily,scope,active_tasks=lambda:{('alice',binding['turn_id'])},provider_lane='pricing')
            with gateway.slot() as acquired:self.assertTrue(acquired)
            self.assertTrue((daily.root/'pricing-review/provider.lock').exists())
            active[0]=False
            with self.assertRaises(PermissionError):self.inprocess.native_gateway(daily,scope,active_tasks=lambda:set(),provider_lane='pricing')

    def test_pricing_lost_202_keeps_original_key_and_never_reposts(self):
        DailyReports=self.daily_reports.DailyReports
        Grants=self.transport.Grants
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tasks=TaskStore(root/'tasks.sqlite3')
            modules=dict(self.fixtures.modules,fs_inprocess=self.inprocess,proxy_gateway=self.proxy,transport=self.transport,fc_daily=self.daily_reports)
            with patch.dict(sys.modules,modules):
                service,_=self.fixtures().fixture(root,tasks)
                service.hermes.clock=lambda:datetime.now(timezone.utc)
                service.hermes.grants=Grants();service.hermes.daily=DailyReports(None,root/'daily')
                pricing=service.pricing;pending=[]
                pricing.pricing_pool=pricing.pool=SimpleNamespace(submit=lambda *args:pending.append(args))
                cid=pricing.store.create('alice')['conversation_id'];daily='00000000-0000-4000-8000-000000000001'
                with tasks.db() as db:operations.grant(db,'alice',cid,daily,'daily_review',(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),SOURCE)
                posts=[]
                def timeout(method,path,body=None,key=None):
                    posts.append((method,path,body,key));raise TimeoutError('lost original 202')
                pricing._request=timeout
                item=pricing.submit_pricing('alice',cid,'review daily','pricing_lost_202_01',daily)
                fn,*args=pending.pop()
                with self.assertRaises(TimeoutError):fn(*args)
                row=pricing.native.row('alice',cid,item['turn_id']);self.assertTrue(row['stopped'])
                original_key=row['idempotency_key'];original_binding=deepcopy(row['binding'])
                fn(*args)
                self.assertEqual(len(posts),1)
                found=[]
                def lookup(method,path,body=None,key=None):
                    found.append((method,path));return 200,{'status':'unknown','session_id':original_binding['session_id'],'run_id':None}
                pricing._request=lookup;pricing.native.reconcile_unknown('alice',cid,item['turn_id'])
                reused=pricing.submit_pricing('alice',cid,'review daily','pricing_lost_202_01',daily)
                self.assertTrue(reused['reused']);self.assertEqual(pending,[])
                self.assertEqual(found,[('GET','/v1/native/'+original_binding['session_id'])])
                self.assertEqual(pricing.native.row('alice',cid,item['turn_id'])['idempotency_key'],original_key)
                with tasks.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)

    def test_old_legacy_inflight_recovers_original_task_after_both_stores_construct(self):
        Grants=self.transport.Grants
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tasks=TaskStore(root/'tasks.sqlite3')
            pricing_store=ConversationStore(root/'pricing-reviews');cid=pricing_store.create('alice')['conversation_id']
            item=pricing_store.reserve_turn('alice',cid,'old legacy','legacy_old_native_01')
            spec=dict(period=dict(start='2026-11-01',end_exclusive='2026-11-02',timezone='Asia/Shanghai'),snapshot_id='old-snapshot',template_version='old-template',knowledge_version='old-knowledge',budget_policy_id='old-budget')
            task=tasks.create('alice',spec);lease='c'*32;run='run_'+'d'*32
            tasks.reserve_dispatch(task['id'],'alice',lease);tasks.bind_run(task['id'],'alice',lease,run)
            pricing_store.bind_task('alice',cid,item['turn_id'],task['id'],lease);pricing_store.bind_run('alice',cid,item['turn_id'],run)
            h=SimpleNamespace(root=root,tasks=tasks,clock=lambda:NOW,authorizer=lambda user:user=='alice',grants=Grants(),lock=threading.RLock(),tokens={},books={},gateways={})
            calls=[]
            def request(self,method,path,body=None,**kwargs):
                self.assertion=tasks._native_active_model_tasks()
                calls.append((method,path));return 200,dict(status='failed',error='original legacy failure')
            modules=dict(self.fixtures.modules,fs_inprocess=self.inprocess,proxy_gateway=self.proxy,transport=self.transport,fc_daily=self.daily_reports)
            with patch.dict(sys.modules,modules),patch.object(self.fixtures.active.ConversationService,'_request',request):
                service=self.fixtures.active.ConversationService(h,root/'conversations',root/'run')
                service.pool.shutdown(wait=True);service.pricing_pool.shutdown(wait=True);service.pricing.pool.shutdown(wait=True)
                self.assertEqual(calls,[('GET','/v1/runs/'+run)])
                self.assertIsNotNone(service.native);self.assertIsNotNone(service.pricing.native)
                self.assertIsNone(service.pricing.native.row('alice',cid,item['turn_id']))
                self.assertEqual(tasks.get(task['id'],'alice')['state'],'FAILED')
                self.assertEqual(pricing_store.run('alice',cid,run)['state'],'failed')
                self.assertNotEqual(task['id'],item['turn_id'])

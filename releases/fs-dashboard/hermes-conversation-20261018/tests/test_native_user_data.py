"""Real native binding + existing customer SQLite projections. No production I/O."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
USERS=HERE.parents[1]/'user-analytics-20261022'
LIVE=HERE.parents[1]/'tiered-data-access-20261101'
sys.path[:0]=[str(HERE),str(HERE.parent/'source'),str(USERS/'source'),str(LIVE/'source')]
spec=importlib.util.spec_from_file_location('native_user_real_a2_fixture',USERS/'tests/test_a2_query_context.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
import test_conversation_native as native_tests


class NativeUserRelay(unittest.TestCase):
    make=fixtures.A2Context.make
    load=fixtures.A2Context.load
    summary=fixtures.A2Context.summary
    snapshot=fixtures.A2Context.snapshot
    cid=fixtures.A2Context.cid

    def setUp(self):
        fixtures.A2Context.setUp(self)
        self.addCleanup(fixtures.A2Context.tearDown,self)
        native_tests.NativeDispatchTests.setUpClass()
        self.host_fixture=native_tests.NativeDispatchTests()
        self.modules=patch.dict(sys.modules,native_tests.NativeDispatchTests.modules);self.modules.start();self.addCleanup(self.modules.stop)
        self.conversation,self.conversation_id=self.host_fixture.fixture(Path(self.temp.name)/'chat')
        self.conversation.hermes.authorizer=lambda owner:owner=='operator' and self.host_allowed
        self.conversation_id=self.conversation.store.create('operator')['conversation_id']
        self.binding=self.bind('operator',self.conversation_id,'native_actor_request')
        self.original.authorizer=lambda owner,query,private:self.source_allowed and owner=='operator'
        pilot_path=HERE.parents[1]/'hermes-fc-pilot-20261013/pilot.py'
        spec=importlib.util.spec_from_file_location('pilot',pilot_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        sys.modules['pilot']=module

    def bind(self,owner,cid,request):
        from conversation_native import canonical
        turn=self.conversation.store.reserve_turn(owner,cid,'Synthetic customer question',request,native=True)
        binding=dict(owner=owner,conversation_id=cid,turn_id=turn['turn_id'],request_id=request,
                     session_id=turn['session_id'],lease='a'*32,run_id='run_'+'b'*32)
        store=self.conversation.store
        store.bind_task(owner,cid,turn['turn_id'],turn['turn_id'],binding['lease'])
        store.bind_run(owner,cid,turn['turn_id'],binding['run_id'])
        body={'input':'Synthetic customer question','session_id':turn['session_id']}
        with store.db() as db:
            db.execute('INSERT INTO native_conversation_runs(turn_id,binding,body,idempotency_key,fingerprint,schemas,stopped) VALUES(?,?,?,?,?,NULL,0)',
                       (turn['turn_id'],canonical(binding),canonical(body),request,'c'*64))
        return binding

    def data(self,live_get=None,run_source=None):
        native=self.conversation.native
        self.assertTrue(callable(getattr(native,'user_data_tool',None)),
                        'native host has no run-bound user-data consumer')
        from conversation_user_data import NativeUserData
        data=NativeUserData(native,self.original,live_get=live_get,run_source=run_source,clock=lambda:fixtures.NOW)
        native.user_data=data
        return data

    def call(self,name,args,binding=None):
        bound=self.binding if binding is None else binding
        return self.conversation.native.host_tool(bound,'fs.native.user_data',
            {'binding':bound,'name':name,'arguments':args})

    def test_structure_read_uses_hermes_route_and_rechecks_actor(self):
        data=self.data();calls=[]
        query=dict(mode='hermes',structure='es',profile='FC27',start='2026-11-06',end='2026-11-06',group_by='product')
        def get(params,owner):
            calls.append((params,owner));return 200,{'status':'available','groups':[]}
        host=sys.modules['__main__']
        with patch('user_runtime.authorize',return_value=True), patch.object(host,'HERMES',types.SimpleNamespace(get=get),create=True), patch.object(host,'ADVISOR',types.SimpleNamespace(get=lambda *args:(422,{'error':'invalid_parameters'})),create=True):
            self.assertEqual(data.read(self.binding,'/advisor',query)['status'],'available')
            self.assertEqual(calls,[({k:[str(v)] for k,v in query.items()},'operator')])
            self.source_allowed=False
            with self.assertRaises(PermissionError):data.read(self.binding,'/advisor',query)
            self.assertEqual(len(calls),1)
            self.source_allowed=True
            def revoke(params,owner):
                self.source_allowed=False;return 200,{'status':'available'}
            host.HERMES.get=revoke
            with self.assertRaises(PermissionError):data.read(self.binding,'/advisor',query)

    def test_actual_host_binding_context_and_b2_projection_do_not_create_goals(self):
        self.data()
        receipt=self.call('fs_query_user_analytics',dict(fixtures.SCOPE,start='2026-10-01',
                         end_exclusive='2026-10-25',state_basis='period_end'))
        snapshot=receipt['snapshot_id']
        page=self.call('fs_customer_candidates',{'snapshot_id':snapshot,'limit':1})
        cid=page['rows'][0]['opaque_customer_id']
        result=self.call('fs_describe_customer',{'snapshot_id':snapshot,'customer_id':cid})
        self.assertEqual(result['status'],'observed');self.assertFalse(result['business_write_performed'])
        self.assertEqual(result['customer_id'],cid)
        exported=json.dumps([page,result]);self.assertNotIn('@example.test',exported)
        with self.conversation.store.db() as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_goals_v1'").fetchone())
        for key in ('owner','session_id','lease','private'):
            with self.assertRaises((ValueError,PermissionError)):
                self.call('fs_describe_customer',dict(snapshot_id=snapshot,customer_id=cid,**{key:'other'}))
        self.source_allowed=False
        with self.assertRaises(PermissionError):self.call('fs_describe_customer',{'snapshot_id':snapshot,'customer_id':cid})

    def test_wrong_binding_revoked_run_and_different_customer_fail_before_source(self):
        self.data();snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
        for key in ('owner','conversation_id','session_id','lease','run_id'):
            bound=dict(self.binding,**{key:'wrong'})
            with self.assertRaises((PermissionError,LookupError)):
                self.call('fs_describe_customer',{'snapshot_id':snapshot,'customer_id':cid},bound)
        with self.assertRaises(LookupError):
            self.call('fs_describe_customer',{'snapshot_id':snapshot,'customer_id':'c_'+'0'*32})
        with self.conversation.store.db() as db:
            db.execute('UPDATE native_conversation_runs SET stopped=1 WHERE turn_id=?',(self.binding['turn_id'],))
        with self.assertRaises(PermissionError):self.call('fs_customer_candidates',{'snapshot_id':snapshot})

    def test_default_global_snapshot_offers_explicit_customer_scope_without_selecting_one(self):
        self.data()
        catalog=self.call('fs_get_data_catalog',{})
        for explicit in ({},{'scope':'global'},{'scope':'series','scope_id':'FC'}):
            aggregate=self.call('fs_query_user_analytics',dict(start='2026-10-01',end_exclusive='2026-10-25',
                                state_basis='period_end',**explicit))
            self.assertEqual(aggregate['query']['scope'],explicit.get('scope','global'))
            snapshot=aggregate['snapshot_id']
            # This public schema's default is legal for aggregates, but must
            # not turn into a misleading permission403 or an implicit site.
            blocked=self.call('fs_customer_candidates',{'snapshot_id':snapshot})
            self.assertEqual(blocked['status'],'unavailable')
            self.assertEqual(blocked['reason'],'customer_snapshot_scope_required')
            self.assertEqual(blocked['snapshot_id'],snapshot)
            path=blocked['customer_investigation']
            self.assertFalse(path['snapshot_usable'])
            self.assertEqual(path['scope_choices'],catalog['user_analytics']['customer_investigation']['scope_choices'])
            self.assertEqual(aggregate['customer_investigation'],path)
            self.assertEqual(path['query_required_fields'],['scope','scope_id'])
            self.assertNotIn('selected_scope',path)
            for kind in ('site','project'):
                selected=next(x for x in path['scope_choices'] if x['scope']==kind and
                              (kind=='site' or x['scope_id']==fixtures.SCOPE['scope_id']))
                narrowed=self.call('fs_query_user_analytics',dict(start='2026-10-01',end_exclusive='2026-10-25',
                                   state_basis='period_end',**selected))
                self.assertTrue(narrowed['customer_investigation']['snapshot_usable'])
                page=self.call('fs_customer_candidates',{'snapshot_id':narrowed['snapshot_id'],'limit':1})
                customer=page['rows'][0]['opaque_customer_id']
                result=self.call('fs_describe_customer',{'snapshot_id':narrowed['snapshot_id'],'customer_id':customer})
                self.assertEqual(result['status'],'observed')
                self.assertEqual({k:result['source']['query'][k] for k in ('scope','scope_id')},selected)
        with self.conversation.store.db() as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_goals_v1'").fetchone())

    def test_customer_scope_guidance_does_not_replace_private_or_run_authorization(self):
        self.data()
        args=dict(start='2026-10-01',end_exclusive='2026-10-25',state_basis='period_end')
        snapshot=self.call('fs_query_user_analytics',args)['snapshot_id']
        self.original.authorizer=lambda owner,scope,private:owner=='operator' and not private
        aggregate=self.call('fs_query_user_analytics',args)
        self.assertEqual(aggregate['query']['scope'],'global')
        self.assertEqual(aggregate['customer_investigation']['scope_choices'],[])
        with self.assertRaises(PermissionError):self.call('fs_customer_candidates',{'snapshot_id':snapshot})
        self.host_allowed=False
        with self.assertRaises(PermissionError):self.call('fs_get_data_catalog',{})

    def test_scope_guidance_rechecks_binding_after_authorizer_io(self):
        self.data()
        snapshot=self.call('fs_query_user_analytics',dict(start='2026-10-01',end_exclusive='2026-10-25',state_basis='period_end'))['snapshot_id']
        def revoke(owner,scope,private):
            if scope['scope']=='project' and private:self.host_allowed=False
            return owner=='operator'
        self.original.authorizer=revoke
        with self.assertRaises(PermissionError):self.call('fs_customer_candidates',{'snapshot_id':snapshot})

    def test_actual_policy_reader_is_used_each_call_and_keeps_private_and_resource_boundaries(self):
        import user_runtime
        policy_source=HERE.parents[3]/'opt/fs-access-policy/rbac.py'
        spec=importlib.util.spec_from_file_location('rbac',policy_source)
        rbac=importlib.util.module_from_spec(spec);spec.loader.exec_module(rbac)
        policy={'schema':1,'roles':{'PlatformAdmin':{'super':True,'rules':[]},
            'UserReader':{'rules':[{'effect':'allow','resources':['unified-business'],'actions':['view']}]}},
            'bindings':{'operator':{'roles':['PlatformAdmin']},'maintainer':{'roles':['PlatformAdmin']},
                        'reader':{'roles':['UserReader']}}}
        path=Path(self.temp.name)/'synthetic-policy.json'
        def write():path.write_text(json.dumps(policy),encoding='utf-8')
        write();self.data()
        with patch.dict(sys.modules,{'rbac':rbac}),patch.object(rbac,'LIVE_POLICY',str(path)):
            self.original.authorizer=user_runtime.authorize
            snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
            self.assertEqual(self.call('fs_describe_customer',dict(snapshot_id=snapshot,customer_id=cid))['status'],'observed')
            self.assertTrue(user_runtime.authorize('reader',fixtures.SCOPE))
            self.assertFalse(user_runtime.authorize('reader',fixtures.SCOPE,True))
            self.assertFalse(user_runtime.authorize('reader',fixtures.SCOPE,resource='/dashboard/data-tools/'))
            policy['bindings'].pop('operator');write()
            with self.assertRaises(PermissionError):self.call('fs_describe_customer',dict(snapshot_id=snapshot,customer_id=cid))

    def test_registered_plugin_uses_real_worker_request_grant_scope_and_host(self):
        import ast,io
        from urllib.request import Request,HTTPRedirectHandler
        from urllib.error import HTTPError
        from conversation_native import NativeDockerBackend,_NATIVE_BACKEND
        self.data();native=self.conversation.native
        self.assertTrue(callable(getattr(NativeDockerBackend,'user_data_call',None)))
        core=HERE.parents[1]/'hermes-v2-core-20261020/source'
        sys.path.insert(0,str(core))
        sys.path.insert(0,str(HERE.parents[2]/'fc-coins/fc-review-channel-20261026/source'))
        sys.path.insert(0,str(HERE.parents[2]/'fc-coins/fc-pricing-v2-20261022/source'))
        sys.path.append(str(HERE.parents[1]/'hermes-fc-pilot-20261013'))
        import transport
        from native_chat import NativeChatScope
        grants=transport.Grants();binding=self.binding
        token=grants.mint(binding['owner'],binding['turn_id'],binding['lease'])
        scope=NativeChatScope(binding,lambda:native.authorized(binding),model_schemas=lambda:[],
                              call_tool=lambda name,args:native.host_tool(binding,name,args))
        proxy=transport.Proxy(grants,lambda grant:types.SimpleNamespace(scope=scope))
        worker=HERE.parents[2]/'fc-coins/fc-review-channel-20261026/source/hermes_worker.py'
        tree=ast.parse(worker.read_text('utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='call_tool')
        wire=[]
        class Opener:
            def open(_,request,timeout):
                wire.append(request)
                value=proxy.dispatch('POST','/fc/tools/call',request.get_header('Authorization')[7:],json.loads(request.data))
                return io.BytesIO(json.dumps(value).encode())
        namespace=dict(json=json,Request=Request,HTTPError=HTTPError,NoRedirect=HTTPRedirectHandler,
                       PROXY='http://synthetic.invalid',MAX_PROVIDER_WIRE_BYTES=10_000_000,
                       admission=lambda sid:{'token':token} if sid==binding['session_id'] else {},
                       build_opener=lambda *a:Opener())
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(worker),'exec'),namespace)
        backend=NativeDockerBackend.__new__(NativeDockerBackend)
        backend.binding=binding;backend.authorize=lambda:native.authorized(binding)
        backend.data_call=lambda name,args:json.loads(namespace['call_tool']('fs.native.user_data',
            {'binding':binding,'name':name,'arguments':args},session_id=binding['session_id']))
        sys.path.insert(0,str(HERE.parents[1]/'hermes-server-unify-20261022'))
        sys.path.insert(0,str(HERE.parents[1]/'knowledge-layering-20261023/source'))
        import fs_readonly
        registered={}
        ctx=types.SimpleNamespace(register_tool=lambda **kwargs:registered.update({kwargs['name']:kwargs}),
                                  register_system_prompt_section=lambda *a,**k:None,
                                  register_hook=lambda *a,**k:None)
        with patch.dict(sys.modules,{'toolsets':types.SimpleNamespace(TOOLSET_SESSION_PLATFORMS={})}):fs_readonly.register(ctx,native_only=True,include_knowledge=False)
        current=_NATIVE_BACKEND.set(backend)
        try:
            query_tool=registered['fs_query_user_analytics']
            self.assertIn('global',query_tool['schema']['parameters']['properties']['scope']['enum'])
            aggregate=json.loads(query_tool['handler'](
                dict(start='2026-10-01',end_exclusive='2026-10-25',state_basis='period_end'),task_id=binding['turn_id']))
            guidance=json.loads(registered['fs_customer_candidates']['handler'](
                {'snapshot_id':aggregate['snapshot_id']},task_id=binding['turn_id']))
            self.assertEqual(guidance['reason'],'customer_snapshot_scope_required')
            self.assertIn('site',query_tool['schema']['description'])
            selected=next(x for x in guidance['customer_investigation']['scope_choices'] if x['scope']=='site')
            scoped=json.loads(query_tool['handler'](dict(start='2026-10-01',end_exclusive='2026-10-25',
                state_basis='period_end',**selected),task_id=binding['turn_id']))
            page=json.loads(registered['fs_customer_candidates']['handler'](
                {'snapshot_id':scoped['snapshot_id'],'limit':1},task_id=binding['turn_id']))
            described=json.loads(registered['fs_describe_customer']['handler'](
                {'snapshot_id':scoped['snapshot_id'],'customer_id':page['rows'][0]['opaque_customer_id']},task_id=binding['turn_id']))
            self.assertEqual(described['status'],'observed')
            result=json.loads(registered['fs_query_user_analytics']['handler'](
                dict(fixtures.SCOPE,start='2026-10-01',end_exclusive='2026-10-25',state_basis='period_end'),task_id=binding['turn_id']))
            self.assertTrue(result['snapshot_id'].startswith('us_'))
            wire_count=len(wire);self.assertEqual(wire_count,6)
            with self.assertRaises(PermissionError):registered['fs_query_user_analytics']['handler']({},task_id='another-turn')
            self.assertEqual(len(wire),wire_count)
            grants.revoke(token)
            with self.assertRaises(PermissionError):registered['fs_get_data_catalog']['handler']({},task_id=binding['turn_id'])
        finally:_NATIVE_BACKEND.reset(current)

    def test_explicit_tracking_persists_CAS_before_native_enqueue_and_keeps_original_request(self):
        from pilot import TaskStore
        data=self.data()
        self.assertTrue(callable(getattr(data,'track',None)),'tracking host is not connected to durable goals')
        path=self.conversation.hermes.root/'tasks.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
        self.conversation.hermes.tasks=TaskStore(path)
        snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
        args={'operation':'create','snapshot_id':snapshot,'customer_id':cid,'objective':'Explicit synthetic customer followup',
              'recheck_at':fixtures.NOW.isoformat(),'explicit_goal':True}
        with self.assertRaises(ValueError):self.call('fs_track_customer',dict(args,explicit_goal=False))
        created=self.call('fs_track_customer',args)
        goal=created['goal_id']
        from conversation_goals import ConversationGoals
        goals=ConversationGoals(self.conversation.store,'operator',self.conversation_id,data.goal_authorized)
        state=goals.load_goal(goal)
        self.assertEqual(state['revision'],1);self.assertIsNone(state['work'])
        queued=[]
        self.conversation.pool=types.SimpleNamespace(submit=lambda *a:queued.append(a))
        first=self.call('fs_track_customer',{'operation':'step','goal_id':goal,'snapshot_id':snapshot,
                         'customer_id':cid,'expected_revision':1})
        original=first['request_id'];saved=goals.load_goal(goal)
        self.assertEqual(saved['work']['request_id'],original)
        self.assertEqual(saved['work']['status'],'queued');self.assertEqual(queued,[])
        self.assertEqual(saved['work']['fact_version'],data.version(self.binding,snapshot,cid))
        again=self.call('fs_track_customer',{'operation':'step','goal_id':goal,'snapshot_id':snapshot,
                         'customer_id':cid,'expected_revision':saved['revision']})
        self.assertEqual(again['request_id'],original);self.assertEqual(queued,[])
        self.conversation.store.set_state('operator',self.conversation_id,self.binding['turn_id'],'completed')
        self.conversation._finish_task('operator',self.conversation_id,self.binding['turn_id'],None,'completed')
        self.assertEqual(len(queued),1)
        # The actual existing service, not a fake dispatcher, reserved/enqueued
        # the ordinary native turn only after the goal and outbox commits.
        with self.conversation.store.db() as db:
            turn=db.execute('SELECT id,state FROM turns WHERE conversation_id=? AND request_id=?',
                            (self.conversation_id,original)).fetchone()
            self.assertIsNotNone(turn);self.assertEqual(turn['state'],'preparing')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM conversation_goals_v1').fetchone()[0],1)
        self.assertEqual(self.conversation.native.finish_user_data(self.binding['turn_id'],'completed'),[])
        self.assertEqual(len(queued),1)
        # Synthetic final executor boundary: the existing conversation ledger,
        # rather than model prose, supplies the follow-up terminal receipt.
        self.conversation.store.set_state('operator',self.conversation_id,turn['id'],'completed')
        self.conversation.native.finish_user_data(turn['id'],'completed')
        terminal=goals.load_goal(goal)
        self.assertEqual(terminal['work']['request_id'],original)
        self.assertEqual(terminal['work']['status'],'completed')
        self.conversation.native.finish_user_data(turn['id'],'completed')
        self.assertEqual(goals.load_goal(goal),terminal)

    def test_fact_version_uses_scope_identity_policy_data_and_effective_cutoff_not_capture_clock(self):
        data=self.data();self.assertTrue(callable(getattr(data,'version',None)))
        from conversation_user_data import fact_version
        snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
        receipt=data.context(self.binding,snapshot).timeline(snapshot,cid,limit=1)
        original=fact_version(receipt,fixtures.NOW)
        changed=deepcopy(receipt);changed['source']['captured_at']='2026-10-30T00:00:00+00:00'
        self.assertEqual(fact_version(changed,fixtures.NOW),original)
        for field in ('scope_version','identity_version','policy_version','data_version'):
            changed=deepcopy(receipt);changed['source'][field]=str(changed['source'][field])+'-changed'
            self.assertNotEqual(fact_version(changed,fixtures.NOW),original)
        changed=deepcopy(receipt);changed['source'].pop('identity_version')
        with self.assertRaises(ValueError):fact_version(changed,fixtures.NOW)

    def verify_official_registry_owner_overlay(self):
        import hashlib
        sys.path.insert(0,str(HERE.parents[1]/'hermes-server-unify-20261022'))
        sys.path.insert(0,str(HERE.parents[1]/'knowledge-layering-20261023/source'))
        import fs_readonly
        self.assertTrue(callable(getattr(fs_readonly,'register_scope',None)))
        source=HERE.parents[3]/'.agent_runtime/materials-official-pin/tools_registry.py'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),'4a05aae5b4dd40bf9a104d23582d4363326ad7ce3fdac1ac249e0af04334d909')
        scope=str((Path(self.temp.name)/'owner-profile').resolve())
        constants=types.ModuleType('hermes_constants')
        constants.hermes_home_key=lambda value=None:str(Path(value or scope).resolve())
        constants.normalize_scope=lambda value:None if value is None else str(Path(value).resolve())
        spec=importlib.util.spec_from_file_location('native_user_actual_registry',source)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'hermes_constants':constants,'native_user_actual_registry':module}):
            spec.loader.exec_module(module)
        registry=module.ToolRegistry()
        old=lambda args:'desktop legacy'
        registry.register('fs_get_data_catalog','fs_readonly',{'name':'fs_get_data_catalog','parameters':{'type':'object'}},old)
        fs_readonly.register_scope(registry,scope)
        entry=registry.get_entry('fs_get_data_catalog',scope=scope)
        self.assertIsNot(entry.handler,old)
        self.assertIs(registry.get_entry('fs_get_data_catalog',scope='another-owner').handler,old)
        with self.assertRaises(PermissionError):entry.handler({})
        generation=registry._generation
        fs_readonly.register_scope(registry,scope)
        self.assertEqual(registry._generation,generation)
        # Fixed public toolsets resolves registry-only profile tools; no custom
        # global toolset/config mutation is required by the worker registration.
        toolsets_path=HERE.parents[3]/'.agent_runtime/actor-relay/toolsets-71d34bad.py'
        self.assertEqual(hashlib.sha256(toolsets_path.read_bytes()).hexdigest(),
                         'be9cc61dd8aa082881ed945f7a45db23af85d76b5097f04698a553e2831b0294')
        spec=importlib.util.spec_from_file_location('native_user_actual_toolsets',toolsets_path)
        toolsets=importlib.util.module_from_spec(spec);spec.loader.exec_module(toolsets)
        tools=types.ModuleType('tools');tools.__path__=[]
        with patch.dict(sys.modules,{'tools':tools,'tools.registry':types.SimpleNamespace(registry=registry)}):
            self.assertTrue(toolsets.validate_toolset('fs_readonly'))
            self.assertIn('fs_describe_customer',toolsets.resolve_toolset('fs_readonly'))

    def test_owner_registry_overlay_retains_other_profiles_and_requires_live_backend(self):
        sys.path.insert(0,str(HERE.parents[1]/'hermes-server-unify-20261022'))
        sys.path.insert(0,str(HERE.parents[1]/'knowledge-layering-20261023/source'))
        import fs_readonly
        class Registry:
            def __init__(self):self.rows={}
            def get_entry(self,name,*,scope):return self.rows.get((scope,name))
            def register(self,*,scope,**kwargs):self.rows[(scope,kwargs['name'])]=types.SimpleNamespace(**kwargs)
        registry=Registry();fs_readonly.register_scope(registry,'operator-profile')
        self.assertIn(('operator-profile','fs_describe_customer'),registry.rows)
        self.assertIsNone(registry.get_entry('fs_describe_customer',scope='other-profile'))
        with self.assertRaises(PermissionError):registry.get_entry('fs_get_data_catalog',scope='operator-profile').handler({})

    def test_actual_live_handler_and_original_shared_slot_reject_wrong_customer_and_revocation(self):
        from concurrent.futures import ThreadPoolExecutor
        from admin_live_admission import LiveAdminAdmission
        from admin_live_host import build_handler
        from contextlib import nullcontext
        config=dict(self.config,activation_status='W0_verified',live_admin_single_page=True)
        policy={'admins':['operator']};calls=[]
        rbac=types.SimpleNamespace(validate=lambda p:p)
        def source(path,params,timeout,cap):
            calls.append(params)
            return 200,json.dumps({'code':1,'data':{'total':1,'list':[
                {'id':1,'site_id':266,'gid':1327,'paytime':'2026-10-02 12:00:00','status':86,'pay_status':2,'email':'unrelated@example.test'}]}}).encode()
        with ThreadPoolExecutor(max_workers=1) as pool:
            admission=LiveAdminAdmission(pool,nullcontext)
            def handler(params,user,*,run_source):
                return build_handler(load_config=lambda:config,load_policy=lambda:policy,rbac=rbac,fetch=source,
                    observed_at=lambda:fixtures.NOW.isoformat(),run_source=run_source,
                    existing_authorizer=self.original.authorizer)(params,user)
            self.data(handler,admission.run)
            snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
            args=dict(snapshot_id=snapshot,customer_id=cid,site_id='266',game_id='1327',
                      start='2026-10-01',end_exclusive='2026-10-20',max_pages=1)
            with self.assertRaises(RuntimeError):self.call('fs_observe_customer_orders',args)
            self.assertEqual(len(calls),1)
            self.source_allowed=False
            with self.assertRaises(PermissionError):self.call('fs_observe_customer_orders',args)
            self.assertEqual(len(calls),1)

    def test_tracking_parallel_revision_and_pending_states_do_not_allocate_another_request(self):
        from concurrent.futures import ThreadPoolExecutor
        from pilot import TaskStore
        from conversation_goals import ConversationGoals
        data=self.data();path=self.conversation.hermes.root/'tasks.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
        self.conversation.hermes.tasks=TaskStore(path)
        snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
        created=self.call('fs_track_customer',dict(operation='create',snapshot_id=snapshot,customer_id=cid,
            objective='Explicit fixture tracking',recheck_at=fixtures.NOW.isoformat(),explicit_goal=True))
        goal=created['goal_id'];step=dict(operation='step',snapshot_id=snapshot,customer_id=cid,goal_id=goal,expected_revision=1)
        def try_step():
            try:return self.call('fs_track_customer',step)
            except (ValueError,PermissionError):return 'revision_conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:try_step(),range(2)))
        self.assertGreaterEqual(sum(isinstance(x,dict) for x in results),1)
        self.assertEqual(len(data.pending[self.binding['turn_id']]),1)
        goals=ConversationGoals(self.conversation.store,'operator',self.conversation_id,data.goal_authorized)
        original=goals.load_goal(goal)['work']['request_id']
        for status in ('prepared','queued','running','provider_returned','unknown'):
            current=goals.load_goal(goal);changed=deepcopy(current)
            changed['revision']+=1;changed['work'].update(status=status,
                receipt_ref=None if status=='prepared' else 'fixture-original-receipt',
                receipt_digest=None if status=='prepared' else 'a'*64)
            goals.cas_goal(goal,expected_revision=current['revision'],mutation_id='fixture_'+status,state=changed)
            try:value=self.call('fs_track_customer',dict(step,expected_revision=changed['revision']))
            except ValueError:pass  # An inconsistent lower-layer regression must also fail closed.
            else:self.assertEqual(value['request_id'],original)
            self.assertEqual(goals.load_goal(goal)['work']['request_id'],original)
        self.assertEqual(len(data.pending[self.binding['turn_id']]),1)
        self.conversation._abandon_task('operator',self.conversation_id,self.binding['turn_id'],None)
        self.assertEqual(data.pending,{})

    def test_late_completed_callback_cannot_dispatch_after_parent_was_cancelled(self):
        from pilot import TaskStore
        data=self.data();path=self.conversation.hermes.root/'tasks.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
        self.conversation.hermes.tasks=TaskStore(path)
        snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
        goal=self.call('fs_track_customer',dict(operation='create',snapshot_id=snapshot,customer_id=cid,
            objective='Explicit cancelled-parent fixture',recheck_at=fixtures.NOW.isoformat(),explicit_goal=True))['goal_id']
        self.call('fs_track_customer',dict(operation='step',snapshot_id=snapshot,customer_id=cid,goal_id=goal,expected_revision=1))
        queued=[];self.conversation.pool=types.SimpleNamespace(submit=lambda *a:queued.append(a))
        self.conversation.store.set_state('operator',self.conversation_id,self.binding['turn_id'],'cancelled')
        with self.assertRaises(ValueError):self.conversation.native.finish_user_data(self.binding['turn_id'],'completed')
        self.assertEqual(queued,[])

    def test_live_host_private_email_never_crosses_projection_and_each_page_rechecks(self):
        calls=[]
        def live_get(params,owner,*,run_source):
            self.assertEqual(owner,'operator')
            q={k:v[0] for k,v in params.items()}
            calls.append(q)
            self.assertEqual(set(q)-{'cursor'},{'site_id','game_id','start','end_exclusive','customer_email'})
            run_source(lambda:None,10)
            return 206,{'status':'partial','semantics':'live_non_snapshot','complete':False,
                        'data':[{'customer_email':q['customer_email'],'status':86,'pay_status':2}],
                        'observed_page_rows':1,'next_cursor':'next' if len(calls)==1 else None}
        data=self.data(live_get,lambda fn,timeout:fn())
        snapshot=self.snapshot(self.summary());cid=self.cid(snapshot)
        args=dict(snapshot_id=snapshot,customer_id=cid,site_id='266',game_id='1327',
                  start='2026-10-01',end_exclusive='2026-10-31',max_pages=4)
        result=self.call('fs_observe_customer_orders',args)
        self.assertFalse(result['complete']);self.assertEqual(result['pages'],3)
        self.assertEqual(result['observed_order_rows'],3)
        self.assertIsNone(result['lifetime_first_paid_at']);self.assertNotIn('@',json.dumps(result))
        self.assertEqual(calls[0]['end_exclusive'],'2026-10-29')
        self.assertEqual(calls[2]['start'],'2026-10-29')
        fetch=data.customer_fetch(self.binding,snapshot,cid,'266','1327','2026-10-01','2026-10-31')
        with self.assertRaises(PermissionError):fetch(dict(site_id='266',game_id='1329',start='2026-10-01',end_exclusive='2026-10-02'))
        self.source_allowed=False
        with self.assertRaises(PermissionError):fetch(dict(site_id='266',game_id='1327',start='2026-10-01',end_exclusive='2026-10-02'))


if __name__=='__main__':unittest.main()

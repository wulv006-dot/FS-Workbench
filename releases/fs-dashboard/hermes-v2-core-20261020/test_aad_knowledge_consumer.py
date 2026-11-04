"""Bounded synthetic consumer, not a replay of private production history."""
import ast
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_native_chat import NativeToolHistory

REPO=Path(__file__).resolve().parents[3]
CACHE=Path('pinned_sdk')
RESULTS=[]

def source_functions(path,names,namespace):
    from fixed_sdk_aad_wire import read_source
    source=read_source(path);tree=ast.parse(source)
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in names]
    assert set(n.name for n in nodes)==set(names)
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(path),'exec'),namespace)
    return namespace

def actual_handler(transport,proxy,body,token,path='/v1/chat/completions'):
    # Execute the original nested Handler class with in-memory socket I/O only.
    tree=ast.parse(Path(transport.__file__).read_text(encoding='utf-8'))
    start=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='start_loopback')
    handler=next(n for n in start.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
    wrapper=ast.parse('def bind(proxy):\n pass').body[0]
    wrapper.body=[handler,ast.Return(value=ast.Name(id='Handler',ctx=ast.Load()))]
    ns=dict(vars(transport));exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),transport.__file__,'exec'),ns)
    cls=ns['bind'](proxy)
    raw=json.dumps(body).encode();headers=Message()
    for k,v in [('Authorization','Bearer '+token),('Content-Length',str(len(raw))),('Content-Type','application/json')]:headers[k]=v
    status=[];fake=SimpleNamespace(connection=SimpleNamespace(settimeout=lambda x:None),headers=headers,
        rfile=BytesIO(raw),wfile=BytesIO(),path=path,
        send_response=lambda value:status.append(value),send_header=lambda *a:None,end_headers=lambda:None)
    cls._handle(fake,'POST')
    return status[0],json.loads(fake.wfile.getvalue())

class AadKnowledgeConsumer(unittest.TestCase):
    def fixture(self):return NativeToolHistory('runTest').history_fixture(older=True)

    def prepare(self,h):
        sdk=source_functions(CACHE/'tools/tool_search.py',
            ['_bridge_schema','_search_description','bridge_tool_schemas'],
            dict(TOOL_SEARCH_NAME='tool_search',TOOL_DESCRIBE_NAME='tool_describe',TOOL_CALL_NAME='tool_call'))
        # Exact SDK bridge schemas; no claim this subset equals the private
        # runtime's entire registered registry/listing, which was not exported.
        h.body['tools'][:]=sdk['bridge_tool_schemas'](2)
        tools=[
          ('tool_describe',{'names':['fs_get_knowledge_index','fs_read_knowledge']}),
          ('tool_call',{'calls':[{'name':'fs_get_knowledge_index','arguments':{}}]}),
          ('tool_call',{'calls':[{'name':'fs_read_knowledge','arguments':{'modules':['fs.data.currency'],'entry_ids':['fs.data.currency'],'revision':'fc-v3-20261026'}}]}),
          ('tool_call',{'calls':[{'name':'fs_read_knowledge','arguments':{'modules':['skills'],'skill_id':'synthetic-reviewed-skill'}}]})]
        calls=[dict(id='synthetic-call-'+str(i),type='function',index=0,
            function=dict(name=name,arguments=json.dumps(args,ensure_ascii=False))) for i,(name,args) in enumerate(tools)]
        from fixed_sdk_aad_wire import build_wire
        def sdk_send(messages):
            messages[:]=build_wire(messages,h.body['tools'])
        return calls,sdk_send

    def paid_three(self,h,grouping):
        calls,canonicalize=self.prepare(h)
        sizes=((2,1,1),(1,2,1),(1,1,2))[grouping]
        batches=[];position=0
        for size in sizes:
            batch=deepcopy(calls[position:position+size]);position+=size
            for i,c in enumerate(batch):c['index']=i
            batches.append(batch)
        h.responses[:]=deepcopy(batches)
        outcomes=[{'status':'described','schemas':'synthetic declared schemas'},
                  {'status':'index_only','catalog':'synthetic formal index'},
                  {'status':'available','contract':'fs-knowledge-index-v1','entries':[{'id':'fs.data.currency','revision':'fc-v3-20261026','content':'SYNTHETIC RULE TEXT'}]},
                  {'status':'available','contract':'fs-native-reviewed-skill-read-v1','skill':{'id':'synthetic-reviewed-skill','content':'SYNTHETIC APPROVED SKILL'}}]
        framed={k:deepcopy(v) for k,v in h.body.items() if k!='messages'}
        offset=0
        for batch in batches:
            canonicalize(h.body['messages'])
            response=NativeToolHistory.dispatch(self,h)
            self.assertEqual(response['choices'][0]['finish_reason'],'tool_calls')
            history=h.replay(batch)
            for i,msg in enumerate(history[1:]):msg['content']=json.dumps(outcomes[offset+i],ensure_ascii=False)
            offset+=len(batch);h.body['messages']+=history
            self.assertEqual({k:v for k,v in h.body.items() if k!='messages'},framed)
        canonicalize(h.body['messages'])
        return framed

    def test_three_paid_responses_then_completion_all_adjacent_groupings(self):
        for grouping in range(3):
            with self.subTest(grouping=grouping),self.fixture() as h:
                framed=self.paid_three(h,grouping)
                result=NativeToolHistory.dispatch(self,h)
                self.assertEqual(result['choices'][0]['message']['content'],'synthetic answer')
                self.assertEqual(len(h.wire),4)
                with h.db() as db:
                    logical=db.execute('SELECT COUNT(*) FROM hermes_turns').fetchone()[0]
                    states=[tuple(r) for r in db.execute('SELECT r.turn,m.state FROM hermes_reservations r LEFT JOIN model_calls m ON m.fingerprint=r.fingerprint ORDER BY r.turn')]
                self.assertEqual(logical,4);self.assertEqual(states,[(i,'succeeded') for i in range(4)])
                RESULTS.append(dict(grouping=grouping,logical=logical,reservations=4,provider_stub=4,states=states,
                    framing_sha256=hashlib.sha256(json.dumps(framed,sort_keys=True).encode()).hexdigest()))

    def test_actual_prefix_rejection_keeps_safe_native_tag(self):
        with self.fixture() as h:
            self.paid_three(h,2)
            # Deliberate synthetic tamper ONLY for diagnostic-loss reproduction,
            # never claimed as a transform made by the SDK or this real run.
            h.body['messages'][0]['content']+=' deliberate diagnostic fixture mutation'
            with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):
                NativeToolHistory.dispatch(self,h)
            status,result=actual_handler(h.f.transport,h.proxy,h.body,h.f.token)
            self.assertEqual(status,400)
            self.assertEqual(result['error']['code'],'provider_tool_history_changed')
            self.assertEqual(result['error']['message'],'fs_native_gateway/native_guard_v1/provider_tool_history_changed')
            with h.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM hermes_turns').fetchone()[0],4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM hermes_reservations').fetchone()[0],3)
            self.assertEqual(len(h.wire),3)
            RESULTS.append(dict(diagnostic='actual prefix rejection -> static native tag',logical=4,reservations=3,provider_stub=3))

    def test_handler_masks_fixed_unlisted_codes_and_arbitrary_dynamic_errors(self):
        with self.fixture() as h:
            for error in [ValueError('turn_conflict'),ValueError('daily_model_limit'),ValueError('task_policy_changed'),
                          TypeError('PRIVATE_SENTINEL'),KeyError('PRIVATE_SENTINEL'),ValueError('PRIVATE_SENTINEL')]:
                def reject(*a,error=error,**k):raise error
                status,result=actual_handler(h.f.transport,SimpleNamespace(dispatch=reject),h.body,h.f.token)
                self.assertEqual((status,result),(400,{'error':{'message':'invalid or unreconciled request','type':'invalid_request_error'}}))
                self.assertNotIn('PRIVATE_SENTINEL',json.dumps(result))

    @classmethod
    def tearDownClass(cls):
        print(json.dumps({'aad_consumer_results':RESULTS},sort_keys=True))


class NativeDiagnosticRed(unittest.TestCase):
    def test_static_local_prefix_failure_keeps_a_safe_native_reason(self):
        with NativeToolHistory('runTest').history_fixture(older=False) as h:
            NativeToolHistory.dispatch(self,h)
            h.body['messages']+=h.replay(h.calls)
            h.body['messages'][0]['content']+=' deliberate diagnostic mutation'
            with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):
                NativeToolHistory.dispatch(self,h)
            status,result=actual_handler(h.f.transport,h.proxy,h.body,h.f.token)
            self.assertEqual(status,400)
            # Requested safe diagnostic contract, intentionally RED on aad.
            self.assertEqual(result['error'].get('code'),'provider_tool_history_changed')


class NativeDiagnosticSafety(unittest.TestCase):
    def fixture(self):return NativeToolHistory('runTest').history_fixture(older=False)

    def retry_gateway(self, h, failures):
        # The general FC lane has two configured reset retries. Its real scope,
        # budget and SQLite remain in the test; only the final provider is fake.
        from test_material_transport import load
        module = load('reset_retry_gateway_under_test',
            REPO/'releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py')
        original = h.proxy.gateway_for(h.f.grants.resolve(h.f.token))
        attempts, waits = [], []
        def provider(request):
            attempts.append(deepcopy(request))
            if len(attempts) <= failures:
                error = ValueError('provider_unknown_transport')
                error.response = dict(status='unknown_transport',
                    transport_error_type='ConnectionResetError')
                raise error
            return dict(id='synthetic-reset-success',model='deepseek-flash',
                usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2),
                choices=[dict(message=dict(role='assistant',content='synthetic recovered'),
                              finish_reason='stop')])
        def wait(seconds, check):
            waits.append(seconds)
            check()
        gateway = module.ModelGateway(h.f.gateway.scope,original.budget,
            original.slot,provider,original.input_bound,original.daily_limit,
            transport_retries=2,retry_wait=wait)
        body = dict(messages=[dict(role='user',content='synthetic reset retry')],max_tokens=32)
        return gateway, body, attempts, waits

    def test_transport_reset_retry_succeeds_with_independent_budget_arguments(self):
        with self.fixture() as h:
            gateway, body, attempts, waits = self.retry_gateway(h,1)
            try:
                result = gateway.call('fixture-owner','fixture-task','fixture-lease',0,body)
            except Exception as error:
                self.fail('retry did not reach success: '+type(error).__name__)
            self.assertEqual(result['message']['content'],'synthetic recovered')
            self.assertEqual(len(attempts),2)
            self.assertEqual(attempts[0],attempts[1])
            self.assertEqual(waits,[2])
            with h.db() as db:
                rows=[tuple(r) for r in db.execute('SELECT r.turn,m.state FROM hermes_reservations r JOIN model_calls m ON m.fingerprint=r.fingerprint ORDER BY r.turn')]
            self.assertEqual(rows,[(0,'unknown'),(1,'succeeded')])
            prior = gateway.call('fixture-owner','fixture-task','fixture-lease',0,body)
            self.assertEqual(prior,result)
            self.assertEqual(len(attempts),2)

    def test_transport_reset_exhaustion_keeps_three_unknown_attempts(self):
        with self.fixture() as h:
            gateway, body, attempts, waits = self.retry_gateway(h,3)
            try:
                gateway.call('fixture-owner','fixture-task','fixture-lease',0,body)
            except Exception as error:
                self.assertIsInstance(error,ValueError)
                self.assertEqual(str(error),'provider_transport_recovery_exhausted')
            else:
                self.fail('three resets must not produce a success receipt')
            self.assertEqual(len(attempts),3)
            self.assertEqual(waits,[2,4])
            with h.db() as db:
                rows=[tuple(r) for r in db.execute('SELECT r.turn,m.state FROM hermes_reservations r JOIN model_calls m ON m.fingerprint=r.fingerprint ORDER BY r.turn')]
            self.assertEqual(rows,[(0,'unknown'),(1,'unknown'),(2,'unknown')])
            with self.assertRaisesRegex(ValueError,'^provider_transport_recovery_exhausted$'):
                gateway.call('fixture-owner','fixture-task','fixture-lease',0,body)
            self.assertEqual(len(attempts),3)

    def test_real_local_reservation_and_limit_guards_have_fixed_native_codes(self):
        for code in ('daily_model_limit','task_policy_changed','trusted_token_bound_required',
                     'daily_limit_invalid','turn_conflict','unknown_previous_attempt'):
            with self.subTest(code=code),self.fixture() as h:
                gateway=h.proxy.gateway_for(h.f.grants.resolve(h.f.token))
                direct=False
                if code in ('daily_model_limit','task_policy_changed','turn_conflict','unknown_previous_attempt'):
                    NativeToolHistory.dispatch(self,h)
                    if code in ('daily_model_limit','task_policy_changed'):h.body['messages']+=h.replay(h.calls)
                    if code=='daily_model_limit':gateway.daily_limit=lambda:1
                    if code=='task_policy_changed':
                        with h.db() as db:db.execute("UPDATE hermes_reservations SET policy='{}'")
                    if code=='turn_conflict':h.body['max_tokens']=31;direct=True
                    if code=='unknown_previous_attempt':
                        with h.db() as db:db.execute("UPDATE model_calls SET state='unknown'")
                        direct=True
                elif code=='trusted_token_bound_required':gateway.input_bound=lambda request:0
                else:gateway.daily_limit=lambda:-1
                if direct:
                    request=deepcopy(h.body)
                    # Trusted direct gateway call only exercises the existing
                    # reservation-slot conflict guard; not an SDK transform.
                    gateway_body=dict(messages=request['messages'],tools=request['tools'],max_tokens=request['max_tokens'])
                    def invoke(*args):return gateway.call('fixture-owner','fixture-task','fixture-lease',0,gateway_body)
                    proxy=SimpleNamespace(dispatch=invoke)
                else:proxy=h.proxy
                status,result=actual_handler(h.f.transport,proxy,h.body,h.f.token)
                self.assertEqual(status,400)
                self.assertEqual(result['error'].get('code'),code,result)
                self.assertEqual(result['error']['message'],'fs_native_gateway/native_guard_v1/'+code)

    def test_arbitrary_callback_exceptions_do_not_mint_safe_codes(self):
        for target,code in [('preflight','provider_tool_history_changed'),('input_bound','daily_model_limit'),('daily_limit','daily_limit_invalid'),('active_tasks','task_policy_changed')]:
            with self.subTest(target=target),self.fixture() as h:
                gateway=h.proxy.gateway_for(h.f.grants.resolve(h.f.token))
                def reject(*a,code=code):raise ValueError(code)
                setattr(gateway.budget if target=='active_tasks' else gateway,target,reject)
                status,result=actual_handler(h.f.transport,h.proxy,h.body,h.f.token)
                self.assertEqual(status,400)
                self.assertEqual(result['error'],{'message':'invalid or unreconciled request','type':'invalid_request_error'})
                self.assertEqual(len(h.wire),0)

    def test_revocation_before_guard_and_initial_authorization_keep_denial(self):
        for change in ('initial','revoked','owner','conversation_id','turn_id','request_id','session_id','lease','run_id'):
            with self.subTest(change=change),self.fixture() as h:
                gateway=h.proxy.gateway_for(h.f.grants.resolve(h.f.token))
                if change=='initial':gateway.scope._authorize=lambda:False
                else:
                    def revoke():
                        if change=='revoked':gateway.scope._authorize=lambda:False
                        else:gateway.scope._binding[change]='changed-binding'
                        return -1
                    gateway.daily_limit=revoke
                status,result=actual_handler(h.f.transport,h.proxy,h.body,h.f.token)
                self.assertEqual(status,403)
                self.assertNotIn('source',result['error']);self.assertNotIn('code',result['error'])
                self.assertEqual(len(h.wire),0)

    def test_non_native_and_untrusted_private_lookalikes_remain_generic(self):
        with self.fixture() as h:
            real=h.f.module._NativeModelGuardError
            fake=type('_NativeModelGuardError',(ValueError,),{})
            child=type('NativeChild',(real,),{})
            for error in (ValueError('provider_tool_history_changed'),fake('provider_tool_history_changed'),
                          child('provider_tool_history_changed'),real('PRIVATE_SENTINEL'),real(1),real('x','y')):
                def reject(*a,error=error):raise error
                status,result=actual_handler(h.f.transport,SimpleNamespace(dispatch=reject),h.body,h.f.token)
                self.assertEqual(status,400)
                self.assertEqual(result['error'],{'message':'invalid or unreconciled request','type':'invalid_request_error'})
        from test_material_transport import MaterialTransport
        with MaterialTransport().fixture(material=False) as f:
            f.body['tools']=f.module.schemas()
            f.gateway.call.side_effect=ValueError('provider_tool_history_changed')
            status,result=actual_handler(f.transport,f.proxy,f.body,f.token)
            self.assertEqual(status,400);self.assertNotIn('code',result['error'])

    def test_legacy_safe_material_and_calculation_mappings_remain(self):
        from test_material_transport import MaterialTransport
        with MaterialTransport().fixture() as f:
            status,result=actual_handler(f.transport,f.proxy,dict(f.body,unexpected='PRIVATE_SENTINEL'),f.token)
            self.assertEqual(status,400);self.assertEqual(result['error']['source'],'fs_material_transport')
            self.assertEqual(result['error']['code'],'request_fields')
            for code in ('model_busy','context_rejected','provider_payload_too_large','pilot_usage_hold'):
                def reject(*a,code=code):raise ValueError(code)
                status,result=actual_handler(f.transport,SimpleNamespace(dispatch=reject),f.body,f.token)
                self.assertEqual(status,400);self.assertEqual(result['error']['message'],'FC model request blocked: '+code)
            def reject(*a):raise ValueError('calculation_operand_mismatch')
            status,result=actual_handler(f.transport,SimpleNamespace(dispatch=reject),{'name':'fc.calculate'},f.token,'/fc/tools/call')
            self.assertEqual((status,result),(400,{'error':{'message':'invalid calculation arguments','type':'invalid_request_error','code':'calculation_operand_mismatch'}}))

    def test_fixed_sdk_summary_preserves_each_static_message_code(self):
        import re
        path=CACHE/'agent/api_error_summary.py'
        from fixed_sdk_aad_wire import read_source
        source=read_source(path);tree=ast.parse(source)
        names={'_http_prefix','_coerce_api_error_detail','_decorate_xai_entitlement_error','_summarize_api_error','_is_xai_entitlement_text'}
        nodes=[deepcopy(n) for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in names]
        for n in nodes:n.decorator_list=[]
        ns=dict(json=json,re=re,is_provider_stream_parse_error=lambda error:False)
        for n in tree.body:
            if isinstance(n,ast.Assign):
                try:value=ast.literal_eval(n.value)
                except (ValueError,TypeError):continue
                for t in n.targets:
                    if isinstance(t,ast.Name):ns[t.id]=value
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])),str(path),'exec'),ns)
        ns['ApiErrorSummaryMixin']=SimpleNamespace(**{name:ns[name] for name in names})
        with self.fixture() as h:
            for code,message in h.f.module._NATIVE_GUARD_MESSAGES.items():
                error=ValueError('synthetic error body carrier')
                error.status_code=400;error.body={'error':{'message':message,'code':code}}
                self.assertEqual(ns['_summarize_api_error'](error),'HTTP 400: '+message)

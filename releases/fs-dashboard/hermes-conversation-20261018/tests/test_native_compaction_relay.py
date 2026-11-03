"""Official facade return through the actual private worker/host/Core consumers."""
import ast
from copy import deepcopy
from datetime import timedelta,timezone
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,HTTPRedirectHandler


class NativeCompactionCombination(unittest.TestCase):
    def test_official_facade_worker_grant_host_and_same_gateway_continue(self):
        from test_conversation_native import NativeDispatchTests,SOURCE
        core=SOURCE.parents[1]/'hermes-v2-core-20261020'
        sys.path.insert(0,str(core))
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
            return module
        tests=load('compaction_core_combination',core/'test_native_chat.py')
        facade=load('compaction_official_facade',Path(__file__).parent/'fixtures/native_compaction_facade_71d34bad.py')
        sdk=load('compaction_official_assembly',core/'fixtures/native_compaction_sdk_71d34bad.py')
        host=NativeDispatchTests('runTest');host.setUpClass()
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,host.modules):
            service,cid=host.fixture(root)
            turn=service.submit('alice',cid,'synthetic compaction integration','compaction_integration_01')
            with service.store.db() as db:sid=service.store._owned(db,'alice',cid)['session_id']
            service._request=lambda *a,**kw:(202,{'run_id':'run_'+'a'*32})
            service._dispatch('alice',cid,turn['turn_id'],sid,'synthetic compaction integration','compaction_integration_01')
            binding=service.native.row('alice',cid,turn['turn_id'])['binding']
            admitted=deepcopy(host.admissions[-1])
            # The Core fixture runs normalization/preflight/budget/provider wire construction.
            # Only its final provider HTTP and OS slot/limit boundary are synthetic.
            with patch('zoneinfo.ZoneInfo',return_value=timezone(timedelta(hours=8))),tests.NativeToolHistory('runTest').history_fixture(older=True) as h:
                native=sys.modules['native_chat'];gateway=h.proxy.gateway_for(h.f.grants.resolve(h.f.token))
                schemas=h.body['tools']
                scope=native.NativeChatScope(binding,lambda:service.native.authorized(binding),
                    model_schemas=lambda:service.native.schemas(binding),reasoning_effort=lambda:'none',
                    call_tool=lambda name,args:service.native.host_tool(binding,name,args))
                gateway.scope=scope;gateway.budget.active_tasks=lambda:{('alice',turn['turn_id'])}
                service.hermes.gateways[turn['turn_id']]=gateway
                service.native.register_schemas(binding,dict(binding=binding,model_schemas=schemas,
                    catalog_sha256='a'*64,registry_generation=1,reasoning_effort='none'))
                token=h.f.grants.mint('alice',turn['turn_id'],binding['lease'])
                admitted['token']=token
                import conversation_native
                admitted['native_chat']['environment'].update(profile=conversation_native.NATIVE_ROOT+'/profiles/'+conversation_native.sha(b'alice'),
                    workspace=conversation_native.execution_workspace(binding))
                path=service.run_root/'admissions'/(sid+'.json');path.parent.mkdir(parents=True)
                path.write_text(json.dumps(admitted),encoding='utf-8')
                worker_path=SOURCE.parents[2]/'fc-coins/fc-review-channel-20261026/source/hermes_worker.py'
                nodes=[n for n in ast.parse(worker_path.read_text('utf-8')).body
                    if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('NoRedirect','admission','call_tool','install_native_compaction_relay')]
                self.assertEqual(len(nodes),4)
                private=[]
                def opening(*args):
                    def request(req,**kw):
                        self.assertEqual(urlsplit(req.full_url).path,'/fc/tools/call')
                        payload=json.loads(req.data);private.append(payload)
                        result=h.proxy.dispatch('POST','/fc/tools/call',req.get_header('Authorization')[7:],payload)
                        return io.BytesIO(json.dumps(result).encode())
                    return types.SimpleNamespace(open=request)
                namespace=dict(Path=Path,re=re,json=json,Request=Request,HTTPRedirectHandler=HTTPRedirectHandler,HTTPError=HTTPError,
                    build_opener=opening,ADMISSIONS=path.parent,MAX_PROVIDER_WIRE_BYTES=10*1024*1024,
                    PROXY='http://127.0.0.1:8940',
                    ContextVar=__import__('contextvars').ContextVar,RLock=__import__('threading').RLock)
                exec(compile(ast.Module(body=nodes,type_ignores=[]),str(worker_path),'exec'),namespace)
                def check():
                    current=namespace['admission'](sid)
                    if current['ready'] is not True or current['run_id']!=binding['run_id'] or service.native.authorized(binding) is not True:
                        raise PermissionError('synthetic inactive')
                def relay(value):return json.loads(namespace['call_tool']('fs.native.compacted_request',value,session_id=sid))
                def dispatch(body):return h.proxy.dispatch('POST','/v1/chat/completions',token,body)
                dispatch(deepcopy(h.body))
                messages=h.body['messages']+h.replay(h.calls)+[dict(role='user',content='continue this same synthetic task')]
                # Engine summary/window selection and persistence are explicit dependencies;
                # compressed messages/event and the facade's return/finally are original SDK code.
                class Agent(facade.CompressionFacadeMixin):
                    session_id=sid;platform='api_server';_memory_manager=None;event_callback=None;log_prefix=''
                    tools=schemas
                    def __init__(self):
                        self.context_compressor=sdk.SDKAssembler();self.context_compressor.compression_count=0
                        self.context_compressor._summary_has_user_turn=True
                    def _conversation_root_id(self):return sid
                    def _emit_diagnostic_status(self,*a):pass
                    def _build_api_kwargs(self,messages,**kw):return dict(deepcopy(h.body),messages=deepcopy(messages))
                def compress(agent,messages,prompt,**kwargs):
                    engine=agent.context_compressor;start=len(messages)-1
                    result=engine._assemble_compressed(messages,0,start,
                        types.SimpleNamespace(tail_start=start,summary_indices=set()),sdk.SUMMARY_PREFIX+'\nSynthetic summary provider dependency.')
                    engine.compression_count+=1
                    sdk._finish_compaction_boundary(agent,result,new_system_prompt=prompt,old_session_id=None,
                        in_place=True,compacted_in_place=True,session_commit_succeeded=True,defer_context_engine_notification=False,
                        compression_made_progress=True,compression_used_fallback=False,compression_feasibility_skip=False,task_id=kwargs['task_id'])
                    return result,prompt
                portal=types.SimpleNamespace(get_conversation_context=lambda:sid,get_affinity_scope=lambda:sid,
                    reset_affinity_scope=lambda *a:None,reset_conversation_context=lambda *a:None,
                    set_affinity_scope=lambda *a:None,set_conversation_context=lambda *a:None)
                dependencies={'agent.conversation_compression':types.SimpleNamespace(CompressionCommitFence=object,compress_context=compress,
                    reset_context_compression_timeout_outcome=lambda *a:None,resolve_context_compression_timeouts=lambda:(0,0),_stamp_scoped_twins=lambda *a:None),
                    'agent.portal_tags':portal,'agent.prompt_cache_scope':types.SimpleNamespace(declared_conversation_scope_safe=lambda *a:None),
                    'agent.context_compressor':types.SimpleNamespace(_DB_PERSISTED_MARKER='_db_persisted'),
                    'agent.message_sanitization':types.SimpleNamespace(sanitize_outbound_kwargs=lambda agent,kwargs:None)}
                with patch.dict(sys.modules,dependencies):
                    agent=Agent();namespace['install_native_compaction_relay'](agent,binding,'none',check,relay)
                    result,prompt=agent._compress_context(messages,'',task_id=binding['turn_id'])
                    self.assertNotEqual(result,messages);self.assertEqual(private,[])
                    # The SDK wire builder excludes its own underscore persistence scaffolding.
                    wire=[{k:v for k,v in m.items() if not k.startswith('_')} for m in result]
                    body=agent._build_api_kwargs(wire)
                    self.assertEqual(len(private),1)
                    self.assertEqual(private[0]['name'],'fs.native.compacted_request')
                    self.assertEqual(set(private[0]['arguments']),{'binding','compression_count','messages_sha256'})
                    self.assertEqual(private[0]['arguments']['binding'],binding)
                    self.assertIs(service.hermes.gateways[turn['turn_id']],gateway)
                    newer=deepcopy(h.calls)
                    for call in newer:call['function']['arguments']='{"round":1}'
                    h.responses.append(newer)
                    dispatch(body)
                    body['messages']+=h.replay(newer)
                    self.assertEqual(dispatch(body)['choices'][0]['message']['content'],'synthetic answer')
                self.assertEqual(len(h.wire),3)
                with h.db() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM model_calls WHERE state='succeeded'").fetchone()[0],3)

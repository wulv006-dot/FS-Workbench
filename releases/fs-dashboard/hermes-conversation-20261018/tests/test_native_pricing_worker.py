"""Native pricing constructor contract; SDK/Docker boundaries are explicit doubles."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import test_conversation_file_loop as fixture


class NativePricingWorkerTests(unittest.TestCase):
    def test_pricing_retains_native_context_and_uses_host_schema_and_high(self):
        import conversation_native as native
        pricing=fixture.load('worker_pricing_schema',fixture.SOURCE.parents[2]/'fc-coins/fc-pricing-v3-20261026/source/pricing_operations.py')
        original=pricing.schema();allowed=[a for a in pricing.ACTIONS if a not in pricing.MUTATING]
        schema=deepcopy(original);schema['function']['parameters']['properties']['action']['enum']=allowed
        capabilities=dict(allowed_actions=allowed,tool_schema=schema)
        bound=dict(owner='alice',conversation_id='b'*32,turn_id='c'*32,request_id='pricing_native_01',
                   session_id='hc_'+'a'*64,lease='d'*32,run_id='run_'+'e'*32)
        item=dict(session_id=bound['session_id'],model='deepseek-flash',token='f'*43,conversation=True,
                  ready=True,run_id=bound['run_id'],prompt='',reasoning_effort='high',native_chat=dict(
                  binding=bound,environment={'files':[]},pricing=dict(conversation=bound['conversation_id'],
                  mode='daily_review',runs=['00000000-0000-4000-8000-000000000001'],
                  expires_at='2099-01-01T00:00:00+00:00',source='daily',source_quote_run=None,source_quote_sha256=None)))
        with fixture.WorkerEnvironmentTests().runtime() as (worker,adapter,calls,modules):
            current=[item];worker.admission=lambda sid:current[0]
            session_db=object();adapter._ensure_session_db=lambda:session_db
            @contextmanager
            def scope(**kwargs):yield
            def check(task_id=None):
                if not backend.authorize() or task_id not in (None,bound['turn_id']):
                    raise PermissionError('native_worker_inactive')
            backend=types.SimpleNamespace(profile=Path('/native/alice'),environment={'workspace':'/workspace'},
                scope=scope,check=check,ensure_environment=lambda:None,observe_pending=lambda *a:None,
                close_environment=lambda:None)
            def pricing_call(arguments,task_id=None):
                check(task_id);value=backend.pricing_rpc(arguments);check(task_id);return value
            backend.pricing_call=pricing_call
            def build_backend(value,authorize):backend.authorize=authorize;return backend
            class Agent:
                def __init__(self,**kwargs):
                    calls['native_kwargs']=kwargs
                    self.enabled_toolsets=kwargs['enabled_toolsets'];self.disabled_toolsets=kwargs['disabled_toolsets']
                    self.tools=[schema];self._tool_snapshot_generation=7
                def run_conversation(self,*a,**kw):check(kw.get('task_id'));return kw['task_id']
                def close(self):pass
            modules['run_agent'].AIAgent=Agent
            modules['toolsets'].resolve_toolset=lambda name,**kw:list(calls['toolsets'].get(name,()))
            registered=[];rpc=[]
            def call_tool(name,arguments,**kwargs):
                rpc.append((name,deepcopy(arguments),kwargs))
                if name=='fs.native.check':return '{"authorized":true}'
                if name=='fs.native.pricing':return json.dumps(capabilities)
                if name=='fs.native.register_schemas':registered.append(arguments);return '{"registered":true}'
                raise AssertionError(name)
            worker.call_tool=call_tool
            overrides={'hermes_cli.tools_config':types.SimpleNamespace(_get_platform_tools=lambda *a:{'file','terminal','memory','skills','fs_readonly'}),
                       'model_tools':types.SimpleNamespace(get_tool_definitions=lambda **kw:[schema]),
                       'hermes_constants':types.SimpleNamespace(resolve_reasoning_config=lambda *a:{'enabled':False}),
                       'agent.reasoning_params':types.SimpleNamespace(unset_reasoning_default=lambda a:{'enabled':False})}
            with patch.dict(sys.modules,overrides),patch.object(native,'NativeDockerBackend',side_effect=build_backend), \
                    patch.object(native,'install_native_backend_guards'),patch.object(worker,'install_native_compaction_relay'), \
                    patch.object(modules['hermes_cli.config'],'load_config',return_value={
                        'memory':{'write_approval':True},'skills':{'write_approval':True}},create=True):
                agent=adapter._create_native_agent(item)
                config=calls['native_kwargs']
                self.assertEqual(set(config['enabled_toolsets']),{'file','terminal','memory','skills','fs_native_pricing_readonly'})
                self.assertEqual(config['disabled_toolsets'],['fs_materials','fs_native_pricing_unavailable'])
                self.assertEqual(config['reasoning_config'],{'enabled':True,'effort':'high'})
                self.assertIs(config['session_db'],session_db)
                for key in ('skip_memory','skip_context_files','skip_background_review'):self.assertIs(config[key],False)
                self.assertIs(config['load_soul_identity'],True)
                self.assertEqual(agent.run_conversation('original text'),bound['turn_id'])
                self.assertEqual(registered[0]['model_schemas'],[schema]);self.assertEqual(registered[0]['reasoning_effort'],'high')
                self.assertEqual(rpc[1][0],'fs.native.pricing')
                self.assertEqual(rpc[1][1],dict(binding=bound,arguments={'action':'capabilities'}))
                selection=calls['toolsets']['fs_native_pricing_readonly']
                self.assertTrue(set(modules['fs_native_readonly'].TOOLS)<=set(selection))
                self.assertFalse(set(modules['fs_native_readonly'].CUSTOMER_TOOLS)&set(selection))
                self.assertEqual(selection[-1],'mcp__fcro__fs_pricing_control')
                changed=deepcopy(item);changed['native_chat']['pricing']['source']='changed';current[0]=changed
                with self.assertRaises(PermissionError):agent.run_conversation('inactive')
                current[0]=item
                for bad in ({},dict(capabilities,tool_schema={})):
                    capabilities=bad
                    with self.assertRaises(PermissionError):adapter._create_native_agent(item)
                capabilities=dict(allowed_actions=allowed,tool_schema=schema)
                changed=deepcopy(item);changed.pop('reasoning_effort')
                with self.assertRaises(PermissionError):adapter._create_native_agent(changed)
                selector=fixture.load('pinned_native_pricing_selection',Path(__file__).parent/'sdk71.py')
                native_names={'terminal','read_file','write_file','memory','skill_view'}
                for configured in ('all','current_profile_bundle'):
                    with self.subTest(configured=configured):
                        overrides['hermes_cli.tools_config']._get_platform_tools=lambda *a:{configured}
                        adapter._create_native_agent(item)
                        selected_config=calls['native_kwargs']
                        resolved={key:set(value) for key,value in calls['toolsets'].items()}
                        resolved['fs_readonly']=set(modules['fs_native_readonly'].TOOLS)|set(modules['fs_native_readonly'].CUSTOMER_TOOLS)
                        resolved['current_profile_bundle']=resolved['fs_readonly']|native_names|{'mcp__fcro__fs_pricing_control'}
                        resolved['all']=set().union(*resolved.values())
                        selected=selector.select_resolved_tool_names(selected_config['enabled_toolsets'],
                            selected_config['disabled_toolsets'],resolved)
                        self.assertFalse(set(modules['fs_native_readonly'].CUSTOMER_TOOLS)&selected)
                        self.assertTrue(set(modules['fs_native_readonly'].TOOLS)<=selected)
                        self.assertTrue(native_names<=selected)
                        self.assertIn('mcp__fcro__fs_pricing_control',selected)
        self.assertIn('recommend',original['function']['parameters']['properties']['action']['enum'])


if __name__=='__main__':unittest.main()

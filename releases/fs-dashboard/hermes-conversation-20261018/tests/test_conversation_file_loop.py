"""Synthetic worker/tool loop through real A bindings + B consumer + ScopedTools.

No provider, credentials, HTTP business service or production state is involved.
"""
import importlib.util
import asyncio
import builtins
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from email.message import Message
from contextlib import contextmanager, nullcontext
from datetime import timezone
import threading

SOURCE = Path(__file__).resolve().parents[1] / 'source'
PACKAGES = SOURCE.parents[1]
CORE = PACKAGES / 'hermes-v2-core-20261020/source'
STRATEGY = PACKAGES / 'hermes-v2-strategy-20261021/source'
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(CORE))
from conversation_store import ConversationStore
from conversation_files import ConversationFiles
from conversation_file_bindings import context_factory
from conversation_http import handle


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class WorkerFileLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from conversation_file_tools import attach_conversation_file_tools, file_prompt
        cls.attach = staticmethod(attach_conversation_file_tools)
        cls.prompt = staticmethod(file_prompt)
        # Load the real allowlist and task-scope gateway; only unrelated strategies are mocked.
        pilot = types.ModuleType('pilot')
        pilot.digest = lambda x: 'fixture'
        pilot.encoded = json.dumps
        pilot.TOOLS = ()
        pilot.SHANGHAI = None
        research = types.ModuleType('research')
        research.RESEARCH_NAMES = ()
        strategies = types.ModuleType('strategy_tools')
        strategies.NAMES = ()
        strategies.call = lambda *args: (_ for _ in ()).throw(AssertionError('unexpected strategy'))
        with patch.dict(sys.modules, {'pilot': pilot, 'research': research, 'strategy_tools': strategies}):
            contract = load('file_loop_runs_contract', STRATEGY / 'runs_contract.py')
            with patch.dict(sys.modules, {'runs_contract': contract}):
                cls.gateway_module = load('file_loop_proxy', STRATEGY / 'proxy_gateway.py')
            contract = load('deployed_file_contract', PACKAGES.parent / 'fc-coins/fc-pricing-v2-20261022/source/runs_contract.py')
            with patch.dict(sys.modules, {'runs_contract': contract}):
                cls.deployed_gateway = load('deployed_file_proxy', PACKAGES.parent / 'fc-coins/fc-review-channel-20261026/source/proxy_gateway.py')
        cls.strategies = strategies

    def test_active_service_submit_and_admission_attach_without_preparing_read(self):
        self.service_submit_admission(CORE / 'conversation_service.py')

    def test_deployed_service_submit_and_admission_preserves_pricing_lane(self):
        self.service_submit_admission(PACKAGES.parent / 'fc-coins/fc-pricing-v3-20261026/source/conversation_service.py')

    def service_submit_admission(self, service_path):
        @contextmanager
        def guard(_):
            yield True
        controller = types.ModuleType('controller')
        controller.NoRedirect = object
        controller.admission_guard = guard
        admissions = []
        controller.atomic = lambda path, value, **kw: admissions.append(json.loads(json.dumps(value)))
        evidence = types.ModuleType('fs_evidence')
        book = types.SimpleNamespace(capture_id='synthetic', call=lambda n, a: {'old': n})
        evidence.build_book = lambda *a, **kw: book
        inprocess = types.ModuleType('fs_inprocess')
        inprocess.native_gateway = lambda daily, scope, **kw: types.SimpleNamespace(scope=scope)
        inprocess.spending_hold = lambda *a,**kw: False
        inprocess.gateway = lambda *a, **kw: types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model': 'synthetic'}))
        pilot = types.ModuleType('pilot')
        pilot.SHANGHAI, pilot.digest, pilot.encoded = timezone.utc, lambda _: 'synthetic', json.dumps
        context_module = types.ModuleType('business_context')
        knowledge = {'version': 'test', 'skills': [], 'text': 'synthetic', 'identity': {}, 'files': [],
                     'memory_path': None, 'native_skip_reason': 'fixture'}
        context_module.freeze_learning = lambda *a, **kw: knowledge
        skills = types.ModuleType('skill_bundle')
        skills.load_bundle = lambda *a, **kw: {}
        registry = types.ModuleType('learning_registry')
        registry.manifest, registry.record_use = lambda *a: {}, lambda *a: None
        catalog = types.ModuleType('knowledge_catalog')
        catalog.task_selection = lambda *a, **kw: {}
        injected = {'controller': controller, 'fs_evidence': evidence, 'fs_inprocess': inprocess,
                    'pilot': pilot, 'business_context': context_module, 'skill_bundle': skills,
                    'learning_registry': registry, 'knowledge_catalog': catalog}
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, injected):
            module = load('file_loop_active_service', service_path)
            module.attach_current_learning = lambda *a: None
            module.attach_customer_tracking = lambda *a: None
            task = {'id': 'a' * 32, 'state': 'QUEUED'}
            tasks = types.SimpleNamespace(db=lambda: nullcontext(None), create=lambda *a: task,
                reserve_dispatch=lambda *a: None, bind_run=lambda *a: None)
            hermes = types.SimpleNamespace(root=Path(directory), lock=threading.RLock(), daily=None,
                authorizer=lambda user: user == 'alice', tasks=tasks, detail=None, read_range=None,
                diagnostics=None, source_root=Path(directory), clock=lambda: 0,
                proxy=types.SimpleNamespace(background=None), tokens={}, books={}, gateways={},
                grants=types.SimpleNamespace(mint=lambda *a, **kw: 'synthetic-not-a-credential'))
            service = module.ConversationService(hermes, Path(directory) / 'data', Path(directory) / 'run')
            if hasattr(service, 'pricing'):
                self.assertNotEqual(service.store.root, service.pricing.store.root)
                service.pricing.pool.shutdown(wait=True)
                service.pricing_pool.shutdown(wait=True)
                service._pricing_lane = lambda *a: False
            service.pool.shutdown(wait=True)
            jobs = []
            service.pool = types.SimpleNamespace(submit=lambda fn, *args: jobs.append((fn, args)))
            cid = service.create('alice')['conversation_id']
            item = ConversationFiles(service.store).save('alice', cid, 'a.csv', b'a,b\n1,2', 'upload_001')
            submitted = service.submit('alice', cid, 'modify attached table', 'turn_001', [item['file_id']])
            self.assertEqual(service.submit('alice', cid, 'modify attached table', 'turn_001', [item['file_id']])['turn_id'], submitted['turn_id'])
            self.assertEqual(len(jobs), 1)
            results = []
            service._request = lambda *a, **kw: (202, {'run_id': 'run_' + 'b' * 32})
            def monitor(owner, cid, turn_id, run_id, live):
                if getattr(service, 'native', None) is not None:
                    environment = admissions[-1]['native_chat']['environment']
                    attached = Path(environment['workspace']) / environment['files'][0]['path']
                    self.assertEqual(attached.read_bytes(), b'a,b\n1,2')
                    (Path(environment['workspace']) / 'result.csv').write_bytes(b'a,b\n1,3')
                    results.extend(service.native.complete(owner, cid, turn_id, run_id))
                    service.store.set_state(owner, cid, turn_id, 'completed')
                    return
                catalog = book.call('fc.list_conversation_files', {})
                self.assertEqual(catalog['items'][0]['file_id'], item['file_id'])
                results.append(book.call('fc.revise_conversation_file', {'file_id': item['file_id'],
                    'edits': [], 'format': 'xlsx', 'request_id': 'revision_001'}))
                service.store.set_state(owner, cid, turn_id, 'completed')
            service._monitor = monitor
            fn, args = jobs[0]
            fn(*args)
            self.assertEqual(len(results), 1)  # No preparing-stage catalog prefetch may abort dispatch.
            admission = next(value for value in admissions if value.get('ready') is False)
            if getattr(service, 'native', None) is not None:
                self.assertIn('native_chat', admission)
                self.assertEqual(admission['prompt'], '')
            else:
                self.assertIn(self.prompt(), admission['prompt'])
            self.assertTrue(admissions[-1]['ready'])
            self.assertEqual(service.detail('alice', cid)['turns'][0]['state'], 'completed')
            if hasattr(service, 'pricing'):
                service._pricing_lane = lambda *a: True
                with self.assertRaisesRegex(PermissionError, 'pricing_file_attachments_unavailable'):
                    service.submit('alice', cid, 'no file access in pricing', 'pricing_001', [item['file_id']])
                self.assertEqual(len(jobs), 1)

    def test_upload_bind_scripted_worker_revision_download_and_followup(self):
        self.upload_loop(handle, self.gateway_module)

    def test_deployed_http_and_allowlist_upload_paging_revision_followup(self):
        module = load('deployed_file_http', PACKAGES.parent / 'fc-coins/fc-pricing-v3-20261026/source/conversation_http.py')
        self.upload_loop(module.handle, self.deployed_gateway)

    def upload_loop(self, http_handle, gateway_module):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create('alice')['conversation_id']
            files = ConversationFiles(store)
            service = types.SimpleNamespace(store=store, detail=store.detail)
            service.submit = lambda owner, cid, text, request_id, file_ids=None: store.reserve_turn(owner, cid, text, request_id, file_ids)
            def http(method, suffix, body=b'', extra=None, user='alice'):
                headers = Message()
                for key, value in {'Content-Length': str(len(body)), 'Content-Type': 'application/json',
                                   'X-FS-Advisor-Action': 'submit', 'Sec-Fetch-Site': 'same-origin', **(extra or {})}.items():
                    headers[key] = value
                status, response_headers = [], {}
                handler = types.SimpleNamespace(headers=headers, rfile=io.BytesIO(body), wfile=io.BytesIO(),
                    connection=types.SimpleNamespace(settimeout=lambda _: None), send_response=status.append,
                    send_header=lambda k, v: response_headers.update({k: v}), end_headers=lambda: None)
                http_handle(handler, method, urlsplit('/api/hermes/conversations/' + cid + suffix), user, service, lambda _: True)
                return status[0], handler.wfile.getvalue(), response_headers

            raw = ('item,amount\n' + ''.join('row,2\n' for _ in range(450))).encode()
            status, payload, _ = http('POST', '/files', raw, {'Content-Type': 'application/octet-stream',
                'X-FS-Filename': 'sample.csv', 'X-FS-Request-ID': 'upload_001'})
            self.assertEqual(status, 201)
            original = json.loads(payload)
            hidden = files.save('alice', cid, 'not-bound.csv', b'private', 'upload_002')

            def start(file_ids, request_id):
                status, payload, _ = http('POST', '/turns', json.dumps({'text': '按要求修改金额',
                    'client_request_id': request_id, 'file_ids': file_ids}).encode())
                self.assertEqual(status, 202)
                turn = json.loads(payload)
                store.bind_run('alice', cid, turn['turn_id'], 'run_' + turn['turn_id'])
                context = context_factory(store, 'alice', cid, turn['turn_id'], lambda _: True)
                book = types.SimpleNamespace(capture_id='synthetic', call=lambda n, a: {'original_tool': n})
                self.attach(book, context)
                task = {'state': 'RUNNING', 'lease': 'original-lease', 'spec': {'snapshot_id': 'synthetic'}}
                tasks = types.SimpleNamespace(get=lambda task_id, owner: task if owner == 'alice' else (_ for _ in ()).throw(PermissionError()))
                gateway = gateway_module.ScopedTools(tasks, book, lambda: 0)
                def worker_call(name, arguments, lease='original-lease'):
                    # The scripted worker supplies only wire tool names and arguments.
                    with patch.dict(sys.modules, {'strategy_tools': self.strategies}):
                        receipt = gateway.call('alice', 'task-fixture', lease, 'mcp__fcro__fc_' + name, arguments)
                    return receipt['data']
                return turn, context, worker_call

            turn, context, call = start([original['file_id']], 'turn_001')
            catalog = call('list_conversation_files', {})
            self.assertEqual(catalog['items'][0]['file_id'], original['file_id'])
            self.assertEqual(catalog['material_role'], 'untrusted_data')
            with self.assertRaises(PermissionError):
                call('list_conversation_files', {}, lease='wrong-lease')
            with self.assertRaises(LookupError):
                call('read_conversation_file', {'file_id': hidden['file_id'], 'sheet': 0, 'offset': 0, 'limit': 200})
            combined, offset = [], 0
            while offset is not None:
                result = call('read_conversation_file', {'file_id': original['file_id'], 'sheet': 0, 'offset': offset, 'limit': 200})
                self.assertFalse(result['complete'])
                combined.extend(result['sheets'][0]['rows'])
                offset = result['next_offset']
            self.assertEqual(len(combined), 451)
            self.assertEqual(sum(int(row[1]) for row in combined[1:]), 900)
            arguments = {'file_id': original['file_id'], 'edits': [{'sheet': 0, 'row': 450, 'column': 1, 'value': 7}],
                         'format': 'xlsx', 'request_id': 'revision_001'}
            derived = call('revise_conversation_file', arguments)
            self.assertEqual(call('revise_conversation_file', arguments), derived)
            self.assertEqual(context.read_table(derived['file_id'])['sheets'][0]['rows'][450][1], 7)
            status, content, headers = http('GET', '/files/' + derived['file_id'])
            self.assertEqual(status, 200)
            self.assertTrue(content.startswith(b'PK'))
            self.assertEqual(http('GET', '/files/' + derived['file_id'], user='bob')[0], 404)
            store.set_state('alice', cid, turn['turn_id'], 'completed')
            with self.assertRaises(PermissionError):
                call('list_conversation_files', {})
            followup, next_context, next_call = start([derived['file_id']], 'turn_002')
            third = next_call('revise_conversation_file', dict(arguments, file_id=derived['file_id'], edits=[], format='csv'))
            self.assertEqual(third['version'], 3)
            self.assertEqual(third['parent_id'], derived['file_id'])
            self.assertEqual(files.read('alice', cid, original['file_id'])['content'], raw)
            self.assertIn(third['file_id'], [i['file_id'] for i in next_context.catalog()['items']])
            self.assertIn('fc.list_conversation_files', self.prompt())


class WorkerEnvironmentTests(unittest.TestCase):
    @contextmanager
    def runtime(self, *, original_loader=False, initialization_error=None, execution=None, extra_tool=False,
                executor=None, worker_error=None, agent_error=None, agent_result=None, sync_executor=None):
        from conversation_file_tools import WIRE_NAMES
        wires = tuple(WIRE_NAMES) if execution else ('mcp__fcro__fc_read_skill', 'mcp__fcro__fc_list_conversation_files')
        calls = {'dotenv_reads': 0, 'registered': [], 'agent': None, 'executed': False}
        modules = {name: types.ModuleType(name) for name in (
            'proxy_gateway', 'runs_contract', 'hermes_cli', 'hermes_cli.config',
            'hermes_cli.env_loader', 'aiohttp', 'gateway', 'gateway.config',
            'gateway.platforms', 'gateway.platforms.api_server', 'gateway.platforms.api_server_runs',
            'tools', 'tools.registry', 'toolsets', 'run_agent', 'skill_bundle', 'agent', 'agent.context_compressor', 'agent.system_prompt')}
        proxy = modules['proxy_gateway']
        proxy.schemas = lambda: [{'function': {'name': name}} for name in wires]
        proxy.MAX_PROVIDER_CONTEXT_TOKENS = proxy.MAX_HERMES_OUTPUT_TOKENS = 1000
        proxy.MAX_PROVIDER_WIRE_BYTES = 10000000
        contract = modules['runs_contract']
        contract.WIRE_TOOLS, contract.SEMANTIC_TOOLS, contract.PIN = wires, ('fc.read_skill', 'fc.list_conversation_files'), 'fixture'
        loader = modules['hermes_cli.env_loader']
        def denied(**kwargs):
            calls['dotenv_reads'] += 1
            raise PermissionError('synthetic /profile/.env read refused')
        loader.load_hermes_dotenv = denied
        dotenv_library = object(); loader.DotEnv = dotenv_library
        modules['hermes_cli'].env_loader = loader
        modules['hermes_cli'].config = modules['hermes_cli.config']
        modules['aiohttp'].web = types.SimpleNamespace(middleware=lambda fn: fn)
        modules['gateway.platforms'].api_server_runs = modules['gateway.platforms.api_server_runs']
        async def execute(*args, **kwargs):
            calls['executed'] = True
        modules['gateway.platforms.api_server_runs']._execute_run = executor or execute
        result = ({'completed': True} if agent_result is None else agent_result, {}, {})
        def sync_execute(adapter, run, agent, approval_notify, *, _api_server):
            calls['sync_calls'] = calls.get('sync_calls', 0) + 1
            if worker_error is not None:
                raise worker_error
            return result
        modules['gateway.platforms.api_server_runs']._run_agent_sync = sync_executor or sync_execute
        calls['sync_result'] = result
        class Config:
            def __init__(self, **kwargs): self.values = kwargs
        modules['gateway.config'].PlatformConfig = Config
        class Adapter:
            def __init__(self, config):
                if initialization_error:
                    raise initialization_error
                self.config = config
                self._stopping_run_ids = set(); self._shutdown_interrupted_run_ids = set()
                self._active_run_agents = {}; self._run_statuses = {}
            def _set_run_status(self, run_id, status, **fields):
                value = dict(self._run_statuses.get(run_id, {}), status=status, **fields)
                self._run_statuses[run_id] = json.loads(json.dumps(value))
                return value
            def _ensure_session_db(self): return 'synthetic-db'
            def _http_route_table(self):
                return [('GET', '/v1/capabilities'), ('POST', '/v1/runs'),
                        ('POST', '/v1/runs/{run_id}/stop'), ('POST', '/v1/chat/completions')]
        modules['gateway.platforms.api_server'].APIServerAdapter = Adapter
        registry_rows={}
        def register(**kw):
            calls['registered'].append(kw['name'])
            registry_rows[(kw.get('scope'),kw['name'])]=types.SimpleNamespace(**kw)
        modules['tools.registry'].registry = types.SimpleNamespace(register=register,
            get_entry=lambda name,scope=None:registry_rows.get((scope,name)))
        modules['fs_native_readonly']=load('fs_native_readonly',PACKAGES/'hermes-server-unify-20261022/fs_readonly/__init__.py')
        modules['toolsets'].create_custom_toolset = lambda name, *args, **kwargs: calls.setdefault('toolsets', {}).update({name:kwargs['tools']})
        class Compressor:
            _config_context_length = 1000
            protect_first_n = protect_last_n = proactive_prune_tokens = 1
            proactive_prune_min_result_chars = proactive_prune_min_reclaim_tokens = 1
        modules['agent.context_compressor'].ContextCompressor = Compressor
        class Agent:
            def __init__(self, **kwargs):
                if agent_error is not None:
                    raise agent_error
                calls['agent'] = kwargs
                self.context_compressor = Compressor(); self.valid_tool_names = wires
                self.tools=[{'function':{'name':v}} for v in wires]+([{'function':{'name':'forbidden'}}] if extra_tool else [])
                self.ephemeral_system_prompt=kwargs['ephemeral_system_prompt']
                self.skip_context_files=kwargs['skip_context_files'];self.load_soul_identity=kwargs['load_soul_identity']
                self.skip_background_review=kwargs['skip_background_review']
                self._memory_enabled=False;self._memory_store=None;self._memory_manager=None
            def close(self):calls['closed']=True
        modules['run_agent'].AIAgent = Agent
        modules['agent.system_prompt'].build_system_prompt=lambda agent:'Actual SDK fixture system prefix'
        modules['skill_bundle'].load_bundle = lambda *args, **kw: self.fail('no eager conversation bundle')
        modules['skill_bundle'].prompt = lambda *args: 'unused'
        real_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == 'run_agent':
                # Simulate the pinned run_agent.py:96 import-time loader call.
                loader.load_hermes_dotenv(hermes_home='/profile', project_env=Path('/opt/hermes/.env'))
            return real_import(name, *args, **kwargs)
        with patch.dict(sys.modules, modules):
            worker = load('isolated_deployed_worker', PACKAGES.parent / 'fc-coins/fc-review-channel-20261026/source/hermes_worker.py')
            if original_loader:
                worker._fs_no_implicit_dotenv = denied
            item = {'model': 'deepseek-flash', 'token': 'fixture-task-token', 'conversation': True,
                    'prompt': 'synthetic', 'ready': True}
            if execution:
                item.pop('conversation');item['prompt']=execution['system_prompt']
                item['materials']={'execution':execution};item['run_id']='run_'+'d'*32
            worker.admission = lambda sid: item
            with patch('builtins.__import__', importing):
                adapter = worker.make_adapter('fixture-listener-key')
                if execution:adapter._material_admitted_inputs={'mg_'+'a'*64:execution['input']}
                self.assertIs(loader.DotEnv, dotenv_library)
                yield worker, adapter, calls, modules

    def test_official_import_refusal_is_reproduced_and_fs_constructor_does_not_read_dotenv(self):
        with self.assertRaisesRegex(PermissionError, 'synthetic /profile/.env'):
            with self.runtime(original_loader=True):
                self.fail('unfixed loader must fail before construction')
        original_read = Path.read_bytes
        with self.runtime() as (worker, adapter, calls, modules):
            self.assertEqual(calls['dotenv_reads'], 0)
            self.assertIs(Path.read_bytes, original_read)
            self.assertEqual(modules['hermes_cli.config'].get_config_path(),
                             Path(worker.__file__).with_name('runtime-config.yaml'))
            self.assertEqual(adapter.config.values['extra'], {'host': '127.0.0.1', 'port': 8941,
                             'key': 'fixture-listener-key', 'model_name': 'deepseek-flash'})
            self.assertEqual(calls['registered'], list(worker.WIRE_TOOLS))
            self.assertEqual(calls['toolsets']['fs_fc_readonly'], list(worker.WIRE_TOOLS))
            self.assertIn(('GET', '/v1/capabilities'), adapter._http_route_table())
            self.assertIn(('POST', '/v1/runs/{run_id}/stop'), adapter._http_route_table())
            self.assertNotIn(('POST', '/v1/chat/completions'), adapter._http_route_table())
            adapter._create_agent(session_id='hc_' + 'a' * 64)
            self.assertEqual(calls['agent']['base_url'], 'http://127.0.0.1:8940/v1')
            self.assertEqual(calls['agent']['api_key'], 'fixture-task-token')
            self.assertEqual(calls['agent']['model'], 'deepseek-flash')
            self.assertIsNone(calls['agent']['fallback_model'])
            self.assertTrue(calls['agent']['skip_memory'])
            run = types.SimpleNamespace(run_id='run_' + 'a' * 32, session_id='hc_' + 'a' * 64)
            asyncio.run(modules['gateway.platforms.api_server_runs']._execute_run(adapter, run, _api_server=None))
            self.assertTrue(calls['executed'])
            self.assertEqual(calls['dotenv_reads'], 0)

    def test_native_agent_uses_owner_context_and_actual_schemas_not_fc_fixed_tools(self):
        import conversation_native
        bound=dict(owner='alice',conversation_id='b'*32,turn_id='c'*32,request_id='native_req_01',session_id='hc_'+'a'*64,lease='d'*32,run_id='run_'+'e'*32)
        with self.runtime() as (worker,adapter,calls,modules):
            item={'session_id':bound['session_id'],'model':'deepseek-flash','token':'f'*43,
                  'conversation':True,'ready':True,'run_id':bound['run_id'],'prompt':'',
                  'native_chat':{'binding':bound,'environment':{'files':[]},'key':'native-key','fingerprint':'0'*64}}
            worker.admission=lambda sid:item
            adapter._ensure_session_db=lambda:types.SimpleNamespace(native_owner_profile=True)
            @contextmanager
            def native_scope(**scope_kwargs):
                calls['native_scope']=calls.get('native_scope',0)+1
                yield
            backend=types.SimpleNamespace(profile=Path('/native/alice'),environment={'workspace':'/native/alice/workspace'},scope=native_scope,ensure_environment=lambda:None,
                check=lambda *a:None,observe_pending=lambda *a:None)
            class NativeAgent:
                def __init__(self,**kwargs):
                    calls['native_kwargs']=kwargs
                    self.tools=[{'type':'function','function':{'name':'tool_search','parameters':{'type':'object','properties':{}}}}]
                    self.enabled_toolsets=kwargs['enabled_toolsets'];self.disabled_toolsets=kwargs['disabled_toolsets']
                    self._tool_snapshot_generation=7
                def run_conversation(self,*a,**kw):calls['native_ran']=True;return {'completed':True}
                def close(self):pass
            config=types.ModuleType('hermes_cli.tools_config');config._get_platform_tools=lambda cfg,platform:{'file','terminal','memory','skills'}
            model_tools=types.ModuleType('model_tools');model_tools.get_tool_definitions=lambda **kw:[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]
            modules['run_agent'].AIAgent=NativeAgent
            registration=[]
            worker.call_tool=lambda name,args,**kw: registration.append((name,args)) or '{"registered":true}'
            with patch.dict(sys.modules,{'hermes_cli.tools_config':config,'model_tools':model_tools}),patch.object(conversation_native,'NativeDockerBackend',return_value=backend),patch.object(conversation_native,'install_native_backend_guards'),patch.object(modules['hermes_cli.config'],'load_config',return_value={'memory':{'write_approval':True},'skills':{'write_approval':True},'agent':{'reasoning_effort':'high'}},create=True),patch.dict(sys.modules,{'hermes_constants':types.SimpleNamespace(resolve_reasoning_config=lambda config,model:{'enabled':True,'effort':'high'}),'agent.reasoning_params':types.SimpleNamespace(unset_reasoning_default=lambda agent:{'enabled':True,'effort':'medium'})}):
                agent=adapter._create_agent(session_id=bound['session_id'])
                kwargs=calls['native_kwargs']
                self.assertIs(kwargs['skip_memory'],False);self.assertIs(kwargs['skip_context_files'],False)
                self.assertIs(kwargs['skip_background_review'],False);self.assertIs(kwargs['load_soul_identity'],True)
                self.assertEqual(set(kwargs['enabled_toolsets']),{'file','terminal','memory','skills','fs_readonly'})
                self.assertEqual(registration[0][0],'fs.native.register_schemas')
                self.assertEqual(registration[0][1]['binding'],bound)
                self.assertEqual(registration[0][1]['model_schemas'],agent.tools)
                self.assertEqual(kwargs['reasoning_config'],{'enabled':True,'effort':'high'})
                self.assertEqual(registration[0][1]['reasoning_effort'],'high')
                agent.run_conversation('unchanged original')
                self.assertGreaterEqual(calls['native_scope'],2)

    def test_unrelated_adapter_initialization_errors_propagate(self):
        for error in (RuntimeError('synthetic initialization failed'), PermissionError('synthetic other access denied')):
            with self.subTest(type=type(error).__name__):
                with self.assertRaises(type(error)) as result:
                    with self.runtime(initialization_error=error):
                        self.fail('initialization error must propagate')
                self.assertIs(result.exception, error)

    @staticmethod
    async def terminal_executor(adapter, run, *, _api_server):
        # Protocol fixture; the separate pinned-source check substitutes real SDK functions.
        adapter._run_statuses[run.run_id] = {'session_id': run.session_id}
        try:
            adapter._set_run_status(run.run_id, 'running')
            agent = adapter._create_agent(session_id=run.session_id)
            adapter._active_run_agents[run.run_id] = agent
            result = sys.modules['gateway.platforms.api_server_runs']._run_agent_sync(
                adapter, run, agent, None, _api_server=_api_server)
            adapter._set_run_status(run.run_id, 'failed' if result[0].get('failed') else 'completed')
        except asyncio.CancelledError:
            adapter._set_run_status(run.run_id, 'cancelled')
            raise
        except Exception:
            adapter._set_run_status(run.run_id, 'failed', error='existing SDK error field')
        finally:
            adapter._active_run_agents.pop(run.run_id, None)

    def diagnostic_run(self, adapter, modules, suffix='a', prefix='mg'):
        run = types.SimpleNamespace(run_id='run_' + suffix * 32, session_id=prefix + '_' + suffix * 64)
        asyncio.run(modules['gateway.platforms.api_server_runs']._execute_run(adapter, run, _api_server=None))
        return run, adapter._run_statuses[run.run_id]

    def test_material_diagnostic_captures_real_exception_type_at_create_and_worker_boundaries(self):
        secret = 'secret-token model-output private-reasoning https://secret.invalid/path'
        for option, phase, cls in (('agent_error', 'agent_create', ValueError),
                                   ('worker_error', 'agent_worker', PermissionError)):
            with self.subTest(option=option), self.runtime(
                    executor=self.terminal_executor, **{option: cls(secret)}) as (_, adapter, calls, modules):
                run, state = self.diagnostic_run(adapter, modules)
                self.assertEqual(state['status'], 'failed')
                self.assertEqual(state['runtime']['fs_material_diagnostic'], {
                    'version': 'materials_diagnostic_v1', 'phase': phase,
                    'exception_class': cls.__name__, 'reason': 'unknown'})
                self.assertNotIn(secret, json.dumps(state['runtime']))
                self.assertEqual(adapter._material_diagnostics, {})
                self.assertEqual(calls.get('sync_calls', 0), 0 if option == 'agent_error' else 1)

    def test_material_failed_return_is_unchanged_and_reason_never_uses_error_prose(self):
        for reason, expected in (('max_iterations', 'max_iterations'),
                                 ('secret-token model-output private-reasoning', 'unknown')):
            result = {'failed': True, 'reason': reason, 'error': 'secret-model-output'}
            with self.subTest(reason=expected), self.runtime(
                    executor=self.terminal_executor, agent_result=result) as (_, adapter, calls, modules):
                run, state = self.diagnostic_run(adapter, modules)
                note = state['runtime']['fs_material_diagnostic']
                self.assertEqual(note, {'version': 'materials_diagnostic_v1', 'phase': 'agent_returned',
                                       'exception_class': 'unknown', 'reason': expected})
                self.assertIs(calls['sync_result'][0], result)
                self.assertEqual(result['error'], 'secret-model-output')
                self.assertNotIn('secret', json.dumps(note))
                self.assertEqual(adapter._material_diagnostics, {})

    def test_material_custom_exception_cannot_spoof_whitelisted_class(self):
        forged = type('PermissionError', (PermissionError,), {})("secret private reasoning")
        class HostileMeta(type):
            def __hash__(cls): raise AssertionError('must not hash exception class')
        class HostileError(Exception, metaclass=HostileMeta):
            def __str__(self): raise AssertionError('must not stringify exception')
            def __repr__(self): raise AssertionError('must not repr exception')
        for error in (forged, HostileError()):
            with self.subTest(kind=type(error).__name__), self.runtime(
                    executor=self.terminal_executor, worker_error=error) as (_, adapter, _, modules):
                _, state = self.diagnostic_run(adapter, modules)
                self.assertEqual(state['runtime']['fs_material_diagnostic']['exception_class'], 'other_exception')

    def test_material_success_fc_human_and_old_record_keep_original_semantics(self):
        with self.runtime(executor=self.terminal_executor) as (worker, adapter, _, modules):
            for prefix in ('mg', 'fc', 'hc'):
                with self.subTest(prefix=prefix):
                    _, state = self.diagnostic_run(adapter, modules, prefix=prefix)
                    self.assertEqual(state['status'], 'completed')
                    self.assertEqual('fs_material_diagnostic' in state.get('runtime', {}), prefix == 'mg')
                    if prefix == 'mg':
                        note = state['runtime']['fs_material_diagnostic']
                        worker._material_note(adapter, 'run_' + 'a' * 32, phase='agent_create', error=ValueError('late secret'))
                        adapter._active_run_agents['run_' + 'a' * 32] = types.SimpleNamespace(
                            _hermes_api_runtime={'fs_material_context': {'version': 'fixture'}})
                        repeated = adapter._set_run_status('run_' + 'a' * 32, 'completed')
                        self.assertEqual(repeated['runtime']['fs_material_diagnostic'], note)
            old = adapter._set_run_status('run_' + 'f' * 32, 'failed', session_id='mg_' + 'f' * 64)
            self.assertNotIn('fs_material_diagnostic', old.get('runtime', {}))
            self.assertEqual(adapter._material_diagnostics, {})

    def test_official_error_caught_outside_observed_boundaries_stays_unknown(self):
        async def caught(adapter, run, *, _api_server):
            adapter._run_statuses[run.run_id] = {'session_id': run.session_id}
            adapter._set_run_status(run.run_id, 'failed', error='ValueError secret model-output private-reasoning')
        with self.runtime(executor=caught) as (_, adapter, _, modules):
            _, state = self.diagnostic_run(adapter, modules)
            self.assertEqual(state['runtime']['fs_material_diagnostic'], {
                'version': 'materials_diagnostic_v1', 'phase': 'executor',
                'exception_class': 'unknown', 'reason': 'unknown'})

    def test_material_wrapping_once_and_propagated_exception_cancel_cleanup(self):
        async def failing(adapter, run, *, _api_server):
            raise error
        for error in (ValueError('secret'), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__), self.runtime(executor=failing) as (worker, adapter, _, modules):
                api = modules['gateway.platforms.api_server_runs']
                execute, sync = api._execute_run, api._run_agent_sync
                worker.make_adapter('same-fixture-key')
                self.assertIs(api._execute_run, execute)
                self.assertIs(api._run_agent_sync, sync)
                run = types.SimpleNamespace(run_id='run_' + 'c' * 32, session_id='mg_' + 'c' * 64)
                async def check_original_exception():
                    # Python 3.9's Task.result() can rebuild CancelledError.
                    # Check the wrapper's exact exception before crossing that boundary.
                    try:
                        await api._execute_run(adapter, run, _api_server=None)
                    except type(error) as actual:
                        self.assertIs(actual, error)
                        raise
                with self.assertRaises(type(error)):
                    asyncio.run(check_original_exception())
                self.assertEqual(adapter._material_diagnostics, {})

    def test_material_sync_keeps_exact_return_and_exception_objects(self):
        observed = {}
        async def executor(adapter, run, *, _api_server):
            adapter._run_statuses[run.run_id] = {'session_id': run.session_id}
            try:
                observed['returned'] = sys.modules['gateway.platforms.api_server_runs']._run_agent_sync(
                    adapter, run, None, None, _api_server=_api_server)
            except BaseException as error:
                observed['error'] = error
                raise
        for error in (None, ValueError('secret model-output private-reasoning')):
            with self.subTest(failed=error is not None), self.runtime(
                    executor=executor, worker_error=error) as (_, adapter, calls, modules):
                if error is None:
                    self.diagnostic_run(adapter, modules)
                    self.assertIs(observed['returned'], calls['sync_result'])
                else:
                    with self.assertRaises(ValueError) as raised:
                        self.diagnostic_run(adapter, modules)
                    self.assertIs(raised.exception, error)
                    self.assertIs(observed['error'], error)
                self.assertEqual(calls['sync_calls'], 1)
                self.assertEqual(adapter._material_diagnostics, {})

    def test_material_terminal_cancel_clears_admitted_input_and_diagnostics(self):
        error = asyncio.CancelledError()
        with self.runtime(executor=self.terminal_executor, worker_error=error) as (_, adapter, _, modules):
            sid, rid = 'mg_' + 'a' * 64, 'run_' + 'a' * 32
            adapter._material_admitted_inputs = {sid: 'secret-model-input'}
            async def check_original_cancellation():
                run = types.SimpleNamespace(run_id=rid, session_id=sid)
                try:
                    await modules['gateway.platforms.api_server_runs']._execute_run(
                        adapter, run, _api_server=None)
                except asyncio.CancelledError as actual:
                    self.assertIs(actual, error)
                    raise
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(check_original_cancellation())
            self.assertEqual(adapter._run_statuses[rid]['status'], 'cancelled')
            self.assertEqual(adapter._material_admitted_inputs, {})
            self.assertEqual(adapter._material_diagnostics, {})

    def test_material_concurrent_runs_do_not_mix_phases_or_retain_terminal_state(self):
        ready = 0
        release = None
        async def concurrent(adapter, run, *, _api_server):
            nonlocal ready
            adapter._run_statuses[run.run_id] = {'session_id': run.session_id}
            ready += 1
            if ready == 2: release.set()
            await release.wait()
            return await self.terminal_executor(adapter, run, _api_server=_api_server)
        with self.runtime(executor=concurrent) as (_, adapter, _, modules):
            api = modules['gateway.platforms.api_server_runs']
            # One session fails inside the existing agent-builder boundary; the other succeeds.
            build = adapter._create_admitted_agent
            def selected(ephemeral_system_prompt=None, session_id=None, **kwargs):
                if session_id.startswith('mg_' + 'a'):
                    raise TypeError('secret')
                return build(ephemeral_system_prompt, session_id, **kwargs)
            async def both():
                nonlocal release
                release = asyncio.Event()
                await asyncio.gather(*(api._execute_run(adapter, types.SimpleNamespace(
                    run_id='run_' + v * 32, session_id='mg_' + v * 64), _api_server=None) for v in ('a', 'b')))
            with patch.object(adapter, '_create_admitted_agent', selected):
                asyncio.run(both())
            a, b = (adapter._run_statuses['run_' + v * 32] for v in ('a', 'b'))
            self.assertEqual(a['status'], 'failed'); self.assertEqual(b['status'], 'completed')
            self.assertEqual(a['runtime']['fs_material_diagnostic']['exception_class'], 'TypeError')
            self.assertEqual(b['runtime']['fs_material_diagnostic']['exception_class'], 'unknown')
            self.assertEqual(adapter._material_diagnostics, {})


if __name__ == '__main__':
    unittest.main()

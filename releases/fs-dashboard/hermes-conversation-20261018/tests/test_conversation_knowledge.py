"""Real native turn, persisted knowledge and private RPC; no provider or business writes."""
import ast
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from dataclasses import dataclass
from urllib.parse import urlsplit

import test_conversation_native as native_fixture
SOURCE = native_fixture.SOURCE


class KnowledgeWiring(unittest.TestCase):
    fixture = native_fixture.NativeDispatchTests.fixture

    @classmethod
    def setUpClass(cls):
        native_fixture.NativeDispatchTests.setUpClass.__func__(cls)
        cls.original_atomic = cls.modules['controller'].atomic
        path = SOURCE.parents[1] / 'hermes-v2-core-20261020/source/controller.py'
        node = next(n for n in ast.parse(path.read_text('utf-8')).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'atomic')
        namespace = dict(Path=Path, secrets=secrets, json=json)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
        cls.atomic = staticmethod(namespace['atomic'])
        sys.path.insert(0, str(SOURCE.parents[1] / 'knowledge-layering-20261023/source'))
        sys.path.insert(0, str(SOURCE.parents[1] / 'hermes-fc-pilot-20261013'))
        sys.path.insert(0, str(SOURCE.parents[1] / 'hermes-memory-approval-20261022'))
        path = SOURCE.parents[1] / 'hermes-server-unify-20261022/fs_readonly/knowledge.py'
        spec = importlib.util.spec_from_file_location('fs_native_knowledge', path)
        cls.knowledge_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.knowledge_module)
        path = SOURCE.parents[1] / 'hermes-v2-core-20261020/source/transport.py'
        nodes = [n for n in ast.parse(path.read_text('utf-8')).body
                 if isinstance(n, ast.ClassDef) and n.name in {'Grant', 'Grants', 'Proxy'}]
        cls.transport = dict(dataclass=dataclass, threading=threading, time=time,
                             secrets=secrets, hashlib=hashlib, json=json)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), cls.transport)

    @contextmanager
    def runtime(self, *, configured=True, lost=False):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, self.modules):
            service, cid = self.fixture(directory)
            service.hermes.grants = self.transport['Grants']()
            (service.run_root / 'admissions').mkdir(parents=True, exist_ok=True)
            root = service.hermes.root
            if configured:
                folder = root / 'knowledge-releases/fixed'
                folder.mkdir(parents=True)
                text = b'formal fixture rule'
                (folder / 'rule.md').write_bytes(text)
                entry = dict(id='fs.rule', revision='v1', layer='current', status='effective',
                    modules=['FS'], effective_at='2026-11-04', owner='alice', authority='git',
                    provenance=['offline'], supersedes=[],
                    source=dict(path='rule.md', sha256=hashlib.sha256(text).hexdigest()))
                index = dict(contract='fs-knowledge-index-v1', release='fixture-v1',
                    release_state='published', source_commit='a'*40,
                    source_root='knowledge-releases/fixed', entries=[entry])
                raw = json.dumps(index).encode()
                (folder / 'index.json').write_bytes(raw)
                route = dict(owner='alice', project='FS', channel='fs', task_types=['conversation'],
                    profile_name=hashlib.sha256(b'alice').hexdigest(), modules=['FS'],
                    catalog='knowledge-releases/fixed/index.json', sha256=hashlib.sha256(raw).hexdigest(),
                    baseline_compatibility=dict(mode='retain_full_baseline', sha256=hashlib.sha256(text).hexdigest()))
                policy = root / 'knowledge-load-policy.json'
                policy.write_text(json.dumps(dict(contract='fs-knowledge-load-policy-v1',
                    task_routes=dict(enabled=True, routes=[route]))), encoding='utf-8')
                policy.chmod(0o600)
            constants = types.ModuleType('hermes_constants')
            # Explicit pinned-SDK boundary fixture; production uses the official function.
            constants.profile_name_for_home = lambda home: Path(home).name
            calls = []
            def request(method, path, body=None, key=None):
                before = json.loads((service.run_root / 'admissions' / (body['session_id']+'.json')).read_bytes())
                calls.append((method, path, body, key, before))
                if lost:
                    raise TimeoutError('original response lost')
                return 202, dict(run_id='run_'+'a'*32)
            service._request = request
            turn = service.submit('alice', cid, 'ordinary question', 'knowledge_request_1')
            with service.store.db() as db:
                sid = service.store._owned(db, 'alice', cid)['session_id']
            with patch.object(self.modules['controller'], 'atomic', self.atomic), patch.dict(
                    sys.modules, {'hermes_constants': constants, 'fs_native_knowledge': self.knowledge_module}):
                yield service, cid, turn['turn_id'], sid, calls

    @contextmanager
    def worker_runtime(self, service, item, *, behavior='read'):
        import conversation_native as native
        from test_conversation_file_loop import WorkerEnvironmentTests
        with WorkerEnvironmentTests().runtime() as (worker, adapter, calls, modules):
            original = ast.parse(Path(worker.__file__).read_text('utf-8'))
            node = next(n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == 'admission')
            exec(compile(ast.Module(body=[node], type_ignores=[]), worker.__file__, 'exec'), worker.__dict__)
            worker.ADMISSIONS = service.run_root / 'admissions'
            # Actual original transport classifier and compaction consumer, not mocked authorization.
            proxy_path = SOURCE.parents[2] / 'fc-coins/fc-review-channel-20261026/source/proxy_gateway.py'
            tree = ast.parse(proxy_path.read_text('utf-8'))
            nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                     and n.name in {'native_scope', 'confirm_native_compaction'}]
            namespace = dict(re=__import__('re'))
            exec(compile(ast.Module(body=nodes, type_ignores=[]), str(proxy_path), 'exec'), namespace)
            modules['proxy_gateway'].native_scope = namespace['native_scope']
            bound = item['native_chat']['binding']
            gateway = service.hermes.gateways[bound['turn_id']]
            gateway._compaction_lock = threading.Lock()
            gateway._native_compaction = None
            gateway.budget = types.SimpleNamespace(db=service.store.db)
            gateway.confirm_native_compaction = types.MethodType(namespace['confirm_native_compaction'], gateway)
            with service.store.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS hermes_reservations(owner,task,turn,fingerprint)')
                db.execute('CREATE TABLE IF NOT EXISTS model_calls(fingerprint,state)')
            proxy = self.transport['Proxy'](service.hermes.grants,
                lambda grant: service.hermes.gateways[grant.task_id])
            rpc = []
            class Opener:
                def open(self, request, **kwargs):
                    body = json.loads(request.data)
                    rpc.append(body['name'])
                    token = request.get_header('Authorization').split(' ', 1)[1]
                    result = proxy.dispatch(request.get_method(), urlsplit(request.full_url).path, token, body)
                    return io.BytesIO(json.dumps(result).encode())
            # Only Docker/SDK/HTTP boundaries are fixtures. Store, grants, scope, pin and RPC dispatch are real.
            profile = service.store.path.parent.parent / 'w'
            profile.mkdir(mode=0o700)
            class Backend:
                def __init__(self, admitted, active):
                    self.profile = profile
                    self.environment = admitted['native_chat']['environment']
                    self.active = active
                def check(self, task_id=None):
                    if task_id not in (None, bound['turn_id']) or self.active() is not True:
                        raise PermissionError('native_chat_inactive')
                @contextmanager
                def scope(self, *, check=True):
                    if check:
                        self.check()
                    token = native._NATIVE_BACKEND.set(self)
                    try:
                        yield
                    finally:
                        native._NATIVE_BACKEND.reset(token)
                def ensure_environment(self): pass
                def close_environment(self): pass
                def observe_pending(self, *args): pass
            registry = modules['tools.registry'].registry
            def definitions(**kwargs):
                values = [{'type':'function', 'function':dict(name='read_file', parameters=dict(type='object'))}]
                for name in ('fs_get_knowledge_index', 'fs_read_knowledge'):
                    entry = registry.get_entry(name, scope=str(profile))
                    if entry is not None:
                        values.append(dict(type='function', function=entry.schema))
                return values
            class Agent:
                def __init__(self, **kwargs):
                    self.session_id = kwargs['session_id']; self.platform = kwargs['platform']
                    self.enabled_toolsets = kwargs['enabled_toolsets']; self.disabled_toolsets = kwargs['disabled_toolsets']
                    self.ephemeral_system_prompt = kwargs['ephemeral_system_prompt']
                    self.tools = definitions(); self._tool_snapshot_generation = 1
                    self.context_compressor = types.SimpleNamespace(compression_count=0)
                    self.event_callback = lambda *a: None
                def _compress_context(self, messages, prompt, **kwargs):
                    old = self.session_id; self.session_id = 'official-child'
                    self.context_compressor.compression_count += 1
                    self.event_callback('session:compress', dict(platform=self.platform, session_id=self.session_id,
                        old_session_id=old, in_place=False, compression_count=self.context_compressor.compression_count))
                    return [dict(role='user', content='actual compressed fixture result')], prompt
                def _build_api_kwargs(self, messages, **kwargs): return dict(messages=messages)
                def run_conversation(self, text, **kwargs):
                    if behavior == 'compact':
                        compacted, _ = self._compress_context([dict(role='user', content=text)], 'prompt')
                        if self._fs_native_knowledge.knowledge.active_task(self.session_id, bound['turn_id']) is not None:
                            raise AssertionError('child linked before official returned fence')
                        self._build_api_kwargs(compacted)
                    if behavior == 'stop': service.native.fence('alice', bound['conversation_id'], bound['turn_id'])
                    entry = registry.get_entry('fs_read_knowledge', scope=str(profile))
                    arguments = dict(modules=['FS'])
                    if behavior == 'skill': arguments['skill_id'] = 'methods/test-method'
                    return json.loads(entry.handler(arguments, task_id=kwargs['task_id']))
                def close(self): pass
            constants = types.SimpleNamespace(profile_name_for_home=lambda home: hashlib.sha256(b'alice').hexdigest(),
                resolve_reasoning_config=lambda config, model: dict(enabled=False))
            tool_config = types.SimpleNamespace(_get_platform_tools=lambda config, platform: ['file','memory','skills','fs_native_knowledge'])
            with patch.object(worker, 'build_opener', return_value=Opener()), patch.object(native, 'NativeDockerBackend', Backend), \
                    patch.object(native, 'install_native_backend_guards'), patch.object(native, 'NATIVE_ROOT', service.native.workspace.root.as_posix()), \
                    patch.object(modules['hermes_cli.config'], 'load_config', return_value=dict(memory=dict(write_approval=True),skills=dict(write_approval=True)),create=True), \
                    patch.object(modules['run_agent'], 'AIAgent', Agent), patch.dict(sys.modules, {
                        'hermes_constants':constants, 'hermes_cli.tools_config':tool_config,
                        'model_tools':types.SimpleNamespace(get_tool_definitions=definitions),
                        'agent.reasoning_params':types.SimpleNamespace(unset_reasoning_default=lambda a: dict(enabled=False)),
                        'agent.message_sanitization':types.SimpleNamespace(sanitize_outbound_kwargs=lambda *a:None)}):
                # POSIX path rendering is a filesystem fixture; the original admission validator still executes.
                class WirePath(type(Path())):
                    def __str__(self): return super().__str__().replace('\\','/')
                service.native.workspace.root = WirePath(service.native.workspace.root)
                for key in ('profile','workspace'):
                    item['native_chat']['environment'][key] = Path(item['native_chat']['environment'][key]).as_posix()
                self.atomic(worker.ADMISSIONS/(bound['session_id']+'.json'), item, mode=0o640)
                adapter._ensure_session_db = lambda: types.SimpleNamespace(original_session=bound['session_id'])
                with patch.object(native, 'Path', WirePath):
                    agent = adapter._create_agent(session_id=bound['session_id'])
                    yield worker, agent, rpc

    def dispatch(self, service, cid, turn, sid):
        service._dispatch('alice', cid, turn, sid, 'ordinary question', 'knowledge_request_1')
        return json.loads((service.run_root / 'admissions' / (sid+'.json')).read_bytes())

    def test_original_dispatch_freezes_knowledge_before_the_only_runtime_post(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            admission = self.dispatch(service, cid, turn, sid)
            reference = admission['native_chat']['knowledge']
            self.assertEqual(reference['info']['owner'], 'alice')
            self.assertEqual(reference['info']['platform'], 'api_server')
            self.assertEqual(reference['info']['session_id'], sid)
            self.assertRegex(reference['pin_sha256'], '^[a-f0-9]{64}$')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:2], ('POST', '/v1/runs'))
            self.assertEqual(calls[0][2], dict(input='ordinary question', session_id=sid))
            self.assertEqual(calls[0][4]['native_chat']['knowledge'], reference)
            self.assertIsNone(calls[0][4]['native_chat']['binding']['run_id'])
            self.assertNotIn('formal fixture rule', json.dumps(admission))

    def test_unconfigured_chat_persists_none_and_keeps_single_post(self):
        with self.runtime(configured=False) as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            self.assertIsNone(item['native_chat']['knowledge'])
            self.assertEqual(len(calls), 1)

    def test_policy_without_matching_fs_route_does_not_require_host_sdk(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            path = service.hermes.root / 'knowledge-load-policy.json'
            policy = json.loads(path.read_bytes())
            policy['task_routes']['routes'][0]['owner'] = 'other-owner'
            path.write_text(json.dumps(policy), encoding='utf-8')
            with patch.dict(sys.modules, {'hermes_constants': None}):
                item = self.dispatch(service, cid, turn, sid)
            self.assertIsNone(item['native_chat']['knowledge'])
            self.assertEqual(len(calls), 1)

    def test_matching_fs_route_uses_original_owned_profile_without_host_sdk(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            with patch.dict(sys.modules, {'hermes_constants': None}):
                item = self.dispatch(service, cid, turn, sid)
            reference = item['native_chat']['knowledge']
            self.assertEqual(reference['info']['profile_name'], hashlib.sha256(b'alice').hexdigest())
            self.assertEqual(len(calls), 1)

    def test_wrong_environment_profile_is_rejected_before_runtime_post(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            prepare = service.native.workspace.prepare
            def wrong(*args, **kwargs):
                environment = prepare(*args, **kwargs)
                environment['profile'] = str(service.native.workspace.root/'profiles'/'other-owner')
                return environment
            with patch.object(service.native.workspace, 'prepare', side_effect=wrong):
                with self.assertRaisesRegex(PermissionError, 'knowledge_profile'):
                    self.dispatch(service, cid, turn, sid)
            self.assertEqual(calls, [])

    def test_original_unknown_retains_durable_pin_without_new_post_or_selection(self):
        import conversation_native
        from conversation_knowledge import reference_for, host_paths
        with self.runtime(lost=True) as (service, cid, turn, sid, calls):
            with self.assertRaises(TimeoutError):
                self.dispatch(service, cid, turn, sid)
            binding = service.native.row('alice', cid, turn)['binding']
            reference = reference_for(service.native, binding)
            self.assertIsNotNone(reference)
            self.assertEqual(service.store.detail('alice', cid)['turns'][0]['state'], 'dispatch_unknown')
            # Recreate the native host object on the same real store, then change current policy.
            service.native = conversation_native.NativeConversation(service)
            (service.hermes.root / 'knowledge-load-policy.json').write_bytes(b'broken current policy')
            service._dispatch('alice', cid, turn, sid, 'ordinary question', 'knowledge_request_1')
            self.assertEqual(reference_for(service.native, binding), reference)
            self.assertTrue(host_paths(service.native, binding)[1].is_file())
            self.assertEqual(len(calls), 1)

    def test_host_read_requires_current_binding_digest_and_authorization(self):
        from conversation_knowledge import reference_for, host_paths
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            bound = item['native_chat']['binding']
            reference = reference_for(service.native, bound)
            payload = dict(binding=bound, reference=reference, operation='read',
                           name='fs_read_knowledge', arguments=dict(modules=['FS']))
            read = service.native.host_tool(bound, 'fs.native.knowledge', payload)
            self.assertEqual(read['entries'][0]['content'], 'formal fixture rule')
            root, _ = host_paths(service.native, bound)
            self.assertEqual(len(list((root/'knowledge/native').glob('use-*.json'))), 1)
            with self.assertRaises(PermissionError):
                service.native.host_tool(bound, 'fs.native.knowledge', dict(payload,
                    reference=dict(reference, pin_sha256='0'*64)))
            with self.assertRaises(PermissionError):
                service.native.host_tool(bound, 'fs.native.knowledge', dict(payload, binding=dict(bound, owner='bob')))
            service.hermes.authorizer = lambda owner: 1
            with self.assertRaises(PermissionError):
                service.native.host_tool(bound, 'fs.native.knowledge', payload)
            service.hermes.authorizer = lambda owner: True
            service.native.fence('alice', cid, turn)
            with self.assertRaises(PermissionError):
                service.native.host_tool(bound, 'fs.native.knowledge', payload)

    def test_actual_worker_construction_registration_scope_and_grant_rpc_return(self):
        from conversation_knowledge import host_paths
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            with self.worker_runtime(service, item) as (worker, agent, rpc):
                self.assertIn('fixture-v1', agent.ephemeral_system_prompt)
                self.assertNotIn('formal fixture rule', agent.ephemeral_system_prompt)
                self.assertEqual(agent.platform, 'api_server')
                self.assertIn('fs.native.register_schemas', rpc)
                result = agent.run_conversation('question')
                self.assertEqual(result['entries'][0]['content'], 'formal fixture rule')
                knowledge = agent._fs_native_knowledge
                self.assertNotEqual(knowledge.knowledge.receipt_root, host_paths(service.native, item['native_chat']['binding'])[0])
                self.assertIsNone(knowledge.knowledge.active_task(sid, turn))
                self.assertEqual(worker.loaded_context_metadata(agent)['fs_native_knowledge']['release'], 'fixture-v1')
                self.assertEqual(len(calls), 1)

    def test_stop_during_worker_run_rejects_read_and_cleans_alias(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            with self.worker_runtime(service, item, behavior='stop') as (worker, agent, rpc):
                with self.assertRaises(PermissionError): agent.run_conversation('question')
                self.assertIsNone(agent._fs_native_knowledge.knowledge.active_task(sid, turn))

    def test_official_compaction_fence_links_same_pin_child_then_cleans_it(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            with self.worker_runtime(service, item, behavior='compact') as (worker, agent, rpc):
                result = agent.run_conversation('question')
                self.assertEqual(result['entries'][0]['content'], 'formal fixture rule')
                self.assertIn('fs.native.compacted_request', rpc)
                self.assertIsNone(agent._fs_native_knowledge.knowledge.active_task('official-child', turn))
                with self.assertRaises(PermissionError):
                    agent._fs_native_knowledge.link('late-child')

    def test_worker_wrong_external_digest_fails_before_agent_construction(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            item['native_chat']['knowledge']['pin_sha256'] = '0'*64
            with self.assertRaisesRegex(PermissionError, 'knowledge_reference'):
                with self.worker_runtime(service, item):
                    self.fail('wrong digest constructed an agent')

    def test_unconfigured_worker_keeps_original_tools_and_prompt(self):
        with self.runtime(configured=False) as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            with self.worker_runtime(service, item) as (worker, agent, rpc):
                self.assertFalse(hasattr(agent, '_fs_native_knowledge'))
                self.assertNotIn('fs_native_knowledge', agent.enabled_toolsets)
                self.assertIn('memory', agent.enabled_toolsets)
                self.assertNotIn('fs.native.knowledge', rpc)

    def test_revocation_after_actual_read_does_not_return_the_result(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            bound = item['native_chat']['binding']
            checks = iter((True, True, False))
            service.hermes.authorizer = lambda owner: next(checks)
            with self.assertRaisesRegex(PermissionError, 'inactive'):
                service.native.host_tool(bound, 'fs.native.knowledge', dict(binding=bound,
                    reference=item['native_chat']['knowledge'], operation='read', name='fs_read_knowledge',
                    arguments=dict(modules=['FS'])))

    def test_second_authenticated_owner_cannot_borrow_first_owner_reference(self):
        with self.runtime() as (service, cid, turn, sid, calls):
            item = self.dispatch(service, cid, turn, sid)
            bound = item['native_chat']['binding']
            service.hermes.authorizer = lambda owner: owner in {'alice', 'bob'}
            other = dict(bound, owner='bob')
            with self.assertRaises((LookupError, PermissionError)):
                service.native.host_tool(other, 'fs.native.knowledge', dict(binding=other,
                    reference=item['native_chat']['knowledge'], operation='load'))

    def test_approved_skill_index_and_body_freeze_before_post_and_worker_reads_old_pin(self):
        import reviewed_skills
        import conversation_knowledge
        with self.runtime() as (service, cid, turn, sid, calls):
            profile = service.hermes.root / 'p'
            skills = profile / 'skills'
            path = skills / 'methods/test-method'
            path.mkdir(parents=True)
            (path/'SKILL.md').write_text('approved fixture method', encoding='utf-8')
            package = reviewed_skills.package(skills, 'methods/test-method')
            material = dict(contract=reviewed_skills.CONTRACT, items=[dict(id='methods/test-method',
                package_sha256=package['sha256'], sha256=package['sha256'], files=package['entries'],
                modules=['FS'], description='Approved fixture', review_request_id='fixture-review')])
            index = dict(material, sha256=reviewed_skills.digest(material))
            folder = service.hermes.root / 'knowledge'
            folder.mkdir()
            (folder/'reviewed-skills.json').write_text(json.dumps(index), encoding='utf-8')
            policy_path = service.hermes.root / 'knowledge-load-policy.json'
            policy = json.loads(policy_path.read_bytes())
            policy['task_routes']['routes'][0]['reviewed_skills'] = dict(
                index='knowledge/reviewed-skills.json', sha256=index['sha256'])
            policy_path.write_text(json.dumps(policy), encoding='utf-8')
            with patch.object(conversation_knowledge, 'SHARED_PROFILE', profile):
                item = self.dispatch(service, cid, turn, sid)
                (path/'SKILL.md').write_text('unreviewed changed method', encoding='utf-8')
                with self.worker_runtime(service, item, behavior='skill') as (worker, agent, rpc):
                    result = agent.run_conversation('question')
                    self.assertEqual(result['content'], 'approved fixture method')
                    self.assertEqual(agent._fs_native_knowledge.pin['reviewed_skills']['index_sha256'], index['sha256'])
                    self.assertNotIn('approved fixture method', agent.ephemeral_system_prompt)
            self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()

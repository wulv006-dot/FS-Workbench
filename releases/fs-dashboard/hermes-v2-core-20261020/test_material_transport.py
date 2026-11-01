"""Actual FS transport validation with scoped synthetic dependencies, no I/O."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import http.client
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
CORE = Path(__file__).resolve().parent / 'source'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def declaration(path, name):
    # Read existing full tool-family names, without initializing business readers.
    for node in ast.parse(path.read_text('utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def schema_fixture(names):
    return [dict(type='function', function=dict(name='mcp__fcro__' + name.replace('.', '_'),
            parameters=dict(type='object', properties={}))) for name in names]


class MaterialTransport(unittest.TestCase):
    @contextmanager
    def fixture(self, material=True):
        with patch.dict(sys.modules):
            load('pilot', ROOT / 'releases/fs-dashboard/hermes-fc-pilot-20261013/pilot.py')
            research = declaration(ROOT / 'releases/fs-dashboard/hermes-fs-research-integration-20261015/source/research.py', 'RESEARCH_NAMES')
            strategies = declaration(ROOT / 'releases/fs-dashboard/hermes-v2-strategy-20261021/source/strategy_tools.py', 'NAMES')
            sys.modules['research'] = SimpleNamespace(RESEARCH_NAMES=research, tool_schemas=lambda: schema_fixture(research))
            sys.modules['strategy_tools'] = SimpleNamespace(NAMES=strategies, schemas=lambda: schema_fixture(strategies))
            sys.modules['background'] = SimpleNamespace(background_index=Mock(), read_section=Mock())
            load('material_evidence', CORE / 'material_evidence.py')
            files = load('conversation_file_tools', CORE / 'conversation_file_tools.py')
            contract = load('runs_contract', ROOT / 'releases/fc-coins/fc-pricing-v2-20261022/source/runs_contract.py')
            gateway_module = load('proxy_gateway', ROOT / 'releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py')
            transport = load('material_transport_under_test', CORE / 'transport.py')
            task = dict(state='RUNNING', lease='fixture-lease', spec={'snapshot_id': 'fixture-capture'})
            def get(task_id, owner):
                if (task_id, owner) != ('fixture-task', 'fixture-owner'):
                    raise PermissionError('task_owner')
                return task
            book = SimpleNamespace(capture_id='fixture-capture', material_execution=material,
                                   authorize_execution=Mock(return_value=True))
            scope = gateway_module.ScopedTools(SimpleNamespace(get=get), book,
                                               lambda: datetime.now(timezone.utc))
            turns = []
            class SpyProxy(transport.Proxy):
                @staticmethod
                def _turn(db_factory, grant, request):
                    turns.append(deepcopy(request))
                    return 0
            receipt = dict(provider_request_id='synthetic-receipt', model='deepseek-flash', usage={},
                           message={'role': 'assistant', 'content': 'synthetic'}, finish_reason='stop')
            gateway = SimpleNamespace(scope=scope, budget=SimpleNamespace(policy={'model': 'deepseek-flash'}, db=None),
                                      call=Mock(return_value=receipt))
            now = [0]
            grants = transport.Grants(clock=lambda: now[0])
            token = grants.mint('fixture-owner', 'fixture-task', 'fixture-lease')
            proxy = SpyProxy(grants, lambda grant: gateway)
            body = dict(model='deepseek-flash', messages=[{'role': 'user', 'content': 'synthetic'}],
                        max_tokens=32, tools=files.tool_schemas(scope='material_execution_files'),
                        tool_choice='auto', stream=False)
            yield SimpleNamespace(proxy=proxy, gateway=gateway, module=gateway_module, contract=contract,
                                  task=task, book=book, token=token, grants=grants, now=now,
                                  body=body, turns=turns, files=files, transport=transport)

    def dispatch(self, f, body=None):
        return f.proxy.dispatch('POST', '/v1/chat/completions', f.token,
                                deepcopy(f.body if body is None else body))

    def untouched(self, f):
        self.assertEqual(f.turns, [])
        f.gateway.call.assert_not_called()

    def test_material_three_tools_and_preflight_use_trusted_task_schemas(self):
        with self.fixture() as f, patch.object(f.module, 'request_body', wraps=f.module.request_body) as preflight:
            before = deepcopy(f.body)
            self.assertEqual(self.dispatch(f)['id'], 'synthetic-receipt')
            self.assertEqual(preflight.call_args.kwargs['tool_schemas'], before['tools'])
            self.assertEqual(f.body, before)
            self.assertEqual(len(f.turns), 1)
            f.book.authorize_execution.assert_called_once()
            f.gateway.call.assert_called_once()

    def test_material_never_expands_global_schemas_or_trusts_client_parameters(self):
        with self.fixture() as f, patch.object(f.module, 'schemas', side_effect=AssertionError('global schemas')):
            trusted = deepcopy(f.body['tools'])
            f.body['tools'][0]['function']['parameters'] = {'type': 'object', 'properties': {'arbitrary': {}}}
            with patch.object(f.module, 'request_body', wraps=f.module.request_body) as preflight:
                self.dispatch(f)
                self.assertEqual(preflight.call_args.kwargs['tool_schemas'], trusted)

    def test_material_rejects_full_nonfile_subset_duplicate_and_unknown_tools(self):
        with self.fixture() as f:
            choices = [f.module.schemas(), f.body['tools'][:-1], f.body['tools'] + [f.body['tools'][0]],
                       [dict(type='function', function={'name': 'unregistered'})], [None]]
            for tools in choices:
                with self.subTest(tools=len(tools)), self.assertRaisesRegex(ValueError, 'tool_allowlist'):
                    self.dispatch(f, dict(f.body, tools=tools))
                self.untouched(f)

    def test_fc_keeps_original_full_set_and_rejects_three_tools(self):
        with self.fixture(material=False) as f:
            with self.assertRaisesRegex(ValueError, 'tool_allowlist'):
                self.dispatch(f)
            self.untouched(f)
            full = f.module.schemas()
            self.assertEqual(set(v['function']['name'] for v in full), set(f.contract.WIRE_TOOLS))
            self.assertGreater(len(full), 3)
            self.dispatch(f, dict(f.body, tools=full))
            self.assertEqual(len(f.turns), 1)
            f.book.authorize_execution.assert_not_called()

    def test_task_lease_state_owner_scope_and_grant_guards_still_precede_dispatch(self):
        for change in ('lease', 'state', 'capture', 'revoked', 'expired', 'owner'):
            with self.subTest(change=change), self.fixture() as f:
                if change == 'lease': f.task['lease'] = 'wrong'
                elif change == 'state': f.task['state'] = 'CANCELLED'
                elif change == 'capture': f.task['spec']['snapshot_id'] = 'wrong'
                elif change == 'revoked': f.book.authorize_execution.return_value = False
                elif change == 'expired': f.now[0] = 601
                elif change == 'owner': f.token = f.grants.mint('other-owner', 'fixture-task', 'fixture-lease')
                with self.assertRaises(PermissionError): self.dispatch(f)
                self.untouched(f)

    def test_client_cannot_select_material_kind_or_relax_request_policy(self):
        changes = [dict(material_execution=True), dict(kind='conversation_materials_v1'),
                   dict(temperature=0), dict(model='other'), dict(stream=True), dict(tool_choice='required'),
                   dict(reasoning_effort='high')]
        with self.fixture() as f:
            for change in changes:
                with self.subTest(fields=list(change)), self.assertRaises(ValueError):
                    self.dispatch(f, dict(f.body, **change))
                self.untouched(f)

    def test_native_auxiliary_request_still_has_no_tools(self):
        with self.fixture() as f:
            real_preflight = f.module.request_body
            with patch.object(f.module, 'request_body', wraps=real_preflight) as preflight:
                body = {'model': f.body['model'], 'messages': f.body['messages'], 'stream': False}
                self.dispatch(f, body)
                request = preflight.call_args.args[0]
                self.assertTrue(request['auxiliary'])
                self.assertEqual(real_preflight(request, body['model'])['tools'], [])

    def test_actual_loopback_accepts_three_tools_and_keeps_denial_responses(self):
        with self.fixture() as f:
            server, thread = f.transport.start_loopback(f.proxy, port=0)
            def send(body, authorized=True):
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    headers = {'Content-Type': 'application/json'}
                    if authorized:
                        headers['Authorization'] = 'Bearer ' + f.token
                    connection.request('POST', '/v1/chat/completions', json.dumps(body), headers)
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            try:
                status, value = send(f.body)
                self.assertEqual((status, value['id']), (200, 'synthetic-receipt'))
                for body in (dict(f.body, tools=f.module.schemas()), dict(f.body, temperature=0)):
                    status, value = send(body)
                    self.assertEqual(status, 400)
                    self.assertEqual(value['error']['message'], 'invalid or unreconciled request')
                self.assertEqual(send(f.body, authorized=False)[0], 403)
                self.assertEqual(len(f.turns), 1)
                self.assertEqual(f.gateway.call.call_count, 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()

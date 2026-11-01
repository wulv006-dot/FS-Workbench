"""FS transport with scoped synthetic dependencies and loopback-only HTTP."""
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
                   dict(temperature=0), dict(model='other'), dict(stream='true'), dict(tool_choice='required'),
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

    def test_material_stream_usage_is_response_format_not_provider_override(self):
        with self.fixture() as f:
            body = dict(f.body, stream=True, stream_options={'include_usage': True})
            before = deepcopy(body)
            value = self.dispatch(f, body)
            self.assertEqual(value['id'], 'synthetic-receipt')
            self.assertEqual(body, before)
            self.assertEqual(len(f.turns), 1)
            self.assertEqual(f.gateway.call.call_count, 1)
            request = f.gateway.call.call_args.args[-1]
            self.assertEqual(request, {'messages': body['messages'], 'max_tokens': body['max_tokens']})
            # SDK may omit options, send null/empty, or explicitly omit usage.
            for options in (None, {}, {'include_usage': False}):
                self.dispatch(f, dict(body, stream_options=options))

    def test_material_stream_option_types_and_unknown_fields_fail_before_dispatch(self):
        changes = [dict(stream=1), dict(stream='true'), dict(stream=None),
                   dict(stream=True, stream_options={'include_usage': 1}),
                   dict(stream=True, stream_options={'include_usage': 'true'}),
                   dict(stream=True, stream_options={'unknown': True}),
                   dict(stream=True, stream_options=[]),
                   dict(stream=False, stream_options={'include_usage': True})]
        with self.fixture() as f:
            for change in changes:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.dispatch(f, dict(f.body, **change))
                self.untouched(f)

    def test_fc_and_native_auxiliary_stream_policies_are_preserved(self):
        with self.fixture(material=False) as f:
            body = dict(f.body, tools=f.module.schemas(), stream=True)
            with self.assertRaisesRegex(ValueError, 'provider_override'):
                self.dispatch(f, body)
            with self.assertRaisesRegex(ValueError, 'stream_options'):
                self.dispatch(f, dict(body, stream_options={'include_usage': True}))
            self.untouched(f)
        with self.fixture() as f:
            body = dict(model=f.body['model'], messages=f.body['messages'], stream=True,
                        stream_options={'include_usage': True})
            with self.assertRaisesRegex(ValueError, 'stream_not_supported'):
                self.dispatch(f, body)
            self.untouched(f)

    def stream_http(self, f, body, authorized=True):
        server, thread = f.transport.start_loopback(f.proxy, port=0)
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            headers = {'Content-Type': 'application/json'}
            if authorized:
                headers['Authorization'] = 'Bearer ' + f.token
            connection.request('POST', '/v1/chat/completions', json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def stream_events(self, raw):
        lines = raw.decode('utf-8').splitlines()
        data = [line[6:] for line in lines if line.startswith('data: ')]
        self.assertEqual(data[-1], '[DONE]')
        self.assertEqual(data.count('[DONE]'), 1)
        return [json.loads(value) for value in data[:-1]]

    def test_material_http_stream_has_chunks_finish_and_requested_usage(self):
        with self.fixture() as f:
            f.gateway.call.return_value['usage'] = dict(prompt_tokens=3, completion_tokens=2, total_tokens=5)
            body = dict(f.body, stream=True, stream_options={'include_usage': True})
            status, content_type, raw = self.stream_http(f, body)
            self.assertEqual(status, 200)
            self.assertTrue(content_type.startswith('text/event-stream'))
            events = self.stream_events(raw)
            self.assertEqual([v['object'] for v in events], ['chat.completion.chunk'] * 3)
            self.assertTrue(all(v['id'] == 'synthetic-receipt' and v['model']=='deepseek-flash'
                                and v['created']==events[0]['created'] for v in events))
            self.assertEqual(events[0]['choices'][0]['delta'], {'role': 'assistant', 'content': 'synthetic'})
            self.assertIsNone(events[0]['choices'][0]['finish_reason'])
            self.assertEqual(events[1]['choices'][0], {'index': 0, 'delta': {}, 'finish_reason': 'stop'})
            self.assertEqual(events[2]['choices'], [])
            self.assertEqual(events[2]['usage'], f.gateway.call.return_value['usage'])
            self.assertEqual(f.gateway.call.call_count, 1)
            self.assertEqual(len(f.turns), 1)

    def test_material_http_stream_preserves_tool_call_and_can_omit_usage(self):
        with self.fixture() as f:
            call = dict(id='call-synthetic', type='function',
                        function=dict(name=f.body['tools'][1]['function']['name'], arguments='{"file_id":"synthetic"}'))
            f.gateway.call.return_value.update(message={'role': 'assistant', 'content': None, 'tool_calls': [call]},
                                               finish_reason='tool_calls')
            status, content_type, raw = self.stream_http(f, dict(f.body, stream=True))
            self.assertEqual(status, 200)
            self.assertTrue(content_type.startswith('text/event-stream'))
            events = self.stream_events(raw)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]['choices'][0]['delta']['tool_calls'], [dict(call, index=0)])
            self.assertEqual(events[1]['choices'][0]['finish_reason'], 'tool_calls')
            self.assertTrue(all('usage' not in event for event in events))
            self.assertEqual(f.gateway.call.call_count, 1)

    def test_material_stream_errors_remain_json_and_do_not_retry(self):
        with self.fixture() as f:
            body = dict(f.body, stream=True, stream_options={'include_usage': True})
            status, content_type, raw = self.stream_http(f, body, authorized=False)
            self.assertEqual(status, 403)
            self.assertTrue(content_type.startswith('application/json'))
            self.assertEqual(json.loads(raw)['error']['type'], 'permission_error')
            self.untouched(f)
            f.gateway.call.side_effect = OSError('synthetic provider failure')
            status, content_type, raw = self.stream_http(f, body)
            self.assertEqual(status, 503)
            self.assertTrue(content_type.startswith('application/json'))
            self.assertEqual(json.loads(raw)['error']['type'], 'server_error')
            self.assertEqual(f.gateway.call.call_count, 1)
            self.assertEqual(len(f.turns), 1)

    def test_material_guard_failures_identify_the_exact_local_boundary(self):
        with self.fixture() as f:
            for code, change in [('request_fields', {'unexpected': 'PRIVATE_SENTINEL'}),
                                 ('tool_allowlist', {'tools': f.module.schemas()})]:
                status, content_type, raw = self.stream_http(f, dict(f.body, **change))
                self.assertEqual(status, 400)
                error = json.loads(raw)['error']
                self.assertEqual(error, dict(message='invalid or unreconciled request',
                    type='invalid_request_error', source='fs_material_transport',
                    diagnostic_version='material_guard_v1', code=code))
                self.assertNotIn(b'PRIVATE_SENTINEL', raw)
                self.untouched(f)

    def test_guard_diagnostic_is_not_inferred_from_an_arbitrary_exception_string(self):
        with self.fixture(material=False) as f:
            status, _, raw = self.stream_http(f, dict(f.body, unexpected=True))
            self.assertEqual(status, 400)
            self.assertNotIn('code', json.loads(raw)['error'])
        with self.fixture() as f:
            status, _, raw = self.stream_http(f, dict(f.body, unexpected=True), authorized=False)
            self.assertEqual(status, 403)
            self.assertNotIn('source', json.loads(raw)['error'])
            f.gateway.call.side_effect = ValueError('tool_allowlist')
            status, _, raw = self.stream_http(f, f.body)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(raw)['error'], dict(message='invalid or unreconciled request',
                                                          type='invalid_request_error'))
            self.assertEqual(f.gateway.call.call_count, 1)

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

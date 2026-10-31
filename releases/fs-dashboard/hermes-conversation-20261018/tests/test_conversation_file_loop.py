"""Synthetic worker/tool loop through real A bindings + B consumer + ScopedTools.

No provider, credentials, HTTP business service or production state is involved.
"""
import importlib.util
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
        cls.strategies = strategies

    def test_active_service_submit_and_admission_attach_without_preparing_read(self):
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
        inprocess.spending_hold = lambda *a: False
        inprocess.gateway = lambda *a: types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model': 'synthetic'}))
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
        injected = {'controller': controller, 'fs_evidence': evidence, 'fs_inprocess': inprocess,
                    'pilot': pilot, 'business_context': context_module, 'skill_bundle': skills,
                    'learning_registry': registry}
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, injected):
            module = load('file_loop_active_service', CORE / 'conversation_service.py')
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
            self.assertIn(self.prompt(), admission['prompt'])
            self.assertTrue(admissions[-1]['ready'])
            self.assertEqual(service.detail('alice', cid)['turns'][0]['state'], 'completed')

    def test_upload_bind_scripted_worker_revision_download_and_followup(self):
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
                handle(handler, method, urlsplit('/api/hermes/conversations/' + cid + suffix), user, service, lambda _: True)
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
                gateway = self.gateway_module.ScopedTools(tasks, book, lambda: 0)
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


if __name__ == '__main__':
    unittest.main()

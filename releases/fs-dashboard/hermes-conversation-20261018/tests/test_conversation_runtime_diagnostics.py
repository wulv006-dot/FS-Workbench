"""Read-only process diagnostics, real SQLite, isolated production entry AST."""
import ast
from contextlib import closing
from email.message import Message
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parents[2]
sys.path[:0] = [str(MODULE / 'source'), str(MODULE.parent / 'hermes-fc-pilot-20261013')]
from conversation_store import ConversationStore
from conversation_material_runs import MaterialService, MaterialRuntime
from pilot import TaskStore
from test_conversation_goal_tasks import index_metadata, MetadataRows

RANGE = REPO / 'releases/fs-dashboard/dashboard-refresh-20261025/source/range_api.py'
HTTP = [MODULE / 'source/conversation_http.py',
        REPO / 'releases/fc-coins/fc-pricing-v3-20261026/source/conversation_http.py']
NAMES = {'conversation_runtime_diagnostics', 'bind_conversation_diagnostics', 'conversation_get'}


def range_entry():
    tree = ast.parse(RANGE.read_text('utf-8'))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    assert {n.name for n in selected} == NAMES
    namespace = {'re': re}
    # Do not import range_api: its real readers, services and recovery never run.
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(RANGE), 'exec'), namespace)
    return namespace, tree


def load_http(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.fresh_service(Path(self.temp.name))

    def fresh_service(self, root):
        self.store = ConversationStore(root / 'conversations')
        self.cid = self.store.create('alice')['conversation_id']
        self.tasks = TaskStore(root / 'tasks.sqlite3')
        self.allowed = True
        self.auth = lambda user: self.allowed
        self.hermes = SimpleNamespace(root=root, tasks=self.tasks, authorizer=self.auth)
        self.service = SimpleNamespace(store=self.store, hermes=self.hermes)
        self.materials = MaterialService(self.hermes, self.service)
        self.service.materials = self.materials

    def test_real_http_old_index_loop_fails_then_legacy_proof_initializes_empty_original_lookup(self):
        def old_index_loop(db):
            # Exact old validation, swapped in memory only. All constructor,
            # real DB transactions, MaterialService and HTTP code stay actual.
            unique = []
            for index in db.execute('PRAGMA index_list(tasks)'):
                if index['unique'] and not index['partial']:
                    name = index['name'].replace('"', '""')
                    unique.append(tuple(r['name'] for r in db.execute('PRAGMA index_info("'+name+'")')))
            if ('owner', 'fingerprint') not in unique or ('run_id',) not in unique:
                raise OSError('goal_task_original_schema_unavailable')
        for number, path in enumerate(HTTP):
            with self.subTest(http=path):
                self.fresh_service(Path(self.temp.name)/('actual-http-'+str(number)))
                http = load_http(path, 'compat_http_'+str(number))
                before = self.snapshot()
                from conversation_goal_tasks import ConversationGoalTasks
                with index_metadata(), patch('conversation_goal_tasks._task_unique_indexes', old_index_loop):
                    with self.assertRaises(IndexError) as error:
                        ConversationGoalTasks(self.tasks, 'alice', self.cid, lambda *a: True, expected_path=self.tasks.path)
                    self.assertIsInstance(error.exception, LookupError)
                    code, value, _ = self.request(http, '/materials/original-request')
                    self.assertEqual((code, value), (404, {'error':'not_found','source':'material_http','stage':'lookup'}))
                self.assertEqual(before, self.snapshot())
                with index_metadata(), patch('socket.socket.connect', side_effect=AssertionError('no network')), \
                        patch.object(MaterialRuntime, 'reconcile', side_effect=AssertionError('no original run')), \
                        patch.object(MaterialRuntime, 'start', side_effect=AssertionError('no POST')):
                    code, value, headers = self.request(http, '/materials/original-request')
                    self.assertEqual((code, value), (404, {'error':'not_found','source':'material_http','stage':'lookup'}))
                    self.assertEqual(headers['X-FS-Material-Adapter'], 'materials_runtime_diagnostics_v1')
                after = self.snapshot()
                conversation = after[str(self.store.path)][2]; tasks = after[str(self.tasks.path)][2]
                self.assertEqual(conversation['conversation_goals_v1'], 0)
                self.assertEqual(conversation['conversation_goal_mutations_v1'], 0)
                for table in ('conversation_goal_outbox_v1', 'conversation_material_selections_v1', 'conversation_material_runs_v1', 'tasks'):
                    self.assertEqual(tasks[table], 0)
                self.assertEqual(tasks['conversation_goal_outbox_identity_v1'], 1)
                with self.tasks.db() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)

    def test_real_http_unprovable_index_metadata_is_503_without_private_schema(self):
        def incomplete(sql, parameters, fields, rows):
            if sql == 'PRAGMA index_list(tasks)':
                return MetadataRows(['seq', 'name'], [[r['seq'], r['name']] for r in rows])
        for number, path in enumerate(HTTP):
            self.fresh_service(Path(self.temp.name)/('unprovable-http-'+str(number)))
            before = self.snapshot(); http = load_http(path, 'unprovable_http')
            with index_metadata(incomplete):
                code, value, _ = self.request(http, '/materials/original-request')
            self.assertEqual((code, value), (503, {'error':'conversation_unavailable'}))
            self.assertEqual(before, self.snapshot())

    def snapshot(self):
        result = {}
        for value in (self.store.path, self.tasks.path):
            path = Path(value)
            with closing(sqlite3.connect(path)) as db:
                tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
                counts = {name: db.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] for name in tables}
            result[str(path)] = (path.read_bytes(), tables, counts)
        return result

    def bind(self, http):
        entry, tree = range_entry()
        entry.update(CONVERSATION=self.service, conversation_handle=http.handle,
                     conversation_respond=http.respond, CONVERSATION_PREFIX=http.PREFIX,
                     hermes_authorizer=self.auth)
        entry['bind_conversation_diagnostics'](self.service, http.handle,
            store_path=self.store.path, tasks_path=self.tasks.path)
        return entry, tree

    def request(self, http, suffix, *, user='alice', method='GET', body=None, through_range=False):
        message = Message()
        raw = json.dumps(body or {}).encode()
        for k, v in {'Content-Length': str(len(raw)), 'Content-Type': 'application/json',
                     'X-FS-Advisor-Action': 'submit', 'Sec-Fetch-Site': 'same-origin'}.items():
            message[k] = v
        statuses, headers = [], {}
        handler = SimpleNamespace(headers=message, rfile=io.BytesIO(raw), wfile=io.BytesIO(),
            connection=SimpleNamespace(settimeout=lambda *a: None),
            send_response=statuses.append, send_header=lambda k, v: headers.update({k: v}),
            end_headers=lambda: None)
        uri = urlsplit(http.PREFIX + '/' + self.cid + suffix)
        if through_range:
            entry, _ = self.bind(http)
            entry['conversation_get'](handler, uri, user)
        else:
            http.handle(handler, method, uri, user, self.service, self.auth)
        return statuses[0], json.loads(handler.wfile.getvalue()), headers

    def test_two_http_and_real_range_entry_are_read_only_and_do_not_initialize_private_tables(self):
        for index, path in enumerate(HTTP):
            with self.subTest(http=str(path)):
                http = load_http(path, 'diagnostic_http_' + str(index))
                self.bind(http)
                before = self.snapshot()
                # These paths would initialize tables/dispatch if accidentally used.
                with patch.object(self.materials, '_parts', side_effect=AssertionError('no material initialization')), \
                        patch('socket.socket.connect', side_effect=AssertionError('no network')), \
                        patch.object(self.tasks, 'db', side_effect=AssertionError('no task auto-create')):
                    for via_range in (False, True):
                        code, value, headers = self.request(http, '/runtime-diagnostics', through_range=via_range)
                        self.assertEqual(code, 200)
                        self.assertEqual(set(value), {'version', 'http', 'materials_bound', 'materials_store_matches',
                            'materials_tasks_matches', 'store_path_matches_expected', 'tasks_path_matches_expected'})
                        self.assertTrue(all(value[k] is True for k in value if k not in ('version', 'http')))
                        self.assertEqual(value['http']['module_path'], str(path.resolve()))
                        self.assertEqual(set(value['http']), {'module_path', 'handle_code_filename', 'loaded_code_sha256',
                            'code_fingerprint_format', 'disk_file_sha256', 'materials_branch_present', 'adapter_version'})
                        self.assertEqual(value['http']['handle_code_filename'], str(path))
                        self.assertEqual(value['http']['disk_file_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                        self.assertTrue(value['http']['materials_branch_present'])
                        self.assertRegex(value['http']['loaded_code_sha256'], '^[a-f0-9]{64}$')
                        self.assertEqual(headers['X-FS-Material-Adapter'], 'materials_runtime_diagnostics_v1')
                self.assertEqual(before, self.snapshot())
                self.assertEqual(self.materials.runtimes, {})

    def test_auth_owner_revocation_and_invalid_route_do_not_disclose_diagnostics(self):
        for path in HTTP:
            http = load_http(path, 'diagnostic_denials'); self.bind(http)
            before = self.snapshot()
            for via_range in (False, True):
                for user, allowed, expected in ((None, True, 401), ('bob', True, 404), ('alice', False, 403), ('alice', 1, 403)):
                    self.allowed = allowed
                    code, value, _ = self.request(http, '/runtime-diagnostics', user=user, through_range=via_range)
                    self.assertEqual(code, expected); self.assertEqual(set(value), {'error'})
                self.allowed = True
                for suffix in ('/runtime-diagnostics?path=/etc/passwd', '/runtime-diagnostics?x=', '/runtime-diagnostics/extra'):
                    code, value, _ = self.request(http, suffix, through_range=via_range)
                    self.assertEqual(code, 404); self.assertEqual(value, {'error': 'not_found'})
            self.assertEqual(before, self.snapshot())

    def test_existing_goal_outbox_and_task_counts_and_bytes_are_unchanged(self):
        from conversation_goals import ConversationGoals
        from conversation_goal_tasks import ConversationGoalTasks
        goals = ConversationGoals(self.store, 'alice', self.cid, lambda *a: True)
        state = dict(version='b2_goal_state_v1', revision=1, goal_id='diagnostic-goal', owner='alice',
            scope_ref='synthetic', objective='Read-only check', constraints=[], status='active',
            next_check_at='2026-11-01T03:00:00+00:00', updated_at='2026-11-01T02:00:00+00:00',
            work=None, evidence=[], completed_actions=[])
        goals.cas_goal('diagnostic-goal', expected_revision=0, mutation_id='diagnostic-create', state=state)
        queue = ConversationGoalTasks(self.tasks, 'alice', self.cid, lambda *a: True, expected_path=self.tasks.path)
        binding = dict(owner='alice', cid=self.cid, goal_id='diagnostic-goal', scope_ref='synthetic',
                       request_id='diagnostic-request', intent_sha256='a'*64)
        handoff = dict(task_id='diagnostic-request', revision=1, goal='Read-only check', constraints=[],
                       evidence=[], completed_actions=[], next_step='Do not dispatch')
        queue.submit(binding=binding, handoff=handoff)
        http = load_http(HTTP[1], 'diagnostic_existing'); self.bind(http)
        before = self.snapshot()
        self.assertEqual(self.request(http, '/runtime-diagnostics', through_range=True)[0], 200)
        self.assertEqual(before, self.snapshot())

    def test_missing_or_wrong_db_is_never_repaired_and_bound_object_mismatch_is_explicit(self):
        http = load_http(HTTP[0], 'diagnostic_db'); entry, _ = self.bind(http)
        original = self.tasks.path
        self.tasks.path = self.hermes.root / 'missing.sqlite3'
        code, value, _ = self.request(http, '/runtime-diagnostics')
        self.assertEqual((code, value), (503, {'error': 'conversation_unavailable'}))
        self.assertFalse(self.tasks.path.exists()); self.tasks.path = original
        other = TaskStore(self.hermes.root / 'other.sqlite3')
        self.tasks.path = other.path
        code, value, _ = self.request(http, '/runtime-diagnostics')
        self.assertEqual(code, 200); self.assertFalse(value['tasks_path_matches_expected'])
        self.tasks.path = original
        self.service.materials = None
        code, value, _ = self.request(http, '/runtime-diagnostics')
        self.assertEqual(code, 200); self.assertFalse(value['materials_bound'])
        self.assertFalse(value['materials_store_matches']); self.assertFalse(value['materials_tasks_matches'])

    def test_loaded_code_and_disk_are_separate_and_range_observes_cached_old_same_name_module(self):
        old = Path(self.temp.name) / 'conversation_http.py'
        old.write_text("PREFIX='/api/hermes/conversations'\ndef respond(*args,**kwargs):\n pass\ndef handle(*args):\n return 'old route'\n", encoding='utf-8')
        current = load_http(HTTP[1], 'diagnostic_current')
        with patch.dict(sys.modules), patch.object(sys, 'path', [self.temp.name, str(HTTP[1].parent), *sys.path]):
            sys.modules.pop('conversation_http', None)
            entry, tree = self.bind(current)
            # The real import chooses the first same-name file under this path
            # order, then stays cached. No service constructor is imported.
            node = next(n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'conversation_http')
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(RANGE), 'exec'), entry)
            old_module = sys.modules['conversation_http']
            self.assertEqual(Path(old_module.__file__), old)
            entry['bind_conversation_diagnostics'](self.service, entry['conversation_handle'],
                store_path=self.store.path, tasks_path=self.tasks.path)
            first = self.service.runtime_diagnostics('alice', self.cid)
            old.write_text("def handle(*args):\n return 'different disk materials'\n", encoding='utf-8')
            second = self.service.runtime_diagnostics('alice', self.cid)
            self.assertEqual(first['http']['loaded_code_sha256'], second['http']['loaded_code_sha256'])
            self.assertNotEqual(first['http']['disk_file_sha256'], second['http']['disk_file_sha256'])
            self.assertEqual(second['http']['handle_code_filename'], str(old))
            self.assertFalse(second['http']['materials_branch_present'])
            self.assertIsNone(second['http']['adapter_version'])
            # The range-owned route still observes the original old function;
            # ordinary dispatch is not silently switched to the new module.
            with patch.dict(entry, {'conversation_handle': old_module.handle}):
                status, value = [], []
                entry['conversation_respond'] = lambda h, code, data, **kw: (status.append(code), value.append(data))
                entry['conversation_get'](object(), urlsplit(current.PREFIX+'/'+self.cid+'/runtime-diagnostics'), 'alice')
                self.assertEqual(status, [200]); self.assertEqual(value[0]['http'], second['http'])

    def test_material_route_http_owned_submit_owned_and_later_lookup_are_fixed_enums(self):
        body = {'client_request_id': 'test_request', 'goal': 'synthetic', 'file_ids': [], 'operation': {'mode': 'read'}}
        before = self.snapshot()
        for path in HTTP:
            http = load_http(path, 'diagnostic_stages')
            code, value, headers = self.request(http, '/materials', user=None, method='POST', body=body)
            self.assertEqual((code, value), (401, {'error': 'login_required'}))
            self.assertNotIn('X-FS-Material-Adapter', headers)
            cases = [('/materials/extra/extra', None, 'route'),
                     ('/materials?unexpected=1', None, 'route'),
                     ('/materials', 'http', 'http_owned'),
                     ('/materials', 'submit', 'submit_owned'),
                     ('/materials', 'later', 'lookup')]
            for suffix, fail, stage in cases:
                with self.subTest(path=path, stage=stage):
                    original = self.store._owned
                    calls = []
                    def owned(*args):
                        calls.append(True)
                        if fail == 'http' or fail == 'submit' and len(calls) == 2:
                            raise LookupError('DO NOT DISCLOSE OWNER OR DATABASE DETAILS')
                        return original(*args)
                    with patch.object(self.store, '_owned', owned):
                        # The real _queue must be in the traceback. Keep its
                        # owner guard but stop before any namespace is created.
                        def submit(owner, cid, payload):
                            if fail == 'submit': return self.materials._queue(owner, cid)
                            raise LookupError('DO NOT DISCLOSE LATER INTERNAL DATA')
                        with patch.object(self.materials, 'submit', side_effect=submit):
                            code, value, headers = self.request(http, suffix, method='POST', body=body)
                    self.assertEqual(code, 404)
                    self.assertEqual(value, {'error': 'not_found', 'stage': stage, 'source': 'material_http'})
                    self.assertEqual(headers['X-FS-Material-Adapter'], 'materials_runtime_diagnostics_v1')
            self.assertEqual(before, self.snapshot())

    def test_range_actual_get_method_calls_the_isolated_entry_and_health_stays_unchanged(self):
        _, tree = range_entry()
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        get = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_GET')
        # Execute only the production conversation dispatch if block.
        branch = get.body[2]
        self.assertIn('CONVERSATION_PREFIX', ast.unparse(branch))
        calls = []
        fake = SimpleNamespace(headers={'X-Auth-User': 'synthetic'})
        env = {'uri': urlsplit('/api/hermes/conversations/'+self.cid+'/runtime-diagnostics'),
               'self': fake, 'CONVERSATION_PREFIX': '/api/hermes/conversations', 'CONVERSATION': self.service,
               'conversation_get': lambda *a: calls.append(a), 'conversation_respond': self.fail}
        function = ast.FunctionDef(name='dispatch', args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
                                   body=[branch], decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(RANGE), 'exec'), env)
        env['dispatch'](); self.assertEqual(calls, [(fake, env['uri'], 'synthetic')])
        self.assertNotIn('diagnostic', ast.unparse(get.body[1]))


if __name__ == '__main__':
    unittest.main()

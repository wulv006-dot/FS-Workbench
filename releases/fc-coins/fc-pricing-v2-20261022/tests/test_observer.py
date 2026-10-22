import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
import fc_observer as observer

RUN = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


class ObserverRead(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('jobs', 'queue'):
            (self.root / name).mkdir()
        self.api = SimpleNamespace(ROOT=self.root, read_json=lambda p: json.loads(p.read_text()),
            load_policy=lambda: {'revision': 40},
            automation_view=lambda *a: {'revision': 40, 'can_edit_discount_rules': True},
            monitor_view=lambda: {'generated_at': '2026-10-22T03:20:00Z',
                                 'publication': {'status': 'matched', 'execution_id': RUN,
                                     'platforms': [{'platform': 'PS', 'public_page_usd': '11.20',
                                        'public_checked_at': '2026-10-22T02:41:00Z', 'token': 'CANARY'}]},
                                 'health': {'queue_depth': 0, 'credentials': 'CANARY'},
                                 'player_sync': {'private': 'CANARY'}})

    def read(self, path):
        return observer.read_observation(self.api, urlsplit(path))

    def test_monitor_preserves_original_public_time_and_drops_unapproved_fields(self):
        code, data = self.read('/monitor')
        self.assertEqual(code, 200)
        self.assertEqual(data['publication']['execution_id'], RUN)
        self.assertEqual(data['publication']['platforms'][0]['public_checked_at'],
                         '2026-10-22T02:41:00Z')
        self.assertNotIn('CANARY', json.dumps(data))
        self.assertFalse(data['observer_can_execute'])

    def test_automation_never_advertises_observer_edit_authority(self):
        code, data = self.read('/automation')
        self.assertEqual(code, 200)
        self.assertEqual(data['revision'], 40)
        self.assertFalse(data['can_edit_discount_rules'])

    def test_jobs_project_only_coins_status_and_model_receipt_ids(self):
        value = {'job_id': RUN, 'kind': 'auto_cycle', 'status': 'failed',
                 'request': {'customer_email': 'CANARY'}, 'result': {'status': 'FAILED',
                 'orders': ['CANARY']}, 'hermes_review': {'turn_id': 'turn1',
                 'recommendation': {'text': 'CANARY'}, 'turn': {'state': 'failed', 'text': 'CANARY'}}}
        (self.root / 'jobs' / (RUN + '.json')).write_text(json.dumps(value))
        code, data = self.read('/jobs/' + RUN)
        self.assertEqual(code, 200)
        self.assertEqual(data['status'], 'failed')
        self.assertEqual(data['hermes_review']['turn_id'], 'turn1')
        self.assertNotIn('CANARY', json.dumps(data))
        value['kind'] = 'player_sync'
        (self.root / 'jobs' / (RUN + '.json')).write_text(json.dumps(value))
        self.assertEqual(self.read('/jobs/' + RUN)[0], 403)
        value['kind'], value['job_id'] = 'auto_cycle', 'wrong'
        (self.root / 'jobs' / (RUN + '.json')).write_text(json.dumps(value))
        self.assertEqual(self.read('/jobs/' + RUN)[0], 403)

    def test_queries_unknown_routes_and_other_ledgers_are_denied_before_reads(self):
        self.api.monitor_view = lambda: self.fail('must not read')
        for path in ('/monitor?refresh=true', '/monitor?x=1', '/quotes/' + RUN,
                     '/audits/' + RUN, '/activity', '/jobs/../../private', '/monitor/'):
            with self.subTest(path=path):
                self.assertEqual(self.read(path)[0], 403)
        self.assertEqual(self.read('/jobs/' + RUN)[0], 404)

    def test_quote_is_read_only_projection_without_owned_model_lookup(self):
        value = dict(version='v13', quote_usable=False, execution_ready=False,
            quote={'run_id': RUN, 'evidence': {'checked_at': '2026-10-22T02:30:00Z',
                   'credentials': 'CANARY', 'fx': {'cny_per_usd': '7', 'url': 'CANARY'}},
                   'result': {'rows': [{'platform': 'PS', 'gross_margin_pct': '25',
                                       'orders': 'CANARY', 'proof': {'customer': 'CANARY'}}]}},
            recent=[{'job_id': RUN, 'kind': 'auto_cycle', 'request': {'password': 'CANARY'}}],
            hermes_review={'text': 'CANARY'})
        calls = []
        module = SimpleNamespace(state=lambda **kw: (calls.append(kw) or copy.deepcopy(value)))
        with patch.dict(sys.modules, pricing_state=module):
            code, data = self.read('/pricing/state')
        self.assertEqual(code, 200)
        self.assertEqual(calls, [{'root': self.root, 'owner': None}])
        self.assertFalse(data['quote_usable'])
        self.assertEqual(data['quote']['run_id'], RUN)
        self.assertNotIn('CANARY', json.dumps(data))

    def test_malformed_existing_ledger_fails_without_raw_payload_or_retry(self):
        (self.root / 'jobs' / (RUN + '.json')).write_text('CANARY invalid json')
        self.assertEqual(self.read('/jobs/' + RUN), (503, {'error': 'observer_state_unavailable'}))

    def test_actual_post_handler_rejects_before_body_or_any_side_effect(self):
        tree = ast.parse((SOURCE / 'fc27_cloud_api.py').read_text('utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     'fc27_cloud_api.do_POST', 'exec'), namespace)
        responses = []
        handler = SimpleNamespace(actor=lambda: 'dot_fc_observer',
            body=lambda: self.fail('read body before rejecting observer'),
            respond=lambda code, data: responses.append((code, data)))
        namespace['do_POST'](handler)
        self.assertEqual(responses, [(403, {'error': 'observer_read_only'})])

    def test_publisher_auth_replacement_keeps_all_other_consumer_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'fc_v2_release_adapter.py').write_bytes((SOURCE.parent / 'deploy/release.py').read_bytes())
            (root / 'observer.py').write_bytes((SOURCE.parent / 'deploy/observer.py').read_bytes())
            spec = importlib.util.spec_from_file_location('observer_release_check', root / 'observer.py')
            wrapper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(wrapper)
            adapter = wrapper.adapter
            anchor = "  if not required.issubset(protected) or set(protected)&set(targets.values()):raise ValueError('Hermes protected consumer boundary differs')"
            source = "def check(required, protected, targets):\n" + anchor + "\n"
            namespace = {}
            exec(adapter.approved_auth_source(source), namespace)
            required = {'/opt/fs-access-policy/access_policy.py', '/protected/other-consumer'}
            targets = adapter.TARGETS
            namespace['check'](set(required), {'/protected/other-consumer'}, targets)
            with self.assertRaisesRegex(ValueError, 'protected consumer'):
                namespace['check'](set(required), set(), targets)
            with self.assertRaisesRegex(ValueError, 'protected consumer'):
                namespace['check'](set(required), required, targets)
            adapter.TARGETS = dict(targets, extra='/opt/unapproved.py')
            with self.assertRaisesRegex(ValueError, 'exact_observer_auth'):
                adapter.approved_auth_source(source)


if __name__ == '__main__':
    unittest.main()

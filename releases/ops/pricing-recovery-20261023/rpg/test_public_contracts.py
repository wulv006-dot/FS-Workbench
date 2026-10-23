"""Self-contained CI regression of the exact new logic; no private baseline needed."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import admin_cache_local as admin
import prepare_candidate as candidate


class PublicContracts(unittest.TestCase):
    def test_unknown_partial_and_prewrite_recovery_are_distinct(self):
        scope = {}
        exec(candidate.CLASSIFY, scope)
        classify = scope['execution_state']
        zero = {'finished': True, 'write_attempts': 0}
        self.assertEqual(classify(None, zero, 1), ('prewrite_failed', True))
        for phase, code in (({}, 1), (zero, 0), (zero, -9), ({'finished': False, 'write_attempts': 0}, 1),
                            ({'finished': True, 'write_attempts': 1}, 1)):
            self.assertEqual(classify(None, phase, code), ('unknown', False))
        result = {'ok': 1, 'fail': 0, 'mismatch': [['synthetic', 1]], 'jobs': []}
        self.assertEqual(classify(result, {'write_attempts': 1}, 1), ('partial', False))
        self.assertEqual(classify({'ok': 1}, {}, 0), ('unknown', False))
        result = {'ok': 42, 'fail': 0, 'mismatch': [], 'jobs': [], 'clearcache_ok': False}
        self.assertEqual(classify(result, {'write_attempts': 42}, 0), ('confirmed', False))

    def test_phase_receipt_precedes_mutation_and_blocks_original_id_replay(self):
        tree = ast.parse(candidate.PHASE)
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'execution.json')
            scope = {'os': os, 'json': json, 'sys': types.SimpleNamespace(argv=['srv_run.py', 'writegold']), 'EXECUTION': {'job_id': 'synthetic', 'write_attempts': 0, 'finished': False},
                     'P': types.SimpleNamespace(main=Mock(side_effect=RuntimeError('cookie unavailable')))}
            exec(compile(tree, 'phase', 'exec'), scope)
            with patch.dict(os.environ, {'FS_RPG_JOB_ID': 'synthetic', 'FS_RPG_EXECUTION_RECEIPT': str(path)}):
                with self.assertRaisesRegex(RuntimeError, 'cookie unavailable'):
                    scope['run_job']()
                self.assertEqual(json.loads(path.read_text())['write_attempts'], 0)
                self.assertTrue(json.loads(path.read_text())['finished'])
                scope['EXECUTION']['finished'] = False
                def write_then_fail():
                    scope['before_write']()
                    self.assertEqual(json.loads(path.read_text())['write_attempts'], 1)
                    raise TimeoutError()
                scope['P'].main.side_effect = write_then_fail
                with self.assertRaises(TimeoutError):
                    scope['run_job']()
                with self.assertRaisesRegex(RuntimeError, 'reconcile_original_execution'):
                    scope['run_job']()
                self.assertEqual(scope['P'].main.call_count, 2)

    def test_existing_read_only_and_cache_commands_need_no_price_receipt(self):
        tree = ast.parse(candidate.PHASE)
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        for name in ('ping', 'read', 'readgame', 'clearcache'):
            scope = {'os': os, 'json': json, 'sys': types.SimpleNamespace(argv=['srv_run.py', name]),
                     'EXECUTION': {'job_id': None, 'write_attempts': 0, 'finished': False},
                     'P': types.SimpleNamespace(main=Mock(return_value=0))}
            exec(compile(tree, 'phase', 'exec'), scope)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(scope['run_job'](), 0)
            scope['P'].main.assert_called_once_with()

    def test_owner_unavailable_sends_no_cache_post(self):
        cache = types.SimpleNamespace(load_token=lambda: None, clear_cache=Mock())
        scope = {'admin_cache': cache, 'log': Mock(), 'json': json, 'time': Mock()}
        exec(candidate.CLEAR_MAIN, scope)
        self.assertEqual(scope['clear_main_cache'](), (False, 'shared_admin_unavailable'))
        cache.clear_cache.assert_not_called()

    def test_unknown_cache_post_is_never_repeated(self):
        owner = Mock()
        owner.request.side_effect = TimeoutError('synthetic-secret')
        with patch.object(admin, 'SessionManager', return_value=owner):
            self.assertEqual(admin.clear_cache('all', 'synthetic-token'),
                             (0, 'admin_clear_outcome_unknown:TimeoutError'))
        owner.request.assert_called_once()
        cache = types.SimpleNamespace(load_token=lambda: 'synthetic-token', clear_cache=Mock(return_value=(0, 'unknown')))
        scope = {'admin_cache': cache, 'log': Mock(), 'json': json, 'time': Mock()}
        exec(candidate.CLEAR_MAIN, scope)
        self.assertFalse(scope['clear_main_cache']()[0])
        cache.clear_cache.assert_called_once()
        scope['time'].sleep.assert_not_called()

    def test_only_confirmed_throttle_can_retry_same_cache_request(self):
        cache = types.SimpleNamespace(load_token=lambda: 'synthetic-token', clear_cache=Mock(side_effect=[
            (200, '{"code":0,"msg":"throttled"}'), (200, '{"code":1,"msg":"confirmed"}')]))
        scope = {'admin_cache': cache, 'log': Mock(), 'json': json, 'time': Mock(), '_throttled': lambda message: message == 'throttled'}
        exec(candidate.CLEAR_MAIN, scope)
        self.assertEqual(scope['clear_main_cache'](), (True, 'confirmed'))
        scope['time'].sleep.assert_called_once_with(31)
        self.assertEqual(cache.clear_cache.call_args_list[0], cache.clear_cache.call_args_list[1])

    def test_no_independent_admin_login_or_persisted_token(self):
        text = Path(admin.__file__).read_text(encoding='utf-8')
        for forbidden in ('p2pah_autologin', 'playwright', '_admin_token.json', 'login_admin', 'open('):
            self.assertNotIn(forbidden, text)
        owner = Mock(token='synthetic-token')
        with patch.object(admin, 'SessionManager', return_value=owner):
            self.assertEqual(admin.load_token(), 'synthetic-token')
        owner.ensure.assert_called_once_with()
        with patch.object(admin, 'load_token', return_value='synthetic-token') as read, patch.object(admin, 'log'):
            self.assertEqual(admin.cmd_login(types.SimpleNamespace()), 0)
        read.assert_called_once_with()

    def test_prepare_rejects_changed_baseline_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory, 'baseline'); baseline.mkdir()
            (baseline / 'srv_exec.py').write_text('changed', encoding='utf-8')
            output = Path(directory, 'output')
            with self.assertRaisesRegex(ValueError, 'baseline_changed:srv_exec.py'):
                candidate.prepare(baseline, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

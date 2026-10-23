import ast
import hashlib
import json
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if os.name == 'nt':
    # Windows unit tests mock the Unix lock; actual flock is checked separately on Linux.
    sys.modules['fcntl'] = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=Mock())
runtime = load('madden_runtime_test', ROOT / 'source/browser_runtime.py')
browser = load('madden_browser_test', ROOT / 'source/madden_nfl_27/browser.py')
tree = ast.parse((ROOT / 'source/dashboard/server.py').read_text(encoding='utf-8-sig'))
ns = dict(datetime=datetime, timedelta=timedelta, timezone=timezone)
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                             and n.name == '_next_after_settings'], type_ignores=[]),
             'schedule_helper', 'exec'), ns)


class RecoveryTests(unittest.TestCase):
    def test_backend_uses_fresh_chrome_and_shared_identity(self):
        pw = Mock(); launched = pw.chromium.launch.return_value
        ctx = launched.new_context.return_value
        auth = types.SimpleNamespace(apply=Mock())
        with patch.dict(os.environ, MADDEN_ISOLATED_BACKEND='1'), patch.dict(sys.modules, fs_order_client=auth):
            result, close = browser.session(pw, '/old/profile')
        self.assertIs(result, ctx)
        pw.chromium.connect_over_cdp.assert_not_called()
        auth.apply.assert_called_once_with(ctx)
        close(); ctx.close.assert_called_once(); launched.close.assert_called_once()

    def test_auth_failure_closes_chrome_and_never_falls_back(self):
        pw = Mock(); auth = types.SimpleNamespace(apply=Mock(side_effect=RuntimeError('original_session_unavailable')))
        with patch.dict(os.environ, MADDEN_ISOLATED_BACKEND='1'), patch.dict(sys.modules, fs_order_client=auth):
            with self.assertRaisesRegex(RuntimeError, 'original_session_unavailable'):
                browser.session(pw, '/old/profile')
        pw.chromium.launch.return_value.close.assert_called_once()
        pw.chromium.connect_over_cdp.assert_not_called()

    def test_context_creation_failure_closes_chrome(self):
        pw = Mock(); pw.chromium.launch.return_value.new_context.side_effect = RuntimeError('no_context')
        with patch.dict(os.environ, MADDEN_ISOLATED_BACKEND='1'), patch.dict(sys.modules, fs_order_client=types.SimpleNamespace(apply=Mock())):
            with self.assertRaises(RuntimeError): browser.session(pw, '/old/profile')
        pw.chromium.launch.return_value.close.assert_called_once()

    def test_close_failure_still_closes_chrome(self):
        pw = Mock(); ctx = pw.chromium.launch.return_value.new_context.return_value
        ctx.close.side_effect = RuntimeError('close_failed')
        with patch.dict(os.environ, MADDEN_ISOLATED_BACKEND='1'), patch.dict(sys.modules, fs_order_client=types.SimpleNamespace(apply=Mock())):
            _, close = browser.session(pw, '/old/profile')
        with self.assertRaisesRegex(RuntimeError, 'close_failed'): close()
        pw.chromium.launch.return_value.close.assert_called_once()

    def test_competitor_still_uses_own_cdp_context(self):
        pw = Mock()
        with patch.object(browser, 'CDP_ENDPOINT', 'http://competitor:9222'):
            ctx, close = browser.fresh(pw)
        pw.chromium.connect_over_cdp.assert_called_once_with('http://competitor:9222')
        close(); ctx.close.assert_called_once()
        pw.chromium.launch.assert_not_called()

    def test_worker_keeps_exact_operation_and_budget(self):
        original = {'Id': 'a'*64, 'Image': 'sha256:'+'b'*64, 'HostConfig': {'NetworkMode': 'bridge'}}
        args = ['-u','run_pipeline.py','--write','--operation-id=original-operation']
        cmd = runtime.command(args, 2700, original, 'madden-job-'+'c'*32, True)
        self.assertEqual(cmd[-len(args):], args)
        self.assertIn('2700s', cmd)
        self.assertEqual(cmd[cmd.index('--memory')+1], '2g')
        self.assertIn('container:'+'a'*64, cmd)
        self.assertIn('MADDEN_ISOLATED_BACKEND=1', cmd)
        self.assertNotIn('/profile', ' '.join(cmd))
        self.assertNotIn('P2PAH_PASSWORD', ' '.join(cmd))

    def test_backend_only_does_not_need_competitor(self):
        for args in (['--snapshot-out','x'], ['--targets-json=x','--write'], ['--restore'], ['--from-evidence']):
            with self.subTest(args=args):self.assertFalse(runtime.needs_competitors(args))
        self.assertTrue(runtime.needs_competitors(['--write','--quote-out=x']))

    def test_invalid_budget_or_program_rejected(self):
        for args, budget in ((['-u','other.py'],900), (['-u','run_pipeline.py'],0), (['-u','run_pipeline.py'],2701)):
            with self.assertRaises(ValueError):runtime.command(args,budget,{},'name',False)

    def test_idle_never_stops_active_worker(self):
        with patch.object(runtime,'workers',return_value=['owned']), patch.object(runtime,'call') as invoke:
            self.assertFalse(runtime.stop_idle())
        invoke.assert_not_called()

    def test_failed_stop_is_not_reported_as_released(self):
        with patch.object(runtime,'workers',return_value=[]), patch.object(runtime,'inspect',return_value={'State':{'Running':True}}), patch.object(runtime,'call',return_value=types.SimpleNamespace(returncode=1)), patch.object(runtime,'state') as record:
            with self.assertRaisesRegex(RuntimeError,'madden_idle_stop_unverified'):runtime.stop_idle()
            record.assert_called_once_with(status='cleanup_unverified')

    def test_idle_stop_verified_before_state_commit(self):
        with patch.object(runtime,'workers',return_value=[]), patch.object(runtime,'inspect',side_effect=[{'State':{'Running':True}},{'State':{'Running':False}}]), patch.object(runtime,'call',return_value=types.SimpleNamespace(returncode=0)) as invoke, patch.object(runtime,'state') as record:
            self.assertTrue(runtime.stop_idle())
        self.assertEqual(invoke.call_args.args[0], ['stop','--time','10',runtime.CONTAINER])
        record.assert_called_once_with(status='idle_stopped',worker=None,competitor_running=False)

    def test_six_hour_change_does_not_dispatch_immediately(self):
        now=datetime(2026,10,23,13,30,tzinfo=timezone.utc)
        before={'interval_minutes':240,'system_enabled':True,'mode':'auto'}
        after={**before,'interval_minutes':360}
        next_at=ns['_next_after_settings'](before,after,{'created_at':'2026-10-23T10:47:45+00:00'},now)
        self.assertEqual(next_at,datetime(2026,10,23,16,47,45,tzinfo=timezone.utc))
        self.assertGreater(next_at,now)

    def test_missing_anchor_waits_new_interval(self):
        now=datetime.now(timezone.utc)
        before={'interval_minutes':240};after={'interval_minutes':360}
        self.assertEqual(ns['_next_after_settings'](before,after,{},now),now+timedelta(hours=6))

    def test_explicit_enable_keeps_original_immediate_semantics(self):
        now=datetime.now(timezone.utc)
        self.assertEqual(ns['_next_after_settings']({'system_enabled':False,'interval_minutes':240},{'system_enabled':True,'interval_minutes':360},{},now),now)

    def test_original_business_functions_unchanged(self):
        prior=json.loads((ROOT/'protected-functions.json').read_text())
        self.assertEqual(len(prior),7)
        source=(ROOT/'source/dashboard/server.py').read_text(encoding='utf-8-sig')
        current={n.name:hashlib.sha256(ast.get_source_segment(source,n).encode()).hexdigest() for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name,expected in prior.items():
            with self.subTest(name=name): self.assertEqual(expected,current[name])


if __name__=='__main__':unittest.main(verbosity=2)

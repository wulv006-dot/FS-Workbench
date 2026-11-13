import ast
import hashlib
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import sys

SOURCE = Path(__file__).resolve().parents[1] / 'source'
spec = importlib.util.spec_from_file_location('fc_admin_dc_under_test', SOURCE / 'fc_shared_admin.py')
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


def response(value):
    result = io.BytesIO(json.dumps(value).encode())
    result.status = 200
    return result


class AdminDcTests(unittest.TestCase):
    def manager(self):
        return admin.SessionManager({'P2PAH_API_BASE': admin.API_BASES[0]})

    def test_config_has_no_session_or_credential_dependency(self):
        with patch.dict(os.environ, {'FS_ADMIN_SESSION_URL': 'http://retired:8767'}, clear=True):
            self.assertEqual(admin.read_private_config()['P2PAH_API_BASE'], admin.API_BASES[0])
        with patch.dict(os.environ, {'FS_ADMIN_API_BASE': admin.API_BASES[2]}, clear=True):
            self.assertEqual(admin.read_private_config()['P2PAH_API_BASE'], admin.API_BASES[2])
        with patch.dict(os.environ, {'FS_ADMIN_API_BASE': 'https://admin-api.p2pah.cn'}, clear=True):
            with self.assertRaises(ValueError):
                admin.read_private_config()

    def test_ensure_requires_business_code_and_bound_api_identity(self):
        for code, user, expected in [(1, 'wulvapi', True), (1, 'chenchaoapi', True),
                                     (401, 'wulvapi', False), (1, 'wulv', False)]:
            with self.subTest(code=code, user=user):
                manager = self.manager()
                manager.request = Mock(return_value=(200, json.dumps({
                    'code': code, 'data': {'adminInfo': {'username': user}}}).encode()))
                self.assertEqual(manager.ensure(), expected)
                manager.request.assert_called_once_with('/admin/index/index')
                self.assertEqual(bool(manager.token), expected)

    def test_ensure_unavailable_is_false(self):
        manager = self.manager()
        manager.request = Mock(side_effect=OSError('unavailable'))
        self.assertFalse(manager.ensure())

    def test_direct_request_preserves_wire_contract_without_batoken(self):
        manager = self.manager()
        manager.opener = Mock()
        manager.opener.open.return_value = response({'code': 1, 'data': {}})
        payload = {'id': 123, 'unit_price': '0.0738'}
        status, raw = manager.request('/admin/goods.Goods/edit', data=payload, token='old-token')
        request = manager.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, admin.API_BASES[0] + '/admin/goods.Goods/edit')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.data, json.dumps(payload).encode())
        self.assertNotIn('batoken', {key.lower() for key in request.headers})
        self.assertEqual((status, json.loads(raw)['code']), (200, 1))
        manager.opener.open.assert_called_once()
        self.assertEqual(manager.opener.open.call_args.kwargs, {'timeout': 15})

    def test_post_does_not_retry_and_http_error_keeps_response(self):
        manager = self.manager()
        manager.opener = Mock()
        manager.opener.open.side_effect = OSError('unknown')
        with self.assertRaises(OSError):
            manager.request('/admin/goods.Goods/edit', data={})
        manager.opener.open.assert_called_once()
        manager.opener.open.side_effect = urllib.error.HTTPError(
            'http://local/admin', 403, 'Forbidden', {}, io.BytesIO(b'{"code":401}'))
        self.assertEqual(manager.request('/admin/index/index'), (403, b'{"code":401}'))
        manager.opener.open.side_effect.close()

    def test_real_all_and_players_callers_use_adapter_request_protocol(self):
        for name in ['coin_all_sync_job', 'player_sync_job']:
            with self.subTest(name=name):
                spec = importlib.util.spec_from_file_location('direct_dc_' + name, SOURCE / (name + '.py'))
                caller = importlib.util.module_from_spec(spec)
                with patch.dict(sys.modules, {'p2pah_session_service': admin}):
                    spec.loader.exec_module(caller)
                manager = self.manager()
                manager.opener = Mock()
                manager.opener.open.side_effect = lambda *args, **kwargs: response({
                    'code': 1, 'data': {'adminInfo': {'username': 'wulvapi'}}})
                self.assertTrue(manager.ensure())
                identity = caller.api(manager, '/admin/index/index')
                self.assertEqual(identity['adminInfo']['username'], 'wulvapi')
                for call in manager.opener.open.call_args_list:
                    request = call.args[0]
                    self.assertTrue(request.full_url.startswith(admin.API_BASES[0] + '/admin/'))
                    self.assertNotIn('batoken', {key.lower() for key in request.headers})

    def test_real_sync_recipient_uses_ensure_and_two_stable_reads(self):
        spec = importlib.util.spec_from_file_location('coin_all_sync_job', SOURCE / 'coin_all_sync_job.py')
        coin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(coin)
        tree = ast.parse((SOURCE / 'price_writer.py').read_text(encoding='utf8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'confirm_sync_recipient')
        namespace = {'sys': sys, 'current_cycle_quote': Mock(), 'datetime': datetime,
                     'timezone': timezone, 'same_money': lambda a, b: str(a) == str(b)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'real-sync-recipient', 'exec'), namespace)
        opener = Mock()
        opener.open.side_effect = lambda *args, **kwargs: response({
            'code': 1, 'data': {'adminInfo': {'username': 'wulvapi'}}})
        with patch.dict(sys.modules, {'p2pah_session_service': admin, 'coin_all_sync_job': coin}), \
                patch.object(admin, 'build_opener', return_value=opener), \
                patch.object(coin, 'read_row', return_value={'unit_price': '7.38', 'more': {'price': ['7.38']}}), \
                patch('time.sleep'):
            result = namespace['confirm_sync_recipient']({
                'preview_id': 'same-preview', 'selected': 'daily', 'automation_policy_revision': 42,
                'targets': [{'platform': 'PS', 'quote': '7.38'}]})
        self.assertEqual(result['basis'], 'two_stable_original_admin_recipient_reads')
        self.assertFalse(result['sync_replayed'])
        self.assertEqual(len(result['rounds']), 2)

    def test_login_and_external_urls_are_rejected(self):
        manager = self.manager()
        manager.opener = Mock()
        for path in ['/admin/index/login', '/admin/index/login?x=1',
                     'https://admin-api.p2pah.cn/admin/index/index', '/api/common/captcha']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                manager.request(path, data={})
        manager.opener.open.assert_not_called()

    def test_shells_mount_one_adapter_and_choose_reachable_dc_base(self):
        for name in ['execute_price.sh', 'reconcile_price.sh', 'restore_price.sh',
                     'sync_players.sh', 'clear_cache_after_write.sh']:
            with self.subTest(name=name):
                text = (SOURCE / name).read_text(encoding='utf8')
                self.assertEqual(text.count('dst=/usr/local/bin/p2pah_session_service.py'), 1)
                self.assertNotIn('8767', text)
                self.assertNotIn('fs-global-admin.json', text)
                self.assertIn('src=/opt/fc27-cloud-browser/fc_shared_admin.py,dst=/usr/local/bin/p2pah_session_service.py', text)
                self.assertNotIn('src=/opt/fs-order-session/fc_shared_admin.py,', text)
                if name != 'clear_cache_after_write.sh':
                    self.assertIn('flock -w 20 9' if name == 'sync_players.sh' else 'flock -n 9', text)
                base = admin.API_BASES[0] if '--network host' in text else admin.API_BASES[2]
                self.assertIn('FS_ADMIN_API_BASE=' + base, text)

    def test_publisher_requires_exact_targets_with_cost_collector(self):
        spec = importlib.util.spec_from_file_location('fc_admin_target_map', SOURCE.parent / 'deploy/target_map.py')
        targets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(targets)
        mapping = targets.targets(SOURCE)
        self.assertEqual(targets.TARGET_COUNT, 101)
        self.assertEqual(len(mapping), targets.TARGET_COUNT)
        self.assertEqual(mapping['fc_shared_admin.py'], '/opt/fc27-cloud-browser/fc_shared_admin.py')
        self.assertNotIn('/opt/fs-order-session/fc_shared_admin.py', mapping.values())
        self.assertEqual(mapping['sync_players.sh'], '/opt/fc27-cloud-browser/sync_players.sh')
        self.assertEqual(mapping['collect_p2pah_cost.py'], '/opt/fc27-cloud-browser/collect_p2pah_cost.py')
        expected={prefix+'fc_pricing_v3/'+name for prefix in ('source/','source/hermes-copy/') for name in ('api.py','business_source.py','demand_model.py','engine.py','ledger.py','runtime.py','scheduler.py','selective_sources.py','smart.py')}
        expected.update({'source/fc27-coins.html','source/fc-pricing-v3.js','source/pricing_simulation.py'})
        self.assertEqual(set(targets.DELTA_NAMES),expected)
        self.assertEqual(len(targets.DELTA_NAMES),21)
        self.assertEqual(targets.DELTA_NEW,frozenset({'source/fc_pricing_v3/smart.py','source/hermes-copy/fc_pricing_v3/smart.py'}))
        # Default stages stay exact101; the explicit new stage adds only six
        # mirrored modules. Both actual mappings are checked, not code spelling.
        native = targets.three_platform_targets(SOURCE)
        self.assertEqual(targets.THREE_PLATFORM_TARGET_COUNT, 107)
        self.assertEqual(len(native), targets.THREE_PLATFORM_TARGET_COUNT)
        runtime_new={prefix+'fc_pricing_v3/'+name for prefix in ('','hermes-copy/')
                     for name in targets.THREE_PLATFORM_MODULES}
        self.assertEqual(set(native)-set(mapping),
                         runtime_new)
        # The pinned library is an explicit external payload, not a Python module.
        library=targets.MONITOR_SQLITE_CANDIDATE
        self.assertEqual(targets.THREE_PLATFORM_NEW,
                         {'source/'+name for name in runtime_new}|{library})
        self.assertNotIn(library.removeprefix('source/'),native)
        self.assertEqual(targets.THREE_PLATFORM_EXTRA[library],
                         '/opt/fc-ops-readonly-monitor/runtime/sqlite-3.53.4/lib/libsqlite3.so.0')
        stage={'source/'+name for name in native}|set(targets.THREE_PLATFORM_EXTRA)
        self.assertEqual(len(stage),112)
        self.assertEqual(len(targets.THREE_PLATFORM_NAMES),56)
        self.assertTrue(set(targets.THREE_PLATFORM_NAMES)<=stage)

    def test_curve_modules_require_explicit_versioned_target_scope(self):
        spec = importlib.util.spec_from_file_location('curve_candidate_target_map', SOURCE.parent / 'deploy/target_map.py')
        targets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(targets)
        current = targets.three_platform_targets(SOURCE)
        candidate = targets.curve_v6_targets(SOURCE)
        modules = {'competitor_offers.py', 'cost_inputs_v6.py', 'cost_model.py', 'price_curve.py',
                   'pricing_proof_v6.py', 'planning_baskets_v6.py', 'curve_strategy_v6.py'}
        added = {prefix + 'fc_pricing_v3/' + name for prefix in ('', 'hermes-copy/') for name in modules}
        self.assertEqual(set(targets.CURVE_V6_MODULES), modules)
        self.assertEqual(set(candidate) - set(current), added | {
            'collect_lootbar.sh', 'lootbar-collector/lootbar_server_collector.py',
            'lootbar-collector/background.js', 'collect_competitor.sh',
            'collector/collect_competitor_browser.py',
        })
        self.assertEqual(targets.CURVE_V6_TARGET_COUNT, 50)
        self.assertEqual(len(candidate), targets.CURVE_V6_TARGET_COUNT)
        self.assertEqual({key: path for key, path in candidate.items() if key in current},
                         {key: current[key] for key in candidate.keys() & current.keys()})
        self.assertEqual(len(set(candidate.values())), len(candidate))

    def test_existing_rpg_empty_and_https_configs_keep_the_original_shared_adapter(self):
        # Production /opt/d4follow/_p2pah_srv/admin_cache_local.py uses these two configs.
        path = Path(__file__).parent / 'fixtures/legacy_shared_admin.py'
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(raw).hexdigest(), 'a676388f0011b5f0ca116b0bfb2a1d428c8782e5538f8402e8734a5405beaa42')
        namespace = {}
        exec(compile(raw, str(path), 'exec'), namespace)
        for config in [{}, {'P2PAH_API_BASE': 'https://admin-api.p2pah.cn'}]:
            self.assertEqual(namespace['SessionManager'](config).config, config)

    def health(self, admin_payload):
        tree = ast.parse((SOURCE / 'fc27_cloud_api.py').read_text(encoding='utf8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'health')
        calls = []
        def open_url(request, **kwargs):
            url = request.full_url if isinstance(request, urllib.request.Request) else request
            calls.append(url)
            if url.endswith('/admin/index/index'):
                return response(admin_payload)
            if url.endswith('/json/version'):
                return response({'Browser': 'Chrome'})
            if url.endswith('/json'):
                return response([])
            raise OSError('Order session unavailable')
        with tempfile.TemporaryDirectory() as directory:
            namespace = {'ROOT': Path(directory), 'writer_status': lambda: 'ok',
                         'certificate_health': lambda: 'ok', 'datetime': datetime, 'timezone': timezone,
                         'os': os, 'json': json, 'shutil': shutil, 'valid_id': lambda value: True,
                         'urllib': SimpleNamespace(request=SimpleNamespace(
                             Request=urllib.request.Request, urlopen=open_url), error=urllib.error)}
            exec(compile(ast.Module(body=[function], type_ignores=[]), 'health', 'exec'), namespace)
            return namespace['health'](), calls

    def test_health_checks_dc_identity_once_and_keeps_order_separate(self):
        result, calls = self.health({'code': 1, 'data': {'adminInfo': {'username': 'wulvapi'}}})
        self.assertEqual(result['admin_dc'], 'reachable')
        self.assertEqual(result['admin_identity'], 'ok')
        self.assertEqual(result['p2pah_session'], 'ok')
        self.assertEqual(result['order_session'], 'missing')
        self.assertEqual(sum('/admin/index/index' in url for url in calls), 1)
        self.assertFalse(any('8767' in url for url in calls))

    def test_health_does_not_confuse_reachable_with_permission(self):
        result, _ = self.health({'code': 401, 'msg': 'No permission'})
        self.assertEqual(result['admin_dc'], 'reachable')
        self.assertEqual(result['admin_identity'], 'missing')
        self.assertEqual(result['p2pah_session'], 'missing')


@unittest.skipUnless(os.name == 'posix' and shutil.which('flock') and shutil.which('timeout'), 'Linux flock contract')
class PlayerWriterLockShellTests(unittest.TestCase):
    def fixture(self, folder, recovery=False):
        root = Path(folder) / 'state-root'
        for name in ('requests', 'executions', 'config', 'state', 'player-sync', 'all-coin-sync'):
            (root / name).mkdir(parents=True)
        job = '00000000-0000-4000-8000-000000000091'
        coin = '00000000-0000-4000-8000-000000000092'
        request = root / 'requests' / (job + '.json')
        request.write_text(json.dumps(dict(job_id=job, coin_execution_id=coin, recovery_preflight=recovery)))
        for path in (root / 'executions' / (coin + '.json'), root / 'all-coin-sync' / (coin + '.json'), root / 'config/player-sync.json'):
            path.write_text('{}')
        shell = Path(folder) / 'sync_players.sh'
        # Execute the complete original shell; only production paths and docker are isolated.
        shell.write_text((SOURCE / 'sync_players.sh').read_text().replace('/var/lib/fc27-cloud', str(root)).replace('/opt/fc27-cloud-browser', str(Path(folder) / 'app')))
        shell.chmod(0o700)
        commands = Path(folder) / 'bin'; commands.mkdir()
        (commands / 'python3').symlink_to(sys.executable)
        docker = commands / 'docker'
        docker.write_text('#!/bin/sh\nprintf "%s\\n" dispatch >> "$PLAYER_LOCK_TEST_MARKER"\nprintf "%s\\n" "{\\"status\\":\\"confirmed\\"}"\n')
        docker.chmod(0o700)
        marker = Path(folder) / 'dispatches'
        waiting = Path(folder) / 'waiting'
        flock = commands / 'flock'
        flock.write_text('#!/bin/sh\n: > "$PLAYER_LOCK_TEST_WAITING"\nexec ' + shutil.which('flock') + ' "$@"\n')
        flock.chmod(0o700)
        env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'], PLAYER_LOCK_TEST_MARKER=str(marker), PLAYER_LOCK_TEST_WAITING=str(waiting))
        return root, shell, request, marker, env

    def waiting(self, process, env):
        import time
        deadline = time.monotonic() + 5
        while not Path(env['PLAYER_LOCK_TEST_WAITING']).exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(Path(env['PLAYER_LOCK_TEST_WAITING']).exists(), 'original shell did not reach real flock')
        self.assertIsNone(process.poll())

    def test_wait_budget_fits_normal_and_readonly_probe_deadlines(self):
        source = (SOURCE / 'sync_players.sh').read_text()
        worker = ast.parse((SOURCE / 'fc27_cloud_worker.py').read_text())
        timeouts = {n.args[-1].value for n in ast.walk(worker) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'run_writer_request' and len(n.args) == 4 and isinstance(n.args[1], ast.Constant) and n.args[1].value == 'sync_players.sh'}
        self.assertEqual(timeouts, {180, 3700})
        self.assertIn('limit=3600', source); self.assertIn('limit=150', source)
        self.assertLess(20 + 3600, 3700); self.assertLess(20 + 150, 180)
        self.assertLess(source.index('flock -w 20 9'), source.index('timeout "$limit"s docker run'))

    def test_original_shell_waits_then_dispatches_exactly_once_for_both_paths(self):
        import fcntl, subprocess, time
        for recovery in (False, True):
            with self.subTest(recovery=recovery), tempfile.TemporaryDirectory() as folder:
                root, shell, request, marker, env = self.fixture(folder, recovery)
                with (root / 'state/price-writer.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    process = subprocess.Popen([str(shell), str(request)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        self.waiting(process, env); self.assertFalse(marker.exists())
                    finally:
                        fcntl.flock(lock, fcntl.LOCK_UN)
                    output, error = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, error)
                self.assertEqual(marker.read_text().splitlines(), ['dispatch'])
                self.assertEqual(json.loads(output)['status'], 'confirmed')

    def test_original_shell_wait_timeout_is_busy_with_zero_docker_dispatch(self):
        import fcntl, subprocess, time
        with tempfile.TemporaryDirectory() as folder:
            root, shell, request, marker, env = self.fixture(folder)
            with (root / 'state/price-writer.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                started = time.monotonic()
                process = subprocess.Popen([str(shell), str(request)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    output, error = process.communicate(timeout=25)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    if process.poll() is None:process.kill(); process.communicate(timeout=5)
            self.assertEqual(process.returncode, 75, error)
            self.assertEqual(json.loads(output), {'status': 'busy'})
            self.assertFalse(marker.exists()); self.assertGreaterEqual(time.monotonic() - started, 19)
            self.assertLess(time.monotonic() - started, 25)

    def test_killed_waiter_never_dispatches_and_inherited_lock_is_released(self):
        import fcntl, subprocess, time
        with tempfile.TemporaryDirectory() as folder:
            root, shell, request, marker, env = self.fixture(folder)
            with (root / 'state/price-writer.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                process = subprocess.Popen([str(shell), str(request)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.waiting(process, env); self.assertFalse(marker.exists())
                    process.terminate()
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0); self.assertFalse(marker.exists())
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)


if __name__ == '__main__':
    unittest.main()

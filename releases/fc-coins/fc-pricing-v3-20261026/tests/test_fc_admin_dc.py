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
                self.assertIn('flock -n 9', text) if name != 'clear_cache_after_write.sh' else None
                base = admin.API_BASES[0] if '--network host' in text else admin.API_BASES[2]
                self.assertIn('FS_ADMIN_API_BASE=' + base, text)

    def test_publisher_requires_exact_98_targets(self):
        spec = importlib.util.spec_from_file_location('fc_admin_target_map', SOURCE.parent / 'deploy/target_map.py')
        targets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(targets)
        mapping = targets.targets(SOURCE)
        self.assertEqual(targets.TARGET_COUNT, 98)
        self.assertEqual(len(mapping), targets.TARGET_COUNT)
        self.assertEqual(mapping['fc_shared_admin.py'], '/opt/fc27-cloud-browser/fc_shared_admin.py')
        self.assertNotIn('/opt/fs-order-session/fc_shared_admin.py', mapping.values())
        self.assertEqual(mapping['sync_players.sh'], '/opt/fc27-cloud-browser/sync_players.sh')
        for name in ['build_stage.py', 'prepare_manifest.py']:
            text = (SOURCE.parent / 'deploy' / name).read_text(encoding='utf8')
            self.assertIn('!= TARGET_COUNT', text)

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


if __name__ == '__main__':
    unittest.main()

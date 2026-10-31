"""Shared authentication must not widen Players writes or expose credentials."""
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from player_web.main import App
from player_web.repository import Repository
from player_web.shared_session import shared_client, session_token
from tests_cloud.test_feature_parity import configuration
from 球员维护工具.admin_client import AdminAuthError


def settings(root):
    return replace(configuration(root), admin_api_base_url='https://admin-api.p2pah.cn',
                   root_path='/tools/fc27-players')


class SharedSessionTests(unittest.TestCase):
    def test_hmac_proxy_requests_do_not_restore_browser_login(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            seen = []
            def opener(request, *, timeout):
                self.assertEqual(urlsplit(request.full_url).netloc, '127.0.0.1:8912')
                seen.append(dict(request.header_items()))
                return io.BytesIO(b'{"code":1,"data":{}}')
            with patch('urllib.request.OpenerDirector.open', side_effect=opener), \
                 patch('player_web.shared_session.session_token', side_effect=AssertionError('retired session used')):
                client = shared_client(config)
                client.verify_identity()
                self.assertEqual([row['Batoken'] for row in seen], ['dc-hmac-proxy', 'dc-hmac-proxy'])
                self.assertNotIn('Origin', seen[0])
                self.assertEqual(seen[0]['Server'], 'true')
                client.clear_auth()
                with self.assertRaises(AdminAuthError):
                    client.verify_identity()

    def test_retired_token_entry_never_opens_network(self):
        with patch('socket.socket', side_effect=AssertionError('retired socket used')):
            with self.assertRaisesRegex(AdminAuthError, '^FS_SHARED_SESSION_RETIRED$'):
                session_token()

    def test_browser_guards_logout_and_existing_write_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(settings(Path(temporary)), shared_backend_session=True,
                             manual_new_cards_enabled=True, manual_model_images_enabled=True,
                             manual_existing_recommend_enabled=True)
            Repository(config.data_root / 'db/control.sqlite3').initialize()
            app = App(config)
            self.addCleanup(app._pool.shutdown, wait=True)
            def call(path, headers, body=None):
                raw = json.dumps(body or {}).encode()
                env = {'PATH_INFO':path, 'REQUEST_METHOD':'GET' if body is None else 'POST',
                       'REMOTE_ADDR':'127.0.0.1', 'wsgi.input':io.BytesIO(raw),
                       'CONTENT_LENGTH':str(len(raw)), **headers}
                result = {}
                def start(status, headers): result.update(status=status, headers=dict(headers))
                result['body'] = json.loads(b''.join(app(env, start)))
                return result
            gate = {'HTTP_X_FC27_USER':'operator', 'HTTP_X_FC27_ROLE':'admin'}
            boot = call('/api/bootstrap', gate)
            headers = {**gate, 'HTTP_COOKIE':boot['headers']['Set-Cookie'].split(';')[0],
                       'HTTP_ORIGIN':config.public_origin, 'HTTP_X_CSRF_TOKEN':boot['body']['csrf']}
            self.assertTrue(boot['body']['shared_backend_session'])
            with patch('player_web.main.shared_client') as factory:
                for change, error in [({'HTTP_X_FC27_ROLE':'readonly'}, 'ROLE_REQUIRED'),
                                      ({'HTTP_X_CSRF_TOKEN':'wrong'}, 'CSRF_INVALID'),
                                      ({'HTTP_ORIGIN':'https://wrong.invalid'}, 'ORIGIN_MISMATCH')]:
                    self.assertEqual(call('/api/auth/shared', {**headers, **change}, {})['body']['error'], error)
                factory.assert_not_called()
                connected = call('/api/auth/shared', headers, {})
                self.assertEqual(set(connected['body']), {'authenticated', 'csrf'})
                self.assertNotIn('token', json.dumps(connected['body']))
                headers['HTTP_X_CSRF_TOKEN'] = connected['body']['csrf']
                self.assertTrue(call('/api/status', headers)['body']['backend_authenticated'])
                other = call('/api/bootstrap', gate)
                self.assertFalse(other['body']['backend_authenticated'])
                for path in ('/api/auth/challenge', '/api/auth/login'):
                    self.assertEqual(call(path, headers, {})['body']['error'], 'USE_FS_SHARED_SESSION')
                call('/api/auth/logout', headers, {})
                factory.return_value.clear_auth.assert_called_once()
                self.assertFalse(call('/api/status', headers)['body']['backend_authenticated'])
                factory.side_effect = AdminAuthError('never return upstream secrets')
                self.assertEqual(call('/api/auth/shared', headers, {})['body'], {'error':'BACKEND_AUTH_UNAVAILABLE'})
            self.assertFalse(config.write_enabled)
            self.assertTrue(config.new_card_write_enabled and config.model_image_write_enabled)
            self.assertTrue(config.existing_action_write_enabled('recommend_enable'))
            self.assertFalse(any(config.existing_action_write_enabled(action) for action in
                                 ('recommend_disable', 'add_tags', 'remove_tags', 'unlist')))


if __name__ == '__main__':
    unittest.main()

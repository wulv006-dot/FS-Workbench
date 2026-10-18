"""Shared authentication must not widen Players writes or expose credentials."""
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from player_web.main import App
from player_web.repository import Repository
from player_web.shared_session import shared_client, session_token
from tests_cloud.test_feature_parity import configuration
from 球员维护工具.admin_client import AdminAuthError


def settings(root):
    return replace(configuration(root), admin_api_base_url='https://admin-api.p2pah.cn',
                   root_path='/tools/fc27-players')


class SharedSessionTests(unittest.TestCase):
    def test_fresh_token_per_request_headers_and_no_external_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            seen = []
            def opener(request, *, timeout):
                seen.append(dict(request.header_items()))
                return io.BytesIO(b'{"code":1,"data":{}}')
            with patch('urllib.request.OpenerDirector.open', side_effect=opener), \
                 patch('player_web.shared_session.session_token', side_effect=['first', 'rotated']):
                client = shared_client(config)
                client.verify_identity()
                self.assertEqual([row['Batoken'] for row in seen], ['first', 'rotated'])
                self.assertEqual(seen[0]['Origin'], 'https://admin.p2pah.cn')
                self.assertEqual(seen[0]['Server'], '1')
                with self.assertRaises(AdminAuthError):
                    client._opener(Request('https://outside.invalid/admin/index/index'), timeout=1)
                client.clear_auth()
                with self.assertRaises(AdminAuthError):
                    client.verify_identity()

    def test_unavailable_or_unsafe_token_is_redacted(self):
        for raw in (b'{"error":"shared_session_unavailable"}\n', b'{"token":"secret\\r\\n"}', b'x' * 17000):
            class Connection:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def settimeout(self, value): pass
                def connect(self, value): pass
                def sendall(self, value): pass
                def makefile(self, value): return io.BytesIO(raw)
            with patch('player_web.shared_session.socket.socket', return_value=Connection()):
                with self.assertRaisesRegex(AdminAuthError, '^FS_SHARED_SESSION_UNAVAILABLE$'):
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

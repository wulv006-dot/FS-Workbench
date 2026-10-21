import ast
import io
import unittest
from unittest.mock import patch as mock_patch
import prepare_patch
import shared_admin


class Response(io.BytesIO):
    status = 200


class Tests(unittest.TestCase):
    def read(self, body, status=200):
        response = Response(body)
        response.status = status
        with mock_patch.object(shared_admin, 'build_opener') as build:
            build.return_value.open.return_value = response
            result = shared_admin.admin_token_from_service()
            self.assertEqual(build.return_value.open.call_count, 1)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8767/session/admin-token')
            self.assertEqual(request.get_method(), 'GET')
        return result

    def test_success(self):
        self.assertEqual(self.read(b'{"token":"synthetic-token"}'), ('synthetic-token', None))

    def test_invalid_or_not_ready(self):
        for body, status in [(b'{"token":"old"}', 503), (b'[]', 200),
                             (b'not-json', 200), (b'{"token":42}', 200),
                             (b'{"token":"a\\nb"}', 200), (b'{}', 200),
                             (b'x' * 16385, 200)]:
            with self.subTest(status=status, body=body[:35]):
                self.assertEqual(self.read(body, status), (None, 'shared_admin_unavailable'))

    def test_connection_failure_no_retry(self):
        with mock_patch.object(shared_admin, 'build_opener') as build:
            build.return_value.open.side_effect = OSError('synthetic-secret')
            self.assertEqual(shared_admin.admin_token_from_service(), (None, 'shared_admin_unavailable'))
            self.assertEqual(build.return_value.open.call_count, 1)

    def test_no_redirect(self):
        self.assertIsNone(shared_admin.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_patch_preserves_order_and_fails_before_order_when_unavailable(self):
        source = '''import os
USER = os.environ.get('P2PAH_USER', 'synthetic-user')
PASSWORD = os.environ.get('P2PAH_PASSWORD', 'synthetic-password')
def admin_token_from_service(timeout=8):
    return 'old', None
def admin_login(s):
    return 'bad'
def order_login(s):
    s.order_calls += 1
class Session:
    def __init__(self):
        self.closed = False
        self.order_calls = 0
    def close(self):
        self.closed = True
    def save(self):
        _save_state({'admin_token': self.token, 'admin_at': 0, 'order_cookies': {}, 'order_at': 0})
def bootstrap(reuse=True):
    s = Session()
    st = _load_state() if reuse else {}
    s.token = admin_login(s)
    ck = st.get('order_cookies') or {}
    order_login(s)
    s.save()
    return s
'''
        result = prepare_patch.patch(source)
        self.assertNotIn('synthetic-password', result)
        self.assertNotIn('synthetic-user', result)
        namespace = {'_load_state': lambda: {'admin_token': 'stale'}, '_save_state': lambda v: saved.append(v)}
        saved = []
        exec(compile(result, 'synthetic', 'exec'), namespace)
        namespace['admin_token_from_service'] = lambda: (None, 'unavailable')
        with self.assertRaisesRegex(RuntimeError, '^shared_admin_unavailable$'):
            namespace['bootstrap']()
        self.assertEqual(saved, [])
        namespace['USER'], namespace['PASSWORD'] = 'synthetic', 'synthetic'
        namespace['admin_token_from_service'] = lambda: ('new', None)
        session = namespace['bootstrap']()
        self.assertEqual(session.token, 'new')
        self.assertEqual(session.order_calls, 1)
        self.assertEqual(saved, [{'order_cookies': {}, 'order_at': 0}])
        with self.assertRaisesRegex(RuntimeError, 'sales_admin_login_disabled'):
            namespace['admin_login'](session)
        ast.parse(result, feature_version=(3, 9))


if __name__ == '__main__':
    unittest.main()

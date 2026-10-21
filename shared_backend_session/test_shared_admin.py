import ast
import io
import unittest
from unittest.mock import patch as mock_patch
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
        for body, status in [(b'{"token":"old"}', 503), (b'[]', 200), (b'not-json', 200), (b'{"token":42}', 200), (b'{"token":"a\\nb"}', 200), (b'{}', 200), (b'x' * 16385, 200)]:
            with self.subTest(status=status, body=body[:35]):
                self.assertEqual(self.read(body, status), (None, 'shared_admin_unavailable'))

    def test_connection_failure_no_retry(self):
        with mock_patch.object(shared_admin, 'build_opener') as build:
            build.return_value.open.side_effect = OSError('synthetic-secret')
            self.assertEqual(shared_admin.admin_token_from_service(), (None, 'shared_admin_unavailable'))
            self.assertEqual(build.return_value.open.call_count, 1)

    def test_no_redirect(self):
        self.assertIsNone(shared_admin.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
if __name__ == '__main__':
    unittest.main()

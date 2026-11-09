from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from fs_mcp_connector.portal import Portal, PortalError


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        cls.status = 200
        cls.subject = 'alice'
        cls.duplicate = False
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append((self.path, dict(self.headers)))
                self.send_response(cls.status)
                if cls.subject:
                    self.send_header('X-Auth-User', cls.subject)
                    if cls.duplicate:
                        self.send_header('X-Auth-User', 'admin')
                self.end_headers()
            def log_message(self, *_):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.__class__.status, self.__class__.subject = 200, 'alice'
        self.__class__.duplicate = False
        self.portal = Portal('http://127.0.0.1:%s' % self.server.server_port)

    def test_uses_only_server_portal_identity_and_forwards_real_resource(self):
        principal = self.portal.verify('fs_session=opaque', '/api/users?limit=20', 'POST')
        self.assertEqual(principal.subject, 'alice')
        path, headers = self.requests[-1]
        self.assertEqual(path, '/verify?group=dashboard')
        self.assertEqual(headers['Cookie'], 'fs_session=opaque')
        self.assertEqual(headers['X-Original-URI'], '/api/users?limit=20')
        self.assertEqual(headers['X-Original-Method'], 'POST')
        self.assertNotIn('opaque', repr(principal))

    def test_status_and_missing_identity_fail_closed_without_leaking_cookie(self):
        for status, subject in [(401, 'alice'), (403, 'alice'), (302, 'alice'), (500, 'alice'), (200, '')]:
            self.__class__.status, self.__class__.subject = status, subject
            with self.subTest(status=status, subject=subject), self.assertRaises(PortalError) as caught:
                self.portal.verify('secret-cookie', '/')
            self.assertNotIn('secret-cookie', str(caught.exception))

    def test_rejects_non_loopback_and_header_injection(self):
        for url in ['https://fs.example', 'http://127.0.0.1.evil.example',
                    'http://@127.0.0.1', 'http://127.0.0.1:0', 'http://127.0.0.1#',
                    'http://127.0.0.1?', 'http://127.0.0.1\n',
                    'http://user@127.0.0.1', 'http://127.0.0.1/verify', 'http://127.0.0.1?x=1']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                Portal(url)
        for cookie, resource, method in [('', '/', 'GET'), ('x\r\nX-Auth-User:admin', '/', 'GET'),
                                         ('cookie', '//evil.example', 'GET'),
                                         ('cookie', '/\r\nX:test', 'GET'), ('cookie', '/', 'DELETE')]:
            with self.subTest(cookie=cookie, resource=resource), self.assertRaises(PortalError):
                self.portal.verify(cookie, resource, method)

    def test_duplicate_identity_header_is_rejected(self):
        self.__class__.duplicate = True
        with self.assertRaises(PortalError):
            self.portal.verify('cookie=valid', '/dashboard/')


if __name__ == '__main__':
    unittest.main()

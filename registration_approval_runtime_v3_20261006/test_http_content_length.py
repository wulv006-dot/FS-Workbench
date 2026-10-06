"""Real stdlib HTTP header boundary tests for the legacy logout refusal."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading
import time
import traceback
import unittest

from portal_bridge import Bridge


class Reader:
    def __init__(self, wrapped, handler):
        self.wrapped, self.handler = wrapped, handler

    def read1(self, size=-1):
        self.handler.body_reads += 1
        return self.wrapped.read1(size)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.body_reads = 0
        self.rfile = Reader(self.rfile, self)

    def log_message(self, *args):
        pass

    def do_POST(self):
        Bridge(None, None, None).legacy_logout(self)

    def _send(self, code, body=b'', ctype='text/plain; charset=utf-8', headers=None):
        payload = body.encode('utf-8') if isinstance(body, str) else body
        self.server.observations.append({'status': code, 'body_reads': self.body_reads})
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        for name, value in headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


class Server(ThreadingHTTPServer):
    def __init__(self, address):
        self.observations, self.errors = [], []
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        # Preserve handler failures for assertions; no candidate exception catch.
        self.errors.append(traceback.format_exc())
        super().handle_error(request, client_address)


class ContentLengthTests(unittest.TestCase):
    def setUp(self):
        self.int_limit = sys.get_int_max_str_digits() if hasattr(sys, 'get_int_max_str_digits') else None
        self.server = Server(('127.0.0.1', 0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual([], self.server.errors)
        current = sys.get_int_max_str_digits() if hasattr(sys, 'get_int_max_str_digits') else None
        self.assertEqual(self.int_limit, current)

    def request(self, values, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        start = time.monotonic()
        try:
            connection.putrequest('POST', '/logout/?next=/dashboard/')
            for value in values:
                connection.putheader('Content-Length', value)
            connection.endheaders(body)
            response = connection.getresponse()
            response.read()
            self.assertTrue(response.will_close)
            self.assertEqual('close', response.getheader('Connection'))
            self.assertIsNone(response.getheader('Set-Cookie'))
            return response.status, self.server.observations[-1]['body_reads'], time.monotonic() - start
        finally:
            connection.close()

    def test_long_leading_zeroes_reach_real_header_limit(self):
        allowed = http.client._MAXLINE - len(b'Content-Length: \r\n')
        for value, body in (('0' * 5000, None), ('0' * 5000 + '2', b'{}'),
                            ('0' * allowed, None), ('0' * (allowed - 1) + '2', b'{}')):
            with self.subTest(length_chars=len(value), body_bytes=len(body or b'')):
                self.assertEqual(405, self.request([value], body)[0])

    def test_small_legal_values_and_4096_boundary(self):
        for value, body in (('0', None), ('0000', None), ('2', b'{}'), ('0002', b'{}'),
                            ('4096', b'x' * 4096), ('0004096', b'x' * 4096)):
            with self.subTest(value=value):
                self.assertEqual(405, self.request([value], body)[0])

    def test_large_values_reject_without_body_read(self):
        allowed = http.client._MAXLINE - len(b'Content-Length: \r\n')
        for value in ('4097', '10000', '9' * 5000, '0' * 5000 + '4097', '9' * allowed):
            with self.subTest(length_chars=len(value)):
                code, reads, _ = self.request([value])
                self.assertEqual(400, code)
                self.assertEqual(0, reads)

    def test_duplicate_negative_and_malformed_lengths(self):
        for values in (['2', '2'], ['0', '2'], ['-1'], ['+2'], ['2.0'], ['2,2'],
                       [''], ['abc'], ['²']):
            with self.subTest(values=values):
                code, reads, _ = self.request(values)
                self.assertEqual(400, code)
                self.assertEqual(0, reads)


if __name__ == '__main__':
    unittest.main(verbosity=2)

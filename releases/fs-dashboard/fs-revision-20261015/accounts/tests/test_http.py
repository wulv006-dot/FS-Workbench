"""Real loopback HTTP requests against the isolated production dispatcher."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
import test_accounts as fixtures
import runtime
OLD, NEW = fixtures.OLD, fixtures.NEW


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AccountsTests(methodName='runTest')
        self.fixture.setUp()
        app = self.fixture.app
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_request(self):
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 4096 or self.headers.get('Transfer-Encoding'):
                    self.send_error(400); return
                cookies = dict(part.strip().split('=', 1) for part in self.headers.get('Cookie', '').split(';') if '=' in part)
                code, result, headers = app.dispatch(self.command, self.path, headers=dict(self.headers), cookies=cookies, body=self.rfile.read(length))
                data = json.dumps(result).encode()
                self.send_response(code)
                for key, values in headers.items():
                    for value in values if isinstance(values, list) else [values]:
                        self.send_header(key, value)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
            do_GET = handle_request
            do_POST = handle_request
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.cookie = 'SYNTHETIC_AUTH=' + self.fixture.token
        self.conn.request('GET', '/api/bootstrap', headers={'Cookie': self.cookie})
        response = self.conn.getresponse(); bootstrap = json.loads(response.read())
        self.cookie += '; ' + response.getheader('Set-Cookie').split(';', 1)[0]
        self.csrf = bootstrap['csrf']

    def tearDown(self):
        self.conn.close(); self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.fixture.tearDown()

    def request(self, method, path, body=None, **changes):
        headers = {'Cookie': self.cookie, 'Origin': 'https://synthetic.invalid', 'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf}
        headers.update(changes)
        self.conn.request(method, path, body, headers)
        response = self.conn.getresponse()
        return response.status, json.loads(response.read())

    def test_real_http_inventory_password_write_and_readback(self):
        self.assertEqual(7, len(self.request('GET', '/api/accounts')[1]['items']))
        form = self.fixture.form('native:mmoexp', new_password=NEW, confirm_password=NEW)
        code, result = self.request('POST', '/api/account-password', json.dumps(form))
        self.assertEqual(200, code); self.assertTrue(result['sessions_revoked'])
        self.assertTrue(self.fixture.store.accounts.authenticate('mmoexp', NEW))
        self.assertFalse(self.fixture.store.accounts.authenticate('mmoexp', OLD))
        self.assertEqual(1, len(self.request('GET', '/api/account-audit')[1]['items']))

    def test_real_http_csrf_origin_and_duplicate_json_rejected(self):
        form = json.dumps(self.fixture.form('native:mmoexp', new_password=NEW, confirm_password=NEW))
        self.assertEqual(403, self.request('POST', '/api/account-password', form, **{'X-CSRF-Token': 'wrong'})[0])
        self.assertEqual(403, self.request('POST', '/api/account-password', form, Origin='https://other.invalid')[0])
        duplicate = form[:-1] + ',"reason":"duplicate"}'
        self.assertEqual(400, self.request('POST', '/api/account-password', duplicate)[0])
        self.assertEqual([], self.fixture.store.accounts.audit(0))

    def test_real_http_stale_cas_is_conflict_and_one_audit_event(self):
        form = json.dumps(self.fixture.form('native:mmoexp', new_password=NEW, confirm_password=NEW))
        self.assertEqual(200, self.request('POST', '/api/account-password', form)[0])
        self.assertEqual(409, self.request('POST', '/api/account-password', form)[0])
        self.assertEqual(1, len(self.request('GET', '/api/account-audit')[1]['items']))


if __name__ == '__main__':
    unittest.main()

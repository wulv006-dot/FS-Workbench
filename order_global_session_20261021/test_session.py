import unittest
from unittest.mock import patch
import client
from service import Session, IDENTITY_CHECK


class SessionTests(unittest.TestCase):
    def test_probe_cached_and_failure_drops_cookies(self):
        calls = []
        def probe():
            calls.append(1)
            if len(calls) > 1:
                raise ValueError('sensitive error text')
            return {'ready': True, 'cookies': [{'name': 'test', 'value': 'fake'}]}
        session = Session(probe)
        self.assertTrue(session.get()['ready'])
        self.assertTrue(session.get()['ready'])
        self.assertEqual(len(calls), 1)
        session.checked = 0
        self.assertEqual(session.get(), {'ready': False, 'error': 'order_probe_unavailable'})

    def test_protected_home_rejects_anonymous_and_wrong_origin(self):
        scope = {}
        exec(IDENTITY_CHECK, scope)
        check = scope['identity_ok']
        url = 'https://order.p2pah.cn/admin/index/index.html'
        body = '<a href="/admin/public/logout.html">logout</a>'
        self.assertTrue(check(200, url, body))
        self.assertFalse(check(200, 'https://order.p2pah.cn/login.html', body))
        self.assertFalse(check(200, 'https://example.test/admin/index/index.html', body))
        self.assertFalse(check(200, url, '<input type="password">'))
        self.assertFalse(check(200, url, body + '<input type=password>'))

    def test_health_does_not_wait_on_probe_or_disclose_cookies(self):
        session = Session(lambda: {'ready': True, 'cookies': [{'value': 'synthetic-only'}]})
        session.get()
        session.probing = True
        session.lock.acquire()
        try:
            health = session.health()
            self.assertTrue(health['ready'])
            self.assertTrue(health['checking'])
            self.assertNotIn('cookies', health)
            self.assertNotIn('synthetic-only', str(health))
        finally:
            session.lock.release()
        session.checked -= 46
        self.assertFalse(session.health()['ready'])

    def test_identity_failure_immediately_drops_ready(self):
        session = Session(lambda: {'ready': False, 'cookies': [], 'error': 'order_identity_unverified'})
        self.assertFalse(session.get()['ready'])
        self.assertFalse(session.health()['ready'])

    def test_missing_service_fails_closed(self):
        with patch('client.os.path.exists', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '^global_order_unavailable$'):
                client.cookies()

    def test_jar_replaces_old_identity(self):
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        with patch('client.cookies', return_value=[{'name': 'test', 'value': 'synthetic',
                                                  'domain': 'order.p2pah.cn', 'path': '/', 'secure': True}]):
            self.assertEqual(client.fill_jar(jar), 1)
            self.assertEqual(next(iter(jar)).domain, 'order.p2pah.cn')


if __name__ == '__main__':
    unittest.main()

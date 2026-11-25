import io
import json
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import Cookie
from threading import Event
import unittest
from unittest.mock import Mock, patch

import client
import service
from service import Session, identity_ok



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
        self.assertEqual(session.get(), {'ready': False, 'cookies': [], 'error': 'order_probe_unavailable'})

    def test_protected_home_rejects_anonymous_and_wrong_origin(self):
        check = identity_ok
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



HOME = '<a href="/admin/public/logout.html">logout</a>'
LOGIN = '<input type="password">'
PNG = b'\x89PNG\r\n\x1a\nsynthetic'


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.session = service.Session()
        self.posts = []
        self.probes = []
        self.replies = []
        self.probe_headers = {}
        self.outcome = (200, LOGIN)
        self.session.opener.open = Mock(side_effect=self.respond)
        self.entered = Event()
        self.release = Event()
        self.release.set()
        for target, value in (
            ('read_private_config', ('synthetic', 'synthetic')),
            ('recognize', '1234'),
        ):
            mock = patch.object(service, target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def cookie(self, name):
        self.session.jar.set_cookie(Cookie(
            0, name, 'synthetic', None, False, 'order.p2pah.cn', False,
            False, '/', True, True, None, True, None, None, {}, False))

    def respond(self, req, timeout):
        path = req.selector.split('?')[0]
        if path == service.PROBE_PATH:
            self.probes.append(path)
            self.entered.set()
            self.release.wait(3)
            if isinstance(self.outcome, Exception):
                raise self.outcome
            status, body = self.outcome
            payload = body.encode()
        elif path == '/new_captcha.html':
            self.cookie('PHPSESSID')
            status, payload = 200, PNG
        else:
            self.assertEqual(path, '/admin/public/dologin.html')
            self.posts.append(req.data)
            reply = self.replies.pop(0)
            if reply['code'] == 1:
                self.cookie('user')
                self.cookie('admin_username')
                self.outcome = (200, HOME)
            status, payload = 200, json.dumps(reply).encode()
        response = io.BytesIO(payload)
        response.status = status
        response.headers = self.probe_headers if path == service.PROBE_PATH else {}
        return response

    def test_restart_logs_in_after_positive_login_page_evidence(self):
        self.assertEqual(list(self.session.jar), [])
        self.replies = [{'code': 1}]
        result = self.session.get()
        self.assertTrue(result['ready'])
        self.assertEqual({row['name'] for row in result['cookies']},
                         {'PHPSESSID', 'user', 'admin_username'})
        self.assertEqual(len(self.probes), 2)
        self.assertEqual(len(self.posts), 1)

    def test_known_login_redirect_triggers_renewal(self):
        self.outcome = (302, '')
        self.probe_headers = {'Location': '/admin'}
        self.replies = [{'code': 1}]
        self.assertTrue(self.session.get()['ready'])

    def test_unexpected_redirect_never_logs_in(self):
        self.outcome = (302, '')
        self.probe_headers = {'Location': 'https://example.test/admin'}
        self.assertEqual(self.session.get()['error'], 'order_identity_unverified')
        self.assertEqual(self.posts, [])

    def test_valid_identity_requires_all_cookies(self):
        self.cookie('PHPSESSID')
        self.outcome = (200, HOME)
        self.assertEqual(self.session.get()['error'], 'order_session_cookies_missing')
        self.assertEqual(self.posts, [])

    def test_valid_then_expired(self):
        for name in ('PHPSESSID', 'user', 'admin_username'):
            self.cookie(name)
        self.outcome = (200, HOME)
        self.assertTrue(self.session.get()['ready'])
        self.assertEqual(self.posts, [])
        self.session.checked = 0
        self.outcome = (200, LOGIN)
        self.replies = [{'code': 1}]
        self.assertTrue(self.session.get()['ready'])
        self.assertEqual(len(self.posts), 1)

    def test_captcha_retry_and_password_rejection(self):
        self.replies = [{'code': 0, 'msg': '验证码错误'}, {'code': 0, 'msg': '密码错误'}]
        self.assertEqual(self.session.get()['error'], 'order_login_rejected')
        self.session.checked = 0
        self.assertEqual(self.session.get()['error'], 'order_login_rejected')
        self.assertEqual(len(self.posts), 2)

    def test_captcha_attempts_exhausted(self):
        self.replies = [{'code': 0, 'msg': '验证码错误'}] * 2
        with patch.object(service, 'ocr_attempts', return_value=2):
            self.assertEqual(self.session.get()['error'], 'order_captcha_attempts_exhausted')
        self.assertEqual(len(self.posts), 2)

    def test_probe_failure_never_logs_in(self):
        for outcome in (TimeoutError(), (503, LOGIN), (429, LOGIN), (200, 'unexpected')):
            with self.subTest(outcome=outcome):
                self.session.checked = 0
                self.outcome = outcome
                self.assertFalse(self.session.get()['ready'])
        self.assertEqual(len(self.posts), 0)

    def test_concurrent_consumers_share_one_renewal(self):
        self.replies = [{'code': 1}]
        self.release.clear()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.session.get) for _ in range(4)]
            self.assertTrue(self.entered.wait(2))
            self.release.set()
            self.assertTrue(all(future.result(3)['ready'] for future in futures))
        self.assertEqual(len(self.posts), 1)

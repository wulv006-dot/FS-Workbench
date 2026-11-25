import io
import json
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import Cookie
from http.client import IncompleteRead
from threading import Event
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

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

    def test_explicit_broker_budget_is_shared_by_connect_send_and_receive(self):
        from http.cookiejar import CookieJar
        from unittest.mock import MagicMock

        stream = MagicMock()
        clock = [10]
        stream.__enter__.return_value = stream

        def connect(path):
            clock[0] += 2

        def sendall(data):
            clock[0] += 3

        stream.connect.side_effect = connect
        stream.sendall.side_effect = sendall
        with patch('client.socket.AF_UNIX', 1, create=True), \
             patch('client.socket.socket', return_value=stream), \
             patch('client.os.path.exists', return_value=True), \
             patch('client.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, '^global_order_unavailable$'):
                client.fill_jar(CookieJar(), timeout=5)
        self.assertEqual([call.args[0] for call in stream.settimeout.call_args_list], [5, 3])
        stream.recv.assert_not_called()

    def test_jar_replaces_old_identity(self):
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        with patch('client.cookies', return_value=[{'name': 'test', 'value': 'synthetic',
                                                  'domain': 'order.p2pah.cn', 'path': '/', 'secure': True}]):
            self.assertEqual(client.fill_jar(jar), 1)
            self.assertEqual(next(iter(jar)).domain, 'order.p2pah.cn')



HOME = '<a href="/admin/public/logout.html">logout</a>'
LOGIN = '<form action="/admin/public/dologin.html"><input type="password"></form>'
PNG = b'\x89PNG\r\n\x1a\nsynthetic'


class HTTPTests(unittest.TestCase):
    real_recognize = staticmethod(service.recognize)

    def setUp(self):
        self.session = service.Session()
        self.posts = []
        self.probes = []
        self.replies = []
        self.probe_headers = {}
        self.response_stream = io.BytesIO
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
        response = self.response_stream(payload)
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

    def test_order_captcha_on_login_page_triggers_renewal(self):
        self.outcome = (200, '<input type="password"><img src="/new_captcha.html?width=150">')
        self.replies = [{'code': 1}]
        self.assertTrue(self.session.get()['ready'])
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

    def test_login_posts_are_bounded_across_cache_expirations(self):
        self.replies = [{'code': 0, 'msg': '验证码错误'}] * 12
        with patch.object(service.time, 'monotonic', return_value=100) as clock:
            with patch.object(service, 'ocr_attempts', return_value=2):
                self.assertEqual(self.session.get()['error'], 'order_captcha_attempts_exhausted')
                for instant in (121, 142, 163):
                    clock.return_value = instant
                    self.assertFalse(self.session.get()['ready'])
                self.assertEqual(len(self.posts), 2)
                self.assertEqual(len(self.probes), 4)
                clock.return_value = 184
                for name in ('PHPSESSID', 'user', 'admin_username'):
                    self.cookie(name)
                self.outcome = (200, HOME)
                self.assertTrue(self.session.get()['ready'])
                self.assertEqual(len(self.posts), 2)

    def test_transient_login_success_does_not_reset_post_budget(self):
        self.replies = [{'code': 1}] * 5
        with patch.object(service.time, 'monotonic', return_value=100) as clock:
            with patch.object(service, 'ocr_attempts', return_value=2):
                self.assertTrue(self.session.get()['ready'])
                clock.return_value = 121
                self.outcome = (200, LOGIN)
                self.assertTrue(self.session.get()['ready'])
                clock.return_value = 142
                self.outcome = (200, LOGIN)
                self.assertFalse(self.session.get()['ready'])
                self.assertEqual(len(self.posts), 2)
                clock.return_value = 163
                self.assertFalse(self.session.get()['ready'])
                self.assertEqual(len(self.posts), 2)
                clock.return_value = 421
                self.assertTrue(self.session.get()['ready'])
                self.assertEqual(len(self.posts), 3)

    def test_incomplete_login_receipt_is_reconciled_by_read_only_probe(self):
        class TruncatedReceipt(io.BytesIO):
            def read(self, *args):
                raise IncompleteRead(b'partial')

            read1 = read

        self.replies = [{'code': 1}]
        stream = self.response_stream
        def truncated_if_receipt(payload):
            if payload.startswith(b'{'):
                return TruncatedReceipt(payload)
            return stream(payload)

        self.response_stream = truncated_if_receipt
        self.assertEqual(self.session.get()['error'], 'order_login_outcome_unverified')
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(len(self.probes), 1)

        self.session.checked = 0
        self.assertTrue(self.session.get()['ready'])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(len(self.probes), 2)

    def test_expired_deadline_before_post_has_no_unknown_receipt(self):
        self.replies = [{'code': 1}]
        with patch.object(service.time, 'monotonic', return_value=100) as clock:
            def late_ocr(_image, _deadline):
                clock.return_value = 134
                return '1234'

            with patch.object(service, 'recognize', side_effect=late_ocr):
                self.assertEqual(self.session.get()['error'], 'order_login_deadline')
            self.assertEqual(self.posts, [])
            self.assertEqual(self.session.health()['login_attempts'], 0)

            clock.return_value = 435
            self.assertTrue(self.session.get()['ready'])
            self.assertEqual(len(self.posts), 1)

    def test_password_controls_without_order_login_evidence_never_post(self):
        password = '<input type="password" name="new_password">'
        for html in (f'<form action="/admin/profile/password.html">{password}</form>',
                     HOME + password):
            with self.subTest(html=html):
                self.session.checked = 0
                self.outcome = (200, html)
                self.assertEqual(self.session.get()['error'], 'order_identity_unverified')
                self.assertEqual(self.posts, [])

    def test_slow_probe_body_releases_waiters_and_never_posts(self):
        reading = Event()
        finish_chunk = Event()
        self.addCleanup(finish_chunk.set)

        class SlowBody(io.BytesIO):
            def read1(self, *args):
                reading.set()
                finish_chunk.wait(2)
                clock.return_value = 134
                return io.BytesIO.read(self, 1)

            read = read1

        self.response_stream = SlowBody
        with patch.object(service.time, 'monotonic', return_value=100) as clock:
            with patch.object(service, 'WAIT_TIMEOUT', 0.05):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    owner = pool.submit(self.session.get)
                    self.assertTrue(reading.wait(1))
                    waiter = pool.submit(self.session.get)
                    try:
                        self.assertEqual(waiter.result(0.5)['error'], 'order_probe_wait_timeout')
                        self.assertEqual(len(self.probes), 1)
                        self.assertEqual(self.posts, [])
                    finally:
                        finish_chunk.set()
                    self.assertEqual(owner.result(1)['error'], 'order_probe_transport_unavailable')
        self.assertEqual(self.posts, [])

    def test_socket_read_deadline_includes_headers_and_chunk_framing(self):
        stalled_responses = (
            b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n',
            b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\na',
        )
        for response in stalled_responses:
            with self.subTest(response=response):
                client_stream, server_stream = socket.socketpair()
                with client_stream, server_stream:
                    server_stream.sendall(response)

                    def connect(connection):
                        client_stream.settimeout(3)
                        connection.sock = client_stream

                    session = service.Session()
                    started = time.monotonic()
                    with (patch.object(service.HTTPSConnection, 'connect', connect),
                          patch.object(service, 'PROBE_TIMEOUT', 0.2)):
                        self.assertEqual(session.get()['error'], 'order_probe_transport_unavailable')
                    self.assertLess(time.monotonic() - started, 1.5)
                    self.assertEqual(session.health()['login_attempts'], 0)

    def test_stuck_ocr_is_bounded_and_waiter_does_not_renew(self):
        started_ocr = Event()
        halted_ocr = Event()
        original_recognize = HTTPTests.real_recognize

        def stalled_worker(command, *, timeout, **kwargs):
            self.assertEqual(command, service.OCR_COMMAND)
            self.assertEqual(kwargs['input'], PNG)
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 0.8)
            started_ocr.set()
            halted_ocr.wait(timeout)
            raise subprocess.TimeoutExpired(command, timeout)

        with (patch.object(service, 'recognize', side_effect=original_recognize),
              patch.object(subprocess, 'run', side_effect=stalled_worker),
              patch.object(service, 'PROBE_TIMEOUT', 0.8),
              patch.object(service, 'WAIT_TIMEOUT', 0.05),
              ThreadPoolExecutor(max_workers=2) as pool):
            owner = pool.submit(self.session.get)
            self.assertTrue(started_ocr.wait(1))
            waiter = pool.submit(self.session.get)
            self.assertEqual(waiter.result(1)['error'], 'order_probe_wait_timeout')
            self.assertEqual(owner.result(2)['error'], 'order_captcha_ocr_unavailable')
            self.assertEqual(len(self.probes), 1)
        self.assertEqual(self.posts, [])

    def test_order_captcha_post_preserves_alphanumeric_ocr(self):
        model = Mock()
        model.classification.side_effect = ['A', ' A9-b7 ']
        self.replies = [{'code': 1}]
        with (patch.object(service, 'ocr_model', return_value=model),
              patch.object(service, 'recognize',
                           side_effect=lambda image, _: service.recognize_in_worker(image))):
            self.assertTrue(self.session.get()['ready'])
        self.assertEqual([parse_qs(post.decode())['captcha'] for post in self.posts], [['A9b7']])

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

import io
import gzip
import zlib
import json
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import Cookie
from http.client import HTTPException, IncompleteRead
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
        session.last_ready_at -= service.TRANSPORT_GRACE + 1
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
        session.checked -= service.STALE_SERVE + service.PROBE_TIMEOUT + 1
        self.assertFalse(session.health()['ready'])

    def test_waiter_gets_recent_ready_result_while_probe_runs(self):
        # Probes take 10-45 s on 187; consumers must not queue behind them.
        gate = Event()
        calls = []

        def probe():
            calls.append(1)
            if len(calls) > 1:
                gate.wait(2)
            return {'ready': True, 'cookies': [{'name': 'PHPSESSID', 'value': 'x'}], 'error': None}

        session = Session(probe)
        self.assertTrue(session.get()['ready'])
        session.checked -= 21
        with patch.object(service, 'WAIT_TIMEOUT', 0.05), ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(session.get, True)
            for _ in range(100):
                if session.probing:
                    break
                time.sleep(0.01)
            self.assertTrue(pool.submit(session.get).result(1)['ready'])
            gate.set()
            self.assertTrue(owner.result(2)['ready'])

    def test_consumer_never_triggers_probe_while_recent_result_is_ready(self):
        calls = []
        session = Session(lambda: calls.append(1) or {'ready': True, 'cookies': [], 'error': None})
        session.get()
        session.checked -= 21
        self.assertTrue(session.get()['ready'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(session.get(refresh=True)['ready'])
        self.assertEqual(len(calls), 2)

    def test_waiter_does_not_get_stale_result(self):
        session = Session(lambda: {'ready': True, 'cookies': [], 'error': None})
        session.get()
        session.checked -= service.STALE_SERVE + 1
        session.probing = True
        session.lock.acquire()
        try:
            with patch.object(service, 'WAIT_TIMEOUT', 0.05):
                self.assertEqual(session.get()['error'], 'order_probe_wait_timeout')
        finally:
            session.lock.release()

    def test_transport_blip_keeps_last_ready_session(self):
        # 187 saw 4 probe timeouts in 2 minutes while the session stayed valid;
        # consumers must keep the cookies instead of failing the P0 round.
        results = [{'ready': True, 'cookies': [{'name': 'PHPSESSID', 'value': 'x'}], 'error': None},
                   {'ready': False, 'cookies': [], 'error': 'order_probe_transport_unavailable'}]
        session = Session(lambda: results.pop(0))
        self.assertTrue(session.get()['ready'])
        session.checked -= 21
        kept = session.get(refresh=True)
        self.assertTrue(kept['ready'])
        self.assertEqual(kept['cookies'], [{'name': 'PHPSESSID', 'value': 'x'}])
        self.assertEqual(session.health()['degraded'], 'order_probe_transport_unavailable')
        self.assertTrue(session.health()['ready'])

    def test_degraded_session_age_and_cookie_grace_use_last_success(self):
        ready = {'ready': True, 'cookies': [{'name': 'PHPSESSID', 'value': 'x'}], 'error': None}
        failed = {'ready': False, 'cookies': [], 'error': 'order_probe_transport_unavailable'}
        session = Session(Mock(side_effect=[ready, failed]))
        with patch.object(service.time, 'monotonic', return_value=100) as clock:
            self.assertEqual(session.get(), ready)
            clock.return_value = 100 + service.TRANSPORT_GRACE - 1
            self.assertEqual(session.get(refresh=True), ready)
            self.assertEqual(session.health()['verified_age_seconds'], service.TRANSPORT_GRACE - 1)
            clock.return_value += 2
            self.assertEqual(session.get(), failed)
            self.assertEqual(session.get(refresh=True), failed)
            self.assertFalse(session.health()['ready'])
            self.assertEqual(session.health()['verified_age_seconds'], service.TRANSPORT_GRACE + 1)

    def test_transport_failure_beyond_grace_drops_ready(self):
        results = [{'ready': True, 'cookies': [], 'error': None},
                   {'ready': False, 'cookies': [], 'error': 'order_probe_transport_unavailable'}]
        session = Session(lambda: results.pop(0))
        session.get()
        session.last_ready_at -= service.TRANSPORT_GRACE + 1
        session.checked -= 21
        self.assertEqual(session.get(refresh=True)['error'], 'order_probe_transport_unavailable')

    def test_identity_failure_is_not_masked_by_grace(self):
        results = [{'ready': True, 'cookies': [], 'error': None},
                   {'ready': False, 'cookies': [], 'error': 'order_identity_unverified'}]
        session = Session(lambda: results.pop(0))
        session.get()
        session.checked -= 21
        self.assertEqual(session.get(refresh=True)['error'], 'order_identity_unverified')

    def test_identity_failure_immediately_drops_ready(self):
        session = Session(lambda: {'ready': False, 'cookies': [], 'error': 'order_identity_unverified'})
        self.assertFalse(session.get()['ready'])
        self.assertFalse(session.health()['ready'])

    def test_missing_service_fails_closed(self):
        with patch('client.os.path.exists', return_value=False):
            with patch('time.sleep'), self.assertRaisesRegex(RuntimeError, '^global_order_unavailable:no_socket$'):
                client.cookies()

    def test_default_broker_entrypoints_preserve_retry_and_reason(self):
        from http.cookiejar import CookieJar

        context = Mock()
        for read in (client.cookies, lambda: client.fill_jar(CookieJar()),
                     lambda: client.apply(context), lambda: client.new_page(context)):
            with self.subTest(read=read), patch('client.os.path.exists', return_value=False) as exists, \
                 patch('time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, '^global_order_unavailable:no_socket$'):
                    read()
                self.assertEqual(exists.call_count, 3 * len(client.SOCKETS))
                self.assertEqual([call.args for call in sleep.call_args_list], [(21,), (21,)])
        context.add_cookies.assert_not_called()
        context.new_page.assert_not_called()

    def test_broker_budget_admits_only_retries_that_can_fit(self):
        for budget, retries in ((8, 0), (32, 1), (60, 2)):
            with self.subTest(budget=budget):
                clock = [100]
                def backoff(seconds):
                    clock[0] += seconds

                with patch('client.os.path.exists', return_value=False) as exists, \
                     patch('time.monotonic', side_effect=lambda: clock[0]), \
                     patch('time.sleep', side_effect=backoff) as sleep:
                    with self.assertRaisesRegex(RuntimeError, '^global_order_unavailable:no_socket$'):
                        client.cookies(timeout=budget)
                self.assertEqual(exists.call_count, (retries + 1) * len(client.SOCKETS))
                self.assertEqual([call.args for call in sleep.call_args_list], [(21,)] * retries)

    def test_bounded_broker_preserves_transport_and_session_failures(self):
        cases = [
            (ConnectionRefusedError(), 'transport:ConnectionRefusedError'),
            (socket.timeout(), 'transport:timeout'),
            (b'{"ready":false,"error":"order_identity_unverified"}\n', 'order_identity_unverified'),
        ]
        for reply, reason in cases:
            with self.subTest(reason=reason):
                stream = Mock()
                stream.recv.side_effect = [reply]
                connection = Mock()
                connection.__enter__ = Mock(return_value=stream)
                connection.__exit__ = Mock(return_value=False)
                with patch('client.socket.AF_UNIX', 1, create=True), \
                     patch('client.socket.socket', return_value=connection), \
                     patch('client.os.path.exists', return_value=True):
                    with self.assertRaisesRegex(RuntimeError, f'^global_order_unavailable:{reason}$'):
                        client.cookies(timeout=8)

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
             patch('time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, '^global_order_unavailable:transport:timeout$'):
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
        self.login_page_visits = 0
        self.login_redirects = 0
        self.login_referers = []
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
        elif path in ('/login.html', '/'):
            # Real Order: without PHPSESSID, /login.html -> / -> /login.html.
            if not any(c.name == 'PHPSESSID' for c in self.session.jar):
                self.cookie('PHPSESSID')
                self.login_redirects += 1
                status, payload = 302, b''
                response = self.response_stream(payload)
                response.status = status
                response.headers = {'Location': '/'}
                return response
            if path == '/':
                self.login_redirects += 1
                status, payload = 302, b''
                response = self.response_stream(payload)
                response.status = status
                response.headers = {'Location': '/login.html'}
                return response
            self.login_page_visits += 1
            status, payload = 200, LOGIN.encode()
        elif path == '/new_captcha.html':
            self.login_referers.append(req.get_header('Referer'))
            status, payload = 200, PNG
        else:
            self.assertEqual(path, '/admin/public/dologin.html')
            self.login_referers.append(req.get_header('Referer'))
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

    def test_each_login_attempt_opens_login_page_before_captcha(self):
        # Order answers "非法登录!" unless /login.html was opened in the same session.
        self.replies = [{'code': 0, 'msg': '验证码错误！'}, {'code': 1, 'msg': 'ok'}]
        self.assertTrue(self.session.get()['ready'])
        self.assertEqual(self.login_page_visits, 2)
        self.assertEqual(self.login_redirects, 4)
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(set(self.login_referers), {service.BASE + '/login.html'})

    def test_restart_logs_in_after_positive_login_page_evidence(self):
        self.assertEqual(list(self.session.jar), [])
        self.replies = [{'code': 1}]
        result = self.session.get()
        self.assertTrue(result['ready'])
        self.assertEqual({row['name'] for row in result['cookies']},
                         {'PHPSESSID', 'user', 'admin_username'})
        self.assertEqual(len(self.probes), 2)
        self.assertEqual(len(self.posts), 1)

    def test_confirmed_expiry_is_not_revived_by_renewal_transport_failure(self):
        self.cookie('PHPSESSID')
        self.outcome = (200, HOME)
        self.assertTrue(self.session.get(refresh=True)['ready'])
        self.session.checked -= 21
        self.outcome = (200, LOGIN)
        self.replies = [{'code': 1}]
        real_check = self.session.check_identity
        calls = []

        def check(deadline):
            calls.append(1)
            if len(calls) == 1:
                return real_check(deadline)
            return 'order_probe_transport_unavailable'

        with patch.object(self.session, 'check_identity', side_effect=check):
            result = self.session.get(refresh=True)
        self.assertFalse(result['ready'])
        self.assertIsNone(self.session.health()['degraded'])

    def test_consumers_do_not_get_expired_cookies_while_renewing(self):
        self.cookie('PHPSESSID')
        self.outcome = (200, HOME)
        self.assertTrue(self.session.get(refresh=True)['ready'])
        self.session.checked -= 21
        self.outcome = (200, LOGIN)
        seen = []

        def renew(deadline):
            # A consumer arrives while the upkeep thread is renewing.
            seen.append(self.session.get())
            return 'order_captcha_attempts_exhausted'

        with patch.object(self.session, 'renew', side_effect=renew):
            self.session.get(refresh=True)
        self.assertFalse(seen[0]['ready'])
        self.assertEqual(seen[0]['error'], 'order_session_renewing')

    def test_rejected_login_is_retried_after_hold(self):
        # 2026-11-26: the account whitelist was removed and later restored; the
        # broker must recover without a manual restart, but not hammer Order.
        self.replies = [{'code': 0, 'msg': '未设置谷歌验证器，请联系管理员'}, {'code': 1}]
        clock = [100]
        with patch('service.time.monotonic', side_effect=lambda: clock[0]):
            self.assertEqual(self.session.get(refresh=True)['error'], 'order_login_rejected')
            clock[0] += 21
            self.assertEqual(self.session.get(refresh=True)['error'], 'order_login_rejected')
            self.assertEqual(len(self.posts), 1)
            clock[0] += service.REJECTED_RETRY
            self.assertTrue(self.session.get(refresh=True)['ready'])
            self.assertEqual(len(self.posts), 2)

    def test_external_loss_after_valid_is_logged_once_per_session(self):
        self.replies = [{'code': 1}, {'code': 1}]
        clock = [100]
        with patch('service.time.monotonic', side_effect=lambda: clock[0]), \
             patch('service.log_event') as journal:
            self.assertTrue(self.session.get(refresh=True)['ready'])
            self.assertEqual(self.session.health()['sessions_lost_externally'], 0)
            self.assertIsNone(self.session.health()['last_external_loss_at'])

            clock[0] += 21
            self.outcome = (503, '')
            # A transport blip keeps the last ready session (degraded), no loss counted.
            self.assertTrue(self.session.get(refresh=True)['ready'])
            self.assertEqual(self.session.health()['degraded'], 'order_probe_transport_unavailable')
            self.assertEqual(self.session.health()['sessions_lost_externally'], 0)

            clock[0] += 21
            self.outcome = (200, LOGIN)
            with patch('service.recognize', return_value=''):
                self.assertFalse(self.session.get(refresh=True)['ready'])
            self.assertEqual(self.session.health()['sessions_lost_externally'], 1)

            clock[0] += 21
            self.assertEqual(self.session.get(refresh=True)['error'], 'order_login_cooldown')
            self.assertEqual(self.session.health()['sessions_lost_externally'], 1)

            clock[0] += 40
            self.assertTrue(self.session.get(refresh=True)['ready'])
            self.assertEqual(len(self.posts), 2)
            health = self.session.health()
            self.assertEqual(health['sessions_lost_externally'], 1)
            self.assertRegex(health['last_external_loss_at'], r'^\d{4}-\d{2}-\d{2}T')
            events = [call for call in journal.call_args_list if call.args == ('session_lost_externally',)]
            self.assertEqual(len(events), 1)
            self.assertEqual(set(events[0].kwargs), {'last_valid_at', 'detected_at'})
            self.assertEqual(events[0].kwargs['detected_at'], health['last_external_loss_at'])

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

    def test_valid_identity_requires_session_cookie(self):
        self.outcome = (200, HOME)
        self.assertEqual(self.session.get()['error'], 'order_session_cookies_missing')
        self.assertEqual(self.posts, [])

    def test_live_session_with_only_phpsessid_is_ready(self):
        # 187 live browser session exports only PHPSESSID at path / and every
        # consumer works with it; identity proof comes from the page itself.
        self.cookie('PHPSESSID')
        self.outcome = (200, HOME)
        result = self.session.get()
        self.assertTrue(result['ready'])
        self.assertEqual([row['name'] for row in result['cookies']], ['PHPSESSID'])

    def test_renewal_gets_its_own_deadline(self):
        # The authenticated page alone takes 10-20 s on 187; renewal must not
        # inherit what is left of the probe budget.
        self.outcome = (200, LOGIN)
        seen = []
        with patch.object(self.session, 'renew', side_effect=lambda d: seen.append(d - time.monotonic()) or 'order_captcha_attempts_exhausted'):
            self.session.get()
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0], service.RENEW_TIMEOUT - 1)

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
                self.assertEqual(self.session.get(refresh=True)['error'], 'order_captcha_attempts_exhausted')
                for instant in (121, 142, 163):
                    clock.return_value = instant
                    self.assertFalse(self.session.get(refresh=True)['ready'])
                self.assertEqual(len(self.posts), 2)
                self.assertEqual(len(self.probes), 4)
                clock.return_value = 184
                for name in ('PHPSESSID', 'user', 'admin_username'):
                    self.cookie(name)
                self.outcome = (200, HOME)
                self.assertTrue(self.session.get(refresh=True)['ready'])
                self.assertEqual(len(self.posts), 2)

    def test_transient_login_success_does_not_reset_post_budget(self):
        self.replies = [{'code': 1}] * 5
        with patch.object(service.time, 'monotonic', return_value=100) as clock:
            with patch.object(service, 'ocr_attempts', return_value=2):
                self.assertTrue(self.session.get(refresh=True)['ready'])
                clock.return_value = 121
                self.outcome = (200, LOGIN)
                self.assertTrue(self.session.get(refresh=True)['ready'])
                clock.return_value = 142
                self.outcome = (200, LOGIN)
                self.assertFalse(self.session.get(refresh=True)['ready'])
                self.assertEqual(len(self.posts), 2)
                clock.return_value = 163
                self.assertFalse(self.session.get(refresh=True)['ready'])
                self.assertEqual(len(self.posts), 2)
                clock.return_value = 421
                self.assertTrue(self.session.get(refresh=True)['ready'])
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
                clock.return_value = 100 + service.RENEW_TIMEOUT + 1
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

    def test_probe_http_decodes_and_bounds_compressed_responses(self):
        body = HOME.encode()
        large = body + b' ' * 512
        for encoding, wire, error in (
            ('gzip', gzip.compress(body), None),
            ('deflate', zlib.compress(body), None),
            ('br', body, 'order_response_encoding_unsupported'),
            ('identity', large, 'order_response_too_large'),
            ('gzip', gzip.compress(large), 'order_response_too_large'),
            ('deflate', zlib.compress(body)[:-2], 'order_response_compression_invalid'),
        ):
            with self.subTest(encoding=encoding, error=error):
                response = io.BytesIO(wire)
                response.status = 200
                response.headers = {'Content-Encoding': encoding}
                self.session.opener.open.reset_mock(side_effect=True)
                self.session.opener.open.return_value = response
                with patch.object(service, 'RESPONSE_LIMIT', 256):
                    if error:
                        with self.assertRaisesRegex(HTTPException, error):
                            self.session.request(service.PROBE_PATH, time.monotonic() + 1)
                    else:
                        status, _, payload = self.session.request(service.PROBE_PATH, time.monotonic() + 1)
                        self.assertEqual((status, payload), (200, body))
                request = self.session.opener.open.call_args.args[0]
                self.assertEqual(request.get_header('Accept-encoding'), 'gzip, deflate')
                self.assertEqual(self.session.login_attempts, 0)

    def test_slow_probe_body_releases_waiters_and_never_posts(self):
        reading = Event()
        finish_chunk = Event()
        self.addCleanup(finish_chunk.set)

        class SlowBody(io.BytesIO):
            def read1(self, *args):
                reading.set()
                finish_chunk.wait(2)
                clock.return_value = 100 + service.PROBE_TIMEOUT + 1
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
            self.assertLessEqual(timeout, 0.8 + 1e-6)
            started_ocr.set()
            halted_ocr.wait(timeout)
            raise subprocess.TimeoutExpired(command, timeout)

        with (patch.object(service, 'recognize', side_effect=original_recognize),
              patch.object(subprocess, 'run', side_effect=stalled_worker),
              patch.object(service, 'PROBE_TIMEOUT', 0.8),
              patch.object(service, 'RENEW_TIMEOUT', 0.8),
              patch.object(service, 'WAIT_TIMEOUT', 0.05),
              ThreadPoolExecutor(max_workers=2) as pool):
            owner = pool.submit(self.session.get)
            self.assertTrue(started_ocr.wait(1))
            waiter = pool.submit(self.session.get)
            self.assertEqual(waiter.result(1)['error'], 'order_session_renewing')
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

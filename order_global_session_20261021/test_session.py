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


import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from service import PROBE, Session


class ProbeError(Exception):
    pass


class ProbeRecoveryTests(unittest.TestCase):
    def response(self, status=200, url='https://order.p2pah.cn/admin/index/index.html'):
        response = Mock(status=status, url=url)
        response.text.return_value = '<a href="/admin/public/logout.html">logout</a>'
        return response

    def probe(self, results):
        ctx = Mock()
        ctx.request.get.side_effect = results
        ctx.cookies.return_value = [{'name': 'test', 'value': 'synthetic', 'domain': 'order.p2pah.cn'}]
        browser = Mock(contexts=[ctx])
        playwright = Mock()
        playwright.chromium.connect_over_cdp.return_value = browser
        manager = Mock()
        manager.__enter__ = Mock(return_value=playwright)
        manager.__exit__ = Mock(return_value=False)
        module = types.ModuleType('playwright.sync_api')
        module.sync_playwright = lambda: manager
        module.Error = ProbeError
        output = io.StringIO()
        with patch.dict(sys.modules, {'playwright': types.ModuleType('playwright'), 'playwright.sync_api': module}), contextlib.redirect_stdout(output):
            exec(PROBE, {})
        return json.loads(output.getvalue()), ctx

    def test_transport_failure_recovers_before_negative_cache(self):
        response = self.response()
        result, ctx = self.probe([ProbeError('private network detail'), response])
        session = Session(lambda: result)
        self.assertTrue(session.get()['ready'])
        self.assertEqual([call.kwargs['timeout'] for call in ctx.request.get.call_args_list], [12000, 8000])
        response.dispose.assert_called_once_with()

    def test_transient_status_retries_and_disposes_both_responses(self):
        for status in (429, 503):
            with self.subTest(status=status):
                first, second = self.response(status), self.response()
                result, ctx = self.probe([first, second])
                self.assertTrue(result['ready'])
                self.assertEqual(ctx.request.get.call_count, 2)
                first.dispose.assert_called_once_with()
                second.dispose.assert_called_once_with()

    def test_login_redirect_rejected_without_retry_or_cookies(self):
        response = self.response(url='https://order.p2pah.cn/login.html')
        result, ctx = self.probe([response])
        self.assertEqual(result, {'ready': False, 'cookies': [], 'error': 'order_identity_unverified'})
        ctx.request.get.assert_called_once()
        ctx.cookies.assert_not_called()

    def test_persistent_transport_failure_is_bounded_and_hides_details(self):
        result, ctx = self.probe([ProbeError('private'), ProbeError('private')])
        self.assertEqual(result, {'ready': False, 'cookies': [], 'error': 'order_probe_transport_unavailable'})
        self.assertEqual(ctx.request.get.call_count, 2)
        ctx.cookies.assert_not_called()

    def test_success_and_forbidden_do_not_retry(self):
        for status in (200, 403):
            with self.subTest(status=status):
                result, ctx = self.probe([self.response(status)])
                self.assertEqual(result['ready'], status == 200)
                ctx.request.get.assert_called_once()

    def test_probe_budget_fits_the_existing_cookie_client(self):
        with patch('service.subprocess.run', return_value=Mock(returncode=0, stdout='{"ready": false}')) as run:
            Session.browser_probe()
        self.assertEqual(run.call_args.kwargs['timeout'], 35)
        self.assertLess(8 + 12 + 8, 35)
        self.assertLess(35, 40)


if __name__ == '__main__':
    unittest.main()

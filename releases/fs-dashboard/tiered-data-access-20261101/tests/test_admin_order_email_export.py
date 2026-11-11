import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'source'))
import admin_order_email_export as export


class ExportTests(unittest.TestCase):
    def request(self, **changes):
        value = dict(site_id='266', game_ids=['1'], start='2026-10-01', end_exclusive='2026-10-02')
        value.update(changes)
        return value

    def page(self, rows, total=None, cursor=None):
        return 206, dict(semantics='live_non_snapshot', limitation='live_pagination_not_snapshot', source_reported_total=len(rows) if total is None else total, data=rows, next_cursor=cursor)

    def run_export(self, fetch, request=None, **kwargs):
        return export.collect(request or self.request(), 'actor', page_get=fetch, observed_at=lambda: '2026-11-11T12:00:00+08:00', **kwargs)

    def test_user_email_only_and_deduplication(self):
        rows = [dict(order_id='3', customer_email=' A@Example.COM ', pay_email='payment@invalid.test'), dict(order_id='2', customer_email='a@example.com'), dict(order_id='1', customer_email=None)]
        # The live adapter already strips surrounding whitespace.
        rows[0]['customer_email'] = rows[0]['customer_email'].strip()
        status, result = self.run_export(lambda *args: self.page(rows))
        self.assertEqual(status, 200)
        self.assertEqual(result['emails'], ['A@Example.COM'])
        self.assertEqual(result['observed_orders'], 3)
        self.assertEqual(result['missing_email_orders'], 1)
        self.assertTrue(result['complete'])
        self.assertEqual(result['semantics'], 'live_non_snapshot')

    def test_multigame_crossmonth_28_day_serial_windows(self):
        calls = []
        def fetch(query, user):
            calls.append(query.copy())
            return self.page([])
        status, result = self.run_export(fetch, self.request(game_ids=['1', '2'], start='2026-09-20', end_exclusive='2026-11-02'))
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 4)
        self.assertEqual([q['game_id'] for q in calls], [['1'], ['1'], ['2'], ['2']])
        self.assertEqual(calls[1]['start'], ['2026-10-18'])

    def test_pagination_and_no_partial_on_error(self):
        calls = []
        def fetch(query, user):
            calls.append(query.copy())
            if len(calls) == 1:
                return self.page([dict(order_id='3', customer_email='private@example.test')], 2, 'next')
            return 503, {'error': 'source_timeout'}
        status, result = self.run_export(fetch)
        self.assertEqual(status, 503)
        self.assertFalse(result['complete'])
        self.assertNotIn('emails', result)
        self.assertEqual(calls[1]['cursor'], ['next'])
        self.assertNotIn('private', json.dumps(result))

    def test_source_changed_and_unsupported_filters(self):
        for page in [self.page([], 2), self.page([dict(order_id='1', customer_email='bad')])]:
            status, result = self.run_export(lambda *args: page)
            self.assertGreaterEqual(status, 400)
            self.assertNotIn('emails', result)
        status, result = self.run_export(lambda *args: self.fail(), self.request(filters={'made_up': '1'}))
        self.assertEqual((status, result['error']), (422, 'invalid_export_request'))

    def test_dates_and_duplicate_json_fail_closed(self):
        for request in [self.request(start='2020-01-01'), self.request(end_exclusive='2027-01-01'), self.request(game_ids=['1', '1']), self.request(start='2026-1-01'), self.request(start='20261001'), self.request(end_exclusive='20261002'), self.request(start='2026-W40-4')]:
            self.assertEqual(self.run_export(lambda *args: self.fail(), request)[0], 422)
        with self.assertRaises(ValueError):
            export.parse_body(b'{"site_id":"266","site_id":"1"}')

    def test_page_and_time_budgets(self):
        with patch.object(export, 'MAX_PAGES', 0):
            status, result = self.run_export(lambda *args: self.fail())
            self.assertEqual(result['error'], 'export_budget_exceeded')
        ticks = iter([0, 46])
        self.assertEqual(self.run_export(lambda *args: self.fail(), clock=lambda: next(ticks))[0], 503)

    def test_crossgame_crosswindow_dedup_keeps_original_address(self):
        calls = []
        def fetch(query, user):
            calls.append(query.copy())
            address = 'Buyer+FC@Example.test' if len(calls) == 1 else 'buyer+fc@example.test'
            return self.page([dict(order_id=str(len(calls)), customer_email=address)])
        status, result = self.run_export(fetch, self.request(game_ids=['1', '2'], start='2026-09-20', end_exclusive='2026-11-02'))
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['emails'], ['Buyer+FC@Example.test'])
        self.assertEqual(result['observed_orders'], 4)
        self.assertEqual(result['unique_emails'], 1)

    def test_complete_json_envelope_budget_includes_unicode_escaping(self):
        rows = [dict(order_id=str(i), customer_email=('é' * 300) + str(i) + '@e.test') for i in range(10)]
        with patch.object(export, 'MAX_EXPORT_BYTES', 15000):
            status, result = self.run_export(lambda *args: self.page(rows))
        self.assertEqual(status, 503)
        self.assertEqual(result, {'error': 'export_response_too_large', 'complete': False})

    def test_response_budget_and_mid_export_revocation_discard_emails(self):
        with patch.object(export, 'MAX_EXPORT_BYTES', 4096):
            status, result = self.run_export(lambda *args: self.page([dict(order_id='1', customer_email='private@example.test')]))
        self.assertEqual(status, 503)
        self.assertEqual(result['error'], 'export_response_too_large')
        self.assertNotIn('emails', result)
        calls = []
        def fetch(query, user):
            calls.append(query.copy())
            if len(calls) == 1:
                return self.page([dict(order_id='2', customer_email='private@example.test')], 2, 'next')
            return 403, {'error': 'scope_denied'}
        status, result = self.run_export(fetch)
        self.assertEqual(status, 403)
        self.assertFalse(result['complete'])
        self.assertNotIn('emails', result)

    def test_no_login_and_empty_success(self):
        self.assertEqual(export.collect({}, None, page_get=lambda *args: self.fail())[0], 401)
        status, result = self.run_export(lambda *args: self.page([]))
        self.assertEqual(status, 200)
        self.assertEqual(result['emails'], [])


class HttpTests(unittest.TestCase):
    def setUp(self):
        import ast
        import re
        import types
        from urllib.parse import urlsplit
        root = pathlib.Path(__file__).resolve().parents[3]
        source = root / 'fs-dashboard/management-november-20261103/source/range_api.py'
        tree = ast.parse(source.read_text(encoding='utf8'))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        self.responses = []
        self.calls = []
        self.env = dict(urlsplit=urlsplit, re=re, LIVE_ADMIN=types.SimpleNamespace(run=lambda op, timeout: op()), verify_live_session=lambda cookie: (200, 'real-actor'))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), 'exec'), self.env)

    def invoke(self, extra=None, query='', path='/users/order-email-export', raw=None, implementation=None):
        import io
        import types
        if raw is None:
            request = dict(site_id='266', start='2026-10-01', end_exclusive='2026-10-02')
            request.update(game_id='1') if path.endswith('-page') else request.update(game_ids=['1'])
            raw = json.dumps(request).encode()
        headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw)), 'Sec-Fetch-Site': 'same-origin', 'X-Auth-User': 'forged'}
        headers.update(extra or {})
        target = types.SimpleNamespace(path=path + query, headers=headers, rfile=io.BytesIO(raw), connection=types.SimpleNamespace(settimeout=lambda t: None), reply=lambda status, result: self.responses.append((status, result)))
        def get(request, actor, *, run_source):
            run_source(lambda: self.calls.append(actor), 10)
            return 200, {'complete': True, 'emails': []}
        with patch.object(export, 'page_get' if path.endswith('-page') else 'get', implementation or get):
            self.env['do_POST'](target)
        return self.responses[-1]

    def test_verified_actor_and_origin_body_limits(self):
        self.assertEqual(self.invoke()[0], 200)
        self.assertEqual(self.calls, ['real-actor'])
        for headers, query in [({'Sec-Fetch-Site': 'cross-site'}, ''), ({'Content-Length': '4097'}, ''), ({'Content-Type': 'text/plain'}, ''), ({}, '?email=secret')]:
            self.assertGreaterEqual(self.invoke(headers, query)[0], 400)
        self.assertEqual(self.calls, ['real-actor'])

    def test_session_revocation_before_admitted_work(self):
        answers = iter([(200, 'real-actor'), (401, None)])
        self.env['verify_live_session'] = lambda cookie: next(answers)
        self.assertEqual(self.invoke()[0], 503)
        self.assertEqual(self.calls, [])

    def test_both_paths_share_all_guards_and_verified_session(self):
        for path in ('/users/order-email-export', '/users/order-email-export-page'):
            self.env['verify_live_session'] = lambda cookie: (200, 'real-actor')
            self.assertEqual(self.invoke(path=path)[0], 200)
            self.assertEqual(self.calls[-1], 'real-actor')
            before = len(self.calls)
            for headers, query, raw in [({'Sec-Fetch-Site': 'cross-site'}, '', None),
                    ({'Content-Length': '4097'}, '', None), ({'Content-Type': 'text/plain'}, '', None),
                    ({'Transfer-Encoding': 'chunked'}, '', None), ({}, '?cursor=secret', None),
                    ({}, '', b'{}'), ({}, '', b'{"site_id":"266","site_id":"266"}'),
                    ({'Content-Length': '4096'}, '', b'{}')]:
                with self.subTest(path=path, headers=headers, raw=raw):
                    self.assertGreaterEqual(self.invoke(headers, query, path, raw)[0], 400)
            self.assertEqual(len(self.calls), before)
            for status in (401, 403, 429, 503):
                self.env['verify_live_session'] = lambda cookie, status=status: (status, None)
                self.assertEqual(self.invoke(path=path)[0], status)
            answers = iter([(200, 'real-actor'), (200, 'different-actor')])
            self.env['verify_live_session'] = lambda cookie: next(answers)
            self.assertEqual(self.invoke(path=path)[0], 503)
            self.assertEqual(len(self.calls), before)

    def test_both_paths_private_permission_and_source_errors(self):
        import types
        for path, implementation in (('/users/order-email-export', export.get),
                                     ('/users/order-email-export-page', export.page_get)):
            with patch.dict(sys.modules, {'user_runtime': types.SimpleNamespace(authorize=lambda *a: False)}), patch('admin_email_export_source.get') as source:
                self.assertEqual(self.invoke(path=path, implementation=implementation)[0], 403)
                source.assert_not_called()
            with patch.dict(sys.modules, {'user_runtime': types.SimpleNamespace(authorize=lambda *a: True)}), patch('admin_email_export_source.get', return_value=(503, {'error': 'source_timeout'})):
                self.assertEqual(self.invoke(path=path, implementation=implementation), (503, {'error': 'source_timeout', 'complete': False}))


class PageExportTests(unittest.TestCase):
    def setUp(self):
        import types
        self.request = dict(site_id='266', game_id='1', start='2026-10-01', end_exclusive='2026-10-02')
        self.payload = dict(status='partial', complete=False, semantics='live_non_snapshot',
            limitation='live_pagination_not_snapshot', scope=dict(site_id='266', game_id='1'),
            period=dict(start='2026-10-01', end_exclusive='2026-10-02'), timezone='Asia/Shanghai',
            observed_at='2026-11-11T12:00:00+08:00', source_reported_total=0,
            observed_page_rows=0, data=[], next_cursor=None)
        self.auth = unittest.mock.Mock(return_value=True)
        self.runtime = patch.dict(sys.modules, {'user_runtime': types.SimpleNamespace(authorize=self.auth)})
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def call(self, payload=None, status=206, request=None):
        with patch('admin_email_export_source.get', return_value=(status, self.payload if payload is None else payload)) as source:
            result = export.page_get(self.request if request is None else request, 'real-actor', run_source='admission')
            self.source = source
            return result

    def test_one_page_projection_keeps_orders_and_original_spelling(self):
        self.payload.update(data=[dict(order_id=str(i + 1), customer_email=e, pay_email='never@test.invalid')
            for i, e in enumerate([' Straße@Example.test ', 'STRASSE@example.test', None, '', '  '])],
            source_reported_total=5, observed_page_rows=5)
        status, result = self.call()
        self.assertEqual(status, 206)
        self.assertFalse(result['complete'])
        self.assertEqual(result['date_field'], 'paytime')
        self.assertEqual(result['email_field'], 'user_email')
        self.assertEqual(len(result['data']), 5)
        self.assertEqual(result['data'][0]['email'], 'Straße@Example.test')
        self.assertEqual(result['data'][0]['email_key'], result['data'][1]['email_key'])
        self.assertEqual(result['data'][2], dict(order_id='3', email=None, email_key=None))
        self.assertNotIn('never', json.dumps(result))
        self.source.assert_called_once_with({k: [v] for k, v in self.request.items()}, 'real-actor', run_source='admission')
        self.auth.assert_called_once_with('real-actor', {'scope': 'site', 'scope_id': '266'}, True)

    def test_opaque_cursor_and_last_page_remain_partial(self):
        self.request['cursor'] = 'opaque.source-token'
        self.payload.update(data=[dict(order_id='1', customer_email=None)], source_reported_total=21, observed_page_rows=1)
        status, result = self.call()
        self.assertEqual(status, 206)
        self.assertIsNone(result['next_cursor'])
        self.assertFalse(result['complete'])
        self.assertEqual(self.source.call_args[0][0]['cursor'], ['opaque.source-token'])
        self.payload.update(data=[dict(order_id=str(i+1), customer_email=None) for i in range(20)], observed_page_rows=20, next_cursor='next.opaque')
        self.assertEqual(self.call()[1]['next_cursor'], 'next.opaque')

    def test_request_validation_before_source(self):
        for changes in [dict(game_id=1), dict(site_id='２６６'), dict(game_id=''), dict(game_ids=['1']),
                dict(actor='forged'), dict(start='20261001'), dict(start='2026-1-01'), dict(start='2026-W40-4'),
                dict(end_exclusive='2026-11-01'), dict(start='2020-01-01'), dict(end_exclusive='2027-01-01'),
                dict(filters={'status': 'paid'}), dict(filters=[]), dict(cursor=None), dict(cursor=''), dict(cursor=1), dict(cursor='a'*1025)]:
            with self.subTest(changes=changes):
                self.assertEqual(self.call(request=dict(self.request, **changes))[0], 422)
                self.source.assert_not_called()
        for raw in [b'{}', b'[]', b' '*4097, b'\xff', b'{"site_id":"266","site_id":"266"}',
                    json.dumps(dict(self.request, filters={'x': 1})).encode()]:
            with self.assertRaises(ValueError):
                export.parse_page_body(raw)

    def test_malformed_source_discards_all_data(self):
        good = dict(self.payload, data=[dict(order_id='1', customer_email='private@example.test')], observed_page_rows=1, source_reported_total=1)
        for changes in [dict(complete=True), dict(status='available'), dict(scope={}), dict(period={}),
                dict(timezone='UTC'), dict(observed_at='bad'), dict(observed_at='2026-11-11'),
                dict(source_reported_total=True), dict(source_reported_total=-1), dict(observed_page_rows=True),
                dict(observed_page_rows=2), dict(source_reported_total=2), dict(next_cursor=1), dict(next_cursor=''),
                dict(next_cursor='next'), dict(data={}), dict(data=[{}]),
                dict(data=[dict(order_id=1, customer_email=None)]), dict(data=[dict(order_id='1', customer_email=5)]),
                dict(data=[dict(order_id='1', pay_email='payment@example.test')]),
                dict(data=[dict(order_id='1', customer_email='bad')]),
                dict(data=good['data']*2, observed_page_rows=2, source_reported_total=2),
                dict(data=good['data']*21, observed_page_rows=21, source_reported_total=21)]:
            with self.subTest(changes=changes):
                status, result = self.call(dict(good, **changes))
                self.assertEqual(status, 503)
                self.assertNotIn('data', result)
                self.assertNotIn('private@', json.dumps(result))
        for payload in ([], None, {}, {'data': []}):
            if payload is not None:
                self.assertEqual(self.call(payload)[0], 503)

    def test_permission_and_source_errors_retry_after(self):
        self.assertEqual(export.page_get({}, None)[0], 401)
        self.auth.return_value = False
        self.assertEqual(self.call()[0], 403)
        self.source.assert_not_called()
        self.auth.return_value = True
        for status, error in [(403, 'scope_denied'), (422, 'invalid_live_query'), (409, 'source_changed_restart_required'),
                (429, 'source_busy'), (503, 'source_timeout')]:
            self.assertEqual(self.call({'error': error, 'retryAfter': 10, 'data': ['secret']}, status),
                (status, {'error': error, 'retryAfter': 10, 'complete': False}))

    def test_real_host_scope_cursor_and_revocation_boundaries(self):
        from admin_email_export_source import build_handler
        from test_live_global_authorization import RBAC
        config = dict(activation_status='W0_verified', sites={'266': {}, '267': {}},
                      projects={'1': {}}, live_admin_single_page=True)
        calls = []
        def fetch(path, params, timeout, cap):
            calls.append(params)
            rows = [dict(id=i, site_id=266, gid=1, paytime='2026-10-01 12:00:00',
                         status='11', pay_status='1', email='Buyer@example.test')
                    for i in (range(21, 1, -1) if params['page'] == 1 else [1])]
            return 200, json.dumps(dict(code=1, data=dict(total=21, list=rows))).encode()
        def live(params, actor, *, run_source):
            return build_handler(load_config=lambda: config, load_policy=lambda: {}, rbac=RBAC,
                fetch=fetch, run_source=run_source, authorize=self.auth)(params, actor)
        with patch('admin_email_export_source.get', live):
            def invoke(request):
                return export.page_get(request, 'real-actor', run_source=lambda op, timeout: op())
            self.auth.return_value = False
            self.assertEqual(invoke(dict(self.request, site_id='999'))[0], 403)
            self.assertEqual(calls, [])
            self.auth.return_value = True
            # The old generic project/site directory is not the admin's export scope.
            config['sites'] = {}
            config['projects'] = {}
            status, first = invoke(self.request)
            self.assertEqual(status, 206)
            self.assertEqual(len(first['data']), 20)
            self.assertEqual(calls[0]['limit'], 20)
            self.assertEqual(calls[0]['search[2][field]'], 'paytime')
            continuation = dict(self.request, cursor=first['next_cursor'])
            self.assertEqual(invoke(dict(continuation, cursor=first['next_cursor'] + 'bad'))[0], 422)
            status, last = invoke(continuation)
            self.assertEqual(status, 206)
            self.assertEqual(len(last['data']), 1)
            self.assertIsNone(last['next_cursor'])
            self.assertFalse(last['complete'])
            self.assertEqual(len(calls), 2)
            self.auth.return_value = False
            self.assertEqual(invoke(continuation)[0], 403)
            self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()

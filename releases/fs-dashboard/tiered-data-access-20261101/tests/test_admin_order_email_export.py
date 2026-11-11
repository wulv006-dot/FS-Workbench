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
        self.assertEqual((status, result['error']), (422, 'unsupported_export_filters'))

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

    def invoke(self, extra=None, query=''):
        import io
        import types
        raw = json.dumps(dict(site_id='266', game_ids=['1'], start='2026-10-01', end_exclusive='2026-10-02')).encode()
        headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw)), 'Sec-Fetch-Site': 'same-origin', 'X-Auth-User': 'forged'}
        headers.update(extra or {})
        target = types.SimpleNamespace(path='/users/order-email-export' + query, headers=headers, rfile=io.BytesIO(raw), connection=types.SimpleNamespace(settimeout=lambda t: None), reply=lambda status, result: self.responses.append((status, result)))
        def get(request, actor, *, run_source):
            run_source(lambda: self.calls.append(actor), 10)
            return 200, {'complete': True, 'emails': []}
        with patch.object(export, 'get', get):
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


if __name__ == '__main__':
    unittest.main()

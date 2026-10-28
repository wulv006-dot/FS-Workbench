"""Exercise the real detail consumers with the existing calendar-window helper."""
import ast
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[2]
sys.path.insert(0, str(PACKAGE / 'source'))
import cohort_paid_source as cohort


def function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


WINDOWS = function(REPO / 'releases/fs-dashboard/channel-effects-20261021/source/channel_source.py',
                   'windows', dict(date=date, timedelta=timedelta))
CHANNEL = SimpleNamespace(windows=WINDOWS, apply_cost_overrides=lambda value: value)
DETAIL = REPO / 'releases/fs-dashboard/fc-detail-analytics-20261012'
sys.path.insert(0, str(DETAIL / 'source'))
spec = importlib.util.spec_from_file_location('bounded_detail_reader', DETAIL / 'source/fc_detail_reader.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
CFG = json.loads((DETAIL / 'source/fc_detail_config.json').read_text(encoding='utf-8'))


class OrderDateWindows(unittest.TestCase):
    def online(self, pages, start='2026-09-01T06:12:34+08:00', end='2026-10-02T12:34:56+08:00'):
        namespace = dict(TZ=timezone(timedelta(hours=8)), defaultdict=defaultdict,
            _window_instant=datetime.fromisoformat, _quantity=lambda row: 0,
            amount=lambda value: float(value or 0),
            bind_price_windows=lambda rows, *args, **kwargs: dict(rows=len(rows), complete=True))
        call = function(REPO / 'releases/fc-coins/fc-pricing-v3-20261026/source/fc_pricing_v3/business_source.py',
                        'online_window_context', namespace)
        with patch.dict(sys.modules, channel_source=CHANNEL):
            return call(None, pages, [dict(opened_at=start, origin='confirmed_public_price_window',
                mode='production')], datetime.fromisoformat(end), [])

    def test_online_clips_seconds_and_covers_every_window(self):
        ranges = []
        def pages(session, path, filters, limit):
            ranges.append(filters[-1][2]); self.assertEqual(limit, 100)
            return []
        self.assertTrue(self.online(pages)['complete'])
        self.assertEqual(ranges, ['2026-09-01 06:12:34,2026-09-28 23:59:59',
                                  '2026-09-29 00:00:00,2026-10-02 12:34:56'])

    def test_online_short_window_remains_one_query_and_missing_slice_is_not_complete(self):
        calls = []
        def pages(*args): calls.append(args); return []
        self.online(pages, end='2026-09-02T12:34:56+08:00')
        self.assertEqual(len(calls), 1)
        def failed(*args): raise OSError('source unavailable')
        self.assertFalse(self.online(failed)['learning_coverage']['query_complete'])

    def test_online_repeated_identity_with_changed_row_is_rejected(self):
        def pages(session, path, filters, limit):
            return [dict(id=1, site_id=266, gid=1327, paytime=filters[-1][2].split(',')[0])]
        self.assertFalse(self.online(pages)['learning_coverage']['query_complete'])

    def detail(self, days, fail=None):
        ranges = []
        def request(path):
            if 'siteList' in path:
                return 200, json.dumps(dict(code=1, data=dict(list=[dict(id=266)])))
            p = parse_qs(urlsplit(path).query)
            paid = p.get('search[2][field]') == ['paytime']
            if paid: ranges.extend(p['search[2][val]'])
            if fail and paid: return fail, '{}'
            return 200, json.dumps(dict(code=1, data=dict(total=0, list=[])))
        q = dict(period=dict(start='2026-09-01 00:00',
            end=(datetime(2026, 9, 1) + timedelta(days=days)).strftime('%Y-%m-%d %H:%M')))
        return reader.collect(request, q, CFG), ranges

    def test_detail_long_window_uses_existing_daily_path_without_long_probe(self):
        result, ranges = self.detail(29)
        self.assertTrue(result['coverage']['paid_complete'])
        self.assertEqual(len(ranges), 29)
        self.assertEqual(ranges[0], '2026-09-01 00:00:00,2026-09-02 00:00:00')
        self.assertEqual(ranges[-1], '2026-09-29 00:00:00,2026-09-30 00:00:00')

    def test_detail_28_days_keeps_single_request_and_permission_failure_stops(self):
        _, ranges = self.detail(28)
        self.assertEqual(len(ranges), 1)
        with self.assertRaises(PermissionError): self.detail(29, fail=403)

    def test_detail_missing_daily_source_never_becomes_complete(self):
        with self.assertRaisesRegex(ValueError, 'fc_paid_days_unavailable'):
            self.detail(29, fail=500)

    def paid(self, request):
        with patch.dict(sys.modules, channel_source=CHANNEL):
            return cohort.collect(request, dict(profile='FC27', start='2026-08-01', end='2026-09-30'))

    def reply(self, path, *, ident=1, total=1):
        p = parse_qs(urlsplit(path).query)
        lower, upper = p['search[3][val]'][0].split(',')
        row = dict(id=ident, order_no='PRIVATE-' + str(ident), gid=1327, site_id=266,
                   pay_status=1, uid=12, paytime=lower)
        return 200, json.dumps(dict(code=1, data=dict(total=total, list=[row]))).encode()

    def test_cohort_preserves_full_range_and_per_slice_totals(self):
        calls = []
        def request(path, timeout):
            calls.append(parse_qs(urlsplit(path).query)['search[3][val]'][0])
            return self.reply(path, ident=len(calls))
        result = self.paid(request)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['coverage']['source_total'], 3)
        self.assertEqual(result['coverage']['received'], 3)
        self.assertEqual(calls, ['2026-08-01 00:00:00,2026-08-28 23:59:59',
            '2026-08-29 00:00:00,2026-09-25 23:59:59', '2026-09-26 00:00:00,2026-09-30 23:59:59'])
        self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_cohort_budget_is_global_and_missing_slices_stay_partial(self):
        clock = [0]
        def request(path, timeout):
            self.assertLessEqual(timeout, 30)
            clock[0] = 851
            return self.reply(path)
        with patch.object(cohort.time, 'monotonic', side_effect=lambda: clock[0]):
            result = self.paid(request)
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['coverage']['paid_complete'])
        self.assertEqual(len(result['coverage']['missing_windows']), 2)
        self.assertIsNone(result['coverage']['source_total'])

    def test_cohort_row_cap_is_shared_across_windows(self):
        calls = []
        def request(path, timeout):
            calls.append(path)
            return self.reply(path, ident=len(calls), total=1 if len(calls)==1 else 30000)
        with self.assertRaisesRegex(ValueError, 'row_budget'): self.paid(request)
        self.assertEqual(len(calls), 2)

    def test_cohort_conflicting_identity_and_missing_page_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_conflict'):
            self.paid(lambda path, timeout: self.reply(path))
        calls = []
        def request(path, timeout):
            calls.append(path)
            if len(calls)==1: return self.reply(path, total=2)
            return 200, json.dumps(dict(code=1, data=dict(total=2, list=[]))).encode()
        with self.assertRaisesRegex(ValueError, 'empty_page'): self.paid(request)


if __name__ == '__main__': unittest.main()

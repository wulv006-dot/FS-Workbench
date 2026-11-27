"""Offline Order HTML coverage of the V6 cost collector."""
import json
import re
import runpy
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from http.client import BadStatusLine
from io import StringIO
from itertools import chain, repeat
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from test_ps_six_cost import SOURCE, load
from order_http import OrderHTTP


FIXTURES = SOURCE.parents[3] / 'order_global_session_20261021' / 'fixtures'
LIST_HTML = (FIXTURES / 'real_delivery_v6.html').read_text(encoding='utf-8')
DETAIL_HTML = (FIXTURES / 'real_order_detail.html').read_text(encoding='utf-8')
LIST_HEADER, LIST_BODY = LIST_HTML.split('<tbody>', 1)
LIST_ROW = LIST_BODY.split('</tr>', 1)[0] + '</tr>'
SHANGHAI = timezone(timedelta(hours=8))
PLATFORMS = ('PS', 'XBOX', 'PC')


class CostListVerification(unittest.TestCase):
    def setUp(self):
        self.collector = load('cost_list_collector', SOURCE / 'collect_p2pah_cost.py')
        self.trade = datetime.now(SHANGHAI).replace(microsecond=0) - timedelta(minutes=5)
        self.rows = [dict(id=str(800000 + i), order=str(900000 + i), platform=platform,
                          price='.4', total='44.80', trade=self.trade - timedelta(seconds=i))
                     for i, platform in enumerate(PLATFORMS * 6)]
        self.detail_reads = []
        self.page_reads = []

    def fetch(self, path, timeout):
        route = urlsplit(path)
        if '/admin_order/' in route.path:
            order = route.path.rsplit('/', 1)[1].removesuffix('.html')
            self.detail_reads.append(order)
            shipments = {r['id']: dict(id=r['id'], pid='700018', qty='111', give='1',
                                       delivery_price=r['price'], delivery_amount=r['total'])
                         for r in self.rows if r['order'] == order}
            html = re.sub(r'(var orderDeliveryData = )[^;]+', lambda m: m[1] + json.dumps(shipments), DETAIL_HTML)
        else:
            query = parse_qs(route.query)
            page = int(query['page'][0])
            self.page_reads.append(page)
            start, end = (query[k][0] for k in ('start', 'end'))
            html = LIST_HEADER.replace('2026-10-28 10:22', start[:16]).replace('2026-10-28 13:22', end[:16])
            eligible = [r for r in self.rows if start <= r['trade'].strftime('%Y-%m-%d %H:%M:%S') <= end]
            for r in eligible[(page - 1) * 9:page * 9]:
                html_row = (LIST_ROW.replace('700000', r['id']).replace('700001', r['order'])
                            .replace('▶PS', '▶' + r['platform']).replace('1.111111', r['price'])
                            .replace('<span>11.11</span>', '<span>' + r['total'] + '</span>')
                            .replace('26-10-28 11:23:18', r['trade'].strftime('%y-%m-%d %H:%M:%S')))
                html += html_row
            html += '</tbody></table></body></html>'
        return path, html.encode('utf-8')

    def run_round(self, references=None):
        # Existing list and required-detail behavior when optional purchase
        # classification has no remaining time in this collection round.
        with patch.object(self.collector, 'monotonic', side_effect=chain([0], repeat(121))), \
                patch.object(self.collector, 'OrderHTTP', return_value=OrderHTTP(fetch=self.fetch)):
            result = self.collector.collect(curve_v6=True, confirmed_costs=references)
        self.assertEqual(result['status'], 'valid')
        self.assertEqual(result['cost_protocol'], 'fc27_curve_v6')
        self.assertEqual([r['platform'] for r in result['costs']], list(PLATFORMS))
        self.assertTrue(all(r['status'] == 'valid' for r in result['costs']))
        for platform in result['costs']:
            self.assertTrue(platform['v6_delivery_samples']['window_complete'])
        return {r['record_id']: r for cost in result['costs'] for r in cost['v6_delivery_samples']['records']}

    def test_normal_list_rows_do_not_read_details_and_keep_evidence(self):
        self.rows[0].update(price='.28', total='31.37')
        self.rows[1].update(price='.52', total='58.24')
        rows = self.run_round(dict.fromkeys(PLATFORMS, '.4'))
        self.assertEqual(self.detail_reads, [])
        self.assertEqual(self.page_reads, [1, 2, 3])
        self.assertEqual(len(rows), 18)
        self.assertEqual({r['verification'] for r in rows.values()}, {'list_fast_path'})
        self.assertEqual(rows['800000']['cny_per_1k'], '0.28')
        self.assertEqual(rows['800000']['quantity_evidence']['delivered_k'], '112')
        self.assertEqual(rows['800000']['quantity_evidence']['total_cny'], '31.37')
        self.assertIsNone(rows['800000']['quantity_evidence']['ordered_k'])
        self.assertEqual(rows['800000']['quantity_evidence']['listed_shipment_k'], '111')

    def test_optional_older_list_failure_preserves_the_qualified_recent_cost(self):
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost

        read = self.collector.read_page

        def optional_window_times_out(reader, page, observations=None, window=None):
            if window['end'] - window['start'] > timedelta(hours=3):
                raise self.collector.CostPageError('order_page_navigation_timeout:1', {})
            return read(reader, page, observations, window=window)

        with patch.object(self.collector, 'read_page', side_effect=optional_window_times_out), \
                patch.object(self.collector, 'OrderHTTP', return_value=OrderHTTP(fetch=self.fetch)):
            result = self.collector.collect(curve_v6=True, confirmed_costs=dict.fromkeys(PLATFORMS, '.4'))

        for row in result['costs']:
            cost = smooth_delivery_cost(row, row['platform'], datetime.now(timezone.utc), '.4')
            self.assertEqual(cost['selected_count'], 6)
            self.assertEqual(cost['bands']['large']['fallback_reason'], 'order_page_navigation_timeout:1')

    def test_unavailable_optional_older_order_detail_keeps_other_platforms_usable(self):
        from fc_pricing_v3.cost_inputs_v6 import smooth_delivery_cost

        self.rows.append(dict(id='800030', order='900030', platform='PS',
                              price='.6', total='67.20', trade=self.trade - timedelta(hours=4)))

        def fetch(path, timeout):
            if urlsplit(path).path.endswith('/900030.html'):
                return path, b'<html><body></body></html>'
            return self.fetch(path, timeout)

        with patch.object(self.collector, 'OrderHTTP', return_value=OrderHTTP(fetch=fetch)):
            result = self.collector.collect(curve_v6=True, confirmed_costs=dict.fromkeys(PLATFORMS, '.4'))

        self.assertEqual(result['status'], 'valid')
        costs = {row['platform']: smooth_delivery_cost(row, row['platform'], datetime.now(timezone.utc), '.4')
                 for row in result['costs']}
        self.assertTrue(all(row['status'] == 'valid' for row in costs.values()))
        self.assertEqual(costs['PS']['bands']['large']['fallback_reason'], 'cost_order_detail_unavailable')

    def test_required_combined_samples_take_priority_over_other_platform_history(self):
        required = [row for row in self.rows if row['platform'] == 'XBOX'][-3:]
        for row in required:
            row.update(price='.6', total='67.20', trade=row['trade'] - timedelta(hours=4))
        optional_orders = {str(900030 + i) for i in range(4)}
        self.rows.extend(dict(id=str(800030 + i), order=str(900030 + i), platform='PS',
                              price='.6', total='67.20', trade=self.trade - timedelta(hours=4, seconds=i))
                         for i in range(4))
        self.rows.sort(key=lambda row: row['trade'], reverse=True)
        with patch.object(self.collector, 'OrderHTTP', return_value=OrderHTTP(fetch=self.fetch)):
            result = self.collector.collect(curve_v6=True, confirmed_costs=dict.fromkeys(PLATFORMS, '.4'))

        required_orders = {row['order'] for row in required}
        older_reads = [order for order in self.detail_reads if order in required_orders | optional_orders]
        self.assertCountEqual(older_reads[:3], required_orders)
        self.assertTrue(all(row['status'] == 'valid' for row in result['costs']))

    def test_abnormal_rows_use_the_existing_detail_verifier(self):
        self.rows[0]['total'] = '44.82'
        self.rows[1].update(price='.27', total='30.24')
        self.rows[2].update(price='.53', total='59.36')
        self.rows[9]['order'] = self.rows[3]['order']
        rows = self.run_round(dict.fromkeys(PLATFORMS, '.4'))
        self.assertCountEqual(self.detail_reads, ['900000', '900001', '900002', '900003'])
        self.assertNotIn('800000', rows)
        for record_id in ('800001', '800002', '800003', '800009'):
            self.assertEqual(rows[record_id]['verification'], 'order_detail')
            self.assertEqual(rows[record_id]['quantity_evidence']['ordered_k'], '111')
        self.assertEqual(rows['800004']['verification'], 'list_fast_path')

    def test_cost_page_classifies_an_http_protocol_failure(self):
        def read_page(*args, **kwargs):
            raise BadStatusLine('invalid response')

        reader = SimpleNamespace(delivery_page=read_page)
        with self.assertRaisesRegex(self.collector.CostPageError, 'order_page_transport_error:1'):
            self.collector.read_page(reader, 1)

    def test_no_reference_requires_detail_for_all_platforms(self):
        for references in (None, {}):
            with self.subTest(references=references):
                self.detail_reads.clear()
                rows = self.run_round(references)
                self.assertCountEqual(self.detail_reads, [r['order'] for r in self.rows])
                self.assertEqual(len(rows), 18)
                self.assertEqual({r['verification'] for r in rows.values()}, {'order_detail'})

    def test_invalid_reference_requires_detail_for_that_platform(self):
        for reference in ('invalid', 'NaN', 'sNaN', 'Infinity', '-.4', '0'):
            with self.subTest(reference=reference):
                self.detail_reads.clear()
                rows = self.run_round({'PS': '.4', 'XBOX': reference, 'PC': '.4'})
                self.assertCountEqual(self.detail_reads, [r['order'] for r in self.rows if r['platform'] == 'XBOX'])
                self.assertEqual(rows['800000']['verification'], 'list_fast_path')
                self.assertEqual(rows['800001']['verification'], 'order_detail')

    def test_missing_platform_reference_uses_its_own_details(self):
        rows = self.run_round({'PS': '.4', 'PC': '.4'})
        self.assertCountEqual(self.detail_reads, [r['order'] for r in self.rows if r['platform'] == 'XBOX'])
        self.assertEqual(rows['800000']['verification'], 'list_fast_path')
        self.assertEqual(rows['800001']['verification'], 'order_detail')

    def test_cli_preserves_json_reference_types_with_unchecked_older_rows(self):
        for row in self.rows[12:]:
            row['trade'] -= timedelta(hours=4)
        for offset, row in enumerate(self.rows[12:15]):
            self.rows.append(dict(row, id=str(800018 + offset), order=str(900018 + offset),
                                  trade=row['trade'] - timedelta(minutes=1)))
        references = {'PS': '.40', 'XBOX': .4, 'PC': 'invalid'}
        output = StringIO()
        with patch('order_http.OrderHTTP', return_value=OrderHTTP(fetch=self.fetch)), \
                patch('time.monotonic', side_effect=chain([0], repeat(121))), \
                patch.dict('os.environ', FC_V6_COST_REFERENCES=json.dumps(references)), \
                redirect_stdout(output), self.assertRaises(SystemExit) as exit_status:
            runpy.run_path(str(SOURCE / 'collect_p2pah_cost.py'), run_name='__main__')

        report = json.loads(output.getvalue())
        self.assertEqual((exit_status.exception.code, report['status']), (0, 'valid'), report.get('reason'))
        for platform, cost in zip(PLATFORMS, report['costs']):
            samples = cost['v6_delivery_samples']
            self.assertEqual(len(samples['records']), 6)
            scope = samples['detail_scope']
            self.assertEqual(scope['older_detail_rows_not_checked'], 1)
            expected = None if platform == 'PC' else references[platform]
            self.assertEqual(scope['qualification_reference_cny_per_k'], expected)

    def test_expanded_window_rechecks_a_recent_order_found_again_on_an_older_row(self):
        self.rows[-1]['trade'] -= timedelta(hours=4)
        self.rows[-1]['order'] = self.rows[2]['order']
        rows = self.run_round(dict.fromkeys(PLATFORMS, '.4'))
        self.assertEqual(self.page_reads, [1, 2, 3] * 2)
        self.assertEqual(self.detail_reads, [self.rows[2]['order']])
        self.assertEqual(rows['800002']['verification'], 'order_detail')
        self.assertEqual(rows['800017']['verification'], 'order_detail')
        self.assertEqual(rows['800004']['verification'], 'list_fast_path')

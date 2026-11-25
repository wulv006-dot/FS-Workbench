"""Offline Order HTML coverage of the V6 cost collector."""
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
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
        with patch.object(self.collector, 'OrderHTTP', return_value=OrderHTTP(fetch=self.fetch)):
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

    def test_no_reference_requires_detail_for_all_platforms(self):
        for references in (None, {}):
            with self.subTest(references=references):
                self.detail_reads.clear()
                rows = self.run_round(references)
                self.assertCountEqual(self.detail_reads, [r['order'] for r in self.rows])
                self.assertEqual(len(rows), 18)
                self.assertEqual({r['verification'] for r in rows.values()}, {'order_detail'})

    def test_missing_platform_reference_uses_its_own_details(self):
        rows = self.run_round({'PS': '.4', 'PC': '.4'})
        self.assertCountEqual(self.detail_reads, [r['order'] for r in self.rows if r['platform'] == 'XBOX'])
        self.assertEqual(rows['800000']['verification'], 'list_fast_path')
        self.assertEqual(rows['800001']['verification'], 'order_detail')

    def test_expanded_window_rechecks_a_recent_order_found_again_on_an_older_row(self):
        self.rows[-1]['trade'] -= timedelta(hours=4)
        self.rows[-1]['order'] = self.rows[2]['order']
        rows = self.run_round(dict.fromkeys(PLATFORMS, '.4'))
        self.assertEqual(self.page_reads, [1, 2, 3, 1, 2, 3])
        self.assertEqual(self.detail_reads, [self.rows[2]['order']])
        self.assertEqual(rows['800002']['verification'], 'order_detail')
        self.assertEqual(rows['800017']['verification'], 'order_detail')
        self.assertEqual(rows['800004']['verification'], 'list_fast_path')

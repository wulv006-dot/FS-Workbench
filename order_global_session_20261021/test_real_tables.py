import importlib.util
from datetime import datetime
import json
from pathlib import Path
import re
import unittest

from lxml import html
from order_http import OrderHTTP, OrderReadError


FIXTURES = Path(__file__).with_name('fixtures')
COST_SOURCE = (FIXTURES.parents[1] / 'releases/fc-coins/fc-pricing-v3-20261026'
               / 'source/collect_p2pah_cost.py')
spec = importlib.util.spec_from_file_location('real_table_cost', COST_SOURCE)
cost = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cost)


def load_page(name):
    raw = (FIXTURES / f'real_{name}.html').read_bytes()
    return OrderHTTP(lambda path, timeout: (path, raw)), html.fromstring(raw.decode('utf-8'))


def text(cell):
    return ''.join(cell.itertext()).strip()


class OrderRealTableTests(unittest.TestCase):
    def test_cost_collects_the_same_delivery_rows_as_the_browser(self):
        cases = [('delivery_v6', 1), ('delivery_scalar', 1), ('delivery_v6_page2', 2),
                 ('delivery_order_links', 1)]
        for name, number in cases:
            with self.subTest(fixture=name):
                reader, tree = load_page(name)
                old_data_rows = [row.xpath('./td') for row in tree.xpath('//table//tr')
                                 if len(row.xpath('./td')) >= 10]
                self.assertTrue(old_data_rows)
                expected = []
                for cells in old_data_rows:
                    platform = re.fullmatch(r'FC\s*27\s*▶\s*(PS|XBOX|PC)', text(cells[6]), re.I)
                    if platform:
                        # The visible label is separate from the embedded action menu.
                        delivery_type = ''.join(cells[2].xpath('.//text()[not(ancestor::select)]')).strip()
                        path = cells[4].xpath('.//a/@href')[0]
                        expected.append(dict(platform=platform[1].upper(), record_id=text(cells[1]),
                                             delivery_type=delivery_type, trade_at=text(cells[5]),
                                             cny_per_1k=text(cells[9]), order_id=re.search(r'/id/(\d+)', path)[1],
                                             quantity=text(cells[7]), gift=text(cells[8]), cost_total=text(cells[10])))
                self.assertTrue(expected)
                window = None
                if name != 'delivery_scalar':
                    window = {key: datetime.strptime(tree.xpath(f'//*[@id="lot-{key}"]/@value')[0],
                                                     '%Y-%m-%d %H:%M')
                              for key in ('start', 'end')}
                    window['area'] = '0'
                actual = cost.read_page(reader, number, window=window)
                self.assertEqual(actual, dict(rows=expected, hasDataRows=True, empty=False,
                                              deliveryRowCount=len(old_data_rows)))

    def test_delivery_row_with_missing_cells_still_fails(self):
        _, tree = load_page('delivery_v6')
        row = next(row for row in tree.xpath('//tbody/tr') if len(row.xpath('./td')) == 19)
        for cell in row.xpath('./td')[8:]:
            row.remove(cell)
        raw = html.tostring(tree, encoding='utf-8')
        reader = OrderHTTP(lambda path, timeout: (path, raw))
        with self.assertRaisesRegex(OrderReadError, 'table_columns_unverified'):
            reader.delivery_page({'page': 1}, timeout=1)

    def test_channel_and_sales_match_the_original_lxml_exports(self):
        for fixture, sales in (('channel_delivery', False), ('sales_delivery', True)):
            with self.subTest(fixture=fixture):
                reader, tree = load_page(fixture)
                rows = tree.xpath('//table[contains(@class, "table-list")]//tbody/tr')
                self.assertTrue(any(len(row.xpath('./td')) == 8 for row in rows))
                if sales:
                    expected = [tuple(text(cell) for cell in row.xpath('./td')) for row in rows
                                if len(row.xpath('./td')) >= 16]
                    pages = re.findall(r'\d+', ' '.join(tree.xpath(
                        '//*[contains(@class,"pagination")]//text()')))
                else:
                    expected = [tuple(' '.join(cell.itertext()).strip() for cell in row.xpath('./td'))
                                for row in rows if not row.xpath('./td[@colspan]')]
                    pages = [page for link in tree.xpath('//*[contains(@class,"pagination")]//a/@href')
                             for page in re.findall(r'[?&]page=(\d+)', link)]
                self.assertTrue(expected)
                actual = reader.delivery_export_page({'page': 1}, timeout=1, sales=sales)
                self.assertEqual(actual.rows, tuple(expected))
                self.assertEqual(actual.page_count, max([1, *map(int, pages)]))
                self.assertTrue(actual.has_body_rows)

    def test_dashboard_stats_match_the_original_lxml_form_and_rows(self):
        for name, gid, site in (('shipping_stats', '1322', 'www.mmoexp.com'),
                                ('shipping_stats_rs', '506', '')):
            with self.subTest(fixture=name):
                reader, tree = load_page(name)
                filters = {'genre': '1', 'gid': gid, 'aid': '0', 'cid': '-1', 'status': '-1',
                           'op_id': '0', 'source[]': site, 'ship_source[]': '', 'show_ccy': '-1',
                           'start': '2026-10-27 00:00', 'end': '2026-10-27 23:59',
                           'keyword': '', 'sn': '', 'wid': ''}
                old_headers = [' '.join(cell.itertext()).strip() for cell in tree.xpath('//table//th')]
                old_rows = [[' '.join(cell.itertext()).strip() for cell in row.xpath('./td')]
                            for row in tree.xpath('//table//tbody/tr[td and not(td[@colspan])]')]
                self.assertTrue(old_rows)
                result = reader.dashboard_shipping(filters, timeout=1, reject_pagination=gid != '506')
                self.assertEqual(result, dict(filters=filters, headers=old_headers, rows=old_rows))
                generic = reader.shipping_stats(filters, timeout=1)
                self.assertEqual(generic.rows, tuple(dict(zip(old_headers, row)) for row in old_rows))

    def test_order_detail_matches_the_old_projection_for_the_attribution_list_order(self):
        _, listing = load_page('attribution_list')
        row, = listing.xpath('//table//tbody/tr[td]')
        cells = row.xpath('./td')
        self.assertEqual(len(cells), 13)
        self.assertIn('FIXTURE-ORDER-1', text(cells[2]))
        self.assertIn('www.mmoexp.com', text(cells[2]))
        order_path, = cells[2].xpath('.//a/@href')
        self.assertIn(order_path, cells[12].xpath('.//a/@href'))

        reader, detail = load_page('order_detail')
        goods = tuple({key: item.get('data-' + key) for key in
                       ('pid', 'gid', 'cid', 'aid', 'unit', 'qty', 'used')}
                      for item in detail.xpath('//table[contains(@class,"look-goods-table")]//tr[@data-pid]'))
        script, = detail.xpath('//script[contains(text(),"orderDeliveryData")]/text()')
        deliveries = tuple(dict(id=row['id'], pid=row['pid'], qty=row['qty'], gift=row['give'],
                                price=row['delivery_price'], total=row['delivery_amount'])
                           for row in json.loads(script.split('=', 1)[1].rstrip(';')).values())
        complete = bool(detail.xpath('(//tr[@class="log-item"])[1]/td[@class="order-status-3"]'))
        self.assertTrue(goods and deliveries and complete)
        result = reader.order_detail(re.search(r'/id/(\d+)', order_path)[1], timeout=1)
        self.assertEqual((result.status, result.goods, result.deliveries, result.complete),
                         ('found', goods, deliveries, complete))

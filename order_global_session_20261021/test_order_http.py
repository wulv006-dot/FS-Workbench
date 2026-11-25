
import ast
from contextlib import contextmanager
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
import re
from time import monotonic
from urllib.error import HTTPError
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from order_http import OrderHTTP


def page(body):
    return ('<table class="table-list"><thead><tr><th>编号</th><th>交货类型</th>'
            '</tr></thead><tbody>' + body + '</tbody></table>')


class OrderHTTPTests(unittest.TestCase):
    def test_missing_detail_is_explicit(self):
        def fetch(path, timeout):
            raise HTTPError(path, 404, 'missing', {}, BytesIO())
        self.assertEqual(OrderHTTP(fetch).order_detail('123', timeout=1).status, 'not_found')

    def test_detail_statuses(self):
        detail = (
            '<table class="look-goods-table"><tbody><tr data-pid="9" data-unit="K">'
            '</tr></tbody></table><tr class="log-item"><td class="order-status-3"></td></tr>'
            '<script>var orderDeliveryData = {"1":{"id":1,"pid":"9","qty":"3",'
            '"give":"0","delivery_price":"1","delivery_amount":"3"}};</script>'
        )
        for body, expected in ((detail, 'found'), ('<input type="password">', 'login_lost'),
                               ('<div>Detail</div>', 'parse_failed')):
            with self.subTest(expected=expected):
                result = OrderHTTP(lambda path, timeout: (path, body.encode())).order_detail('123', timeout=1)
                self.assertEqual(result.status, expected)
                if expected == 'found':
                    self.assertTrue(result.complete)
                    self.assertEqual(result.goods[0]['pid'], '9')
                    self.assertEqual(result.deliveries[0]['total'], '3')

        def timed_out(path, timeout):
            raise TimeoutError
        self.assertEqual(OrderHTTP(timed_out).order_detail('123', timeout=1).status, 'timeout')

    def test_delivery_iteration_and_boundaries(self):
        calls = []
        def fetch(path, timeout):
            calls.append(path)
            body = '' if path.endswith('page=2') else '<tr><td><b>7</b></td><td>订单发货</td></tr>'
            return path, page(body).encode()

        reader = OrderHTTP(fetch)
        pages = reader.iter_delivery_pages({}, max_pages=3, deadline=monotonic()+5)
        self.assertEqual(next(pages).rows, ({'编号': '7', '交货类型': '订单发货'},))
        self.assertEqual(pages.end_reason, 'caller_stopped')
        self.assertEqual(len(calls), 1)
        self.assertEqual([x.rows for x in pages], [()])
        self.assertEqual(pages.end_reason, 'source_exhausted')

        pages = reader.iter_delivery_pages({}, max_pages=1, deadline=monotonic()+5)
        self.assertEqual(len(list(pages)), 1)
        self.assertEqual(pages.end_reason, 'page_limit')
        pages = reader.iter_delivery_pages({}, max_pages=1, deadline=monotonic()-1)
        self.assertEqual(list(pages), [])
        self.assertEqual(pages.end_reason, 'deadline')

    def test_delivery_reordered_headers_and_invalid_pages(self):
        html = page('<tr><td>订单发货</td><td>7</td></tr>').replace(
            '<th>编号</th><th>交货类型</th>', '<th>交货类型</th><th>编号</th>')
        for body, failure in ((html, None), (html[:-8], 'table_truncated'),
                              (html.replace('<td>7</td>', ''), 'table_columns_unverified'),
                              ('<form action="/admin/public/dologin.html"></form>', 'login_lost')):
            with self.subTest(failure=failure):
                reader = OrderHTTP(lambda path, timeout: (path, body.encode()))
                pages = reader.iter_delivery_pages({}, max_pages=1, deadline=monotonic()+5)
                rows = list(pages)
                if failure is None:
                    self.assertEqual(rows[0].rows[0]['编号'], '7')
                else:
                    self.assertEqual(pages.end_reason, 'failed')
                    self.assertEqual(str(pages.failure), failure)

    def test_shipping_filter_readback(self):
        html = ('<select name="gid"><option value="0">全部</option>'
                '<option selected value="1322">FC</option></select>'
                '<table><tr><th>订单总数</th></tr><tr><td>6</td></tr></table>')
        result = OrderHTTP(lambda path, timeout: (path, html.encode())).shipping_stats({'gid': '1322'})
        self.assertEqual(result.filters['gid'], '1322')
        self.assertEqual(result.rows, ({'订单总数': '6'},))

    def test_delivery_matches_existing_lxml_parser(self):
        from lxml import html as LH

        # Load only the legacy parser. Importing the sales job creates its data folder.
        source = Path(__file__).resolve().parents[1] / 'shared_backend_session/sales_collection.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if
                     isinstance(node, ast.FunctionDef) and node.name in {'lxml_login', '_parse_delivery'}
                     or isinstance(node, ast.Assign) and any(
                         isinstance(target, ast.Name) and target.id == '_DELIV_HEAD' for target in node.targets)]
        namespace = dict(LH=LH, re=re)
        exec(compile(tree, str(source), 'exec'), namespace)
        labels = ('', '编号', '交货类型', '来源', '商户订单号', '交易时间', '游戏', '数量',
                  '赠送', '单价', '采购总额', '销售总额', '利润率', '供货商', '收款人',
                  '操作人', '备注', '结算状态', '操作')
        cells = ('', '<b>7</b>', '订单发货', 'www.example.test',
                 '<a href="/order/admin_order/look/id/123.html">TEST-123</a>',
                 '2026-11-25 02:01:02', 'FC 27 ▶ PS', '500', '0', '0.4', '200',
                 '250', '20%', 'fixture supplier', '', '', '', '未结算', '')
        html = ('<table class="table-list"><thead><tr>' +
                ''.join(f'<th>{label}</th>' for label in labels) + '</tr></thead><tbody><tr>' +
                ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr></tbody></table>')
        current = OrderHTTP(lambda path, timeout: (path, html.encode())).delivery_page({}, timeout=1)
        old, _ = namespace['_parse_delivery'](html, 1)
        projected = {name: current.rows[0][label] for label, name in zip(labels, namespace['_DELIV_HEAD'])
                     if label}
        self.assertEqual(projected, {key: value for key, value in old[0].items() if key not in ('', 'genre')})
        self.assertEqual(current.order_ids, ('123',))

    def test_shipping_preserves_empty_and_multiple_values(self):
        combined = ('<select name="empty[]" multiple><option value="0">Ordinary</option></select>'
                    '<select name="source[]" multiple><option selected value="1">A</option>'
                    '<option value="2">B</option><option selected value="3">C</option></select>'
                    '<table><tr><th>订单总数</th></tr><tr><td>6</td></tr></table>')

        def fetch(path, timeout):
            self.assertIn('source%5B%5D=1&source%5B%5D=3', path)
            return path, combined.encode()

        result = OrderHTTP(fetch).shipping_stats({'source[]': ('1', '3')})
        self.assertEqual(result.filters['empty[]'], ())
        self.assertEqual(result.filters['source[]'], ('1', '3'))

    def test_login_loss_reacquires_shared_session_on_next_request(self):
        @contextmanager
        def response(body, url):
            yield SimpleNamespace(geturl=lambda: url, read=lambda: body.encode())

        login = '<input name="password">'
        updated = ('<table class="look-goods-table"></table>'
                   '<script>var orderDeliveryData = {};</script>')
        old_opener = SimpleNamespace(open=lambda url, timeout: response(login, url))
        new_opener = SimpleNamespace(open=lambda url, timeout: response(updated, url))
        fill_jar = Mock()
        with patch.dict('sys.modules', {'fs_order_client': SimpleNamespace(fill_jar=fill_jar)}), \
             patch('order_http.build_opener', side_effect=[old_opener, new_opener]):
            reader = OrderHTTP()
            self.assertEqual(reader.order_detail('123', timeout=1).status, 'login_lost')
            self.assertEqual(reader.order_detail('123', timeout=1).status, 'found')
            self.assertEqual(reader.order_detail('123', timeout=1).status, 'found')
        self.assertEqual(fill_jar.call_count, 2)

    def test_truncated_response_fails_instead_of_yielding_an_empty_page(self):
        def fetch(path, timeout):
            raise IncompleteRead(b'<html>', 20)

        reader = OrderHTTP(fetch)
        pages = reader.iter_delivery_pages({}, max_pages=2, deadline=monotonic()+5)
        self.assertEqual(list(pages), [])
        self.assertEqual(pages.end_reason, 'failed')
        self.assertEqual(str(pages.failure), 'response_truncated')

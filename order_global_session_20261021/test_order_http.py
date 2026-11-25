
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

from order_http import OrderHTTP, OrderReadError


STATS_HEADERS = ('游戏', '￥销售总额', '￥采购总额', '利润率', '订单总数', '交易总数')


def shipping_fixture(fields='<input name="gid" value="1322">', rows='', headers=STATS_HEADERS):
    return ('<form action="/stats/admin_index/delivery.html">' + fields + '</form>' +
            '<table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) +
            '</tr></thead><tbody>' + rows + '</tbody></table>')


def page(body):
    return ('<table class="table-list"><thead><tr><th>编号</th><th>交货类型</th>'
            '</tr></thead><tbody>' + body + '</tbody></table>')


class OrderHTTPTests(unittest.TestCase):
    def test_missing_detail_is_explicit(self):
        def fetch(path, timeout):
            raise HTTPError(path, 404, 'missing', {}, BytesIO())
        self.assertEqual(OrderHTTP(fetch).order_detail('123', timeout=1).status, 'not_found')

    def test_http_error_without_body_is_classified_by_status(self):
        def fetch(path, timeout):
            raise HTTPError(path, 502, 'gateway error', {}, None)

        detail = OrderHTTP(fetch).order_detail('123', timeout=1)
        self.assertEqual((detail.status, detail.reason), ('parse_failed', 'http_502'))

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
        html = shipping_fixture(
            '<select name="gid"><option value="0">全部</option>'
            '<option selected value="1322">FC</option></select>',
            '<tr><td>1322&nbsp;| FC 27<td>1,250.00<td>800.00<td>36%<td>6<td>7</tr>')
        result = OrderHTTP(lambda path, timeout: (path, html.encode())).shipping_stats({'gid': '1322'})
        self.assertEqual(result.filters, {'gid': '1322'})
        self.assertEqual(result.rows[0]['￥销售总额'], '1,250.00')
        self.assertEqual(result.rows[0]['订单总数'], '6')

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
        combined = shipping_fixture(
            '<select name="empty[]" multiple><option value="0">Ordinary</option></select>'
            '<select name="source[]" multiple><option selected value="1">A</option>'
            '<option value="2">B</option><option selected value="3">C</option></select>')

        def fetch(path, timeout):
            self.assertIn('source%5B%5D=1&source%5B%5D=3', path)
            return path, combined.encode()

        result = OrderHTTP(fetch).shipping_stats({'source[]': ('1', '3'), 'empty[]': ''})
        self.assertEqual(result.filters['empty[]'], [])
        self.assertEqual(result.filters['source[]'], ['1', '3'])

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

    def test_shipping_rejects_pagination(self):
        html = shipping_fixture() + '<ul class="pagination"><li><a href="?page=2">2</a></li></ul>'
        reader = OrderHTTP(lambda path, timeout: (path, html.encode()))
        with self.assertRaisesRegex(OrderReadError, 'shipping_pagination_unhandled'):
            reader.shipping_stats({'gid': '1322'})

    def test_shipping_scope_reads_one_matching_form_with_unique_fields(self):
        other = '<form action="/other"><input name="gid" value="0"></form>'
        reader = OrderHTTP(lambda path, timeout: (path, (shipping_fixture() + other).encode()))
        self.assertEqual(reader.shipping_stats({'gid': '1322'}).filters, {'gid': '1322'})
        cases = [
            (shipping_fixture().replace('/stats/admin_index/delivery.html', '/unrelated'),
             'shipping_form_changed'),
            (shipping_fixture() + shipping_fixture().split('</form>')[0] + '</form>',
             'shipping_form_changed'),
            (shipping_fixture('<input name="cid" value="1">') + other, 'shipping_filter_missing'),
            (shipping_fixture('<input name="gid" value="1"><input name="gid" value="2">'),
             'shipping_filter_missing'),
        ]
        for html, reason in cases:
            with self.subTest(reason=reason):
                reader = OrderHTTP(lambda path, timeout: (path, html.encode()))
                with self.assertRaisesRegex(OrderReadError, reason):
                    reader.shipping_stats({'gid': '1322'})

    def test_shipping_empty_rows_require_a_known_marker_and_six_headers(self):
        for marker in ('暂无', '暂无数据', '没有数据'):
            with self.subTest(marker=marker):
                html = shipping_fixture(rows=f'<tr><td colspan="6">{marker}</td></tr>')
                result = OrderHTTP(lambda path, timeout: (path, html.encode())).shipping_stats({'gid': '1322'})
                self.assertEqual(result.rows, ())
                self.assertEqual(result.headers, STATS_HEADERS)
        for marker, headers, reason in [
            ('无权限', STATS_HEADERS, 'shipping_unknown_empty_state'),
            ('暂无', STATS_HEADERS[:-1], 'shipping_headers_unverified'),
        ]:
            with self.subTest(marker=marker, headers=headers):
                html = shipping_fixture(rows=f'<tr><td colspan="6">{marker}</td></tr>', headers=headers)
                reader = OrderHTTP(lambda path, timeout: (path, html.encode()))
                with self.assertRaisesRegex(OrderReadError, reason):
                    reader.shipping_stats({'gid': '1322'})

    def test_unavailable_shared_session_is_reported_at_public_read_interfaces(self):
        broker = SimpleNamespace(fill_jar=Mock(side_effect=RuntimeError('global_order_unavailable')))
        with patch.dict('sys.modules', fs_order_client=broker):
            reader = OrderHTTP()
            pages = reader.iter_delivery_pages({}, max_pages=2, deadline=monotonic()+5)
            self.assertEqual(list(pages), [])
            self.assertEqual(pages.end_reason, 'failed')
            self.assertEqual(str(pages.failure), 'global_order_unavailable')
            result = reader.order_detail('123', timeout=1)
            self.assertEqual((result.status, result.reason), ('parse_failed', 'global_order_unavailable'))

    def test_broker_and_order_request_share_page_deadline(self):
        for elapsed, expected in ((3, 2), (5, None)):
            with self.subTest(elapsed=elapsed):
                current = [10]
                def fill_jar(jar, *, timeout):
                    self.assertEqual(timeout, 5)
                    current[0] += elapsed

                @contextmanager
                def response(url, timeout):
                    yield SimpleNamespace(geturl=lambda: url, read=lambda: page('').encode())

                opener = SimpleNamespace(open=Mock(side_effect=response))
                with patch('order_http.monotonic', side_effect=lambda: current[0]), \
                     patch.dict('sys.modules', fs_order_client=SimpleNamespace(fill_jar=fill_jar)), \
                     patch('order_http.build_opener', return_value=opener):
                    pages = OrderHTTP().iter_delivery_pages({}, max_pages=1, deadline=15)
                    if expected is None:
                        self.assertEqual(list(pages), [])
                        self.assertEqual(pages.end_reason, 'deadline')
                        opener.open.assert_not_called()
                    else:
                        self.assertEqual(len(list(pages)), 1)
                        self.assertEqual(opener.open.call_args.kwargs['timeout'], expected)


from time import monotonic
from urllib.error import HTTPError
import unittest

from order_http import OrderHTTP


def page(body):
    return ('<table class="table-list"><thead><tr><th>编号</th><th>交货类型</th>'
            '</tr></thead><tbody>' + body + '</tbody></table>')


class OrderHTTPTests(unittest.TestCase):
    def test_missing_detail_is_explicit(self):
        def fetch(path, timeout):
            raise HTTPError(path, 404, 'missing', {}, None)
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

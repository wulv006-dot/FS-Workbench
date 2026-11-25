
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager, nullcontext
from http.client import HTTPConnection, HTTPSConnection, IncompleteRead
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from io import BytesIO
from hashlib import sha256
import gzip
import zlib
import json
from pathlib import Path
import re
import socket
from threading import Barrier, Event, Thread
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
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
    def test_native_order_stats_reads_browser_projection_from_literals(self):
        page = """<form>
          <select name="gid"><option>0</option><option selected value="1322">FC 27</option></select>
          <input name="start_paytime" value="2026-11-24 00:00">
          </form><div><h2>3</h2>订单数量</div>
          <div><h2>24.00</h2>订单金额</div>
          <div id="master-chart"></div><div id="status"></div>
          <script>
          var chartDom = document.getElementById('master-chart');
          var myChart = echarts.init(chartDom);
          var option = {
            title: {text: '订单数量和金额'},
            legend: {data: ['订单数', '订单金额']},
            xAxis: {type: 'category', data: ["2026-11-24 08"] // displayed bucket
            },
            tooltip: {formatter: function (data) { return data[0].value; }},
            series: [
              {name: '订单数', type: 'line', data: [3]},
              {name: '订单金额', type: 'line', data: ["24.00"]}
            ]
          };
          option && myChart.setOption(option);
          var chartDom5 = document.getElementById('status');
          var myChart5 = echarts.init(chartDom5);
          option5 = {title: {text: '订单状态'}, series: [
              {name: '订单状态', type: 'pie', data: [{"status":3,"value":"24.00","counts":3,"name":"已完成"}]}
          ]};
          option5 && myChart5.setOption(option5);
          </script>"""
        reader = OrderHTTP(lambda path, timeout: (path, page.encode()))
        filters = {'gid': '1322', 'start_paytime': '2026-11-24 00:00'}
        actual = reader.native_order_stats(filters, timeout=1)
        self.assertEqual(actual, {
            'filters': filters, 'names': ['3订单数量', '24.00订单金额'],
            'metrics': ['3', '24.00'],
            'charts': [
                {'title': ['订单数量和金额'], 'labels': ['2026-11-24 08'],
                 'series': [{'name': '订单数', 'data': [3]}, {'name': '订单金额', 'data': ['24.00']}]},
                {'title': ['订单状态'], 'labels': [],
                 'series': [{'name': '订单状态', 'data': [
                     {'status': 3, 'value': '24.00', 'counts': 3, 'name': '已完成'}]}]},
            ],
        })

    def test_problem_orders_preserve_filters_pagination_and_minimal_detail(self):
        order_list = """<form>
            <select name="status"><option value="6" selected>问题单</option></select>
            <select multiple name="gid[]"><option value="1322" selected>FC 27</option></select>
            <select multiple name="source[]"><option value="www.mmoexp.com" selected>MMOEXP</option></select>
            </form><table><thead><tr><th></th><th>ID</th><th>来源/ 商户订单号</th>
            <th>游戏/ 服务器</th><th>产品</th><th>角色名</th><th>金额</th><th>总量/已交量</th>
            <th>状态历时</th><th>提单时间</th><th>管理员/绑定下家/分组</th><th>状态</th><th>Actions</th>
            </tr></thead><tbody><tr><td></td><td>123</td><td>www.mmoexp.com PRIVATE</td><td>FC 27 ▶ PS</td>
            <td>Coins</td><td>PRIVATE</td><td>USD 24.00</td><td></td><td></td><td></td><td></td><td>问题单</td>
            <td><a href="javascript:open('/order/admin_order/look/id/123.html')">查看</a></td>
            </tr></tbody></table><ul class="pagination"><li><a href="?page=2">2</a></li></ul>"""
        detail = """<table><thead><tr><th>日志ID</th><th>生成时间</th><th>操作人</th><th>订单状态</th>
            <th>内容</th></tr></thead><tbody><tr><td>42</td><td>26-11-24 10:00:00</td><td>PRIVATE</td>
            <td>问题单</td><td>等待客户回复</td></tr></tbody></table>
            <table><tbody><tr class="jq-each-cg" data-gid="1322" data-aid="0" data-cid="1" data-qty="100">
            <td>PRIVATE</td></tr></tbody></table>"""
        paths = []
        def fetch(path, timeout):
            paths.append(path)
            return path, (order_list if '?' in path else detail).encode()

        reader = OrderHTTP(fetch)
        rows, has_next = reader.problem_order_page(1, timeout=1)
        self.assertTrue(has_next)
        self.assertEqual(rows, [{'id': '123', 'platform': 'PS', 'amount_usd': 24.0,
                                 'detail': '/order/admin_order/look/id/123.html'}])
        self.assertIn('page=1', paths[0])
        logs = reader.problem_order_logs('123', timeout=1)
        self.assertEqual(logs, [{'time': '26-11-24 10:00:00', 'status': '问题单', 'content': '等待客户回复'}])
        events = reader.problem_order_events('123', timeout=1)
        self.assertEqual(events['events'], [{'id': '42', 'time': '26-11-24 10:00:00', 'status': '问题单'}])
        self.assertEqual(events['item_count'], 1)
        self.assertEqual(events['items'][0]['qty'], '100')
        self.assertNotIn('PRIVATE', str(events))
        self.assertNotIn('等待客户回复', str(events))

    def test_remaining_consumer_manifest_pins_sources_and_range_overlay(self):
        from prepare_remaining_readers import prepare_range_api

        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'docs/planning/order-http-access-20261125/'
                               'consumer-release-3c-manifest.json').read_text(encoding='utf-8'))
        targets = {row['target'] for row in manifest['files']}
        self.assertEqual(len(targets), 10)
        self.assertIn('/opt/fs-order-session/order_http.py', targets)
        self.assertIn('/opt/fs-exact-range-20261001/fc_order_reader.py', targets)
        range_target = '/opt/fs-exact-range-20261001/range_api.py'
        for row in manifest['files']:
            source = (root / row['source']).read_bytes().replace(b'\r\n', b'\n')
            if row['target'] == range_target:
                self.assertEqual(sha256(source).hexdigest(), row['maintenanceSourceSha256'])
                builder = (root / row['preparation']).read_bytes().replace(b'\r\n', b'\n')
                self.assertEqual(sha256(builder).hexdigest(), row['preparationSha256'])
                range_source = source
            else:
                self.assertEqual(sha256(source).hexdigest(), row['sha256'], row['source'])

        baseline = (b"def call(container, script, requests, timeout):\n"
                    b" return dispatch_browser(container, script, requests, timeout)\n\n"
                    b"def extra_live_route():\n return 'preserved'\n\n"
                    b"def capture():\n"
                    b" existing_call('fs-order-browser','fc_category_reader.py', [], 5)\n"
                    b" return call('fc27-cloud-browser','primary_reader.py', [], 5)\n")
        before = sha256(baseline).hexdigest()
        prepared = prepare_range_api(baseline, range_source, before)
        self.assertIn(b"def extra_live_route():\n return 'preserved'\n", prepared)
        self.assertIn(b"existing_call(None,'fc_category_reader.py'", prepared)
        self.assertIn(b"call(None,'primary_reader.py'", prepared)
        self.assertIn(b"sys.executable,'-B',str(reader)", prepared)
        with self.assertRaisesRegex(ValueError, 'range_api_baseline_drift'):
            prepare_range_api(baseline + b'\n', range_source, before)

    def test_stats_and_problem_read_preserve_unavailable_and_filter_errors(self):
        blocked = OrderHTTP(lambda path, timeout: (path, b'<form><input type="password"></form>'))
        with self.assertRaisesRegex(ValueError, 'primary_login_or_page_unavailable'):
            blocked.native_order_stats({}, timeout=1)
        with self.assertRaisesRegex(ValueError, 'source_login_or_page'):
            blocked.problem_order_page(1, timeout=1)
        mismatched = OrderHTTP(lambda path, timeout: (path, b'<form><input name="gid" value="0"></form>'))
        with self.assertRaisesRegex(ValueError, 'primary_filter_mismatch'):
            mismatched.native_order_stats({'gid': '1322'}, timeout=1)

    def test_dashboard_shipping_preserves_single_selection_and_nested_text(self):
        body = shipping_fixture(
            '<select name="source[]" multiple><option selected value="main">Main</option></select>',
            '<tr><td><b>506</b> | RS</td><td>10</td><td>8</td><td>20%</td><td>1</td><td>2</td></tr>'
            '<tr><td colspan="6">查询期间暂无发货记录</td></tr>')
        reader = OrderHTTP(lambda path, timeout: (path, body.encode()))
        result = reader.dashboard_shipping({'source[]': 'main'}, timeout=1)
        self.assertEqual(result, dict(filters={'source[]': 'main'}, headers=list(STATS_HEADERS),
                                      rows=[['506  | RS', '10', '8', '20%', '1', '2']]))

    def test_delivery_export_preserves_channel_and_sales_page_evidence(self):
        cells = '<td></td><td>123</td><td>订单发货</td><td>www.mmoexp.com</td>' + '<td></td>' * 15
        body = ('<table class="table-list"><thead><tr><th>商户订单号</th></tr></thead>'
                '<tbody><tr>' + cells + '</tr></tbody></table>'
                '<div class="pagination"><a href="?page=2">2</a> 共 100 条</div>')
        reader = OrderHTTP(lambda path, timeout: (path, body.encode()))
        channel = reader.delivery_export_page({'page': 1}, timeout=1)
        sales = reader.delivery_export_page({'page': 1}, timeout=1, sales=True)
        self.assertEqual(channel.page_count, 2)
        self.assertEqual(sales.page_count, 100)
        self.assertTrue(channel.has_body_rows)
        self.assertEqual(channel.rows, sales.rows)
        self.assertEqual(channel.rows[0][:4], ('', '123', '订单发货', 'www.mmoexp.com'))

    def test_delivery_export_reuses_callers_session_and_refreshes_shared_cookie_jar(self):
        body = '<table class="table-list"><tbody><tr><td>暂无数据</td></tr></tbody></table>'
        def get(url, **kwargs):
            raw = SimpleNamespace(length_remaining=None, read=Mock(side_effect=[body.encode(), b'']))
            return nullcontext(SimpleNamespace(url=url, status_code=200, headers={}, raw=raw))

        session = SimpleNamespace(cookies=object(), get=Mock(side_effect=get))
        broker = SimpleNamespace(fill_jar=Mock())
        with patch.dict('sys.modules', {'fs_order_client': broker}):
            reader = OrderHTTP.from_order_session(session)
            for number in (1, 2):
                self.assertEqual(reader.delivery_export_page({'page': number}, timeout=1, sales=True).rows, ())
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(broker.fill_jar.call_count, 2)
        for number, (args, kwargs) in enumerate(session.get.call_args_list, 1):
            self.assertTrue(args[0].endswith(f'?page={number}'))
            self.assertFalse(kwargs['allow_redirects'])
        self.assertTrue(all(entry.args == (session.cookies,) for entry in broker.fill_jar.call_args_list))

    def test_dashboard_shipping_pagination_matches_the_consumers(self):
        body = shipping_fixture() + '<div class="pagination"><a href="?page=2">2</a></div>'
        reader = OrderHTTP(lambda path, timeout: (path, body.encode()))
        with self.assertRaisesRegex(ValueError, 'shipping_pagination_unhandled'):
            reader.dashboard_shipping({'gid': '1322'}, timeout=1)
        rs = reader.dashboard_shipping({'gid': '1322'}, timeout=1, reject_pagination=False)
        self.assertEqual(rs['rows'], [])

    def test_consumer_candidate_pins_bind_runtime_dependencies_and_payloads(self):
        root = Path(__file__).resolve().parents[1]
        source_map = json.loads((root / 'docs/collaboration/SOURCE-MAP.json').read_text(encoding='utf-8'))
        reader = source_map['orderHttpReader20261125']
        consumer_map = source_map['orderHttpConsumers20261125']
        release = json.loads((root / reader['release']).read_text(encoding='utf-8'))
        consumers = json.loads((root / consumer_map['release']).read_text(encoding='utf-8'))
        self.assertEqual(consumers['status'], 'candidate')
        deps = {reader['runtime'].split(':', 1)[1]: reader['sha256'],
                reader['brokerClientRuntime'].split(':', 1)[1]: reader['brokerClientSha256']}
        self.assertEqual({row['target']: row['sha256'] for row in consumers['prerequisites']}, deps)
        self.assertEqual({row['target']: row['sha256'] for row in release['files']
                          if row['target'] in deps}, deps)
        self.assertEqual({row['target'] for row in consumers['files']}, {
            '/opt/fs-exact-range-20261001/business_shipping.py',
            '/opt/fs-exact-range-20261001/rs_shipping.py',
            '/opt/fs-hermes-fc/channel_cost_source.py',
            '/opt/sales-dashboard/collector/fetch_all.py',
        })
        for row in release['files'] + consumers['files']:
            data = (root / row['source']).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(sha256(data).hexdigest(), row['sha256'], row['source'])

    def test_http_reads_bound_compressed_and_decoded_responses(self):
        html = page('<tr><td>7</td><td>订单发货</td></tr>').encode()
        large = html + b' ' * 512
        cases = [
            ('gzip', gzip.compress(html), None),
            ('deflate', zlib.compress(html), None),
            ('br', html, 'response_encoding_unsupported'),
            ('identity', large, 'response_too_large'),
            ('gzip', gzip.compress(large), 'response_too_large'),
            ('gzip', gzip.compress(html)[:-4], 'response_compression_invalid'),
        ]
        for pooled in (False, True):
            for encoding, wire, error in cases:
                with self.subTest(pooled=pooled, encoding=encoding, error=error):
                    def respond(url, *args, **kwargs):
                        headers = {'Content-Encoding': encoding}
                        if pooled:
                            self.assertEqual(kwargs['headers']['Accept-Encoding'], 'gzip, deflate')
                            self.assertTrue(kwargs['stream'])
                        else:
                            self.assertEqual(url.get_header('Accept-encoding'), 'gzip, deflate')
                            url = url.full_url
                        source = BytesIO(wire)
                        def read(size, **kwargs):
                            if pooled:
                                self.assertFalse(kwargs['decode_content'])
                            return source.read(size)
                        return nullcontext(SimpleNamespace(
                            url=url, geturl=lambda: url, status_code=200, headers=headers,
                            length=None, read1=read,
                            raw=SimpleNamespace(length_remaining=None, read=read)))

                    with patch.dict('sys.modules', fs_order_client=SimpleNamespace(fill_jar=Mock())), \
                         patch('order_http.OrderTransport', return_value=SimpleNamespace(open=respond)), \
                         patch('order_http.RESPONSE_LIMIT', 256, create=True):
                        reader = OrderHTTP.from_order_session(
                            SimpleNamespace(get=respond, cookies=object())) if pooled else OrderHTTP()
                        if error:
                            with self.assertRaisesRegex(OrderReadError, error):
                                reader.delivery_page({}, timeout=1)
                        else:
                            result = reader.delivery_page({}, timeout=1)
                            self.assertEqual(result.rows[0]['编号'], '7')
                            self.assertEqual(result.raw_sha256, sha256(html).hexdigest())

    def test_detail_reads_reuse_connection_and_reconnect_after_unannounced_close(self):
        ports = []
        wire = gzip.compress(b'<table class="look-goods-table"></table>'
                             b'<script>var orderDeliveryData = {};</script>')

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                ports.append(self.client_address[1])
                self.send_response(200)
                self.send_header('Content-Encoding', 'gzip')
                self.send_header('Content-Length', str(len(wire)))
                self.end_headers()
                self.wfile.write(wire)
                if self.path.endswith('/124.html'):
                    self.close_connection = True

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict('sys.modules', fs_order_client=SimpleNamespace(fill_jar=Mock())), \
                     patch('order_http.BASE', f'https://127.0.0.1:{server.server_port}'), \
                     patch.object(HTTPSConnection, 'connect', HTTPConnection.connect):
                    reader = OrderHTTP()
                    for order_id in ('123', '124', '125'):
                        self.assertEqual(reader.order_detail(order_id, timeout=1).status, 'found')
            finally:
                server.shutdown()
                worker.join(2)
        self.assertEqual(ports[0], ports[1])
        self.assertNotEqual(ports[1], ports[2])

    def test_parallel_detail_batches_lease_distinct_connections_and_reuse_them(self):
        arrived = Barrier(2, timeout=2)
        ports = {}
        body = (b'<table class="look-goods-table"></table>'
                b'<script>var orderDeliveryData = {};</script>')

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                ports[self.path.rsplit('/', 1)[-1]] = self.client_address[1]
                arrived.wait()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict('sys.modules', fs_order_client=SimpleNamespace(fill_jar=Mock())), \
                     patch('order_http.BASE', f'https://127.0.0.1:{server.server_port}'), \
                     patch.object(HTTPSConnection, 'connect', HTTPConnection.connect):
                    reader = OrderHTTP()
                    for ids in (('123', '124'), ('125', '126')):
                        with ThreadPoolExecutor(2) as pool:
                            work = [pool.submit(reader.order_detail, order_id, timeout=3) for order_id in ids]
                        self.assertEqual([job.result().status for job in work], ['found', 'found'])
            finally:
                server.shutdown()
                worker.join(2)
        first, second = (ports[f'{order_id}.html'] for order_id in ('123', '124'))
        self.assertNotEqual(first, second)
        self.assertEqual({ports['125.html'], ports['126.html']}, {first, second})

    def test_dripped_headers_and_body_share_request_deadline(self):
        prefix = b'HTTP/1.1 200 OK\r\nContent-Length: 9'
        for headers_slow in (True, False):
            with self.subTest(headers_slow=headers_slow):
                immediate, dripped = (prefix, b'\r\nX: 1234\r\n\r\n123456789') if headers_slow else (
                    prefix + b'\r\n\r\n', b'123456789')

                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        try:
                            self.connection.sendall(immediate)
                            for byte in dripped:
                                sleep(0.05)
                                self.connection.sendall(bytes([byte]))
                        except OSError:
                            pass

                broker = SimpleNamespace(fill_jar=Mock())
                with HTTPServer(('127.0.0.1', 0), Handler) as server:
                    worker = Thread(target=server.handle_request, daemon=True)
                    worker.start()
                    try:
                        # Keep urllib, HTTPResponse and the real socket reads. TLS is
                        # replaced with plain loopback transport for the offline test.
                        with patch.dict('sys.modules', fs_order_client=broker), \
                             patch('order_http.BASE', f'https://127.0.0.1:{server.server_port}'), \
                             patch.object(HTTPSConnection, 'connect', HTTPConnection.connect):
                            start = monotonic()
                            result = OrderHTTP().order_detail('123', timeout=0.12)
                            elapsed = monotonic() - start
                    finally:
                        worker.join(2)
                self.assertLess(elapsed, 0.30)
                self.assertEqual(result.status, 'timeout')

    def test_waiting_for_another_broker_acquisition_uses_own_deadline(self):
        entered, release = Event(), Event()

        def fill_jar(jar, *, timeout):
            entered.set()
            release.wait(2)
            raise RuntimeError('global_order_unavailable')

        broker = SimpleNamespace(fill_jar=fill_jar)
        with patch.dict('sys.modules', fs_order_client=broker), ThreadPoolExecutor(2) as pool:
            reader = OrderHTTP()
            first = pool.submit(reader.order_detail, '123', timeout=2)
            try:
                self.assertTrue(entered.wait(1))
                second = pool.submit(reader.order_detail, '456', timeout=0.05)
                try:
                    result = second.result(timeout=0.30)
                except FutureTimeout:
                    self.fail('the second read stayed blocked on the session lock')
                self.assertEqual(result.status, 'timeout')
            finally:
                release.set()
            first.result(timeout=1)

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

    def test_detail_classifies_socket_and_wrapped_timeouts(self):
        for error in (socket.timeout(), TimeoutError(), URLError(socket.timeout()), URLError(TimeoutError())):
            with self.subTest(error=type(error), reason=type(getattr(error, 'reason', None))):
                fetch = Mock(side_effect=error)
                self.assertEqual(OrderHTTP(fetch).order_detail('123', timeout=1).status, 'timeout')

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
        old = LH.fromstring(html).xpath('//tbody/tr/td')
        expected = tuple(''.join(cell.itertext()).strip() for cell in old)
        self.assertEqual(current.rows[0], dict(zip(labels[1:], expected[1:])))
        export = OrderHTTP(lambda path, timeout: (path, html.encode())).delivery_export_page(
            {'page': 1}, timeout=1, sales=True)
        self.assertEqual(export.rows, (expected,))


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
            yield SimpleNamespace(geturl=lambda: url.full_url, length=None, headers={},
                                  read1=Mock(side_effect=[body.encode(), b'']))

        login = '<input name="password">'
        updated = ('<table class="look-goods-table"></table>'
                   '<script>var orderDeliveryData = {};</script>')
        old_opener = SimpleNamespace(open=lambda url, deadline: response(login, url))
        new_opener = SimpleNamespace(open=lambda url, deadline: response(updated, url))
        fill_jar = Mock()
        with patch.dict('sys.modules', {'fs_order_client': SimpleNamespace(fill_jar=fill_jar)}), \
             patch('order_http.OrderTransport', side_effect=[old_opener, new_opener]):
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

    def test_broker_failure_reason_reaches_list_and_detail(self):
        for reason in ('no_socket', 'transport:ConnectionRefusedError', 'transport:timeout', 'order_identity_unverified'):
            with self.subTest(reason=reason):
                failure = 'global_order_unavailable:' + reason
                broker = SimpleNamespace(fill_jar=Mock(side_effect=RuntimeError(failure)))
                with patch.dict('sys.modules', fs_order_client=broker):
                    reader = OrderHTTP()
                    with self.assertRaisesRegex(OrderReadError, '^' + failure + '$'):
                        reader.delivery_page({}, timeout=1)
                    result = reader.order_detail('123', timeout=1)
                self.assertEqual((result.status, result.reason), ('parse_failed', failure))

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
                def response(url, deadline):
                    yield SimpleNamespace(geturl=lambda: url.full_url, length=None, headers={},
                                          read1=Mock(side_effect=[page('').encode(), b'']))

                opener = SimpleNamespace(open=Mock(side_effect=response))
                with patch('order_http.monotonic', side_effect=lambda: current[0]), \
                     patch.dict('sys.modules', fs_order_client=SimpleNamespace(fill_jar=fill_jar)), \
                     patch('order_http.OrderTransport', return_value=opener):
                    pages = OrderHTTP().iter_delivery_pages({}, max_pages=1, deadline=15)
                    if expected is None:
                        self.assertEqual(list(pages), [])
                        self.assertEqual(pages.end_reason, 'deadline')
                        opener.open.assert_not_called()
                    else:
                        self.assertEqual(len(list(pages)), 1)
                        self.assertEqual(opener.open.call_args.args[1] - current[0], expected)

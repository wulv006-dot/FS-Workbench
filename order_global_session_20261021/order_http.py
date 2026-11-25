
"""Read-only HTTP access to the shared Order session."""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from gzip import GzipFile
from hashlib import sha256
from html.parser import HTMLParser
from http.client import HTTPResponse, HTTPSConnection, IncompleteRead
from http.cookiejar import CookieJar
from io import BufferedReader, BytesIO, RawIOBase
import json
import re
import socket
from sys import version_info
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request
from weakref import finalize
import zlib

BASE = 'https://order.p2pah.cn'
ACCEPT_ENCODING = {'Accept-Encoding': 'gzip, deflate'}
RESPONSE_LIMIT = 1048576
DELIVERY = '/order/admin_delivery/index.html'
DETAIL = '/order/admin_order/look/id/{}.html'
DETAIL_LINK = re.compile(r'/order/admin_order/look/id/([0-9]+)\.html')
STATS = '/stats/admin_index/delivery.html'
SHIPPING_HEADERS = frozenset(('游戏', '￥销售总额', '￥采购总额', '利润率', '订单总数', '交易总数'))
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class OrderReadError(ValueError):
    def __init__(self, reason, *, status=None):
        super().__init__(reason)
        self.status = status


class Node:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.closed = False

    def find(self, tag=None, css=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (css is None or css in child.attrs.get('class', '').split()):
                    yield child
                yield from child.find(tag, css)

    def text_parts(self, *, skip_tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag != skip_tag:
                    yield from child.text_parts(skip_tag=skip_tag)
            else:
                yield child

    def text(self, separator='', *, skip_tag=None):
        return separator.join(self.text_parts(skip_tag=skip_tag))

    def direct(self, tag):
        return [child for child in self.children if isinstance(child, Node) and child.tag == tag]


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = Node('')
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in ('td', 'th') and self.stack[-1].tag in ('td', 'th'):
            self.stack.pop().closed = True
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def login_url(url):
    return 'login' in urlsplit(url).path.lower()


def field_value(node):
    if node.tag == 'input':
        return node.attrs.get('value', '')
    options = list(node.find('option'))
    selected = [item for item in options if 'selected' in item.attrs]
    if 'multiple' in node.attrs:
        return [item.attrs.get('value', item.text().strip()) for item in selected]
    option = next(iter(selected or options), None)
    return option.attrs.get('value', option.text().strip()) if option is not None else ''


def form_values(root):
    values = {}
    for node in list(root.find('input')) + list(root.find('select')):
        if node.attrs.get('type') in ('checkbox', 'radio') and 'checked' not in node.attrs:
            continue
        for key in (node.attrs.get('id'), node.attrs.get('name')):
            if key:
                values[key] = field_value(node)
    return values


def table_body_rows(table):
    return [row for body in table.find('tbody') for row in body.find('tr')]


def class_contains(root, name, tag=None):
    return (node for node in root.find(tag) if name in node.attrs.get('class', ''))


def table_rows(table, *, shipping=False):
    if not table.closed:
        raise OrderReadError('table_truncated')
    headers = tuple(node.text().strip() for node in table.find('th'))
    if shipping and (len(headers) != len(SHIPPING_HEADERS) or frozenset(headers) != SHIPPING_HEADERS):
        raise OrderReadError('shipping_headers_unverified')
    if not headers or len(set(filter(None, headers))) != sum(bool(header) for header in headers):
        raise OrderReadError('table_headers_unverified')
    delivery = len(headers) >= 11 and headers[2] == '交货类型' and headers[4] == '商户订单号'
    rows = []
    explicit_empty = False
    for row in table.find('tr'):
        cells = row.direct('td')
        if not cells:
            continue
        if len(cells) == 1:
            message = cells[0].text().strip()
            if shipping and 'colspan' in cells[0].attrs:
                if message not in ('暂无', '暂无数据', '没有数据'):
                    raise OrderReadError('shipping_unknown_empty_state')
                continue
            if not shipping and message == '暂无数据':
                explicit_empty = True
                continue
        merged = any('colspan' in cell.attrs or 'rowspan' in cell.attrs for cell in cells)
        if delivery and len(cells) < 10:
            # The native delivery footer has eight cells, with its leading
            # colspan covering the ID column. The DOM collector counts 10+ cells.
            has_id = (len(cells) > 1 and 'colspan' not in cells[0].attrs
                      and cells[1].text().strip().isdigit())
            has_order = any(DETAIL_LINK.search(link.attrs.get('href', '')) for link in row.find('a'))
            has_selector = any(node.attrs.get('type') == 'checkbox' for node in row.find('input'))
            if not (has_id or has_order or has_selector):
                continue
        if len(cells) != len(headers) or merged:
            raise OrderReadError('table_columns_unverified')
        rows.append(cells)
    return headers, rows, explicit_empty and not rows


@dataclass(frozen=True)
class DeliveryPage:
    page_no: int
    headers: tuple
    rows: tuple
    order_ids: tuple
    filters: dict
    has_next: bool
    raw_sha256: str
    explicit_empty: bool = False


@dataclass(frozen=True)
class DeliveryExportPage:
    rows: tuple
    page_count: int
    has_body_rows: bool


@dataclass(frozen=True)
class DetailResult:
    status: str
    goods: tuple = ()
    deliveries: tuple = ()
    complete: bool = False
    reason: str = ''


@dataclass(frozen=True)
class ShippingStats:
    headers: tuple
    filters: dict
    rows: tuple
    raw_sha256: str


class DeliveryPages:
    def __init__(self, reader, query, max_pages, deadline):
        self.end_reason = 'caller_stopped'
        self.failure = None
        self._pages = self._iterate(reader, dict(query), max_pages, deadline)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._pages)

    def close(self):
        self._pages.close()

    def _iterate(self, reader, query, max_pages, deadline):
        start = int(query.get('page', 1))
        for number in range(start, start + max_pages):
            remaining = deadline - monotonic()
            if remaining <= 0:
                self.end_reason = 'deadline'
                return
            try:
                page = reader.delivery_page(dict(query, page=number), timeout=min(35, remaining))
            except (OrderReadError, OSError) as exc:
                self.end_reason = 'deadline' if monotonic() >= deadline else 'failed'
                self.failure = exc
                return
            if monotonic() >= deadline:
                self.end_reason = 'deadline'
                return
            if not page.has_next:
                self.end_reason = 'source_exhausted'
            elif number == start + max_pages - 1:
                self.end_reason = 'page_limit'
            yield page
            if self.end_reason == 'source_exhausted':
                return
        self.end_reason = 'page_limit'


def remaining_time(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError('order_http_deadline')
    return remaining


def read_body(read, headers, expected, deadline):
    encoding = headers.get('Content-Encoding', '').strip().lower()
    if encoding not in ('', 'identity', 'gzip', 'deflate'):
        raise OrderReadError('response_encoding_unsupported')
    if expected is not None and expected > RESPONSE_LIMIT:
        raise OrderReadError('response_too_large')
    wire = bytearray()
    while True:
        remaining_time(deadline)
        chunk = read(min(65536, RESPONSE_LIMIT + 1 - len(wire)))
        if not chunk:
            break
        wire.extend(chunk)
        if len(wire) > RESPONSE_LIMIT:
            raise OrderReadError('response_too_large')
    remaining_time(deadline)
    if expected is not None and len(wire) != expected:
        raise IncompleteRead(b'', expected - len(wire))
    try:
        if encoding == 'gzip':
            with GzipFile(fileobj=BytesIO(wire)) as source:
                body = source.read(RESPONSE_LIMIT + 1)
        elif encoding == 'deflate':
            decoder = zlib.decompressobj()
            body = decoder.decompress(wire, RESPONSE_LIMIT + 1)
            if len(body) <= RESPONSE_LIMIT and (not decoder.eof or decoder.unused_data):
                raise OrderReadError('response_compression_invalid')
        else:
            body = bytes(wire)
    except (OSError, EOFError, zlib.error) as error:
        raise OrderReadError('response_compression_invalid') from error
    remaining_time(deadline)
    if len(body) > RESPONSE_LIMIT:
        raise OrderReadError('response_too_large')
    return body


def is_timeout(error):
    if isinstance(error, URLError):
        error = error.reason
    return isinstance(error, (socket.timeout, TimeoutError))


class DeadlineReader(RawIOBase):
    def __init__(self, stream, deadline):
        super().__init__()
        self.stream = stream
        self.raw = stream.makefile('rb', buffering=0)
        self.deadline = deadline

    def makefile(self, mode):
        # HTTPResponse uses this buffer for headers, chunk framing and the body.
        return BufferedReader(self)

    def readable(self):
        return True

    def readinto(self, buffer):
        self.stream.settimeout(remaining_time(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class OrderHTTPSConnection(HTTPSConnection):
    def __init__(self, host, deadline, **kwargs):
        super().__init__(host, **kwargs)
        self.deadline = deadline

    def connect(self):
        self.timeout = remaining_time(self.deadline)
        super().connect()
        self.sock.settimeout(remaining_time(self.deadline))

    def response_class(self, stream, **kwargs):
        return HTTPResponse(DeadlineReader(stream, self.deadline), **kwargs)


class OrderTransport:
    """Lease up to two idle connections for the shared Order session."""

    def __init__(self, jar):
        self.jar = jar
        self._idle = deque()
        self._lock = Lock()
        finalize(self, self._close_idle, self._idle)

    @staticmethod
    def _close_idle(idle):
        while idle:
            idle.pop().close()

    @contextmanager
    def open(self, request, deadline):
        self.jar.add_cookie_header(request)
        headers = dict(request.header_items())
        headers.setdefault('User-Agent', f'Python-urllib/{version_info.major}.{version_info.minor}')
        with self._lock:
            connection = self._idle.pop() if self._idle else None
        reusable = False
        try:
            if connection is not None:
                try:
                    response = self._request(connection, request, headers, deadline)
                except ConnectionError:
                    # An idle peer can close without sending Connection: close.
                    # Replay this read-only GET at most once, before any response.
                    connection.close()
                    connection = None
            if connection is None:
                connection = OrderHTTPSConnection(request.host, deadline)
                response = self._request(connection, request, headers, deadline)
            with response:
                self.jar.extract_cookies(response, request)
                if 300 <= response.status < 400 and login_url(response.headers.get('Location', '')):
                    raise OrderReadError('login_lost', status=response.status)
                if response.status != 200:
                    raise HTTPError(request.full_url, response.status, response.reason, response.headers, None)
                yield response
                # The caller drains and validates the body before returning.
                reusable = connection.sock is not None
        finally:
            if connection is not None:
                if reusable:
                    with self._lock:
                        if len(self._idle) < 2:
                            self._idle.append(connection)
                            connection = None
                if connection is not None:
                    connection.close()

    @staticmethod
    def _request(connection, request, headers, deadline):
        connection.deadline = deadline
        if connection.sock is not None:
            connection.sock.settimeout(remaining_time(deadline))
        connection.request('GET', request.selector, headers=headers)
        return connection.getresponse()


class OrderHTTP:
    def __init__(self, fetch=None):
        self._fetch = fetch
        self._transport = None
        self._session_lock = Lock()

    @classmethod
    def from_order_session(cls, session):
        """Reuse the caller's Order connection pool for paginated exports."""
        def fetch(path, timeout):
            from fs_order_client import fill_jar

            deadline = monotonic() + timeout
            fill_jar(session.cookies, timeout=min(40, timeout))
            with session.get(BASE + path, headers=ACCEPT_ENCODING, stream=True,
                             timeout=remaining_time(deadline), allow_redirects=False) as response:
                status = response.status_code
                if 300 <= status < 400 and login_url(response.headers.get('Location', '')):
                    raise OrderReadError('login_lost', status=status)
                if status != 200:
                    raise HTTPError(response.url, status, response.reason, response.headers, None)
                def read(size):
                    try:
                        return response.raw.read(size, decode_content=False)
                    except Exception as error:
                        # requests wraps these as OSError when consuming response.content.
                        # The raw stream is needed here to bound compressed bytes too.
                        from urllib3.exceptions import HTTPError as PoolHTTPError
                        if not isinstance(error, PoolHTTPError):
                            raise
                        raise OSError('order_response_transport') from error

                return response.url, read_body(read, response.headers,
                                               response.raw.length_remaining, deadline)

        return cls(fetch)

    @contextmanager
    def _session_access(self, deadline):
        if not self._session_lock.acquire(timeout=remaining_time(deadline)):
            raise TimeoutError('order_http_deadline')
        try:
            yield
        finally:
            self._session_lock.release()

    def _shared_transport(self, deadline):
        with self._session_access(deadline):
            if self._transport is None:
                from fs_order_client import fill_jar
                jar = CookieJar()
                try:
                    fill_jar(jar, timeout=min(40, remaining_time(deadline)))
                except RuntimeError as exc:
                    if str(exc).partition(':')[0] != 'global_order_unavailable':
                        raise
                    raise OrderReadError(str(exc)) from exc
                self._transport = OrderTransport(jar)
            return self._transport

    def _document(self, path, timeout):
        deadline = monotonic() + timeout
        transport = self._shared_transport(deadline) if self._fetch is None else None
        try:
            if transport is None:
                url, raw = self._fetch(path, remaining_time(deadline))
            else:
                remaining_time(deadline)
                request = Request(BASE + path, headers=ACCEPT_ENCODING)
                with transport.open(request, deadline) as response:
                    url = request.full_url
                    raw = read_body(response.read1, response.headers, response.length, deadline)
            if len(raw) > RESPONSE_LIMIT:
                raise OrderReadError('response_too_large')
            remaining_time(deadline)
            try:
                root = Document(raw.decode('utf-8-sig')).root
            except UnicodeError as exc:
                raise OrderReadError('response_encoding_invalid') from exc
            if (login_url(url) or any(node.attrs.get('type', '').lower() == 'password'
                                     or node.attrs.get('name') == 'password'
                                     for node in root.find('input'))
                    or any('dologin' in node.attrs.get('action', '') for node in root.find('form'))):
                raise OrderReadError('login_lost')
            return root, raw, url
        except IncompleteRead as exc:
            raise OrderReadError('response_truncated') from exc
        except OrderReadError as exc:
            if str(exc) == 'login_lost' and transport is not None:
                with self._session_access(deadline):
                    if self._transport is transport:
                        self._transport = None
            raise

    def dashboard_shipping(self, filters, *, timeout, reject_pagination=True):
        # The dashboard projects its exact six-column layout and single-site controls.
        try:
            root, _, _ = self._document(STATS + '?' + urlencode(filters), timeout)
        except HTTPError as exc:
            if exc.fp is not None:
                exc.close()
            if exc.code in (301, 302, 401, 403):
                raise PermissionError('shipping_session_denied') from exc
            raise OSError('shipping_page_unavailable') from exc
        except OrderReadError as exc:
            if str(exc) == 'login_lost':
                if exc.status is None or exc.status in (301, 302, 401, 403):
                    raise PermissionError('shipping_session_denied') from exc
                raise OSError('shipping_page_unavailable') from exc
            if str(exc).partition(':')[0] == 'global_order_unavailable':
                raise RuntimeError(str(exc)) from exc
            raise

        forms = [form for form in root.find('form') if form.attrs.get('action') == STATS]
        if len(forms) != 1:
            raise ValueError('shipping_form_changed')
        controls = list(forms[0].find())
        selected = {}
        for name in filters:
            fields = [node for node in controls if node.attrs.get('name') == name]
            if len(fields) != 1:
                raise ValueError('shipping_filter_missing')
            field = fields[0]
            if field.tag == 'select':
                options = field.direct('option')
                chosen = [item for item in options if 'selected' in item.attrs]
                if not chosen and 'multiple' not in field.attrs:
                    chosen = options[:1]
                if len(chosen) > 1:
                    raise ValueError('shipping_multiple_sources')
                selected[name] = chosen[0].attrs.get('value', '') if chosen else ''
            else:
                selected[name] = field.attrs.get('value', '')

        tables = [table for table in root.find('table')
                  if any(node.text().strip() == '订单总数' for node in table.find('th'))]
        if len(tables) != 1:
            raise ValueError('shipping_table_missing')
        headers = [node.text(' ').strip() for node in tables[0].find('th')]
        rows = []
        for row in table_body_rows(tables[0]):
            cells = row.direct('td')
            if cells and not any('colspan' in cell.attrs for cell in cells):
                rows.append([cell.text(' ').strip() for cell in cells])
            elif cells and not any(message in row.text() for message in ('没有数据', '暂无')):
                raise ValueError('shipping_unknown_empty_state')
        if reject_pagination and any(next(node.find('a'), None) is not None
                                     for node in class_contains(root, 'pagination')):
            raise ValueError('shipping_pagination_unhandled')
        return dict(filters=selected, headers=headers, rows=rows)

    def delivery_export_page(self, query, *, timeout, sales=False):
        """Read one delivery list page for the original channel or sales export format."""
        page = int(query.get('page', 1))
        path = DELIVERY + '?' + urlencode(query, doseq=True)
        for attempt in range(3):
            try:
                root, _, _ = self._document(path, timeout)
                break
            except HTTPError as exc:
                if exc.fp is not None:
                    exc.close()
                if sales:
                    raise RuntimeError('发货记录 HTTP=%s page=%d' % (exc.code, page)) from exc
                if exc.code in (301, 302, 401, 403):
                    raise PermissionError('shared_order_denied') from exc
                raise ValueError('shared_order_unavailable') from exc
            except OrderReadError as exc:
                if str(exc) == 'login_lost':
                    if sales:
                        raise RuntimeError('发货记录需要重新登录（返回了登录页）') from exc
                    if exc.status in (301, 302, 401, 403):
                        raise PermissionError('shared_order_denied') from exc
                    raise ValueError('shared_order_unavailable') from exc
                if str(exc).partition(':')[0] == 'global_order_unavailable':
                    raise RuntimeError(str(exc)) from exc
                raise
            except OSError as exc:
                if attempt < 2:
                    sleep(1.5 * (attempt + 1))
                    continue
                if sales:
                    raise RuntimeError('发货记录 HTTP=0 page=%d' % page) from exc
                raise ValueError('shared_order_unavailable') from exc

        pagination = class_contains(root, 'pagination')
        tables = class_contains(root, 'table-list', 'table')
        if sales:
            table = next(tables, None)
            if table is None:
                return DeliveryExportPage((), None, False)
            numbers = re.findall(r'\d+', ' '.join(node.text(' ') for node in pagination))
            rows = table_body_rows(table)
            cells = (tuple(cell.text().strip() for cell in row.direct('td')) for row in rows)
            return DeliveryExportPage(tuple(row for row in cells if len(row) >= 16),
                                      max(map(int, numbers), default=page), bool(rows))

        numbers = [int(value) for node in pagination for link in node.find('a')
                   for value in re.findall(r'[?&]page=(\d+)', link.attrs.get('href', ''))]
        tables = [table for table in tables
                  if any(node.text().strip() == '商户订单号' for node in table.find('th'))]
        if len(tables) != 1:
            raise ValueError('delivery_table_missing')
        rows = table_body_rows(tables[0])
        cells = []
        for row in rows:
            columns = row.direct('td')
            if any('colspan' in cell.attrs for cell in columns):
                continue
            values = tuple(cell.text(' ').strip() for cell in columns)
            if values != ('',):
                cells.append(values)
        return DeliveryExportPage(tuple(cells), max([page] + numbers), bool(rows))

    def delivery_page(self, query, *, timeout):
        number = int(query.get('page', 1))
        root, raw, url = self._document(DELIVERY + '?' + urlencode(dict(query, page=number), doseq=True), timeout)
        if parse_qs(urlsplit(url).query).get('page') != [str(number)]:
            raise OrderReadError('delivery_page_unverified')
        table = next(root.find('table', 'table-list'), None)
        if table is None:
            raise OrderReadError('delivery_table_missing')
        headers, cells, explicit_empty = table_rows(table)
        # The delivery type cell can contain a separate menu of editing options.
        rows = tuple({header: node.text(skip_tag='select' if header == '交货类型' else None).strip()
                      for header, node in zip(headers, row) if header} for row in cells)
        ids = [None] * len(cells)
        if '商户订单号' in headers:
            order_column = headers.index('商户订单号')
            for index, row in enumerate(cells):
                # The first merchant link can wrap the detail route in JavaScript.
                # Extract the numeric ID for order_detail's fixed GET route.
                link = next(row[order_column].find('a'), None)
                if link is not None and (match := DETAIL_LINK.search(link.attrs.get('href', ''))):
                    ids[index] = match[1]
        # The active collector proves the tail by requesting the first empty page.
        return DeliveryPage(number, headers, rows, tuple(ids), form_values(root),
                            bool(rows), sha256(raw).hexdigest(), explicit_empty)

    def iter_delivery_pages(self, query, *, max_pages, deadline):
        return DeliveryPages(self, query, max_pages, deadline)

    def order_detail(self, order_id, *, timeout):
        if not re.fullmatch(r'[0-9]+', str(order_id)):
            raise ValueError('invalid_order_id')
        try:
            root, _, _ = self._document(DETAIL.format(order_id), timeout)
            scripts = [match[1] for node in root.find('script')
                       if (match := re.search(r'^\s*var\s+orderDeliveryData\s*=\s*(\{[^\n]*\});\s*$',
                                              node.text(), re.M))]
            table = next(root.find('table', 'look-goods-table'), None)
            if len(scripts) != 1 or table is None or not table.closed:
                return DetailResult('parse_failed', reason='detail_structure_unverified')
            goods = tuple({key: row.attrs.get('data-' + key)
                           for key in ('pid', 'gid', 'cid', 'aid', 'unit', 'qty', 'used')}
                          for row in table.find('tr') if 'data-pid' in row.attrs)
            fields = dict(id='id', pid='pid', qty='qty', gift='give',
                          price='delivery_price', total='delivery_amount')
            deliveries = tuple({key: item[field] for key, field in fields.items()}
                               for item in json.loads(scripts[0]).values())
            log = next(root.find('tr', 'log-item'), None)
            return DetailResult('found', goods, deliveries,
                                log is not None and next(log.find('td', 'order-status-3'), None) is not None)
        except HTTPError as exc:
            if exc.fp is not None:
                exc.close()
            if exc.code == 404:
                return DetailResult('not_found')
            return DetailResult('parse_failed', reason=f'http_{exc.code}')
        except OSError as exc:
            if is_timeout(exc):
                return DetailResult('timeout')
            return DetailResult('parse_failed', reason='transport_error')
        except OrderReadError as exc:
            return DetailResult('login_lost' if str(exc) == 'login_lost' else 'parse_failed',
                                reason=str(exc))
        except (ValueError, TypeError, KeyError, AttributeError):
            return DetailResult('parse_failed', reason='detail_payload_invalid')

    def shipping_stats(self, filters, *, timeout=35):
        root, raw, _ = self._document(STATS + '?' + urlencode(filters, doseq=True), timeout)
        if any(next(node.find('a'), None) is not None for node in root.find(css='pagination')):
            raise OrderReadError('shipping_pagination_unhandled')

        forms = []
        for form in root.find('form'):
            action = urlsplit(form.attrs.get('action', ''))
            if action.path == STATS and (not action.netloc or action.netloc == urlsplit(BASE).netloc):
                forms.append(form)
        if len(forms) != 1:
            raise OrderReadError('shipping_form_changed')
        form = forms[0]
        controls = list(form.find('input')) + list(form.find('select'))
        selected = {}
        for name in filters:
            fields = [node for node in controls if node.attrs.get('name') == name]
            if len(fields) != 1:
                raise OrderReadError('shipping_filter_missing')
            selected[name] = field_value(fields[0])

        tables = [table for table in root.find('table')
                  if any(node.text().strip() == '订单总数' for node in table.find('th'))]
        if len(tables) != 1:
            raise OrderReadError('shipping_table_missing')
        headers, rows, _ = table_rows(tables[0], shipping=True)
        return ShippingStats(headers, selected,
                             tuple(dict(zip(headers, (cell.text().strip() for cell in row))) for row in rows),
                             sha256(raw).hexdigest())

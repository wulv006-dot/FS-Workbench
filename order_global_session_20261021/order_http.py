
"""Read-only HTTP access to the shared Order session."""
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import re
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, build_opener

BASE = 'https://order.p2pah.cn'
DELIVERY = '/order/admin_delivery/index.html'
DETAIL = '/order/admin_order/look/id/{}.html'
STATS = '/stats/admin_index/delivery.html'
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class OrderReadError(ValueError):
    pass


class Node:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.closed = False

    def find(self, tag, css=None):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag and (css is None or css in child.attrs.get('class', '').split()):
                    yield child
                yield from child.find(tag, css)

    def text(self):
        return ''.join(child.text() if isinstance(child, Node) else child for child in self.children)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = Node('')
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if login_url(newurl):
            raise OrderReadError('login_lost')
        return None


def login_url(url):
    return 'login' in urlsplit(url).path.lower()


def form_values(root):
    values = {}
    for node in root.find('input'):
        key = node.attrs.get('id') or node.attrs.get('name')
        if node.attrs.get('type') in ('checkbox', 'radio') and 'checked' not in node.attrs:
            continue
        if key:
            value = node.attrs.get('value', '')
            values[key] = value
            if node.attrs.get('name'):
                values[node.attrs['name']] = value
    for node in root.find('select'):
        key = node.attrs.get('id') or node.attrs.get('name')
        options = list(node.find('option'))
        if key:
            selected = [item for item in options if 'selected' in item.attrs]
            choices = tuple(item.attrs.get('value', item.text().strip()) for item in selected)
            if 'multiple' in node.attrs:
                value = choices
            elif choices:
                value = choices[0]
            elif options:
                value = options[0].attrs.get('value', options[0].text().strip())
            else:
                value = ''
            values[key] = value
            if node.attrs.get('name'):
                values[node.attrs['name']] = value
    return values


def table_rows(table):
    if not table.closed:
        raise OrderReadError('table_truncated')
    headers = tuple(node.text().strip() for node in table.find('th'))
    if not headers or len(set(filter(None, headers))) != sum(bool(header) for header in headers):
        raise OrderReadError('table_headers_unverified')
    rows = []
    for row in table.find('tr'):
        cells = [node for node in row.children if isinstance(node, Node) and node.tag == 'td']
        if not cells:
            continue
        if len(cells) == 1 and '暂无数据' in cells[0].text():
            continue
        if len(cells) != len(headers):
            raise OrderReadError('table_columns_unverified')
        rows.append(cells)
    return headers, rows


@dataclass(frozen=True)
class DeliveryPage:
    page_no: int
    headers: tuple
    rows: tuple
    order_ids: tuple
    filters: dict
    has_next: bool
    raw_sha256: str


@dataclass(frozen=True)
class DetailResult:
    status: str
    goods: tuple = ()
    deliveries: tuple = ()
    complete: bool = False
    reason: str = ''


@dataclass(frozen=True)
class ShippingStats:
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


class OrderHTTP:
    def __init__(self, fetch=None):
        self._fetch = fetch
        self._opener = None
        self._session_lock = Lock()

    def _shared_opener(self):
        with self._session_lock:
            if self._opener is None:
                from fs_order_client import fill_jar
                jar = CookieJar()
                fill_jar(jar)
                self._opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar), NoRedirect())
            return self._opener

    def _document(self, path, timeout):
        opener = self._shared_opener() if self._fetch is None else None
        try:
            if opener is None:
                url, raw = self._fetch(path, timeout)
            else:
                with opener.open(BASE + path, timeout=timeout) as response:
                    url, raw = response.geturl(), response.read()
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
        except OrderReadError as exc:
            if str(exc) == 'login_lost' and opener is not None:
                with self._session_lock:
                    if self._opener is opener:
                        self._opener = None
            raise

    def delivery_page(self, query, *, timeout):
        number = int(query.get('page', 1))
        root, raw, url = self._document(DELIVERY + '?' + urlencode(dict(query, page=number), doseq=True), timeout)
        if parse_qs(urlsplit(url).query).get('page') != [str(number)]:
            raise OrderReadError('delivery_page_unverified')
        table = next(root.find('table', 'table-list'), None)
        if table is None:
            raise OrderReadError('delivery_table_missing')
        headers, cells = table_rows(table)
        rows = tuple({header: node.text().strip() for header, node in zip(headers, row) if header} for row in cells)
        ids = []
        for row in cells:
            matches = [match[1] for cell in row for link in cell.find('a')
                       if (match := re.fullmatch(r'/order/admin_order/look/id/(\d+)\.html',
                                                urlsplit(link.attrs.get('href', '')).path))]
            ids.append(matches[0] if len(set(matches)) == 1 else None)
        # The active collector proves the tail by requesting the first empty page.
        return DeliveryPage(number, headers, rows, tuple(ids), form_values(root),
                            bool(rows), sha256(raw).hexdigest())

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
            exc.close()
            if exc.code == 404:
                return DetailResult('not_found')
            return DetailResult('parse_failed', reason=f'http_{exc.code}')
        except OSError as exc:
            if isinstance(exc, TimeoutError) or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)):
                return DetailResult('timeout')
            return DetailResult('parse_failed', reason='transport_error')
        except OrderReadError as exc:
            return DetailResult('login_lost' if str(exc) == 'login_lost' else 'parse_failed',
                                reason=str(exc))
        except (ValueError, TypeError, KeyError, AttributeError):
            return DetailResult('parse_failed', reason='detail_payload_invalid')

    def shipping_stats(self, filters, *, timeout=35):
        root, raw, _ = self._document(STATS + '?' + urlencode(filters, doseq=True), timeout)
        tables = [table for table in root.find('table')
                  if any(node.text().strip() == '订单总数' for node in table.find('th'))]
        if len(tables) != 1:
            raise OrderReadError('shipping_table_missing')
        headers, rows = table_rows(tables[0])
        return ShippingStats(form_values(root),
                             tuple(dict(zip(headers, (cell.text().strip() for cell in row))) for row in rows),
                             sha256(raw).hexdigest())

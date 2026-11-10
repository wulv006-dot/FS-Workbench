"""Read native Order item quantities for a verified Admin merchant order only."""
from decimal import Decimal, InvalidOperation
import math
import re
import threading
import time

from lxml import html

from .core import ContractError

LIST = '/order/admin_order/index.html'
DETAIL = re.compile(r'/order/admin_order/look/id/[0-9]{1,12}\.html')
PLATFORMS = {'21942': 'ps', '21944': 'xbox', '21946': 'pc'}


class OrderLineReader:
    def __init__(self, session):
        self.session = session
        self._pending = False
        self._lock = threading.Lock()

    def read(self, order_no, timeout=20):
        if not isinstance(order_no, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,100}', order_no):
            raise ContractError('ORDER_LINE_IDENTITY_INVALID')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 90:
            raise ContractError('ORDER_LINE_DEADLINE_INVALID')
        with self._lock:
            if self._pending:
                raise TimeoutError('ORDER_LINE_READ_BUSY')
            self._pending = True
        done, result = threading.Event(), {}

        def run():
            try:
                result['lines'] = self._read(order_no, time.monotonic() + timeout)
            except Exception as error:
                result['error'] = error if isinstance(error, (ContractError, TimeoutError)) else ContractError('ORDER_LINES_UNAVAILABLE')
            finally:
                with self._lock:
                    self._pending = False
                done.set()

        # The shared client has its own120s socket timeout; one in-flight read never queues another.
        threading.Thread(target=run, daemon=True).start()
        if not done.wait(timeout):
            raise TimeoutError('ORDER_LINE_READ_TIMEOUT')
        if 'error' in result:
            raise result['error']
        return result['lines']

    def _get(self, path, deadline, **params):
        if time.monotonic() >= deadline:
            raise TimeoutError('ORDER_LINE_READ_TIMEOUT')
        status, body = self.session.get_order(path, **params)
        if time.monotonic() >= deadline:
            raise TimeoutError('ORDER_LINE_READ_TIMEOUT')
        if status != 200 or not isinstance(body, str) or len(body.encode('utf-8')) > 2000000:
            raise ContractError('ORDER_LINES_UNAVAILABLE')
        doc = html.fromstring(body)
        if doc.xpath('//input[@name="password"]'):
            raise ContractError('ORDER_LINES_LOGIN_REQUIRED')
        return doc

    def _read(self, order_no, deadline):
        doc = self._get(LIST, deadline, sn=order_no, status='all', start='', end='', page='1')
        if doc.xpath('//input[@name="sn"]/@value') != [order_no]:
            raise ContractError('ORDER_LINE_ORDER_MISMATCH')
        tables = doc.xpath('//table[thead//th[normalize-space()="ID"]]')
        if len(tables) != 1:
            raise ContractError('ORDER_LINE_LIST_CHANGED')
        pages = [int(v) for link in doc.xpath('//*[contains(@class,"pagination")]//a/@href') for v in re.findall(r'[?&]page=(\d+)', link)]
        if any(n > 1 for n in pages):
            raise ContractError('ORDER_LINE_LIST_INCOMPLETE')
        rows = tables[0].xpath('.//tr[td]')
        if not rows or len(rows) > 200:
            raise ContractError('ORDER_LINE_ORDER_NOT_FOUND')
        paths = []
        for row in rows:
            cells = row.xpath('./td')
            if len(cells) != 13:
                raise ContractError('ORDER_LINE_LIST_CHANGED')
            merchant = ' '.join(cells[2].itertext())
            if not re.search(r'(?<![A-Za-z0-9_-])' + re.escape(order_no) + r'(?![A-Za-z0-9_-])', merchant) or 'www.mmoexp.com' not in merchant:
                raise ContractError('ORDER_LINE_ORDER_MISMATCH')
            if not re.search(r'FC\s*27', ' '.join(cells[3].itertext()), re.I):
                raise ContractError('ORDER_LINE_GAME_MISMATCH')
            links = {m.group() for a in cells[12].xpath('.//a') for key in ('href', 'onclick') for m in DETAIL.finditer(a.get(key, ''))}
            if len(links) != 1 or next(iter(links)) in paths:
                raise ContractError('ORDER_LINE_DETAIL_MISMATCH')
            paths.append(next(iter(links)))
        lines = []
        for path in paths:
            detail = self._get(path, deadline)
            if not re.search(r'(?<![A-Za-z0-9_-])' + re.escape(order_no) + r'(?![A-Za-z0-9_-])', ' '.join(detail.itertext())):
                raise ContractError('ORDER_LINE_DETAIL_MISMATCH')
            items = detail.xpath('//tr[contains(concat(" ",normalize-space(@class)," ")," jq-each-cg ")]')
            if not items or len(items) > 200:
                raise ContractError('ORDER_LINE_ITEMS_INCOMPLETE')
            for item in items:
                ids = {key: item.get('data-' + key, '') for key in ('gid', 'cid', 'pid', 'aid')}
                if any(not re.fullmatch(r'[1-9][0-9]{0,19}', value) for value in ids.values()):
                    raise ContractError('ORDER_LINE_PRODUCT_IDENTITY_INVALID')
                try:
                    quantity = Decimal(item.get('data-qty', ''))
                    if not quantity.is_finite() or quantity <= 0 or quantity > 9007199254740991:
                        raise ValueError()
                except (InvalidOperation, ValueError):
                    raise ContractError('ORDER_LINE_QUANTITY_INVALID') from None
                names = item.xpath('./td[contains(concat(" ",normalize-space(@class)," ")," col-product-cell ")]//*[contains(concat(" ",normalize-space(@class)," ")," product-title-wrap ")]')
                if len(names) != 1:
                    raise ContractError('ORDER_LINE_PRODUCT_NAME_MISSING')
                title = ' '.join(' '.join(names[0].itertext()).split())
                title = re.sub(r'^\[' + re.escape(ids['pid']) + r'\]\s*', '', title)
                if not title or len(title) > 240:
                    raise ContractError('ORDER_LINE_PRODUCT_NAME_INVALID')
                unit = item.get('data-unit', '')
                if ids['cid'] == '2' and not unit:
                    if quantity != quantity.to_integral_value():
                        raise ContractError('ORDER_LINE_QUANTITY_INVALID')
                    unit = 'item'
                lines.append(dict(game_id=ids['gid'], category_id=ids['cid'], product_id=ids['pid'],
                                  attribute_id=ids['aid'], platform=PLATFORMS.get(ids['aid'], 'unknown'),
                                  quantity=format(quantity, 'f'), unit=unit, title=title))
        return lines

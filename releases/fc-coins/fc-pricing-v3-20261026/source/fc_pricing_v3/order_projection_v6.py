"""The Order price page's native single-field edit for a FC27 B2C rate."""
import hashlib
import http.cookiejar
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler

ORIGIN = 'https://order.p2pah.cn'
PAGE = '/game/admin_game_price/index.html?gid=1322'
EDIT = '/game/admin_game_price/itemEdit'
IDS = {'PS': '21942', 'XBOX': '21944', 'PC': '21946'}
SCRIPT_SHA256 = '5cc6a802674337c6c05766a8a656cc87518d5b56bc054169ffbbeeb201ab704f'
EVIDENCE = 'order_item_edit_admin_js_sha256:' + SCRIPT_SHA256


def _rate(value):
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('pricing_curve_order_rate_invalid') from None
    if not rate.is_finite() or rate <= 0:
        raise ValueError('pricing_curve_order_rate_invalid')
    return rate


class _PricePage(HTMLParser):
    def __init__(self, platform):
        super().__init__(convert_charrefs=True)
        self.platform = platform
        self.rows = []
        self.row = None
        self.cell = None
        self.in_game = False
        self.games = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select' and attrs.get('id') == 'lot-game':
            self.in_game = True
        if tag == 'option' and self.in_game and 'selected' in attrs:
            self.games.append(attrs.get('value'))
        if tag == 'tr' and attrs.get('data-id') == IDS[self.platform]:
            self.row = dict(path=attrs.get('data-url'), titles=[], editors=[], game=False)
            self.rows.append(self.row)
        if self.row is None:
            return
        if tag == 'td':
            self.cell = attrs
            if attrs.get('title') == '1322':
                self.row['game'] = True
        if tag == 'input' and self.cell is not None:
            field = self.cell.get('data-type')
            if field == 'title':
                self.row['titles'].append(attrs.get('value'))
            if field == 'b2c':
                self.row['editors'].append((self.cell, attrs))

    def handle_endtag(self, tag):
        if tag == 'select':
            self.in_game = False
        elif tag == 'td':
            self.cell = None
        elif tag == 'tr':
            self.row = None
            self.cell = None

    def read(self):
        if self.games != ['1322'] or len(self.rows) != 1:
            raise ValueError('pricing_curve_order_page_scope_changed')
        row = self.rows[0]
        if (row['path'] != EDIT or not row['game'] or row['titles'] != [self.platform]
                or len(row['editors']) != 1):
            raise ValueError('pricing_curve_order_row_scope_changed')
        cell, editor = row['editors'][0]
        if (cell.get('send-url') is not None or 'toggle-input' not in cell.get('class', '').split()
                or cell.get('data-refresh') != '0' or cell.get('data-callback') != 'showprice'
                or editor.get('type') != 'text' or 'readonly' in editor or 'disabled' in editor):
            raise ValueError('pricing_curve_order_editor_scope_changed')
        return _rate(editor.get('value'))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OrderProjection:
    def __init__(self, opener=None):
        self.opener = opener

    def _opener(self):
        if self.opener is None:
            from fs_order_client import fill_jar

            jar = http.cookiejar.CookieJar()
            try:
                fill_jar(jar)
            except RuntimeError:
                raise ValueError('pricing_curve_order_session_unavailable') from None
            self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar), _NoRedirect())
        return self.opener

    def _request(self, path, data=None):
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': ORIGIN + PAGE}
        if data is not None:
            headers.update({'Origin': ORIGIN, 'X-Requested-With': 'XMLHttpRequest',
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                            'Accept': 'application/json, text/javascript, */*; q=0.01'})
        request = Request(ORIGIN + path, data=data, headers=headers)
        try:
            with self._opener().open(request, timeout=12) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def read(self, platform):
        status, raw = self._request(PAGE)
        if status != 200:
            raise ValueError('pricing_curve_order_page_unavailable')
        doc = _PricePage(platform)
        doc.feed(raw.decode('utf-8'))
        doc.close()
        return doc.read()

    def path(self, platform):
        return EDIT + '?' + urlencode({'ids': IDS[platform]})

    def prepare(self, platform, before, target):
        """Check the native row immediately before returning the exact POST."""
        if self.read(platform) != _rate(before):
            raise ValueError('pricing_curve_order_before_rate_changed')
        path = self.path(platform)
        payload = urlencode({'data_type': 'b2c', 'data_val': format(_rate(target), 'f')}).encode()

        def send(observer):
            started = datetime.now(timezone.utc).isoformat()
            try:
                status, raw = self._request(path, payload)
            except OSError as error:
                observer(dict(path=path, started_at=started, received_at=datetime.now(timezone.utc).isoformat(),
                              transport_error=type(error).__name__))
                raise
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                value = None
            code = value.get('code') if isinstance(value, dict) else None
            observer(dict(path=path, started_at=started, received_at=datetime.now(timezone.utc).isoformat(),
                          http_status=status, response_code=code, response_sha256=hashlib.sha256(raw).hexdigest()))
            if status != 200 or type(code) is not int or code != 1:
                raise ValueError('pricing_curve_order_item_edit_rejected')

        return send

    def adapter(self, platform):
        return dict(path=self.path(platform), evidence_ref=EVIDENCE, read=self.read, prepare=self.prepare)


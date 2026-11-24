"""Read only the submitted mailbox's MMOEXP order history from Admin."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from match_rewards_delivery import EMAIL


SITE = 266
SHANGHAI = timezone(timedelta(hours=8))
START = datetime(2026, 10, 1)
ORDERS = '/admin/order.Order/index'
MEMBERS = '/admin/user.Member/index'
ADMIN = 'http://127.0.0.1:8912'
PAGE_SIZE = 50
MAX_PAGES = 40
MAX_BYTES = 2 * 1024 * 1024


class OrderLookupError(RuntimeError):
    """Eligibility cannot be established from the available Admin data."""


@dataclass(frozen=True)
class OrderHistory:
    member_id: int
    paid: int
    completed: int


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(path, params):
    request = Request(ADMIN + path + '?' + urlencode(params),
                      headers={'X-Requested-With': 'XMLHttpRequest'}, method='GET')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise OrderLookupError('Admin order page exceeds the read limit')
    return json.loads(raw)


def _decimal_int(value):
    value = str(value)
    if not value.isascii() or not value.isdecimal() or len(value) > 20:
        raise OrderLookupError('Admin returned an invalid numeric field')
    return int(value)


def _page(fetch, path, page, limit, email):
    params = {'page': page, 'limit': limit, 'order': 'id,desc', 'quick_search': email}
    for index, (field, value) in enumerate((('site_id', str(SITE)), ('email', email))):
        params.update({f'search[{index}][field]': field, f'search[{index}][operator]': '=',
                       f'search[{index}][val]': value})
    try:
        payload = fetch(path, params)
    except Exception:
        raise OrderLookupError('Admin lookup is temporarily unavailable') from None
    if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload['code'] != 1:
        raise OrderLookupError('Admin did not confirm this lookup')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        raise OrderLookupError('Admin returned an invalid page')
    rows, total = data['list'], _decimal_int(data.get('total'))
    for row in rows:
        if (not isinstance(row, dict) or _decimal_int(row.get('site_id')) != SITE
                or str(row.get('email', '')).strip().lower() != email):
            raise OrderLookupError('Admin results do not match the submitted MMOEXP mailbox')
    return rows, total


def lookup_order_history(email, *, fetch=_fetch, now=None):
    """Reuse the Admin page's quick search, with exact site/email filtering.

    Quick search reaches older orders and draft orders. Their member IDs may
    establish identity without making those records count as paid purchases.
    """
    if not isinstance(email, str):
        raise OrderLookupError('Enter your MMOEXP account email')
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL.fullmatch(email):
        raise OrderLookupError('Enter your MMOEXP account email')
    now = datetime.now(SHANGHAI).replace(tzinfo=None) if now is None else now
    total = last_id = None
    paid = completed = seen = 0
    members = set()
    for page in range(1, MAX_PAGES + 1):
        rows, count = _page(fetch, ORDERS, page, PAGE_SIZE, email)
        if total is None:
            total = count
        if (count != total or total > PAGE_SIZE * MAX_PAGES
                or len(rows) != min(PAGE_SIZE, total - seen)):
            raise OrderLookupError('Admin order lookup returned incomplete or changing results')
        for row in rows:
            order_id = _decimal_int(row.get('id'))
            if order_id == 0 or (last_id is not None and order_id >= last_id):
                raise OrderLookupError('Admin order pages are out of sequence')
            last_id = order_id
            member_id = _decimal_int(row.get('uid'))
            if member_id:
                members.add(member_id)
            pay_state = _decimal_int(row.get('pay_status'))
            if pay_state in (0, 2):  # Unpaid, refunded.
                continue
            if pay_state != 1:
                raise OrderLookupError('Admin returned an unrecognized payment state')
            try:
                paid_at = datetime.strptime(row['paytime'], '%Y-%m-%d %H:%M:%S')
            except (KeyError, TypeError, ValueError):
                raise OrderLookupError('Admin could not establish payment time') from None
            if START <= paid_at <= now:
                paid += 1
                completed += _decimal_int(row.get('status')) == 101
        seen += len(rows)
        if seen == total:
            break
    if not members:
        rows, total = _page(fetch, MEMBERS, 1, 2, email)
        if total == 1 and len(rows) == 1:
            member_id = _decimal_int(rows[0].get('uid'))
            if member_id:
                members.add(member_id)
    if len(members) != 1:
        raise OrderLookupError('A unique MMOEXP member account could not be resolved')
    return OrderHistory(members.pop(), paid, completed)

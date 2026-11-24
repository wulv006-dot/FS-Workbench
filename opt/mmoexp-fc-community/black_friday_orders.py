"""Read only the submitted mailbox's MMOEXP order history from Admin."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from match_rewards_delivery import EMAIL


SITE = 266
SHANGHAI = timezone(timedelta(hours=8))
START = datetime(2026, 10, 1)
ORDERS = '/admin/order.Order/index'
ADMIN = 'http://127.0.0.1:8912'
PAGE_SIZE = 50
MAX_PAGES = 40
MAX_BYTES = 2 * 1024 * 1024


class OrderLookupError(RuntimeError):
    """Eligibility cannot be established from the available Admin data."""


@dataclass(frozen=True)
class OrderHistory:
    member_id: Optional[int]
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


def _page(fetch, page, email, period):
    params = {'page': page, 'limit': PAGE_SIZE, 'order': 'id,desc', 'quick_search': email}
    filters = (('site_id', '=', str(SITE)), ('email', '=', email), ('timestamp', 'RANGE', period))
    for index, (field, operator, value) in enumerate(filters):
        params.update({f'search[{index}][field]': field, f'search[{index}][operator]': operator,
                       f'search[{index}][val]': value})
    params['search[2][render]'] = 'datetime'
    try:
        payload = fetch(ORDERS, params)
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
    """Search the exact site's mailbox orders from the past calendar year.

    A matching order can supply a member ID for deduplication. A successful
    empty history is eligible for the new-customer reward without that ID.
    """
    if not isinstance(email, str):
        raise OrderLookupError('Enter your MMOEXP account email')
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL.fullmatch(email):
        raise OrderLookupError('Enter your MMOEXP account email')
    now = datetime.now(SHANGHAI) if now is None else now
    if now.tzinfo is not None:
        now = now.astimezone(SHANGHAI)
    now = now.replace(tzinfo=None, microsecond=0)
    # February 29 maps to February 28 in the previous year.
    day = 28 if (now.month, now.day) == (2, 29) else now.day
    since = now.replace(year=now.year - 1, day=day)
    start_epoch = int(since.replace(tzinfo=SHANGHAI).timestamp())
    end_epoch = int(now.replace(tzinfo=SHANGHAI).timestamp())
    period = f'{since:%Y-%m-%d %H:%M:%S},{now:%Y-%m-%d %H:%M:%S}'
    total = last_id = None
    paid = completed = seen = 0
    members = set()
    for page in range(1, MAX_PAGES + 1):
        rows, count = _page(fetch, page, email, period)
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
            if not start_epoch <= _decimal_int(row.get('timestamp')) <= end_epoch:
                raise OrderLookupError('Admin results fall outside the requested order window')
            member_id = _decimal_int(row.get('uid') or 0)
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
    member_id = members.pop() if len(members) == 1 else None
    return OrderHistory(member_id, paid, completed)

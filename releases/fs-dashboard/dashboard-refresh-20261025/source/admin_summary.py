"""Aggregate-only Admin reads through the existing ready session; never renew it."""
from datetime import datetime, timezone
import json
from supplement_fields import extract
from rs_admin import native_rows

ENDPOINT = '/admin/order.Order/orderStaticsDetailByEs'
GAMES = {'': '', '552': '', '456': '', '891': '',
         '1327': '', '1329': '', '1309': '', '927': '', '1307': '', '833': '',
         '506': '', '1333': '', '925': '', '589': '', '1367': '',
         '897': '', '859': ''}

def collect(request, game, start, end, *, country_code="", local_repeat=None):
    if str(game) not in GAMES:
        raise ValueError('invalid_game')
    for value in (start, end):
        if datetime.strptime(value, '%Y-%m-%d %H:%M').strftime('%Y-%m-%d %H:%M') != value:
            raise ValueError('invalid_period')
    if start >= end:
        raise ValueError('invalid_period')
    if country_code and (len(country_code)!=2 or not country_code.isascii() or not country_code.isalpha() or country_code!=country_code.upper()):
        raise ValueError('invalid_country_code')
    payload = {'order_status': GAMES[str(game)], 'pay_status': 1, 'game': game, 'site': '',
               'country_code': country_code, 'client': '', 'date': [start, end], 'pay_type': '',
               'time_unit': 1, 'cid': '', 'discount_code': '', 'product_type': ''}
    status, raw = request(ENDPOINT, data=payload)
    if status in (401, 403):
        raise PermissionError('admin_permission_denied')
    value = json.loads(raw)
    if status != 200 or value.get('code') != 1:
        raise OSError('admin_summary_unavailable')
    value = value.get('data')
    if isinstance(value, dict) and isinstance(value.get('data'), dict):
        value = value['data']
    if not isinstance(value, dict):
        raise ValueError('invalid_admin_summary')
    mapped = extract(value)
    period = {'start': start, 'end': end}
    try:
        rows = native_rows(value, period)
        labels_verified = True
    except ValueError:
        rows, labels_verified = [], False
    # Site ranks are aggregates. No customer/order records are returned or stored.
    from admin_scope import enrich
    result = {'system': 'admin.p2pah.cn', 'endpoint': ENDPOINT, 'status': 'available',
            'normalisedScope': 'all-websites', 'period': period, 'currency': 'USD',
            'rows': rows, 'seriesGranularity': 'day-or-hour' if labels_verified else 'upstream-undated', 'labelsVerified': labels_verified,
            'filters': payload, 'capturedAt': datetime.now(timezone.utc).isoformat(),
            'sourceDataAsOf': None, 'asOfStatus': 'not_provided_by_upstream',
            'newCustomers': mapped['metrics']['newCustomers']['value'], **mapped}

    return enrich(result, value, local_repeat)

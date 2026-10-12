"""Aggregate-only Admin reads through the existing ready session; never renew it."""
from datetime import datetime, timezone
import json
from supplement_fields import extract

ENDPOINT = '/admin/order.Order/orderStaticsDetailByEs'
GAMES = {'': '', '552': '101', '456': '101', '891': '101',
         '1327': '', '1329': '', '1309': '', '927': '', '1307': '', '833': '',
         '506': '', '1333': '', '925': '', '589': '101', '1367': '101',
         '897': '', '859': ''}

def collect(request, game, start, end):
    if str(game) not in GAMES:
        raise ValueError('invalid_game')
    for value in (start, end):
        if datetime.strptime(value, '%Y-%m-%d %H:%M').strftime('%Y-%m-%d %H:%M') != value:
            raise ValueError('invalid_period')
    if start >= end:
        raise ValueError('invalid_period')
    payload = {'order_status': GAMES[str(game)], 'pay_status': 1, 'game': game, 'site': '',
               'country_code': '', 'client': '', 'date': [start, end], 'pay_type': '',
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
    # Site ranks are aggregates. No customer/order records are returned or stored.
    return {'system': 'admin.p2pah.cn', 'endpoint': ENDPOINT, 'status': 'available',
            'normalisedScope': 'all-websites', 'period': {'start': start, 'end': end},
            'filters': payload, 'capturedAt': datetime.now(timezone.utc).isoformat(),
            'sourceDataAsOf': None, 'asOfStatus': 'not_provided_by_upstream',
            'newCustomers': mapped['metrics']['newCustomers']['value'], **mapped}

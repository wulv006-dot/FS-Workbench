"""Direct Admin API and existing isolated Order readers; no credential reads."""
import os, urllib.error, urllib.request
from urllib.parse import urlencode
from live_summary import SummaryCache

DC_PROXY = os.environ.get('FS_DC_PROXY_BASE', 'http://127.0.0.1:8912')


def dc_encode(payload):
    pairs = []
    for key, value in payload.items():
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                pairs.append(('%s[%d]' % (key, index), str(item)))
        else:
            pairs.append((key, str(value)))
    return urlencode(pairs)


def dc_request(endpoint, data=None, method='POST'):
    body = dc_encode(data).encode() if data else None
    request = urllib.request.Request(DC_PROXY + endpoint, data=body, method=method,
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=85) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()

def build(profiles, order_call, dimension_map, web):
    def admin(q):
        if q['profile']=='RS':
            from rs_admin import collect
            return collect(q)
        if q.get('admin_site')=='266':
            from site_summary import collect
            return collect(q, profiles[q['profile']])
        game = profiles[q['profile']][3]
        from admin_summary import collect as dc_collect
        return dc_collect(dc_request, str(game), q['period']['start'], q['period']['end'])

    def order(q):
        import fcntl
        row = profiles[q['profile']]
        with (web/'collector.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if q['profile']=='RS':
                from rs_shipping import collect
                return collect(q)
            result = order_call('fc27-cloud-browser', 'primary_reader.py',
                                [{'key': 'range', 'gid': row[2], 'status': '3' if row[4] == 'rpg' else '', **rs_order_filters(q), **q['period']}], 210)['range']
        result['dimensions'] = dimension_map(result)
        return result

    def shipping(q):
        import fcntl
        from business_shipping import collect
        with (web/'collector.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return collect(q)
    return SummaryCache(admin, order, profiles, shipping_read=shipping)


def rs_order_filters(q):
    if q['profile']!='RS': return {}
    from rs_admin import SERVERS, ORDER_TYPES, CATEGORIES
    return {'aid': str(SERVERS[q['rs_server']][0] or '0'), 'tid': ORDER_TYPES[q['rs_category']], 'rsScopeLabel':SERVERS[q['rs_server']][1]+' · '+CATEGORIES[q['rs_category']][1]}

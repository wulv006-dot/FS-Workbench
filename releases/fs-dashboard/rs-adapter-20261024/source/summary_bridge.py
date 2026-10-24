"""Adapters reuse the existing containers; no credential or raw customer reads."""
import json, subprocess
from urllib.parse import urlencode
from live_summary import SummaryCache

def build(profiles, order_call, dimension_map, web):
    def admin(q):
        if q['profile']=='RS':
            from rs_admin import collect
            return collect(q)
        game = profiles[q['profile']][3]
        query = urlencode({'game': game, **q['period']})
        program = ('import urllib.request,urllib.error,json\n'
                   'try:\n'
                   ' r=urllib.request.urlopen(' + repr('http://127.0.0.1:8767/business/summary?' + query) + ',timeout=85)\n'
                   ' print(json.dumps({"code":r.status,"body":json.load(r)}))\n'
                   'except urllib.error.HTTPError as e:\n print(json.dumps({"code":e.code}))\n')
        result = subprocess.run(['docker', 'exec', '-i', 'fc27-p2pah-session', 'python3', '-'],
                                input=program.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if result.returncode:
            raise OSError('admin_summary_transport')
        envelope = json.loads(result.stdout)
        if envelope['code'] in (401, 403):
            raise PermissionError('admin_summary_denied')
        if envelope['code'] != 200:
            raise OSError('admin_summary_unavailable')
        return envelope['body']

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

    return SummaryCache(admin, order, profiles)


def rs_order_filters(q):
    if q['profile']!='RS': return {}
    from rs_admin import SERVERS, ORDER_TYPES, CATEGORIES
    return {'aid': str(SERVERS[q['rs_server']][0] or '0'), 'tid': ORDER_TYPES[q['rs_category']], 'rsScopeLabel':SERVERS[q['rs_server']][1]+' · '+CATEGORIES[q['rs_category']][1]}

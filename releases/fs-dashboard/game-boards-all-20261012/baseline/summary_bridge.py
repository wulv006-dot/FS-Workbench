"""Adapters reuse the existing containers; no credential or raw customer reads."""
from datetime import datetime
import json, subprocess
from urllib.parse import urlencode
from live_summary import SummaryCache

def build(profiles, order_call, dimension_map, snapshot, web, timer_seconds):
    def admin(q):
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
        if timer_seconds() < 270:
            raise OSError('scheduled_collection_due')
        with (web/'collector.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = order_call('fc27-cloud-browser', 'primary_reader.py',
                                [{'key': 'range', 'gid': row[2], 'status': '3' if row[4] == 'rpg' else '', **q['period']}], 210)['range']
        result['dimensions'] = dimension_map(result)
        return result

    def fallback(q):
        old = snapshot()['profiles'].get(q['profile'])
        period = (old or {}).get('supplement', {}).get('period', {})
        # Only the same beginning and ending day; old dates never answer a new day.
        if period.get('start') != q['period']['start'] or not period.get('end'):
            return None
        end, wanted = period['end'], q['period']['end']
        if end > wanted or end[:10] != wanted[:10]:
            return None
        return old if old.get('supplement', {}).get('status') == 'available' else None

    return SummaryCache(admin, order, profiles, fallback)

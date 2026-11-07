"""Task-scoped Discord REST helper. Reads credentials only on the server."""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

APP = '1568239618111832094'
GUILD = '1041923524601851914'

def request(method, route, payload=None):
    token = next(line.split('=', 1)[1].strip().strip('"').strip("'")
                 for line in Path('/etc/mmoexp-fc-community.env').read_text().splitlines()
                 if line.startswith('DISCORD_BOT_TOKEN='))
    data = None if payload is None else json.dumps(payload).encode()
    for attempt in range(3):
        req = urllib.request.Request('https://discord.com/api/v10/' + route.lstrip('/'),
            data=data, method=method, headers={'Authorization': 'Bot ' + token,
            'Content-Type': 'application/json', 'User-Agent': 'MMOEXP-FC-Operations/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                delay = min(float(json.loads(exc.read()).get('retry_after', 2)), 30)
                time.sleep(delay)
                continue
            raise RuntimeError('Discord HTTP {}'.format(exc.code)) from None

def identity():
    me = request('GET', 'users/@me')
    if me.get('id') != APP or me.get('bot') is not True:
        raise RuntimeError('Unexpected bot identity')
    return me

if __name__ == '__main__':
    me = identity()
    roles = request('GET', 'guilds/' + GUILD + '/roles')
    member = request('GET', 'guilds/' + GUILD + '/members/' + APP)
    owned = [r for r in roles if r['id'] in member['roles'] or r['id'] == GUILD]
    permissions = 0
    for role in owned:
        permissions |= int(role['permissions'])
    channels = request('GET', 'guilds/' + GUILD + '/channels')
    print(json.dumps({'bot_id': me['id'], 'permissions': str(permissions),
        'roles': [{k:r[k] for k in ('id','name','position','permissions')} for r in owned],
        'fc_channels': [{k:c.get(k) for k in ('id','name','parent_id','type')} for c in channels
            if 'fc-' in c.get('name','').lower() or c.get('name') == 'EA FC - FIFA']}, ensure_ascii=False))

"""Create only the requested permissionless club roles and application-owned badge copies."""
import base64
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

spec = importlib.util.spec_from_file_location('ops', '/tmp/fc27-discord-ops-20261108.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
sys.path.insert(0, '/tmp/fc27-clubs-20261108')
from club_panel import CLUBS

# Public badge URLs observed on the reference role-assignment page, in the displayed order.
BADGES = '''1417998551677538367 1418002887782437060 1418003067403501631 1418003131500990644 1418412737343524965
1418004017799237752 1418003247670628382 1543021835262623915 1418003394957938771 1418003442714153020
1418003478000701652 1543021894259707964 1543022686681174086 1418004662065434816 1418004226403078274
1418003584817303692 1418003629599752285 1418003674332004464 1418404094254518303 1418003713611530322
1418003750995623996 1418004195021164795 1418003802535235635 1418003949931200542 1418003835645071361
1418001264717070578 1418001266155589796 1418001267552157746 1418001269859160115 1418408037374230649
1418001275663941837 1418001273331912824 1418001277589258250 1418001280449777714 1418408374319710410
1418001282295267499 1418001284765716614 1418001286975983616 1418001289320730715 1418408828768223342
1418001291300311144 1418001294152699985 1418001296728002733 1418409056149835788 1418001300733558884
1418001304063836210 1418001312494256220'''.split()
clubs = list(CLUBS['england']) + list(CLUBS['europe'])
assert len(clubs) == len(BADGES) == 47
root = Path('/opt/mmoexp-fc-community/assets/brand-20261108')
ops.identity()
roles = ops.request('GET', 'guilds/' + ops.GUILD + '/roles')
members = ops.request('GET', 'guilds/' + ops.GUILD + '/members/' + ops.APP)
mine = [r for r in roles if r['id'] in members['roles']]
if not any(int(r['permissions']) & (1 << 28) for r in mine):
    raise RuntimeError('Approved manage-role permission is not present')
snapshot = root / 'roles-before.json'
if not snapshot.exists():
    snapshot.write_text(json.dumps(roles))
role_map = {}
for slug, label in reversed(clubs):
    name = 'FC27 · ' + label
    matches = [r for r in roles if r['name'] == name]
    if len(matches) > 1 or (matches and (int(matches[0]['permissions']) or matches[0]['managed'])):
        raise RuntimeError('Conflicting club role')
    role = matches[0] if matches else ops.request('POST', 'guilds/' + ops.GUILD + '/roles',
        {'name': name, 'permissions': '0', 'hoist': False, 'mentionable': False, 'color': 3447003})
    role_map[slug] = int(role['id'])
matches = [r for r in roles if r['name'] == 'FC27']
if len(matches) > 1 or (matches and (int(matches[0]['permissions']) or matches[0]['managed'])):
    raise RuntimeError('Conflicting FC27 community role')
base = matches[0] if matches else ops.request('POST', 'guilds/' + ops.GUILD + '/roles',
    {'name': 'FC27', 'permissions': '0', 'hoist': True, 'mentionable': False, 'color': 3447003})
result = {'guild_id': int(ops.GUILD), 'channel_id': 1568663362567413820,
          'community_role_id': int(base['id']), 'role_ids': role_map, 'emoji_map': {}}
(root / 'club-config.json').write_text(json.dumps(result, indent=2))
emoji_result = ops.request('GET', 'applications/' + ops.APP + '/emojis')
existing = {e['name']: e for e in emoji_result['items']}
for (slug, label), badge in zip(clubs, BADGES):
    name = 'fc_' + slug
    emoji = existing.get(name)
    if not emoji:
        url = 'https://cdn.discordapp.com/emojis/' + badge + '.webp?size=44'
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20) as response:
            data = response.read(262145)
        if len(data) > 262144:
            raise RuntimeError('Badge too large')
        emoji = ops.request('POST', 'applications/' + ops.APP + '/emojis',
            {'name': name, 'image': 'data:image/webp;base64,' + base64.b64encode(data).decode()})
    result['emoji_map'][slug] = '<:{}:{}>'.format(emoji['name'], emoji['id'])
    (root / 'club-config.json').write_text(json.dumps(result, indent=2))
latest = ops.request('GET', 'guilds/' + ops.GUILD + '/roles')
ids = set(role_map.values()) | {int(base['id'])}
selected = [r for r in latest if int(r['id']) in ids]
if len(selected) != 48 or any(int(r['permissions']) for r in selected):
    raise RuntimeError('Role verification failed')
print(json.dumps({'club_roles': len(role_map), 'badges': len(result['emoji_map']),
    'community_role_id': base['id'], 'role_positions': [{k:r[k] for k in ('id','name','position','hoist')}
       for r in latest if int(r['id']) in ids or r['id'] in members['roles']]}))

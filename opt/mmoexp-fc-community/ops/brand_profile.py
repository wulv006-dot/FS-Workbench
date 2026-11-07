import base64
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location('ops', '/tmp/fc27-discord-ops-20261108.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
root = Path('/opt/mmoexp-fc-community/assets/brand-20261108')
before = ops.identity()
app_before = ops.request('GET', 'applications/@me')
backup = root / 'profile-before.json'
if not backup.exists():
    backup.write_text(json.dumps({'user': {k: before.get(k) for k in ('id','avatar','banner')},
        'application': {k: app_before.get(k) for k in ('id','icon','cover_image','description')}}, indent=2))
    os.chmod(str(backup), 0o600)
def image(name):
    return 'data:image/png;base64,' + base64.b64encode((root / name).read_bytes()).decode()
ops.request('PATCH', 'users/@me', {'avatar': image('avatar.png'), 'banner': image('banner.png')})
description = ('Your MMOEXP FC 27 companion. Daily FC news, curated community updates and private, '
    'live quotes for Coins, SBCs, Packs, Evolutions, Gallery and Boosting. '
    'Pick your football club and join the community. Real-time order tracking and member events are coming soon.')
ops.request('PATCH', 'applications/@me', {'description': description, 'icon': image('avatar.png')})
user = ops.identity()
app = ops.request('GET', 'applications/@me')
result = {'avatar_url': 'https://cdn.discordapp.com/avatars/' + ops.APP + '/' + user['avatar'] + '.png?size=256',
    'banner_url': 'https://cdn.discordapp.com/banners/' + ops.APP + '/' + user['banner'] + '.png?size=1024',
    'description': app['description'], 'application_icon_set': bool(app['icon'])}
(root / 'profile-result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))

"""Task-scoped welcome release. No customer data or notification sends."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/opt/mmoexp-fc-news-stage-20261108-core/community-ux')
sys.path[:0] = [str(STAGE), str(BASE), str(STAGE.parent)]
from deploy_news_center import atomic, run
import discord_ops as ops

FILES = ('club_panel.py', 'onboarding_panel.py', 'content_bot.py', 'alert_panel.py')
BEFORE = {'club_panel.py': '9d0f13c2d45e37fcfa0cb66cc6500e33ce3235c113ddfbed964fe41bb0a0675c',
          'content_bot.py': '1632607df5e4ac9f38ca2ea4c85cbaa4308a229fb724dfa3f90fa1aff457e873'}
GUILD = 1041923524601851914
WELCOME = 1568663362567413820
TEST_CHANNEL = 1568260661010497627
CHANNELS = [WELCOME, 1501757710381748254, 1568663210901504041, 1301379787696377926,
            1372781247847465000, 1568610224502345758, 1568610467587563591,
            1568610700463710278, 1041923524601851916]


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def verify_sources():
    manifest = json.loads((STAGE/'manifest.json').read_text())
    for name in FILES:
        if hashlib.sha256((STAGE/name).read_bytes()).hexdigest() != manifest[name]:
            raise RuntimeError('Candidate drift: ' + name)
    return manifest


async def preview():
    from club_panel import welcome_embed
    from onboarding_panel import WelcomeView, PopularClubView
    import discord
    config = json.loads((BASE/'content.config.json').read_text())
    clubs = dict(config['club_panels'], guild_id=1565922092518613064, channel_id=TEST_CHANNEL,
                 role_ids={}, community_role_id=None)
    result_path = STAGE/'preview.json'
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    cards = [('welcome', welcome_embed(config.get('quote_presentation')), WelcomeView(clubs)),
             ('popular', discord.Embed(title='⚽ Choose your club',
                 description='Pick your team. Your FC27 badge is included.', color=0xF28C28), PopularClubView(clubs))]
    for key, embed, view in cards:
        if result.get(key):
            if not isinstance(result[key], str) or not result[key].isdigit():
                raise RuntimeError('Preview needs reconciliation')
            continue
        for child in view.children:
            child.disabled = True
        result[key] = 'sending'; save(result_path, result)
        message = ops.request('POST', f'channels/{TEST_CHANNEL}/messages', {
            'content': 'FC27 welcome preview · controls disabled', 'embeds': [embed.to_dict()],
            'components': view.to_components(), 'allowed_mentions': {'parse': []}})
        result[key] = message['id']; save(result_path, result)
        read = ops.request('GET', f'channels/{TEST_CHANNEL}/messages/{message["id"]}')
        if read['author']['id'] != ops.APP or read['embeds'][0]['title'] != embed.title:
            raise RuntimeError('Preview readback failed')
    print(json.dumps({'preview': result}))


def roles():
    from alert_panel import ALERTS
    listed = ops.request('GET', f'guilds/{GUILD}/roles')
    member = ops.request('GET', f'guilds/{GUILD}/members/{ops.APP}')
    own = [r for r in listed if r['id'] in member['roles']]
    if not any(int(r['permissions']) & (1 << 28) for r in own):
        raise RuntimeError('Missing manage roles permission')
    receipt_path = STAGE/'roles.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    output = {}
    for key, (_, label) in ALERTS.items():
        name = 'FC27 Alerts · ' + label
        found = [r for r in listed if r['name'] == name]
        if len(found) > 1 or (found and (int(found[0]['permissions']) or found[0]['managed']
                                      or found[0]['hoist'] or found[0]['mentionable'])):
            raise RuntimeError('Unsafe/conflicting alert role')
        if found:
            role = found[0]
        else:
            if receipt.get(key):
                raise RuntimeError('Role create requires reconciliation')
            receipt[key] = {'status': 'sending', 'name': name}; save(receipt_path, receipt)
            role = ops.request('POST', f'guilds/{GUILD}/roles', {
                'name': name, 'permissions': '0', 'hoist': False, 'mentionable': False, 'color': 3447003})
        receipt[key] = {'status': 'confirmed', 'name': name, 'id': role['id']}; save(receipt_path, receipt)
        output[key] = int(role['id'])
    latest = ops.request('GET', f'guilds/{GUILD}/roles')
    own_latest = [r for r in latest if r['id'] in member['roles']]
    top = max(own_latest, key=lambda r: (r['position'], -int(r['id'])))
    for role in latest:
        if int(role['id']) in output.values() and (role['managed'] or int(role['permissions'])
                or (role['position'], -int(role['id'])) >= (top['position'], -int(top['id']))):
            raise RuntimeError('Alert role not safely below bot')
    return output


def release(manifest):
    from content_bot import validate_config
    receipt_path = STAGE/'deployment.json'
    if receipt_path.exists():
        raise RuntimeError('Deployment receipt exists; inspect instead of replaying')
    originals = {}
    for name in FILES:
        path = BASE/name
        data = path.read_bytes() if path.exists() else None
        if name in BEFORE and (data is None or hashlib.sha256(data).hexdigest() != BEFORE[name]):
            raise RuntimeError('Production drift: ' + name)
        if name not in BEFORE and data is not None:
            raise RuntimeError('Unexpected existing new file: ' + name)
        originals[name] = data
    cfgpath = BASE/'content.config.json'
    original_cfg = cfgpath.read_bytes()
    cfg = json.loads(original_cfg)
    if 'alert_preferences' in cfg:
        raise RuntimeError('Alerts already configured')
    if cfg['club_panels']['channel_id'] != WELCOME or cfg['club_panels']['guild_id'] != GUILD:
        raise RuntimeError('Welcome route drift')
    channels = ops.request('GET', f'guilds/{GUILD}/channels')
    if not set(CHANNELS) <= {int(c['id']) for c in channels}:
        raise RuntimeError('Missing configured channel')
    snapshot = STAGE/'channels-before.json'
    if not snapshot.exists():
        save(snapshot, [c for c in channels if int(c['id']) in CHANNELS])
    cfg['alert_preferences'] = {'guild_id': GUILD, 'channel_ids': CHANNELS, 'role_ids': roles()}
    validate_config(cfg)
    marker = BASE/'var/club-panels.json'
    original_marker = marker.read_bytes()
    saved = json.loads(original_marker)
    backup = BASE/'backups'/('community-ux-'+str(int(time.time())))
    backup.mkdir(mode=0o700)
    for name, data in originals.items():
        if data is not None:
            (backup/name).write_bytes(data)
    (backup/'content.config.json').write_bytes(original_cfg)
    (backup/'club-panels.json').write_bytes(original_marker)
    save(receipt_path, {'status': 'prepared', 'backup': str(backup), 'manifest': manifest})
    try:
        run('systemctl', 'stop', 'mmoexp-fc-community')
        if cfgpath.read_bytes() != original_cfg or marker.read_bytes() != original_marker:
            raise RuntimeError('Config or welcome marker drift')
        for name in FILES:
            atomic(BASE/name, (STAGE/name).read_bytes(), BASE/'club_panel.py')
        atomic(cfgpath, (json.dumps(cfg, indent=2, ensure_ascii=False)+'\n').encode())
        run('systemctl', 'start', 'mmoexp-fc-community')
        for _ in range(45):
            pid = int(run('systemctl', 'show', 'mmoexp-fc-community', '-p', 'MainPID').split('=')[1])
            ready = json.loads((BASE/'var/ready.json').read_text())
            if ready.get('pid') == pid and ready.get('connected') and ready.get('test_guild_present'):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Community did not become ready')
        expected = {'welcome': 'Welcome to the MMOEXP FC 27 Club', 'england': '⚽ Choose your club',
                    'europe': '🔔 Your updates'}
        verified = {}
        for _ in range(20):
            verified = {}
            for key, title in expected.items():
                message = ops.request('GET', f'channels/{WELCOME}/messages/{saved["messages"][key]}')
                if message['author']['id'] == ops.APP and message['embeds'][0]['title'] == title:
                    controls = [c for row in message.get('components', []) for c in row.get('components', [])]
                    if len(controls) == {'welcome': 4, 'england': 6, 'europe': 1}[key]:
                        verified[key] = str(message['id'])
            if len(verified) == 3:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Welcome message readback failed')
        if marker.read_bytes() != original_marker:
            raise RuntimeError('Welcome IDs changed')
    except Exception:
        run('systemctl', 'stop', 'mmoexp-fc-community')
        for name, data in originals.items():
            if data is None:
                (BASE/name).unlink(missing_ok=True)
            else:
                atomic(BASE/name, data)
        atomic(cfgpath, original_cfg)
        run('systemctl', 'start', 'mmoexp-fc-community')
        save(receipt_path, {'status': 'rolled_back', 'backup': str(backup)})
        raise
    result = {'status': 'ready', 'backup': str(backup), 'pid': pid, 'manifest': manifest,
              'messages': verified, 'alert_preferences': cfg['alert_preferences'],
              'welcome_ids_unchanged': True, 'real_notifications_sent': False}
    save(receipt_path, result)
    print(json.dumps(result))


if __name__ == '__main__':
    manifest = verify_sources()
    ops.identity()
    if sys.argv[1:] == ['preview']:
        asyncio.run(preview())
    elif sys.argv[1:] == ['release']:
        release(manifest)
    else:
        raise SystemExit('Use preview or release')

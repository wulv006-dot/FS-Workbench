"""Publish a disabled test preview or one recorded official game picker."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

APP = '1568239618111832094'
OFFICIAL = ('1041923524601851914', '1569198390107971795')
PREVIEW = ('1565922092518613064', '1568260661010497627')
MARKER = Path('/opt/mmoexp-fc-community/var/game-picker-panel.json')


def save_marker(path, data):
    fd, name = tempfile.mkstemp(prefix='.game-picker-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        if hasattr(os, 'chown'):
            owner = path.parent.stat()
            os.chown(name, owner.st_uid, owner.st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def controls(payload):
    return [button for row in payload.get('components', []) for button in row.get('components', [])]


def preflight_roles(config, request):
    from game_picker import ORDINARY_CHANNEL_PERMISSIONS
    guild = str(config['guild_id'])
    if guild != OFFICIAL[0]:
        raise ValueError('Unexpected official guild')
    roles = request('GET', 'guilds/' + guild + '/roles')
    member = request('GET', 'guilds/' + guild + '/members/' + APP)
    channels = request('GET', 'guilds/' + guild + '/channels')
    by_id = {str(role['id']): role for role in roles}
    owned = [role for role in roles if role['id'] == guild or role['id'] in member.get('roles', [])]
    if not owned:
        raise RuntimeError('Bot role metadata unavailable')
    permissions = 0
    for role in owned:
        permissions |= int(role['permissions'])
    if not permissions & ((1 << 28) | (1 << 3)):
        raise RuntimeError('Bot cannot manage roles')
    rank = lambda role: (int(role['position']), -int(role['id']))
    top = max(owned, key=rank)
    allowlist = {str(role) for game in config['games'] for role in game['role_ids']}
    channel_ids = {int(channel['id']) for channel in channels}
    if any(channel not in channel_ids for game in config['games'] for channel in game['channel_ids']):
        raise RuntimeError('Configured guide channel is unavailable')
    for role_id in allowlist:
        role = by_id.get(role_id)
        if (not role or role_id == guild or role.get('managed') is not False
                or int(role['permissions']) != 0 or rank(role) >= rank(top)):
            raise RuntimeError('Game role is unsafe or unavailable')
        for channel in channels:
            for overwrite in channel.get('permission_overwrites', []):
                if (overwrite.get('type') == 0 and overwrite.get('id') == role_id
                        and int(overwrite['allow']) & ~ORDINARY_CHANNEL_PERMISSIONS):
                    raise RuntimeError('Game role has unsafe channel permissions')
    return len(allowlist)


def verify_message(message, payload):
    expected = controls(payload)
    actual = controls(message)
    if (message.get('author', {}).get('id') != APP or len(actual) != 24
            or [button.get('custom_id') for button in actual] != [button.get('custom_id') for button in expected]
            or [bool(button.get('disabled', False)) for button in actual]
            != [bool(button.get('disabled', False)) for button in expected]
            or not message.get('embeds') or message['embeds'][0].get('title') != payload['embeds'][0].get('title')):
        raise RuntimeError('Published message readback mismatch; reconcile before retry')


def publish_panel(mode, payload, marker, request):
    if mode not in ('preview', 'official'):
        raise ValueError('Unsupported mode')
    guild, channel = PREVIEW if mode == 'preview' else OFFICIAL
    buttons = controls(payload)
    if (len(buttons) != 24 or len({b.get('custom_id') for b in buttons}) != 24
            or any(not str(b.get('custom_id', '')).startswith('mmoexp:game:') for b in buttons)
            or any(bool(b.get('disabled', False)) != (mode == 'preview') for b in buttons)
            or payload.get('allowed_mentions') != {'parse': []}):
        raise ValueError('Invalid picker payload')
    lock = marker.with_suffix('.lock')
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise RuntimeError('Publisher lock exists; reconcile before retry') from None
    try:
        me = request('GET', 'users/@me')
        target = request('GET', 'channels/' + channel)
        if (me.get('id') != APP or me.get('bot') is not True or target.get('id') != channel
                or target.get('guild_id') != guild or target.get('type') != 0):
            raise RuntimeError('Unexpected bot or destination')
        saved = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {'version': 1, 'panels': {}}
        if not isinstance(saved, dict) or saved.get('version') != 1 or not isinstance(saved.get('panels'), dict):
            raise RuntimeError('Invalid marker; reconcile before retry')
        key = guild + ':' + channel
        if key in saved['panels']:
            existing = saved['panels'][key]
            if (not isinstance(existing, dict) or existing.get('status') != 'published'
                    or not str(existing.get('message_id', '')).isdigit()
                    or int(existing['message_id']) <= 0):
                raise RuntimeError('Pending publication; reconcile before retry')
            message = request('GET', 'channels/' + channel + '/messages/' + str(existing['message_id']))
            verify_message(message, payload)
            return str(existing['message_id'])
        saved['panels'][key] = {'status': 'pending'}
        save_marker(marker, saved)
        message = request('POST', 'channels/' + channel + '/messages', payload)
        message_id = str(message.get('id', ''))
        if not message_id.isdigit() or int(message_id) <= 0:
            raise RuntimeError('Send response lacks message ID; reconcile before retry')
        saved['panels'][key] = {'status': 'published', 'message_id': message_id}
        save_marker(marker, saved)
        verify_message(request('GET', 'channels/' + channel + '/messages/' + message_id), payload)
        return message_id
    finally:
        lock.rmdir()


async def payload_for(config, preview):
    from game_picker import GamePickerView, game_picker_embed, validate_game_config
    validate_game_config(config)
    if (str(config['guild_id']), str(config['channel_id'])) != OFFICIAL:
        raise ValueError('Game picker config must target the approved official route')
    view = GamePickerView(config)
    if preview:
        for button in view.children:
            button.disabled = True
    return {'embeds': [game_picker_embed().to_dict()], 'components': view.to_components(),
            'allowed_mentions': {'parse': []}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('preview', 'official'))
    parser.add_argument('--config', required=True, help='Path to approved picker config JSON')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import discord_ops
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    config = config.get('game_picker', config)
    if args.mode == 'official':
        base = Path('/opt/mmoexp-fc-community')
        live = json.loads((base / 'content.config.json').read_text(encoding='utf-8'))
        if live.get('game_picker') != config:
            raise RuntimeError('Live picker configuration differs; refusing publication')
        pid = int(subprocess.run(['systemctl', 'show', 'mmoexp-fc-community', '-p', 'MainPID'],
                  check=True, stdout=subprocess.PIPE, text=True, timeout=10).stdout.split('=', 1)[1])
        ready = json.loads((base / 'var' / 'ready.json').read_text(encoding='utf-8'))
        if pid <= 0 or ready.get('pid') != pid or not ready.get('connected'):
            raise RuntimeError('Community service is not ready; refusing publication')
    payload = asyncio.run(payload_for(config, args.mode == 'preview'))
    preflight_roles(config, discord_ops.request)
    message = publish_panel(args.mode, payload, MARKER, discord_ops.request)
    guild, channel = PREVIEW if args.mode == 'preview' else OFFICIAL
    print(json.dumps({'mode': args.mode, 'guild_id': guild, 'channel_id': channel, 'message_id': message}))


if __name__ == '__main__':
    main()

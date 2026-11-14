"""Publish or edit one FC27 matchday card per approved Discord channel."""

import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

from matchday_card import render_card
from matchday_remote import fetch_latest


ROUTES = {
    'test': {'guild_id': 1565922092518613064, 'channel_id': 1568260661010497627,
             'discuss_channel_id': 1565922093525237953, 'players_channel_id': None},
    'official': {'guild_id': 1041923524601851914, 'channel_id': 1571043454136484082,
                 'discuss_channel_id': 1571043570268242014,
                 'players_channel_id': 1568878333087719454},
}
KEY_PATH = '/etc/mmoexp-fc-matchday/collector_ed25519'
KNOWN_HOSTS = '/etc/mmoexp-fc-matchday/known_hosts'
STATE_DIR = '/opt/fc27-matchday-discord-stage/var'
API = 'https://discord.com/api/v10'


def _atomic_state(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix='.matchday-', dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, separators=(',', ':'))
            stream.write('\n')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def discord_request(method, path, payload, token):
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    request = urllib.request.Request(API + path, data=body, method=method,
        headers={'Authorization': 'Bot ' + token, 'Content-Type': 'application/json',
                 'User-Agent': 'DiscordBot (https://www.mmoexp.com, 0.1)'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def publish(mode, snapshot, token, sender=discord_request, state_dir=STATE_DIR):
    if mode not in ROUTES:
        raise ValueError('Unknown matchday route')
    route = ROUTES[mode]
    card = render_card(snapshot, guild_id=route['guild_id'],
                       discuss_channel_id=route['discuss_channel_id'],
                       players_channel_id=route['players_channel_id'])
    digest = hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    state_path = os.path.join(state_dir, mode + '.json')
    if os.path.exists(state_path):
        with open(state_path, encoding='utf-8') as stream:
            state = json.load(stream)
    else:
        state = None
    if state:
        if state.get('channel_id') != route['channel_id'] or state.get('message_id') == 'pending':
            raise RuntimeError('Matchday card needs reconciliation')
        if state.get('digest') == digest:
            return {'result': 'unchanged', 'message_id': state['message_id']}
        message = sender('PATCH', '/channels/%s/messages/%s' %
                         (route['channel_id'], state['message_id']), card, token)
        state['digest'] = digest
        _atomic_state(state_path, state)
        return {'result': 'edited', 'message_id': message['id']}
    _atomic_state(state_path, {'channel_id': route['channel_id'], 'message_id': 'pending'})
    message = sender('POST', '/channels/%s/messages' % route['channel_id'], card, token)
    _atomic_state(state_path, {'channel_id': route['channel_id'],
                               'message_id': message['id'], 'digest': digest})
    return {'result': 'created', 'message_id': message['id']}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ROUTES:
        raise SystemExit('Use test or official')
    if os.environ.get('FC_ENABLE_LIVE') != '1':
        raise SystemExit('Live mode is disabled')
    token = os.environ['DISCORD_BOT_TOKEN']
    snapshot = fetch_latest(KEY_PATH, KNOWN_HOSTS)
    result = publish(sys.argv[1], snapshot, token)
    print(json.dumps({'mode': sys.argv[1], **result}))


if __name__ == '__main__':
    main()

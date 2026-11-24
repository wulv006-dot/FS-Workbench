"""Install the D4 acceptance card or publish/pause the official campaign card."""
import json
import sys
from pathlib import Path

from discord_ops import APP, identity, request

STATE = Path('/var/lib/fc27-black-friday-pilot')
CONFIG = Path('/etc/mmoexp-fc-black-friday.json')
D4 = '1565922092518613064'
D4_CHANNEL = '1568260661010497627'
OFFICIAL = '1041923524601851914'
FC_CATEGORY = '1194543013628756088'
TITLE = '🎰  FC27 Black Friday Mystery Drop'


def button(code, label, emoji, style=1):
    return {'type': 2, 'style': style, 'custom_id': code, 'label': label, 'emoji': {'name': emoji}}


def card(description, buttons):
    return {'embeds': [{'title': TITLE, 'color': 0xE4AF45, 'description': description}],
            'components': [{'type': 1, 'components': buttons}] if buttons else [],
            'allowed_mentions': {'parse': []}}


def verify(message, channel, expected_ids=None):
    if (message['author']['id'] != APP or message['channel_id'] != channel
            or not message['embeds'] or message['embeds'][0]['title'] != TITLE):
        raise RuntimeError('Unexpected Black Friday card')
    if expected_ids is not None:
        actual = [button['custom_id'] for row in message['components'] for button in row['components']]
        if actual != expected_ids:
            raise RuntimeError('Unexpected Black Friday buttons')
    return message['id']


def d4():
    channel = request('GET', 'channels/' + D4_CHANNEL)
    if channel['guild_id'] != D4 or channel['name'] != 'fc27-bot-test':
        raise RuntimeError('Wrong D4 channel')
    route = f"channels/{D4_CHANNEL}/messages/{(STATE / 'message.id').read_text().strip()}"
    verify(request('GET', route), D4_CHANNEL)
    payload = card('**D4 VIP acceptance test**\nTry all reward tiers or reopen the prior real receipt privately.',
                   [button('bf26:verify', 'Run acceptance cases', '🧪'),
                    button('bf26:verify:prior', 'Check prior real receipt', '🧾', 2)])
    request('PATCH', route, payload)
    return verify(request('GET', route), D4_CHANNEL, ['bf26:verify', 'bf26:verify:prior'])


def official(config, action):
    channel_id = str(config['channel_id'])
    channel = request('GET', 'channels/' + channel_id)
    if channel['guild_id'] != OFFICIAL or channel['parent_id'] != FC_CATEGORY or channel['type'] != 0:
        raise RuntimeError('Wrong official channel')
    route = f'channels/{channel_id}/messages'
    marker = STATE / 'official-message.id'
    pending = STATE / 'official-publish.pending'
    description = ('## ⚽  │  🎁  │  🏆\n**Three reels. One Mystery Drop.**\n\n'
                   '⚽ Pick your club in **FC27 Welcome**.\n'
                   '🎰 Tap **Spin the reels** and enter your MMOEXP account email.\n'
                   '🎟️ Watch the reels land to reveal your FC27 reward privately.\n\n'
                   '*Limited time · One spin per Discord account and MMOEXP member.*')
    receipt = button('bf26:receipt', 'Check my reward', '🧾', 2)
    buttons = [button('bf26:claim', 'Spin the reels', '🎰'), receipt]
    if action == 'close':
        config['enabled'] = False
        temporary = CONFIG.with_suffix('.next')
        temporary.write_text(json.dumps(config), encoding='utf-8')
        temporary.chmod(0o644)
        temporary.replace(CONFIG)
        description = 'This Black Friday drop has closed. Your claimed coupons remain valid until their own expiry.'
        buttons = [receipt]
    payload = card(description, buttons)
    if marker.is_file():
        message_id = marker.read_text().strip()
    elif action == 'close':
        raise RuntimeError('No official card has been published')
    elif pending.is_file():
        matches = [row for row in request('GET', route + '?limit=100')
                   if row.get('author', {}).get('id') == APP and row.get('embeds')
                   and row['embeds'][0].get('title') == TITLE]
        if len(matches) != 1:
            raise RuntimeError('Check the original Discord publish before retrying')
        message_id = verify(matches[0], channel_id)
    else:
        with pending.open('x') as out:
            out.write(channel_id)
        message_id = verify(request('POST', route, payload), channel_id)
    url = f'{route}/{message_id}'
    verify(request('GET', url), channel_id)
    request('PATCH', url, payload)
    ident = verify(request('GET', url), channel_id, [button['custom_id'] for button in buttons])
    temporary = marker.with_suffix('.next')
    temporary.write_text(ident)
    temporary.replace(marker)
    return ident


if __name__ == '__main__':
    identity()
    action = sys.argv[1]
    if action == 'd4':
        print(d4())
    elif action in ('publish', 'close'):
        settings = json.loads(CONFIG.read_text(encoding='utf-8'))
        if action == 'publish' and settings.get('enabled') is not True:
            raise RuntimeError('The campaign is closed')
        print(official(settings, action))
    else:
        raise SystemExit('Use d4, publish, or close')

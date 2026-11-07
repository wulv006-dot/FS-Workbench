"""Publish one multi-game introduction with a branded FC entry in start-here."""
import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/mmoexp-fc-news-stage-20261108-core')
from discord_ops import APP, GUILD, identity, request

CHANNEL = '1568693175877501192'
HOME = '1568663362567413820'
MARKER = Path('/opt/mmoexp-fc-community/var/general-fc-gateway.json')
GAMES = [('Diablo IV', '1232493719412801556'), ('Path of Exile', '1305793388599054400'),
         ('GTA', '1470604129834500261'), ('Madden / NFL', '1518795532598907041'),
         ('MLB', '1395564367713665054'), ('ARC Raiders', '1453656593081303133')]


def main():
    identity()
    channel = request('GET', 'channels/' + CHANNEL)
    if channel.get('guild_id') != GUILD or 'start-here' not in channel.get('name', ''):
        raise RuntimeError('Unexpected start-here channel')
    config = json.loads(Path('/opt/mmoexp-fc-community/content.config.json').read_text())
    brand = config.get('quote_presentation', {})
    embed = {'title': 'Your FUT club starts here.', 'color': 0xF28C28,
             'author': {'name': 'MMOEXP · FC27 Club'},
             'description': ('📰 **Daily updates** — news, SBCs, Evolutions & Objectives\n'
                             '💰 **Live prices** — coins, packs & more, privately\n'
                             '⚽ **Your club** — pick your team and choose your alerts'),
             'footer': {'text': 'Your game. Your club. Your community.'}}
    if brand.get('banner_url'):
        embed['image'] = {'url': brand['banner_url']}
    introduction = {'title': 'Welcome to MMOEXP', 'color': 0x3498DB,
                    'description': '**Choose your game**\nFind news, meet players and explore your community below.'}
    payload = {'embeds': [introduction, embed], 'allowed_mentions': {'parse': []},
               'components': [{'type': 1, 'components': [
                   {'type': 2, 'style': 5, 'label': 'Enter FC27 Club',
                    'emoji': {'name': '⚽'}, 'url': 'https://discord.com/channels/' + GUILD + '/' + HOME}]}]}
    for start in (0, 3):
        payload['components'].append({'type': 1, 'components': [
            {'type': 2, 'style': 5, 'label': name, 'url': 'https://discord.com/channels/' + GUILD + '/' + target}
            for name, target in GAMES[start:start + 3]]})
    if '--apply' not in sys.argv:
        print(json.dumps({'channel': channel['name'], 'payload': payload}))
        return
    if MARKER.exists():
        saved = json.loads(MARKER.read_text())
        if saved.get('channel_id') != CHANNEL:
            raise RuntimeError('Gateway marker belongs to another channel; reconcile before sending')
        if saved.get('status') != 'published':
            raise RuntimeError('Reconcile uncertain previous publication before retry')
        sent = request('GET', 'channels/' + CHANNEL + '/messages/' + saved['message_id'])
        if sent['author']['id'] != APP:
            raise RuntimeError('Wrong author')
        request('PATCH', 'channels/' + CHANNEL + '/messages/' + sent['id'], payload)
    else:
        MARKER.write_text(json.dumps({'status': 'sending', 'channel_id': CHANNEL}))
        sent = request('POST', 'channels/' + CHANNEL + '/messages', payload)
        MARKER.write_text(json.dumps({'status': 'published', 'channel_id': CHANNEL,
                                      'message_id': sent['id']}))
    verified = request('GET', 'channels/' + CHANNEL + '/messages/' + sent['id'])
    if (verified['author']['id'] != APP or len(verified.get('embeds', [])) != 2
            or verified['embeds'][0]['title'] != introduction['title']
            or verified['embeds'][1]['title'] != embed['title']
            or [[c['url'] for c in row['components']] for row in verified.get('components', [])]
            != [[c['url'] for c in row['components']] for row in payload['components']]):
        raise RuntimeError('Publication readback failed')
    print(json.dumps({'channel_id': CHANNEL, 'message_id': sent['id'], 'verified': True}))


if __name__ == '__main__':
    main()

"""Publish one branded FC entry in the authorized general welcome channel."""
import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/mmoexp-fc-news-stage-20261108-core')
from discord_ops import APP, GUILD, identity, request

CHANNEL = '1041923524601851916'
HOME = '1568663362567413820'
MARKER = Path('/opt/mmoexp-fc-community/var/general-fc-gateway.json')


def main():
    identity()
    channel = request('GET', 'channels/' + CHANNEL)
    if channel.get('guild_id') != GUILD or 'welcome' not in channel.get('name', ''):
        raise RuntimeError('Unexpected welcome channel')
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
    payload = {'embeds': [embed], 'allowed_mentions': {'parse': []},
               'components': [{'type': 1, 'components': [
                   {'type': 2, 'style': 5, 'label': 'Enter FC27 Club',
                    'emoji': {'name': '⚽'}, 'url': 'https://discord.com/channels/' + GUILD + '/' + HOME}]}]}
    if '--apply' not in sys.argv:
        print(json.dumps({'channel': channel['name'], 'payload': payload}))
        return
    if MARKER.exists():
        saved = json.loads(MARKER.read_text())
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
    if verified['author']['id'] != APP or verified['embeds'][0]['title'] != embed['title']:
        raise RuntimeError('Publication readback failed')
    print(json.dumps({'channel_id': CHANNEL, 'message_id': sent['id'], 'verified': True}))


if __name__ == '__main__':
    main()

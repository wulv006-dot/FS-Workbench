"""Local operator CLI for a DSH-assisted, test-guild-only Player batch."""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, parse_qs

from player_publish import PlayerPublishStore, TEST_GUILD, TEST_CHANNEL, EASYSBC_AUTHOR, _message
from quote_bridge import SocketProvider

ROOT = Path(__file__).resolve().parent
OPERATOR = 1237241595674361962


def discord_request(method, route, payload=None):
    sys.path.insert(0, str(ROOT/'ops'))
    from discord_ops import request
    return request(method, route, payload)


def record_receipt(store, batch_id, model_id, message_url, player_url, label, request=discord_request):
    message_id = _message(message_url)
    batch = store.get(batch_id)
    message = request('GET', f'/channels/{TEST_CHANNEL}/messages/{message_id}')
    if (message.get('id') != message_id or message.get('channel_id') != str(TEST_CHANNEL)
            or message.get('author', {}).get('id') != str(EASYSBC_AUTHOR)):
        raise ValueError('Not an EasySBC message in the test channel')
    sent_at = datetime.fromisoformat(message['timestamp'].replace('Z', '+00:00'))
    if sent_at < datetime.fromisoformat(batch['created_at']):
        raise ValueError('Receipt predates this batch')
    url = urlsplit(player_url)
    roles = parse_qs(url.query).get('player-role-id', [''])
    if len(roles) != 1:
        raise ValueError('Ambiguous player role')
    identity = dict(easysbc_id=url.path.rstrip('/').split('/')[-1], easysbc_role_id=roles[0],
                    easysbc_url=player_url, autocomplete_label=label)
    # The browser operator attests card identity; REST verifies author, destination and timestamp.
    return store.record(batch_id, model_id, message_url, identity, OPERATOR, EASYSBC_AUTHOR)


async def send_home(batch):
    from player_panel import PlayerHomeView
    from quote_panel import category_embed
    config = json.loads((ROOT/'content.config.json').read_text(encoding='utf-8'))
    panel = config['player_panel']
    if not panel['enabled'] or panel['guild_id'] != TEST_GUILD or panel['channel_id'] != TEST_CHANNEL:
        raise ValueError('Player interactions are not installed in the test destination')
    me = discord_request('GET', '/users/@me')
    if me.get('id') != '1568239618111832094' or me.get('bot') is not True:
        raise ValueError('Wrong application')
    channel = discord_request('GET', f'/channels/{TEST_CHANNEL}')
    if channel.get('guild_id') != str(TEST_GUILD):
        raise ValueError('Wrong destination')
    provider = SocketProvider('/run/mmoexp-fc-quotes/quotes.sock')
    view = PlayerHomeView(provider, {TEST_GUILD: {TEST_CHANNEL: 'players'}}, config.get('quote_presentation'))
    result = discord_request('POST', f'/channels/{TEST_CHANNEL}/messages', {
        'embeds': [category_embed('players', config.get('quote_presentation')).to_dict()],
        'components': view.to_components(), 'allowed_mentions': {'parse': []}})
    return f"https://discord.com/channels/{TEST_GUILD}/{TEST_CHANNEL}/{result['id']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('create')
    create.add_argument('--request-id', required=True, help='A UUID, reused for every retry of the same dispatch')
    for name in ('show', 'finalize'):
        sub.add_parser(name).add_argument('--batch-id', required=True)
    record = sub.add_parser('record')
    for option in ('batch-id', 'message-url', 'player-url', 'selected-label'):
        record.add_argument('--'+option, required=True)
    record.add_argument('--model-id', type=int, required=True)
    args = parser.parse_args()
    store = PlayerPublishStore(ROOT/'var/player-publish')
    if args.action == 'create':
        try:
            result = store.get(args.request_id)
        except FileNotFoundError:
            result = None
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        cfg = json.loads((ROOT/'content.config.json').read_text(encoding='utf-8'))['player_panel']
        if not cfg['enabled'] or cfg['guild_id'] != TEST_GUILD or cfg['channel_id'] != TEST_CHANNEL:
            raise ValueError('Enable the fixed test Player route before creating a batch')
        provider = SocketProvider('/run/mmoexp-fc-quotes/quotes.sock')
        cards = provider.player_manage_selection()
        titles = {c['model_id']: c['title'] for c in cards if c.get('model_available')}
        result = store.create(cfg, args.request_id, lambda mid: titles[mid],
                              lambda mid: provider.player_manage_match(str(mid)))
    elif args.action == 'show':
        result = store.get(args.batch_id)
    elif args.action == 'record':
        result = record_receipt(store, args.batch_id, args.model_id, args.message_url,
                                args.player_url, args.selected_label)
    else:
        result = store.finalize(args.batch_id, lambda batch: asyncio.run(send_home(batch)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

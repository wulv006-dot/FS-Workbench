"""Server-only polish preparation and explicitly requested REST previews; no Gateway."""
import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import struct
import sys
import time
import urllib.request

APP = '1568239618111832094'
TEST_GUILD = '1565922092518613064'
TEST_CHANNEL = '1568260661010497627'
OFFICIAL_GUILD = 1041923524601851914
ICON_KEYS = {'sbc', 'packs', 'gallery', 'evolutions', 'boosting', 'coins',
             'clock', 'search', 'external', 'platform'}


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def png_size(data):
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('Invalid PNG')
    return struct.unpack('>II', data[16:24])


def load_ops():
    spec = importlib.util.spec_from_file_location('fc_polish_ops', '/tmp/fc27-discord-ops-20261108.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.identity()['id'] != APP:
        raise ValueError('Wrong application identity')
    return module


def prepare_icons(stage, ops):
    assets = stage / 'assets/easysbc-reference-20261108'
    proposal = json.loads((assets / 'proposal.json').read_text())['icons']
    if len(proposal) != 10 or {item['key'] for item in proposal} != ICON_KEYS:
        raise ValueError('Expected ten exact icons')
    receipt_path = stage / 'receipts/application-icons.json'
    receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    listed = ops.request('GET', 'applications/' + APP + '/emojis')['items']
    mapping = {}
    for item in proposal:
        key, name = item['key'], item['emoji_name']
        if name != 'fcq_' + key or item['file'] != 'quote-icons/' + key + '.png':
            raise ValueError('Unexpected icon name/path')
        raw = (assets / item['file']).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if (digest != item['sha256'] or len(raw) != item['bytes'] or len(raw) > 256 * 1024
                or png_size(raw) != (128, 128)):
            raise ValueError('Source PNG verification failed: ' + key)
        matches = [emoji for emoji in listed if emoji['name'] == name]
        if len(matches) > 1:
            raise ValueError('Ambiguous application emoji: ' + name)
        prior = receipts.get(key)
        if prior and prior['source_sha256'] != digest:
            raise ValueError('Icon source differs from prior upload: ' + key)
        if matches:
            emoji = matches[0]
            if prior and prior.get('id') and prior['id'] != emoji['id']:
                raise ValueError('Application emoji identity drift: ' + key)
        else:
            if prior and prior.get('status') in ('sending', 'uncertain'):
                raise ValueError('Prior emoji upload needs reconciliation: ' + key)
            receipts[key] = {'name': name, 'source_sha256': digest, 'status': 'sending'}
            save(receipt_path, receipts)
            try:
                emoji = ops.request('POST', 'applications/' + APP + '/emojis',
                    {'name': name, 'image': 'data:image/png;base64,' + base64.b64encode(raw).decode()})
            except Exception as error:
                receipts[key]['status'] = 'uncertain'
                receipts[key]['error_code'] = type(error).__name__
                save(receipt_path, receipts)
                raise
            listed.append(emoji)
        if emoji.get('name') != name or not emoji.get('id') or emoji.get('animated'):
            raise ValueError('Unexpected uploaded emoji')
        url = 'https://cdn.discordapp.com/emojis/' + emoji['id'] + '.png?size=128&quality=lossless'
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            rendered = response.read(256 * 1024 + 1)
        if png_size(rendered) != (128, 128) or len(rendered) > 256 * 1024:
            raise ValueError('Uploaded emoji image verification failed')
        cdn_hash = hashlib.sha256(rendered).hexdigest()
        if matches and not prior and cdn_hash != digest:
            raise ValueError('Unrecorded existing emoji image differs: ' + key)
        receipts[key] = {'name': name, 'id': emoji['id'], 'source_sha256': digest,
                         'source_bytes': len(raw), 'cdn_sha256': cdn_hash,
                         'cdn_bytes': len(rendered), 'dimensions': [128, 128], 'status': 'verified'}
        save(receipt_path, receipts)
        mapping[key] = '<:' + name + ':' + emoji['id'] + '>'
    save(stage / 'presentation-icons.json', {'icons': mapping})
    return mapping


def candidate_config(stage, mapping):
    from content_bot import validate_config
    config = json.loads((stage / 'production-baseline/content.config.json').read_text())
    if config['news_publish']['poll_seconds'] != 21600:
        raise ValueError('Existing six-hour news schedule changed')
    config.setdefault('quote_presentation', {})['icons'] = mapping
    validate_config(config)
    save(stage / 'candidate.config.json', config)
    return config


def publish_once(stage, ops, key, payload):
    ledger_path = stage / 'receipts/test-previews.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    payload['allowed_mentions'] = {'parse': []}
    payload['content'] = ('TEST PREVIEW — sample price layout (not a private response)'
                          if key == 'coins_100k_ps_quote' else 'TEST PREVIEW — ' + key.replace('_', ' '))
    if key in ledger:
        if ledger[key]['status'] != 'published':
            raise ValueError('Preview attempt needs reconciliation: ' + key)
        route = 'channels/' + TEST_CHANNEL + '/messages/' + ledger[key]['message_id']
        previous = ops.request('GET', route)
        if previous.get('author', {}).get('id') != APP or previous.get('channel_id') != TEST_CHANNEL:
            raise ValueError('Existing preview identity differs')
        ops.request('PATCH', route, payload)
        ledger[key]['updated_at'] = int(time.time())
        save(ledger_path, ledger)
        return ledger[key]['message_id']
    ledger[key] = {'status': 'sending', 'attempted_at': int(time.time()), 'channel_id': TEST_CHANNEL}
    save(ledger_path, ledger)
    try:
        message = ops.request('POST', 'channels/' + TEST_CHANNEL + '/messages', payload)
        if message.get('author', {}).get('id') != APP or message.get('channel_id') != TEST_CHANNEL:
            raise ValueError('Preview acknowledgement identity mismatch')
    except Exception as error:
        ledger[key].update(status='uncertain', error_code=type(error).__name__)
        save(ledger_path, ledger)
        raise
    ledger[key].update(status='published', message_id=message['id'])
    save(ledger_path, ledger)
    return message['id']


async def previews(stage, ops, config):
    from club_panel import ClubPanelView, welcome_embed, club_embed
    from quote_panel import (CategoryHomeView, category_embed, QuoteView, panel_embed,
                             fetch_quote, entries)
    from quote_bridge import SocketProvider
    channel = ops.request('GET', 'channels/' + TEST_CHANNEL)
    if channel.get('guild_id') != TEST_GUILD or channel.get('type') != 0:
        raise ValueError('Preview channel is not the designated test channel')
    presentation = config['quote_presentation']
    provider = SocketProvider(config['quote_socket'])
    for kind in ('sbc', 'packs', 'gallery', 'evolutions', 'boosting', 'coins'):
        view = CategoryHomeView(provider, kind, allowed_routes={int(TEST_GUILD): {int(TEST_CHANNEL): kind}}, presentation=presentation)
        publish_once(stage, ops, 'category_' + kind,
            {'embeds': [category_embed(kind, presentation).to_dict()], 'components': view.to_components()})
    clubs = config['club_panels']
    for key in ('welcome', 'england', 'europe'):
        embed = welcome_embed(presentation, OFFICIAL_GUILD) if key == 'welcome' else club_embed(key, presentation)
        components = []
        if key != 'welcome':
            view = ClubPanelView(clubs['guild_id'], clubs['channel_id'], key,
                clubs['role_ids'], clubs['emoji_map'], community_role_id=clubs.get('community_role_id'))
            for child in view.children:
                child.disabled = True
            components = view.to_components()
            if not all(child.get('disabled') is True for row in components for child in row['components']):
                raise ValueError('Welcome preview buttons must be disabled')
        publish_once(stage, ops, 'welcome_' + key, {'embeds': [embed.to_dict()], 'components': components})
    products = entries(provider.catalog('coins'))
    product = 'coins:100'
    if product not in products:
        raise ValueError('Exact 100K Coins SKU unavailable; do not substitute')
    quote = fetch_quote(provider, product, 'PlayStation 5', 'coins')
    view = QuoteView(provider, 1237241595674361962, 'coins', products, product=product,
        platform='PlayStation 5', quote=quote,
        allowed_routes={int(TEST_GUILD): {int(TEST_CHANNEL): 'coins'}}, presentation=presentation)
    for child in view.children:
        if not getattr(child, 'url', None):
            child.disabled = True
    publish_once(stage, ops, 'coins_100k_ps_quote', {'embeds': [panel_embed(view).to_dict()], 'components': view.to_components()})
    save(stage / 'receipts/quote-example.json', {'product_id': product, 'platform': quote['option_label'],
        'amount': quote['amount'], 'currency': quote['currency'], 'source_url': quote['url'],
        'queried_at': quote['queried_at'], 'read_only_socket': True, 'customer_data': False})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--action', required=True, choices=('icons', 'previews'))
    args = parser.parse_args()
    stage = Path(args.stage).resolve()
    if not str(stage).startswith('/opt/mmoexp-fc-stage-20261108-polish-') or not (stage / 'production-baseline').is_dir():
        raise SystemExit('Unexpected stage directory')
    sys.path.insert(0, str(stage / 'mmoexp-fc-pilot'))
    ops = load_ops()
    if args.action == 'icons':
        mapping = prepare_icons(stage, ops)
        candidate_config(stage, mapping)
        print(json.dumps({'icons_verified': len(mapping), 'news_poll_seconds': 21600, 'production_config_changed': False}))
    else:
        if (stage / 'receipts/preview-paused.txt').exists():
            raise SystemExit('Preview is paused by current task instructions.')
        config = json.loads((stage / 'candidate.config.json').read_text())
        asyncio.run(previews(stage, ops, config))
        ledger = json.loads((stage / 'receipts/test-previews.json').read_text())
        print(json.dumps({'preview_messages': ledger, 'gateway_started': False, 'production_changed': False}))


if __name__ == '__main__':
    main()

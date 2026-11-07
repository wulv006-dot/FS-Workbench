import asyncio
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('ops', '/tmp/fc27-discord-ops-20261108.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
sys.path.insert(0, '/opt/mmoexp-fc-community')
from quote_panel import CategoryHomeView, category_embed

async def main():
    ops.identity()
    config = json.loads(Path('/opt/mmoexp-fc-community/content.config.json').read_text())
    cards = [('sbc', '1301379787696377926', '1568645119320522927'),
             ('packs', '1568610700463710278', '1568645120226492558'),
             ('gallery', '1568610467587563591', '1568645120931143682')]
    for kind, channel, message in cards:
        route = 'channels/' + channel + '/messages/' + message
        before = ops.request('GET', route)
        if before['author']['id'] != ops.APP or before['channel_id'] != channel:
            raise RuntimeError('Unexpected message owner')
        presentation = config.get('quote_presentation')
        view = CategoryHomeView(None, kind, presentation=presentation)
        ops.request('PATCH', route, {'embeds': [category_embed(kind, presentation).to_dict()],
            'components': view.to_components(), 'allowed_mentions': {'parse': []}})
        print('Refreshed ' + kind)

asyncio.run(main())

"""Offline restoration check. Pass the downloaded paused order source path.

PYTHONPATH must include the existing order dependencies and community modules.
No Discord connection or real member messages are made.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import AsyncMock

from restore_fcvip6_20261115 import candidates, TEXT
from chat_panel import SurpriseDrop


async def check(paused):
    before = {'chat_bot': {'surprise': {'enabled': False, 'codes': ['FCVIP6'],
        'texts': ['Limited'], 'trigger': '!drop', 'daily_limit': 3, 'cooldown_seconds': 600}},
        'unrelated': {'keep': True}}
    original = {'order_panel.py': Path(paused).read_bytes(),
        'chat_service.py': b"description=text or 'Limited discount code'\ntext='Limited quantity, final price at checkout'\n",
        'content.chat.config.json': json.dumps(before).encode()}
    after = candidates(original)
    cfg = json.loads(after['content.chat.config.json'])
    assert cfg['unrelated'] == before['unrelated']
    assert cfg['chat_bot']['surprise']['daily_limit'] == 3
    assert cfg['chat_bot']['surprise']['cooldown_seconds'] == 600
    drop = SurpriseDrop(cfg['chat_bot'], ['123'])
    assert drop.is_staff(123) and not drop.is_staff(456)
    assert drop.draw() == ('FCVIP6', TEXT)
    panel = types.ModuleType('restored_order_panel')
    exec(compile(after['order_panel.py'], 'order_panel.py', 'exec'), panel.__dict__)
    with tempfile.TemporaryDirectory() as temp:
        store = panel.InteractionStore(Path(temp) / 'interactions.sqlite3')
        config = {'guild_id': 1041923524601851914, 'channel_id': 1570789310813442080,
                  'socket': '/run/fc-order/order.sock'}
        service = types.SimpleNamespace(store=store)
        view = panel.OrderPanelView(config, service)
        assert not view.reward.disabled and not view.lookup.disabled
        assert 'temporarily paused' not in panel.panel_embed(0).description
        assert '6%' in panel.panel_embed(0).description
        marker = dict(config)
        marker.pop('socket')
        marker['message_id'] = 100
        (Path(temp) / 'order-panel.json').write_text(json.dumps(marker))
        client = types.SimpleNamespace(order_panel=view,
            store=types.SimpleNamespace(path=Path(temp) / 'state.sqlite3'))
        member = types.SimpleNamespace(id=123, bot=False, send=AsyncMock())
        payload = types.SimpleNamespace(**marker, member=member, user_id=123, emoji='👍')
        await panel.handle_reaction(client, payload)
        await panel.handle_reaction(client, payload)
        assert member.send.await_count == 1
        assert store.eligible(config['guild_id'], 123)
        interaction = types.SimpleNamespace(guild_id=config['guild_id'],
            user=member, response=types.SimpleNamespace(defer=AsyncMock()),
            followup=types.SimpleNamespace(send=AsyncMock()))
        await view.reward.callback(interaction)
        assert interaction.followup.send.await_args.args[0] == panel.COUPON
        interaction.user = types.SimpleNamespace(id=456)
        await view.reward.callback(interaction)
        assert 'React with' in interaction.followup.send.await_args.args[0]
    print('PASS: button, first-reaction DM, no duplicate DM, eligibility gate, accurate copy, surprise limits/staff')


if __name__ == '__main__':
    asyncio.run(check(sys.argv[1]))

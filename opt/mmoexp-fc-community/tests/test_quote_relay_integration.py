import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from community import CommunityStore
from content_bot import ContentClient, TEST_GUILD, OFFICIAL_GUILD, validate_config


class RelayIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.channel_id = 1568610700463710278
        self.config = {'guild_id': TEST_GUILD, 'staff_user_ids': [],
            'quote_channel_id': 1568260661010497627, 'quote_socket': '/unused',
            'quote_relay': {'guild_id': OFFICIAL_GUILD, 'channels': {str(self.channel_id): 'packs'}}}
        self.client = ContentClient(self.config, CommunityStore(Path(self.temp.name)/'db.sqlite3', []))
        self.addAsyncCleanup(self.client.close)
        self.channel = SimpleNamespace(id=self.channel_id, guild=SimpleNamespace(id=OFFICIAL_GUILD),
                                       send=AsyncMock())
        self.client.get_channel = MagicMock(return_value=self.channel)

    def event(self):
        return SimpleNamespace(id=1568616943907250267, channel=self.channel,
            guild=self.channel.guild, author=SimpleNamespace(id=1167033335256731658, bot=True),
            type=0, created_at=datetime.fromtimestamp(1000, timezone.utc), webhook_id=None,
            interaction_metadata=None, interaction=None)

    async def test_actual_sender_path_sends_once_without_mentions_and_enforces_routes(self):
        self.assertTrue(self.client.quote_relay.accept(self.event(), 1000))
        await self.client.flush_quote_relay()
        await self.client.flush_quote_relay()
        self.channel.send.assert_awaited_once()
        kwargs = self.channel.send.await_args.kwargs
        self.assertFalse(kwargs['allowed_mentions'].everyone)
        view = kwargs['view']
        self.assertEqual(view.kind, 'packs')
        self.assertEqual(view.allowed_routes[OFFICIAL_GUILD], {self.channel_id: 'packs'})
        self.assertFalse(self.client.intents.message_content)

    async def test_wrong_resolved_guild_never_sends(self):
        self.client.quote_relay.accept(self.event(), 1000)
        self.channel.guild.id = TEST_GUILD
        await self.client.flush_quote_relay()
        self.channel.send.assert_not_awaited()

    async def test_uncertain_send_is_not_retried(self):
        self.client.quote_relay.accept(self.event(), 1000)
        self.channel.send.side_effect = RuntimeError('ambiguous transport')
        await self.client.flush_quote_relay()
        await self.client.flush_quote_relay()
        self.channel.send.assert_awaited_once()

    def test_unimplemented_categories_and_other_guilds_rejected(self):
        for relay in ({'guild_id': 999, 'channels': {str(self.channel_id): 'packs'}},
                      {'guild_id': OFFICIAL_GUILD, 'channels': {str(self.channel_id): 'coins'}}):
            with self.assertRaises(ValueError):
                validate_config(dict(self.config, quote_relay=relay))

    def test_extended_config_accepts_five_relay_routes_and_one_static_coins(self):
        routes = {str(1568610700463710200 + n): kind for n, kind in enumerate(
            ('sbc', 'packs', 'gallery', 'evolutions', 'boosting'))}
        static = {'guild_id': OFFICIAL_GUILD, 'channels': {'1568610700463710290': 'coins'}}
        config = dict(self.config, quote_relay={'guild_id': OFFICIAL_GUILD, 'channels': routes}, quote_static=static)
        self.assertEqual(validate_config(config), config)
        for invalid in (
            {'guild_id': 999, 'channels': {'1568610700463710290': 'coins'}},
            {'guild_id': OFFICIAL_GUILD, 'channels': {}},
            {'guild_id': OFFICIAL_GUILD, 'channels': {'1568610700463710290': 'packs'}},
            {'guild_id': OFFICIAL_GUILD, 'channels': {'1568610700463710200': 'coins'}},
            {'guild_id': OFFICIAL_GUILD, 'channels': {'1568610700463710290': 'coins',
                                                      '1568610700463710291': 'coins'}},
            {'guild_id': OFFICIAL_GUILD, 'channels': {'1568610700463710290': 'coins'}, 'extra': True},
        ):
            with self.subTest(static=invalid), self.assertRaises(ValueError):
                validate_config(dict(config, quote_static=invalid))
        with self.assertRaises(ValueError):
            validate_config(dict(config, quote_socket='', quote_static=static))

    async def test_static_coins_card_is_reused_and_routes_are_precise(self):
        channel_id = 1568610700463710290
        self.client.config['quote_static'] = {'guild_id': OFFICIAL_GUILD, 'channels': {str(channel_id): 'coins'}}
        card = SimpleNamespace(id=12345, edit=AsyncMock())
        channel = SimpleNamespace(id=channel_id, guild=SimpleNamespace(id=OFFICIAL_GUILD),
                                  send=AsyncMock(return_value=card), get_partial_message=MagicMock(return_value=card))
        self.client.get_channel = MagicMock(return_value=channel)
        await self.client.setup_quote_static_panel()
        await self.client.setup_quote_static_panel()
        channel.send.assert_awaited_once()
        card.edit.assert_awaited_once()
        view = channel.send.await_args.kwargs['view']
        self.assertEqual(view.kind, 'coins')
        self.assertEqual(view.allowed_routes[OFFICIAL_GUILD][channel_id], 'coins')
        self.assertEqual(view.allowed_routes[OFFICIAL_GUILD][self.channel_id], 'packs')
        self.assertFalse(channel.send.await_args.kwargs['allowed_mentions'].everyone)

    async def test_static_uncertain_send_and_wrong_resolved_channel_never_republish(self):
        channel_id = 1568610700463710290
        self.client.config['quote_static'] = {'guild_id': OFFICIAL_GUILD, 'channels': {str(channel_id): 'coins'}}
        channel = SimpleNamespace(id=channel_id, guild=SimpleNamespace(id=OFFICIAL_GUILD),
                                  send=AsyncMock(side_effect=RuntimeError('ambiguous send')))
        self.client.get_channel = MagicMock(return_value=channel)
        await self.client.setup_quote_static_panel()
        await self.client.setup_quote_static_panel()
        channel.send.assert_awaited_once()
        marker = Path(self.temp.name) / 'quote-static-panel.json'
        self.assertEqual(__import__('json').loads(marker.read_text())['message_id'], 'pending')
        marker.unlink()
        channel.id += 1
        await self.client.setup_quote_static_panel()
        channel.send.assert_awaited_once()
        self.assertFalse(marker.exists())

    async def test_static_marker_from_another_channel_requires_reconciliation(self):
        import json
        channel_id = 1568610700463710290
        self.client.config['quote_static'] = {'guild_id': OFFICIAL_GUILD, 'channels': {str(channel_id): 'coins'}}
        channel = SimpleNamespace(id=channel_id, guild=SimpleNamespace(id=OFFICIAL_GUILD), send=AsyncMock(),
                                  get_partial_message=MagicMock())
        self.client.get_channel = MagicMock(return_value=channel)
        marker = Path(self.temp.name) / 'quote-static-panel.json'
        marker.write_text(json.dumps({'guild_id': OFFICIAL_GUILD, 'channel_id': channel_id + 1, 'message_id': 12345}))
        await self.client.setup_quote_static_panel()
        channel.send.assert_not_awaited()
        channel.get_partial_message.assert_not_called()

    def test_static_cannot_duplicate_test_panel_channel(self):
        config = dict(self.config,
            quote_static={'guild_id': TEST_GUILD, 'channels': {str(self.config['quote_channel_id']): 'coins'}})
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_all_test_panel_categories_remain_available_when_relay_uses_same_test_channel(self):
        test_channel = str(self.config['quote_channel_id'])
        self.client.config['quote_relay'] = {'guild_id': TEST_GUILD, 'channels': {test_channel: 'sbc'}}
        for kind in ('sbc', 'packs', 'gallery', 'evolutions', 'boosting', 'coins'):
            self.assertEqual(self.client.quote_routes(kind)[TEST_GUILD][int(test_channel)], kind)

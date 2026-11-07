import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from community import CommunityStore
from content_bot import ContentClient, TEST_GUILD


class QuoteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        store = CommunityStore(self.path / 'data.db', [])
        config = {'guild_id': TEST_GUILD, 'staff_user_ids': [], 'quote_channel_id': 123,
                  'quote_socket': '/run/mmoexp-fc-quotes/quotes.sock'}
        self.client = ContentClient(config, store)
        self.addAsyncCleanup(self.client.close)
        self.messages = {n: SimpleNamespace(edit=AsyncMock()) for n in (101, 102, 103, 104, 105, 106, 456)}
        self.channel = SimpleNamespace(guild=SimpleNamespace(id=TEST_GUILD),
            send=AsyncMock(side_effect=[SimpleNamespace(id=n) for n in (101, 102, 103, 104, 105, 106)]),
            get_partial_message=MagicMock(side_effect=lambda n: self.messages[n]))
        self.client.get_channel = MagicMock(return_value=self.channel)

    async def test_six_cards_are_reused_and_old_card_is_retired(self):
        (self.path / 'quote-panel.json').write_text(json.dumps({'message_id': 456}))
        with patch('quote_panel.CategoryHomeView', create=True, side_effect=lambda p, kind, **kwargs: kind), \
             patch('quote_panel.category_embed', create=True, side_effect=lambda kind, presentation=None: kind):
            await self.client.setup_quote_panel()
            await self.client.setup_quote_panel()
        self.assertEqual(self.channel.send.await_count, 6)
        self.assertEqual([c.kwargs['view'] for c in self.channel.send.await_args_list],
                         ['sbc', 'packs', 'gallery', 'evolutions', 'boosting', 'coins'])
        self.assertEqual(json.loads((self.path / 'quote-panels-v2.json').read_text()),
                         {'sbc': 101, 'packs': 102, 'gallery': 103, 'evolutions': 104, 'boosting': 105, 'coins': 106})
        for n in (101, 102, 103, 104, 105, 106):
            self.messages[n].edit.assert_awaited_once()
        self.assertIsNone(self.messages[456].edit.await_args.kwargs['view'])

    async def test_wrong_guild_does_not_publish(self):
        self.channel.guild.id = 1041923524601851914
        with patch('quote_panel.CategoryHomeView', create=True), patch('quote_panel.category_embed', create=True):
            await self.client.setup_quote_panel()
        self.channel.send.assert_not_awaited()
        self.assertFalse((self.path / 'quote-panels-v2.json').exists())

    async def test_pending_record_does_not_send_again(self):
        (self.path / 'quote-panels-v2.json').write_text(json.dumps({'sbc': 'pending'}))
        with patch('quote_panel.CategoryHomeView', create=True), patch('quote_panel.category_embed', create=True):
            await self.client.setup_quote_panel()
        self.channel.send.assert_not_awaited()

    async def test_public_category_branding_and_view_keep_presentation_and_route(self):
        presentation = {'avatar_url': 'https://cdn.discordapp.com/avatars/owned.png',
                        'banner_url': 'https://cdn.discordapp.com/banners/owned.png',
                        'emoji': {'PC': '⌨️'}}
        self.client.config['quote_presentation'] = presentation
        await self.client.setup_quote_panel()
        options = self.channel.send.await_args_list[0].kwargs
        self.assertFalse(options['embed'].image.url)
        self.assertEqual(options['embed'].thumbnail.url, presentation['avatar_url'])
        self.assertEqual(options['view'].presentation, presentation)
        self.assertEqual(options['view'].allowed_routes[TEST_GUILD][123], 'sbc')


    async def test_all_six_views_register_and_on_ready_sets_up_static_coins(self):
        from quote_panel import CategoryHomeView
        self.client.tree.sync = AsyncMock()
        self.client.add_view = MagicMock()
        await self.client.setup_hook()
        kinds = {call.args[0].kind for call in self.client.add_view.call_args_list
                 if isinstance(call.args[0], CategoryHomeView)}
        self.assertEqual(kinds, {'sbc', 'packs', 'gallery', 'evolutions', 'boosting', 'coins'})
        self.client.config['quote_static'] = {'guild_id': TEST_GUILD, 'channels': {'123456789012345678': 'coins'}}
        self.client._connection.user = SimpleNamespace(id=42)
        self.client.get_guild = MagicMock(return_value=object())
        self.client.setup_quote_panel = AsyncMock()
        self.client.setup_quote_static_panel = AsyncMock()
        await self.client.on_ready()
        self.client.setup_quote_static_panel.assert_awaited_once()

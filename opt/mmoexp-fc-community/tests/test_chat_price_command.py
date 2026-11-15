import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from community import CommunityStore
from content_bot import CHAT_QUOTE_CHANNELS, OFFICIAL_GUILD, TEST_GUILD, build_client
from player_panel import PlayerHomeView
from quote_panel import CategoryHomeView, HubHomeView


class ChatPriceCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = {
            'guild_id': TEST_GUILD,
            'staff_user_ids': ['1237241595674361962'],
            'quote_socket': '/unused',
            'player_panel': {
                'enabled': True, 'guild_id': OFFICIAL_GUILD,
                'channel_id': 1560000000000000000, 'featured_model_ids': [],
            },
        }
        with patch('player_service.validate_player_config'):
            self.client = build_client(self.config, CommunityStore(Path(temporary.name) / 'data.db',
                                                                     self.config['staff_user_ids']))
        self.addAsyncCleanup(self.client.close)

    def interaction(self, guild=OFFICIAL_GUILD, channel=None, user=1237241595674361962):
        return SimpleNamespace(
            guild_id=guild, channel_id=channel or CHAT_QUOTE_CHANNELS[guild],
            user=SimpleNamespace(id=user, bot=False),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

    def command(self, guild=OFFICIAL_GUILD):
        return self.client.tree.get_command('price', guild=discord.Object(guild))

    async def test_staff_posts_each_existing_card_and_private_routes_remain_in_chat(self):
        expected = {
            'coins': CategoryHomeView, 'players': PlayerHomeView,
            'sbc': CategoryHomeView, 'hub': HubHomeView,
        }
        for guild in CHAT_QUOTE_CHANNELS:
            for card, view_type in expected.items():
                interaction = self.interaction(guild=guild)
                await self.command(guild).callback(interaction, card)
                sent = interaction.response.send_message.await_args.kwargs
                self.assertIsInstance(sent['view'], view_type)
                self.assertFalse(sent.get('ephemeral', False))
                self.assertEqual(sent['view'].allowed_routes[guild][interaction.channel_id],
                                 'hub' if card == 'hub' else card)
                self.assertFalse(sent['allowed_mentions'].everyone)

    async def test_nonstaff_and_wrong_channel_never_post_public_card(self):
        for interaction in (self.interaction(user=999), self.interaction(channel=123456789012345678)):
            await self.command().callback(interaction, 'coins')
            self.assertTrue(interaction.response.send_message.await_args.kwargs['ephemeral'])
            self.assertNotIn('view', interaction.response.send_message.await_args.kwargs)

    async def test_production_registration_only_upserts_price(self):
        self.client.tree.sync = AsyncMock()
        self.client.http.upsert_guild_command = AsyncMock()
        self.client.add_view = MagicMock()
        self.client._connection.application_id = 1568239618111832094
        await self.client.setup_hook()
        self.client.tree.sync.assert_awaited_once()
        self.assertEqual(self.client.tree.sync.await_args.kwargs['guild'].id, TEST_GUILD)
        self.client.http.upsert_guild_command.assert_awaited_once()
        args = self.client.http.upsert_guild_command.await_args.args
        self.assertEqual(args[:2], (1568239618111832094, OFFICIAL_GUILD))
        self.assertEqual(args[2]['name'], 'price')


if __name__ == '__main__':
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from community import CommunityStore
from content_bot import ContentClient, OFFICIAL_GUILD, TEST_GUILD, validate_config


class ClubIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = {'guild_id': TEST_GUILD, 'staff_user_ids': [],
            'quote_presentation': {'emoji': {'PC': '🖥️'}},
            'club_panels': {'guild_id': OFFICIAL_GUILD, 'channel_id': 123456789012345678,
                            'role_ids': {'arsenal': 223456789012345678}, 'emoji_map': {}}}
        self.client = ContentClient(self.config, CommunityStore(self.path / 'community.db', []))
        self.addAsyncCleanup(self.client.close)
        self.messages = {n: SimpleNamespace(edit=AsyncMock()) for n in [101, 102, 103]}
        self.channel = SimpleNamespace(id=123456789012345678, guild=SimpleNamespace(id=OFFICIAL_GUILD),
            send=AsyncMock(side_effect=[SimpleNamespace(id=n) for n in [101, 102, 103]]),
            get_partial_message=MagicMock(side_effect=lambda n: self.messages[n]))
        self.client.get_channel = MagicMock(return_value=self.channel)

    async def test_three_persistent_cards_reuse_saved_ids(self):
        await self.client.setup_club_panels()
        await self.client.setup_club_panels()
        self.assertEqual(self.channel.send.await_count, 3)
        calls = self.channel.send.await_args_list
        self.assertIn('Welcome', calls[0].kwargs['embed'].title)
        self.assertEqual(len(calls[0].kwargs['view'].children), 4)
        self.assertEqual(len(calls[1].kwargs['view'].children), 6)
        self.assertIsNone(calls[2].kwargs['view'])
        self.assertFalse(calls[0].kwargs['allowed_mentions'].everyone)
        for message in self.messages.values():
            message.edit.assert_awaited_once()

    async def test_pending_marker_and_wrong_routes_never_send(self):
        marker = self.path / 'club-panels.json'
        marker.write_text(json.dumps({'guild_id': OFFICIAL_GUILD, 'channel_id': self.channel.id,
                                     'messages': {'welcome': 'pending'}}))
        await self.client.setup_club_panels()
        self.channel.send.assert_not_awaited()
        marker.unlink()
        self.channel.guild.id = TEST_GUILD
        await self.client.setup_club_panels()
        self.channel.send.assert_not_awaited()

    async def test_views_register_on_startup_and_ready_sets_up_club(self):
        from club_panel import ClubPanelView
        from onboarding_panel import WelcomeView, ClubSectionView
        self.client.tree.sync = AsyncMock()
        self.client.add_view = MagicMock()
        await self.client.setup_hook()
        registered = [call.args[0] for call in self.client.add_view.call_args_list
                      if isinstance(call.args[0], ClubPanelView)]
        self.assertEqual({view.section for view in registered}, {'england', 'europe'})
        self.assertTrue(any(isinstance(call.args[0], WelcomeView) for call in self.client.add_view.call_args_list))
        self.assertTrue(any(isinstance(call.args[0], ClubSectionView) for call in self.client.add_view.call_args_list))
        self.client._connection.user = SimpleNamespace(id=42)
        self.client.get_guild = MagicMock(return_value=object())
        self.client.setup_club_panels = AsyncMock()
        await self.client.on_ready()
        self.client.setup_club_panels.assert_awaited_once()

    def test_strict_config_rejects_unknown_routes_role_ids_and_branding(self):
        import copy
        for field, value in [('guild_id', 17), ('channel_id', True), ('role_ids', {'arsenal': True}),
                             ('role_ids', {'administrator': 123456789012345678}),
                             ('emoji_map', {'arsenal': 123})]:
            config = copy.deepcopy(self.config)
            config['club_panels'][field] = value
            with self.assertRaises(ValueError):
                validate_config(config)
        for presentation in [{'banner_url': 'http://invalid.example/banner.png'}, {'not_a_key': 'x'},
                             {'emoji': {'not_a_platform': 'x'}}]:
            with self.assertRaises(ValueError):
                validate_config(dict(self.config, quote_presentation=presentation))

    async def test_optional_community_role_is_validated_and_passed_to_both_views(self):
        self.config['club_panels']['community_role_id'] = 323456789012345678
        validate_config(self.config)
        await self.client.setup_club_panels()
        for call in self.channel.send.await_args_list[:2]:
            self.assertEqual(call.kwargs['view'].community_role_id, 323456789012345678)
        for value in [True, 223456789012345678]:
            self.config['club_panels']['community_role_id'] = value
            with self.assertRaises(ValueError):
                validate_config(self.config)

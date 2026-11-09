import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from tests.test_club_panel import Role

GUILD = 1041923524601851914


class GamePickerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from game_picker import GamePickerView, GENERAL_CHAT_CHANNEL_ID
        self.config = {'guild_id': GUILD, 'channel_id': 200, 'games': [
            {'key': 'game_' + str(index), 'label': 'Game ' + str(index),
             'role_ids': [index + 21], 'channel_ids': [index + 301]}
            for index in range(24)]}
        self.roles = {index: Role(index) for index in range(21, 45)}
        self.member = SimpleNamespace(id=7, bot=False, roles=[Role(99)])
        self.member.add_roles = AsyncMock(side_effect=self.add)
        self.member.remove_roles = AsyncMock(side_effect=self.remove)
        self.channels = {index: SimpleNamespace(id=index, guild=SimpleNamespace(id=GUILD), name='chat-' + str(index),
            overwrites_for=lambda role: discord.PermissionOverwrite(),
            permissions_for=lambda member: discord.Permissions(view_channel=True, read_message_history=True))
            for index in list(range(301, 325)) + [GENERAL_CHAT_CHANNEL_ID]}
        self.guild = SimpleNamespace(id=GUILD, channels=list(self.channels.values()), get_role=self.roles.get,
            get_channel=self.channels.get, fetch_member=AsyncMock(return_value=self.member),
            me=SimpleNamespace(guild_permissions=discord.Permissions(manage_roles=True), top_role=Role(90, 10)))
        self.view = GamePickerView(self.config)

    async def add(self, *roles, **kwargs):
        self.member.roles.extend(role for role in roles if role.id not in {r.id for r in self.member.roles})

    async def remove(self, *roles, **kwargs):
        remove_ids = {role.id for role in roles}
        self.member.roles[:] = [role for role in self.member.roles if role.id not in remove_ids]

    def interaction(self, user_id=7, channel_id=200, guild_id=GUILD, bot=False):
        return SimpleNamespace(user=SimpleNamespace(id=user_id, bot=bot), guild=self.guild,
            guild_id=guild_id, channel_id=channel_id,
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def click(self, index=0, interaction=None):
        interaction = interaction or self.interaction()
        await self.view.children[index].callback(interaction)
        return interaction

    async def test_24_persistent_colored_buttons_use_five_columns(self):
        self.assertTrue(self.view.is_persistent())
        self.assertEqual(len(self.view.children), 24)
        self.assertEqual([sum(button.row == row for button in self.view.children) for row in range(5)],
                         [5, 5, 5, 5, 4])
        self.assertGreater(len({button.style for button in self.view.children}), 1)
        self.assertEqual(len({button.custom_id for button in self.view.children}), 24)

    async def test_join_is_idempotent_and_multiple_games_and_other_roles_coexist(self):
        first = await self.click()
        await self.click()
        await self.click(1)
        self.assertEqual({role.id for role in self.member.roles}, {99, 21, 22})
        self.assertEqual(self.member.add_roles.await_count, 2)
        self.assertTrue(first.followup.send.await_args.kwargs['ephemeral'])
        self.assertFalse(first.followup.send.await_args.kwargs['allowed_mentions'].everyone)
        self.assertIn('Channels & Roles', first.followup.send.await_args.args[0])

    async def test_private_remove_checks_owner_and_preserves_other_games(self):
        joined = await self.click()
        await self.click(1)
        panel = joined.followup.send.await_args.kwargs['view']
        remove = next(button for button in panel.children if button.custom_id)
        outsider = self.interaction(user_id=8)
        await remove.callback(outsider)
        self.member.remove_roles.assert_not_awaited()
        await remove.callback(self.interaction())
        self.assertEqual({role.id for role in self.member.roles}, {99, 22})

    async def test_wrong_routes_and_bot_and_fetched_member_mismatch_are_rejected(self):
        for interaction in [self.interaction(guild_id=7), self.interaction(channel_id=201),
                            self.interaction(bot=True)]:
            await self.click(interaction=interaction)
        self.guild.fetch_member.return_value = SimpleNamespace(id=8, bot=False, roles=[])
        await self.click()
        self.member.add_roles.assert_not_awaited()

    async def test_normal_native_channel_access_is_allowed_but_management_is_rejected(self):
        channel = self.channels[301]
        channel.overwrites_for = lambda role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        await self.click()
        self.assertEqual({role.id for role in self.member.roles}, {99, 21})
        channel.overwrites_for = lambda role: discord.PermissionOverwrite(manage_webhooks=True)
        await self.click(1)
        self.assertEqual({role.id for role in self.member.roles}, {99, 21})

    async def test_native_invite_overwrite_is_allowed_while_guild_management_is_rejected(self):
        channel = self.channels[301]
        channel.overwrites_for = lambda role: discord.PermissionOverwrite(create_instant_invite=True)
        await self.click()
        self.assertEqual({role.id for role in self.member.roles}, {99, 21})
        self.roles[22] = Role(22, permissions=discord.Permissions(manage_guild=True).value)
        await self.click(1)
        self.assertEqual({role.id for role in self.member.roles}, {99, 21})
        self.roles[22] = Role(22)
        channel.overwrites_for = lambda role: discord.PermissionOverwrite(manage_guild=True)
        await self.click(1)
        self.assertEqual({role.id for role in self.member.roles}, {99, 21})

    async def test_privileged_managed_default_and_high_roles_cannot_be_added(self):
        for role in [Role(21, permissions=8), Role(21, managed=True), Role(21, position=10), Role(1)]:
            self.roles[21] = role
            await self.click()
        self.member.add_roles.assert_not_awaited()

    async def test_ambiguous_response_rolls_back_only_current_game_roles(self):
        calls = 0
        async def add_then_error(*roles, **kwargs):
            nonlocal calls
            await self.add(*roles, **kwargs)
            calls += 1
            if calls == 1:
                raise OSError('secret transport payload')
        self.member.add_roles.side_effect = add_then_error
        interaction = await self.click()
        self.assertEqual({role.id for role in self.member.roles}, {99})
        self.assertNotIn('secret', str(interaction.followup.send.await_args))
        self.assertIn('could not', interaction.followup.send.await_args.args[0].lower())

    async def test_links_are_member_visible_and_empty_game_uses_honest_general_fallback(self):
        self.channels[301].permissions_for = lambda member: discord.Permissions.none()
        interaction = await self.click()
        self.assertFalse(any(button.url for button in interaction.followup.send.await_args.kwargs['view'].children))
        self.config['games'][1]['channel_ids'] = []
        from game_picker import GamePickerView, GENERAL_CHAT_CHANNEL_ID
        self.view = GamePickerView(self.config)
        interaction = await self.click(1)
        self.assertIn('no dedicated', interaction.followup.send.await_args.args[0].lower())
        links = [button.url for button in interaction.followup.send.await_args.kwargs['view'].children if button.url]
        self.assertEqual(links, [f'https://discord.com/channels/{GUILD}/{GENERAL_CHAT_CHANNEL_ID}'])

    async def test_simultaneous_game_joins_keep_both_preferences(self):
        await asyncio.gather(self.click(), self.click(1))
        self.assertEqual({role.id for role in self.member.roles}, {99, 21, 22})

    def test_config_rejects_non24_unknown_fields_bool_ids_and_duplicate_roles(self):
        from game_picker import validate_game_config
        for field, value in [('games', self.config['games'][:23]), ('guild_id', True), ('extra', 3)]:
            invalid = dict(self.config, **{field: value})
            with self.assertRaises(ValueError):
                validate_game_config(invalid)
        invalid = copy.deepcopy(self.config)
        invalid['games'][0]['role_ids'] = [True]
        with self.assertRaises(ValueError):
            validate_game_config(invalid)
        invalid['games'][0]['role_ids'] = invalid['games'][1]['role_ids']
        with self.assertRaises(ValueError):
            validate_game_config(invalid)

    async def test_content_client_validates_and_registers_persistent_game_picker(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from community import CommunityStore
        from content_bot import ContentClient, TEST_GUILD, validate_config
        from game_picker import GamePickerView
        config = {'guild_id': TEST_GUILD, 'staff_user_ids': [], 'game_picker': self.config}
        with tempfile.TemporaryDirectory() as directory:
            client = ContentClient(config, CommunityStore(Path(directory) / 'community.db', []))
            self.addAsyncCleanup(client.close)
            client.tree.sync = AsyncMock()
            client.add_view = MagicMock()
            await client.setup_hook()
            registered = [call.args[0] for call in client.add_view.call_args_list
                          if isinstance(call.args[0], GamePickerView)]
            self.assertEqual(len(registered), 1)
            self.assertTrue(registered[0].is_persistent())
        with self.assertRaises(ValueError):
            validate_config(dict(config, game_picker=dict(self.config, guild_id=123)))

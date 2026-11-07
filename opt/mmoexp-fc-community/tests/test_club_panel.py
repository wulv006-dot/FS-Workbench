import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord


class Role:
    def __init__(self, role_id, position=1, permissions=0, managed=False):
        self.id, self.position, self.managed = role_id, position, managed
        self.permissions = discord.Permissions(permissions)

    def is_default(self):
        return self.id == 1

    def __lt__(self, other):
        return self.position < other.position


class ClubPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from club_panel import ClubPanelView
        self.roles = {11: Role(11), 12: Role(12), 13: Role(13)}
        self.member = SimpleNamespace(id=7, bot=False, roles=[Role(99)])
        self.member.add_roles = AsyncMock(side_effect=self.add)
        self.member.remove_roles = AsyncMock(side_effect=self.remove)
        self.guild = SimpleNamespace(id=100, get_role=self.roles.get,
            fetch_member=AsyncMock(return_value=self.member),
            me=SimpleNamespace(guild_permissions=discord.Permissions(manage_roles=True), top_role=Role(90, 10)))
        self.mapping = {'arsenal': 11, 'chelsea': 12, 'ajax': 13}
        self.view = ClubPanelView(100, 200, 'england', self.mapping)

    async def add(self, *roles, **kwargs):
        self.member.roles.extend(role for role in roles if role not in self.member.roles)

    async def remove(self, *roles, **kwargs):
        self.member.roles[:] = [r for r in self.member.roles if r not in roles]

    def interaction(self, guild_id=100, channel_id=200, user=None):
        return SimpleNamespace(guild_id=guild_id, channel_id=channel_id, guild=self.guild,
            user=user or self.member,
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    async def press(self, slug, interaction=None):
        interaction = interaction or self.interaction()
        button = next(c for c in self.view.children if c.custom_id == 'fc:club:england:' + slug)
        await button.callback(interaction)
        return interaction

    async def test_persistent_grid_and_cross_section_single_choice_preserves_access_roles(self):
        from club_panel import ClubPanelView
        self.assertTrue(self.view.is_persistent())
        self.assertEqual([sum(c.row == row for c in self.view.children) for row in range(5)], [5] * 5)
        self.member.roles.append(self.roles[13])
        await self.press('arsenal')
        self.assertEqual({r.id for r in self.member.roles}, {99, 11})
        await self.press('chelsea')
        self.assertEqual({r.id for r in self.member.roles}, {99, 12})
        europe = ClubPanelView(100, 200, 'europe', self.mapping)
        button = next(c for c in europe.children if c.custom_id == 'fc:club:europe:ajax')
        await button.callback(self.interaction())
        self.assertEqual({r.id for r in self.member.roles}, {99, 13})

    async def test_route_and_actor_guards_reject_before_role_mutation(self):
        for interaction in [self.interaction(guild_id=101), self.interaction(channel_id=201),
                            self.interaction(user=SimpleNamespace(id=5, bot=True))]:
            await self.press('arsenal', interaction)
            self.assertTrue(interaction.response.send_message.await_args.kwargs['ephemeral'])
        self.guild.fetch_member.return_value = SimpleNamespace(id=8, bot=False, roles=[])
        await self.press('arsenal')
        self.member.add_roles.assert_not_awaited()

    async def test_permissions_hierarchy_and_unconfigured_buttons_fail_closed(self):
        for role in [Role(11, permissions=discord.Permissions(administrator=True).value),
                     Role(11, position=10), Role(11, managed=True), Role(1)]:
            self.roles[11] = role
            await self.press('arsenal')
        self.roles[11] = Role(11)
        self.guild.me.guild_permissions = discord.Permissions.none()
        await self.press('arsenal')
        self.member.add_roles.assert_not_awaited()
        self.assertTrue(next(c for c in self.view.children if c.label == 'Aston Villa').disabled)
        self.guild.me.guild_permissions = discord.Permissions(manage_roles=True)
        await self.press('aston_villa')
        self.member.add_roles.assert_not_awaited()

    async def test_channel_permission_overwrites_are_not_self_assignable(self):
        self.guild.channels = [SimpleNamespace(overwrites_for=lambda role:
            discord.PermissionOverwrite(view_channel=role.id == 11))]
        await self.press('arsenal')
        self.member.add_roles.assert_not_awaited()

    async def test_role_switch_failure_rolls_back_new_club_and_preserves_existing_roles(self):
        self.member.roles.append(self.roles[13])
        original_remove = self.remove
        async def fail_previous(*roles, **kwargs):
            if any(role.id == 13 for role in roles):
                raise discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'private')
            await original_remove(*roles, **kwargs)
        self.member.remove_roles.side_effect = fail_previous
        interaction = await self.press('arsenal')
        self.assertEqual({role.id for role in self.member.roles}, {99, 13})
        self.assertIn('could not update', interaction.followup.send.await_args.args[0])

    async def test_api_failure_is_private_and_does_not_leak_details(self):
        self.member.add_roles.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'),
                                                              'internal provider secret')
        interaction = await self.press('arsenal')
        response = interaction.followup.send.await_args
        self.assertTrue(response.kwargs['ephemeral'])
        self.assertNotIn('secret', str(response))

    async def test_duplicate_or_unknown_role_configuration_rejected(self):
        from club_panel import ClubPanelView
        for mapping in [{'arsenal': 11, 'chelsea': 11}, {'not_a_club': 11}, {'arsenal': True}]:
            with self.assertRaises(ValueError):
                ClubPanelView(100, 200, 'england', mapping)

    async def test_community_marker_is_added_and_retained_when_switching_clubs(self):
        from club_panel import ClubPanelView
        self.roles[14] = Role(14)
        self.view = ClubPanelView(100, 200, 'england', self.mapping, community_role_id=14)
        await self.press('arsenal')
        self.assertEqual({role.id for role in self.member.roles}, {99, 11, 14})
        await self.press('chelsea')
        self.assertEqual({role.id for role in self.member.roles}, {99, 12, 14})

    async def test_failed_switch_rolls_back_only_new_community_marker(self):
        from club_panel import ClubPanelView
        self.roles[14] = Role(14)
        self.view = ClubPanelView(100, 200, 'england', self.mapping, community_role_id=14)
        async def fail_target(*roles, **kwargs):
            if any(role.id == 11 for role in roles):
                raise discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'private')
            await self.add(*roles, **kwargs)
        self.member.add_roles.side_effect = fail_target
        await self.press('arsenal')
        self.assertEqual({role.id for role in self.member.roles}, {99})
        self.member.roles.append(self.roles[14])
        await self.press('arsenal')
        self.assertEqual({role.id for role in self.member.roles}, {99, 14})

    async def test_unsafe_or_duplicate_community_marker_fails_closed(self):
        from club_panel import ClubPanelView
        self.roles[14] = Role(14, permissions=discord.Permissions(administrator=True).value)
        self.view = ClubPanelView(100, 200, 'england', self.mapping, community_role_id=14)
        await self.press('arsenal')
        self.member.add_roles.assert_not_awaited()
        with self.assertRaises(ValueError):
            ClubPanelView(100, 200, 'england', self.mapping, community_role_id=11)

    async def test_welcome_and_section_cards_support_optional_owned_branding(self):
        from club_panel import welcome_embed, club_embed
        welcome = welcome_embed()
        self.assertIn('MMOEXP', welcome.title)
        self.assertIn('FC 27', welcome.description)
        card = club_embed('england', {'avatar_url': 'https://cdn.discordapp.com/avatars/a.png',
                                      'banner_url': 'https://cdn.discordapp.com/attachments/b.png'})
        self.assertEqual('English football clubs', card.title)
        self.assertIn('one club', card.description)
        self.assertFalse(card.image.url)
        self.assertFalse(card.thumbnail.url)
        self.assertFalse(welcome.image.url)

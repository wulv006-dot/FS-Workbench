from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest

import discord

from tests import test_club_panel as fixtures
Role = fixtures.Role


class OnboardingTests(unittest.IsolatedAsyncioTestCase):
    add = fixtures.ClubPanelTests.add
    remove = fixtures.ClubPanelTests.remove
    interaction = fixtures.ClubPanelTests.interaction

    async def asyncSetUp(self):
        await fixtures.ClubPanelTests.asyncSetUp(self)
        from onboarding_panel import WelcomeView
        self.roles[14] = Role(14)
        self.clubs = {'guild_id': 100, 'channel_id': 200, 'role_ids': self.mapping,
                      'emoji_map': {}, 'community_role_id': 14}
        self.welcome = WelcomeView(self.clubs)

    async def click(self, action, interaction=None, view=None):
        interaction = interaction or self.interaction()
        view = view or self.welcome
        await next(item for item in view.children
                   if item.custom_id == 'fc:onboard:' + action).callback(interaction)
        return interaction

    async def test_join_without_team_is_private_idempotent_and_preserves_other_roles(self):
        self.assertTrue(self.welcome.is_persistent())
        self.assertEqual(len(self.welcome.children), 4)
        interaction = await self.click('join')
        self.assertEqual({r.id for r in self.member.roles}, {99, 14})
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
        await self.click('join')
        self.assertEqual(self.member.add_roles.await_count, 1)

    async def test_join_rejects_wrong_route_bot_and_unsafe_role(self):
        for interaction in [self.interaction(guild_id=101), self.interaction(channel_id=201),
                            self.interaction(user=SimpleNamespace(id=4, bot=True))]:
            await self.click('join', interaction)
        self.roles[14] = Role(14, permissions=discord.Permissions(administrator=True).value)
        await self.click('join')
        self.roles[14] = Role(14)
        self.guild.fetch_member.return_value = SimpleNamespace(id=8, bot=False, roles=[])
        await self.click('join')
        self.member.add_roles.assert_not_awaited()

    async def test_club_picker_opens_private_groups_then_original_grid(self):
        from onboarding_panel import PopularClubView
        interaction = await self.click('clubs', view=PopularClubView(self.clubs))
        sent = interaction.response.send_message.await_args.kwargs
        self.assertTrue(sent['ephemeral'])
        chooser = sent['view']
        self.assertEqual(len(chooser.children), 2)
        picked = await self.click('section:england', view=chooser)
        grid = picked.response.send_message.await_args.kwargs
        self.assertTrue(grid['ephemeral'])
        self.assertEqual(len(grid['view'].children), 25)
        self.assertEqual(grid['view'].community_role_id, 14)
        await next(b for b in grid['view'].children if b.label == 'Arsenal').callback(self.interaction())
        self.assertEqual({r.id for r in self.member.roles}, {99, 11, 14})

    async def test_popular_clubs_are_direct_safe_buttons_and_other_clubs_remain_available(self):
        from onboarding_panel import PopularClubView
        self.roles[15], self.roles[16] = Role(15), Role(16)
        self.clubs['role_ids'] = dict(self.mapping, man_city=15, real_madrid=16)
        popular = PopularClubView(self.clubs)
        self.assertTrue(popular.is_persistent())
        self.assertEqual([button.label for button in popular.children],
                         ['Man City', 'Real Madrid', 'Barcelona', 'Bayern', 'PSG', 'More clubs'])
        await popular.children[0].callback(self.interaction())
        self.assertEqual({role.id for role in self.member.roles}, {99, 14, 15})
        await popular.children[1].callback(self.interaction())
        self.assertEqual({role.id for role in self.member.roles}, {99, 14, 16})
        self.assertTrue(popular.children[2].disabled)

    async def test_section_launcher_and_navigation_remain_private_and_route_scoped(self):
        from onboarding_panel import ClubSectionView
        view = ClubSectionView(self.clubs, 'europe')
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 1)
        interaction = await self.click('section:europe', view=view)
        self.assertEqual(len(interaction.response.send_message.await_args.kwargs['view'].children), 22)
        bad = await self.click('section:europe', self.interaction(channel_id=201), view)
        self.assertNotIn('view', bad.response.send_message.await_args.kwargs)
        for action in ('news', 'daily', 'prices'):
            interaction = await self.click(action)
            self.assertTrue(interaction.response.send_message.await_args.kwargs['ephemeral'])
            self.assertFalse(interaction.response.send_message.await_args.kwargs['allowed_mentions'].everyone)

    async def test_join_api_failure_does_not_leak_provider_details(self):
        self.member.add_roles.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'provider secret')
        interaction = await self.click('join')
        self.assertNotIn('secret', str(interaction.followup.send.await_args))

    async def test_official_players_link_and_private_navigation(self):
        from onboarding_panel import WelcomeView, CHANNELS, OFFICIAL_GUILD, PLAYER_CHANNEL
        welcome = WelcomeView(dict(self.clubs, guild_id=OFFICIAL_GUILD))
        links = [b for b in welcome.children if b.url]
        self.assertEqual([(b.label, b.url) for b in links], [('Players',
            f'https://discord.com/channels/{OFFICIAL_GUILD}/{PLAYER_CHANNEL}')])
        for section in ('prices', 'daily'):
            self.assertIn(('⚽ Players', PLAYER_CHANNEL), CHANNELS[section])


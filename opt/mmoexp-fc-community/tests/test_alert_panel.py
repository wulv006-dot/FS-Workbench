import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from tests.test_club_panel import Role


class AlertTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from alert_panel import AlertHomeView, AlertPreferencesView
        self.config = {'guild_id': 100, 'channel_ids': [200, 201], 'role_ids':
                       {'sbc': 11, 'evolutions': 12, 'objectives': 13, 'news': 14, 'giveaways': 15}}
        self.roles = {i: Role(i) for i in range(11, 16)}
        self.member = SimpleNamespace(id=7, bot=False, roles=[Role(99), self.roles[11]])
        self.member.add_roles = AsyncMock(side_effect=self.add)
        self.member.remove_roles = AsyncMock(side_effect=self.remove)
        self.guild = SimpleNamespace(id=100, get_role=self.roles.get, channels=[],
            fetch_member=AsyncMock(return_value=self.member), me=SimpleNamespace(
                guild_permissions=discord.Permissions(manage_roles=True), top_role=Role(90, 10)))
        self.home = AlertHomeView(self.config)
        self.panel = AlertPreferencesView(self.config, 7, ['sbc'])

    async def add(self, *roles, **kwargs):
        self.member.roles.extend(r for r in roles if r not in self.member.roles)

    async def remove(self, *roles, **kwargs):
        self.member.roles[:] = [r for r in self.member.roles if r not in roles]

    def interaction(self, user_id=7, channel_id=200, guild_id=100):
        return SimpleNamespace(user=SimpleNamespace(id=user_id, bot=False), guild=self.guild,
            guild_id=guild_id, channel_id=channel_id,
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_persistent_home_opens_private_current_preferences(self):
        self.assertTrue(self.home.is_persistent())
        self.assertEqual(self.home.children[0].custom_id, 'fc:alerts:open')
        interaction = self.interaction()
        await self.home.children[0].callback(interaction)
        result = interaction.followup.send.await_args.kwargs
        self.assertTrue(result['ephemeral'])
        self.assertEqual(result['view'].selected, {'sbc'})
        self.member.add_roles.assert_not_awaited()

    async def test_route_and_user_rejected(self):
        for interaction in [self.interaction(channel_id=999), self.interaction(guild_id=99),
                            self.interaction(user_id=8)]:
            await self.panel.save(interaction)
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_not_awaited()

    async def test_save_and_disable_preserve_other_roles(self):
        self.panel.selected = {'news', 'evolutions'}
        await self.panel.save(self.interaction())
        self.assertEqual({r.id for r in self.member.roles}, {99, 12, 14})
        await self.panel.save(self.interaction(), clear=True)
        self.assertEqual({r.id for r in self.member.roles}, {99})

    async def test_permissionful_overwrite_and_managed_roles_rejected(self):
        self.panel.selected = {'news'}
        for role in [Role(14, permissions=8), Role(14, managed=True), Role(14, position=10)]:
            self.roles[14] = role
            await self.panel.save(self.interaction())
        self.roles[14] = Role(14)
        self.guild.channels = [SimpleNamespace(overwrites_for=lambda r:
            discord.PermissionOverwrite(view_channel=True if r.id == 14 else None))]
        await self.panel.save(self.interaction())
        self.member.add_roles.assert_not_awaited()

    async def test_partial_change_is_restored_after_api_failure(self):
        self.panel.selected = {'news', 'evolutions'}
        async def fail_news(*roles, **kwargs):
            if roles[0].id == 14:
                raise discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'secret detail')
            await self.add(*roles, **kwargs)
        self.member.add_roles.side_effect = fail_news
        interaction = self.interaction()
        await self.panel.save(interaction)
        self.assertEqual({r.id for r in self.member.roles}, {99, 11})
        self.assertNotIn('secret', str(interaction.followup.send.await_args))

    async def test_lost_reply_after_mutation_is_reconciled(self):
        self.panel.selected = {'news'}
        calls = 0
        async def changed_then_error(*roles, **kwargs):
            nonlocal calls
            calls += 1
            await self.add(*roles, **kwargs)
            if calls == 1:
                raise discord.HTTPException(SimpleNamespace(status=500, reason='Unknown'), 'upstream')
        self.member.add_roles.side_effect = changed_then_error
        await self.panel.save(self.interaction())
        self.assertEqual({r.id for r in self.member.roles}, {99, 11})

    async def test_concurrent_saves_do_not_mix_preferences(self):
        from alert_panel import AlertPreferencesView
        other = AlertPreferencesView(self.config, 7, ['giveaways'])
        self.panel.selected = {'news', 'evolutions'}
        await asyncio.gather(self.panel.save(self.interaction()), other.save(self.interaction()))
        self.assertEqual({r.id for r in self.member.roles}, {99, 15})

    async def test_config_rejects_unknown_missing_duplicate_bool_ids(self):
        from alert_panel import validate_alert_config
        for updates in [{'guild_id': True}, {'channel_ids': []}, {'channel_ids': [200, True]},
                        {'role_ids': {'sbc': 11}}, {'role_ids': dict.fromkeys(self.config['role_ids'], 11)}]:
            with self.assertRaises(ValueError):
                validate_alert_config({**self.config, **updates})

    async def test_timeout_offers_persistent_reopen(self):
        self.panel.origin = self.interaction()
        await self.panel.on_timeout()
        result = self.panel.origin.edit_original_response.await_args.kwargs
        self.assertTrue(result['view'].is_persistent())
        self.assertIn('expired', result['content'])

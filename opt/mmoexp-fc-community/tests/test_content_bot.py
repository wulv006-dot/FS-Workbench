import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from community import CommunityStore
from content_bot import TEST_GUILD, build_client, load_config


class ContentBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = {'guild_id': TEST_GUILD, 'staff_user_ids': ['111111111111111111', '222222222222222222']}
        self.store = CommunityStore(self.path / 'data.db', self.config['staff_user_ids'])
        self.client = build_client(self.config, self.store)
        self.addAsyncCleanup(self.client.close)

    def interaction(self, guild=TEST_GUILD, user='333333333333333333'):
        return SimpleNamespace(guild_id=guild, channel_id=444444444444444444,
                               user=SimpleNamespace(id=int(user), bot=False),
                               response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    def command(self, name):
        import discord
        return self.client.tree.get_command('fc', guild=discord.Object(TEST_GUILD)).get_command(name)

    async def test_cross_guild_cannot_query_and_no_global_commands(self):
        i = self.interaction(guild=1041923524601851914)
        await self.command('latest').callback(i)
        i.response.send_message.assert_awaited_once()
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])
        i.followup.send.assert_not_awaited()
        self.assertEqual(self.client.tree.get_commands(), [])
        self.assertFalse(self.client.intents.message_content)
        self.assertFalse(self.client.intents.members)

    async def test_join_uses_discord_actor_and_channel_and_private_response(self):
        # Use a real currently open event instead of mocking the storage implementation.
        import time
        event = self.store.create_event('111111111111111111', 'FC27 clinic', 2, int(time.time())+100, int(time.time()))
        i = self.interaction()
        await self.command('join').callback(i, event)
        self.assertEqual(self.store.report('111111111111111111', event),
                         [{'channel': '444444444444444444', 'active': 1, 'cancelled': 0}])
        self.assertTrue(i.response.defer.call_args.kwargs['ephemeral'])
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertFalse(i.followup.send.call_args.kwargs['allowed_mentions'].everyone)

    async def test_nonstaff_cannot_draft(self):
        i = self.interaction()
        await self.command('draft').callback(i, 'Title', 'guide', 'Body', 'https://www.ea.com')
        self.assertIn('Staff access required', i.followup.send.call_args.args[0])
        self.assertEqual(self.store.latest(), [])

    async def test_long_report_is_delivered_whole_as_private_file(self):
        i = self.interaction()
        expected = '\n'.join(f'Channel {n}: active 123, cancelled 456' for n in range(100))
        await self.client.run_action(i, lambda: expected)
        sent = i.followup.send.call_args.kwargs
        self.assertEqual(sent['file'].fp.getvalue().decode('utf-8'), expected)
        self.assertTrue(sent['ephemeral'])

    async def test_rate_limit_blocks_action_before_ninth_request(self):
        calls = []
        for _ in range(9):
            await self.client.run_action(self.interaction(), lambda: calls.append(1))
        self.assertEqual(len(calls), 8)

    def test_config_rejects_production_and_invalid_staff(self):
        path = self.path / 'config.json'
        for config in [{'guild_id': 1041923524601851914, 'staff_user_ids': []},
                       {'guild_id': TEST_GUILD, 'staff_user_ids': ['not-an-id']}]:
            path.write_text(json.dumps(config), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_custom_icons_are_bounded_to_supported_keys_and_discord_emoji(self):
        from content_bot import validate_config
        base = dict(self.config)
        base['quote_presentation'] = {'icons': {'sbc': '<:fcq_sbc:1568664854124961812>'}}
        validate_config(base)
        for icons in [[], {'unknown': '<:fcq_sbc:1568664854124961812>'},
                      {'sbc': 'https://untrusted.example/image.png'}, {'clock': '@everyone'},
                      {'sbc': 123}]:
            base['quote_presentation'] = {'icons': icons}
            with self.assertRaises(ValueError):
                validate_config(base)


if __name__ == '__main__':
    unittest.main()

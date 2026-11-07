import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from community import CommunityStore
from content_bot import build_client, TEST_GUILD


class MentionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = build_client({'guild_id': TEST_GUILD, 'staff_user_ids': []},
                                   CommunityStore(Path(self.tmp.name)/'test.db', set()))
        self.client._connection.user = SimpleNamespace(id=1568239618111832094)
        self.addAsyncCleanup(self.client.close)

    def message(self, guild=TEST_GUILD, bot=False, mentions=True):
        return SimpleNamespace(guild=SimpleNamespace(id=guild), author=SimpleNamespace(id=123,bot=bot),
            mentions=[self.client.user] if mentions else [], content='hello',
            channel=SimpleNamespace(send=AsyncMock()), webhook_id=None)

    async def test_only_explicit_human_mention_in_test_guild_replies(self):
        for m in [self.message(guild=1041923524601851914),self.message(bot=True),self.message(mentions=False)]:
            await self.client.on_message(m)
            m.channel.send.assert_not_awaited()
        m = self.message()
        await self.client.on_message(m)
        self.assertIsNotNone(m.channel.send.call_args.kwargs['view'])
        self.assertFalse(self.client.intents.message_content)
        self.assertTrue(self.client.intents.guild_messages)

    async def test_mention_rate_limit(self):
        m=self.message()
        for _ in range(4):
            await self.client.on_message(m)
        self.assertEqual(m.channel.send.await_count,3)

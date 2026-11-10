import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from community import CommunityStore
from content_bot import ContentClient, OFFICIAL_GUILD, TEST_GUILD, validate_config


class NewsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {'guild_id': TEST_GUILD, 'staff_user_ids': [],
                      'news_publish': {'guild_id': OFFICIAL_GUILD, 'channel_id': '123456789012345678',
                                       'enabled': True, 'poll_seconds': 900}}
        self.client = ContentClient(self.config, CommunityStore(Path(self.tmp.name) / 'community.db', []))
        self.addAsyncCleanup(self.client.close)
        self.channel = SimpleNamespace(id=123456789012345678, guild=SimpleNamespace(id=OFFICIAL_GUILD),
                                       send=AsyncMock(return_value=SimpleNamespace(id=456)))
        self.client.get_channel = MagicMock(return_value=self.channel)

    async def test_queued_x_post_publishes_once_with_exact_link_and_no_mentions(self):
        self.client.news_store.enqueue_x('https://x.com/Official/status/12345', 'FC 27 squad news')
        await self.client.flush_news()
        await self.client.flush_news()
        self.channel.send.assert_awaited_once()
        options = self.channel.send.await_args.kwargs
        self.assertEqual(options['embed'].url, 'https://x.com/Official/status/12345')
        self.assertFalse(options['allowed_mentions'].everyone)
        self.assertEqual(self.client.news_store.items()[0]['status'], 'published')

    async def test_channel_and_guild_mismatch_do_not_claim_or_send(self):
        self.client.news_store.enqueue_x('https://x.com/Official/status/12345')
        self.channel.guild.id = TEST_GUILD
        await self.client.flush_news()
        self.channel.guild.id = OFFICIAL_GUILD
        self.channel.id += 1
        await self.client.flush_news()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.client.news_store.items()[0]['status'], 'pending')

    async def test_startup_recovery_runs_once_and_close_cancels_background_work(self):
        from news_feed import NewsStore
        self.client.news_store.enqueue_x('https://x.com/Official/status/12345')
        self.client.news_store.claim(self.config['news_publish']['channel_id'])
        self.client.tree.sync = AsyncMock()
        self.client.add_view = MagicMock()
        gate = asyncio.Event()
        self.client.run_news_collection = gate.wait
        self.client.run_news_publication = gate.wait
        with patch.object(NewsStore, 'recover_sending', autospec=True,
                          side_effect=NewsStore.recover_sending) as recover:
            await self.client.setup_hook()
            await self.client.setup_hook()
            self.assertEqual(recover.call_count, 1)
        self.assertEqual(self.client.news_store.items()[0]['status'], 'uncertain')
        tasks = self.client.news_tasks.copy()
        await asyncio.sleep(0)
        await self.client.close()
        self.assertTrue(all(task.cancelled() for task in tasks))

    async def test_fetch_runs_in_worker_thread(self):
        import threading
        called_on = []
        def collect(store, config):
            called_on.append(threading.get_ident())
            return []
        with patch('news_feed.collect_cycle', side_effect=collect) as call:
            await self.client.collect_news_once()
        self.assertEqual(len(called_on), 1)
        self.assertNotEqual(called_on[0], threading.get_ident())
        call.assert_called_once_with(self.client.news_store, self.config['news_publish'])

    async def test_disabled_auto_still_sends_manual_posts(self):
        self.client.config['news_publish']['enabled'] = False
        self.client.news_store.enqueue_x('https://x.com/Official/status/12345')
        await self.client.flush_news()
        self.channel.send.assert_awaited_once()

    async def test_client_passes_ea_switch_to_existing_queue(self):
        from tests.test_news_rounds import row
        store = self.client.news_store
        store.ingest([row(1, 'ea')])
        store.ingest([row(1)])
        self.client.config['news_publish']['ea_enabled'] = False
        await self.client.flush_news()
        self.channel.send.assert_awaited_once()
        self.assertIn('mmoexp.com', self.channel.send.await_args.kwargs['embed'].url)
        self.assertEqual(next(item for item in store.items() if item['kind']=='ea')['status'], 'pending')

    def test_unapproved_news_guild_and_extra_configuration_rejected(self):
        for change in [{'guild_id': 123}, {'poll_seconds': 30}, {'channel_id': 123}, {'extra': True}]:
            with self.assertRaises(ValueError):
                validate_config(dict(self.config, news_publish=dict(self.config['news_publish'], **change)))

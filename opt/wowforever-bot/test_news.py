"""News boundary tests using fabricated content and a real temporary state store."""
import asyncio
import copy
import datetime as dt
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lib.store import Store
from modules import news as N

NOW = dt.datetime(2026, 11, 7, 21, 0, tzinfo=N.CST)


def item(source, key=None, when=NOW):
    return {"source": source, "key": key or source + ':test',
            "title": "Forever test update", "summary": "Test summary.",
            "url": "https://news.blizzard.com/en-us/article/1/test" if source == "official" else
                   "https://www.reddit.com/r/wowforever/comments/abc/test/",
            "epoch": when.timestamp(), "image": None}


class ParsingTests(unittest.TestCase):
    def test_blizzard_ignores_style_and_irrelevant_articles(self):
        page = '<a href="/en-us/article/1/test"><style>forever</style>Midnight update</a>' \
               '<a href="/en-us/article/2/test">WoW Forever Test</a>'
        article = '<meta property="og:title" content="WoW Forever Test — Blizzard News">' \
                  '<meta name="description" content="Test notes for Forever.">' \
                  '<script type="application/ld+json">{"datePublished":"2026-11-07T01:00:00Z"}</script>'
        links = N.BlizzardLinks()
        links.feed(page)
        self.assertEqual(links.links, ['https://news.blizzard.com/en-us/article/2/test'])
        parsed = N.official_items(page, fetch=lambda _: article)
        self.assertEqual(parsed[0]['title'], 'WoW Forever Test')
        self.assertTrue(parsed[0]['key'].startswith('blizzard:2:'))
        self.assertEqual(parsed[0]['epoch'], N.epoch('2026-11-07T01:00:00Z'))

    def test_blizzard_refuses_unrecognised_or_empty_page(self):
        with self.assertRaises(ValueError):
            N.official_items('<html>Access denied</html>')

    def test_reddit_ranking_links_and_metadata(self):
        feed = '''<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><id>t3_1</id><title>Popular Forever topic</title>
        <link href="https://www.reddit.com/r/wowforever/comments/abc/topic/"/>
        <published>2026-11-07T01:00:00Z</published>
        <content>&lt;p&gt;Player discussion.&lt;/p&gt;</content></entry>
        <entry><id>t3_2</id><title>Spoiler topic</title>
        <link href="https://www.reddit.com/r/wowforever/comments/def/topic/"/>
        <published>2026-11-07T01:00:00Z</published></entry>
        <entry><id>t3_3</id><title>Other game</title>
        <link href="https://www.reddit.com/r/wow/comments/ghi/topic/"/>
        <published>2026-11-07T01:00:00Z</published></entry></feed>'''
        parsed = N.reddit_items(feed)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['summary'], 'Player discussion.')
        self.assertEqual(parsed[0]['key'], 't3_1')


class PublishingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, 'state.json')
        self.channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=1, created_at=NOW)))
        self.bot = SimpleNamespace(get_channel=lambda _: self.channel)
        self.config = {'channels': {'news': '123'}, 'features': {'news': {
            'enabled': True, 'channel': 'news', 'daily_limit': 2, 'publish_hours': [12, 20]}}}
        self.m = N.NewsModule(self.bot, self.config, Store(self.path))
        self.found = {'official': [item('official')], 'reddit': [item('reddit')]}

    async def run_module(self, now=NOW, found=None):
        with patch.object(N, 'fetch_candidates', return_value=found or self.found):
            return await self.m.run_once(now)

    async def test_two_sources_share_hard_daily_cap_even_after_restart(self):
        self.config['features']['news']['daily_limit'] = 99
        self.assertEqual(await self.run_module(), 2)
        self.m = N.NewsModule(self.bot, self.config, Store(self.path))
        self.assertEqual(await self.run_module(), 0)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertEqual(len(self.m.store.get('news_state')['posts']), 2)

    async def test_scheduled_slots_and_no_backlog_replay(self):
        self.found = {source: [item(source, when=NOW.replace(hour=10))]
                      for source in ('official', 'reddit')}
        self.assertEqual(await self.run_module(NOW.replace(hour=11)), 0)
        self.assertEqual(await self.run_module(NOW.replace(hour=12)), 1)
        self.assertEqual(await self.run_module(NOW.replace(hour=18)), 0)
        self.assertEqual(await self.run_module(), 1)
        self.assertEqual(await self.run_module(NOW + dt.timedelta(days=1)), 0)

    async def test_next_day_has_new_allowance_for_new_content(self):
        await self.run_module()
        later = NOW + dt.timedelta(days=1)
        self.channel.send.return_value = SimpleNamespace(id=2, created_at=later)
        found = {s: [item(s, key=s+':new', when=later)] for s in ('official', 'reddit')}
        self.assertEqual(await self.run_module(later, found), 2)

    async def test_concurrent_checks_cannot_exceed_two(self):
        with patch.object(N, 'fetch_candidates', return_value=self.found):
            results = await asyncio.gather(self.m.run_once(NOW), self.m.run_once(NOW))
        self.assertEqual(sum(results), 2)
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_unknown_send_reserves_budget_and_is_not_replayed(self):
        self.channel.send.side_effect = TimeoutError('fabricated timeout')
        self.assertEqual(await self.run_module(), 0)
        self.m = N.NewsModule(self.bot, self.config, Store(self.path))
        self.assertEqual(await self.run_module(), 0)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertTrue(all(p['status'] == 'unknown' for p in self.m.store.get('news_state')['posts']))

    async def test_stale_future_and_duplicate_items_are_skipped(self):
        found = {'official': [item('official', when=NOW - dt.timedelta(days=8))],
                 'reddit': [item('reddit', when=NOW + dt.timedelta(days=1))]}
        self.assertEqual(await self.run_module(found=found), 0)
        self.channel.send.assert_not_awaited()

    async def test_source_failure_does_not_fill_with_old_news(self):
        self.assertEqual(await self.run_module(found={'official': [], 'reddit': [item('reddit')]}), 1)
        self.assertEqual(await self.run_module(found={'official': [], 'reddit': [item('reddit')]}), 0)

    async def test_state_failure_prevents_send(self):
        with patch.object(self.m.store, 'set', side_effect=OSError('fabricated disk error')):
            with self.assertRaises(OSError):
                await self.run_module()
        self.channel.send.assert_not_awaited()

    async def test_send_straddling_midnight_counts_actual_day(self):
        actual = NOW.replace(hour=0) + dt.timedelta(days=1)
        self.channel.send.return_value = SimpleNamespace(id=3, created_at=actual)
        self.assertEqual(await self.run_module(), 1)
        record = self.m.store.get('news_state')['posts'][0]
        self.assertEqual(record['day'], actual.date().isoformat())

    async def test_existing_giveaway_state_and_mentions_are_preserved(self):
        original = {'giveaway_stock': {'bag10': 9}, 'giveaway_spins': {'123': 1}}
        self.m.store.update(**copy.deepcopy(original))
        await self.run_module()
        for key, value in original.items():
            self.assertEqual(self.m.store.get(key), value)
        for call in self.channel.send.call_args_list:
            self.assertFalse(call.kwargs['allowed_mentions'].everyone)
            self.assertFalse(call.kwargs['allowed_mentions'].users)


if __name__ == '__main__':
    unittest.main()

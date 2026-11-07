import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from community import CommunityStore

TEST_GUILD = 1565922092518613064


class FutPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from fut_panel import FutHomeView
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CommunityStore(Path(self.tmp.name) / 'community.db', {'editor'})
        with self.store.db() as conn:
            conn.execute("INSERT INTO content VALUES(1,'Rumour','leak','Unconfirmed player move','https://example.com',27,'editor',1,'editor',2,'approved')")
            conn.execute("INSERT INTO content VALUES(2,'Gallery card','collection','A favourite card','https://example.com',27,'editor',1,'editor',2,'approved')")
        self.home = FutHomeView(self.store)

    def interaction(self, user=123, guild=TEST_GUILD, bot=False):
        return SimpleNamespace(guild_id=guild, channel_id=456,
                               user=SimpleNamespace(id=user, bot=bot),
                               response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def choose(self, view, value, i):
        select = next(c for c in view.children if isinstance(c, discord.ui.Select))
        if not await view.interaction_check(i):
            return
        select._refresh_state(i, {'values': [str(value)]})
        await select.callback(i)

    async def test_home_buttons_open_sections_and_private_back_returns_home(self):
        from fut_panel import CATEGORIES
        buttons = [c for c in self.home.children if isinstance(c, discord.ui.Button)]
        self.assertEqual({b.custom_id for b in buttons}, {'fut:home:' + k for k in CATEGORIES})
        button = next(b for b in buttons if b.custom_id == 'fut:home:collection')
        i = self.interaction()
        self.assertTrue(await self.home.interaction_check(i))
        await button.callback(i)
        listing = i.response.send_message.await_args.kwargs['view']
        back = next(c for c in listing.children if isinstance(c, discord.ui.Button) and c.label == 'Home')
        returned = self.interaction()
        self.assertTrue(await listing.interaction_check(returned))
        await back.callback(returned)
        private_home = returned.response.edit_message.await_args.kwargs['view']
        self.assertFalse(await private_home.interaction_check(self.interaction(user=999)))
        self.assertEqual(private_home.timeout, 180)
        self.assertEqual(len([c for c in private_home.children if isinstance(c, discord.ui.Button)]), 10)

    async def test_easysbc_tools_open_privately_with_real_website_links(self):
        i = self.interaction()
        await self.choose(self.home, 'tools', i)
        response = i.response.send_message.await_args.kwargs
        self.assertTrue(response['ephemeral'])
        self.assertIn('EasySBC', str(response['embed'].to_dict()))
        view = response['view']
        links = {child.label: child.url for child in view.children
                 if isinstance(child, discord.ui.Button) and child.url}
        self.assertEqual(links, {
            'Players': 'https://www.easysbc.io/players',
            'SBCs': 'https://www.easysbc.io/sbc',
            'Evolutions': 'https://www.easysbc.io/evolutions',
            'Gallery': 'https://www.easysbc.io/fut-gallery',
        })
        self.assertFalse(await view.interaction_check(self.interaction(user=999)))
        back = next(c for c in view.children if isinstance(c, discord.ui.Button) and c.label == 'Home')
        returned = self.interaction()
        await back.callback(returned)
        self.assertIsNotNone(returned.response.edit_message.await_args.kwargs['view'])

    async def test_article_and_event_return_home_and_navigate_privately(self):
        now = int(time.time())
        event = self.store.create_event('editor', 'Community cup', 3, now + 3600, now)
        for kind, item in (('leak', 1), ('events', event)):
            with self.subTest(kind=kind):
                i = self.interaction()
                await self.choose(self.home, kind, i)
                listing = i.response.send_message.await_args.kwargs['view']
                selected = self.interaction()
                await self.choose(listing, item, selected)
                view = selected.response.edit_message.await_args.kwargs['view']
                back = next(c for c in view.children if isinstance(c, discord.ui.Button) and c.label == 'Home')
                returned = self.interaction()
                await back.callback(returned)
                private_home = returned.response.edit_message.await_args.kwargs['view']
                opened = self.interaction()
                await next(c for c in private_home.children if isinstance(c, discord.ui.Button)
                           and c.custom_id == 'fut:home:collection').callback(opened)
                self.assertEqual(opened.response.edit_message.await_args.kwargs['embed'].title, 'FUT Gallery')

    async def test_home_rejects_other_guild_and_bots(self):
        for i in (self.interaction(guild=1), self.interaction(bot=True)):
            await self.choose(self.home, 'collection', i)
            self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])
            self.assertNotIn('view', i.response.send_message.await_args.kwargs)

    async def test_gallery_is_private_and_selecting_article_shows_source(self):
        i = self.interaction()
        await self.choose(self.home, 'collection', i)
        sent = i.response.send_message.await_args.kwargs
        self.assertTrue(sent['ephemeral'])
        listing = sent['view']
        outsider = self.interaction(user=999)
        await self.choose(listing, 2, outsider)
        self.assertTrue(outsider.response.send_message.await_args.kwargs['ephemeral'])
        owner = self.interaction()
        await self.choose(listing, 2, owner)
        article = owner.response.edit_message.await_args.kwargs['embed']
        self.assertEqual(article.title, 'Gallery card')
        self.assertIn('https://example.com', str(article.to_dict()))
        view = owner.response.edit_message.await_args.kwargs['view']
        source = next(c for c in view.children if isinstance(c, discord.ui.Button) and c.label == 'Read source')
        self.assertEqual(source.url, 'https://example.com')

    async def test_leak_bookmark_is_saved_for_owner_and_retrievable(self):
        i = self.interaction()
        await self.choose(self.home, 'leak', i)
        listing = i.response.send_message.await_args.kwargs['view']
        opened = self.interaction()
        await self.choose(listing, 1, opened)
        result = opened.response.edit_message.await_args.kwargs
        self.assertIn('unconfirmed', str(result['embed'].to_dict()).lower())
        article = result['view']
        bookmark = next(c for c in article.children if isinstance(c, discord.ui.Button) and 'save' in c.label.lower())
        rejected = self.interaction(user=999)
        self.assertFalse(await article.interaction_check(rejected))
        self.assertEqual(self.store.bookmarks(999), [])
        owner = self.interaction()
        self.assertTrue(await article.interaction_check(owner))
        await bookmark.callback(owner)
        self.assertEqual([row['id'] for row in self.store.bookmarks(123)], [1])
        saved = self.interaction()
        await self.choose(self.home, 'bookmarks', saved)
        self.assertEqual(saved.response.send_message.await_args.kwargs['view'].children[0].options[0].value, '1')

    async def test_persistent_home_and_private_empty_guide_notice(self):
        self.assertTrue(self.home.is_persistent())
        for kind in ('sbc', 'squad'):
            i = self.interaction()
            await self.choose(self.home, kind, i)
            response = i.response.send_message.await_args.kwargs
            self.assertTrue(response['ephemeral'])
            self.assertIsNotNone(response['view'])
            self.assertIn('not available', response['embed'].description)

    async def test_empty_test_guild_category_keeps_original_notice(self):
        i = self.interaction()
        await self.choose(self.home, 'news', i)
        self.assertIn('Nothing here yet. Check back soon!',
                      i.response.send_message.await_args.kwargs['embed'].description)

    async def test_withdrawn_article_cannot_be_opened_or_saved(self):
        i = self.interaction()
        await self.choose(self.home, 'leak', i)
        listing = i.response.send_message.await_args.kwargs['view']
        self.store.withdraw('editor', 1)
        owner = self.interaction()
        await self.choose(listing, 1, owner)
        self.assertTrue(owner.response.send_message.await_args.kwargs['ephemeral'])
        owner.response.edit_message.assert_not_awaited()
        self.assertEqual(self.store.bookmarks(123), [])

    async def test_foreign_user_or_guild_cannot_join_from_event_view(self):
        now = int(time.time())
        event = self.store.create_event('editor', 'Community cup', 3, now + 3600, now)
        i = self.interaction()
        await self.choose(self.home, 'events', i)
        selected = self.interaction()
        await self.choose(i.response.send_message.await_args.kwargs['view'], event, selected)
        view = selected.response.edit_message.await_args.kwargs['view']
        for other in (self.interaction(user=999), self.interaction(guild=1), self.interaction(bot=True)):
            self.assertFalse(await view.interaction_check(other))
            self.assertTrue(other.response.send_message.await_args.kwargs['ephemeral'])
        self.assertEqual(self.store.events(now)[0]['joined'], 0)

    async def test_event_join_and_leave_update_real_store(self):
        now = int(time.time())
        event = self.store.create_event('editor', 'Community cup', 3, now + 3600, now)
        i = self.interaction()
        await self.choose(self.home, 'events', i)
        listing = i.response.send_message.await_args.kwargs['view']
        selected = self.interaction()
        await self.choose(listing, event, selected)
        event_view = selected.response.edit_message.await_args.kwargs['view']
        join = next(c for c in event_view.children if isinstance(c, discord.ui.Button) and c.label == 'Join')
        leave = next(c for c in event_view.children if isinstance(c, discord.ui.Button) and c.label == 'Leave')
        player = self.interaction()
        self.assertTrue(await event_view.interaction_check(player))
        await join.callback(player)
        self.assertEqual(self.store.events(now)[0]['joined'], 1)
        player = self.interaction()
        await leave.callback(player)
        self.assertEqual(self.store.events(now)[0]['joined'], 0)


if __name__ == '__main__':
    unittest.main()

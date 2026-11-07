import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from community import CommunityStore
from content_bot import TEST_GUILD, build_client, validate_config


PROD = 1041923524601851914
CHANNELS = {str(200000000000000000 + n): kind for n, kind in enumerate(
    ('news', 'sbc', 'evolutions', 'objectives', 'collection', 'store'))}


class InformationPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CommunityStore(Path(self.tmp.name) / 'data.db', {'editor'})
        self.store.draft('editor', 'News item', 'news', 'Body', 'https://example.com/a', 27, 1)
        self.store.approve('editor', 1, 2)

    def interaction(self, guild=PROD, channel=200000000000000000, user=123, bot=False):
        return SimpleNamespace(guild_id=guild, channel_id=channel,
            user=SimpleNamespace(id=user, bot=bot),
            response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()))

    async def test_click_is_private_and_private_navigation_is_owned(self):
        from fut_panel import InformationPanelView
        panel = InformationPanelView(self.store, PROD, CHANNELS)
        player = self.interaction()
        self.assertTrue(await panel.interaction_check(player))
        await panel.children[0].callback(player)
        sent = player.response.send_message.await_args.kwargs
        self.assertTrue(sent['ephemeral'])
        self.assertEqual(sent['embed'].title, 'News')
        private = sent['view']
        self.assertFalse(await private.interaction_check(self.interaction(user=999)))
        self.assertTrue(await private.interaction_check(self.interaction()))
        back = next(c for c in private.children if getattr(c, 'label', None) == 'Home')
        returned = self.interaction()
        await back.callback(returned)
        self.assertIsNone(returned.response.edit_message.await_args.kwargs['view'])

    async def test_only_configured_channels_and_guild_can_open(self):
        from fut_panel import InformationPanelView
        panel = InformationPanelView(self.store, PROD, CHANNELS)
        self.assertTrue(panel.is_persistent())
        for i in (self.interaction(guild=TEST_GUILD), self.interaction(channel=999), self.interaction(bot=True)):
            self.assertFalse(await panel.interaction_check(i))
            self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])

    def test_configuration_is_explicit_and_six_channels_required(self):
        base = {'guild_id': TEST_GUILD, 'staff_user_ids': []}
        validate_config(base)
        panels = {'guild_id': PROD, 'channels': CHANNELS, 'database': 'var/information.sqlite3'}
        validate_config({**base, 'information_panels': panels})
        for invalid in ({**panels, 'guild_id': TEST_GUILD},
                        {**panels, 'channels': dict(list(CHANNELS.items())[:5])},
                        {**panels, 'channels': {**CHANNELS, next(iter(CHANNELS)): 'bookmarks'}},
                        {**panels, 'channels': {**CHANNELS, next(iter(CHANNELS)): 'sbc'}},
                        {**panels, 'database': 'var/community.sqlite3'}):
            with self.assertRaises(ValueError):
                validate_config({**base, 'information_panels': invalid})

    async def test_client_rejects_missing_or_shared_information_store(self):
        config = {'guild_id': TEST_GUILD, 'staff_user_ids': [],
                  'information_panels': {'guild_id': PROD, 'channels': CHANNELS,
                                         'database': 'var/information.sqlite3'}}
        for info_store in (None, self.store):
            with self.assertRaises(ValueError):
                build_client(config, self.store, info_store)

    async def test_new_categories_show_their_published_items_privately(self):
        from fut_panel import InformationPanelView
        for offset, kind in ((2, 'evolutions'), (3, 'objectives'), (5, 'store')):
            item = self.store.draft('editor', kind + ' item', kind, 'Body', 'https://example.com/a', 27, 1)
            self.store.approve('editor', item, 2)
            i = self.interaction(channel=200000000000000000 + offset)
            panel = InformationPanelView(self.store, PROD, CHANNELS)
            self.assertTrue(await panel.interaction_check(i))
            await panel.children[0].callback(i)
            sent = i.response.send_message.await_args.kwargs
            self.assertTrue(sent['ephemeral'])
            self.assertEqual(sent['view'].children[0].options[0].label, kind + ' item')

    async def test_empty_category_says_content_is_not_available(self):
        from fut_panel import InformationPanelView
        panel = InformationPanelView(self.store, PROD, CHANNELS)
        i = self.interaction(channel=200000000000000002)
        await panel.children[0].callback(i)
        sent = i.response.send_message.await_args.kwargs
        self.assertTrue(sent['ephemeral'])
        self.assertIn('not available yet', sent['embed'].description.lower())

    async def test_article_opened_from_information_panel_has_no_personal_data_actions(self):
        from fut_panel import InformationPanelView
        panel = InformationPanelView(self.store, PROD, CHANNELS)
        i = self.interaction()
        await panel.children[0].callback(i)
        listing = i.response.send_message.await_args.kwargs['view']
        selector = listing.children[0]
        opened = self.interaction()
        selector._refresh_state(opened, {'values': ['1']})
        await selector.callback(opened)
        article = opened.response.edit_message.await_args.kwargs['view']
        self.assertFalse(any(getattr(child, 'label', None) == 'Save' for child in article.children))

    async def test_panel_creation_is_recorded_and_reconnect_edits_existing(self):
        config = {'guild_id': TEST_GUILD, 'staff_user_ids': [],
                  'information_panels': {'guild_id': PROD, 'channels': CHANNELS,
                                         'database': str(Path(self.tmp.name) / 'data.db')}}
        test_store = CommunityStore(Path(self.tmp.name) / 'test.db', set())
        client = build_client(config, test_store, self.store)
        self.addAsyncCleanup(client.close)
        channels = {}
        for n, channel_id in enumerate(CHANNELS):
            message = SimpleNamespace(id=300000000000000000+n)
            channel = SimpleNamespace(guild=SimpleNamespace(id=PROD), send=AsyncMock(return_value=message),
                                      get_partial_message=MagicMock(return_value=SimpleNamespace(edit=AsyncMock())))
            channels[int(channel_id)] = channel
        client.get_channel = lambda channel_id: channels.get(channel_id)
        await client.setup_information_panels()
        self.assertTrue(all(c.send.await_count == 1 for c in channels.values()))
        await client.setup_information_panels()
        self.assertTrue(all(c.send.await_count == 1 and c.get_partial_message.return_value.edit.await_count == 1
                            for c in channels.values()))

    async def test_interrupted_creation_does_not_send_duplicate(self):
        import json
        config = {'guild_id': TEST_GUILD, 'staff_user_ids': [],
                  'information_panels': {'guild_id': PROD, 'channels': CHANNELS,
                                         'database': str(Path(self.tmp.name) / 'data.db')}}
        test_store = CommunityStore(Path(self.tmp.name) / 'test.db', set())
        client = build_client(config, test_store, self.store)
        self.addAsyncCleanup(client.close)
        marker = Path(self.tmp.name) / 'information-panels.json'
        marker.write_text(json.dumps({next(iter(CHANNELS)): 'pending'}))
        channel = SimpleNamespace(guild=SimpleNamespace(id=PROD), send=AsyncMock(),
                                  get_partial_message=MagicMock(return_value=SimpleNamespace(edit=AsyncMock())))
        client.get_channel = lambda channel_id: channel
        await client.setup_information_panels()
        channel.send.assert_not_awaited()
        channel.get_partial_message.assert_not_called()

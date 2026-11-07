import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

TEST_GUILD = 1565922092518613064


class Provider:
    def __init__(self):
        self.result = dict(title='Product 0', option_label='PC', amount='9.50', currency='USD',
                           price_basis='sale', url='https://www.mmoexp.com/item', queried_at=1700000000)
        self.quoted = []

    def catalog(self, kind):
        return [dict(id=str(i), title='Product {}'.format(i)) for i in range(30)]

    def options(self, product_id):
        return [dict(id='4321', label='PC'), dict(id='5678', label='PlayStation 5')]

    def quote(self, product_id, option_id):
        self.quoted.append((product_id, option_id))
        return self.result.copy()


class QuotePanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_six_categories_expire_refresh_and_guard_without_cross_category(self):
        from discord.ui.view import ViewStore
        from quote_panel import CategoryHomeView, QuoteView, CATEGORIES
        routes = {TEST_GUILD: {100+n: kind for n, kind in enumerate(CATEGORIES)}}
        store = ViewStore(Mock())
        for n, kind in enumerate(CATEGORIES):
            with self.subTest(kind=kind):
                home = CategoryHomeView(self.provider, kind, allowed_routes=routes)
                self.assertTrue(home.is_persistent())
                store.add_view(home)
                home._dispatch_item = Mock(return_value=None)
                panel = QuoteView(self.provider, 1, kind, {'0':'Product'}, allowed_routes=routes)
                i = self.interaction()
                i.channel_id = 100+n
                i.message = SimpleNamespace(id=1000+n)
                panel.interaction = i
                store.add_view(panel, message_id=i.message.id)
                self.assertTrue(await panel.interaction_check(i))
                wrong = self.interaction()
                wrong.channel_id = 100+(n+1)%len(CATEGORIES)
                self.assertFalse(await home.interaction_check(wrong))
                panel.stop()
                await panel.on_timeout()
                refresh = next(c for c in panel.children if isinstance(c, discord.ui.Button)
                               and c.label == 'Refresh quote')
                self.assertEqual(refresh.custom_id, 'fc:quote:'+kind)
                self.assertFalse(refresh.disabled)
                self.assertEqual(str(refresh.emoji), '🔄')
                store.dispatch_view(2, refresh.custom_id, i)
                home._dispatch_item.assert_called_once()

    async def test_expired_panel_clears_price_and_keeps_reopen_and_website(self):
        panel = await self.ready()
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        panel = i.edit_original_response.await_args.kwargs['view']
        i.edit_original_response.reset_mock()
        panel.stop()
        await panel.on_timeout()
        result = i.edit_original_response.await_args.kwargs
        self.assertEqual(result['embed'].title, '⏱️ Quote expired')
        self.assertIn('Tap **🔄 Refresh quote** below', result['embed'].description)
        self.assertEqual(result['embed'].footer.text, 'Private')
        self.assertNotIn('9.50', str(result['embed'].to_dict()))
        self.assertNotIn('1700000000', str(result['embed'].to_dict()))
        self.assertIsNone(panel.quote)
        for item in panel.children:
            if isinstance(item, discord.ui.Button) and item.label in ('Refresh quote', 'Open MMOEXP'):
                self.assertFalse(item.disabled)
            else:
                self.assertTrue(item.disabled)
        i.response.send_message.assert_not_awaited()

    async def test_replacement_stops_old_timer_and_binds_new_interaction(self):
        panel = await self.open_panel()
        original = panel.interaction
        original.edit_original_response.reset_mock()
        result = await self.choose(panel, 'Choose a product', '0')
        self.assertTrue(panel.is_finished())
        self.assertTrue(panel.superseded)
        self.assertFalse(result.is_finished())
        self.assertEqual(result.timeout, 180)
        self.assertIsNot(result.interaction, original)
        await panel.on_timeout()
        original.edit_original_response.assert_not_awaited()

    async def test_reopen_button_uses_persistent_dispatch_after_timeout_and_restart(self):
        from discord.ui.view import ViewStore
        from quote_panel import CategoryHomeView
        panel = await self.open_panel()
        button = next(c for c in panel.children if isinstance(c, discord.ui.Button) and c.label == 'Refresh quote')
        self.assertEqual(button.custom_id, 'fc:quote:sbc')
        self.assertEqual(str(button.emoji), '🔄')
        store = ViewStore(Mock())
        store.add_view(self.home)
        store.add_view(panel, message_id=123)
        i = self.interaction()
        i.message = SimpleNamespace(id=123)
        self.home._dispatch_item = Mock(return_value=None)
        panel.stop()
        store.dispatch_view(2, button.custom_id, i)
        self.home._dispatch_item.assert_called_once()
        # A fresh process has only the category entry registered, no private state.
        fresh = CategoryHomeView(self.provider, 'sbc')
        fresh._dispatch_item = Mock(return_value=None)
        restarted = ViewStore(Mock())
        restarted.add_view(fresh)
        restarted.dispatch_view(2, button.custom_id, i)
        fresh._dispatch_item.assert_called_once()

    async def test_active_reopen_guard_and_fallback_new_owner(self):
        panel = await self.open_panel()
        outsider = self.interaction(user=999)
        await self.press(panel, 'Refresh quote', outsider)
        outsider.response.defer.assert_not_awaited()
        i = self.interaction()
        await self.press(panel, 'Refresh quote', i)
        self.assertTrue(i.response.defer.await_args.kwargs['ephemeral'])
        self.assertEqual(i.edit_original_response.await_args.kwargs['view'].owner, 1)
        # Persistent fallback opens a NEW panel owned by the caller, never old state.
        caller = self.interaction(user=777)
        await self.press(self.home, 'Browse SBC', caller)
        reopened = caller.edit_original_response.await_args.kwargs['view']
        self.assertEqual(reopened.owner, 777)
        self.assertIsNone(reopened.product)
        self.assertIsNone(reopened.quote)
        rejected = self.interaction(guild=99)
        await self.press(self.home, 'Browse SBC', rejected)
        rejected.response.defer.assert_not_awaited()

    async def test_timeout_with_expired_discord_token_does_not_raise(self):
        panel = await self.open_panel()
        panel.interaction.edit_original_response.side_effect = discord.ClientException('expired')
        panel.stop()
        await panel.on_timeout()
        self.assertFalse(next(c for c in panel.children if isinstance(c, discord.ui.Button)
                              and c.label == 'Refresh quote').disabled)

    async def asyncSetUp(self):
        from quote_panel import CategoryHomeView, QUERY_TIMES, QUERY_ORDER
        QUERY_TIMES.clear()
        QUERY_ORDER.clear()
        self.provider = Provider()
        self.home = CategoryHomeView(self.provider, 'sbc')

    def interaction(self, user=1, guild=TEST_GUILD, bot=False):
        return SimpleNamespace(guild_id=guild, channel_id=2, user=SimpleNamespace(id=user, bot=bot),
            response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock(), defer=AsyncMock()),
            edit_original_response=AsyncMock())

    async def press(self, view, label, i):
        if await view.interaction_check(i):
            button = next(c for c in view.children if isinstance(c, discord.ui.Button) and c.label == label)
            await button.callback(i)

    async def select(self, view, placeholder, value, i):
        if await view.interaction_check(i):
            select = next(c for c in view.children if isinstance(c, discord.ui.Select)
                          and c.placeholder == placeholder)
            select._refresh_state(i, {'values': [value]})
            await select.callback(i)

    async def open_panel(self):
        i = self.interaction()
        await self.press(self.home, 'Browse SBC', i)
        self.assertTrue(i.response.defer.await_args.kwargs['ephemeral'])
        return i.edit_original_response.await_args.kwargs['view']

    async def choose(self, view, placeholder, value):
        i = self.interaction()
        await self.select(view, placeholder, value, i)
        return i.response.edit_message.await_args.kwargs['view']

    async def ready(self):
        from quote_panel import QUERY_TIMES, QUERY_ORDER
        QUERY_TIMES.clear()
        QUERY_ORDER.clear()
        view = await self.open_panel()
        view = await self.choose(view, 'Choose a product', '0')
        return await self.choose(view, 'Choose a platform', 'PC')

    async def test_category_cards_are_persistent_and_test_guild_only(self):
        from quote_panel import CategoryHomeView, category_embed
        for kind, label in [('sbc', 'SBC'), ('packs', 'Packs'), ('gallery', 'Gallery')]:
            view = CategoryHomeView(self.provider, kind)
            self.assertTrue(view.is_persistent())
            self.assertEqual(view.children[0].custom_id, 'fc:quote:' + kind)
            self.assertIn(label.lower(), str(category_embed(kind).to_dict()).lower())
        for i in (self.interaction(guild=7), self.interaction(bot=True)):
            await self.press(self.home, 'Browse SBC', i)
            self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])
            i.response.defer.assert_not_awaited()
        panel = await self.open_panel()
        outsider = self.interaction(user=999)
        await self.select(panel, 'Choose a product', '0', outsider)
        self.assertTrue(outsider.response.send_message.await_args.kwargs['ephemeral'])
        outsider.response.edit_message.assert_not_awaited()

    async def test_one_panel_queries_sale_and_reuses_selected_sku_for_refresh(self):
        panel = await self.ready()
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        i.response.defer.assert_awaited_once()
        result = i.edit_original_response.await_args.kwargs
        self.assertEqual(self.provider.quoted, [('0', '4321')])
        text = str(result['embed'].to_dict()).lower()
        self.assertEqual(result['embed'].title, '💰 $9.50 USD')
        self.assertIn('9.50', text)
        self.assertIn('1700000000', text)
        self.assertIn('checkout', text)
        panel = result['view']
        self.assertEqual(len([c for c in panel.children if isinstance(c, discord.ui.Select)]), 2)
        self.assertEqual(next(c.url for c in panel.children if isinstance(c, discord.ui.Button) and c.label == 'Open MMOEXP'),
                         'https://www.mmoexp.com/item')
        self.provider.result['amount'] = '8.25'
        from quote_panel import QUERY_TIMES, QUERY_ORDER
        QUERY_TIMES.clear()
        QUERY_ORDER.clear()
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        self.assertIn('8.25', str(i.edit_original_response.await_args.kwargs['embed'].to_dict()))

    async def test_pagination_retains_platform_and_changing_product_removes_old_link(self):
        panel = await self.ready()
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        panel = i.edit_original_response.await_args.kwargs['view']
        i = self.interaction()
        await self.press(panel, 'Next', i)
        panel = i.response.edit_message.await_args.kwargs['view']
        platform = next(c for c in panel.children if isinstance(c, discord.ui.Select)
                        and c.placeholder == 'Choose a platform')
        self.assertTrue(next(o for o in platform.options if o.value == 'PC').default)
        products = next(c for c in panel.children if isinstance(c, discord.ui.Select)
                        and c.placeholder == 'Choose a product')
        self.assertEqual([o.value for o in products.options], ['25', '26', '27', '28', '29'])
        panel = await self.choose(panel, 'Choose a product', '25')
        from quote_panel import QUERY_TIMES, QUERY_ORDER
        QUERY_TIMES.clear()
        QUERY_ORDER.clear()
        self.assertFalse(any(c.label == 'Open MMOEXP' for c in panel.children if isinstance(c, discord.ui.Button)))
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        self.assertEqual(self.provider.quoted[-1], ('25', '4321'))

    async def test_invalid_or_ambiguous_prices_and_unmatched_platform_are_retryable(self):
        for change in ({'url': 'https://evil.example/item'}, {'url': 'https://user@mmoexp.com/'},
                       {'amount': 'NaN'}, {'amount': '-1'}, {'price_basis': 'original'}):
            with self.subTest(change=change):
                panel = await self.ready()
                old = self.provider.result.copy()
                self.provider.result.update(change)
                i = self.interaction()
                await self.press(panel, 'Get price', i)
                result = i.edit_original_response.await_args.kwargs
                self.assertNotIn('9.50', str(result['embed'].to_dict()))
                self.assertTrue(any(c.label == 'Get price' for c in result['view'].children
                                    if isinstance(c, discord.ui.Button)))
                self.assertFalse(any(c.url for c in result['view'].children if isinstance(c, discord.ui.Button)))
                self.provider.result = old
        panel = await self.ready()
        self.provider.options = lambda _: [dict(id='1', label='PC'), dict(id='2', label='PC')]
        self.provider.quoted.clear()
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        self.assertEqual(self.provider.quoted, [])
        self.assertIn('unavailable', str(i.edit_original_response.await_args.kwargs['embed'].to_dict()).lower())

    async def test_provider_errors_defer_and_allow_retry_without_details(self):
        panel = await self.ready()
        def failure(product):
            raise RuntimeError('private provider error')
        self.provider.options = failure
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        i.response.defer.assert_awaited_once()
        result = i.edit_original_response.await_args.kwargs
        self.assertNotIn('private provider error', str(result['embed'].to_dict()))
        self.assertTrue(any(c.label == 'Get price' for c in result['view'].children
                            if isinstance(c, discord.ui.Button)))


    async def test_changing_platform_removes_old_price_and_link(self):
        panel = await self.ready()
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        panel = i.edit_original_response.await_args.kwargs['view']
        i = self.interaction()
        await self.select(panel, 'Choose a platform', 'PlayStation 5', i)
        result = i.response.edit_message.await_args.kwargs
        self.assertNotIn('9.50', str(result['embed'].to_dict()))
        self.assertFalse(any(c.url for c in result['view'].children if isinstance(c, discord.ui.Button)))

    async def test_unavailable_catalog_can_reload_without_leaking_error(self):
        def failure(kind):
            raise RuntimeError('secret upstream details')
        catalog = self.provider.catalog
        self.provider.catalog = failure
        i = self.interaction()
        await self.press(self.home, 'Browse SBC', i)
        result = i.edit_original_response.await_args.kwargs
        self.assertNotIn('secret upstream details', str(result['embed'].to_dict()))
        self.provider.catalog = catalog
        retry = self.interaction()
        await self.press(result['view'], 'Reload products', retry)
        retry.response.defer.assert_awaited_once()
        panel = retry.edit_original_response.await_args.kwargs['view']
        select = next(c for c in panel.children if isinstance(c, discord.ui.Select)
                      and c.placeholder == 'Choose a product')
        self.assertEqual(len(select.options), 25)

    async def test_unavailable_platform_never_queries_another_sku(self):
        panel = await self.ready()
        self.provider.options = lambda _: [dict(id='5678', label='PlayStation 5')]
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        self.assertEqual(self.provider.quoted, [])
        self.assertIn('unavailable', str(i.edit_original_response.await_args.kwargs['embed'].to_dict()).lower())

    async def test_explicit_routes_limit_category_and_private_panel_to_mapped_channel(self):
        from quote_panel import CategoryHomeView
        routes = {TEST_GUILD: {2: 'sbc', 3: 'packs'}, 88: {40: 'sbc', 41: 'gallery'}}
        public = CategoryHomeView(self.provider, 'sbc', allowed_routes=routes)
        for i in (self.interaction(guild=88), self.interaction(guild=77)):
            await self.press(public, 'Browse SBC', i)
            i.response.defer.assert_not_awaited()
            self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])
        wrong_kind = self.interaction(guild=88)
        wrong_kind.channel_id = 41
        await self.press(public, 'Browse SBC', wrong_kind)
        wrong_kind.response.defer.assert_not_awaited()
        authorized = self.interaction(guild=88)
        authorized.channel_id = 40
        await self.press(public, 'Browse SBC', authorized)
        self.assertTrue(authorized.response.defer.await_args.kwargs['ephemeral'])
        panel = authorized.edit_original_response.await_args.kwargs['view']
        moved = self.interaction(guild=88)
        moved.channel_id = 41
        await self.select(panel, 'Choose a product', '0', moved)
        moved.response.edit_message.assert_not_awaited()
        self.assertTrue(moved.response.send_message.await_args.kwargs['ephemeral'])
        owner = self.interaction(guild=88)
        owner.channel_id = 40
        await self.select(panel, 'Choose a product', '0', owner)
        self.assertIsNotNone(owner.response.edit_message.await_args.kwargs['view'])

    async def test_empty_explicit_routes_never_enable_the_test_guild(self):
        from quote_panel import CategoryHomeView
        public = CategoryHomeView(self.provider, 'sbc', allowed_routes={})
        i = self.interaction()
        await self.press(public, 'Browse SBC', i)
        i.response.defer.assert_not_awaited()
        self.assertTrue(i.response.send_message.await_args.kwargs['ephemeral'])


    async def test_provider_calls_reject_immediately_at_capacity(self):
        import asyncio
        import threading
        from quote_panel import call_provider, ProviderBusy
        started = threading.Semaphore(0)
        release = threading.Event()
        def work():
            started.release()
            release.wait(2)
        tasks = [asyncio.create_task(call_provider(work)) for _ in range(3)]
        try:
            for _ in range(3):
                self.assertTrue(await asyncio.to_thread(started.acquire, True, 1))
            with self.assertRaises(ProviderBusy):
                await asyncio.wait_for(call_provider(work), timeout=0.2)
        finally:
            release.set()
            await asyncio.gather(*tasks)

    async def test_quote_rate_limit_is_private_and_busy_keeps_panel_retryable(self):
        import quote_panel
        panel = await self.ready()
        first = self.interaction()
        await self.press(panel, 'Get price', first)
        panel = first.edit_original_response.await_args.kwargs['view']
        again = self.interaction()
        await self.press(panel, 'Get price', again)
        self.assertTrue(again.response.send_message.await_args.kwargs['ephemeral'])
        self.assertIn('wait', str(again.response.send_message.await_args).lower())
        self.assertEqual(len(self.provider.quoted), 1)
        quote_panel.QUERY_TIMES.clear()
        quote_panel.QUERY_ORDER.clear()
        for _ in range(3):
            self.assertTrue(quote_panel.PROVIDER_LIMIT.acquire(blocking=False))
        try:
            busy = self.interaction()
            await self.press(panel, 'Get price', busy)
            result = busy.edit_original_response.await_args.kwargs
            self.assertIn('busy', str(result['embed'].to_dict()).lower())
            self.assertTrue(any(isinstance(c, discord.ui.Button) and c.label == 'Get price'
                                for c in result['view'].children))
        finally:
            for _ in range(3):
                quote_panel.PROVIDER_LIMIT.release()
        retry = self.interaction()
        await self.press(result['view'], 'Get price', retry)
        self.assertEqual(len(self.provider.quoted), 2)

    async def test_rate_limit_expires_and_storage_is_bounded(self):
        from unittest.mock import patch
        import quote_panel
        with patch('quote_panel.time.monotonic', side_effect=[1, 2, 5, 5, 5]), \
                patch('quote_panel.MAX_QUERY_USERS', 2):
            self.assertIsNotNone(quote_panel.begin_query(10))
            self.assertIsNone(quote_panel.begin_query(10))
            self.assertIsNotNone(quote_panel.begin_query(10))
            self.assertIsNotNone(quote_panel.begin_query(11))
            self.assertIsNotNone(quote_panel.begin_query(12))
        self.assertLessEqual(len(quote_panel.QUERY_TIMES), 2)
        self.assertLessEqual(len(quote_panel.QUERY_ORDER), 2)

    async def ready_kind(self, kind, label, selection='0', placeholder='Choose a product'):
        from quote_panel import CategoryHomeView, QUERY_TIMES, QUERY_ORDER
        QUERY_TIMES.clear()
        QUERY_ORDER.clear()
        home = CategoryHomeView(self.provider, kind)
        i = self.interaction()
        await self.press(home, 'Browse ' + label, i)
        panel = i.edit_original_response.await_args.kwargs['view']
        if kind == 'boosting':
            placeholder = 'Choose a service'
        panel = await self.choose(panel, placeholder, selection)
        return await self.choose(panel, 'Choose a platform', 'PC')

    async def test_new_categories_have_persistent_cards_and_route_guards(self):
        from quote_panel import CategoryHomeView, category_embed
        for kind, name, emoji in [('evolutions', 'Evolutions', '🧬'),
                                   ('boosting', 'Boosting', '🏆'), ('coins', 'Coins', '🪙')]:
            with self.subTest(kind=kind):
                home = CategoryHomeView(self.provider, kind, allowed_routes={88: {40: kind}})
                self.assertTrue(home.is_persistent())
                self.assertEqual(home.children[0].custom_id, 'fc:quote:' + kind)
                self.assertEqual(category_embed(kind).title, name)
                self.assertIn(emoji, category_embed(kind).description)
                self.assertFalse(category_embed(kind).fields)
                wrong = self.interaction(guild=88)
                await self.press(home, 'Browse ' + name, wrong)
                wrong.response.defer.assert_not_awaited()
                allowed = self.interaction(guild=88)
                allowed.channel_id = 40
                await self.press(home, 'Browse ' + name, allowed)
                self.assertTrue(allowed.response.defer.await_args.kwargs['ephemeral'])
                private = allowed.edit_original_response.await_args.kwargs['view']
                denied = self.interaction(user=99, guild=88)
                denied.channel_id = 40
                self.assertFalse(await private.interaction_check(denied))

    async def test_coins_shows_selectable_amount_and_delivered_bonus_in_quote(self):
        self.provider.catalog = lambda kind: [dict(id='100', title='100K'), dict(id='500', title='500K'),
            dict(id='1000', title='1000K'), dict(id='2000', title='2000K'), dict(id='5000', title='5000K')]
        self.provider.result['title'] = '100K + 5K bonus = 105K delivered'
        panel = await self.ready_kind('coins', 'Coins', '100', 'Choose an amount')
        amount = next(c for c in panel.children if isinstance(c, discord.ui.Select)
                      and c.placeholder == 'Choose an amount')
        self.assertEqual([o.label for o in amount.options], ['100K', '500K', '1000K', '2000K', '5000K'])
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        content = str(i.edit_original_response.await_args.kwargs['embed'].to_dict())
        self.assertIn('100K + 5K bonus = 105K delivered', content)
        self.assertEqual(i.edit_original_response.await_args.kwargs['embed'].title, '💰 $9.50 USD')

    async def test_boosting_is_from_price_with_website_options_not_a_sale_total(self):
        from quote_panel import category_embed
        self.provider.result.update(title='Boosting service', price_basis='from')
        panel = await self.ready_kind('boosting', 'Boosting')
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        content = str(i.edit_original_response.await_args.kwargs['embed'].to_dict())
        self.assertIn('From $9.50', content)
        self.assertIn('website', content.lower())
        self.assertNotIn('Sale price', content)
        self.assertIn('starting', str(category_embed('boosting').to_dict()).lower())

    async def test_price_basis_is_specific_to_category(self):
        for kind, label, basis in [('boosting', 'Boosting', 'sale'), ('boosting', 'Boosting', 'original'),
                                   ('evolutions', 'Evolutions', 'from'), ('coins', 'Coins', 'from')]:
            with self.subTest(kind=kind, basis=basis):
                self.provider.result['price_basis'] = basis
                panel = await self.ready_kind(kind, label, placeholder='Choose an amount' if kind == 'coins'
                                              else 'Choose a product')
                i = self.interaction()
                await self.press(panel, 'Get price', i)
                result = i.edit_original_response.await_args.kwargs
                self.assertIn('unavailable', str(result['embed'].to_dict()).lower())
                self.assertFalse(any(c.url for c in result['view'].children if isinstance(c, discord.ui.Button)))


    async def test_evolutions_displays_sale_price(self):
        self.provider.result.update(title='Evolution service', price_basis='sale')
        panel = await self.ready_kind('evolutions', 'Evolutions')
        i = self.interaction()
        await self.press(panel, 'Get price', i)
        result = i.edit_original_response.await_args.kwargs
        self.assertEqual(result['embed'].title, '💰 $9.50 USD')
        self.assertTrue(any(c.url for c in result['view'].children if isinstance(c, discord.ui.Button)))

    async def test_price_layout_promotes_price_and_displays_product_once_with_platform_and_clock(self):
        from quote_panel import panel_embed
        panel = await self.ready()
        interaction = self.interaction()
        await self.press(panel, 'Get price', interaction)
        embed = interaction.edit_original_response.await_args.kwargs['embed']
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn('🎮  Platform', fields)
        self.assertIn('🖥️ PC', fields['🎮  Platform'])
        self.assertEqual(embed.title, '💰 $9.50 USD')
        self.assertEqual(str(embed.to_dict()).count('Product 0'), 1)
        self.assertEqual(str(embed.to_dict()).count('9.50'), 1)
        self.assertEqual(len(fields), 2)
        self.assertIn('1700000000', fields['🕒  Last checked'])
        self.assertNotIn('Source', str(fields))
        self.assertNotIn('Quote', str(fields))
        self.assertIn('Private', embed.footer.text)

    async def test_optional_presentation_survives_selections_and_reload(self):
        from quote_panel import CategoryHomeView, category_embed
        presentation = {'emoji': {'PC': '⌨️', 'PlayStation 5': '🎮', 'Xbox Series X|S': '🟢'},
                        'avatar_url': 'https://cdn.discordapp.com/avatars/owned.png',
                        'banner_url': 'https://cdn.discordapp.com/attachments/owned.png'}
        self.home = CategoryHomeView(self.provider, 'sbc', presentation=presentation)
        panel = await self.ready()
        platforms = next(child for child in panel.children if isinstance(child, discord.ui.Select)
                         and child.placeholder == 'Choose a platform')
        self.assertEqual(str(platforms.options[0].emoji), '⌨️')
        interaction = self.interaction()
        await self.press(panel, 'Reload products', interaction)
        embed = interaction.edit_original_response.await_args.kwargs['embed']
        self.assertEqual(embed.thumbnail.url, presentation['avatar_url'])
        self.assertFalse(embed.image.url)
        self.assertFalse(category_embed('sbc', presentation).image.url)

    async def test_custom_icons_survive_private_quote_flow_and_serialize_as_application_emoji(self):
        from quote_panel import CategoryHomeView, category_embed
        icons = {name: '<:fc_{}:1568661000000000001>'.format(name)
                 for name in ('sbc', 'coins', 'clock', 'search', 'external', 'platform')}
        presentation = {'icons': icons, 'banner_url': 'https://cdn.discordapp.com/banner.png'}
        self.home = CategoryHomeView(self.provider, 'sbc', presentation=presentation)
        self.assertEqual(self.home.children[0].to_component_dict()['emoji']['id'], 1568661000000000001)
        public = category_embed('sbc', presentation)
        self.assertIn(icons['sbc'], public.description)
        self.assertNotIn('<:', public.title)
        self.assertFalse(public.image.url)
        panel = await self.ready()
        interaction = self.interaction()
        await self.press(panel, 'Get price', interaction)
        result = interaction.edit_original_response.await_args.kwargs
        fields = {field.name: field.value for field in result['embed'].fields}
        self.assertEqual(result['embed'].title, '💰 $9.50 USD')
        self.assertIn('<t:1700000000:f>', fields[icons['clock'] + '  Last checked'])
        self.assertEqual(len(fields), 2)
        buttons = {child.label: child for child in result['view'].children if isinstance(child, discord.ui.Button)}
        self.assertEqual(str(buttons['Get price'].emoji), icons['search'])
        self.assertEqual(str(buttons['Open MMOEXP'].emoji), icons['external'])
        self.assertFalse(result['embed'].image.url)
        outsider = self.interaction(user=99)
        self.assertFalse(await result['view'].interaction_check(outsider))

    async def test_malformed_or_missing_custom_icons_fall_back_without_broken_components(self):
        from quote_panel import CategoryHomeView, category_embed
        for value in ('https://example.com/icon.png', '<:wrong:123>', '@everyone', '', None):
            presentation = {'icons': {'sbc': value}}
            home = CategoryHomeView(self.provider, 'sbc', presentation=presentation)
            self.assertEqual(str(home.children[0].emoji), '🧩')
            self.assertTrue(category_embed('sbc', presentation).description.startswith('🧩'))

    async def test_error_render_never_displays_a_stale_price_or_checked_timestamp(self):
        from quote_panel import panel_embed
        panel = await self.ready()
        panel.quote = self.provider.result.copy()
        rendered = panel_embed(panel, 'Price is unavailable. Please try again.')
        text = str(rendered.to_dict())
        self.assertNotIn('9.50', text)
        self.assertNotIn('1700000000', text)
        self.assertIn('unavailable', rendered.description)

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from player_service import ProductProvider, validate_player_config
from quote_bridge import dispatch
from tests.test_player_catalog import Client, goods, model


def config():
    return dict(enabled=True, guild_id=1565922092518613064, channel_id=1568610700463710278,
                featured_model_ids=[101], allowed_tag_ids=[12], verified_prices={'101': [21587]})


class ServiceTests(unittest.TestCase):
    def test_bridge_to_live_sale_and_configuration_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            cfg = config()
            path.write_text(json.dumps({'player_panel': cfg}))
            base = Mock()
            client = Client()
            client.row.update(price='7', unit_price='10', discount=70)
            service = ProductProvider(base, client, path, client)
            self.assertEqual(dispatch(service, {'action': 'player_search', 'args': ['Haaland', 1]})['items'][0]['id'], 'players:101')
            self.assertEqual(service.catalog('players')[0]['id'], 'players:101')
            option = service.options('players:101')[0]['id']
            self.assertEqual(service.quote('players:101', option)['amount'], '7.00')
            service.catalog('packs')
            base.catalog.assert_called_once_with('packs')
            cfg['verified_prices'] = {}
            path.write_text(json.dumps({'player_panel': cfg}))
            self.assertEqual(len(service.options('players:101')), 1)
            cfg['enabled'] = False
            path.write_text(json.dumps({'player_panel': cfg}))
            with self.assertRaises(ValueError):
                service.player_search('Haaland', 1)

    def test_empty_featured_list_uses_admin_recommendation_with_pagination(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            cfg = config()
            cfg['featured_model_ids'] = []
            path.write_text(json.dumps({'player_panel': cfg}))
            client = Client()
            client.models[0]['is_rec'] = 0
            client.models[1]['is_rec'] = 1
            service = ProductProvider(Mock(), client, path, client)
            result = dispatch(service, {'action': 'player_featured', 'args': [1]})
            self.assertEqual([r['id'] for r in result['items']], ['players:102'])
            for invalid in (True, 0, 201, '1'):
                with self.assertRaises(ValueError):
                    dispatch(service, {'action': 'player_featured', 'args': [invalid]})

    def test_explicit_easysbc_configuration_is_data_only_and_version_specific(self):
        from player_config import validate_easysbc_config
        value = dict(template='card', selection='tags', tag_match='any', mappings=[
            dict(model_id=101, easysbc_id='50524153', easysbc_role_id='44', easysbc_url='')])
        self.assertEqual(validate_easysbc_config(value), value)
        validate_easysbc_config(dict(value, with_card=True))
        with self.assertRaises(ValueError):
            validate_easysbc_config(dict(value, with_card='true'))
        for template in ('card', 'price', 'info', 'meta'):
            validate_easysbc_config(dict(value, template=template))
        for change in ({'template': 'unknown'}, {'selection': 'all'}, {'auto_send': True},
                       {'mappings': [dict(value['mappings'][0], easysbc_role_id='')]},
                       {'mappings': [dict(value['mappings'][0], easysbc_url='https://evil.example/card')]}):
            with self.assertRaises(ValueError):
                validate_easysbc_config(dict(value, **change))
        two_roles = value['mappings'] + [dict(value['mappings'][0], model_id=102, easysbc_role_id='45')]
        validate_easysbc_config(dict(value, mappings=two_roles))
        with self.assertRaises(ValueError):
            validate_easysbc_config(dict(value, mappings=value['mappings'] + [dict(value['mappings'][0], model_id=102)]))

    def test_specific_preview_revalidates_selection_and_live_options(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            cfg = config()
            path.write_text(json.dumps({'player_panel': cfg}))
            client = Client()
            service = ProductProvider(Mock(), client, path, client)
            self.assertEqual(dispatch(service, {'action': 'player_preview', 'args': ['101']})['id'], 'players:101')
            with self.assertRaises(ValueError):
                service.player_preview('102')
            client.row['status'] = 0
            with self.assertRaises(ValueError):
                service.player_preview('101')

    def test_management_search_selection_and_named_tags_are_narrow_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            cfg = config()
            cfg.update(enabled=False, allowed_tag_ids=[], featured_model_ids=[101, 999])
            path.write_text(json.dumps({'player_panel': cfg}))
            client = Client()
            service = ProductProvider(Mock(), client, path, client)
            rows = dispatch(service, {'action': 'player_manage_search', 'args': ['Haaland', 1]})['items']
            self.assertEqual([r['model_id'] for r in rows], [101, 102])
            self.assertEqual(rows[0]['verified_platforms'], ['PlayStation 5'])
            self.assertEqual(rows[1]['verified_platforms'], [])
            self.assertEqual(rows[0]['goods_availability'], 'not_checked')
            self.assertEqual(service.player_manage_search('102', 1)['items'][0]['model_id'], 102)
            client.models[0]['status'] = 0
            self.assertFalse(service.player_manage_search('101', 1)['items'][0]['model_available'])
            self.assertEqual(service.player_manage_selection()[1]['model_id'], 999)
            self.assertFalse(service.player_manage_selection()[1]['model_available'])
            self.assertEqual(dispatch(service, {'action': 'player_manage_tags', 'args': []}), [{'id': '12', 'name': 'Popular'}])
            with self.assertRaises(ValueError):
                service.player_search('Haaland', 1)
            for args in (['%abc', 1], ['abc', True], ['abc', 11], ['../admin', 0]):
                with self.assertRaises(ValueError):
                    dispatch(service, {'action': 'player_manage_search', 'args': args})
            client.models[1]['cid'] = 9625
            with self.assertRaises(ValueError):
                service.player_manage_search('102', 1)

    def test_signature_quotes_use_real_verified_standard_goods_and_never_relabel_price(self):
        class MultiClient(Client):
            def __init__(self):
                super().__init__()
                self.goods = {201: goods(101), 202: dict(goods(102), id=202, title=self.models[1]['title'], price='10', unit_price='10')}
            def list_goods(self, **kwargs):
                rows=[row for row in self.goods.values() if row['mid']==kwargs['mid']]
                return SimpleNamespace(rows=rows,total=len(rows))
            def get_goods(self, goods_id):
                return self.goods[goods_id].copy()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            cfg=config();cfg['verified_prices']['102']=[21587]
            path.write_text(json.dumps({'player_panel':cfg}))
            client=MultiClient();service=ProductProvider(Mock(),client,path,client)
            self.assertEqual(service.options('players:102'), [{'id':'201','label':'PlayStation 5'}])
            quote=service.quote('players:102','201')
            self.assertEqual(quote['amount'],'4.41')
            self.assertEqual(quote['quoted_product_id'],'players:101')
            self.assertNotIn('Signature',quote['title'])
            with self.assertRaises(ValueError):service.quote('players:102','202')
            self.assertEqual(client.goods[202]['price'],'10')
            # Broken signature inventory must not discard the verified ordinary option.
            original_list_goods = client.list_goods
            def broken_signature(**kwargs):
                if kwargs['mid'] == 102:
                    return SimpleNamespace(rows=[], total=1)
                return original_list_goods(**kwargs)
            client.list_goods = broken_signature
            self.assertEqual(service.options('players:102'), [{'id':'201','label':'PlayStation 5'}])
            self.assertEqual(service.quote('players:102','201')['amount'], '4.41')
            with self.assertRaises(ValueError):
                service.quote('players:102','202')
            client.list_goods = original_list_goods
            cfg['verified_prices']={'102':[21587]}
            path.write_text(json.dumps({'player_panel':cfg}))
            self.assertEqual(service.options('players:102'), [{'id':'201','label':'PlayStation 5'}])
            self.assertEqual(service.quote('players:102','201')['amount'],'4.41')
            cfg['verified_prices']['101']=[21587]
            path.write_text(json.dumps({'player_panel':cfg}))
            client.models.append(model(103))
            self.assertEqual(service.options('players:102'), [{'id':'202','label':'PlayStation 5'}])

    def test_invalid_configuration_and_queries_never_reach_provider(self):
        for change in ({'enabled': 1}, {'guild_id': 1}, {'channel_id': True},
                       {'verified_prices': {'101': [1]}}, {'featured_model_ids': [101, 101]}):
            with self.assertRaises(ValueError):
                validate_player_config({**config(), **change})
        provider = Mock()
        for args in (['Haaland', True], ['%ha', 1], ['ha', 11], ['ha', 0]):
            with self.assertRaises(ValueError):
                dispatch(provider, {'action': 'player_search', 'args': args})
        provider.player_search.assert_not_called()


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_panel_preserves_context_and_private_owner(self):
        from player_panel import PlayerHomeView, PlayerQuoteView, load_players
        provider = Mock()
        provider.player_search.return_value = {'items': [{'id': 'players:101', 'title': 'Haaland/91/ST/Gold'}], 'has_more': True}
        routes = {config()['guild_id']: {config()['channel_id']: 'players'}}
        home = PlayerHomeView(provider, routes)
        self.assertTrue(home.is_persistent())
        interaction = SimpleNamespace(user=SimpleNamespace(id=90123456, bot=False), guild_id=config()['guild_id'],
                                      channel_id=config()['channel_id'], response=SimpleNamespace(send_message=AsyncMock()),
                                      edit_original_response=AsyncMock())
        await load_players(interaction, home, 'search', 'Haaland', 1)
        panel = interaction.edit_original_response.call_args.kwargs['view']
        self.assertIsInstance(panel, PlayerQuoteView)
        self.assertTrue(await panel.interaction_check(interaction))
        interaction.user.id += 1
        self.assertFalse(await panel.interaction_check(interaction))
        copied = panel.copy(product='players:101', platform='PlayStation 5')
        self.assertEqual((copied.search_query, copied.has_more), ('Haaland', True))
        copied.interaction = interaction
        await copied.on_timeout()
        refresh = next(c for c in copied.children if c.custom_id == 'fc:quote:players')
        self.assertFalse(refresh.disabled)
        self.assertTrue(all(c.disabled for c in copied.children if c.custom_id != 'fc:quote:players'))
        panel.stop()
        copied.stop()
        home.stop()

    async def test_specific_player_button_opens_only_private_preselected_quote(self):
        from player_panel import PlayerCardView
        provider = Mock()
        provider.player_preview.return_value = {'id': 'players:101', 'title': 'Haaland/91/ST/Gold'}
        routes = {config()['guild_id']: {config()['channel_id']: 'players'}}
        view = PlayerCardView(provider, 101, routes)
        self.assertTrue(view.is_persistent())
        interaction = SimpleNamespace(user=SimpleNamespace(id=90123555, bot=False), guild_id=config()['guild_id'],
                                      channel_id=config()['channel_id'], response=SimpleNamespace(defer=AsyncMock()),
                                      edit_original_response=AsyncMock())
        await view.open_player(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        panel = interaction.edit_original_response.call_args.kwargs['view']
        self.assertEqual(panel.product, 'players:101')
        self.assertEqual(panel.owner, interaction.user.id)
        self.assertIsNone(panel.platform)
        panel.stop()
        view.stop()

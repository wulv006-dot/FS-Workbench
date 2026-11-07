import unittest
from types import SimpleNamespace

from player_catalog import PlayerCatalog


def model(mid=101, title='Erling Haaland/91/ST++/Gold Non Rare'):
    return {'id': mid, 'gid': 1327, 'cid': 9627, 'status': 1, 'is_put': 1,
            'title': title, 'more': {'extend': [{'key': 'player_id', 'value': '1'}]}}


def goods(mid=101, aid=21587):
    return {'id': 201, 'mid': mid, 'gid': 1327, 'cid': 9627, 'aid': aid,
            'site_id': 266, 'title': model(mid)['title'], 'status': 1, 'num': 1,
            'sku_switch': 0, 'attr_switch': 1, 'auto_off': 0, 'total': 0, 'price': '4.40501',
            'unit_price': '4.40501', 'discount': 100,
            'more': {'saleprop': [], 'skuTableSet': []}}


class Client:
    def __init__(self):
        self.models = [model(), model(102, 'Erling Haaland/91/ST++/Gold Non Rare/Signature')]
        self.row = goods()
        self.calls = []

    def category_tree(self, **kwargs):
        return [{'id': 9627}]

    def list_models(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(rows=self.models[:kwargs['limit']], total=len(self.models))

    def list_tags(self, **kwargs):
        return [{'id': 12, 'name': 'Popular', 'gid': 1327, 'cate_id': ['9627'], 'status': 1},
                {'id': 13, 'name': 'Disabled', 'gid': 1327, 'cate_id': ['9627'], 'status': 0}]

    def get_model(self, mid):
        return {'data': {'row': next(r for r in self.models if r['id'] == mid)}}

    def list_goods(self, **kwargs):
        return SimpleNamespace(rows=[self.row], total=1)

    def get_goods(self, goods_id):
        return dict(self.row)


class PlayerCatalogTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.catalog = PlayerCatalog(self.client)

    def test_bounded_search_keeps_variants_and_separate_futbin_id(self):
        result = self.catalog.search('Haaland', limit=2)
        self.assertEqual([x['id'] for x in result['items']], ['players:101', 'players:102'])
        self.assertEqual(result['items'][0]['rating'], 91)
        self.assertEqual(result['items'][1]['card_type'], 'Signature')
        self.assertEqual(result['items'][0]['futbin_player_id'], '1')
        self.assertEqual(self.client.calls[0]['limit'], 2)
        for query in ('', 'x', '%a', 'a_b', 'a' * 81, 'a\nb'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.catalog.search(query)
        with self.assertRaises(ValueError):
            self.catalog.search('Haaland', limit=26)

    def test_featured_consumes_explicit_ids_and_rejects_wrong_category(self):
        result = self.catalog.featured([102, 101])
        self.assertEqual([x['id'] for x in result], ['players:102', 'players:101'])
        self.client.models[0]['cid'] = 9625
        with self.assertRaises(ValueError):
            self.catalog.featured([101])
        with self.assertRaises(ValueError):
            self.catalog.featured([101, 101])

    def test_quotes_default_closed_and_verified_price_is_live_sale(self):
        self.assertEqual(self.catalog.options('players:101'), [])
        with self.assertRaises(ValueError):
            self.catalog.quote('players:101', '201')
        catalog = PlayerCatalog(self.client, verified_prices={101: [21587]})
        self.assertEqual(catalog.options('players:101'), [{'id': '201', 'label': 'PlayStation 5'}])
        self.assertEqual(catalog.quote('players:101', '201')['amount'], '4.41')
        self.client.row['price'] = self.client.row['unit_price'] = '5.1'
        self.assertEqual(catalog.quote('players:101', '201')['amount'], '5.10')

    def test_quote_rejects_unverified_or_complex_goods(self):
        catalog = PlayerCatalog(self.client, verified_prices={101: [21587]})
        for change in ({'aid': 21589}, {'site_id': 0}, {'mid': 102}, {'status': 0},
                       {'sku_switch': 1}, {'attr_switch': 0}, {'num': 2},
                       {'price': 'NaN'}, {'price': '1'},
                       {'more': {'saleprop': [{'price': 1}], 'skuTableSet': []}},
                       {'more': {}}, {'title': 'different'}):
            original = self.client.row
            self.client.row = {**original, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                catalog.quote('players:101', '201')
            self.client.row = original

    def test_stock_contract_distinguishes_unlimited_from_auto_off_stock(self):
        catalog = PlayerCatalog(self.client, verified_prices={101: [21587]})
        # Live contract: auto_off=0 / total=0 is not an out-of-stock product.
        self.assertEqual(catalog.quote('players:101', '201')['amount'], '4.41')
        self.client.row.update(auto_off=1, total='1')
        self.assertEqual(catalog.quote('players:101', '201')['amount'], '4.41')
        for change in ({'total': 0}, {'total': '-1'}, {'total': 'NaN'}, {'total': True},
                       {'auto_off': 2}, {'auto_off': None}, {'total': None}):
            original = self.client.row
            self.client.row = {**original, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                catalog.quote('players:101', '201')
            self.client.row = original
        for key in ('total', 'auto_off'):
            original = self.client.row
            self.client.row = {k: v for k, v in original.items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValueError):
                catalog.quote('players:101', '201')
            self.client.row = original
        self.client.models[0]['status'] = 0
        with self.assertRaises(ValueError):
            catalog.quote('players:101', '201')

    def test_tag_browsing_is_configured_and_filters_one_bounded_page(self):
        self.client.models[0]['tid'] = ['12']
        self.client.models[1]['tid'] = ['13']
        catalog = PlayerCatalog(self.client, tag_client=self.client, allowed_tag_ids=[12, 13])
        self.assertEqual(catalog.tags(), [{'id': '12', 'name': 'Popular'}])
        result = catalog.browse_tag(12, limit=2)
        self.assertEqual([item['id'] for item in result['items']], ['players:101'])
        with self.assertRaises(ValueError):
            catalog.browse_tag(13)


    def test_recommended_uses_admin_flag_and_keeps_raw_page_cursor(self):
        self.client.models[0]['is_rec'] = 0
        self.client.models[1]['is_rec'] = '1'
        result = self.catalog.recommended(limit=1)
        self.assertEqual(result['items'], [])
        self.assertTrue(result['has_more'])
        result = self.catalog.recommended(limit=2)
        self.assertEqual([r['id'] for r in result['items']], ['players:102'])
        self.client.models[1]['status'] = 0
        self.assertEqual(self.catalog.recommended(limit=2)['items'], [])

    def test_tag_ids_can_use_the_existing_comma_separated_contract(self):
        self.client.models[0]['tid'] = '12,13'
        catalog = PlayerCatalog(self.client, tag_client=self.client, allowed_tag_ids=[12])
        self.assertEqual(catalog.browse_tag(12)['items'][0]['id'], 'players:101')


if __name__ == '__main__':
    unittest.main()

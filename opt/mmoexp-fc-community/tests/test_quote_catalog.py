import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from quote_catalog import QuoteCatalog


SAMPLE = json.loads((Path(__file__).parent / 'fixtures/fs_pack_sample.json').read_text(encoding='utf-8'))


class Client:
    def __init__(self):
        self.rows = [dict(SAMPLE)]
        self.model = {'id': SAMPLE['mid'], 'gid': 1327, 'cid': 10255, 'status': 1}
        self.models = {}
        self.calls = []

    def category_tree(self, **kwargs):
        return ({'id': 9629, 'children': [{'id': 10255}]},
                {'id': 9625, 'children': [{'id': 10203}]},
                {'id': 9623},
                {'id': 9825, 'children': [{'id': 10397}, {'id': 10399}]},
                {'id': 108, 'children': [
                    {'id': 10211, 'children': [{'id': 10213}]},
                    {'id': 10063, 'children': [{'id': 10067}]},
                    {'id': 9703, 'children': [{'id': 9711}, {'id': 9963}]},
                    {'id': 10445}, {'id': 10265}, {'id': 9999}]})

    def list_goods(self, **kwargs):
        self.calls.append(kwargs)
        rows = [r for r in self.rows if kwargs.get('mid', r['mid']) == r['mid']]
        offset = (kwargs['page'] - 1) * kwargs['limit']
        return SimpleNamespace(rows=rows[offset:offset + kwargs['limit']], total=len(rows))

    def get_goods(self, goods_id):
        return next(dict(r) for r in self.rows if r['id'] == goods_id)

    def get_model(self, model_id):
        return {'data': {'row': dict(self.models.get(model_id, self.model))}}


class QuoteCatalogTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.catalog = QuoteCatalog(self.client)

    def test_uses_actual_sale_price_not_strikethrough_price(self):
        self.assertEqual(self.catalog.catalog('packs'), [{'id': 'packs:44656527', 'title': 'ManCity11-PlayerBundle'}])
        self.assertEqual(self.catalog.options('packs:44656527'), [{'id': '185327195', 'label': 'PlayStation 5'}])
        q = self.catalog.quote('packs:44656527', '185327195')
        self.assertEqual((q['amount'], q['currency'], q['price_basis']), ('8.21', 'USD', 'sale'))
        self.assertEqual(q['url'], 'https://www.mmoexp.com/Fc-27/Packs/In-game-packs.html')
        self.assertIsInstance(q['queried_at'], int)

    def test_rejects_wrong_site_model_and_options(self):
        for change in ({'site_id': 0}, {'status': 0}, {'is_put': 0}, {'sku_switch': 1},
                       {'attr_switch': 1}, {'sku_switch': 0.5}, {'status': 1.5},
                       {'num': 2}, {'num': 1.5}, {'unit_price': 0},
                       {'unit_price': 'NaN'}, {'discount': 0}, {'aid': 999},
                       {'price': 0}, {'cid': 999}, {'gid': 1}):
            with self.subTest(change=change):
                self.client.rows = [{**SAMPLE, **change}]
                with self.assertRaises(ValueError):
                    self.catalog.quote('packs:44656527', '185327195')
        self.client.rows = [dict(SAMPLE)]
        self.client.model['status'] = 0
        with self.assertRaises(ValueError):
            self.catalog.quote('packs:44656527', '185327195')
        with self.assertRaises(ValueError):
            self.catalog.quote('packs:1', '185327195')

    def test_catalog_paginates_and_other_categories_are_not_assumed(self):
        self.client.rows = [{**SAMPLE, 'id': 1000000 + i, 'mid': 2000000 + i, 'title': str(i)} for i in range(205)]
        self.assertEqual(len(self.catalog.catalog('packs')), 205)
        self.assertGreaterEqual(len(self.client.calls), 2)
        self.assertEqual(self.catalog.catalog('players'), [])

    def test_gallery_packages_remain_distinct_and_sbc_quote_has_no_discount(self):
        self.client.rows = [
            {**SAMPLE, 'id': 184515837, 'mid': 44284075, 'cid': 10213,
             'title': 'From 0 to 500 Tokens', 'price': 23.45, 'unit_price': 23.45, 'discount': 100},
            {**SAMPLE, 'id': 178574883, 'mid': 43861869, 'cid': 10067,
             'title': 'From 0 to 500 Tokens', 'price': 36.65, 'unit_price': 36.65, 'discount': 100},
        ]
        products = self.catalog.catalog('gallery')
        self.assertEqual(len(products), 2)
        self.assertNotEqual(products[0]['title'], products[1]['title'])
        self.client.model.update(id=44284075, cid=10213)
        gallery_quote = self.catalog.quote('gallery:44284075', '184515837')
        self.assertIn('Your Coins', gallery_quote['title'])
        self.assertTrue(gallery_quote['url'].endswith('/Gallery-your-coins.html'))
        self.client.rows = [{**SAMPLE, 'id': 187292685, 'mid': 45498255, 'cid': 10203,
                             'title': 'Loïs Openda', 'price': 10.03141,
                             'unit_price': 10.03141, 'discount': 100}]
        self.client.model.update(id=45498255, cid=10203)
        self.assertEqual(self.catalog.quote('sbc:45498255', '187292685')['amount'], '10.03')
        self.client.rows[0].update(price=7, unit_price=10, discount=70)
        with self.assertRaises(ValueError):
            self.catalog.quote('sbc:45498255', '187292685')

    def test_evolutions_supports_simple_product(self):
        self.client.rows = [{**SAMPLE, 'id': 187151497, 'mid': 45443513, 'cid': 10397,
                             'title': 'Green Classic Arrow Spin', 'price': .89,
                             'unit_price': .89, 'discount': 100}]
        self.client.model.update(id=45443513, cid=10397)
        self.assertEqual(self.catalog.catalog('evolutions')[0]['id'], 'evolutions:45443513')
        quote = self.catalog.quote('evolutions:45443513', '187151497')
        self.assertEqual((quote['amount'], quote['price_basis']), ('0.89', 'sale'))

    def test_coins_fixed_tiers_require_real_array_and_bonus(self):
        row = {**SAMPLE, 'id': 163329311, 'mid': 41217957, 'cid': 9623,
               'title': 'coins', 'price': 0, 'unit_price': .0809,
               'discount': 100, 'sku_switch': 1, 'attr_switch': 1, 'unit': 'K',
               'more': {'gold': [100, 500, 1000, 2000, 5000],
                        'price': [8.09, 40.45, 80.9, 161.8, 404.5],
                        'give': [5, 25, 50, 100, 250], 'discount': [100]*5}}
        self.client.rows = [row]
        self.client.model.update(id=41217957, cid=9623)
        self.assertEqual([x['id'] for x in self.catalog.catalog('coins')],
                         ['coins:100', 'coins:500', 'coins:1000', 'coins:2000', 'coins:5000'])
        self.assertEqual(self.catalog.options('coins:100'), [{'id': '21587', 'label': 'PlayStation 5'}])
        quote = self.catalog.quote('coins:100', '21587')
        self.assertEqual((quote['amount'], quote['price_basis']), ('8.09', 'sale'))
        self.assertIn('5K', quote['title'])
        self.assertIn('105K', quote['title'])
        for change in ({'gold': [100, 100, 1000, 2000, 5000]}, {'price': [8.09]},
                       {'give': [-5, 25, 50, 100, 250]}, {'discount': [70, 100, 100, 100, 100]},
                       {'price': [9999, 40.45, 80.9, 161.8, 404.5]}):
            with self.subTest(change=change):
                row['more'] = {**row['more'], **change}
                with self.assertRaises(ValueError):
                    self.catalog.quote('coins:100', '21587')
                row['more'] = {'gold': [100, 500, 1000, 2000, 5000], 'price': [8.09, 40.45, 80.9, 161.8, 404.5],
                               'give': [5, 25, 50, 100, 250], 'discount': [100]*5}
        row['site_id'] = 0
        with self.assertRaises(ValueError):
            self.catalog.quote('coins:100', '21587')
        row['site_id'] = 266
        self.client.model['status'] = 0
        with self.assertRaises(ValueError):
            self.catalog.quote('coins:100', '21587')

    def test_boosting_from_uses_minimum_current_verified_simple_goods(self):
        self.client.rows = [{**SAMPLE, 'id': 166158777, 'mid': 42608119, 'cid': 9711,
                             'title': 'FC 27 Champions Finals 8 Wins', 'price': 45.99,
                             'unit_price': 45.99, 'discount': 100},
                            {**SAMPLE, 'id': 166158778, 'mid': 42608123, 'cid': 9711,
                             'title': 'FC 27 Champions Finals 9 Wins', 'price': 55,
                             'unit_price': 55, 'discount': 100}]
        self.client.model.update(id=42608119, cid=9711)
        self.client.models[42608123] = {'id': 42608123, 'gid': 1327, 'cid': 9711, 'status': 1}
        self.assertEqual(self.catalog.catalog('boosting'), [
            {'id': 'boosting:9711', 'title': 'Champions Finals'},
            {'id': 'boosting:9963', 'title': 'Unlock Champions Finals'},
            {'id': 'boosting:10445', 'title': 'Season 2'},
            {'id': 'boosting:10265', 'title': 'Ultimate Gauntlet'},
            {'id': 'boosting:9999', 'title': 'Unlock Transfer Market'},
        ])
        self.assertEqual(self.catalog.options('boosting:9711'), [{'id': '21587', 'label': 'PlayStation 5'}])
        quote = self.catalog.quote('boosting:9711', '21587')
        self.assertEqual((quote['amount'], quote['price_basis']), ('45.99', 'from'))
        self.assertEqual(quote['url'], 'https://www.mmoexp.com/Fc-27/Boosting/Champions-finals.html')
        self.client.rows[0]['sku_switch'] = 1
        with self.assertRaises(ValueError):
            self.catalog.quote('boosting:9711', '21587')
        self.client.rows[0].update(sku_switch=0, price=40, unit_price=50, discount=80)
        with self.assertRaises(ValueError):
            self.catalog.quote('boosting:9711', '21587')
        self.client.rows[0].update(price=9999, unit_price=9999, discount=100)
        self.assertEqual(self.catalog.quote('boosting:9711', '21587')['amount'], '55.00')
        self.client.models[42608123]['status'] = 0
        with self.assertRaises(ValueError):
            self.catalog.quote('boosting:9711', '21587')

    def test_other_boosting_groups_use_their_own_category_and_url(self):
        cases = [(9963, 43481217, 177645545, '27.90', 'Unlock Champions Finals',
                  'Unlock-champions-finals.html'),
                 (10445, 45498159, 187292793, '19.49', 'Season 2', None),
                 (10265, 45493717, 187285245, '23.39', 'Ultimate Gauntlet', None),
                 (9999, 43183857, 170055297, '53.99', 'Unlock Transfer Market', None)]
        for cid, mid, gid, amount, title, path in cases:
            with self.subTest(cid=cid):
                self.client.rows = [{**SAMPLE, 'id': gid, 'mid': mid, 'cid': cid,
                                     'title': title, 'price': amount, 'unit_price': amount,
                                     'discount': 100}]
                self.client.model.update(id=mid, cid=cid)
                quote = self.catalog.quote('boosting:' + str(cid), '21587')
                self.assertEqual((quote['title'], quote['amount'], quote['price_basis']),
                                 (title, amount, 'from'))
                expected = ('https://www.mmoexp.com/Fc-27/Boosting/' + path if path
                            else 'https://www.mmoexp.com/Fc-27/Boosting.html')
                self.assertEqual(quote['url'], expected)


if __name__ == '__main__':
    unittest.main()


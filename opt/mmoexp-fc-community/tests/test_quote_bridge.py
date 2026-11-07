import unittest
from quote_bridge import dispatch


class Provider:
    def catalog(self, kind):
        return [{'id': '12', 'title': kind}]

    def quote(self, product, option):
        return {'title': product, 'option_label': option}


class BridgeTests(unittest.TestCase):
    def test_only_fixed_read_operations(self):
        p = Provider()
        self.assertEqual(dispatch(p, {'action': 'catalog', 'args': ['packs']})[0]['id'], '12')
        for request in [ {'action': 'edit_goods_price', 'args': []},
                         {'action': 'catalog', 'args': ['customers']},
                         {'action': 'quote', 'args': ['../admin', '2']},
                         {'action': 'quote', 'args': ['1', '2'], 'path': '/admin/users'},
                         {'action': 'quote', 'args': ['1']} ]:
            with self.assertRaises(ValueError):
                dispatch(p, request)

    def test_identifier_pair_preserved(self):
        self.assertEqual(dispatch(Provider(), {'action': 'quote', 'args': ['packs:12', '34']}),
                         {'title': 'packs:12', 'option_label': '34'})

    def test_new_category_identifiers_are_allowed_but_arbitrary_paths_remain_blocked(self):
        p = Provider()
        for product in ('evolutions:42', 'boosting:9711', 'coins:100'):
            with self.subTest(product=product):
                self.assertEqual(dispatch(p, {'action': 'quote', 'args': [product, '21589']})['title'], product)
        for product in ('coins:0', 'coins:100:extra', 'coins:../../etc', 'players:123'):
            with self.assertRaises(ValueError):
                dispatch(p, {'action': 'quote', 'args': [product, '21589']})

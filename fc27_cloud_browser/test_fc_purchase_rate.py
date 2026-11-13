import copy
import unittest
from decimal import Decimal
import json
from unittest.mock import Mock
from fc_purchase_rate import purchase_rate, read_purchase_rates, PRODUCTS


class PurchaseRateTests(unittest.TestCase):
    def row(self):
        return dict(id=163329311, mid=41217957, gid=1327, cid=9623,
                    site_id=266, aid=21587, unit='K', status=1,
                    unit_price='0.07', more=dict(gold=[100, 1000, 2000],
                    price=['8.62', '88.70', '177.40'], give=[0, 30, 60]))

    def test_actual_100k_not_scalar_large_band_or_bonus(self):
        row = self.row(); before = copy.deepcopy(row)
        self.assertEqual(purchase_rate(row, 'PS'), Decimal('0.0862'))
        self.assertEqual(row, before)
        row['more']['give'][0] = 5
        self.assertEqual(purchase_rate(row, 'PS'), Decimal('0.0862'))

    def test_identity_missing_duplicate_and_invalid_price_rejected(self):
        for changes in ({'site_id': 0}, {'gid': 922}, {'aid': 21589}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                purchase_rate(dict(self.row(), **changes), 'PS')
        for gold, prices in (([1000], ['88.70']), ([100, 100], ['8', '9']),
                             ([100], ['NaN']), ([100], [0]), ([100], [])):
            row=self.row(); row['more'].update(gold=gold, price=prices)
            with self.subTest(gold=gold, prices=prices), self.assertRaises(ValueError):
                purchase_rate(row, 'PS')

    def test_authenticated_get_only_platform_failure_isolated(self):
        manager = Mock(); manager.ensure.return_value = True
        responses=[]
        for platform, (product, area) in PRODUCTS.items():
            row=dict(self.row(), id=product, aid=area)
            responses.append((200, json.dumps({'code': 0} if platform == 'PC' else
                {'code': 1, 'data': {'row': row}})))
        manager.request.side_effect=responses
        rates, errors=read_purchase_rates(manager)
        self.assertEqual(rates, {'PS': '0.0862', 'XBOX': '0.0862'})
        self.assertEqual(errors, {'PC': 'ValueError'})
        self.assertEqual(manager.request.call_count, 3)
        for call in manager.request.call_args_list:
            self.assertEqual(call.kwargs, {})
            self.assertTrue(call.args[0].startswith('/admin/goods.Goods/edit?id='))

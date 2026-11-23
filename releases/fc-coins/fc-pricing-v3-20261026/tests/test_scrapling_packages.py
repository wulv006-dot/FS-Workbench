"""Ordinary FC27 price evidence through the public package reader."""
from importlib.util import find_spec
import unittest
from datetime import datetime, timezone

from fc_collection.package_reader import parse_packages


@unittest.skipUnless(find_spec('scrapling'), 'run in the separate market-package worker environment')
class Packages(unittest.TestCase):
    def test_lootbar_platform_sku_excludes_new_user_coupon_and_special_sale(self):
        from fc_collection.package_reader import lootbar_rows, lootbar_url
        stamp = datetime.now(timezone.utc).isoformat()
        item = dict(id=2322450, info={'asset_name':'1M Safe Coins'}, tradable=True, gift={'gift_num':'50K'},
                    sell_order={'display_price':{'currency':'USD','price':'72.50','real_price':'63.80','save_price':'8.70'}},
                    discount_info={'coupon':{'name':'New User 12% OFF Coupon'}})
        data = dict(msg='OK', data=dict(page_num=1,total_page=1,total_count=2,
                    items=[item, dict(item, info={'asset_name':'1M Safe Coins Special Sale'})]))
        rows = lootbar_rows(data, lootbar_url('PC'), {('PS','1000'),('PC','1000')}, stamp)
        self.assertEqual([(r['platform'], r['regular_price'], r['bonus_k']) for r in rows],
                         [('PC','72.50','50')])
        self.assertEqual(lootbar_rows(data, lootbar_url('PS'), {('PS','1000')}, stamp), [])
        item['discount_info'] = {}
        self.assertEqual(lootbar_rows(data, lootbar_url('PC'), {('PC','1000')}, stamp), [])

    def test_iggm_uses_only_active_tier_and_visible_price_of_the_same_regular_card(self):
        from scrapling import Selector
        card = """<html><body><li class="item shippingCoins"><p class="item-title">FC 27 Coins PS Comfort Trade</p>
        <div class="item-price"><span class="price" lkr="70"><strong>$</strong><i>70.00</i></span></div>
        <span data-num="100">100 K</span><span class="active" data-num="1000">1M +50 K</span>
        </li></body></html>"""
        rows = parse_packages('IGGM', Selector(card), 'https://www.iggm.com/ea-sports-fc/fc-27-coins',
                              [('PS', '100'), ('PS', '1000')], datetime.now(timezone.utc).isoformat())
        self.assertEqual([(row['purchase_k'], row['regular_price'], row['bonus_k']) for row in rows],
                         [('1000', '70.00', '50')])

        restricted = card.replace('<div class="item-price">', '<b>Flash Sale</b><div class="item-price">')
        self.assertFalse(parse_packages('IGGM', Selector(restricted), 'https://www.iggm.com/ea-sports-fc/fc-27-coins',
                                        [('PS', '1000')], datetime.now(timezone.utc).isoformat()))

    def test_u4gm_applies_native_volume_discount_to_selected_platform_only(self):
        from scrapling import Selector
        body = """<html><h1>FC 27 Coins PS 4/5 Comfort Trade</h1><span>USD</span>
        <input data-unit-price="0.07"><div class="js-product-level">
        {"100":{"type":"bonus","feature":"fixed","value":5},
         "1000":{"type":"discount","feature":"percent","value":10}}
        </div></html>"""
        rows = parse_packages('U4GM', Selector(body), 'https://www.u4gm.com/fc-27/coins',
                              [['PS', '100'], ['PS', '1000'], ['PC', '100']], datetime.now(timezone.utc).isoformat())
        self.assertEqual([(row['platform'], row['regular_price'], row['bonus_k']) for row in rows],
                         [('PS', '7.00', '5'), ('PS', '63.00', '0')])

        from unittest.mock import Mock
        from fc_collection.adapters import SourceUnavailable
        from fc_collection.public_sources import package_adapter
        transport = Mock()
        transport.get.side_effect = [body.encode(), SourceUnavailable('http_429', 90)]
        transport.clock.return_value = datetime.now(timezone.utc)
        result = package_adapter(dict(source_id='U4GM', requested_platforms=['PS','PC'],
            quantity_scope={'slots': [('PS','100'),('PC','100')]}), transport)
        self.assertEqual((result['status'], result['reason_code'], result['retry_after_seconds']),
                         ('partial','http_429',90))
        self.assertEqual([(o['platform'],o['amount']) for o in result['offers']], [('PS','7.00')])

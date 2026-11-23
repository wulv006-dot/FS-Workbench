"""Ordinary FC27 price evidence through the public package reader."""
from importlib.util import find_spec
import unittest
from datetime import datetime, timezone

from fc_collection.package_reader import parse_packages


@unittest.skipUnless(find_spec('scrapling'), 'run in the separate market-package worker environment')
class Packages(unittest.TestCase):
    def test_iggm_uses_only_active_tier_and_visible_price_of_the_same_regular_card(self):
        from scrapling import Selector
        card = """<html><body><li class="item shippingCoins"><p class="item-title">FC 27 Coins PS Comfort Trade</p>
        <div class="item-price"><span class="price" lkr="70"><strong>$</strong><i>70.00</i></span></div>
        <span data-num="100">100 K</span><span class="active" data-num="1000">1000 K +50 K</span>
        </li></body></html>"""
        rows = parse_packages('IGGM', Selector(card), 'https://www.iggm.com/ea-sports-fc/fc-27-coins',
                              [('PS', '100'), ('PS', '1000')], datetime.now(timezone.utc).isoformat())
        self.assertEqual([(row['purchase_k'], row['regular_price'], row['bonus_k']) for row in rows],
                         [('1000', '70.00', '50')])

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

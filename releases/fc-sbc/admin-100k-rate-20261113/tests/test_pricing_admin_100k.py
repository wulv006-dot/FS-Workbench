import sys,types,unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source'),str(ROOT/'fc27_cloud_browser')]
sys.modules.setdefault('sports_outbound', types.ModuleType('sports_outbound'))
import pricing
from fc_purchase_rate import PRODUCTS

class Admin100KTests(unittest.TestCase):
    def test_legacy_scalar_cache_excluded_new_tier_cache_roundtrips(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'coin.json'
            path.write_text(json.dumps({'fetched_at':1,'prices':{'21587':{'per_coin':'.00007'}}}))
            self.assertEqual(pricing.load_cached_prices(path), {})
            value=pricing.parse_price({'goods':{'index':{'list':[self.row()]}}},21587)
            pricing.save_cached_prices(path,{21587:value})
            self.assertEqual(pricing.load_cached_prices(path)[21587],value)

    def row(self, platform='PS'):
        product,aid=PRODUCTS[platform]
        return dict(id=product,aid=aid,gid=1327,cid=9623,site_id=266,mid=41217957,
            unit='K',status=1,unit_price='.07',more=dict(gold=[100,1000],price=['8.62','88.70'],give=[0,30]))

    def test_admin_actual_tier_with_same_authenticated_client(self):
        client=Mock(); client._json.return_value={'code':1,'data':{'row':self.row()}}
        client.list_goods.return_value=types.SimpleNamespace(rows=[self.row()])
        values=pricing.fetch_from_admin(client,aids=[21587],log=lambda *_:None)
        self.assertEqual(values[21587].price_per_100k,Decimal('8.62'))
        self.assertEqual(values[21587].per_coin,Decimal('.0000862'))
        client._json.assert_called_once_with('GET','/admin/goods.Goods/edit',params={'id':163329311})

    def test_public_actual_tier_not_scalar(self):
        value=pricing.parse_price({'goods':{'index':{'list':[self.row()]}}},21587)
        self.assertEqual(value.price_per_100k,Decimal('8.62'))

    def test_admin_identity_and_missing_tier_rejected(self):
        for row in (dict(self.row(),site_id=0),dict(self.row(),more={})):
            client=Mock();client._json.return_value={'code':1,'data':{'row':row}}
            with self.assertRaises(pricing.PricingError):
                pricing.fetch_from_admin(client,aids=[21587],log=lambda *_:None)

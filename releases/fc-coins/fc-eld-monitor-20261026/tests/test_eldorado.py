from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import eldorado as e

def row(minimum='100',stock='20,000',price='.0543',seller='Goodsellerfc'):
 return dict(seller=seller,seller_url='/users/'+seller+'/shop/Currency',text=seller+'\n99.2%\n56,198 reviews\nIn stock\n'+stock+' K\nMin. qty.\n'+minimum+' K\nDelivery time\n4 min - 5 h\n$'+price+' / K')
class ELD(unittest.TestCase):
 def data(self,*rows):return dict(usd=True,devices=['PlayStation'],rows=list(rows))
 def parse(self,data):return e.parse(data,'PS','PlayStation','2026-10-26T04:00:00+00:00')
 def test_300k_minimum_is_not_a_100k_quote(self):
  v=self.parse(self.data(row('300')));r=v['offers'][0]
  self.assertFalse(r['quantity_eligible_100k']);self.assertIsNone(r['quoted_100k_usd']);self.assertIsNone(v['lowest_observed_100k_usd']);self.assertEqual(r['minimum_purchase_usd'],'16.2900')
 def test_observed_eligible_minimum_is_not_site_minimum(self):
  v=self.parse(self.data(row('100',price='.055'),row('100',price='.0543',seller='Other')))
  self.assertEqual(v['lowest_observed_100k_usd'],'5.4300');self.assertEqual(v['coverage'],'partial_first_page');self.assertFalse(v['executable_quote'])
 def test_vendor_quality_delivery_and_fees_retained(self):
  r=self.parse(self.data(row()))['offers'][0]
  self.assertEqual(r['reviews'],56198);self.assertEqual(r['rating_pct'],'99.2');self.assertEqual(r['delivery_time'],'4 min - 5 h')
  self.assertEqual(r['delivery_method'],'not_verified_per_seller');self.assertEqual(r['checkout_fees'],'not_verified');self.assertFalse(r['comparable']);self.assertEqual(r['direct_pricing_weight'],'0')
 def test_wrong_platform_or_currency_rejected(self):
  for values in (dict(usd=False),dict(devices=['PC']),dict(devices=[])):
   v=self.data(row());v.update(values)
   with self.assertRaises(ValueError):self.parse(v)
 def test_insufficient_inventory_not_an_eligible_quote(self):
  for stock in ('0','99'):
   v=self.parse(self.data(row(stock=stock)));self.assertFalse(v['offers'][0]['quantity_eligible_100k'])
 def test_unknown_missing_rows_not_zero(self):
  for rows in ([],[dict(seller='x',seller_url='https://other.invalid',text='incomplete')]):
   with self.assertRaises(ValueError):self.parse(self.data(*rows))
 def test_invalid_price_fails_closed(self):
  with self.assertRaises(ValueError):self.parse(self.data(row(price='0')))
 def test_number_bounds_and_nonfinite(self):
  for value in ('NaN','Infinity','-1','0','1e13'):
   with self.assertRaises(ValueError):e.amount(value)
 def test_collector_has_no_cdp_or_backend_identity(self):
  source=(Path(e.__file__)).read_text(encoding='utf-8')
  self.assertNotIn('connect_over_cdp',source);self.assertNotIn('p2pah',source);self.assertNotIn('storage_state',source)

if __name__=='__main__':unittest.main()

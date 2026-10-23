import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('itemd2r',Path(__file__).resolve().parents[1]/'source/itemd2r.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def valid():
    return dict(device='2',quantity='100000',tier='100000',tier_label='100 K',delivered='100',
                method='ai-automatic',method_selected=True,usd=True,busy=False,fee='0',
                price='9.85',total='9.85',unit='0.00009852633')

class OfferTest(unittest.TestCase):
    def test_real_displayed_sale_price_and_zero_coin_bonus(self):
        row=m.offer(valid(),'PS','2')
        self.assertEqual((row['gross_usd'],row['bonus_k'],row['effective_usd_per_k']),('9.85','0','0.0985'))
        self.assertEqual(row['source'],'ItemD2R')
        self.assertTrue(row['coupon_excluded'])
    def test_wrong_platform_rejected(self):
        with self.assertRaises(ValueError):m.offer(valid(),'XBOX','4')
    def test_wrong_quantity_or_bonus_label_rejected(self):
        for key,value in [('quantity','10000'),('tier','10000'),('tier_label','100K + 5K'),('delivered','105')]:
            with self.subTest(key=key),self.assertRaises(ValueError):m.offer(dict(valid(),**{key:value}),'PS','2')
    def test_non_usd_or_unsettled_page_rejected(self):
        for key,value in [('usd',False),('busy',True),('method_selected',False)]:
            with self.subTest(key=key),self.assertRaises(ValueError):m.offer(dict(valid(),**{key:value}),'PS','2')
    def test_other_delivery_fee_rejected(self):
        for change in [dict(method='ai-express'),dict(fee='1')]:
            with self.subTest(change=change),self.assertRaises(ValueError):m.offer(dict(valid(),**change),'PS','2')
    def test_crossed_out_or_mismatched_price_rejected(self):
        for change in [dict(price='14.07'),dict(total='14.07'),dict(unit='0.0002'),dict(price='9.850')]:
            with self.subTest(change=change),self.assertRaises(ValueError):m.offer(dict(valid(),**change),'PS','2')
    def test_nonfinite_zero_or_negative_price_rejected(self):
        for value in ['NaN','Infinity','0','-1','broken']:
            with self.subTest(value=value),self.assertRaises(ValueError):m.offer(dict(valid(),price=value),'PS','2')
    def test_three_platform_contract(self):
        for platform,device,_ in m.DEVICES:
            self.assertEqual(m.offer(dict(valid(),device=device),platform,device)['platform'],platform)

if __name__=='__main__':unittest.main()

import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import rs_shipping as s
import profit_daily as p

class Shipping(unittest.TestCase):
    def setUp(self):
        self.q=dict(rs_site='rsorders',rs_server='all',rs_category='all',period=dict(start='2026-10-23 00:00',end='2026-10-24 00:00'))
        self.raw=dict(filters=s.filters(self.q),headers=['游戏','￥销售总额','￥采购总额','利润率','订单总数','交易总数'],rows=[['506 | RS','24,700.02','18,961.09','23.23%','61','70']])
        self.expected={'RS':dict(sites='www.rsorders.com',gid='506',tid='-1',status='-1',aid='0',delivery=True)}
    def test_native_values(self):
        v=s.project(self.raw,self.q);self.assertEqual(v['metrics']['profitCny']['value'],5738.93);self.assertEqual(v['metrics']['profitMarginPct']['value'],23.23);self.assertEqual(v['currency'],'CNY');self.assertNotIn('revenueUsd',v['metrics'])
    def test_filters(self):
        q=dict(self.q,rs_site='all',rs_category='items',rs_server='rs3');f=s.filters(q);self.assertEqual((f['source[]'],f['cid'],f['aid']),('','2','12370'))
    def test_mismatch(self):
        for key in ('source[]','start','cid','aid'):
            raw=copy.deepcopy(self.raw);raw['filters'][key]='wrong'
            with self.assertRaises(ValueError):s.project(raw,self.q)
    def test_currency_headers(self):
        self.raw['headers'][1]='$销售总额'
        with self.assertRaises(ValueError):s.project(self.raw,self.q)
    def test_margin_and_game(self):
        for index,value in ((0,'1322 | FC27'),(3,'30%'),(1,'NaN')):
            raw=copy.deepcopy(self.raw);raw['rows'][0][index]=value
            with self.assertRaises(ValueError):s.project(raw,self.q)
    def test_zero_and_loss(self):
        self.raw['rows']=[];v=s.project(self.raw,self.q);self.assertEqual(v['metrics']['profitCny']['value'],0);self.assertIsNone(v['metrics']['profitMarginPct']['value'])
        self.raw['rows']=[['506 | RS','100','120','-20%','1','2']];self.assertEqual(s.project(self.raw,self.q)['metrics']['profitCny']['value'],-20)
    def day(self):
        v=s.project(self.raw,self.q);v.update(profileKey='RS',date='2026-10-23',capturedAt='2026-10-24T07:00:00+00:00');return p.normalise(v,self.expected)
    def test_daily_same_source(self):
        row=self.day();p.validate_row(row,self.expected);self.assertEqual(row['profitCny'],5738.93);self.assertIsNone(row['revenueUsd']);self.assertEqual(row['scope']['sites'],'www.rsorders.com')
        row['salesCny']=1
        with self.assertRaises(ValueError):p.validate_row(row,self.expected)
    def test_cache_rejects_old_source(self):
        row=self.day();row['sourceContract']='order-native-daily-margin-v2'
        with self.assertRaises(ValueError):p.validate_row(row,self.expected)
    def test_other_site_rejected(self):
        row=self.day();row['scope']['sites']='www.rsfast.com'
        with self.assertRaises(ValueError):p.validate_row(row,self.expected)
if __name__=='__main__':unittest.main()

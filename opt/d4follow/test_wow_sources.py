import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import core_wow_sources as S
import core_wow_gold as W

P={'毛利率下限':.15,'毛利率上限':.30,'IGGM锚定倍数':1.03,'常规利润率':.30,
   '低价最小库存金':20,'成本采样金':21,'报价最长时效秒':1200,'变动闸百分比':.5,'写入口径':'cost'}
def page(price=10,stock=50,minimum=1,**kw):
    return dict({'items':[{'unit_rmb':price,'stock':stock,'min_qty':minimum}],
                 'captured_at':time.time(),'href':'/test','label':'test'},**kw)
def row():
    return {'id':'1','name':'美服-PVP - Alliance','region':'美服','type':'PVP','faction':'A',
            'cost':8,'margin':.2,'b2c':2}
def cfg():
    return {'参数':dict(P),'区服':[{'区':'美服','类型':'PVP','阵营':'A','后台行ID':'1','启用':True,'key':'x'}]}
def listing(**kw):
    r={'attrNameIndexes':'PVP - Alliance(联盟)','gameName':'魔兽世界：无限(美服)',
       'unit':'G','price':10,'effectiveQuantity':50,'warnQuantity':1,'id':'a',
       'merchant':{'online':True,'userId':'seller'}}
    r.update(kw);return r

class StockAndPrice(unittest.TestCase):
    def test_exact_twenty_rejected(self):
        self.assertIsNone(S.source_cost(page(stock=20),'x',P))
    def test_over_twenty_accepted(self):
        self.assertGreater(S.source_cost(page(stock=20.01),'x',P)['gold_used'],20)
    def test_thin_low_source_cannot_win(self):
        r=S.price_pair(page(1,20),page(20,50),P,6.65,10)
        self.assertEqual(r['selected_source'],'比价器');self.assertAlmostEqual(r['avg_rmb'],20)
    def test_cheaper_dd_wins(self):
        self.assertEqual(S.price_pair(page(10),page(20),P,6.65,2)['selected_source'],'DD373')
    def test_cheaper_bjq_wins(self):
        self.assertEqual(S.price_pair(page(20),page(10),P,6.65,2)['selected_source'],'比价器')
    def test_single_source_is_enough(self):
        self.assertEqual(S.price_pair(None,page(10),P,6.65,2)['selected_source'],'比价器')
    def test_no_supply_freezes_even_with_iggm(self):
        self.assertIsNone(S.price_pair(page(stock=20),None,P,6.65,100)['b2c'])
    def test_error_is_not_cost(self):
        self.assertEqual(S.price_pair(page(1,error='failed'),page(20),P,6.65,10)['avg_rmb'],20)
    def test_stale_rejected(self):
        self.assertIsNone(S.source_cost(page(captured_at=time.time()-1201),'x',P))
    def test_future_rejected(self):
        self.assertIsNone(S.source_cost(page(captured_at=time.time()+50),'x',P))
    def test_minimum_purchase_honored(self):
        self.assertEqual(S.source_cost(page(minimum=30),'x',P)['gold_used'],30)
    def test_pack_step_honored(self):
        q=page(minimum=5);q['items'][0]['step_qty']=5
        self.assertEqual(S.source_cost(q,'x',P)['gold_used'],25)
    def test_impossible_minimum_rejected(self):
        self.assertIsNone(S.source_cost(page(stock=25,minimum=30),'x',P))
    def test_nan_cost_rejected(self):
        self.assertIsNone(S.source_cost(page(price=float('nan')),'x',P))
    def test_iggm_target_is_three_percent(self):
        r=S.price_pair(page(10),None,P,6.65,2)
        self.assertAlmostEqual(r['b2c'],2.06)
    def test_fifteen_percent_floor(self):
        r=S.price_pair(page(10),None,P,6.65,.01)
        self.assertGreaterEqual(r['margin'],.15);self.assertLess(r['margin'],.15001)
    def test_thirty_percent_ceiling(self):
        r=S.price_pair(page(10),None,P,6.65,100)
        self.assertLessEqual(r['margin'],.30);self.assertGreater(r['margin'],.29999)
    def test_no_iggm_still_capped(self):
        r=S.price_pair(page(10),None,P,6.65)
        self.assertLessEqual(r['margin'],.30);self.assertGreaterEqual(r['margin'],.15)
    def test_invalid_fx_rejected(self):
        with self.assertRaises(ValueError):S.price_pair(page(),None,P,0,2)
    def test_invalid_margin_rejected(self):
        with self.assertRaises(ValueError):S.price_pair(page(),None,dict(P,毛利率下限=.4),6.65,2)
    def test_floor_rounding_many_costs(self):
        for c in [.0001,.01,.17,1,3.33,17.513135,25,49.99999,1000]:
            for ig in [.0001,.3,1,10,1000,None]:
                m=S.price_pair(page(c),None,P,6.65,ig)['margin']
                self.assertGreaterEqual(m,.15-1e-12);self.assertLessEqual(m,.30+1e-12)

class PublicSellContract(unittest.TestCase):
    def parse(self,rows):return S.parse_offers(rows,10109,'美服',('美服','PVP','A'))
    def test_online_only(self):
        self.assertFalse(self.parse([listing(merchant={'online':False,'userId':'s'})]))
    def test_string_false_not_online(self):
        self.assertFalse(self.parse([listing(merchant={'online':'false','userId':'s'})]))
    def test_wrong_unit_rejected(self):
        with self.assertRaises(ValueError):self.parse([listing(unit='K')])
    def test_wrong_region_rejected(self):
        with self.assertRaises(ValueError):self.parse([listing(gameName='魔兽世界：无限(欧服)')])
    def test_wrong_faction_rejected(self):
        with self.assertRaises(ValueError):self.parse([listing(attrNameIndexes='PVP-Horde(部落)')])
    def test_duplicate_merchant_not_added(self):
        self.assertEqual(len(self.parse([listing(),listing(id='b',price=11)])),1)
    def test_korean_spelling(self):
        self.assertEqual(S.server_key('韩服','PVP-AIliance(联盟)'),('韩服','PVP','A'))

class BackendIntegration(unittest.TestCase):
    def plan(self,r=None,c=None,pages=None,bjq=None):
        return W.build_plan([r or row()],pages or {('美服','PVP','A'):page(10)},c or cfg(),6.65,
                 iggm={'US|PVP-Alliance':2},bjq_pages=bjq or {})[0]
    def test_backend_row_margin_used(self):
        r=row();r['margin']=.33;x=self.plan(r)
        self.assertAlmostEqual(x['建议采购成本'],x['目标b2c']*6.65*.67,places=6)
    def test_margin_violation_overrides_half_percent_hold(self):
        r=row();r['b2c']=(10/6.65/.85)*.999
        x=self.plan(r,c={**cfg(),'参数':dict(P,IGGM锚定倍数=.01)})
        self.assertNotEqual(x['动作'],'hold')
    def test_disabled_row_never_written(self):
        c=cfg();c['区服'][0]['启用']=False;self.assertIsNone(self.plan(c=c)['建议采购成本'])
    def test_unknown_row_id_never_written(self):
        r=row();r['id']='2';self.assertIsNone(self.plan(r)['建议采购成本'])
    def test_hardcore_untouched(self):
        r=row();r['type']='HC';self.assertIsNone(self.plan(r)['建议采购成本'])
    def test_no_supply_never_writes_fallback(self):
        x=self.plan(pages={('美服','PVP','A'):page(stock=0)})
        self.assertEqual(x['动作'],'hold');self.assertIsNone(x['目标b2c'])
    def test_empty_existing_price_can_be_initialized(self):
        r=row();r['b2c']=None;self.assertEqual(self.plan(r)['动作'],'follow_up')
    def test_two_sources_started_together(self):
        seen=[]
        def dd(log):seen.append('dd');time.sleep(.03);return {'dd':1}
        def bjq(log):seen.append('bjq');time.sleep(.03);return {'bjq':1}
        with patch.object(S,'bjq_crawl',bjq):
            a,b,_=S.collect_pair(dd,log=lambda *a:None)
        self.assertEqual(set(seen),{'dd','bjq'});self.assertEqual(a,{'dd':1});self.assertEqual(b,{'bjq':1})

if __name__=='__main__':unittest.main(verbosity=2)

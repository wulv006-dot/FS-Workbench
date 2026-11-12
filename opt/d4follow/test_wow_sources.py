"""Synthetic v5.4 regression: inventory bands, all SELL offers, 1.60 cap/2.99 exception."""
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import core_wow_sources as S
import core_wow_gold as W

P={'常规利润率':.25,'薄区利润率':.30,'稀缺利润率':.35,'薄区阈值金':50,
   '成本采样金':150,'最高售价USD每G':1.6,'报价最长时效秒':1200,'变动闸百分比':.5,'写入口径':'cost'}

def page(price=10,stock=50,minimum=1,**kw):
    return dict({'items':[{'unit_rmb':price,'stock':stock,'min_qty':minimum}],
                 'captured_at':time.time(),'href':'/test','label':'test'},**kw)
def row():
    return {'id':'1','name':'美服-PVP - Alliance','region':'美服','type':'PVP','faction':'A',
            'cost':8,'margin':.2,'b2c':1.5}
def cfg():
    return {'参数':dict(P),'区服':[{'区':'美服','类型':'PVP','阵营':'A','后台行ID':'1','启用':True,'key':'x'}]}
def listing(**kw):
    r={'attrNameIndexes':'PVP - Alliance(联盟)','gameName':'魔兽世界：无限(美服)',
       'unit':'G','price':10,'effectiveQuantity':50,'warnQuantity':1,'id':'a',
       'merchant':{'online':True,'userId':'seller'}}
    r.update(kw);return r

class StockAndPrice(unittest.TestCase):
    def test_twenty_is_valid_scarce_inventory(self):
        r=S.price_pair(page(stock=20),None,P,6.65)
        self.assertEqual(r['gold_used'],20);self.assertEqual(r['margin'],.35)
    def test_mixed_inventory_is_weighted_in_price_order(self):
        q=page(2.7,20,20)
        q['items'] += [{'unit_rmb':7.9364,'stock':9,'min_qty':9},
                       {'unit_rmb':8,'stock':40,'min_qty':10,'step_qty':10}]
        r=S.source_cost(q,'x',P)
        self.assertEqual(r['avail_gold'],69);self.assertEqual(r['gold_used'],69)
        self.assertAlmostEqual(r['avg_rmb'],(2.7*20+7.9364*9+8*40)/69)
        self.assertEqual(len(r['legs']),3)
    def test_equal_price_inventory_combines(self):
        q=page(10,11)
        q['items'] += [{'unit_rmb':10,'stock':10,'min_qty':1}]
        self.assertEqual(S.source_cost(q,'x',P)['avail_gold'],21)
    def test_mixed_thin_prices_use_weighted_average(self):
        q=page(10,11)
        q['items'] += [{'unit_rmb':11,'stock':10,'min_qty':1}]
        self.assertAlmostEqual(S.source_cost(q,'x',P)['avg_rmb'],220/21)
    def test_over_twenty_accepted(self):
        self.assertGreater(S.source_cost(page(stock=20.01),'x',P)['gold_used'],20)
    def test_scarce_low_source_can_win(self):
        r=S.price_pair(page(1,20),page(20,50),P,6.65)
        self.assertEqual(r['selected_source'],'DD373');self.assertAlmostEqual(r['avg_rmb'],1)
        self.assertEqual(r['margin'],.35)
    def test_cheaper_dd_wins(self):
        self.assertEqual(S.price_pair(page(10),page(20),P,6.65)['selected_source'],'DD373')
    def test_cheaper_bjq_wins(self):
        self.assertEqual(S.price_pair(page(20),page(10),P,6.65)['selected_source'],'比价器')
    def test_single_source_is_enough(self):
        self.assertEqual(S.price_pair(None,page(10),P,6.65)['selected_source'],'比价器')
    def test_unknown_supply_freezes(self):
        r=S.price_pair(None,None,P,6.65)
        self.assertIsNone(r['b2c']);self.assertFalse(r['both_empty'])
    def test_error_is_not_cost(self):
        self.assertEqual(S.price_pair(page(1,error='failed'),page(20),P,6.65)['avg_rmb'],20)
    def test_stale_rejected(self):
        self.assertIsNone(S.source_cost(page(captured_at=time.time()-1201),'x',P))
    def test_future_rejected(self):
        self.assertIsNone(S.source_cost(page(captured_at=time.time()+50),'x',P))
    def test_minimum_purchase_honored(self):
        self.assertEqual(S.source_cost(page(stock=200,minimum=160),'x',P)['gold_used'],160)
    def test_pack_step_honored(self):
        q=page(stock=200,minimum=5);q['items'][0]['step_qty']=7
        self.assertEqual(S.source_cost(q,'x',P)['gold_used'],154)
    def test_impossible_minimum_rejected(self):
        self.assertIsNone(S.source_cost(page(stock=25,minimum=30),'x',P))
    def test_nan_cost_rejected(self):
        self.assertIsNone(S.source_cost(page(price=float('nan')),'x',P))
    def test_legacy_iggm_parameters_do_not_affect_price(self):
        r=S.price_pair(page(10),None,P,6.65)
        other=S.price_pair(page(10),None,dict(P,IGGM锚定倍数=999,毛利率下限=.9),6.65)
        self.assertEqual(r['b2c'],other['b2c']);self.assertIsNone(r['iggm'])
    def test_exact_stock_band_boundaries(self):
        for stock,band,margin in [(49,'scarce',.35),(50,'thin',.30),(149,'thin',.30),(150,'full',.25),(151,'full',.25)]:
            r=S.price_pair(page(stock=stock),None,P,6.65)
            self.assertEqual((r['margin_band'],r['margin']),(band,margin))
            self.assertEqual(r['gold_used'],min(stock,150))
    def test_available_price_cap_recalculates_actual_margin(self):
        r=S.cap_price_result(S.price_pair(page(10),None,P,6.65),2)
        self.assertEqual(r['b2c'],1.6);self.assertTrue(r['cap_applied'])
        self.assertAlmostEqual(r['margin'],1-10/6.65/1.6)
        self.assertEqual(r['target_margin'],.30)
    def test_final_price_selects_source_including_margin(self):
        r=S.price_pair(page(4,49),page(4.1,150),P,6.65)
        self.assertEqual(r['selected_source'],'比价器');self.assertEqual(r['margin'],.25)
    def test_full_margin_respects_parameter(self):
        r=S.price_pair(page(stock=200),None,dict(P,常规利润率=.4),6.65)
        self.assertEqual(r['margin'],.4)
    def test_invalid_fx_rejected(self):
        with self.assertRaises(ValueError):S.price_pair(page(),None,P,0)
    def test_invalid_margin_rejected(self):
        with self.assertRaises(ValueError):S.price_pair(page(),None,dict(P,薄区利润率=1),6.65)
    def test_rounding_preserves_selected_margin(self):
        for c in [.0001,.01,.17,1,3.33,17.513135,25,49.99999,1000]:
            for stock,margin in [(25,.35),(50,.30),(150,.25)]:
                r=S.price_pair(page(c,stock),None,P,6.65)
                self.assertEqual(r['margin'],margin)
                self.assertGreaterEqual(1-c/6.65/r['b2c'],margin-1e-12)

    def test_only_two_confirmed_empty_sources_use_299(self):
        empty=page(items=[],raw_count=0)
        for other in (None,page(error='failed'),page(stock=0)):
            self.assertIsNone(S.price_pair(empty,other,P,6.65)['b2c'])
        r=S.price_pair(empty,empty,P,6.65)
        self.assertEqual(r['b2c'],2.99)
        self.assertTrue(S.cap_price_result(r,1.2)['cap_exempt'])
    def test_unknown_current_299_stays_unchanged(self):
        r=S.cap_price_result(S.price_pair(None,None,P,6.65),2.99)
        self.assertIsNone(r['b2c']);self.assertTrue(r['cap_exempt'])
    def test_incomplete_inventory_requires_full_sample(self):
        self.assertIsNone(S.source_cost(page(stock=149,inventory_complete=False),'x',P))
        r=S.source_cost(page(stock=160,inventory_complete=False),'x',P)
        self.assertEqual(r['gold_used'],150);self.assertNotIn('all_stock_avg_rmb',r)

class PublicSellContract(unittest.TestCase):
    def parse(self,rows):return S.parse_offers(rows,10109,'美服',('美服','PVP','A'))
    def test_offline_offer_included(self):
        r=self.parse([listing(merchant={'online':False,'userId':'s'})])
        self.assertEqual(len(r),1);self.assertIs(r[0]['online'],False)
    def test_online_metadata_does_not_filter(self):
        self.assertEqual(len(self.parse([listing(merchant={'online':'false','userId':'s'})])),1)
    def test_wrong_unit_rejected(self):
        with self.assertRaises(ValueError):self.parse([listing(unit='K')])
    def test_wrong_region_rejected(self):
        with self.assertRaises(ValueError):self.parse([listing(gameName='魔兽世界：无限(欧服)')])
    def test_wrong_faction_rejected(self):
        with self.assertRaises(ValueError):self.parse([listing(attrNameIndexes='PVP-Horde(部落)')])
    def test_distinct_offers_same_merchant_both_count(self):
        self.assertEqual(len(self.parse([listing(),listing(id='b',price=11)])),2)
        self.assertEqual(len(self.parse([listing(),listing(price=11)])),1)
    def test_korean_spelling(self):
        self.assertEqual(S.server_key('韩服','PVP-AIliance(联盟)'),('韩服','PVP','A'))

class BackendIntegration(unittest.TestCase):
    def plan(self,r=None,c=None,pages=None,bjq=None):
        return W.build_plan([r or row()],pages or {('美服','PVP','A'):page(10)},c or cfg(),6.65,
                 bjq_pages=bjq or {})[0]
    def test_backend_row_margin_used(self):
        r=row();r['margin']=.33;x=self.plan(r)
        self.assertAlmostEqual(x['建议采购成本'],x['目标b2c']*6.65*.67,places=6)
    def test_price_cap_overrides_half_percent_hold(self):
        r=row();r['b2c']=1.601
        x=self.plan(r)
        self.assertEqual(x['目标b2c'],1.6);self.assertEqual(x['动作'],'follow_down')
    def test_disabled_row_never_written(self):
        c=cfg();c['区服'][0]['启用']=False;self.assertIsNone(self.plan(c=c)['建议采购成本'])
    def test_unknown_row_id_never_written(self):
        r=row();r['id']='2';self.assertIsNone(self.plan(r)['建议采购成本'])
    def test_unopened_hardcore_under_cap_held(self):
        r=row();r['type']='HC'
        x=self.plan(r)
        self.assertEqual(x['动作'],'hold');self.assertIsNone(x['建议采购成本'])
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

    def test_opened_hardcore_with_source_follows(self):
        r=row();r['type']='HC'
        c=cfg();c['区服'][0]['类型']='HC'
        self.assertEqual(self.plan(r,c,{('美服','HC','A'):page(4)})['动作'],'follow_down')
    def test_disabled_above_cap_corrected_only_with_matching_id(self):
        c=cfg();c['区服'][0]['启用']=False
        r=row();r['b2c']=2
        self.assertEqual(self.plan(r,c)['动作'],'follow_down')
        r['id']='2';self.assertIsNone(self.plan(r,c)['建议采购成本'])
    def test_confirmed_empty_sources_write_299_exception(self):
        pages={('美服','PVP','A'):page(items=[],raw_count=0)}
        x=self.plan(pages=pages,bjq=pages)
        self.assertEqual(x['目标b2c'],2.99);self.assertTrue(x['上限例外'])
        self.assertEqual(x['动作'],'follow_up')

if __name__=='__main__':unittest.main(verbosity=2)

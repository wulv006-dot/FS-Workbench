import copy
import importlib.util
import json
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

from support import MAIN as main, SEP as separate, fixture
import game_parameters as gp
import core_wow_sources as ws
import core_wow_gold as wg
import core_dd373_cost as dd
import engine


EXPECTED = fixture('pricing_expectations.json')


def page(stock, price=4, now=None):
    return dict(captured_at=now or time.time(),raw_count=int(stock>0),
                items=([dict(unit_rmb=price,stock=stock,min_qty=1,offer_id='a')] if stock else []))


class SettingsTests(unittest.TestCase):
    def test_existing_all_games_noop(self):
        for game in gp.GAMES:
            doc=main if game['file']=='config.json' else separate[game['file']]
            schema=gp.get_game_schema(game['id'],doc,main)
            new,changes=gp.apply_fields(game['id'],doc,{f['key']:f['value'] for f in schema['fields']},main)
            self.assertEqual(new,doc,game['id'])
            self.assertFalse(changes,game['id'])

    def test_invalid_values_and_unknown_fields(self):
        doc=separate['wow_gold_config.json']
        for v in (float('nan'),float('inf'),True,'0.2',-1,1):
            with self.subTest(value=v),self.assertRaises(ValueError):
                gp.apply_fields('wow',doc,{'margin_full':v},main)
        with self.assertRaises(ValueError): gp.apply_fields('wow',doc,{'password':'x'},main)
        with self.assertRaises(ValueError): gp.apply_fields('aa',separate['aa_gold_config.json'],{'skip_lowest':1.5},main)

    def test_relationships(self):
        with self.assertRaises(ValueError):
            gp.apply_fields('wow',separate['wow_gold_config.json'],{'sample_gold':50},main)
        with self.assertRaises(ValueError): gp.apply_fields('aion2',main,{'target_margin':.2})

    def test_game_scoping_and_missing_override(self):
        new,changes=gp.apply_fields('d4',main,{'item_discount':5})
        self.assertFalse(changes[0]['before_exists'])
        self.assertEqual(engine.strategy_of(new,'暗黑破坏神4')['让价百分比'],5)
        self.assertEqual(engine.strategy_of(new,'流放之路2')['让价百分比'],2)
        self.assertEqual(main['跟价']['跟随策略']['让价百分比'],2)

    def test_policy_override_is_authoritative(self):
        cfg=copy.deepcopy(main)
        cfg['金币']['定价策略']['按游戏']['AION2']=dict(cfg['金币']['定价策略'],利润率=.31)
        schema=gp.get_game_schema('aion2',cfg)
        self.assertEqual(next(f for f in schema['fields'] if f['key']=='target_margin')['value'],.31)
        new,_=gp.apply_fields('aion2',cfg,{'target_margin':.32})
        self.assertEqual(new['金币']['定价策略']['利润率'],.29)
        self.assertEqual(new['金币']['定价策略']['按游戏']['AION2']['利润率'],.32)

    def test_sampling_parameters_scoped(self):
        cfg,_=gp.apply_fields('aion2',main,{'sample_quantity':60000})
        self.assertEqual(gp.cost_parameters(cfg,'AION2')['目标万量'],60000)
        self.assertEqual(gp.cost_parameters(cfg,'MapleStory Classic World'),{'最低条数':10})

    def test_no_empty_price_edit(self):
        self.assertNotIn('empty_price',{f['key'] for f in gp.get_game_schema('wow',separate['wow_gold_config.json'],main)['fields']})

    def test_wow_default_numeric_parity(self):
        params=separate['wow_gold_config.json']['参数']
        for case in EXPECTED['wow']:
            a,b=case['stock']
            new=ws.price_pair(page(a,4),page(b,4.5),params,6.65)
            for key,value in case['price'].items():
                self.assertEqual(value,new.get(key),(a,b,key))
            for cap_case in case['caps']:
                newcap=ws.cap_price_result(new,cap_case['current'])
                for key,value in cap_case['result'].items():
                    self.assertEqual(value,newcap.get(key),(a,b,cap_case['current'],key))

    def test_changed_sample_and_boundary_affect_calculation(self):
        params=dict(separate['wow_gold_config.json']['参数'],成本采样金=100,薄区阈值金=30)
        data=page(120)
        result=ws.price_pair(data,None,params,6.65)
        self.assertEqual(result['gold_used'],100)
        self.assertEqual(result['margin'],.25)
        result=ws.price_pair(page(40),None,params,6.65)
        self.assertEqual(result['margin'],.30)

    def test_capped_api_uses_current_sample(self):
        rows=[dict(amount=4,number=1,singleprice=4,shopno=str(i)) for i in range(30)]
        response=dict(StatusCode=0,StatusData=dict(ResultCode=0,ResultData=rows))
        with patch.object(wg,'_api_get',return_value=response):
            self.assertEqual(len(wg.dd_api_items('a','b',100)),30)
            with self.assertRaises(RuntimeError): wg.dd_api_items('a','b',150)

    def test_unknown_quote_preserves_299(self):
        result=ws.price_pair(None,None,separate['wow_gold_config.json']['参数'],6.65)
        self.assertIsNone(ws.cap_price_result(result,2.99)['b2c'])
        self.assertTrue(ws.cap_price_result(result,2.99)['cap_exempt'])

    def test_dd_dispatch_keeps_game_parameters_isolated(self):
        with patch.object(dd,'_fetch_costs_aion2',return_value={}) as a,patch.object(dd,'_fetch_costs_flat',return_value={}) as m:
            dd.fetch_costs([{'key':'a','游戏':'AION2'}],6.65,parameters={'目标万量':60000})
            dd.fetch_costs([{'key':'m','游戏':'MapleStory Classic World'}],6.65,parameters={'目标万量':300})
            self.assertEqual(a.call_args.kwargs['parameters'],{'目标万量':60000})
            self.assertEqual(m.call_args.kwargs['parameters'],{'目标万量':300})
        self.assertEqual(dd.TARGET_WAN,80000)
        self.assertEqual(dd.FLAT_ZONES['MapleStory Classic World']['target_wan'],500)

    def test_engine_default_parity_and_per_game_targets(self):
        items=[{'key':'x','游戏':'暗黑破坏神4','中文名':'X','跟价':True,'装量':1,'iggm':{'goods_no':'x'}},
               {'key':'y','游戏':'流放之路2','中文名':'Y','跟价':True,'装量':1,'iggm':{'goods_no':'y'}}]
        cfg=copy.deepcopy(main)
        cfg['商品映射']={'对照项':items}
        cfg['同族联动']={'启用':False}
        args=(items,{'x':{'price_usd':10},'y':{'price_usd':10}},
              {'x':{'price_usd':9},'y':{'price_usd':9}},
              {'x':{'price_usd':8,'pack_size':1},'y':{'price_usd':8,'pack_size':1}}, {},'2026-11-12T10:00:00')
        new=engine.evaluate(cfg,*args,log=None,backend_rows={})
        self.assertEqual(EXPECTED['engine'],new)
        updated,_=gp.apply_fields('d4',cfg,{'item_discount':10})
        result=engine.evaluate(updated,*args,log=None,backend_rows={})
        bykey={r['key']:r for r in result}
        self.assertAlmostEqual(bykey['x']['target_front_usd'],9)
        self.assertAlmostEqual(bykey['y']['target_front_usd'],9.8)


if __name__=='__main__': unittest.main(verbosity=2)

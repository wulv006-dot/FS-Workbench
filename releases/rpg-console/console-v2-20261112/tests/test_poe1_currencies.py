import copy
import unittest
from unittest.mock import patch
from support import APP
import core_poe1 as p


def config():
    return {p.SECTION: {'商品': [
        {'id':'d','名称':'Divine Orb','倍数':1},
        {'id':'d20','名称':'Divine Orb(20+1 Free)','倍数':20}],
        '附加币种':[{'key':'chaos','币种名称':'Chaos Orb','最低成本':0.0001,
            '最高成本':10,'DD373':dict(p.DD, GameShopTypeId='chaos'), '商品':[
                {'id':'c','名称':'Chaos Orb','倍数':1},
                {'id':'c1000','名称':'Chaos Orb(1000+100 Free)','倍数':1000}]}]}}


def rows(cost):
    return [{'amount':1000,'price':1000*cost,'singleprice':cost} for _ in range(30)]


class CurrencyTests(unittest.TestCase):
    def setUp(self):
        self.cfg=config()
        self.saved={}
        self.stack=[]
        self.stack.append(patch.object(p,'load_state',side_effect=lambda:copy.deepcopy(self.saved)))
        self.stack.append(patch.object(p,'save_state',side_effect=self.save))
        self.stack.append(patch.object(p,'quotes',side_effect=self.quote))
        for mock in self.stack: mock.start()
        self.addCleanup(lambda:[mock.stop() for mock in reversed(self.stack)])

    def save(self, value): self.saved=copy.deepcopy(value)
    def quote(self,cfg,log=print):
        return rows(.0271168 if p._p(cfg)['DD373']['GameShopTypeId']=='chaos' else 2.617896)
    def plan(self,known=None): return p.build_plan(self.cfg,log=lambda x:None,known=known or {})

    def test_correct_sources_and_paid_quantities(self):
        plan=self.plan()
        self.assertEqual(plan['targets']['d20'],round(20*plan['targets']['d'],5))
        self.assertEqual(plan['targets']['c1000'],round(1000*plan['targets']['c'],5))
        self.assertNotEqual(plan['targets']['c1000'],round(1100*plan['targets']['c'],5))
        self.assertEqual(plan['targets']['c'],.00583)
        self.assertEqual(plan['targets']['c1000'],5.83)

    def test_independent_state_and_noop_next_round(self):
        a=self.plan()
        self.assertAlmostEqual(a['next_state']['cost_rmb'],2.617896)
        self.assertAlmostEqual(a['next_state']['currencies']['chaos']['cost_rmb'],.027117)
        b=self.plan(a['next_state'])
        self.assertTrue(all(x['动作']=='保持' for x in b['items']))

    def test_chaos_failure_preserves_state_and_divine_still_runs(self):
        old=self.plan()['next_state']
        def quote(cfg,log=print):
            if p._p(cfg)['DD373']['GameShopTypeId']=='chaos': raise RuntimeError('source failed')
            return rows(2.6)
        with patch.object(p,'quotes',side_effect=quote): b=self.plan(old)
        self.assertEqual({x['id'] for x in b['items']},{'d','d20'})
        self.assertEqual(b['next_state']['currencies']['chaos'],old['currencies']['chaos'])
        self.assertIn('chaos',b['币种错误'])

    def test_divine_failure_does_not_stop_chaos(self):
        def quote(cfg,log=print):
            if p._p(cfg)['DD373']['GameShopTypeId']!='chaos': raise RuntimeError('source failed')
            return rows(.027)
        with patch.object(p,'quotes',side_effect=quote): b=self.plan()
        self.assertEqual({x['id'] for x in b['items']},{'c','c1000'})

    def test_broken_bundle_ratio_forces_both_rows(self):
        old=self.plan()['next_state']
        old['currencies']['chaos']['targets']['c1000']=.00583
        b=self.plan(old)
        self.assertTrue(all(x['动作']=='改价' for x in b['items'] if x['id'].startswith('c')))

    def test_chaos_guard_never_writes_divine_cost(self):
        old=self.plan()['next_state']
        old['currencies']['chaos']['cost_rmb']=.01
        self.saved=copy.deepcopy(old)
        b=self.plan(old)
        self.assertIn('chaos',b['币种错误'])
        self.assertEqual(b['next_state']['currencies']['chaos']['blocked'],1)
        self.assertEqual(b['next_state']['cost_rmb'],old['cost_rmb'])

    def test_duplicate_product_id_rejected_before_fetch(self):
        self.cfg[p.SECTION]['附加币种'][0]['商品'][0]['id']='d'
        with self.assertRaises(ValueError): self.plan()

    def test_legacy_only_retains_two_product_behavior(self):
        self.cfg[p.SECTION].pop('附加币种')
        b=self.plan()
        self.assertEqual(set(b['targets']),{'d','d20'})
        self.assertNotIn('currencies',b['next_state'])


class QuantitySamplingTests(unittest.TestCase):
    def setUp(self):
        self.cfg={p.SECTION:{'采样目标数量':6000}}

    def quote(self,amount,unit):
        return {'amount':amount,'price':amount*unit,'singleprice':unit}

    def test_stops_after_exact_6000_and_skips_cheapest(self):
        offers=[self.quote(20000,.001),self.quote(1000,.016),
                self.quote(5000,.018),self.quote(1000,.12)]
        got=p.compute_cost(self.cfg,offers)
        self.assertEqual(got['总数量'],6000)
        self.assertAlmostEqual(got['总价'],106)
        self.assertEqual(got['用条数'],2)
        self.assertEqual(got['跳过'],1)

    def test_last_offer_is_whole_and_may_exceed_target(self):
        offers=[self.quote(1000,.01),self.quote(3000,.02),
                self.quote(4000,.03),self.quote(1000,.50)]
        got=p.compute_cost(self.cfg,offers)
        self.assertEqual(got['总数量'],7000)
        self.assertAlmostEqual(got['总价'],180)
        self.assertEqual(got['用条数'],2)

    def test_source_order_is_normalized_for_quantity_mode(self):
        offers=[self.quote(1000,.50),self.quote(5000,.018),
                self.quote(1000,.016),self.quote(1000,.001)]
        self.assertEqual(p.compute_cost(self.cfg,offers)['总数量'],6000)
        self.assertAlmostEqual(p.compute_cost(self.cfg,offers)['总价'],106)

    def test_not_limited_to_first_20_when_accumulating_quantity(self):
        offers=[self.quote(1000,.001)]+[self.quote(250,.01+i*.001) for i in range(25)]
        got=p.compute_cost(self.cfg,offers)
        self.assertEqual(got['总数量'],6000)
        self.assertEqual(got['用条数'],24)

    def test_less_than_6000_fails_instead_of_pricing_partial_stock(self):
        offers=[self.quote(1000,.001),self.quote(5999,.02)]
        with self.assertRaisesRegex(RuntimeError,'6000'):
            p.compute_cost(self.cfg,offers)

    def test_invalid_rows_are_not_counted_as_available_stock(self):
        offers=[self.quote(1000,.001),self.quote(3000,.02),
                self.quote(10000,float('nan')),self.quote(0,.02),self.quote(3000,.03)]
        got=p.compute_cost(self.cfg,offers)
        self.assertEqual(got['总数量'],6000)
        self.assertAlmostEqual(got['总价'],150)

    def test_sampling_policy_change_rebases_only_cost_guard(self):
        cfg=config()
        chaos=cfg[p.SECTION]['附加币种'][0]
        chaos['采样目标数量']=6000
        old={'cost_rmb':2.6,'targets':{'d':.56,'d20':11.2},'currencies':{
            'chaos':{'cost_rmb':.04,'targets':{'c':.0086,'c1000':8.6},'blocked':3}}}
        def quotes(c,log=print):
            return rows(.016 if p._p(c)['DD373']['GameShopTypeId']=='chaos' else 2.6)
        with patch.object(p,'quotes',side_effect=quotes),patch.object(p,'save_state'),patch.object(p,'load_state',return_value=old):
            result=p.build_plan(cfg,known=old,log=lambda _:None)
        self.assertNotIn('chaos',result['币种错误'])
        self.assertEqual(result['next_state']['currencies']['chaos']['采样目标数量'],6000)
        self.assertEqual(result['next_state']['currencies']['chaos']['blocked'],0)
        self.assertEqual(next(i['old'] for i in result['items'] if i['id']=='c'),.0086)

    def test_same_quantity_policy_still_has_market_change_guard(self):
        cfg=config();cfg[p.SECTION]['附加币种'][0]['采样目标数量']=6000
        old={'currencies':{'chaos':{'cost_rmb':.04,'采样目标数量':6000,'blocked':0}}}
        def quotes(c,log=print):return rows(.016 if p._p(c)['DD373']['GameShopTypeId']=='chaos' else 2.6)
        with patch.object(p,'quotes',side_effect=quotes),patch.object(p,'save_state'),patch.object(p,'load_state',return_value=old):
            result=p.build_plan(cfg,known=old,log=lambda _:None)
        self.assertIn('chaos',result['币种错误'])


if __name__=='__main__': unittest.main()

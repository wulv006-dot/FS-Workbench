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


if __name__=='__main__': unittest.main()

"""The real runtime persists and revalidates independent platform assignments."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from test_bidirectional_markets import evidence, POLICY
from test_dual20_sprint import NOW
from test_optional_competitors import missing
from fc_pricing_v3 import engine,runtime,smart
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger


class BidirectionalRuntime(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.db=Ledger(self.root/'control.db');self.data=evidence()
        self.db.activate_generation('g',[])
        with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            base=self.db.create_plan('revenue_sprint',['base:console','base:pc'],engine.current_action(self.data))
            self.db.activate_plan(base['plan_id'],now=NOW)
            plan=self.db.create_plan('smart',['base:console','base:pc'],engine.current_action(self.data),starts_at=(NOW-timedelta(days=2)).isoformat())
            self.db.activate_plan(plan['plan_id'],now=NOW)
            self.plan=self.db.migrate_smart_strategy(plan['plan_id'],1,'wulv')
        for item in (patch.object(runtime,'ledger',return_value=self.db),patch.object(runtime,'ROOT',self.root),patch.object(runtime,'clock',return_value=NOW)):
            item.start();self.addCleanup(item.stop)

    def verify(self,result,execution=False):
        return runtime.verify_quote(dict(evidence=self.data,result=result),dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW,for_execution=execution)

    def recalc_hash(self,result):
        receipt=result['decision_receipt'];receipt['sha256']=fingerprint({k:v for k,v in receipt.items() if k!='sha256'})

    def test_real_runtime_nine_variants_independent_labels_and_probability_product(self):
        result=runtime.calculate(self.data);saved=result['decision_receipt']['smart_assignment']
        self.assertEqual(saved['epoch'],0)
        self.assertEqual(saved['strategy_version'],smart.STRATEGY_VERSION)
        self.assertEqual(saved['revision'],self.plan['revision'])
        self.assertEqual(set(saved['variants']),{a+b for a in 'ABC' for b in 'ABC'})
        expected={}
        for key,row in saved['variants'].items():
            probability=Decimal(saved['group_probabilities']['console'][key[0]])*Decimal(saved['group_probabilities']['pc'][key[1]])
            if not probability:continue
            effective=smart.effective_key(self.data,row['action'])
            expected[effective]=expected.get(effective,Decimal(0))+probability
        self.assertEqual({k:Decimal(str(v)) for k,v in saved['effective_probabilities'].items()},expected)
        self.assertEqual(sum(expected.values()),1)
        selected_key=saved['group_labels']['console']+saved['group_labels']['pc']
        self.assertEqual(saved['effective_action'],saved['variants'][selected_key]['action'])
        self.assertEqual(result['decision_receipt']['strategy_parameters']['competitor_policy'],POLICY)
        self.verify(result)
        (self.root/'config').mkdir();(self.root/'config/v3-control.json').write_text(json.dumps(dict(generation='g',enabled=True)))
        self.verify(result,True)

    def test_all_group_schedule_fields_and_version_are_reverified(self):
        result=runtime.calculate(self.data)
        for field in ('strategy_version','revision','group_labels','group_pair_ids','group_schedules','group_probabilities','smart_started_at',
                      'group_keys','no_space_by_group','merged_with_A_by_group','probabilities','effective_key','effective_action'):
            with self.subTest(field=field):
                changed=deepcopy(result);changed['decision_receipt']['smart_assignment'][field]='tampered'
                self.recalc_hash(changed)
                with self.assertRaises(ValueError):self.verify(changed)

    def test_mixed_platform_labels_select_the_joint_candidate(self):
        policy=dict(epoch=0,group_results={},repairs_by_group={
            'console':{'0':dict(label='B',pair_id='old-console-pair')},
            'pc':{'0':dict(label='C',pair_id='old-pc-pair')}})
        self.db.put('metadata','smart-policy:'+smart.policy_suffix(self.plan)+':0',policy)
        result=runtime.calculate(self.data);saved=result['decision_receipt']['smart_assignment']
        self.assertEqual(saved['label'],'MIXED')
        self.assertEqual(saved['group_labels'],dict(console='B',pc='C'))
        self.assertEqual(result['decision_receipt']['action'],saved['variants']['BC']['action'])
        baseline=saved['baseline_candidate']['action']['base_prices']
        self.assertLess(Decimal(saved['effective_action']['base_prices']['console']),Decimal(baseline['console']))
        self.assertGreater(Decimal(saved['effective_action']['base_prices']['pc']),Decimal(baseline['pc']))
        self.verify(result)

    def test_merged_prices_combine_joint_probabilities(self):
        # A price floor above the competitive upper bound collapses all legal variants.
        for p in engine.PLATFORMS:self.data['offers'][p]['Lootbar']['usd_price']='.10'
        result=runtime.calculate(self.data);saved=result['decision_receipt']['smart_assignment']
        self.assertEqual(len(saved['effective_probabilities']),1)
        self.assertEqual(next(iter(saved['effective_probabilities'].values())),1)
        self.assertFalse(result['decision_receipt']['randomization_verified'])
        self.assertEqual(saved['no_space_by_group'],dict(console=True,pc=True))
        self.verify(result)

    def test_daily_arab_quote_and_rendering_survive_write_boundary_recheck(self):
        with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            daily=self.db.create_plan('daily',['base:console','base:pc'],engine.current_action(self.data))
            daily['parameters'].update(competitor_policy=POLICY,region_pricing='global')
            self.db.put('pricing_plans',daily['plan_id'],daily);self.db.activate_plan(daily['plan_id'],now=NOW)
        missing(self.data,'Lootbar')
        result=runtime.calculate(self.data);self.verify(result)
        for row in result['rows']:
            self.assertIn('ArabUT',row['status']);self.assertNotIn('ItemD2R',row['status'])

    def test_collection_scope_passes_current_plan_policy_to_sources(self):
        with patch('automation_policy.load_policy',return_value=dict(interval_minutes=60)):
            scope=runtime.collection_scope(self.db,self.data['run_id'])['scope']
        self.assertEqual(scope['competitor_policy'],POLICY)
        self.assertEqual(scope['region_pricing'],'global')


if __name__=='__main__':unittest.main()

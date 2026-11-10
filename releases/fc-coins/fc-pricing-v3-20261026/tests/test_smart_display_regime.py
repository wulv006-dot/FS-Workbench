from datetime import timedelta
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import smart
from fc_pricing_v3.ledger import Ledger
from test_smart_bidirectional import plan,START
import test_bidirectional_runtime as runtime_tests
from fc_pricing_v3 import runtime
from test_dual20_sprint import NOW

def evidence(at,console='a',pc='b',price='10'):
    return {'checked_at':at.isoformat(),'storefront':{'rows':{p:dict(status='ok',checked_at=at.isoformat(),display_observed_at=at.isoformat(),
        display_status='verified' if key else 'unknown',display_regime_key=key*64 if key else None,
        package_usd=price,display_package_usd='8.5') for p,key in [('PS',console),('XBOX',console),('PC',pc)]}}}

class DisplayRegime(unittest.TestCase):
    def test_failed_refresh_and_missing_display_cannot_reuse_known_winner(self):
        for status in ('unknown','invalid','unavailable','missing'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                db=Ledger(Path(folder)/'db');p=plan()
                context=smart.observe_display(db,p,evidence(START),START)
                first=smart.epoch_policy(db,p,START,0,display=context)
                oldkey=first['display_policy_keys']['console'];cached=db.get('metadata',oldkey)
                cached['group_results']['console'].update(winner='B',status='OBSERVED_WINNER')
                db.put('metadata',oldkey,cached)
                current=evidence(START+timedelta(hours=1))
                row=current['storefront']['rows']['XBOX']
                if status=='unavailable':
                    row.update(evidence(START)['storefront']['rows']['XBOX']);row['status']='unavailable'
                elif status=='missing':
                    current['storefront']['rows']['XBOX']={}
                else:row['display_status']=status
                changed=smart.observe_display(db,p,current,START+timedelta(hours=1))
                self.assertIsNone(changed['groups']['console']['key'])
                self.assertEqual(changed['groups']['pc']['key'],context['groups']['pc']['key'])
                policy=smart.epoch_policy(db,p,START+timedelta(hours=1),0,display=changed)
                self.assertIsNone(policy['group_results']['console']['winner'])
                scheduled=smart.assignment(p,START+timedelta(hours=1),policy=policy)
                self.assertEqual(scheduled['group_schedules'],smart.assignment(p,START+timedelta(hours=1))['group_schedules'])
                self.assertEqual(db.get('metadata',oldkey)['group_results']['console']['winner'],'B')

    def test_unknown_regime_keeps_exploration_at_next_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db');p=plan()
            context=smart.observe_display(db,p,evidence(START,console=None),START)
            smart.epoch_policy(db,p,START,0,display=context)
            later=START+timedelta(hours=48)
            policy=smart.epoch_policy(db,p,later,1,display=context)
            self.assertEqual(policy['repairs_by_group']['console'],{})
            self.assertEqual(smart.assignment(p,later,policy=policy)['group_schedules']['console'],
                             smart.assignment(p,later)['group_schedules']['console'])

    def test_old_frozen_quotes_never_rewrite_newer_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db');p=plan()
            smart.observe_display(db,p,evidence(START),START)
            changed=smart.observe_display(db,p,evidence(START+timedelta(hours=2),console='c'),START+timedelta(hours=2))
            for frozen in (evidence(START+timedelta(hours=1)),evidence(START+timedelta(hours=1),console=None)):
                replay=smart.observe_display(db,p,frozen,START+timedelta(hours=3))
                self.assertEqual(replay,changed)

    def test_failed_rows_retained_timestamp_is_not_current_display_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db');p=plan()
            smart.observe_display(db,p,evidence(START),START)
            failed=evidence(START);failed['checked_at']=(START+timedelta(hours=1)).isoformat()
            for row in failed['storefront']['rows'].values():row['status']='unavailable'
            changed=smart.observe_display(db,p,failed,START+timedelta(hours=1))
            for state in changed['groups'].values():
                self.assertIsNone(state['key'])
                self.assertEqual(state['segments'][0]['end'],START.isoformat())

    def test_first_known_never_backdates_and_price_changes_do_not_change_regime(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            self.assertIsNone(smart.observe_display(db,plan(),{},START))
            first=smart.observe_display(db,plan(),evidence(START+timedelta(hours=1)),START+timedelta(hours=1))
            later=smart.observe_display(db,plan(),evidence(START+timedelta(hours=2),price='10.30'),START+timedelta(hours=2))
            self.assertEqual(first['groups']['console']['key'],later['groups']['console']['key'])
            intervals=smart.display_intervals(later,'console',START,START+timedelta(hours=3))
            self.assertEqual(intervals,[(START+timedelta(hours=1),START+timedelta(hours=3))])

    def test_transition_unknown_gap_and_return_to_same_rule_preserve_old_segments(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            for hour,key in [(0,'a'),(1,'a'),(2,'c'),(3,None),(4,'a')]:
                context=smart.observe_display(db,plan(),evidence(START+timedelta(hours=hour),console=key),START+timedelta(hours=hour))
            intervals=smart.display_intervals(context,'console',START,START+timedelta(hours=5))
            self.assertEqual(intervals,[(START,START+timedelta(hours=1)),(START+timedelta(hours=4),START+timedelta(hours=5))])
            self.assertEqual(smart.display_intervals(context,'pc',START,START+timedelta(hours=5)),[(START,START+timedelta(hours=5))])

    def test_observed_blocks_clip_actual_events_and_keep_physical_window_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            context=smart.observe_display(db,plan(),evidence(START+timedelta(hours=1)),START+timedelta(hours=1))
            info=smart.assignment(plan(),START);info.update(group_keys={'console':'price'},merged_with_A_by_group={'console':False})
            action={'base_prices':{'console':'10'},'region_coefficients':{}}
            op=dict(operation_id='op',plan_id='p',status='COMPLETED',completed_at=START.isoformat(),resources=['base:console'],bundle=dict(action=action,smart_assignment=info))
            window=dict(operation_id='op',action=action)
            rows=[dict(price_window_id='op',group='console',occurred_at=(START+timedelta(minutes=m)).isoformat(),actual_net_usd='9',actual_contribution_usd='2',new_customer=False) for m in (30,90)]
            blocks=smart.observed_blocks(plan(),[op],rows,[window],START+timedelta(hours=3),epoch=None,group='console',display=context)
            self.assertEqual(blocks[0]['hours'],'2.0');self.assertEqual(blocks[0]['orders'],1)
            self.assertEqual(blocks[0]['net'],'9');self.assertEqual(window,dict(operation_id='op',action=action))
            self.assertEqual(op['completed_at'],START.isoformat())

    def test_policy_and_correction_isolate_only_changed_platform(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db');p=plan()
            oldkey='smart-policy:'+smart.policy_suffix(p)+':0'
            db.put('metadata',oldkey,{'group_results':{'console':{'winner':'B'},'pc':{'winner':'C'}}})
            context=smart.observe_display(db,p,evidence(START),START)
            policy=smart.epoch_policy(db,p,START,0,display=context)
            self.assertIsNone(policy['group_results']['console']['winner'])
            console_key=policy['display_policy_keys']['console'];pc_key=policy['display_policy_keys']['pc']
            saved=db.get('metadata',console_key);saved['group_results']['console'].update(winner='B',status='OBSERVED_WINNER')
            db.put('metadata',console_key,saved)
            ckey='smart-correction:'+smart.display_suffix(p,context,'console')
            db.put('metadata',ckey,{'groups':{'console':{'effective_blocks':{'C':1}}}})
            changed=smart.observe_display(db,p,evidence(START+timedelta(hours=1),pc='c'),START+timedelta(hours=1))
            policy=smart.epoch_policy(db,p,START+timedelta(hours=1),0,display=changed)
            correction=smart.early_correction(db,p,START+timedelta(hours=1),0,display=changed)
            self.assertEqual(policy['group_results']['console']['winner'],'B')
            self.assertIsNone(policy['group_results']['pc']['winner'])
            self.assertEqual(policy['display_policy_keys']['console'],console_key)
            self.assertNotEqual(policy['display_policy_keys']['pc'],pc_key)
            self.assertEqual(correction['groups']['console']['effective_blocks'],{'C':1})
            self.assertEqual(correction['groups']['pc']['effective_blocks'],{})
            self.assertEqual(db.get('metadata',oldkey)['group_results']['pc']['winner'],'C')

    def test_pairs_reject_mixed_regimes_without_selecting_by_financial_result(self):
        a=dict(intervals=[[0,10800]],display_regime_key='a')
        b=dict(intervals=[[0,10800]],display_regime_key='b')
        self.assertIsNone(smart.paired_exposure([a],[b]))
        self.assertIsNotNone(smart.paired_exposure([a],[dict(b,display_regime_key='a')]))

class DisplayRuntime(unittest.TestCase):
    setUp=runtime_tests.BidirectionalRuntime.setUp
    verify=runtime_tests.BidirectionalRuntime.verify

    def display(self,at=NOW,console='a'):
        fields=evidence(at,console=console)['storefront']['rows']
        for platform,row in self.data['storefront']['rows'].items():
            row.update({key:value for key,value in fields[platform].items() if key.startswith('display_') or key=='checked_at'})
        self.data['checked_at']=at.isoformat()

    def enable_execution_check(self):
        (self.root/'config').mkdir()
        (self.root/'config/v3-control.json').write_text(json.dumps(dict(generation='g',enabled=True)))

    def test_real_quote_persists_regime_policy_and_execution_rechecks_same_cache(self):
        self.display();self.enable_execution_check()
        first=runtime.calculate(self.data)
        policy=first['decision_receipt']['smart_assignment']['policy']
        key=smart.policy_key(self.plan,0,policy)
        self.assertEqual(self.db.get('metadata',key),policy)
        self.assertEqual(set(policy['display_group_keys']),{'console','pc'})
        self.verify(first,True)
        self.data['run_id']='next-display'
        at=NOW+timedelta(seconds=1);self.display(at,console='c')
        with patch.object(runtime,'clock',return_value=at):second=runtime.calculate(self.data)
        second_policy=second['decision_receipt']['smart_assignment']['policy']
        self.assertNotEqual(smart.policy_key(self.plan,0,second_policy),key)
        self.assertEqual(self.db.get('metadata',key),policy)
        runtime.verify_quote(dict(evidence=self.data,result=second),dict(minimum_gross_margin_pct='20'),
            ['PS','XBOX','PC'],now=at,for_execution=True)
        newkey=smart.policy_key(self.plan,0,second_policy)
        self.db.put('metadata',newkey,dict(status='tampered'))
        with self.assertRaisesRegex(ValueError,'pricing_smart_policy_changed'):
            runtime.verify_quote(dict(evidence=self.data,result=second),dict(minimum_gross_margin_pct='20'),
                ['PS','XBOX','PC'],now=at,for_execution=True)

    def test_invalid_display_keeps_candidate_schedule_price_and_financial_proof(self):
        baseline=runtime.calculate(self.data)
        self.display();known=runtime.calculate(self.data)
        self.enable_execution_check();self.verify(known,True)
        self.data['run_id']='invalid-display'
        at=NOW+timedelta(seconds=1);self.display(at)
        self.data['storefront']['rows']['PS']['display_status']='invalid'
        with patch.object(runtime,'clock',return_value=at):current=runtime.calculate(self.data)
        original=baseline['decision_receipt'];receipt=current['decision_receipt']
        self.assertEqual(receipt['action'],original['action'])
        self.assertEqual(receipt['financial_proof'],original['financial_proof'])
        self.assertEqual(receipt['smart_assignment']['group_schedules'],original['smart_assignment']['group_schedules'])
        self.assertIsNone(receipt['smart_assignment']['policy']['display_group_keys']['console'])
        self.assertIsNotNone(receipt['smart_assignment']['policy']['display_group_keys']['pc'])
        runtime.verify_quote(dict(evidence=self.data,result=current),dict(minimum_gross_margin_pct='20'),
            ['PS','XBOX','PC'],now=at,for_execution=True)
        self.assertEqual(self.db.all('actual_price_windows'),[])
        self.assertEqual(self.db.all('operations'),[])

if __name__=='__main__':unittest.main()

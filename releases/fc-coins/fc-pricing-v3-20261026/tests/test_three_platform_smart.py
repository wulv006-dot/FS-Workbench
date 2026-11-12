from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal
import tempfile
import unittest
from fc_pricing_v3 import smart
from fc_pricing_v3.order_close import admin_targets

START=datetime(2026,11,10,tzinfo=timezone.utc)
def plan():
    return dict(plan_id='three',revision=3,mode='smart',starts_at=(START-timedelta(days=3)).isoformat(),smart_started_at=START.isoformat(),smart_strategy_version='smart-three-platform-v3',resources=['base:PS','base:XBOX','base:PC'])

class ThreePlatformTest(unittest.TestCase):
    def test_three_native_independent_schedules(self):
        policy={'group_results':{'PS':{'winner':'B'},'XBOX':{'winner':'C'},'PC':{'winner':None}}}
        info=smart.assignment(plan(),START+timedelta(hours=48),policy=policy)
        self.assertEqual(set(info['group_labels']),{'PS','XBOX','PC'})
        self.assertEqual(info['group_schedules']['PS'].count('B'),12)
        self.assertEqual(info['group_schedules']['XBOX'].count('C'),12)
        self.assertEqual(info['starts_at'],(START+timedelta(hours=48)).isoformat())
        self.assertNotEqual(info['group_schedules']['PS'],info['group_schedules']['XBOX'])

    def test_native_order_targets_and_legacy_original_receipt(self):
        op={'dispatch_context':{'selected':['XBOX']},'bundle':{'action':{'base_prices':{'PS':'8','XBOX':'9','PC':'6'}}}}
        self.assertEqual(admin_targets(op),[{'platform':'XBOX','quote':'9'}])
        op['bundle']['action']['base_prices']={'console':'7','pc':'6'}
        self.assertEqual(admin_targets(op),[{'platform':'XBOX','quote':'7'}])

    def test_ps_only_confirmation_does_not_cut_or_relabel_xbox(self):
        p=plan();info=smart.assignment(p,START)
        info.update(group_keys={g:g for g in ('PS','XBOX','PC')},merged_with_A_by_group={g:False for g in ('PS','XBOX','PC')})
        action={'base_prices':{'PS':'8','XBOX':'9','PC':'6'},'region_coefficients':{}}
        op=dict(plan_id='three',status='COMPLETED',completed_at=START.isoformat(),resources=['base:XBOX'],bundle=dict(action=action,mutable_resources=['base:XBOX'],smart_assignment=info))
        other=dict(op,completed_at=(START+timedelta(hours=1)).isoformat(),resources=['base:PS'],bundle=dict(action=action,mutable_resources=['base:PS'],smart_assignment=info))
        rows=smart.observed_blocks(p,[op,other],[],[],START+timedelta(hours=3),epoch=None,group='XBOX')
        self.assertEqual(len(rows),1)
        self.assertEqual(Decimal(rows[0]['hours']),3)
        self.assertEqual(rows[0]['intervals'],[[0.0,10800.0]])

    def test_xbox_unknown_display_has_its_own_namespace_and_keeps_draws(self):
        from fc_pricing_v3.ledger import Ledger
        with tempfile.TemporaryDirectory() as directory:
            db=Ledger(Path(directory)/'test.db');p=plan()
            evidence={'checked_at':START.isoformat(),'storefront':{'rows':{platform:dict(status='ok',display_status='verified',display_regime_key='a'*64,display_observed_at=START.isoformat(),checked_at=START.isoformat()) for platform in ('PS','XBOX','PC')}}}
            known=smart.observe_display(db,p,evidence,START)
            old=smart.epoch_policy(db,p,START,0,display=known);oldkey=smart.policy_key(p,0,old)
            later=START+timedelta(seconds=1);evidence['checked_at']=later.isoformat()
            evidence['storefront']['rows']['XBOX']['display_status']='invalid'
            current=smart.observe_display(db,p,evidence,later)
            self.assertIsNone(current['groups']['XBOX']['key'])
            self.assertEqual(current['groups']['PS']['key'],known['groups']['PS']['key'])
            policy=smart.epoch_policy(db,p,later,0,display=current)
            self.assertIsNone(policy['group_results']['XBOX']['winner'])
            self.assertNotEqual(smart.policy_key(p,0,policy),oldkey)
            self.assertEqual(db.get('metadata',oldkey),old)
            self.assertEqual(set(smart.assignment(p,later,policy=policy)['group_labels']),{'PS','XBOX','PC'})

    def test_100k_specification_changes_observation_regime_without_rewriting_old_window(self):
        from fc_pricing_v3.ledger import Ledger
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as directory:
            db=Ledger(Path(directory)/'test.db');p=plan()
            evidence=dict(checked_at=START.isoformat(),storefront={'rows':{platform:dict(status='ok',display_status='verified',display_regime_key='a'*64,display_observed_at=START.isoformat(),checked_at=START.isoformat()) for platform in ('PS','XBOX','PC')}},promotion_envelope={'packages':{platform:{'tiers':[{'base_k':'100','bonus_k':'5','retained_ratio':'1'}]} for platform in ('PS','XBOX','PC')}})
            old=smart.observe_display(db,p,evidence,START)
            changed=deepcopy(evidence);at=START+timedelta(hours=1);changed['checked_at']=at.isoformat()
            for platform in ('PS','XBOX','PC'):
                changed['storefront']['rows'][platform].update(checked_at=at.isoformat(),display_observed_at=at.isoformat())
                changed['promotion_envelope']['packages'][platform]['tiers'][0]['bonus_k']='0'
            new=smart.observe_display(db,p,changed,at)
            for platform in ('PS','XBOX','PC'):
                self.assertNotEqual(old['groups'][platform]['key'],new['groups'][platform]['key'])
                self.assertEqual(new['groups'][platform]['segments'][0]['key'],old['groups'][platform]['key'])
                self.assertEqual(smart.display_intervals(new,platform,START,at),[])

    def test_platform_fallback_keeps_other_platform_direction(self):
        from unittest.mock import patch
        def build(evidence,p,current,baseline,labels,now):
            if labels['XBOX']=='C':raise ValueError('NO_SAFE_COMMIT_PATH')
            return {'action':dict(base_prices=dict(labels))}
        with patch.object(smart,'build_candidate',side_effect=build):
            result=smart.candidate_or_baseline({},plan(),{}, {},{'PS':'B','XBOX':'C','PC':'C'},START)
        self.assertEqual(result['action']['base_prices'],{'PS':'B','XBOX':'A','PC':'C'})
        self.assertEqual(set(result['smart_reasons_by_group']),{'XBOX'})

    def test_new_daily_attribution_does_not_relabel_other_platform(self):
        from fc_pricing_v3.daily import profit_summary
        action={'base_prices':{'PS':'8','XBOX':'9','PC':'6'},'region_coefficients':{}}
        window=dict(operation_id='x',plan_id='original',action=action,resources=['base:XBOX'],opened_at=START.isoformat())
        original=dict(operation_id='x',plan_id='original',status='COMPLETED',completed_at=START.isoformat(),resources=['base:XBOX'],bundle=dict(action=action,mutable_resources=['base:XBOX'],smart_assignment=dict(strategy_version=smart.STRATEGY_VERSION,group_labels={'XBOX':'B'})))
        later=dict(operation_id='ps',plan_id='later',status='COMPLETED',completed_at=(START+timedelta(hours=1)).isoformat(),resources=['base:PS'],bundle=dict(action=action,mutable_resources=['base:PS'],authorized_resources=plan()['resources'],smart_assignment=dict(strategy_version=smart.STRATEGY_VERSION,group_labels={'XBOX':'C','PS':'A'})))
        row=dict(price_window_id='x',platform='XBOX',group='XBOX',occurred_at=(START+timedelta(hours=2)).isoformat(),actual_net_usd='9',actual_contribution_usd='2',new_customer=False)
        result=profit_summary({'actual_outcomes':[row]},[window],[original,later],'2026-11-10','original')
        group=result['review_day']['groups'][0]
        self.assertEqual((group['plan_id'],group['group'],group['label']),('original','XBOX','B'))
        self.assertEqual(result['active_plan']['totals']['orders'],1)

    def test_low_volume_accumulates_fixed_clock_strata(self):
        rows=[]
        for epoch in range(6):
            for slot in (0,1):
                for label,gross in [('A','1'),('C','1.2')]:
                    rows.append(dict(epoch=epoch,slot=slot,pair_id=f'{epoch}:{slot}',label=label,hours='3',complete=True,prices=[label],intervals=[[0,10800]],events=[dict(offset=10,actual_net_usd='5',actual_contribution_usd=gross,new_customer=True,customer_key=f'{epoch}:{slot}:{label}')]))
        self.assertEqual(smart.assess_strata(rows,complete=True)['winner'],'C')
        self.assertIsNone(smart.assess(rows,complete=True)['winner'])
        self.assertIsNone(smart.assess_strata([r for r in rows if r['slot']==0],complete=True)['winner'])
        rows[1]['events'][0]['actual_contribution_usd']=None
        self.assertIsNone(smart.assess_strata(rows,complete=True)['winner'])

class ThreePlatformMigrationTest(unittest.TestCase):
    def test_migration_preserves_grid_control_and_original_windows(self):
        from fc_pricing_v3.ledger import Ledger
        from fc_pricing_v3 import ledger, scheduler
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            db=Ledger(Path(directory)/'test.db')
            old=plan();old.update(revision=2,state='ACTIVE',generation='g',smart_strategy_version='smart-bidirectional-v2',smart_started_at=(START-timedelta(minutes=23)).isoformat(),resources=['base:console','base:pc'],price_anchor={'base_prices':{'console':'8','pc':'6'},'region_coefficients':{}},ends_at=None)
            old['baseline_plan']=dict(plan_id='b',revision=1,mode='revenue_sprint',resources=old['resources'],price_anchor=old['price_anchor'],parameters={})
            db.put('pricing_plans','three',old)
            db.put('metadata','generation',{'id':'g'})
            db.put('metadata','price_control',dict(revision=7,manual_enabled=True,manual_prices={'console':'8','pc':'6'},uplift_enabled=False,uplift_pct='0'))
            with db.transaction() as conn:
                for resource in old['resources']:conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,'three',2,'g'))
            due=START+timedelta(minutes=37);job='cycle:three:'+str(int(due.timestamp()))+':r0'
            db.enqueue('cycle',job,due,dict(plan_id='three',revision=2,scheduled_at=due.isoformat()))
            with patch.object(ledger,'clock',return_value=START):new=db.migrate_smart_strategy('three',2,'test')
            with db.connect() as conn:
                jobs=conn.execute("SELECT id,body FROM durable_jobs WHERE kind='cycle'").fetchall()
                self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['id'],job)
                self.assertEqual(__import__('json').loads(jobs[0]['body'])['revision'],3)
            self.assertEqual(new['smart_started_at'],(START+timedelta(minutes=37)).isoformat())
            self.assertEqual(set(new['resources']),{'base:PS','base:XBOX','base:PC'})
            self.assertEqual(new['price_anchor']['base_prices'],{'PS':'8','XBOX':'8','PC':'6'})
            self.assertEqual(db.price_control()['manual_prices'],{'PS':'8','XBOX':'8','PC':'6'})
            self.assertEqual(db.price_control()['revision'],8)
            self.assertEqual(scheduler.next_cycle_at(db,new,{'interval_minutes':60}),START+timedelta(minutes=37))
            with db.connect() as conn:self.assertEqual({row[0] for row in conn.execute('SELECT resource FROM plan_ownership')},set(new['resources']))

    def test_same_smart_version_still_migrates_new_financial_contract(self):
        from fc_pricing_v3.ledger import Ledger
        from fc_pricing_v3 import ledger
        from fc_pricing_v3.platforms import PRICE_SCOPE_CONTRACT
        from fc_pricing_v3.financial import FINANCIAL_CONTRACT_VERSION
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            db=Ledger(Path(directory)/'test.db');old=plan()
            old.update(state='ACTIVE',generation='g',ends_at=None,parameters={},price_scope_contract=PRICE_SCOPE_CONTRACT,financial_contract_version='fc27_dual20_d9_d2_platform_v3',price_anchor=dict(base_prices={'PS':'8','XBOX':'9','PC':'6'},region_coefficients={}))
            old['baseline_plan']=dict(plan_id='base',revision=1,mode='revenue_sprint',resources=old['resources'],price_anchor=old['price_anchor'],parameters={})
            db.put('pricing_plans','three',old);db.put('metadata','generation',{'id':'g'})
            with db.transaction() as conn:
                for resource in old['resources']:conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,'three',3,'g'))
            with patch.object(ledger,'clock',return_value=START):new=db.migrate_smart_strategy('three',3,'test')
            self.assertEqual(new['revision'],4)
            self.assertEqual(new['financial_contract_version'],FINANCIAL_CONTRACT_VERSION)
            self.assertEqual(new['smart_started_at'],(START+timedelta(hours=1)).isoformat())
            self.assertNotEqual(smart.policy_suffix(old),smart.policy_suffix(new))

    def test_paused_and_draft_financial_route_migrates_all_contracts_without_cycle(self):
        from fc_pricing_v3.ledger import Ledger
        from fc_pricing_v3 import ledger
        from fc_pricing_v3.financial import FINANCIAL_CONTRACT_VERSION
        from unittest.mock import patch
        for state in ('SUSPENDED','DRAFT'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as directory:
                db=Ledger(Path(directory)/'test.db');old=plan()
                old.update(state=state,generation='g',resources=['base:console','base:pc'],ends_at=None,parameters={},smart_strategy_version='smart-bidirectional-v2',financial_contract_version='fc27_dual20_d9_d2_v2',price_anchor=dict(base_prices={'console':'8','pc':'6'},region_coefficients={}))
                old['baseline_plan']=dict(plan_id='base',revision=1,mode='revenue_sprint',resources=old['resources'],price_anchor=old['price_anchor'],parameters={})
                owner='three' if state=='SUSPENDED' else 'base';revision=3 if state=='SUSPENDED' else 1
                old['takeover_owners']={r:[owner,revision,'g'] for r in old['resources']}
                db.put('pricing_plans','three',old);db.put('metadata','generation',{'id':'g'})
                with db.transaction() as conn:
                    for resource in old['resources']:conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,owner,revision,'g'))
                with patch.object(ledger,'clock',return_value=START):new=db.migrate_financial_contract('three',3,'test')
                self.assertEqual(new['state'],state)
                self.assertEqual(new['smart_strategy_version'],smart.STRATEGY_VERSION)
                self.assertEqual(new['financial_contract_version'],FINANCIAL_CONTRACT_VERSION)
                self.assertEqual(set(new['resources']),{'base:PS','base:XBOX','base:PC'})
                with db.connect() as conn:self.assertEqual(conn.execute("SELECT COUNT(*) FROM durable_jobs WHERE kind='cycle'").fetchone()[0],0)
                if state=='DRAFT':
                    activated=db.activate_plan('three',now=START+timedelta(hours=1))
                    self.assertEqual(activated['state'],'ACTIVE')
                    with db.connect() as conn:self.assertEqual({row[0] for row in conn.execute('SELECT resource FROM plan_ownership')},set(new['resources']))

    def test_old_console_window_closes_each_native_platform_independently(self):
        from fc_pricing_v3.ledger import Ledger
        with tempfile.TemporaryDirectory() as directory:
            db=Ledger(Path(directory)/'test.db')
            action={'base_prices':{'console':'8','pc':'6'},'region_coefficients':{}}
            db.put('actual_price_windows','old',dict(operation_id='old',resources=['base:console'],action=action,opened_at=START.isoformat()))
            def record(platform):
                op=dict(operation_id=platform,resources=['base:'+platform],bundle=dict(action={'base_prices':{'PS':'9','XBOX':'10','PC':'6'},'region_coefficients':{}},assignment_id='new'))
                with db.transaction() as conn:db.record_price_window(op,conn)
            record('PS');window=db.get('actual_price_windows','old')
            self.assertNotIn('closed_at',window)
            self.assertEqual(set(window['resource_closed_at']),{'base:PS'})
            record('XBOX');window=db.get('actual_price_windows','old')
            self.assertIn('closed_at',window)
            self.assertEqual(window['action'],action)

if __name__=='__main__':unittest.main()

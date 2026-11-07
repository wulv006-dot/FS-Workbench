from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from fc_pricing_v3 import smart, scheduler
from fc_pricing_v3.ledger import Ledger


VERSION = 'smart-bidirectional-v2'
START = datetime(2026, 11, 7, tzinfo=timezone.utc)


def plan():
    return dict(plan_id='p', revision=1, mode='smart', starts_at=(START-timedelta(days=2)).isoformat(),
                smart_started_at=START.isoformat(), smart_strategy_version=VERSION,
                resources=['base:console', 'base:pc'])


class BidirectionalTest(unittest.TestCase):
    def test_v2_prices_and_migration_anchor_are_isolated(self):
        tiers = {'PC': dict(base_k='100', bonus_k='5', retained_ratio='1')}
        self.assertEqual(smart.candidates('10', tiers, {'PC':'10'}, version=VERSION),
                         {'A':'10', 'B':'9.70', 'C':'10.30'})
        self.assertEqual(smart.candidates('2.03',tiers,{'PC':'10'},version=VERSION)['B'],'1.97')
        new = smart.assignment(plan(), START)
        self.assertEqual(new['epoch'], 0)
        self.assertEqual(new['strategy_version'], VERSION)
        self.assertEqual(new['starts_at'], START.isoformat())

    def test_platform_winners_are_independent(self):
        policy = {'group_results': {'console': {'winner':'B', 'excluded':[]},
                                    'pc': {'winner':'C', 'excluded':[]}}}
        info = smart.assignment(plan(), START+timedelta(hours=48), policy=policy)
        self.assertEqual(info['group_schedules']['console'].count('B'), 12)
        self.assertEqual(info['group_schedules']['pc'].count('C'), 12)
        self.assertNotEqual(info['group_schedules']['console'], info['group_schedules']['pc'])

    def test_actual_confirmation_and_versions(self):
        info = smart.assignment(plan(), START)
        info.update(group_keys={'console':'a'}, merged_with_A_by_group={'console':False})
        action = {'base_prices':{'console':'10'}, 'region_coefficients':{}}
        op = dict(plan_id='p', status='COMPLETED', completed_at=(START+timedelta(hours=1)).isoformat(),
                  resources=['base:console'], bundle=dict(action=action, smart_assignment=info))
        old = dict(op, bundle=dict(action=action, smart_assignment=dict(info, strategy_version='smart-v1')))
        rows = smart.observed_blocks(plan(), [old, op], [], [], START+timedelta(hours=3), epoch=None, group='console')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['hours'], '2.0')
        late = dict(op, completed_at=(START+timedelta(hours=4)).isoformat())
        self.assertEqual(smart.observed_blocks(plan(), [late], [], [], START+timedelta(hours=6), epoch=None, group='console'), [])

    def test_cross_epoch_pairs_are_kept_and_duplicate_attempts_do_not_inflate(self):
        def block(pair, label, epoch, gross):
            return dict(slot=0, epoch=epoch, pair_id=pair, label=label, hours='3', complete=True,
                        prices=[label], intervals=[[0,10800]],
                        events=[dict(offset=10+i, actual_net_usd='5', actual_contribution_usd=str(gross),
                                     new_customer=True, customer_key=str(i)) for i in range(10)])
        rows = [block('0:0','A',0,1), block('0:0','B',1,1.2),
                block('0:1','A',0,1), block('0:1','B',2,1.2)]
        self.assertEqual(smart.assess(rows, complete=True)['winner'], 'B')
        self.assertIsNone(smart.assess(rows[:2]+rows[:2], complete=True)['winner'])
        rows[1]['prices']=['A']
        self.assertIsNone(smart.assess(rows, complete=True)['winner'])

    def test_fixed_cadence_late_finish_restart_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            p=plan();db.put('pricing_plans','p',p)
            with db.transaction() as conn:
                scheduler.finish_cycle(db,conn,{'plan_id':'p','scheduled_at':START.isoformat()},
                                       {'status':'COMPLETED'},(START+timedelta(hours=1,minutes=7)).isoformat())
            p=db.get('pricing_plans','p')
            self.assertEqual(scheduler.next_cycle_at(db,p,{'interval_minutes':60}),START+timedelta(hours=1))
            resumed=dict(p,resumed_at=(START+timedelta(hours=5,minutes=17)).isoformat())
            self.assertEqual(scheduler.next_cycle_at(db,resumed,{'interval_minutes':60}),START+timedelta(hours=6))

    def test_expired_job_does_not_consume_current_live_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            db.put('pricing_plans','p',plan())
            with db.transaction() as conn:
                scheduler.finish_cycle(db,conn,{'plan_id':'p','scheduled_at':START.isoformat()},
                    {'status':'expired_cycle'},(START+timedelta(hours=4,minutes=5)).isoformat())
            next_at=scheduler.next_cycle_at(db,db.get('pricing_plans','p'),{'interval_minutes':60})
            self.assertLessEqual(next_at,START+timedelta(hours=4))

    def test_v2_real_candidate_proves_both_directions_and_floor(self):
        from test_dual20_sprint import source, NOW
        from fc_pricing_v3 import engine
        data=source(loot='10',item='11',cost='.1',bonus='5')
        p=dict(plan(),mode='revenue_sprint',price_anchor=engine.current_action(data),parameters={})
        evaluated=engine.evaluate(data,'revenue_sprint',plan=p,now=NOW)
        baseline=evaluated['selected']
        candidate=smart.candidate_or_baseline(data,p,evaluated['current'],baseline,{'console':'B','pc':'C'},NOW)
        self.assertLess(float(candidate['action']['base_prices']['console']),float(baseline['action']['base_prices']['console']))
        self.assertGreater(float(candidate['action']['base_prices']['pc']),float(baseline['action']['base_prices']['pc']))
        self.assertTrue(candidate['financial_proof']['pass_all'])
        data=source(loot='1',item='2',cost='.35',bonus='5')
        evaluated=engine.evaluate(data,'revenue_sprint',plan=p,now=NOW)
        baseline=evaluated['selected']
        candidate=smart.candidate_or_baseline(data,p,evaluated['current'],baseline,'B',NOW)
        self.assertTrue(candidate['financial_proof']['pass_all'])
        self.assertEqual(candidate['action']['base_prices'],baseline['action']['base_prices'])

    def test_repairs_are_frozen_same_clock_and_do_not_depend_on_profit(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            p=plan()
            policy=smart.epoch_policy(db,p,START,0)
            labels=smart.assignment(p,START,policy=policy)['group_schedules']['console']
            slot=next(i for i in range(8) if set((labels[i],labels[i+8]))=={'A','B'})
            label=labels[slot]
            rows={'console':[dict(epoch=0,slot=slot,pair_id='0:'+str(slot),label=label,hours='3',
                                  intervals=[[0,10800]],events=[],complete=True)],'pc':[]}
            before=smart.missing_repeats(db,p,1,rows)
            repairs=[(int(s),r) for s,r in before['console'].items() if r['pair_id']=='0:'+str(slot)]
            self.assertEqual(len(repairs),1)
            self.assertEqual(repairs[0][0]%8,slot)
            self.assertNotEqual(repairs[0][1]['label'],label)
            rows['console'][0]['events']=[{'actual_contribution_usd':'-10000'}]
            self.assertEqual(smart.missing_repeats(db,p,1,rows),before)
            first=smart.epoch_policy(db,p,START+timedelta(hours=48),1)
            self.assertEqual(first,smart.epoch_policy(db,p,START+timedelta(hours=49),1))
            repair=first['repairs_by_group']['console'][str(slot)]
            info=smart.assignment(p,START+timedelta(hours=48+3*slot),policy=first)
            self.assertEqual(info['group_pair_ids']['console'],repair['pair_id'])
            self.assertFalse(info['randomization_verified'])

    def test_stopped_direction_is_not_rescheduled_as_a_failed_trial(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            p=plan();smart.epoch_policy(db,p,START,0)
            repaired=smart.missing_repeats(db,p,1,{'console':[],'pc':[]},excluded_by_group={'console':['B','C']})
            self.assertEqual(repaired['console'],{})
            self.assertTrue(repaired['pc'])

    def test_partial_opposite_coverage_gets_fresh_same_clock_attempt(self):
        def block(label,epoch,interval,gross):
            return dict(slot=0,epoch=epoch,pair_id='0:0',label=label,hours='2',complete=True,prices=[label],
                        intervals=[interval],events=[dict(offset=4000+i,actual_net_usd='5',actual_contribution_usd=str(gross),
                                                        new_customer=True,customer_key=str(i)) for i in range(10)])
        rows=[block('A',0,[0,7200],1),block('B',0,[3600,10800],1.2)]
        self.assertIsNone(smart.paired_exposure([rows[0]],[rows[1]]))
        rows.append(block('B',1,[0,10800],1.2))
        self.assertIsNotNone(smart.paired_exposure([rows[0]],rows[1:]))

    def test_existing_unknown_is_reconciled_even_when_cycle_is_expired(self):
        p=dict(plan(),state='ACTIVE')
        operation=dict(status='UNKNOWN',operation_id='original')
        db=MagicMock()
        db.get.side_effect=lambda table,key: p if table=='pricing_plans' else operation if table=='operations' else None
        worker=SimpleNamespace(collect_quote=MagicMock())
        with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'reconcile',return_value=operation) as reconcile, \
             patch.object(scheduler,'clock',return_value=START+timedelta(hours=4)), \
             patch.dict('sys.modules',{'fc27_cloud_worker':worker}):
            result=scheduler.cycle(dict(plan_id='p',revision=1,request_id='old',scheduled_at=START.isoformat()))
        self.assertEqual(result['status'],'UNKNOWN')
        reconcile.assert_called_once()
        worker.collect_quote.assert_not_called()

    def test_expired_cycle_without_operation_never_collects_or_writes(self):
        p=dict(plan(),state='ACTIVE')
        db=MagicMock()
        db.get.side_effect=lambda table,key: p if table=='pricing_plans' else None
        db.all.return_value=[]
        worker=SimpleNamespace(collect_quote=MagicMock())
        with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'execute_run') as execute, \
             patch.object(scheduler,'clock',return_value=START+timedelta(hours=4)), \
             patch('automation_policy.load_policy',return_value={'interval_minutes':60}), \
             patch.dict('sys.modules',{'fc27_cloud_worker':worker}):
            result=scheduler.cycle(dict(plan_id='p',revision=1,request_id='old',scheduled_at=START.isoformat()))
        self.assertEqual(result['status'],'expired_cycle')
        worker.collect_quote.assert_not_called()
        execute.assert_not_called()

    def test_collection_crossing_block_boundary_does_not_dispatch_stale_quote(self):
        p=dict(plan(),state='ACTIVE')
        db=MagicMock()
        db.get.side_effect=lambda table,key: p if table=='pricing_plans' else None
        db.all.return_value=[]
        current=[START+timedelta(hours=2,minutes=59)]
        def collect(job):
            current[0]=START+timedelta(hours=3,minutes=1)
            return {'run_id':'quote'}
        worker=SimpleNamespace(collect_quote=MagicMock(side_effect=collect),save_job=MagicMock())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'quotes').mkdir();(root/'quotes/quote.json').write_text('{}')
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'execute_run') as execute, \
                 patch.object(scheduler,'clock',side_effect=lambda:current[0]),patch.object(scheduler,'ROOT',root), \
                 patch('fc_pricing_v3.business_source.history_ES_blocker',return_value=None), \
                 patch('automation_policy.load_policy',return_value={'interval_minutes':60,'revision':1,'system_enabled':True,'mode':'auto'}), \
                 patch.dict('sys.modules',{'fc27_cloud_worker':worker}):
                result=scheduler.cycle(dict(plan_id='p',revision=1,request_id='late',scheduled_at=(START+timedelta(hours=2)).isoformat()))
        self.assertEqual(result['status'],'expired_cycle')
        execute.assert_not_called()

    def test_restarted_scheduler_runs_current_slot_once_without_backlog(self):
        from fc_pricing_v3 import runtime
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            p=dict(plan(),state='ACTIVE',generation='g',resume_count=1)
            db.put('metadata','generation',{'id':'g'});db.put('pricing_plans','p',p)
            with db.transaction() as conn:
                for group in ('console','pc'):
                    conn.execute("INSERT INTO plan_ownership VALUES (?,'p',1,'g')",('base:'+group,))
            future=MagicMock();future.done.return_value=False
            executors={lane:MagicMock() for lane in ('collection','control','observation','outcomes')}
            executors['collection'].submit.return_value=future
            running={}
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'export_shadow_snapshot'), \
                 patch.object(scheduler,'clock',return_value=START+timedelta(hours=7,minutes=15)),patch.object(runtime,'write_json'), \
                 patch('fc_pricing_v3.daily.due_date',return_value=None), \
                 patch('automation_policy.load_policy',return_value={'interval_minutes':60}):
                scheduler.tick(executors,running)
                scheduler.tick(executors,running)
            with db.connect() as conn:
                rows=conn.execute("SELECT body FROM durable_jobs WHERE kind='cycle'").fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0][0])['scheduled_at'],(START+timedelta(hours=7)).isoformat())
            executors['collection'].submit.assert_called_once()

    def test_one_platform_failed_path_does_not_erase_other_direction(self):
        p=plan()
        calls=[]
        def build(evidence,p,current,base,labels,now):
            calls.append(dict(labels))
            if labels['console']=='B':
                raise ValueError('NO_SAFE_COMMIT_PATH')
            return {'action':{'base_prices':{'console':'10','pc':'10.30' if labels['pc']=='C' else '10'}}}
        with patch.object(smart,'build_candidate',side_effect=build):
            result=smart.candidate_or_baseline({},p,{}, {},{'console':'B','pc':'C'},START)
        self.assertEqual(calls[-1],{'console':'A','pc':'C'})
        self.assertEqual(result['action']['base_prices']['pc'],'10.30')


if __name__ == '__main__':
    unittest.main()

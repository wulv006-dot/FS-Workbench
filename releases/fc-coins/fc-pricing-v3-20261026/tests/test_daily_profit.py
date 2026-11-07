import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import daily, runtime, scheduler, history
from fc_pricing_v3.ledger import Ledger
import hermes_pricing_bridge as bridge


class DailyProfit(unittest.TestCase):
    def setUp(self):
        self.windows=[dict(operation_id='w',plan_id='p',mode='production',opened_at='2026-11-06T00:00:00+00:00',resources=['base:console','base:pc'])]
        self.ops=[dict(operation_id='w',plan_id='p',bundle=dict(smart_assignment=dict(label='B')))]
        self.rows=[dict(order_key='private-order',customer_key='private-customer',price_window_id='w',
            occurred_at='2026-11-06T15:59:00+00:00',group='console',actual_net_usd='100',
            actual_contribution_usd='25',new_customer=True),
            dict(order_key='missing',price_window_id='w',occurred_at='2026-11-06T16:01:00+00:00',
            group='pc',actual_net_usd='50',actual_contribution_usd=None,new_customer=None)]
        self.online=dict(actual_outcomes=self.rows,learning_coverage=dict(observed_at='2026-11-07T02:20:00+08:00',query_complete=True))

    def continuation(self,ident,at,plan,label,resources):
        self.windows[0].setdefault('continuations',[]).append(dict(operation_id=ident,at=at,resources=resources))
        self.ops.append(dict(operation_id=ident,plan_id=plan,status='NO_CHANGE',completed_at=at,
            bundle=dict(smart_assignment=dict(label=label,starts_at='2026-11-06T14:00:00+00:00'))))

    def test_same_price_plan_switch_uses_confirmed_time_not_window_owner_or_planned_start(self):
        self.continuation('next','2026-11-06T16:00:00+00:00','next-plan','A',['base:console','base:pc'])
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','next-plan')
        self.assertEqual(result['review_day']['groups'][0]['plan_id'],'p')
        self.assertEqual(result['active_plan']['totals']['orders'],1)
        self.assertEqual(result['active_plan']['totals']['paid_usd'],'50')
        next_day=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-07','next-plan')
        self.assertEqual((next_day['review_day']['groups'][0]['plan_id'],next_day['review_day']['groups'][0]['label']),('next-plan','A'))

    def test_same_price_abc_boundary_includes_order_at_confirmation_and_keeps_prior_orders(self):
        self.rows.append(dict(self.rows[0],order_key='earlier',customer_key='earlier',occurred_at='2026-11-06T15:58:59+00:00'))
        self.continuation('C','2026-11-06T15:59:00+00:00','p','C',['base:console'])
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','p')
        labels={g['label']:g['orders'] for g in result['review_day']['groups']}
        self.assertEqual(labels,{'B':1,'C':1})
        self.assertEqual(result['active_plan']['totals']['orders'],3)

    def test_continuation_is_resource_scoped_and_future_or_unconfirmed_operations_do_not_override(self):
        self.continuation('pc','2026-11-06T15:00:00+00:00','pc-plan','A',['base:pc'])
        self.continuation('future','2026-11-07T01:00:00+00:00','future-plan','C',['base:console','base:pc'])
        self.ops.append(dict(operation_id='unconfirmed',plan_id='not-active',status='PREPARED',created_at='2026-11-06T15:30:00+00:00',bundle=dict(smart_assignment=dict(label='C'))))
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','p')
        self.assertEqual((result['review_day']['groups'][0]['plan_id'],result['review_day']['groups'][0]['label']),('p','B'))
        self.assertEqual(result['active_plan']['totals']['orders'],1)
        self.assertEqual(daily.profit_summary(self.online,self.windows,self.ops,'2026-11-07','pc-plan')['active_plan']['totals']['orders'],1)

    def test_real_ledger_no_change_reuses_window_but_summary_uses_new_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            for ident,plan,label,hour in [('open','old','B',14),('continued','new','C',15)]:
                op=dict(operation_id=ident,plan_id=plan,resources=['base:console'],status='AUTHORIZED',steps=[],bundle=dict(
                    assignment_id=ident,action=dict(base_prices=dict(console='7.50')),catalog=dict(PS={'tiers':[]},XBOX={'tiers':[]}),
                    tested_platforms=['PS','XBOX'],smart_assignment=dict(label=label)))
                db.put('operations',ident,op)
                with patch('fc_pricing_v3.ledger.clock',return_value=datetime(2026,11,6,hour,tzinfo=timezone.utc)):
                    db.finish(ident,{},no_change=ident=='continued')
            windows=db.all('actual_price_windows');self.assertEqual(len(windows),1)
            online=dict(self.online,actual_outcomes=[dict(self.rows[0],price_window_id='open')])
            result=daily.profit_summary(online,windows,db.all('operations'),'2026-11-06','new')
            self.assertEqual((result['active_plan']['totals']['orders'],result['review_day']['groups'][0]['label']),(1,'C'))

    def test_regional_continuation_does_not_relabel_global_or_other_region_orders(self):
        self.windows[0]['resources']+=['region:21:PC','region:21:PS']
        self.rows[0]['group']='21:PS'
        self.rows.append(dict(self.rows[0],order_key='regional-pc',group='21:PC'))
        self.continuation('regional','2026-11-06T15:00:00+00:00','regional-plan','C',['region:21:PC'])
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','regional-plan')
        self.assertEqual(result['active_plan']['totals']['orders'],1)
        self.assertEqual([(g['plan_id'],g['group'],g['label']) for g in result['review_day']['groups']],[('p','console','B'),('regional-plan','pc','C')])

    def test_missing_continuation_operation_keeps_cost_but_does_not_fall_back_to_old_plan(self):
        self.windows[0]['continuations']=[dict(operation_id='missing-operation',at='2026-11-06T15:00:00+00:00',resources=['base:console','base:pc'])]
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','p')
        self.assertEqual(result['review_day']['totals']['procurement_gross_usd'],'25')
        self.assertIsNone(result['review_day']['groups'][0]['plan_id'])
        self.assertEqual(result['active_plan']['totals']['status'],'no_sample')

    def test_review_day_and_plan_total_are_separate_and_no_private_ids_leave(self):
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','p')
        day=result['review_day']['totals'];total=result['active_plan']['totals']
        self.assertEqual((day['orders'],day['paid_usd'],day['procurement_cost_usd'],day['procurement_gross_usd']),(1,'100','75','25'))
        self.assertEqual((total['orders'],total['cost_known_orders'],total['unknown_cost_orders'],total['unknown_cost_paid_usd']),(2,1,1,'50'))
        self.assertEqual(total['covered_paid_usd'],'100')
        self.assertEqual(result['review_day']['groups'][0]['label'],'B')
        self.assertEqual(result['review_day']['groups'][0]['plan_id'],'p')
        self.assertEqual(result['review_day']['groups'][0]['group'],'console')
        self.assertNotIn('private-',json.dumps(result))
        self.assertEqual(self.rows[0]['actual_contribution_usd'],'25')

    def test_no_cost_is_unknown_but_real_zero_gross_is_known(self):
        result=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-07',None)
        t=result['review_day']['totals']
        self.assertIsNone(t['procurement_gross_usd']);self.assertIsNone(t['procurement_cost_usd'])
        self.assertIsNone(t['new_customers']);self.assertEqual(t['status'],'partial')
        self.assertIsNone(result['active_plan'])
        self.rows[1].update(actual_contribution_usd='0',new_customer=False)
        t=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-07','p')['review_day']['totals']
        self.assertEqual((t['procurement_gross_usd'],t['procurement_cost_usd'],t['new_customers']),('0','50',0))
        self.assertEqual(t['status'],'complete')
        empty=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-08','p')['review_day']['totals']
        self.assertEqual(empty['status'],'no_sample');self.assertIsNone(empty['procurement_gross_usd'])

    def test_daily_run_freezes_and_passes_summary_without_replaying_completed_review(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db');db.put('metadata','x',{})
            active=Mock(return_value=dict(plan_id='p'));db.active_plan=active
            for w in self.windows:db.put('actual_price_windows',w['operation_id'],w)
            for op in self.ops:db.put('operations',op['operation_id'],op)
            collected=dict(actual={'status':'complete'},online=self.online)
            proc=Mock(returncode=0,stdout=json.dumps(collected))
            with patch.object(runtime,'ledger',return_value=db),patch.object(daily.subprocess,'run',return_value=proc) as read,patch.object(scheduler,'export_shadow_snapshot'),patch.object(history,'ensure_shadow',return_value=dict(status='completed',result={})),patch.object(bridge,'review',return_value=dict(phase='completed')) as review:
                result=daily.run(dict(local_date='2026-11-06'))
                report=review.call_args.args[1]['daily_report']
                self.assertEqual(report['actual_profit_summary'],result['actual_profit_summary'])
                self.assertEqual(report['actual_profit_summary']['review_day']['totals']['procurement_gross_usd'],'25')
                self.assertEqual(db.get('metadata','latest_daily_review')['actual_profit_summary'],report['actual_profit_summary'])
                daily.run(dict(local_date='2026-11-06'))
                self.assertEqual(review.call_count,1);self.assertEqual(read.call_count,1)

    def test_prompt_carries_summary_preserves_precision_and_does_not_mutate_source(self):
        summary=daily.profit_summary(self.online,self.windows,self.ops,'2026-11-06','p')
        quote=dict(daily_report=dict(actual_profit_summary=summary,actual=dict(hourly=[dict(hour=0,orders=1,net_paid_usd='100')]),decision_basis=dict(demand_model=dict(status='fit',groups={'pc':{'elasticity':'1.12345678','metrics':['detail']}}))))
        before=json.dumps(quote,sort_keys=True)
        text=bridge.daily_review_text(quote);payload=json.loads(text.split('实际及影子摘要：',1)[1])
        self.assertEqual(payload['actual_profit_summary']['review_day']['totals']['procurement_gross_usd'],'25')
        day=payload['actual_profit_summary']['review_day']
        self.assertEqual(dict(zip(day['group_columns'],day['groups'][0]))['cost_known_orders'],1)
        self.assertEqual(dict(zip(payload['actual']['hourly_columns'],payload['actual']['hourly'][0])),quote['daily_report']['actual']['hourly'][0])
        self.assertIn('部分覆盖不能说成没有成本',text)
        self.assertEqual(json.dumps(quote,sort_keys=True),before)


if __name__=='__main__':unittest.main()

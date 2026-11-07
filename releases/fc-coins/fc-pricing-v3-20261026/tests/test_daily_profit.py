import json
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
        self.windows=[dict(operation_id='w',plan_id='p',mode='production')]
        self.ops=[dict(operation_id='w',bundle=dict(smart_assignment=dict(label='B')))]
        self.rows=[dict(order_key='private-order',customer_key='private-customer',price_window_id='w',
            occurred_at='2026-11-06T15:59:00+00:00',group='console',actual_net_usd='100',
            actual_contribution_usd='25',new_customer=True),
            dict(order_key='missing',price_window_id='w',occurred_at='2026-11-06T16:01:00+00:00',
            group='pc',actual_net_usd='50',actual_contribution_usd=None,new_customer=None)]
        self.online=dict(actual_outcomes=self.rows,learning_coverage=dict(observed_at='2026-11-07T02:20:00+08:00',query_complete=True))

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

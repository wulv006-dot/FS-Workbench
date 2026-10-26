import json
import sys
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3 import runtime,region_source
from fc_pricing_v3.region_adapter import operation_step

class BudgetAndTransport(unittest.TestCase):
    def test_confirmed_partial_cannot_be_cancelled_as_zero_write(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            op=dict(operation_id='partial',plan_id='plan',generation='gen',status='PARTIALLY_APPLIED',
                resources=['base:console','region:21:PS'],
                steps=[dict(state='CONFIRMED',kind='base'),dict(state='CANCELLED_NOT_SENT',kind='region')],
                bundle=dict(assignment_id='assignment',mutable_resources=['base:console','region:21:PS'],
                    before_action=dict(base_prices=dict(console='10',pc='10'),region_coefficients={'21:PS':'1'})))
            db.put('operations','partial',op)
            with self.assertRaisesRegex(ValueError,'pricing_cancellation_dispatch_not_proven_zero'):
                db.cancel_not_sent('partial','expired')
            actual=dict(base_prices=dict(console='11',pc='10'),region_coefficients={'21:PS':'1'})
            result=db.finish_known_partial('partial',dict(status='PUBLIC_CONFIRMED'),actual,'expired')
            self.assertEqual(result['status'],'KNOWN_PARTIAL_EXIT_PENDING')
            self.assertEqual(db.get('actual_price_windows','partial')['resources'],['base:console'])

    def test_pending_cost_keeps_reservation_without_double_counting_actual(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db')
            now=datetime.now(timezone.utc)
            plan=dict(plan_id='p',daily_budget='100',total_budget=None)
            with db.transaction() as conn:
                db.reserve('op',{'console':dict(concession='30',negative_contribution='10')},plan,now,conn)
                db.put('settlements','o1',dict(operation_id='op',group='console',concession='20',negative_contribution=None,occurred_at=now.isoformat()),conn)
                usage=db.budget_usage(plan,now,conn)
                self.assertEqual(usage['groups']['console'],dict(concession='30',negative_contribution='10'))
                self.assertEqual(usage['cost_pending_operations'],1)
                db.reserve('op2',{'console':dict(concession='60',negative_contribution='0')},plan,now,conn)

    def test_same_assignment_refresh_reserves_one_forecast_but_counts_actual_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'db');now=datetime.now(timezone.utc)
            plan=dict(plan_id='p',daily_budget='100',total_budget=None)
            with db.transaction() as conn:
                for op in ('first','refresh'):
                    db.reserve(op,{'console':dict(concession='60',negative_contribution='0')},plan,now,conn,assignment_id='block-a')
                    db.put('operations',op,dict(plan_id='p',bundle=dict(assignment_id='block-a')),conn)
                for op,key in (('first','order-a'),('refresh','order-b')):
                    db.put('settlements',key,dict(operation_id=op,group='console',concession='20',negative_contribution='0',occurred_at=now.isoformat()),conn)
                self.assertEqual(db.budget_usage(plan,now,conn)['groups']['console']['concession'],'60')
                db.reserve('next',{'console':dict(concession='30',negative_contribution='0')},plan,now,conn,assignment_id='block-b')

    def test_region_missing_token_can_continue_same_unissued_transport_once(self):
        scope=dict(site_id=266,lang_region_id=21,goods_id=0,gid=1327,top_cid=1,cid=0,sid=7645,aid=21587)
        step=dict(step_id='s',kind='region',state='DISPATCHED',value='.9900',scope=scope,expected_rule_set_sha256=fingerprint([]))
        op=dict(operation_id='op',plan_id='p',generation='g',steps=[step],bundle=dict(mutable_resources=['region:21:PS'],valid_until=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()))
        db=Mock()
        db.transaction.side_effect=lambda:nullcontext(None)
        db.get.side_effect=lambda table,key,*args:op if table=='operations' else dict(state='ACTIVE')
        session=Mock()
        session.post_admin.return_value=(200,dict(code=1))
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=Mock(side_effect=[(None,'missing'),('token','ok')]))
        channel=SimpleNamespace(pages=Mock(),COLLECTOR='/existing/collector')
        row=dict(scope,id=8,factor='.9900',status=1)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir();(root/'config/v3-control.json').write_text(json.dumps(dict(enabled=True,generation='g')))
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.dict(sys.modules,{'channel_source':channel,'p2pah_auth':auth}),patch.object(region_source,'read_rules',side_effect=[[],[row],[row]]):
                self.assertEqual(operation_step('op','s',write=True)['status'],'NOT_SENT')
                self.assertNotIn('transport_claimed_at',step)
                self.assertEqual(operation_step('op','s',write=True)['status'],'CONFIRMED')
                self.assertIn('transport_claimed_at',step)
                self.assertEqual(operation_step('op','s',write=True)['status'],'UNKNOWN')
        self.assertEqual(session.post_admin.call_count,1)

if __name__=='__main__':unittest.main()

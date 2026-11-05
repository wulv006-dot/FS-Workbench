from pathlib import Path
import tempfile
import unittest

from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.business_source import _window_end, _window_instant


class ActualPriceWindowTest(unittest.TestCase):
    def test_no_change_keeps_confirmed_window_and_operation_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'ledger.db')
            action = {'base_prices': {'console': '10.00'}, 'region_coefficients': {}}
            bundle = {'action': action, 'assignment_id': 'a', 'mutable_resources': ['base:console']}
            op = {'operation_id': 'first', 'plan_id': 'p', 'generation': 'g',
                  'bundle': bundle, 'resources': ['base:console']}
            with db.transaction() as conn:
                db.record_price_window(op, conn)
            before = db.get('actual_price_windows', 'first')
            later = dict(op, operation_id='next', bundle=dict(bundle, assignment_id='b'))
            with db.transaction() as conn:
                db.put('operations', 'next', later, conn)
                db.record_price_window(later, conn, no_change=True)
            after = db.get('actual_price_windows', 'first')
            self.assertEqual(after['opened_at'], before['opened_at'])
            self.assertNotIn('closed_at', after)
            self.assertFalse(after['randomization_verified'])
            self.assertEqual(after['continuations'][0]['assignment_id'], 'b')
            self.assertIsNone(db.get('actual_price_windows', 'next'))
            self.assertEqual(db.get('operations', 'next')['bundle']['assignment_id'], 'b')

    def test_changed_pc_catalog_opens_only_pc_window(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'ledger.db')
            catalog={p:{'tiers':[{'base_k':'100','bonus_k':'5','retained_ratio':'1'}]} for p in ('PS','XBOX','PC')}
            from copy import deepcopy
            changed=deepcopy(catalog); changed['PC']['tiers'][0]['bonus_k']='10'
            action={'base_prices':{'console':'10','pc':'9'},'region_coefficients':{}}
            resources=['base:console','base:pc']
            op={'operation_id':'old','resources':resources,'bundle':{'action':action,'assignment_id':'a','mutable_resources':resources,'catalog':catalog}}
            with db.transaction() as conn: db.record_price_window(op,conn)
            new=dict(op,operation_id='new',bundle=dict(op['bundle'],assignment_id='b',catalog=changed))
            with db.transaction() as conn: db.record_price_window(new,conn,no_change=True)
            self.assertEqual(db.get('actual_price_windows','new')['resources'],['base:pc'])
            old=db.get('actual_price_windows','old')
            self.assertIn('base:pc',old['resource_closed_at'])
            self.assertEqual(old['continuations'][0]['resources'],['base:console'])

    def test_new_bonus_binds_order_to_new_window(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        from test_business_source import BusinessSourceTest
        from fc_pricing_v3.business_source import bind_price_windows
        now, order, template=BusinessSourceTest().window_fixture()
        start=datetime(2026,10,26,tzinfo=timezone.utc)
        action={'base_prices':{'pc':'8.68'},'region_coefficients':{}}
        old_catalog={'PC':{'tiers':[{'base_k':'100','bonus_k':'5','retained_ratio':'1'}]}}
        new_catalog={'PC':{'tiers':[{'base_k':'100','bonus_k':'10','retained_ratio':'1'}]}}
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'ledger.db')
            op={'operation_id':'old','resources':['base:pc'],'bundle':{'action':action,'assignment_id':'a','mutable_resources':['base:pc'],'affected_platforms':['PC'],'catalog':old_catalog,'budget_reference':{'base_prices':{'pc':'10'},'region_coefficients':{}}}}
            with patch('fc_pricing_v3.ledger.clock',return_value=start),db.transaction() as conn: db.record_price_window(op,conn)
            new=dict(op,operation_id='new',bundle=dict(op['bundle'],catalog=new_catalog,assignment_id='b'))
            with patch('fc_pricing_v3.ledger.clock',return_value=start+timedelta(hours=2)),db.transaction() as conn: db.record_price_window(new,conn,no_change=True)
            order.update(aid=21589,timestamp=int((start+timedelta(hours=3)).timestamp()),timestamp_format='2026-10-26 11:00:00',content='<span class="item">100 K coins+10K Free x 1 = $8.68</span>')
            result=bind_price_windows([order],[db.get('actual_price_windows','old'),db.get('actual_price_windows','new')],now)
            self.assertEqual(result['budget_settlements'][0]['operation_id'],'new')

    def test_first_no_change_starts_observation_at_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'ledger.db')
            op = {'operation_id': 'first', 'plan_id': 'p', 'generation': 'g',
                  'resources': ['base:pc'], 'bundle': {'assignment_id': 'a',
                  'mutable_resources': ['base:pc'], 'action': {'base_prices': {'pc': '9.00'}}}}
            with db.transaction() as conn:
                db.record_price_window(op, conn, no_change=True)
            window = db.get('actual_price_windows', 'first')
            self.assertTrue(window['no_change'])
            self.assertFalse(window['randomization_verified'])

    def test_partly_closed_window_does_not_extend_closed_resource(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'ledger.db')
            action = {'base_prices': {'console': '10.00', 'pc': '9.00'}}
            window = {'operation_id': 'old', 'action': action, 'resources': ['base:console', 'base:pc'],
                      'resource_closed_at': {'base:console': '2026-11-05T00:00:00+00:00'},
                      'assignment_id': 'a', 'opened_at': '2026-11-04T23:00:00+00:00',
                      'randomization_verified': True}
            op = {'operation_id': 'next', 'plan_id': 'p', 'generation': 'g',
                  'resources': ['base:console', 'base:pc'], 'bundle': {'assignment_id': 'b',
                  'mutable_resources': ['base:console', 'base:pc'], 'action': action}}
            with db.transaction() as conn:
                db.put('actual_price_windows', 'old', window, conn)
                db.record_price_window(op, conn, no_change=True)
            self.assertEqual(db.get('actual_price_windows', 'next')['resources'], ['base:console'])
            self.assertEqual(db.get('actual_price_windows', 'old')['continuations'][0]['resources'], ['base:pc'])

    def test_no_change_continues_two_independently_open_resources(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'ledger.db')
            t = datetime(2026, 11, 5, tzinfo=timezone.utc)
            a = {'base_prices': {'console': '10.00', 'pc': '9.00'}}
            b = {'base_prices': {'console': '10.50', 'pc': '9.00'}}
            def record(key, action, resources, at, no_change=False):
                op = {'operation_id': key, 'plan_id': 'p', 'generation': 'g', 'resources': resources,
                      'bundle': {'assignment_id': key, 'mutable_resources': resources, 'action': action}}
                with patch('fc_pricing_v3.ledger.clock', return_value=at), db.transaction() as conn:
                    db.record_price_window(op, conn, no_change=no_change)
            record('first', a, ['base:console', 'base:pc'], t)
            record('second', b, ['base:console'], t + timedelta(hours=1))
            record('third', b, ['base:console', 'base:pc'], t + timedelta(hours=2), True)
            first, second = db.get('actual_price_windows', 'first'), db.get('actual_price_windows', 'second')
            self.assertIsNone(db.get('actual_price_windows', 'third'))
            self.assertEqual(first['continuations'][0]['resources'], ['base:pc'])
            self.assertEqual(second['continuations'][0]['resources'], ['base:console'])
            self.assertEqual(_window_end(first, 'console', [first, second], t + timedelta(hours=3)), t + timedelta(hours=1))
            self.assertEqual(_window_end(first, 'pc', [first, second], t + timedelta(hours=3)), t + timedelta(hours=3))


if __name__ == '__main__':
    unittest.main()

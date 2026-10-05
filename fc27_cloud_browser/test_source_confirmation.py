from copy import deepcopy
import json
import unittest
from unittest.mock import patch
import coin_all_sync_job as sync
from test_coin_all_sync import fixtures, Manager

class Clock:
    def __init__(self): self.now=0; self.on_sleep=lambda:None
    def clock(self):return self.now
    def sleep(self,seconds):self.now+=seconds;self.on_sleep()

class ConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.rows,self.audit,self.policy=fixtures();self.manager=Manager(self.rows)
        self.audit['before']={'rows':[{'platform':p,'b2c':'0.124'} for p in sync.PRODUCTS]}
        self.record={};self.clock=Clock();self.events=[]
    def wait(self,limit=20):
        return sync.wait_sources(self.manager,self.audit,self.policy,self.record,
            lambda r:self.events.append(deepcopy(r)),lambda:self.policy,
            max_seconds=limit,interval_seconds=5,clock=self.clock.clock,sleep=self.clock.sleep)
    def test_old_read_then_two_stable_exact_rounds_and_no_writes(self):
        self.rows[163329311]['unit_price']=.124
        self.clock.on_sleep=lambda:self.rows[163329311].update(unit_price=.1252)
        self.wait()
        self.assertEqual(self.clock.now,10);self.assertEqual(self.manager.posts,[])
        ev=self.record['source_confirmation'];self.assertEqual(ev['status'],'confirmed')
        self.assertEqual([r['all_rates_match'] for r in ev['rounds']],[False,True,True])
        first=ev['rounds'][0]['observations'][0]
        self.assertEqual(first['observed_unit_price'],'0.124')
        self.assertEqual(first['product_id'],163329311)
        self.assertEqual(first['http_status'],200);self.assertEqual(first['response_code'],1)
        self.assertIn('received_at',first)
    def test_timeout_with_old_value_is_bounded_and_read_only(self):
        self.rows[163329311]['unit_price']=.124
        with self.assertRaisesRegex(ValueError,'confirmation_timeout'):self.wait(12)
        self.assertEqual(self.clock.now,12);self.assertEqual(self.manager.posts,[])
        self.assertEqual(len(self.record['source_confirmation']['rounds']),3)
        self.assertEqual(self.record['source_confirmation']['status'],'stopped')
    def test_third_value_stops_immediately_instead_of_waiting(self):
        self.rows[163329311]['unit_price']=.2
        with self.assertRaisesRegex(ValueError,'source_or_before_changed'):self.wait()
        self.assertEqual(self.clock.now,0);self.assertEqual(self.manager.posts,[])
    def test_protected_change_stops_without_write(self):
        self.clock.on_sleep=lambda:self.rows[163329311].update(is_rec=0)
        with self.assertRaisesRegex(ValueError,'protected_changed'):self.wait()
        self.assertEqual(self.manager.posts,[])
    def test_policy_change_stops_without_write(self):
        self.clock.on_sleep=lambda:self.policy.update(revision=19)
        with self.assertRaisesRegex(ValueError,'preflight_changed'):self.wait()
        self.assertEqual(self.manager.posts,[])
    def test_transport_failure_records_no_auth_retry_or_price_retry(self):
        original=self.manager.request
        def fail(path,**kw):
            if '163329311' in path:raise TimeoutError('fixture')
            return original(path,**kw)
        self.manager.request=fail
        with self.assertRaises(TimeoutError):self.wait()
        item=self.record['source_confirmation']['rounds'][0]['observations'][0]
        self.assertEqual(item['transport_error'],'TimeoutError');self.assertIn('started_at',item)
        self.assertEqual(self.manager.posts,[])
    def test_deadline_after_inflight_response_stops_before_next_get(self):
        original=self.manager.request
        def slow(path,**kw):
            result=original(path,**kw)
            if '163329311' in path:self.clock.now+=16
            return result
        self.manager.request=slow
        with self.assertRaisesRegex(ValueError,'confirmation_timeout'):self.wait(12)
        self.assertEqual(len(self.record['source_confirmation']['rounds'][0]['observations']),1)
        self.assertEqual(self.manager.posts,[])
    def test_explicit_empty_ledger_recovery_writes_only_pending_all(self):
        self.audit.update(status='PARTIAL',stage='stopped',error='coin_mmoexp_confirmed_rate_mismatch')
        self.record.update(execution_id=self.audit['execution_id'],status='needs_reconcile',steps=[])
        pc=self.rows[163329343];pc.update(unit_price=.1252);pc['more']['price']=[1.25,12.52]
        with patch.object(sync.time,'sleep',lambda _:None):
            result=sync.resume_empty_preflight(self.manager,self.audit,self.policy,self.record,
                  lambda a:None,lambda r:None,lambda:self.policy)
        self.assertEqual(self.manager.posts,[163329309,163329275])
        self.assertEqual(result['status'],'confirmed');self.assertFalse(self.audit['recovery_history'][0]['mmoexp_replayed'])
    def test_nonempty_ledger_cannot_use_empty_recovery(self):
        self.audit.update(status='PARTIAL',stage='stopped',error='coin_mmoexp_confirmed_rate_mismatch')
        self.record.update(execution_id=self.audit['execution_id'],status='needs_reconcile',steps=[{'status':'dispatching'}])
        with self.assertRaisesRegex(ValueError,'empty_recovery_scope_changed'):
            sync.resume_empty_preflight(self.manager,self.audit,self.policy,self.record,lambda a:None,lambda r:None,lambda:self.policy)
        self.assertEqual(self.manager.posts,[])

if __name__=='__main__':unittest.main()

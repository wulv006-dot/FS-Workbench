from copy import deepcopy
import json,unittest
import test_gateway
from proxy_gateway import ModelGateway,UnifiedBudget


class CallRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_gateway.GatewayTests('test_large_hermes_context_and_many_rows_preserve_originals')
        self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        f=self.fixture
        policy={'id':'no-pilot-quotas-deepseek-direct-stream-tokens-only-v2','model':'deepseek-flash','price_version':'deepseek-direct-no-cny-invoice-or-fx-v1','input_microcny':None,'output_microcny':None}
        self.budget=UnifiedBudget(f.db,policy,lambda:f.now,allow_unknown_costs=True)
        self.sent=[];self.failures=1;self.cancel_on_reset=False
        self.waits=[]
        def wait(seconds,check):self.waits.append(seconds);check()
        f.gateway=ModelGateway(f.scope,self.budget,f.slot,self.provider,lambda _:100,lambda:0,transport_retries=2,retry_wait=wait)

    def provider(self,request):
        self.sent.append(deepcopy(request))
        if len(self.sent)<=self.failures:
            if self.cancel_on_reset:self.fixture.tasks.cancel(self.fixture.task['id'],'owner')
            error=ValueError('provider_unknown_transport')
            error.response={'status':'unknown_transport','transport_error_type':'ConnectionResetError','provider_response_id':'fixture_reset_'+str(len(self.sent)),'response_headers_received':True,'transport_phase':'reading_stream','response_bytes_received':300,'stream_events_received':1}
            raise error
        return self.fixture.answer(request)

    def rows(self):
        with self.fixture.db() as db:return [dict(r) for r in db.execute('SELECT r.turn,m.state,m.content FROM hermes_reservations r JOIN model_calls m ON r.fingerprint=m.fingerprint ORDER BY r.turn')]

    def test_reset_recovers_current_call_preserves_unknown_and_idempotent_success(self):
        receipt=self.fixture.call()
        self.assertEqual(receipt['status'],'succeeded');self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[0],self.sent[1])
        self.assertEqual(self.waits,[2])
        rows=self.rows();self.assertEqual([r['state'] for r in rows],['unknown','succeeded'])
        self.assertEqual(json.loads(rows[0]['content'])['provider_response_id'],'fixture_reset_1')
        self.assertEqual(self.fixture.call(),receipt);self.assertEqual(len(self.sent),2)
        self.fixture.call(turn=1,body={'messages':[{'role':'user','content':'Next readonly analysis step.'}],'max_tokens':50})
        self.assertEqual([r['turn'] for r in self.rows()],[0,1,3])
        self.assertEqual([r['state'] for r in self.rows()],['unknown','succeeded','succeeded'])

    def test_two_resets_then_success_has_three_distinct_real_call_records(self):
        self.failures=2;self.fixture.call()
        self.assertEqual(len(self.sent),3)
        self.assertEqual(self.waits,[2,4])
        self.assertEqual([r['state'] for r in self.rows()],['unknown','unknown','succeeded'])

    def test_exhaustion_and_sdk_repeat_cannot_start_a_fourth_physical_request(self):
        self.failures=99
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'provider_transport_recovery_exhausted'):self.fixture.call()
        self.assertEqual(len(self.sent),3)
        self.assertEqual([r['state'] for r in self.rows()],['unknown']*3)

    def test_cancel_between_attempts_prevents_any_new_request(self):
        self.cancel_on_reset=True
        with self.assertRaises(PermissionError):self.fixture.call()
        self.assertEqual(len(self.sent),1);self.assertEqual([r['state'] for r in self.rows()],['unknown'])

    def test_http_rejection_and_unverified_payload_are_not_transport_retries(self):
        def blocked(request):
            self.sent.append(request);error=ValueError('provider_http_rejected_400');error.response={'status':'http_rejected','http_status':400};raise error
        self.fixture.gateway.provider=blocked
        with self.assertRaisesRegex(ValueError,'provider_outcome_unknown'):self.fixture.call()
        self.assertEqual(len(self.sent),1)
        with self.assertRaisesRegex(ValueError,'unknown_previous_attempt'):self.fixture.call()
        self.assertEqual(len(self.sent),1)

    def test_unknown_current_task_other_logical_call_is_not_a_duplicate(self):
        self.failures=3
        with self.assertRaisesRegex(ValueError,'provider_transport_recovery_exhausted'):self.fixture.call()
        self.fixture.call(turn=1,body={'messages':[{'role':'user','content':'A separate next readonly step.'}],'max_tokens':50})
        self.assertEqual(len(self.sent),4)
        self.assertEqual([r['turn'] for r in self.rows()],[0,1,2,3])


if __name__=='__main__':unittest.main()

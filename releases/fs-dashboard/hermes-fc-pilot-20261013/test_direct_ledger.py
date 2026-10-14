import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_gateway as fixture
from proxy_gateway import UnifiedBudget, schemas
from controller import HermesService
from pilot import encoded

POLICY={'id':'no-pilot-quotas-deepseek-direct-stream-tokens-only-v2','model':'deepseek-flash',
        'price_version':'deepseek-direct-no-cny-invoice-or-fx-v1','input_microcny':None,'output_microcny':None}


class DirectLedgerTests(unittest.TestCase):
    setUp=fixture.GatewayTests.setUp
    tearDown=fixture.GatewayTests.tearDown
    db=fixture.GatewayTests.db
    slot=fixture.GatewayTests.slot
    answer=fixture.GatewayTests.answer
    call=fixture.GatewayTests.call

    def use_direct(self):
        self.budget=UnifiedBudget(self.db,POLICY,lambda:self.now,allow_unknown_costs=True)
        self.gateway.budget=self.budget

    def test_known_tokens_unknown_amount_and_exact_once_replay(self):
        self.use_direct()
        first=self.call();again=self.call()
        self.assertEqual(first,again)
        self.assertEqual(self.calls,1)
        self.assertEqual(first['usage']['total_tokens'],60)
        self.assertIsNone(first['cost_microcny'])
        self.assertEqual(first['cost_basis'],'amount_unknown_no_cny_invoice_or_fx')
        with self.db() as db:
            self.assertEqual(db.execute('SELECT microcny FROM hermes_reservations').fetchone()[0],-1)
        result=HermesService.usage(SimpleNamespace(daily=SimpleNamespace(db=self.db)),self.task['id'],'owner')
        self.assertEqual(result['total_tokens'],60)
        self.assertIsNone(result['estimated_microcny'])
        self.call(turn=1)
        self.assertEqual(self.calls,2)

    def test_missing_provider_usage_stays_unknown_and_does_not_replay_same_turn(self):
        self.use_direct();self.provider=lambda req:{'id':'fake_bad','choices':[]}
        with self.assertRaises(ValueError):self.call()
        with self.assertRaisesRegex(ValueError,'unknown_previous_attempt'):self.call()
        with self.db() as db:self.assertEqual(db.execute('SELECT state FROM model_calls').fetchone()[0],'unknown')
        result=HermesService.usage(SimpleNamespace(daily=SimpleNamespace(db=self.db)),self.task['id'],'owner')
        self.assertEqual(result['unknown_calls'],1)
        self.assertIsNone(result['estimated_microcny'])

    def test_null_prices_do_not_expand_to_other_model_policy(self):
        for changed in ({'model':'other-model'},{'id':'generic-unknown-fee'},{'price_version':'unverified'}):
            with self.assertRaises(ValueError):UnifiedBudget(self.db,dict(POLICY,**changed),lambda:self.now)

    def test_real_gateway_translates_direct_body_without_old_bailian_credential_loader(self):
        from direct_provider import request_model
        self.use_direct()
        def response(path,encoded):
            body=json.loads(encoded)
            self.assertEqual(body['thinking'],{'type':'enabled'})
            self.assertEqual(body['max_tokens'],393216)
            self.assertNotIn('enable_thinking',body)
            raw=self.answer(body);raw['model']='deepseek-flash';return raw
        self.gateway.provider=lambda req:request_model(req,schemas())
        with patch('direct_provider._open',side_effect=response):
            raw=self.call(body={'messages':[{'role':'user','content':'合成聚合'}],'max_tokens':393216,'reasoning_effort':'max'})
        self.assertEqual(raw['model'],'deepseek-flash')
        self.assertIsNone(raw['cost_microcny'])

    def test_final_native_wire_overhead_is_rejected_before_reservation_or_network(self):
        from direct_provider import prepare_request, WIRE_BYTES
        from proxy_gateway import request_body
        self.use_direct()
        self.gateway.preflight=lambda req:prepare_request(req,schemas())
        body={'messages':[{'role':'user','content':''}],'max_tokens':393216,'reasoning_effort':'max'}
        empty=request_body(body,'deepseek-flash')
        size=WIRE_BYTES-len(encoded(empty).encode())
        body['messages'][0]['content']='x'*size
        self.assertEqual(len(encoded(request_body(body,'deepseek-flash')).encode()),WIRE_BYTES)
        with self.assertRaisesRegex(ValueError,'provider_payload_too_large'):self.call(body=body)
        self.assertEqual(self.calls,0)
        with self.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM model_calls').fetchone()[0],0)
        # Pin the actual final native framing, including streaming usage options.
        overhead=len(prepare_request(empty,schemas()))-len(encoded(empty).encode())
        self.assertGreater(overhead,0)
        body['messages'][0]['content']='x'*(size-overhead)
        self.assertEqual(len(prepare_request(request_body(body,'deepseek-flash'),schemas())),WIRE_BYTES)
        self.call(body=body)
        self.assertEqual(self.calls,1)

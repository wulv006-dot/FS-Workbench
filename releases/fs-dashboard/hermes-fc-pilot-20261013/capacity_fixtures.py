"""Real local boundaries and vendor units, with isolated/fake source/provider only."""
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from urllib.error import HTTPError

import test_gateway as fixture
from proxy_gateway import (request_body,validate_tool_call,MAX_PROVIDER_CONTEXT_TOKENS,
    MAX_PROVIDER_WIRE_BYTES,MAX_HERMES_OUTPUT_TOKENS,schemas)
from transport import Grants,Proxy,start_loopback
from runs_contract import WIRE_TOOLS
from admin_order_capabilities_20261014.provider import response_budget


class MaximumCapacityTests(unittest.TestCase):
    setUp=fixture.GatewayTests.setUp
    tearDown=fixture.GatewayTests.tearDown
    db=fixture.GatewayTests.db
    slot=fixture.GatewayTests.slot
    answer=fixture.GatewayTests.answer

    def test_exact_deepseek_direct_units_and_three_megabyte_request(self):
        self.assertEqual(MAX_PROVIDER_CONTEXT_TOKENS,1048576)
        self.assertEqual(MAX_HERMES_OUTPUT_TOKENS,393216)
        request=request_body({'messages':[{'role':'user','content':'汉'*1000000}],
            'max_tokens':393216,'reasoning_effort':'max'},self.policy['model'])
        self.assertEqual(request['max_tokens'],393216)
        self.assertEqual(len(request['messages'][0]['content'].encode()),3000000)
        self.assertLess(len(json.dumps(request,ensure_ascii=False).encode()),MAX_PROVIDER_WIRE_BYTES)

    def test_real_usage_is_not_limited_by_byte_reservation_guess(self):
        self.gateway.input_bound=lambda _:20
        def provider(request):
            raw=self.answer(request)
            raw['usage']={'prompt_tokens':100000,'completion_tokens':393216,'total_tokens':493216,
                          'completion_tokens_details':{'reasoning_tokens':393000}}
            raw['choices'][0]['message']['reasoning_content']='Synthetic only.'*100000
            return raw
        self.provider=provider
        result=self.gateway.call('owner',self.task['id'],'lease',0,
            {'messages':[{'role':'user','content':'Synthetic prompt'}],'max_tokens':393216,'reasoning_effort':'max'})
        self.assertEqual(result['usage']['prompt_tokens'],100000)
        self.assertEqual(result['reasoning_tokens'],393000)
        self.assertEqual(result['cost_microcny'],100000*self.policy['input_microcny']+393216*self.policy['output_microcny'])

    def test_full_200_operand_argument_json_is_preserved(self):
        args={'operation':'sum','values':['1']*200,'evidence_ids':['ev_fixture'],
            'value_paths':[{'evidence_id':'ev_fixture','path':'/data/synthetic_value'}]*200,
            'assumptions':['']*200}
        wire=json.dumps(args)
        self.assertGreater(len(wire),4096)
        validate_tool_call({'id':'calc_fixture','type':'function','function':{
            'name':'mcp__fcro__fc_calculate','arguments':wire}})
        with self.assertRaisesRegex(ValueError,'tool_arguments_json_invalid'):
            validate_tool_call({'id':'calc_fixture','type':'function','function':{
                'name':'mcp__fcro__fc_calculate','arguments':wire[:-1]}})

    def test_projected_rows_are_not_discarded_to_reduce_context(self):
        value={'status':'available','rows':[{'value':'synthetic projected description '*8,'i':i} for i in range(100)],'coverage':{'complete':True}}
        self.assertGreater(len(json.dumps(value).encode()),12000)
        result=response_budget(value)
        self.assertEqual(result,value)
        self.assertEqual(len(result['rows']),100)

    def test_native_summary_stream_probe_does_not_reserve_or_bill(self):
        grants=Grants();token=grants.mint('owner',self.task['id'],'lease',reasoning_effort='max')
        proxy=Proxy(grants,lambda _:self.gateway)
        body={'model':self.policy['model'],'messages':[{'role':'user','content':'Synthetic compression prompt'}],
              'stream':True,'stream_options':{'include_usage':True}}
        with self.assertRaisesRegex(ValueError,'stream_not_supported'):
            proxy.dispatch('POST','/v1/chat/completions',token,body)
        with self.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM model_calls').fetchone()[0],0)
        body.pop('stream_options');body['stream']=False
        seen=[]
        def provider(request):seen.append(request);return self.answer(request)
        self.provider=provider
        first=proxy.dispatch('POST','/v1/chat/completions',token,body)
        self.assertEqual(proxy.dispatch('POST','/v1/chat/completions',token,body)['id'],first['id'])
        self.assertEqual(self.calls,1)
        self.assertEqual(seen[0]['tools'],[])
        self.assertEqual(seen[0]['max_tokens'],393216)
        self.assertEqual(seen[0]['reasoning_effort'],'max')
        body.update(tools=schemas(),max_tokens=393216,reasoning_effort='none')
        with self.assertRaisesRegex(ValueError,'reasoning_policy'):
            proxy.dispatch('POST','/v1/chat/completions',token,body)
        self.assertEqual(self.calls,1)

    def test_large_tools_and_final_rpc_are_lossless(self):
        import hermes_worker
        import controller
        from test_controller import ControllerTests
        data={'status':'available','projected':'synthetic '*16000}
        raw=json.dumps(data).encode()
        self.assertGreater(len(raw),128000)
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return raw[:n]
        item={'token':'fixture-not-used','session_id':'fixture'}
        with patch.object(hermes_worker,'admission',return_value=item),patch.object(hermes_worker,'build_opener') as opener:
            opener.return_value.open.return_value=Response()
            self.assertEqual(json.loads(hermes_worker.call_tool(WIRE_TOOLS[0],{},session_id='fixture')),data)
        test=ControllerTests();test.setUp()
        try:
            (test.run_root/'api-key').write_text('fixture-not-used')
            with patch.object(controller,'build_opener') as opener:
                opener.return_value.open.return_value=Response()
                self.assertEqual(test.service.remote('GET','/v1/runs/run_'+'a'*32),(200,data))
        finally:test.doCleanups()


if __name__=='__main__':unittest.main()

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'releases/fs-dashboard/hermes-conversation-20261018/tests'))
import test_native_reports  # Existing production dependency paths.
import openai_provider as provider


class SolTests(unittest.TestCase):
    def setUp(self):
        self.tools=[dict(type='function',function=dict(name='echo',description='Echo',parameters=dict(type='object',properties={}))) ]
        self.request=dict(model=provider.MODEL,messages=[dict(role='user',content='hello')],max_tokens=1000,
                          tools=self.tools,tool_choice='auto',stream=False,enable_thinking=True,reasoning_effort='high')

    def test_tool_result_and_encrypted_reasoning_round_trip(self):
        reasoning=dict(type='reasoning',id='rs_test',summary=[],encrypted_content='opaque')
        output=dict(id='resp_test',model=provider.MODEL,status='completed',reasoning={'effort':'high'},
                    usage=dict(input_tokens=10,output_tokens=20,total_tokens=30),
                    output=[reasoning,dict(type='function_call',call_id='call_test',name='echo',arguments='{}')])
        with patch.object(provider,'_open',return_value=output):
            response=provider.request_model(self.request,self.tools,native_chat=True)
        self.assertEqual(response['usage']['total_tokens'],30)
        self.request['messages'] += [response['choices'][0]['message'],dict(role='tool',tool_call_id='call_test',content='ok')]
        body=json.loads(provider.prepare_request(self.request,self.tools,native_chat=True))
        self.assertIn(reasoning,body['input'])
        self.assertEqual(body['input'][-1],dict(type='function_call_output',call_id='call_test',output='ok'))
        self.assertFalse(body['store'])
        self.assertEqual(body['reasoning']['effort'],'high')

    def test_reject_wrong_model_tools_and_limits_before_network(self):
        for update in (dict(model='deepseek-flash'),dict(tools=[{}]),dict(max_tokens=128001),dict(reasoning_effort='ultra')):
            with self.subTest(update=update), self.assertRaises(ValueError):
                provider.prepare_request(dict(self.request,**update),self.tools,native_chat=True)

    def test_unknown_is_returned_without_retry_or_fallback(self):
        with patch.object(provider,'_open',return_value={'status':'unknown_transport'}) as send:
            self.assertEqual(provider.request_model(self.request,self.tools,native_chat=True),{'status':'unknown_transport'})
        self.assertEqual(send.call_count,1)

    def test_structured_output_schema_and_forced_tool_preserved(self):
        self.request['response_format']={'type':'json_object'}
        self.request['tool_choice']={'type':'function','function':{'name':'echo'}}
        body=json.loads(provider.prepare_request(self.request,self.tools,native_chat=True))
        self.assertEqual(body['text']['format'],{'type':'json_object'})
        self.assertEqual(body['tool_choice'],{'type':'function','name':'echo'})


if __name__=='__main__':unittest.main()

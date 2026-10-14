import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
import urllib.error

import direct_provider as provider

TOOLS = [{'type': 'function', 'function': {'name': 'mcp__fcro__get_data_catalog',
          'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}]


def request(**overrides):
    value = {'model': provider.MODEL, 'messages': [{'role': 'user', 'content': '调查FC周销售变动'}],
             'max_tokens': provider.OUTPUT_TOKENS, 'reasoning_effort': 'max',
             'tools': TOOLS, 'tool_choice': 'auto', 'stream': False, 'enable_thinking': True}
    value.update(overrides)
    return value


class ProviderContractTests(unittest.TestCase):
    def test_native_high_and_max_use_real_deepseek_fields_and_maximum(self):
        for effort in ('high', 'max'):
            with self.subTest(effort=effort), patch.object(provider, '_open', return_value={'model': provider.MODEL, 'id': 'synthetic'}) as call:
                self.assertEqual(provider.request_model(request(reasoning_effort=effort), TOOLS)['id'], 'synthetic')
                path, encoded = call.call_args.args
                body = json.loads(encoded)
                self.assertEqual(path, '/chat/completions')
                self.assertEqual(body['thinking'], {'type': 'enabled'})
                self.assertEqual(body['max_tokens'], 393216)
                self.assertEqual(body['reasoning_effort'], effort)
                self.assertNotIn('enable_thinking', body)
                self.assertEqual(body['tools'], TOOLS)
                self.assertIs(body['stream'], True)
                self.assertEqual(body['stream_options'], {'include_usage':True})
                self.assertIn('调查FC'.encode(), encoded)

    def test_native_summary_does_not_send_empty_tools_or_tool_choice(self):
        with patch.object(provider, '_open', return_value={'model': provider.MODEL}) as call:
            provider.request_model(request(tools=[]), TOOLS)
            body = json.loads(call.call_args.args[1])
            self.assertNotIn('tools', body)
            self.assertNotIn('tool_choice', body)
            self.assertEqual(body['max_tokens'], provider.OUTPUT_TOKENS)

    def test_tool_chain_and_reasoning_history_are_not_silently_rewritten(self):
        messages = [{'role': 'user', 'content': '查证'},
                    {'role': 'assistant', 'content': None, 'reasoning_content': 'SYNTHETIC_PRIVATE_THOUGHT',
                     'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'mcp__fcro__get_data_catalog', 'arguments': '{}'}}]},
                    {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'SYNTHETIC_AGGREGATE'}]
        with patch.object(provider, '_open', return_value={'model': provider.MODEL}) as call:
            provider.request_model(request(messages=messages), TOOLS)
            self.assertEqual(json.loads(call.call_args.args[1])['messages'], messages)

    def test_invalid_routing_and_low_effort_are_rejected_before_key_or_network(self):
        variations = [{'endpoint': 'https://other.invalid'}, {'model': 'other'},
                      {'reasoning_effort': 'low'}, {'max_tokens': 8192},
                      {'tools': [{'type': 'function', 'function': {'name': 'shell'}}]},
                      {'enable_thinking': False}, {'stream': True}]
        with patch.object(provider, '_open') as call:
            for change in variations:
                self.assertEqual(provider.request_model(request(**change), TOOLS), {'status': 'configuration_invalid'})
            call.assert_not_called()

    def test_payload_bound_is_ten_megabytes_not_a_token_approximation(self):
        with patch.object(provider, '_open', return_value={'model': provider.MODEL}) as call:
            content = '合成' * 70000
            self.assertEqual(provider.request_model(request(messages=[{'role': 'user', 'content': content}]), TOOLS)['model'], provider.MODEL)
            self.assertGreater(len(call.call_args.args[1]), 96000)
        with patch.object(provider, '_open') as call:
            self.assertEqual(provider.request_model(request(messages=[{'role': 'user', 'content': 'x' * provider.WIRE_BYTES}]), TOOLS), {'status': 'input_too_large'})
            call.assert_not_called()

    def test_discovery_verifies_real_numbers_and_high_max_support(self):
        item = {'id': provider.MODEL, 'context_window': 1048576, 'max_output_tokens': 393216,
                'effort': {'supported_levels': ['low', 'high', 'max']}}
        with patch.object(provider, '_open', return_value={'object': 'list', 'data': [item]}) as call:
            actual = provider.discover_models()
            self.assertEqual(actual['status'], 'verified')
            self.assertEqual(actual['models'][0]['context_window'], 1048576)
            call.assert_called_once_with('/models')
        for change in ({'context_window': 1000000}, {'max_output_tokens': 65536}, {'effort': {'supported_levels': ['high']}}):
            with patch.object(provider, '_open', return_value={'object': 'list', 'data': [dict(item, **change)]}):
                self.assertEqual(provider.discover_models()['status'], 'model_capability_changed')

    def test_absent_credential_does_not_start_a_request_or_include_path(self):
        with patch.dict('os.environ', {}, clear=True), patch('urllib.request.build_opener') as call:
            self.assertEqual(provider.discover_models(), {'status': 'configuration_missing'})
            self.assertEqual(provider.request_model(request(), TOOLS), {'status': 'configuration_missing'})
            call.assert_not_called()

    def test_error_retains_request_id_and_category_without_secret_or_prose(self):
        body = json.dumps({'error': {'code': 'data_inspection_failed', 'message': 'Input data may contain inappropriate content.', 'secret': 'NEVER_KEEP'}}).encode()
        error = urllib.error.HTTPError(provider.BASE_URL, 400, 'private', {'x-request-id': 'synthetic-request-1'}, io.BytesIO(body))
        result = provider._safe_http_error(error)
        self.assertEqual(result['provider_request_id'], 'synthetic-request-1')
        self.assertEqual(result['inspection_direction'], 'input')
        self.assertNotIn('NEVER_KEEP', json.dumps(result))
        self.assertNotIn('message', result)

    def test_unknown_provider_message_is_not_stored_or_guessed(self):
        body = json.dumps({'error': {'code': 'new_code', 'message': 'NEVER_KEEP customer data; output maybe'}}).encode()
        error = urllib.error.HTTPError(provider.BASE_URL, 400, '', {}, io.BytesIO(body))
        result = provider._safe_http_error(error)
        self.assertNotIn('inspection_direction', result)
        self.assertNotIn('NEVER_KEEP', json.dumps(result))

    def test_actual_http_redirect_is_not_followed_or_retried(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/forbidden-credential-forward')
                self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(provider, 'BASE_URL', 'http://127.0.0.1:'+str(server.server_port)), patch.object(provider, '_load_key', return_value='sk-SYNTHETIC-NOT-REAL'):
                result = provider.discover_models()
            self.assertEqual(result['http_status'], 302)
            self.assertEqual(seen, ['/models'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


def sse_chunk(delta=None, finish=None, usage=None, **overrides):
    chunk={'id':'synthetic-stream','model':provider.MODEL,'choices':[{
        'index':0,'delta':delta or {},'finish_reason':finish}]}
    if usage is not None:chunk['usage']=usage
    chunk.update(overrides)
    return chunk


def sse_body(chunks, done=True):
    events=[b': keep-alive\r\n\r\n']
    for chunk in chunks:
        events.append(b'data: '+json.dumps(chunk,ensure_ascii=False).encode('utf-8')+b'\r\n\r\n')
    if done:events.append(b'data: [DONE]\r\n\r\n')
    return b''.join(events)


STREAM_USAGE={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,
              'completion_tokens_details':{'reasoning_tokens':3}}


class StreamingContractTests(unittest.TestCase):
    def test_reset_after_headers_keeps_header_id_and_partial_stream_id(self):
        first=io.BytesIO(sse_body([sse_chunk({'reasoning_content':'NEVER_STORE_PARTIAL_THOUGHT'})],done=False))
        class Response:
            headers={'X-Request-ID':'synthetic-header-uuid'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def readline(self,limit):
                raw=first.readline(limit)
                if raw:return raw
                raise ConnectionResetError('NEVER_STORE_EXCEPTION')
        opener=type('Opener',(),{'open':lambda self,*args,**kwargs:Response()})()
        with patch.object(provider,'_load_key',return_value='sk-SYNTHETIC'),patch('urllib.request.build_opener',return_value=opener) as send:
            result=provider.request_model(request(),TOOLS)
        self.assertEqual(result['status'],'unknown_transport')
        self.assertEqual(result['provider_http_request_id'],'synthetic-header-uuid')
        self.assertEqual(result['provider_response_id'],'synthetic-stream')
        self.assertTrue(result['response_headers_received'])
        self.assertEqual(result['transport_phase'],'reading_stream')
        self.assertGreater(result['response_bytes_received'],0)
        self.assertEqual(result['stream_events_received'],1)
        self.assertRegex(result['local_trace_id'],r'^[a-f0-9]{32}$')
        self.assertIn('+00:00',result['request_started_at'])
        self.assertNotIn('NEVER_STORE',json.dumps(result))
        self.assertEqual(send.call_count,1)

    def test_reset_before_headers_has_only_local_correlation(self):
        opener=type('Opener',(),{'open':lambda *args,**kwargs:(_ for _ in ()).throw(ConnectionResetError('PRIVATE'))})()
        with patch.object(provider,'_load_key',return_value='sk-SYNTHETIC'),patch('urllib.request.build_opener',return_value=opener):
            first=provider.request_model(request(),TOOLS)
            second=provider.request_model(request(),TOOLS)
        self.assertFalse(first['response_headers_received'])
        self.assertEqual(first['transport_phase'],'opening')
        self.assertNotIn('provider_http_request_id',first)
        self.assertNotIn('provider_response_id',first)
        self.assertEqual(first['response_bytes_received'],0)
        self.assertNotEqual(first['local_trace_id'],second['local_trace_id'])

    def test_success_and_http_rejection_preserve_distinct_header_ids(self):
        body=sse_body([sse_chunk({'content':'synthetic'},finish='stop',usage=STREAM_USAGE)])
        class Response(io.BytesIO):
            headers={'x-request-id':'synthetic-header-id'}
        opener=type('Opener',(),{'open':lambda self,*args,**kwargs:Response(body)})()
        with patch.object(provider,'_load_key',return_value='sk-SYNTHETIC'),patch('urllib.request.build_opener',return_value=opener):
            result=provider.request_model(request(),TOOLS)
        self.assertEqual(result['provider_http_request_id'],'synthetic-header-id')
        self.assertEqual(result['id'],'synthetic-stream')
        error=urllib.error.HTTPError(provider.BASE_URL,429,'PRIVATE',{'X-Request-ID':'synthetic-rejected-id'},io.BytesIO(b'{}'))
        with patch.object(provider,'_load_key',return_value='sk-SYNTHETIC'),patch('urllib.request.build_opener') as build:
            build.return_value.open.side_effect=error
            rejected=provider.request_model(request(),TOOLS)
        self.assertEqual(rejected['http_status'],429)
        self.assertEqual(rejected['provider_http_request_id'],'synthetic-rejected-id')
        self.assertTrue(rejected['response_headers_received'])
        self.assertEqual(rejected['transport_phase'],'http_rejected')

    def test_actual_http_keepalive_utf8_native_high_max_and_auxiliary(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(body)
                chunks=[sse_chunk({'role':'assistant','reasoning_content':'SYNTHETIC_THOUGHT'}),
                        sse_chunk({'content':'FC 合成报告'}),sse_chunk(finish='stop',usage=STREAM_USAGE)]
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(sse_body(chunks));self.wfile.flush()
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(provider,'BASE_URL','http://127.0.0.1:'+str(server.server_port)),patch.object(provider,'_load_key',return_value='sk-SYNTHETIC-NOT-REAL'):
                for effort in ('high','max'):
                    reply=provider.request_model(request(reasoning_effort=effort),TOOLS)
                    self.assertEqual(reply['usage'],STREAM_USAGE)
                    self.assertEqual(reply['choices'][0]['message']['content'],'FC 合成报告')
                    self.assertEqual(reply['choices'][0]['message']['reasoning_content'],'SYNTHETIC_THOUGHT')
                provider.request_model(request(tools=[]),TOOLS)
            self.assertEqual(len(seen),3)
            for body in seen:
                self.assertIs(body['stream'],True);self.assertEqual(body['stream_options'],{'include_usage':True})
                self.assertEqual(body['max_tokens'],393216);self.assertEqual(body['thinking'],{'type':'enabled'})
            self.assertNotIn('tools',seen[-1]);self.assertNotIn('tool_choice',seen[-1])
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_fragmented_parallel_tools_preserve_exact_arguments_and_order(self):
        chunks=[sse_chunk({'tool_calls':[{'index':1,'id':'tool-b','type':'function','function':{'name':'fc_b','arguments':'{"v":'}}]}),
                sse_chunk({'tool_calls':[{'index':0,'id':'tool-a','type':'function','function':{'name':'fc_a','arguments':'{}'}},
                                         {'index':1,'function':{'arguments':'"中文"}'}}]}),
                sse_chunk(finish='tool_calls',usage=STREAM_USAGE)]
        reply=provider._read_stream(io.BytesIO(sse_body(chunks)))
        calls=reply['choices'][0]['message']['tool_calls']
        self.assertEqual([c['id'] for c in calls],['tool-a','tool-b'])
        self.assertEqual([c['index'] for c in calls],[0,1])
        self.assertEqual(calls[1]['function'],{'name':'fc_b','arguments':'{"v":"中文"}'})
        self.assertEqual(reply['choices'][0]['finish_reason'],'tool_calls')

    def test_usage_only_and_vendor_final_chunk_are_both_supported(self):
        for chunks in ([sse_chunk({'content':'final'}),sse_chunk(finish='stop',usage=STREAM_USAGE)],
                       [sse_chunk({'content':'final'},finish='stop'),sse_chunk(usage=STREAM_USAGE,choices=[])]):
            with self.subTest(chunks=len(chunks)):
                reply=provider._read_stream(io.BytesIO(sse_body(chunks)))
                self.assertEqual(reply['usage'],STREAM_USAGE)
                self.assertEqual(reply['choices'][0]['message']['content'],'final')

    def test_truncated_missing_usage_and_changed_identity_never_succeed(self):
        variants=[sse_body([sse_chunk({'content':'partial'})],done=False),
                  sse_body([sse_chunk({'content':'partial'},finish='stop')]),
                  sse_body([sse_chunk({'content':'partial'}),sse_chunk(finish='stop',usage=STREAM_USAGE,id='changed')]),
                  sse_body([sse_chunk({'content':'first'}),sse_chunk(id=None,model=None),sse_chunk({'content':'second'},finish='stop',usage=STREAM_USAGE,id='changed')]),
                  sse_body([sse_chunk({'content':'first'},usage=STREAM_USAGE),sse_chunk({'content':'second'},finish='stop')]),
                  sse_body([sse_chunk({'content':'first'},finish='stop',usage=STREAM_USAGE),sse_chunk(usage=STREAM_USAGE)]),
                  sse_body([sse_chunk({'content':'partial'},finish='stop',usage=STREAM_USAGE),sse_chunk({'content':'late'})])]
        for raw in variants:
            with self.subTest(raw_bytes=len(raw)),self.assertRaises(ValueError):provider._read_stream(io.BytesIO(raw))

    def test_length_and_aborted_finish_reason_are_not_rewritten_as_stop(self):
        for finish in ('length','aborted','insufficient_system_resource','content_filter'):
            reply=provider._read_stream(io.BytesIO(sse_body([sse_chunk({'content':'partial'},finish=finish,usage=STREAM_USAGE)])))
            self.assertEqual(reply['choices'][0]['finish_reason'],finish)

    def test_connection_reset_preserves_unknown_and_never_retries(self):
        first=io.BytesIO(sse_body([sse_chunk({'content':'SYNTHETIC_PARTIAL_PRIVATE'})],done=False))
        class BrokenResponse:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def readline(self,limit):
                part=first.readline(limit)
                if part:return part
                raise ConnectionResetError('NEVER_SAVE_EXCEPTION_PROSE')
        opener=type('Opener',(),{'open':lambda self,*args,**kwargs:BrokenResponse()})()
        with patch.object(provider,'_load_key',return_value='sk-SYNTHETIC-NOT-REAL'),patch('urllib.request.build_opener',return_value=opener) as call:
            reply=provider.request_model(request(),TOOLS)
        self.assertEqual(reply['status'],'unknown_transport');self.assertEqual(reply['transport_error_type'],'ConnectionResetError')
        self.assertEqual(call.call_count,1);self.assertNotIn('PRIVATE',json.dumps(reply));self.assertNotIn('PROSE',json.dumps(reply))
        self.assertEqual(reply['timeout_seconds'],1800)

    def test_sse_framing_is_not_an_artificial_output_quota(self):
        chunks=[sse_chunk({'content':'a'}) for _ in range(20)]+[sse_chunk(finish='stop',usage=STREAM_USAGE)]
        raw=sse_body(chunks);self.assertGreater(len(raw),512)
        with patch.object(provider,'WIRE_BYTES',512):reply=provider._read_stream(io.BytesIO(raw))
        self.assertEqual(reply['choices'][0]['message']['content'],'a'*20)

    def test_reconstructed_response_still_respects_existing_wire_bound(self):
        chunks=[sse_chunk({'content':'a'*180}) for _ in range(4)]+[sse_chunk(finish='stop',usage=STREAM_USAGE)]
        with patch.object(provider,'WIRE_BYTES',512),self.assertRaises(ValueError):provider._read_stream(io.BytesIO(sse_body(chunks)))


if __name__ == '__main__':
    unittest.main()

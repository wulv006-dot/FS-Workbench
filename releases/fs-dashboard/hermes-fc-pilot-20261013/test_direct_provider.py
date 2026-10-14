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


if __name__ == '__main__':
    unittest.main()

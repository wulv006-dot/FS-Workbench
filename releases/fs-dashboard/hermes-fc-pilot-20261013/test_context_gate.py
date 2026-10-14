import unittest
import test_gateway as fixture
from proxy_gateway import request_body, MAX_PROVIDER_WIRE_BYTES, MAX_PROVIDER_CONTEXT_TOKENS, MAX_HERMES_OUTPUT_TOKENS, conservative_input_bound


class ContextGateTests(unittest.TestCase):
    setUp = fixture.GatewayTests.setUp
    tearDown = fixture.GatewayTests.tearDown
    db = fixture.GatewayTests.db
    slot = fixture.GatewayTests.slot
    answer = fixture.GatewayTests.answer

    def test_wide_utf8_evidence_fits_verified_window(self):
        body = {'messages': [{'role': 'user', 'content': '经营证据与替代解释。' * 8000}],
                'max_tokens': MAX_HERMES_OUTPUT_TOKENS, 'reasoning_effort': 'max'}
        request = request_body(body, self.policy['model'])
        self.assertGreater(len(request['messages'][0]['content'].encode()), 128000)
        self.assertLess(conservative_input_bound(request) + MAX_HERMES_OUTPUT_TOKENS, MAX_PROVIDER_CONTEXT_TOKENS)

    def test_wire_bytes_are_not_mistaken_for_tokens(self):
        body = {'messages': [{'role': 'user', 'content': ''}], 'max_tokens': MAX_HERMES_OUTPUT_TOKENS, 'reasoning_effort': 'max'}
        base = request_body(body, self.policy['model'])
        size = MAX_PROVIDER_CONTEXT_TOKENS - conservative_input_bound(base) - MAX_HERMES_OUTPUT_TOKENS + 1
        body['messages'][0]['content'] = 'x' * size
        self.assertLess(size, MAX_PROVIDER_WIRE_BYTES)
        request=request_body(body,self.policy['model'])
        self.assertGreater(conservative_input_bound(request)+MAX_HERMES_OUTPUT_TOKENS,MAX_PROVIDER_CONTEXT_TOKENS)
        self.gateway.call('owner',self.task['id'],'lease',0,body)
        self.assertEqual(self.calls,1)

    def test_many_small_rows_account_for_framing_and_output(self):
        body = {'messages': [{'role': 'user', 'content': 'x'}] * 2000, 'max_tokens': MAX_HERMES_OUTPUT_TOKENS, 'reasoning_effort': 'high'}
        request = request_body(body, self.policy['model'])
        self.assertGreater(conservative_input_bound(request), 128 * 2000)
        self.assertLess(conservative_input_bound(request) + MAX_HERMES_OUTPUT_TOKENS, MAX_PROVIDER_CONTEXT_TOKENS)


if __name__ == '__main__':
    unittest.main()

from capacity_fixtures import MaximumCapacityTests

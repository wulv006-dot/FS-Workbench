"""Real local HTTP transport with an isolated SQLite ledger and fake provider."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import unittest
import test_gateway as fixtures
from transport import Grants, Proxy, start_loopback


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GatewayTests()
        self.fixture.setUp()
        self.clock = 0
        self.grants = Grants(lambda: self.clock)
        self.token = self.grants.mint('owner', self.fixture.task['id'], 'lease')
        self.proxy = Proxy(self.grants, lambda grant: self.fixture.gateway)

    def tearDown(self):
        self.fixture.tearDown()

    def body(self):
        return {'model': 'fake-deepseek', 'messages': [{'role': 'user', 'content': 'investigate'}], 'max_tokens': 50}

    def call(self, **changes):
        body = self.body(); body.update(changes)
        return self.proxy.dispatch('POST', '/v1/chat/completions', self.token, body)

    def test_real_loopback_accepts_large_model_request_without_pruning(self):
        server,thread=start_loopback(self.proxy,port=0)
        try:
            body=self.body();body['messages']=[{'role':'user','content':'large evidence '*12000}]
            raw=json.dumps(body).encode()
            self.assertGreater(len(raw),128000)
            request=Request('http://127.0.0.1:'+str(server.server_address[1])+'/v1/chat/completions',raw,{'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
            with urlopen(request,timeout=5) as response:result=json.loads(response.read())
            self.assertEqual(result['id'],'fake_receipt_1')
            self.assertEqual(self.fixture.calls,1)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)

    def test_provider_retry_after_transport_restart_has_one_charge(self):
        first = self.call()
        self.proxy = Proxy(self.grants, lambda grant: self.fixture.gateway)
        self.assertEqual(self.call()['id'], first['id'])
        self.assertEqual(self.fixture.calls, 1)

    def test_explicit_disabled_reasoning_maps_to_existing_provider_policy(self):
        first = self.call(reasoning_effort='none')
        self.assertEqual(self.call()['id'], first['id'])
        self.assertEqual(self.fixture.calls, 1)
        for value in ('low', 'medium', 'high', 'invented', True, {'enabled': False}):
            with self.assertRaisesRegex(ValueError, 'reasoning_policy'):
                self.call(reasoning_effort=value)
        self.assertEqual(self.fixture.calls, 1)

    def test_only_empty_assistant_reasoning_pad_is_normalized(self):
        body=self.body();body['messages']=[{'role':'assistant','content':'continue','reasoning_content':' '}]
        first=self.proxy.dispatch('POST','/v1/chat/completions',self.token,body)
        body['messages'][0].pop('reasoning_content')
        self.assertEqual(self.proxy.dispatch('POST','/v1/chat/completions',self.token,body)['id'],first['id'])
        for value in ('private thought',' ' * 9,42):
            body['messages'][0]['reasoning_content']=value
            with self.assertRaisesRegex(ValueError,'reasoning_content_policy'):
                self.proxy.dispatch('POST','/v1/chat/completions',self.token,body)
        self.assertEqual(self.fixture.calls,1)

    def test_thinking_grant_pins_effort_and_preserves_private_tool_replay(self):
        token=self.grants.mint('owner',self.fixture.task['id'],'lease',reasoning_effort='high')
        seen=[]
        def provider(request):
            seen.append(request)
            result=self.fixture.answer(request)
            result['choices'][0]['message']['reasoning_content']='Synthetic provider thought'
            result['usage']['completion_tokens_details']={'reasoning_tokens':4}
            return result
        self.fixture.provider=provider
        body=self.body();body['reasoning_effort']='high'
        result=self.proxy.dispatch('POST','/v1/chat/completions',token,body)
        self.assertEqual(result['choices'][0]['message']['reasoning_content'],'Synthetic provider thought')
        self.assertTrue(seen[0]['enable_thinking']);self.assertEqual(seen[0]['reasoning_effort'],'high')
        for value in (None,'none','low','max','medium'):
            body['reasoning_effort']=value
            with self.assertRaisesRegex(ValueError,'reasoning_policy'):self.proxy.dispatch('POST','/v1/chat/completions',token,body)
        self.assertEqual(self.fixture.calls,1)
        self.grants.renew(token,'owner',self.fixture.task['id'],'lease')
        self.assertEqual(self.grants.resolve(token).reasoning_effort,'high')

    def test_only_identical_native_reasoning_duplicate_is_stripped(self):
        token=self.grants.mint('owner',self.fixture.task['id'],'lease',reasoning_effort='max')
        body=self.body();body['reasoning_effort']='max'
        body['messages']=[{'role':'assistant','content':'next','reasoning_content':'synthetic','reasoning':'synthetic'}]
        self.proxy.dispatch('POST','/v1/chat/completions',token,body)
        body['messages'][0]['reasoning']='different'
        with self.assertRaisesRegex(ValueError,'reasoning_carrier_mismatch'):
            self.proxy.dispatch('POST','/v1/chat/completions',token,body)
        self.assertEqual(self.fixture.calls,1)

    def test_provider_truncation_is_not_rewritten_as_successful_stop(self):
        def provider(request):
            result=self.fixture.answer(request);result['choices'][0]['finish_reason']='length';return result
        self.fixture.provider=provider
        self.assertEqual(self.call()['choices'][0]['finish_reason'],'length')

    def test_short_token_can_renew_without_total_runtime_cap(self):
        for _ in range(20):
            self.clock += 500
            self.grants.renew(self.token, 'owner', self.fixture.task['id'], 'lease')
        self.assertEqual(self.call()['object'], 'chat.completion')

    def test_expired_revoked_and_foreign_tokens_denied(self):
        with self.assertRaises(PermissionError): self.grants.renew(self.token, 'foreign', self.fixture.task['id'], 'lease')
        self.clock = 600
        with self.assertRaises(PermissionError): self.call()
        self.clock = 0
        self.grants.revoke(self.token)
        with self.assertRaises(PermissionError): self.call()
        self.assertEqual(self.fixture.calls, 0)

    def test_cancel_denies_even_still_valid_token(self):
        self.fixture.tasks.cancel(self.fixture.task['id'], 'owner')
        with self.assertRaises(PermissionError): self.call()
        self.assertEqual(self.fixture.calls, 0)

    def test_unknown_routes_and_provider_overrides_do_not_spend(self):
        for route in ('/api/skills', '/v1/runs', '/fc/context/../../secret'):
            with self.assertRaises(PermissionError): self.proxy.dispatch('GET', route, self.token)
        for change in ({'model': 'another'}, {'stream': True}, {'tools': []}, {'base_url': 'https://invalid'}):
            with self.assertRaises(ValueError): self.call(**change)
        self.assertEqual(self.fixture.calls, 0)

    def test_real_http_is_loopback_authenticated_and_openai_compatible(self):
        server, worker = start_loopback(self.proxy, port=0)
        try:
            self.assertEqual(server.server_address[0], '127.0.0.1')
            url = 'http://127.0.0.1:%s/v1/chat/completions' % server.server_address[1]
            data = json.dumps(self.body()).encode()
            with self.assertRaises(HTTPError) as rejected:
                urlopen(Request(url, data=data), timeout=3)
            self.assertEqual(rejected.exception.code, 403)
            rejected.exception.close()
            request = Request(url, data=data, headers={'Authorization': 'Bearer '+self.token})
            with urlopen(request, timeout=3) as response:
                result = json.load(response)
            self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
            self.assertEqual(result['usage']['total_tokens'], 60)
            self.assertEqual(self.fixture.calls, 1)
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=3)


if __name__ == '__main__': unittest.main()

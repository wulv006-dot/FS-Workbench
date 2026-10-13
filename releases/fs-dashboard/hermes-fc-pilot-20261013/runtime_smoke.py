"""Execute inside the fixed image with --network none and no business mounts.

Uses official Runs/AIAgent, the real local HTTP proxy, synthetic evidence and a
fake provider. This is integration evidence, never a real-model acceptance.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import tempfile

import hermes_worker
from transport import Grants, Proxy, start_loopback
from runs_contract import WIRE_TOOLS
import test_gateway as fixtures


async def run():
    import aiohttp
    fixture = fixtures.GatewayTests()
    fixture.setUp()
    fixture.budget.policy['model'] = 'deepseek-v4.1-flash'
    fixture.scope.deadline = None
    grants = Grants()
    token = grants.mint('owner', fixture.task['id'], 'lease')
    tool_hits = []
    original_call = fixture.scope.call
    def observe(*args, **kwargs):
        tool_hits.append(args[3])
        return original_call(*args, **kwargs)
    fixture.scope.call = observe
    def provider(request):
        result = fixture.answer(request)
        if fixture.calls == 1:
            result['choices'][0]['message'] = {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'call_fixture', 'type': 'function', 'function': {
                    'name': WIRE_TOOLS[0], 'arguments': '{}'}}]}
        else:
            result['choices'][0]['message'] = {'role': 'assistant', 'content': 'Fixture investigation complete.'}
        return result
    fixture.provider = provider
    proxy = Proxy(grants, lambda grant: fixture.gateway)
    original_dispatch = proxy.dispatch
    def diagnose(method, path, token, body=None):
        try:
            return original_dispatch(method, path, token, body)
        except Exception as exc:
            # Synthetic CI only: print shape and validation code, never token/body.
            print(json.dumps({'proxy_error': str(exc), 'keys': sorted(body or {}),
                              'message_shapes': [sorted(m) for m in (body or {}).get('messages', [])]}), flush=True)
            raise
    proxy.dispatch = diagnose
    server, thread = start_loopback(proxy)
    adapter = None
    try:
        session_id = 'fc_'+'a'*64
        hermes_worker.ADMISSIONS = fixture.root/'admissions'
        hermes_worker.ADMISSIONS.mkdir()
        (hermes_worker.ADMISSIONS/(session_id+'.json')).write_text(json.dumps({
            'session_id': session_id, 'token': token, 'model': 'deepseek-v4.1-flash',
            'prompt': 'Use only the registered FC readonly tools. This is synthetic integration validation.'}), encoding='utf-8')
        home = Path(os.environ['HERMES_HOME']); home.mkdir(parents=True, exist_ok=True)
        (home/'config.yaml').write_text((Path(__file__).parent/'runtime-config.yaml').read_text('utf-8'), encoding='utf-8')
        api_key = secrets.token_urlsafe(32)
        adapter = hermes_worker.make_adapter(api_key)
        assert await adapter.connect(), 'official_runtime_start'
        headers = {'Authorization': 'Bearer '+api_key, 'Idempotency-Key': 'fixture-integration-only'}
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get('http://127.0.0.1:8941/v1/skills') as denied:
                assert denied.status == 403, 'skills_route_must_be_denied'
            async with client.post('http://127.0.0.1:8941/v1/runs', json={
                    'input': 'Check FC metric definitions, then finish.', 'session_id': session_id}) as response:
                result = await response.json()
                assert response.status == 202, ('admission', response.status, result)
            run_id = result['run_id']
            for _ in range(90):
                async with client.get('http://127.0.0.1:8941/v1/runs/'+run_id) as response:
                    result = await response.json()
                if result['status'] not in {'queued', 'running', 'stopping'}:
                    break
                await asyncio.sleep(0.5)
            assert result['status'] == 'completed', result
            assert fixture.calls == 2, ('provider_calls', fixture.calls)
            assert tool_hits == [WIRE_TOOLS[0]], ('tool_calls', tool_hits)
            async with client.post('http://127.0.0.1:8941/v1/runs', json={
                    'input': 'Check FC metric definitions, then finish.', 'session_id': session_id}) as response:
                replay = await response.json()
            assert replay['run_id'] == run_id and fixture.calls == 2, 'durable_admission_replay'
        print(json.dumps({'official_runs': 'pass', 'official_agent': 'pass', 'tools': tool_hits,
                          'model': 'fake-provider', 'provider_calls': fixture.calls,
                          'real_business_data': False, 'real_model_call': False}))
    finally:
        if adapter is not None:
            await adapter.disconnect()
        server.shutdown(); server.server_close(); thread.join(timeout=3)
        fixture.tearDown()


if __name__ == '__main__':
    asyncio.run(run())

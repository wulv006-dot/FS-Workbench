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
from runs_contract import WIRE_TOOLS,validate_admission
import test_gateway as fixtures


async def run(effort):
    import aiohttp
    fixture = fixtures.GatewayTests()
    fixture.setUp()
    fixture.budget.policy['model'] = 'deepseek-v4.1-flash'
    fixture.scope.deadline = None
    fixture.task=fixture.tasks.create('owner',dict(fixture.task['spec'],template_version='official-'+effort))
    fixture.task=fixture.tasks.reserve_dispatch(fixture.task['id'],'owner','lease')
    grants = Grants()
    token = grants.mint('owner', fixture.task['id'], 'lease',reasoning_effort=effort)
    tool_hits = []
    original_call = fixture.scope.call
    def observe(*args, **kwargs):
        tool_hits.append(args[3])
        return original_call(*args, **kwargs)
    fixture.scope.call = observe
    def provider(request):
        assert request['enable_thinking'] is True and request['reasoning_effort']==effort, 'thinking_not_enabled'
        assert '自主按线索下钻' in request['messages'][0]['content'], 'skill_not_loaded'
        result = fixture.answer(request)
        if fixture.calls == 1:
            result['choices'][0]['message'] = {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'call_fixture', 'type': 'function', 'index':0, 'function': {
                    'name': WIRE_TOOLS[0], 'arguments': '{}'}}]}
            result['choices'][0]['message']['reasoning_content']='Synthetic private reasoning for the first tool call.'
        elif fixture.calls==2:
            tool_text=request['messages'][3]['content']
            assert '"main_source":"Admin"' in tool_text and '"reference_source":"Order"' in tool_text, 'actual_tool_evidence_not_received'
            assert 'tool_result_contract' not in tool_text, 'tool_contract_error_received'
            assert request['messages'][2]['tool_calls'][0].get('index')==0, 'tool_index_replay_missing'
            assert request['messages'][2]['reasoning_content']=='Synthetic private reasoning for the first tool call.', 'reasoning_replay_missing'
            result['choices'][0]['message'] = {'role': 'assistant', 'content': 'Fixture investigation complete.'}
        else:
            assert any(m.get('role')=='user' and m.get('content')=='Reassess the previous conclusion with a competing explanation.' for m in request['messages']), 'second_user_turn_missing'
            assert any(m.get('role')=='assistant' and m.get('content')=='Fixture investigation complete.' for m in request['messages']), 'previous_judgment_missing'
            result['choices'][0]['message']={'role':'assistant','content':'Fixture follow-up complete.'}
        result['usage']['completion_tokens_details']={'reasoning_tokens':3}
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
                              'message_shapes': [sorted(m) for m in (body or {}).get('messages', [])],
                              'tool_call_shapes': [sorted(c) for m in (body or {}).get('messages', []) for c in m.get('tool_calls', [])]}), flush=True)
            raise
    proxy.dispatch = diagnose
    server, thread = start_loopback(proxy)
    adapter = None
    try:
        session_id = 'fc_'+'a'*64
        hermes_worker.ADMISSIONS = fixture.root/'admissions'
        hermes_worker.ADMISSIONS.mkdir()
        admitted={
            'session_id': session_id, 'token': token, 'model': 'deepseek-v4.1-flash',
            'reasoning_effort':effort,'ready':False,
            'prompt': 'Use only the registered FC readonly tools. This is synthetic integration validation.'}
        admission_file=hermes_worker.ADMISSIONS/(session_id+'.json')
        admission_file.write_text(json.dumps(admitted),encoding='utf-8')
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
            run_id=validate_admission(response.status,result)
            assert result['status']=='started','pinned_admission_shape'
            fixture.tasks.bind_run(fixture.task['id'],'owner','lease',run_id)
            admitted['ready']=True
            temporary=admission_file.with_suffix('.tmp');temporary.write_text(json.dumps(admitted),encoding='utf-8');temporary.replace(admission_file)
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
            async with client.post('http://127.0.0.1:8941/v1/runs',headers={'Idempotency-Key':'fixture-second-user-turn'},json={
                    'input':'Reassess the previous conclusion with a competing explanation.','session_id':session_id}) as response:
                followup=await response.json()
                assert response.status==202 and followup['run_id']!=run_id, 'second_turn_admission'
            for _ in range(90):
                async with client.get('http://127.0.0.1:8941/v1/runs/'+followup['run_id']) as response:followup=await response.json()
                if followup['status'] not in {'queued','running','stopping'}:break
                await asyncio.sleep(.5)
            assert followup['status']=='completed' and fixture.calls==3, ('second_user_turn',followup)
            cancelled_session='fc_'+'b'*64
            cancelled_admission=dict(admitted,session_id=cancelled_session,ready=False)
            (hermes_worker.ADMISSIONS/(cancelled_session+'.json')).write_text(json.dumps(cancelled_admission),encoding='utf-8')
            async with client.post('http://127.0.0.1:8941/v1/runs',headers={'Idempotency-Key':'fixture-handshake-cancel'},json={
                    'input':'Cancel this synthetic run before FS binds it.','session_id':cancelled_session}) as response:
                cancelled=await response.json();cancelled_id=validate_admission(response.status,cancelled)
            async with client.post('http://127.0.0.1:8941/v1/runs/'+cancelled_id+'/stop',json={}) as response:
                assert response.status in (200,202), 'handshake_stop_ack'
            for _ in range(30):
                async with client.get('http://127.0.0.1:8941/v1/runs/'+cancelled_id) as response:cancelled=await response.json()
                if cancelled['status'] not in {'queued','running','stopping'}:break
                await asyncio.sleep(.1)
            assert cancelled['status']=='cancelled' and fixture.calls==3, ('handshake_cancel',cancelled)
        print(json.dumps({'official_runs': 'pass', 'official_agent': 'pass', 'tools': tool_hits,
                          'model': 'fake-provider', 'provider_calls': fixture.calls,
                          'reasoning_effort':effort,'second_user_turn':'pass','tool_index_replay':'pass','actual_tool_evidence_received':'pass',
                          'actual_started_admission_and_run_binding':'pass',
                          'cancel_before_handshake_no_model_call':'pass',
                          'real_business_data': False, 'real_model_call': False}))
    finally:
        if adapter is not None:
            await adapter.disconnect()
        server.shutdown(); server.server_close(); thread.join(timeout=3)
        fixture.tearDown()


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--effort',choices=['high','max'],required=True)
    asyncio.run(run(parser.parse_args().effort))

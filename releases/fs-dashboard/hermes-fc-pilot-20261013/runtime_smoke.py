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
import resource
import time
import hashlib

import hermes_worker
from transport import Grants, Proxy, start_loopback
from proxy_gateway import MAX_PROVIDER_WIRE_BYTES, MAX_HERMES_OUTPUT_TOKENS
from runs_contract import WIRE_TOOLS,validate_admission
import test_gateway as fixtures


async def run(effort):
    import aiohttp
    fixture = fixtures.GatewayTests()
    fixture.setUp()
    from proxy_gateway import UnifiedBudget, schemas
    from direct_provider import MODEL, request_model as direct_request, prepare_request
    from fs_inprocess import approved_background
    from skill_bundle import load_bundle
    from background import task_context
    background=approved_background(Path(__file__).parent)
    context_text,context_receipt=task_context(background,load_bundle(Path(__file__).parent))
    from unittest.mock import patch
    fixture.budget=UnifiedBudget(fixture.db,{'id':'no-pilot-quotas-deepseek-direct-stream-tokens-only-v2','model':MODEL,'price_version':'deepseek-direct-no-cny-invoice-or-fx-v1','input_microcny':None,'output_microcny':None},lambda:fixture.now,allow_unknown_costs=True)
    fixture.gateway.budget=fixture.budget
    fixture.gateway.preflight=lambda req:prepare_request(req,schemas())
    fixture.scope.deadline = None
    fixture.task=fixture.tasks.create('owner',dict(fixture.task['spec'],template_version='official-'+effort))
    fixture.task=fixture.tasks.reserve_dispatch(fixture.task['id'],'owner','lease')
    grants = Grants()
    token = grants.mint('owner', fixture.task['id'], 'lease',reasoning_effort=effort)
    tool_hits = []
    stress = True  # Preserve eight complete large tool results; do not prune early.
    if stress:
        fixture.gateway.input_bound = lambda request: len(json.dumps(request,ensure_ascii=False,separators=(',',':')).encode())
    request_sizes = []
    saw_prune = []
    aux_calls=[]
    original_call = fixture.scope.call
    def observe(*args, **kwargs):
        tool_hits.append(args[3])
        value = original_call(*args, **kwargs)
        if stress:value=dict(value,synthetic_payload=('synthetic-only-'+str(len(tool_hits))+' ')*1100,synthetic_identity='task-scoped HMAC pseudonyms for order/event/item IDs',synthetic_public_note='Use "task-scoped" evidence.')
        return value
    fixture.scope.call = observe
    def provider(request):
        assert request['enable_thinking'] is True and request['reasoning_effort']==effort, 'thinking_not_enabled'
        if request['tools']==[]:
            aux_calls.append(request)
            assert request['max_tokens']==MAX_HERMES_OUTPUT_TOKENS,'aux_output_maximum'
            return {'id':'native_summary_receipt','model':'deepseek-flash',
                'usage':{'prompt_tokens':30,'completion_tokens':50,'total_tokens':80},
                'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'Native complete synthetic summary.'}}]}
        assert '自主按线索下钻' in request['messages'][0]['content'], 'skill_not_loaded'
        assert background['content'] in request['messages'][0]['content'], 'business_background_not_loaded'
        assert context_text in request['messages'][0]['content'], 'reviewed_methods_and_preferences_not_loaded'
        result = dict(fixture.answer(request), model=MODEL)
        if stress:
            size=len(json.dumps(request,ensure_ascii=False,separators=(',',':')).encode())
            assert size<=MAX_PROVIDER_WIRE_BYTES,'stress_request_exceeds_hermes_wire'
            request_sizes.append(size)
            saw_prune.append(any(m.get('role')=='tool' and len(str(m.get('content') or ''))<4000 for m in request['messages']))
            if fixture.calls>1:
                latest=next(m['content'] for m in reversed(request['messages']) if m.get('role')=='tool')
                assert '"main_source":"Admin"' in latest and '"reference_source":"Order"' in latest, 'stress_actual_evidence_missing'
                assert 'tool_result_contract' not in latest, 'stress_tool_error_received'
                assert 'task-scoped HMAC pseudonyms for order/event/item IDs' in latest, 'safe_task_scope_description_not_received'
            for message in request['messages']:
                for call in message.get('tool_calls',[]):
                    assert call.get('index')==0 and call['function']['arguments']=='{}', 'stress_tool_history_changed'
                if message.get('tool_calls'):assert message.get('reasoning_content')=='Synthetic task-scoped reasoning.', 'stress_reasoning_changed'
            if fixture.calls<=8:
                result['choices'][0]['message']={'role':'assistant','content':None,'reasoning_content':'Synthetic task-scoped reasoning.',
                    'tool_calls':[{'id':'stress_'+str(fixture.calls),'type':'function','index':0,'function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}]}
            elif fixture.calls==9:result['choices'][0]['message']={'role':'assistant','content':'Fixture investigation complete.\n'+'\n'.join(hashlib.sha256(('synthetic row '+str(i)).encode()).hexdigest() for i in range(2500))}
            else:result['choices'][0]['message']={'role':'assistant','content':'Fixture follow-up complete.'}
            tokens=min(17000,size)
            result['usage']={'prompt_tokens':tokens,'completion_tokens':20000,'total_tokens':tokens+20000,'completion_tokens_details':{'reasoning_tokens':17000}}
            result['choices'][0]['finish_reason']='tool_calls' if result['choices'][0]['message'].get('tool_calls') else 'stop'
            return result
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
            result['choices'][0]['message'] = {'role': 'assistant', 'content': 'Fixture investigation complete.\n'+'\n'.join(hashlib.sha256(('synthetic row '+str(i)).encode()).hexdigest() for i in range(2500))}
        else:
            assert any(m.get('role')=='user' and m.get('content')=='Reassess the previous conclusion with a competing explanation.' for m in request['messages']), 'second_user_turn_missing'
            assert any(m.get('role')=='assistant' and m.get('content')=='Fixture investigation complete.' for m in request['messages']), 'previous_judgment_missing'
            result['choices'][0]['message']={'role':'assistant','content':'Fixture follow-up complete.'}
        result['usage']['completion_tokens_details']={'reasoning_tokens':3}
        result['choices'][0]['finish_reason']='tool_calls' if result['choices'][0]['message'].get('tool_calls') else 'stop'
        return result
    def through_direct(request):
        def fake_open(path, payload):
            assert path=='/chat/completions','direct_endpoint_not_chat'
            body=json.loads(payload)
            assert body['model']=='deepseek-flash' and body['thinking']=={'type':'enabled'},'direct_provider_identity_or_thinking'
            assert body['reasoning_effort']==effort and body['max_tokens']==MAX_HERMES_OUTPUT_TOKENS,'direct_parameters_not_pinned'
            assert 'enable_thinking' not in body,'bailian_fields_in_direct_payload'
            assert body['stream'] is True and body['stream_options']=={'include_usage':True},'direct_stream_keepalive_missing'
            converted=dict(body,tools=body.get('tools',[]),enable_thinking=True)
            result=provider(converted)
            message=result['choices'][0]['message'];chunks=[]
            def chunk(delta,finish=None,usage=None):
                return dict(id=result['id'],model=result['model'],choices=[dict(index=0,delta=delta,finish_reason=finish)],usage=usage)
            if message.get('reasoning_content'):chunks.append(chunk({'reasoning_content':message['reasoning_content']}))
            if message.get('content'):chunks.append(chunk({'content':message['content']}))
            for index,tool in enumerate(message.get('tool_calls') or []):chunks.append(chunk({'tool_calls':[dict(tool,index=index)]}))
            chunks.append(chunk({},result['choices'][0]['finish_reason'],result['usage']))
            import io
            from direct_provider import _read_stream
            events=b': keep-alive\n\n'+b''.join(b'data: '+json.dumps(row,ensure_ascii=False).encode()+b'\n\n' for row in chunks)+b'data: [DONE]\n\n'
            return _read_stream(io.BytesIO(events))
        with patch('direct_provider._open',side_effect=fake_open):return direct_request(request,schemas())
    fixture.provider = through_direct
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
            'session_id': session_id, 'token': token, 'model': 'deepseek-flash',
            'reasoning_effort':effort,'ready':False,
            'background':background,'context_receipt':context_receipt,
            'prompt': 'Use only the registered FC readonly tools. This is synthetic integration validation.'}
        admission_file=hermes_worker.ADMISSIONS/(session_id+'.json')
        admission_file.write_text(json.dumps(admitted),encoding='utf-8')
        home = Path(os.environ['HERMES_HOME']); home.mkdir(parents=True, exist_ok=True)
        (home/'config.yaml').write_text((Path(__file__).parent/'runtime-config.yaml').read_text('utf-8'), encoding='utf-8')
        import run_agent
        rpc_timeouts=[]
        actual_agents=[]
        original_agent_init=run_agent.AIAgent.__init__
        def observe_agent_init(agent,*args,**kwargs):
            original_agent_init(agent,*args,**kwargs)
            actual_agents.append(agent)
            assert agent.max_tokens==MAX_HERMES_OUTPUT_TOKENS, 'native_output_limit_not_applied'
            read_timeout=getattr(agent.client.timeout,'read',agent.client.timeout)
            stale_timeout=agent._compute_non_stream_stale_timeout({'messages':[]})
            outer_timeout=agent._resolved_api_call_timeout()
            assert min(read_timeout,stale_timeout,outer_timeout)>=1860, 'rpc_timeout_less_than_provider_wait'
            rpc_timeouts.append({'read':read_timeout,'stale':stale_timeout,'outer':outer_timeout})
        run_agent.AIAgent.__init__=observe_agent_init
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
            assert result.get('runtime',{}).get('fs_context_sha256')==context_receipt['context_sha256'], 'runtime_context_receipt_missing'
            assert len(result['output'])>128000,'large_official_final_report_not_exercised'
            summary=await asyncio.to_thread(actual_agents[0].context_compressor._call_summary_llm,
                    'Summarize this synthetic FC-only evidence for native compaction.',time.monotonic())
            assert summary=='Native complete synthetic summary.','official_summary_roundtrip'
            assert len(aux_calls)==1,'auxiliary_probe_or_retry_billed_twice'
            with fixture.db() as db:
                receipts=[json.loads(row[0]) for row in db.execute("SELECT content FROM model_calls WHERE state='succeeded'")]
            assert len([r for r in receipts if r['provider_request_id']=='native_summary_receipt'])==1,'aux_receipt_missing_or_duplicate'
            expected_calls = 9 if stress else 2
            assert fixture.calls == expected_calls, ('provider_calls', fixture.calls)
            assert tool_hits == [WIRE_TOOLS[0]]*(8 if stress else 1), ('tool_calls', tool_hits)
            if stress:
                assert not any(saw_prune), 'unexpected_early_prune'
                assert max(request_sizes)>128000, 'larger_wire_not_exercised'
            async with client.post('http://127.0.0.1:8941/v1/runs', json={
                    'input': 'Check FC metric definitions, then finish.', 'session_id': session_id}) as response:
                replay = await response.json()
            assert replay['run_id'] == run_id and fixture.calls == expected_calls, 'durable_admission_replay'
            async with client.post('http://127.0.0.1:8941/v1/runs',headers={'Idempotency-Key':'fixture-second-user-turn'},json={
                    'input':'Reassess the previous conclusion with a competing explanation.','session_id':session_id}) as response:
                followup=await response.json()
                assert response.status==202 and followup['run_id']!=run_id, 'second_turn_admission'
            for _ in range(90):
                async with client.get('http://127.0.0.1:8941/v1/runs/'+followup['run_id']) as response:followup=await response.json()
                if followup['status'] not in {'queued','running','stopping'}:break
                await asyncio.sleep(.5)
            assert followup['status']=='completed' and fixture.calls==expected_calls+1, ('second_user_turn',followup)
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
            assert cancelled['status']=='cancelled' and fixture.calls==expected_calls+1, ('handshake_cancel',cancelled)
        print(json.dumps({'official_runs': 'pass', 'official_agent': 'pass', 'tools': tool_hits,
                          'model': 'fake-provider', 'provider_calls': fixture.calls,
                          'reasoning_effort':effort,'second_user_turn':'pass','tool_index_replay':'pass','actual_tool_evidence_received':'pass',
                          'native_prune_stress':stress,'native_prune_observed':any(saw_prune),'largest_request_bytes':max(request_sizes or [0]),
                          'fs_transport_limit_bytes':MAX_PROVIDER_WIRE_BYTES,'native_output_limit_tokens':MAX_HERMES_OUTPUT_TOKENS,'direct_provider_wire_verified':True,'direct_context_tokens':1048576,'verified_response_completion_tokens':20000,'complete_tool_results_retained':not any(saw_prune),
                          'ordinary_task_scope_description_preserved':True,'rpc_client_timeout_checks':rpc_timeouts,
                          'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          'actual_started_admission_and_run_binding':'pass',
                          'actual_background_and_methods_prompt':'pass','runtime_context_receipt':'pass',
                          'background_version':context_receipt['background_version'],'background_sha256':context_receipt['background_sha256'],
                          'cancel_before_handshake_no_model_call':'pass','official_native_summary_roundtrip':'pass','auxiliary_paid_calls':len(aux_calls),'large_terminal_output_bytes':len(result['output'].encode()),
                          'real_business_data': False, 'real_model_call': False}))
    finally:
        if adapter is not None:
            await adapter.disconnect()
        server.shutdown(); server.server_close(); thread.join(timeout=3)
        if 'original_agent_init' in locals():run_agent.AIAgent.__init__=original_agent_init
        fixture.tearDown()


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--effort',choices=['high','max'],required=True)
    asyncio.run(run(parser.parse_args().effort))

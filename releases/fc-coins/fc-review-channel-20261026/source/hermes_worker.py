"""Constrained adapter around the pinned official Hermes Runs implementation.

FS registers approved HTTP-backed tools through Hermes' official registry API. The
wire names retain the v1 contract; this adapter does not claim an MCP connection.
Provider credentials never enter this process. Admissions are FS-owned read-only
files containing a renewable task token, model name, and approved task context.
"""
import asyncio
import json
from pathlib import Path
import re
import signal
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

from proxy_gateway import schemas, MAX_PROVIDER_CONTEXT_TOKENS, MAX_HERMES_OUTPUT_TOKENS, MAX_PROVIDER_WIRE_BYTES
from runs_contract import WIRE_TOOLS, SEMANTIC_TOOLS, PIN


ADMISSIONS = Path('/run/fs-hermes-fc/admissions')
PROXY = 'http://127.0.0.1:8940'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def admission(session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r'(?:fc|hc|mg)_[a-f0-9]{64}', session_id):
        raise PermissionError('session_not_admitted')
    path = ADMISSIONS/(session_id+'.json')
    if path.is_symlink() or path.stat().st_size > MAX_PROVIDER_WIRE_BYTES:
        raise PermissionError('admission_invalid')
    item = json.loads(path.read_text('utf-8'))
    if not isinstance(item,dict) or set(item)-{'session_id', 'token', 'model', 'prompt','ready','reasoning_effort','background','context_receipt','report_mode','skill_question','frozen_skills','learning_receipt','learning_text','conversation','run_id','materials'} or not {'session_id','token','model','prompt'}.issubset(item) or item['session_id'] != session_id:
        raise PermissionError('admission_invalid')
    if session_id.startswith('mg_'):
        material = item.get('materials')
        if (not isinstance(material, dict) or set(material) != {'key','fingerprint','execution_sha256','execution'}
                or not re.fullmatch('mg-[a-f0-9]{64}', material.get('key',''))
                or any(not re.fullmatch('[a-f0-9]{64}', material.get(k,'')) for k in ('fingerprint','execution_sha256'))
                or any(k in item for k in ('conversation','background','frozen_skills','learning_text','report_mode','context_receipt'))):
            raise PermissionError('material_admission_invalid')
        from material_execution import validate_execution
        execution=validate_execution(material['execution'])
        if execution['payload_sha256']!=material['execution_sha256'] or execution['system_prompt']!=item['prompt']:
            raise PermissionError('material_context_changed')
    elif 'materials' in item:
        raise PermissionError('material_admission_invalid')
    elif session_id.startswith('hc_'):
        if item.get('conversation') is not True or 'report_mode' in item or 'background' in item:
            raise PermissionError('conversation_admission_invalid')
        if 'run_id' in item and not re.fullmatch(r'run_[a-f0-9]{32}',item['run_id']):
            raise PermissionError('conversation_run_invalid')
    elif 'conversation' in item or 'run_id' in item:
        raise PermissionError('report_admission_changed')
    if ('background' in item)!=('context_receipt' in item) or any(not isinstance(item[n],dict) for n in ('background','context_receipt') if n in item):
        raise PermissionError('admission_context_invalid')
    if 'skill_question' in item and (not isinstance(item['skill_question'],str) or not 2<=len(item['skill_question'])<=600):
        raise PermissionError('admission_skill_question')
    if 'report_mode' in item and item['report_mode'] not in ('daily','investigation','kpi','pricing'):
        raise PermissionError('admission_report_mode')
    if 'ready' in item and type(item['ready']) is not bool:
        raise PermissionError('admission_invalid')
    if item.get('reasoning_effort','none') not in ('none','low','high','max'):raise PermissionError('admission_reasoning')
    if item['model'] != 'deepseek-flash' or not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', item['token']):
        raise PermissionError('admission_invalid')
    if not isinstance(item['prompt'], str):
        raise PermissionError('admission_invalid')
    learning_fields={'frozen_skills','learning_receipt','learning_text'}
    if learning_fields & set(item):
        import hashlib
        if not learning_fields.issubset(item) or not isinstance(item['learning_text'],str) or not isinstance(item['frozen_skills'],dict) or not isinstance(item['learning_receipt'],dict):raise PermissionError('admission_learning_invalid')
        proof=item['learning_receipt'];identity=proof.get('identity',{})
        if hashlib.sha256(item['learning_text'].encode()).hexdigest()!=identity.get('knowledge_sha256'):raise PermissionError('admission_learning_changed')
        if hashlib.sha256(json.dumps(item['frozen_skills'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=identity.get('frozen_skills_sha256'):raise PermissionError('admission_learning_changed')
        if proof.get('version')!='learning-'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest():raise PermissionError('admission_learning_changed')
    return item


def skill_question(item):
    return item.get('skill_question',item['prompt'])


def runtime_metadata(item,bundle):
    result={'provider':'custom','model':item['model'],'route_source':'fs_task_admission',
            'fs_reasoning_effort':item.get('reasoning_effort','none')}
    if not item.get('conversation') and not item.get('materials'):
        result.update(fs_skill_version=bundle['version'],fs_skill_sha256=bundle['sha256'])
    return result


def call_tool(name, args, *, session_id=None, parent_agent=None, **unused):
    session_id = getattr(parent_agent, 'session_id', None) or session_id
    item = admission(session_id)
    body = json.dumps({'name': name, 'arguments': args}).encode()
    request = Request(PROXY+'/fc/tools/call', body,
                      {'Authorization': 'Bearer '+item['token'], 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            raw = response.read(MAX_PROVIDER_WIRE_BYTES+1)
    except HTTPError as error:
        if name not in ('fc.calculate','mcp__fcro__fc_calculate') or error.code!=400:raise
        raw=error.read(MAX_PROVIDER_WIRE_BYTES+1)
        if len(raw)>MAX_PROVIDER_WIRE_BYTES:raise ValueError('tool_response_size')
        try:code=json.loads(raw).get('error')
        except (ValueError,AttributeError):raise error
        if isinstance(code,dict):code=code.get('code')
        codes={'calculation_evidence','calculation_bindings','calculation_assumption','calculation_operand_mismatch','evidence_path','decimal_required','calculation_fields','calculation_operation'}
        if not isinstance(code,str) or code not in codes:raise error
        return json.dumps({'status':'invalid_arguments','code':code,'calculationPerformed':False,
            'help':'values 为无千分逗号的十进制字符串；每项都有 value_paths 和 assumptions。实际证据字段用 /data/... JSON pointer，assumptions 填空字符串；仅情景输入可用 null 路径并说明假设。路径从完整 ev 信封根开始，例如 /data/total/revenue_usd；具体字段须以这条证据实际结构为准，不反复猜路径。'},ensure_ascii=False)
    if len(raw) > MAX_PROVIDER_WIRE_BYTES:
        raise ValueError('tool_response_size')
    return json.dumps(json.loads(raw),ensure_ascii=False,separators=(',',':'),allow_nan=False)


def loaded_context_metadata(agent):
    source=getattr(agent,'_hermes_api_runtime',{}) or {}
    result={}
    if isinstance(source.get('fs_material_context'),dict):
        result['fs_material_context']=source['fs_material_context']
    for key in ('fs_context_version','fs_context_sha256','fs_background_version','fs_background_sha256',
                'fs_methods_sha256','fs_governance_sha256','fs_skill_version','fs_skill_sha256'):
        value=source.get(key)
        pattern=r'[a-f0-9]{64}' if key.endswith('sha256') else r'[A-Za-z0-9_.-]{1,80}'
        if isinstance(value,str) and re.fullmatch(pattern,value):result[key]=value
    proof=source.get('fs_effective_input')
    if isinstance(proof,dict) and proof.get('status')=='assembled_verified' and proof.get('knowledge_present') is True:
        result['fs_effective_input']={k:proof[k] for k in ('status','knowledge_version','knowledge_sha256','system_prompt_sha256','characters','knowledge_present','native_memory_skipped','memory_path')}
    return result


def _fs_no_implicit_dotenv(*, hermes_home=None, project_env=None, load_external_secrets=True):
    # FS supplies its config and task-scoped loopback credential explicitly.
    # The pinned official loader returns a list of loaded paths. This process
    # loads none; Desktop and other processes retain the unmodified loader.
    return []


def make_adapter(api_key):
    from hermes_cli import env_loader
    env_loader.load_hermes_dotenv = _fs_no_implicit_dotenv
    from hermes_cli import config as hermes_config
    # FS owns this config; Desktop keeps the shared home and its own config.yaml.
    hermes_config.get_config_path = lambda: Path(__file__).with_name('runtime-config.yaml')
    from aiohttp import web
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.platforms import api_server_runs
    from tools.registry import registry
    from toolsets import create_custom_toolset
    from run_agent import AIAgent

    # Pinned Runs calls _create_agent on its event loop before starting the
    # executor. Wait cooperatively here so its HTTP202 can actually be flushed.
    # Retain the official executor for terminal state, cancellation and cleanup.
    if not getattr(api_server_runs._execute_run,'_fs_async_gate',False):
        original_executor=api_server_runs._execute_run
        async def admitted_executor(adapter,run,*,_api_server):
            if getattr(adapter,'_fs_handshake',False):
                deadline=time.monotonic()+30
                try:
                    while run.run_id not in adapter._stopping_run_ids and run.run_id not in adapter._shutdown_interrupted_run_ids:
                        try:item=admission(run.session_id)
                        except (ValueError,PermissionError,OSError):break
                        if item.get('ready',True) or time.monotonic()>=deadline:break
                        await asyncio.sleep(.1)
                except asyncio.CancelledError:
                    adapter._stopping_run_ids.add(run.run_id)
            await original_executor(adapter,run,_api_server=_api_server)
        admitted_executor._fs_async_gate=True
        api_server_runs._execute_run=admitted_executor

    for schema in schemas():
        name = schema['function']['name']
        def handler(args, _name=name, **context):
            return call_tool(_name, args, **context)
        registry.register(name=name, toolset='fs_fc_readonly', schema=schema['function'], handler=handler)
    create_custom_toolset('fs_fc_readonly', 'FS FC aggregate readonly', tools=list(WIRE_TOOLS))
    from conversation_file_tools import WIRE_NAMES as MATERIAL_WIRE_NAMES
    create_custom_toolset('fs_materials', 'Explicitly selected material files', tools=list(MATERIAL_WIRE_NAMES))

    class ReadonlyAdapter(APIServerAdapter):
        _fs_handshake=True
        def _set_run_status(self,run_id,status,**fields):
            # Pinned official Runs emits only provider/model. Preserve the actual
            # constructed agent's verified FS context receipt in its pollable record.
            loaded=loaded_context_metadata(self._active_run_agents.get(run_id))
            if loaded:fields['runtime']={**(fields.get('runtime') or {}),**loaded}
            result=super()._set_run_status(run_id,status,**fields)
            if status in {'completed','failed','cancelled','interrupted'}:
                session_id=result.get('session_id')
                getattr(self,'_material_admitted_inputs',{}).pop(session_id,None)
            return result

        def _http_route_table(self):
            allowed = {('GET', '/v1/capabilities'), ('POST', '/v1/runs'),
                       ('GET', '/v1/runs/{run_id}'), ('POST', '/v1/runs/{run_id}/stop'),
                       ('GET', '/v1/runs/{run_id}/events'), ('POST', '/v1/runs/{run_id}/steer')}
            routes = [row for row in super()._http_route_table() if row[:2] in allowed]
            routes.append(('GET', '/v1/materials/{session_id}', self._material_lookup))
            return routes

        async def _material_lookup(self, request):
            denied = self._check_auth(request)
            if denied is not None:
                return denied
            from conversation_material_runs import readonly_official_run, runtime_pin_verified
            try:
                item = admission(request.match_info['session_id'])
                if not item.get('materials') or not runtime_pin_verified(Path(api_server_runs.__file__).parent):
                    raise PermissionError('material_runtime_unverified')
                value = readonly_official_run(self._run_idempotency_store._db_path,
                    scope=self._run_idempotency_scope(request), key=item['materials']['key'],
                    fingerprint=item['materials']['fingerprint'], session_id=item['session_id'],
                    owner_alive=api_server_runs._owner_alive,execution=item['materials']['execution'])
                return web.json_response(value)
            except (ValueError,PermissionError,OSError,KeyError,TypeError):
                return web.json_response({'error':'material_lookup_unavailable'}, status=503)

        def _make_profile_prefix_middleware(self):
            @web.middleware
            async def approved_routes(request, handler):
                path = request.path
                allowed = ((request.method, path) in {('GET', '/v1/capabilities'), ('POST', '/v1/runs')} or
                           request.method == 'GET' and re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}', path) or
                           request.method == 'POST' and re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}/stop', path) or
                           request.method == 'GET' and re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}/events', path) or
                           request.method == 'POST' and re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}/steer', path) or
                           request.method == 'GET' and re.fullmatch(r'/v1/materials/mg_[a-f0-9]{64}', path))
                if not allowed:
                    return web.json_response({'error': 'route_denied'}, status=403)
                if (request.method, path) == ('POST', '/v1/runs'):
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {'input', 'session_id'} or not isinstance(body['input'], str):
                        return web.json_response({'error': 'request_fields'}, status=400)
                    try:
                        item = admission(body['session_id'])
                        if item.get('materials'):
                            from conversation_material_runs import official_fingerprint, runtime_pin_verified
                            if (not runtime_pin_verified(Path(api_server_runs.__file__).parent)
                                    or getattr(self._run_idempotency_store,'durable',False) is not True
                                    or request.headers.get('Idempotency-Key') != item['materials']['key']
                                    or official_fingerprint(body) != item['materials']['fingerprint']):
                                raise PermissionError('material_runtime_unverified')
                            inputs=getattr(self,'_material_admitted_inputs',None)
                            if inputs is None:self._material_admitted_inputs=inputs={}
                            inputs[body['session_id']]=body['input']
                    except (ValueError, PermissionError, OSError):
                        return web.json_response({'error': 'session_not_admitted'}, status=403)
                if path.endswith(('/events','/steer')):
                    run_id=request.match_info.get('run_id','')
                    status=self._durable_run_status(request,run_id)
                    session_id=status.get('session_id','') if status else ''
                    try:item=admission(session_id)
                    except (ValueError,PermissionError,OSError):
                        return web.json_response({'error':'conversation_run_not_admitted'},status=403)
                    if not session_id.startswith(('hc_','mg_')) or item.get('run_id')!=run_id or not item.get('ready'):
                        return web.json_response({'error':'conversation_run_not_bound'},status=403)
                    if session_id.startswith('mg_') and path.endswith('/steer'):
                        return web.json_response({'error':'material_intent_frozen'},status=403)
                response = await handler(request)
                if (request.method,path) == ('GET','/v1/capabilities') and response.status == 200:
                    from conversation_material_runs import runtime_pin_verified
                    value = json.loads(response.body)
                    value['fs_materials'] = {'verified_pin': runtime_pin_verified(Path(api_server_runs.__file__).parent)
                                             and getattr(self._run_idempotency_store,'durable',False) is True,
                                             'readonly_original_lookup': True, 'single_post': True}
                    return web.json_response(value)
                return response
            return approved_routes

        def _wire_plugin_handlers(self, app):
            pass  # No plugin HTTP extensions on this listener.

        def _create_agent(self, ephemeral_system_prompt=None, session_id=None, **kwargs):
            item = admission(session_id)
            material = bool(item.get('materials'))
            # Official Runs can start the worker before POST returns. FS must bind
            # the actual run_id durably before granting any tool/model access.
            if item.get('ready',True) is False:raise PermissionError('admission_handshake_timeout')
            from skill_bundle import load_bundle, prompt
            bundle={} if material or item.get('conversation') else item.get('frozen_skills') or load_bundle(Path(__file__).parent,question=skill_question(item),mode=item.get('report_mode'))
            task_prompt=item['prompt'] if material or item.get('conversation') else prompt(bundle,{'instruction':item['prompt']})
            if item.get('learning_text'):task_prompt+='\n'+item['learning_text']
            tool_names = {k:v for k,v in zip(SEMANTIC_TOOLS,WIRE_TOOLS) if not material or v in MATERIAL_WIRE_NAMES}
            task_prompt+='\n工具调用必须使用本次tools提供的完整函数名，不使用文档语义名或自行拼写。已注册语义名→实际函数名：'+json.dumps(tool_names,ensure_ascii=False)
            context_receipt=None
            if item.get('background') is not None:
                from background import task_context
                context_text,context_receipt=task_context(item['background'],bundle)
                if item.get('context_receipt')!=context_receipt:raise PermissionError('task_context_identity_changed')
                task_prompt=context_text+'\n'+task_prompt
            callbacks = {k: kwargs[k] for k in ('stream_delta_callback', 'tool_progress_callback',
                         'tool_start_callback', 'tool_complete_callback', 'interim_assistant_callback',
                         'reasoning_callback', 'status_callback') if k in kwargs}
            agent = AIAgent(base_url=PROXY+'/v1', api_key=item['token'], provider='custom',
                            api_mode='chat_completions', model=item['model'],
                            enabled_toolsets=['fs_materials' if material else 'fs_fc_readonly'], session_id=session_id,
                            ephemeral_system_prompt=task_prompt, platform='api_server',
                            skip_context_files=True, load_soul_identity=False, skip_memory=True,
                            skip_background_review=True, checkpoints_enabled=False,
                            fallback_model=None, quiet_mode=True, max_tokens=MAX_HERMES_OUTPUT_TOKENS,
                            reasoning_config={'enabled': False} if item.get('reasoning_effort','none')=='none' else {'enabled':True,'effort':item['reasoning_effort']},
                            session_db=self._ensure_session_db(), **callbacks)
            learning=item.get('learning_receipt')
            if learning:
                from agent.system_prompt import build_system_prompt
                import hashlib
                effective=(build_system_prompt(agent)+'\n\n'+agent.ephemeral_system_prompt).strip()
                expected=item['learning_text']
                if expected not in effective or hashlib.sha256(expected.encode()).hexdigest()!=learning['identity']['knowledge_sha256']:
                    agent.close();raise PermissionError('effective_business_memory_missing')
                effective_receipt={'status':'assembled_verified','knowledge_version':learning['version'],
                                   'knowledge_sha256':learning['identity']['knowledge_sha256'],
                                   'system_prompt_sha256':hashlib.sha256(effective.encode()).hexdigest(),
                                   'characters':len(effective),'knowledge_present':True,'native_memory_skipped':True,
                                   'memory_path':'explicit_frozen_business_snapshot'}
            from agent.context_compressor import ContextCompressor
            compressor = agent.context_compressor
            if getattr(compressor, '_config_context_length', None) != MAX_PROVIDER_CONTEXT_TOKENS:
                agent.close()
                raise PermissionError('context_window_configuration_mismatch')
            if not isinstance(compressor,ContextCompressor) or not all(hasattr(compressor,k) for k in (
                    'protect_first_n','protect_last_n','proactive_prune_tokens',
                    'proactive_prune_min_result_chars','proactive_prune_min_reclaim_tokens')):
                agent.close()
                raise PermissionError('unexpected_context_compressor')
            # Keep the pinned official compaction/pruning defaults.
            if set(agent.valid_tool_names) != set(MATERIAL_WIRE_NAMES if material else WIRE_TOOLS):
                observed_tools = sorted(agent.valid_tool_names)
                agent.close()
                raise PermissionError('unexpected_runtime_tools:'+','.join(observed_tools))
            agent._hermes_api_runtime = runtime_metadata(item,bundle)
            if material:
                from material_execution import build_context_proof,validate_execution
                from agent.system_prompt import build_system_prompt
                effective=(build_system_prompt(agent)+'\n\n'+agent.ephemeral_system_prompt).strip()
                from datetime import datetime,timezone
                fixed=validate_execution(item['materials']['execution'],now=datetime.now(timezone.utc))
                actual_input=getattr(self,'_material_admitted_inputs',{}).get(session_id)
                actual_tools=[v['function']['name'] for v in agent.tools]
                skipped=(getattr(agent,'skip_context_files',None) is True and getattr(agent,'load_soul_identity',None) is False
                         and getattr(agent,'skip_background_review',None) is True
                         and getattr(agent,'_memory_enabled',None) is False
                         and getattr(agent,'_memory_store',False) is None
                         and getattr(agent,'_memory_manager',False) is None)
                try:
                    proof=build_context_proof(fixed,session_id=session_id,run_id=item['run_id'],
                        actual_system_prompt=effective,actual_input=actual_input,actual_tool_names=actual_tools,
                        native_memory_skipped=skipped)
                except Exception:
                    agent.close();raise
                agent._hermes_api_runtime['fs_material_context']=proof
            if learning:agent._hermes_api_runtime['fs_effective_input']=effective_receipt
            if context_receipt:
                agent._hermes_api_runtime.update(fs_context_version=context_receipt['version'],fs_context_sha256=context_receipt['context_sha256'],
                                                fs_background_version=context_receipt['background_version'],fs_background_sha256=context_receipt['background_sha256'],
                                                fs_methods_sha256=context_receipt['methods_sha256'],fs_governance_sha256=context_receipt['governance_sha256'])
            return agent

    return ReadonlyAdapter(PlatformConfig(enabled=True, extra={
        'host': '127.0.0.1', 'port': 8941, 'key': api_key, 'model_name': 'deepseek-flash'}))


async def main():
    key = Path('/run/fs-hermes-fc/api-key').read_text('ascii').strip()
    adapter = make_adapter(key)
    if not await adapter.connect():
        raise RuntimeError('runtime_start_failed')
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    try:
        await stopped.wait()
    finally:
        await adapter.disconnect()


if __name__ == '__main__':
    asyncio.run(main())

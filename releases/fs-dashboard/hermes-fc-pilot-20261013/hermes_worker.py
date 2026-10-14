"""Constrained adapter around the pinned official Hermes Runs implementation.

FS registers five HTTP-backed tools through Hermes' official registry API. The
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

from proxy_gateway import schemas, MAX_PROVIDER_CONTEXT_TOKENS, MAX_HERMES_OUTPUT_TOKENS, MAX_PROVIDER_WIRE_BYTES
from runs_contract import WIRE_TOOLS, PIN


ADMISSIONS = Path('/run/fs-hermes-fc/admissions')
PROXY = 'http://127.0.0.1:8940'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def admission(session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r'fc_[a-f0-9]{64}', session_id):
        raise PermissionError('session_not_admitted')
    path = ADMISSIONS/(session_id+'.json')
    if path.is_symlink() or path.stat().st_size > MAX_PROVIDER_WIRE_BYTES:
        raise PermissionError('admission_invalid')
    item = json.loads(path.read_text('utf-8'))
    if not isinstance(item,dict) or set(item)-{'session_id', 'token', 'model', 'prompt','ready','reasoning_effort','background','context_receipt'} or not {'session_id','token','model','prompt'}.issubset(item) or item['session_id'] != session_id:
        raise PermissionError('admission_invalid')
    if ('background' in item)!=('context_receipt' in item) or any(not isinstance(item[n],dict) for n in ('background','context_receipt') if n in item):
        raise PermissionError('admission_context_invalid')
    if 'ready' in item and type(item['ready']) is not bool:
        raise PermissionError('admission_invalid')
    if item.get('reasoning_effort','none') not in ('none','low','high','max'):raise PermissionError('admission_reasoning')
    if item['model'] != 'deepseek-flash' or not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', item['token']):
        raise PermissionError('admission_invalid')
    if not isinstance(item['prompt'], str):
        raise PermissionError('admission_invalid')
    return item


def call_tool(name, args, *, session_id=None, parent_agent=None, **unused):
    session_id = getattr(parent_agent, 'session_id', None) or session_id
    item = admission(session_id)
    body = json.dumps({'name': name, 'arguments': args}).encode()
    request = Request(PROXY+'/fc/tools/call', body,
                      {'Authorization': 'Bearer '+item['token'], 'Content-Type': 'application/json'})
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        raw = response.read(MAX_PROVIDER_WIRE_BYTES+1)
    if len(raw) > MAX_PROVIDER_WIRE_BYTES:
        raise ValueError('tool_response_size')
    return json.dumps(json.loads(raw),ensure_ascii=False,separators=(',',':'),allow_nan=False)


def make_adapter(api_key):
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

    class ReadonlyAdapter(APIServerAdapter):
        _fs_handshake=True
        def _http_route_table(self):
            allowed = {('GET', '/v1/capabilities'), ('POST', '/v1/runs'),
                       ('GET', '/v1/runs/{run_id}'), ('POST', '/v1/runs/{run_id}/stop')}
            return [row for row in super()._http_route_table() if row[:2] in allowed]

        def _make_profile_prefix_middleware(self):
            @web.middleware
            async def approved_routes(request, handler):
                path = request.path
                allowed = ((request.method, path) in {('GET', '/v1/capabilities'), ('POST', '/v1/runs')} or
                           request.method == 'GET' and re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}', path) or
                           request.method == 'POST' and re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}/stop', path))
                if not allowed:
                    return web.json_response({'error': 'route_denied'}, status=403)
                if (request.method, path) == ('POST', '/v1/runs'):
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {'input', 'session_id'} or not isinstance(body['input'], str):
                        return web.json_response({'error': 'request_fields'}, status=400)
                    try:
                        admission(body['session_id'])
                    except (ValueError, PermissionError, OSError):
                        return web.json_response({'error': 'session_not_admitted'}, status=403)
                return await handler(request)
            return approved_routes

        def _wire_plugin_handlers(self, app):
            pass  # No plugin HTTP extensions on this listener.

        def _create_agent(self, ephemeral_system_prompt=None, session_id=None, **kwargs):
            item = admission(session_id)
            # Official Runs can start the worker before POST returns. FS must bind
            # the actual run_id durably before granting any tool/model access.
            if item.get('ready',True) is False:raise PermissionError('admission_handshake_timeout')
            from skill_bundle import load_bundle, prompt
            bundle=load_bundle(Path(__file__).parent)
            task_prompt=prompt(bundle,{'instruction':item['prompt']})
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
                            enabled_toolsets=['fs_fc_readonly'], session_id=session_id,
                            ephemeral_system_prompt=task_prompt, platform='api_server',
                            skip_context_files=True, load_soul_identity=False, skip_memory=True,
                            skip_background_review=True, checkpoints_enabled=False,
                            fallback_model=None, quiet_mode=True, max_tokens=MAX_HERMES_OUTPUT_TOKENS,
                            reasoning_config={'enabled': False} if item.get('reasoning_effort','none')=='none' else {'enabled':True,'effort':item['reasoning_effort']},
                            session_db=self._ensure_session_db(), **callbacks)
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
            if set(agent.valid_tool_names) != set(WIRE_TOOLS):
                observed_tools = sorted(agent.valid_tool_names)
                agent.close()
                raise PermissionError('unexpected_runtime_tools:'+','.join(observed_tools))
            agent._hermes_api_runtime = {'provider': 'custom', 'model': item['model'], 'route_source': 'fs_task_admission',
                                        'fs_skill_version':bundle['version'],'fs_skill_sha256':bundle['sha256'],
                                        'fs_reasoning_effort':item.get('reasoning_effort','none')}
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

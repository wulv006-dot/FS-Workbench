"""Constrained adapter around the pinned official Hermes Runs implementation.

FS registers approved HTTP-backed tools through Hermes' official registry API. The
wire names retain the v1 contract; this adapter does not claim an MCP connection.
Provider credentials never enter this process. Admissions are FS-owned read-only
files containing a renewable task token, model name, and approved task context.
"""
import asyncio
from contextvars import ContextVar
import json
from pathlib import Path
import re
import signal
import time
from threading import RLock
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

from proxy_gateway import schemas, MAX_PROVIDER_CONTEXT_TOKENS, MAX_HERMES_OUTPUT_TOKENS, MAX_PROVIDER_WIRE_BYTES
from runs_contract import WIRE_TOOLS, SEMANTIC_TOOLS, PIN


ADMISSIONS = Path('/run/fs-hermes-fc/admissions')
PROXY = 'http://127.0.0.1:8940'
_MATERIAL_RUN = ContextVar('fs_material_diagnostic_run', default=None)
_MATERIAL_EXCEPTIONS = {cls: cls.__name__ for cls in (
    ValueError, TypeError, AttributeError, KeyError, RuntimeError, OSError,
    PermissionError, TimeoutError, ConnectionError, ImportError, asyncio.CancelledError)}
_MATERIAL_REASONS = frozenset({'max_iterations', 'interrupted', 'cancelled'})
_MATERIAL_PHASES = frozenset({'admission_wait', 'executor', 'agent_create', 'agent_ready',
                              'agent_worker', 'agent_returned'})


def _material_snapshot(value):
    if (type(value) is not dict or set(value) != {'version', 'phase', 'exception_class', 'reason'}
            or type(value['version']) is not str or value['version'] != 'materials_diagnostic_v1'):
        return None
    allowed = {'phase': _MATERIAL_PHASES,
               'exception_class': set(_MATERIAL_EXCEPTIONS.values()) | {'unknown', 'other_exception'},
               'reason': _MATERIAL_REASONS | {'unknown'}}
    if all(type(value[key]) is str and value[key] in options for key, options in allowed.items()):
        return dict(value)
    return None


def _material_note(adapter, run_id, *, phase=None, error=None, reason=None):
    # Only trusted wrapper call sites supply phases; never inspect exception text.
    with adapter._material_diagnostic_lock:
        previous = adapter._material_diagnostics.get(run_id)
        if previous is None:
            return  # Terminal cleanup cannot be undone by a late worker callback.
        note = dict(previous)
        if type(phase) is str and phase in _MATERIAL_PHASES:
            note['phase'] = phase
        if error is not None:
            note['exception_class'] = next((name for cls, name in _MATERIAL_EXCEPTIONS.items()
                                             if type(error) is cls), 'other_exception')
        if reason is not None:
            note['reason'] = reason if type(reason) is str and reason in _MATERIAL_REASONS else 'unknown'
        adapter._material_diagnostics[run_id] = note


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
    if not isinstance(item,dict) or set(item)-{'session_id', 'token', 'model', 'prompt','ready','reasoning_effort','background','context_receipt','report_mode','skill_question','frozen_skills','learning_receipt','learning_text','conversation','run_id','materials','native_chat'} or not {'session_id','token','model','prompt'}.issubset(item) or item['session_id'] != session_id:
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
    if 'native_chat' in item:
        if not session_id.startswith('hc_') or any(key in item for key in ('materials','frozen_skills','learning_text','background')):
            raise PermissionError('native_admission_invalid')
        from conversation_native import validate_native_admission
        validate_native_admission(item)
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


def install_native_compaction_relay(agent, binding, effort, check, relay):
    """Confirm only an adopted, normally returned official SDK compaction."""
    from copy import deepcopy
    from functools import wraps
    attempt_context=ContextVar('fs_native_compaction_attempt',default=None)
    lock=RLock();state={'attempt':None,'pending':None}
    original_compress=agent._compress_context;original_build=agent._build_api_kwargs
    original_event=getattr(agent,'event_callback',None)
    fixed=deepcopy(binding)

    def event(name,payload):
        attempt=attempt_context.get()
        if name=='session:compress' and attempt is not None and type(payload) is dict:
            with lock:
                if attempt['active'] and state['attempt'] is attempt:
                    attempt['events'].append(deepcopy(payload))
        if callable(original_event):return original_event(name,payload)

    @wraps(original_compress)
    def compress(messages,*args,**kwargs):
        check();before=deepcopy(messages)
        count=agent.context_compressor.compression_count
        attempt={'active':True,'events':[],'session':agent.session_id,'count':count}
        with lock:state['attempt']=attempt
        token=attempt_context.set(attempt)
        try:
            result=original_compress(messages,*args,**kwargs)
            with lock:
                sid=attempt['session'];previous=count;valid=type(count) is int
                for item in attempt['events']:
                    now=item.get('compression_count');child=item.get('session_id')
                    valid=valid and (set(item)=={'platform','session_id','old_session_id','in_place','compression_count'} and
                        item['platform']==agent.platform and item['old_session_id']==sid and
                        type(item['in_place']) is bool and type(child) is str and bool(child) and
                        (not item['in_place'] or child==sid) and type(now) is int and now>previous)
                    sid=child;previous=now
                actual=agent.context_compressor.compression_count
                confirmed=(state['attempt'] is attempt and valid and attempt['events'] and
                        type(actual) is int and actual>count and previous==actual and sid==agent.session_id and
                        type(result) is tuple and len(result)==2 and type(result[0]) is list and result[0]!=before)
            if confirmed:
                check()
                with lock:
                    if state['attempt'] is attempt:state['pending']=(actual,sid)
            return result
        finally:
            with lock:attempt['active']=False
            attempt_context.reset(token)

    @wraps(original_build)
    def build(*args,**kwargs):
        result=original_build(*args,**kwargs)
        # Summarization inside the compression attempt is not its adopted request.
        if attempt_context.get() is not None:return result
        with lock:
            pending=None if state['attempt'] is not None and state['attempt']['active'] else state['pending']
        if pending is not None:
            from agent.message_sanitization import sanitize_outbound_kwargs
            from native_chat import native_messages_sha256
            check()
            if agent.session_id!=pending[1]:raise PermissionError('native_compaction_session_changed')
            sanitize_outbound_kwargs(agent,result)
            value={'binding':fixed,'compression_count':pending[0],
                   'messages_sha256':native_messages_sha256(result,reasoning_effort=effort)}
            receipt=relay(value)
            if (type(receipt) is not dict or receipt.get('registered') is not True or
                    receipt.get('compression_count')!=pending[0]):
                raise PermissionError('native_compaction_not_registered')
            check()
            with lock:
                if state['pending'] is pending:state['pending']=None
        return result

    agent.event_callback=event
    agent._compress_context=compress
    agent._build_api_kwargs=build


def make_adapter(api_key):
    from hermes_cli import env_loader
    env_loader.load_hermes_dotenv = _fs_no_implicit_dotenv
    from hermes_cli import config as hermes_config
    # FS owns this config; Desktop keeps the shared home and its own config.yaml.
    def fs_config_path():
        from conversation_native import current_native_profile
        if current_native_profile() is not None:
            from hermes_constants import get_hermes_home
            return get_hermes_home() / 'config.yaml'
        return Path(__file__).with_name('runtime-config.yaml')
    hermes_config.get_config_path = fs_config_path
    from aiohttp import web
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.platforms import api_server_runs
    from tools.registry import registry
    from toolsets import create_custom_toolset
    from run_agent import AIAgent

    # Pinned api_server_runs.py:781-847 calls this synchronous boundary and
    # returns (result, usage, runtime). The official executor still owns catch/
    # status/cleanup; diagnostics neither stringify errors nor replace results.
    if not getattr(api_server_runs._run_agent_sync, '_fs_material_diagnostic', False):
        original_sync = api_server_runs._run_agent_sync
        def material_agent_sync(adapter, run, agent, approval_notify, *, _api_server):
            if not getattr(adapter, '_fs_handshake', False):
                return original_sync(adapter, run, agent, approval_notify, _api_server=_api_server)
            with adapter._material_diagnostic_lock:
                observed = run.run_id in adapter._material_diagnostics
            if not observed:
                return original_sync(adapter, run, agent, approval_notify, _api_server=_api_server)
            _material_note(adapter, run.run_id, phase='agent_worker')
            try:
                result = original_sync(adapter, run, agent, approval_notify, _api_server=_api_server)
            except BaseException as error:
                _material_note(adapter, run.run_id, error=error)
                raise
            reason = 'unknown'
            if type(result) is tuple and result and type(result[0]) is dict and result[0].get('failed') is True:
                reason = result[0].get('turn_exit_reason', result[0].get('reason'))
            _material_note(adapter, run.run_id, phase='agent_returned', reason=reason)
            return result
        material_agent_sync._fs_material_diagnostic = True
        api_server_runs._run_agent_sync = material_agent_sync

    # Pinned Runs calls _create_agent on its event loop before starting the
    # executor. Wait cooperatively here so its HTTP202 can actually be flushed.
    # Retain the official executor for terminal state, cancellation and cleanup.
    if not getattr(api_server_runs._execute_run,'_fs_async_gate',False):
        original_executor=api_server_runs._execute_run
        async def admitted_executor(adapter,run,*,_api_server):
            material = (getattr(adapter, '_fs_handshake', False) and
                        isinstance(run.session_id, str) and re.fullmatch('mg_[a-f0-9]{64}', run.session_id))
            token = None
            if material:
                with adapter._material_diagnostic_lock:
                    adapter._material_diagnostics[run.run_id] = {
                        'version': 'materials_diagnostic_v1', 'phase': 'admission_wait',
                        'exception_class': 'unknown', 'reason': 'unknown'}
                token = _MATERIAL_RUN.set((adapter, run.run_id))
            try:
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
                if material:
                    _material_note(adapter, run.run_id, phase='executor')
                return await original_executor(adapter,run,_api_server=_api_server)
            except BaseException as error:
                if material:
                    _material_note(adapter, run.run_id, error=error)
                raise
            finally:
                if material:
                    with adapter._material_diagnostic_lock:
                        adapter._material_diagnostics.pop(run.run_id, None)
                    _MATERIAL_RUN.reset(token)
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
        def __init__(self, *args, **kwargs):
            self._material_diagnostics = {}
            self._material_diagnostic_lock = RLock()
            super().__init__(*args, **kwargs)

        def _set_run_status(self,run_id,status,**fields):
            # Pinned official Runs emits only provider/model. Preserve the actual
            # constructed agent's verified FS context receipt in its pollable record.
            loaded=loaded_context_metadata(self._active_run_agents.get(run_id))
            if loaded:fields['runtime']={**(fields.get('runtime') or {}),**loaded}
            terminal = status in {'completed','failed','cancelled','interrupted'}
            try:
                with self._material_diagnostic_lock:
                    note = self._material_diagnostics.get(run_id)
                    if note is None:
                        # Keep an already-persisted bounded terminal receipt when
                        # a late SDK status update also carries context metadata.
                        previous = self._run_statuses.get(run_id, {}).get('runtime') or {}
                        note = _material_snapshot(previous.get('fs_material_diagnostic'))
                    if note is not None:
                        fields['runtime'] = {**(fields.get('runtime') or {}), 'fs_material_diagnostic': dict(note)}
                result=super()._set_run_status(run_id,status,**fields)
            finally:
                if terminal:
                    with self._material_diagnostic_lock:
                        self._material_diagnostics.pop(run_id, None)
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
            routes.append(('GET', '/v1/native/{session_id}', self._native_lookup))
            return routes

        async def _native_lookup(self, request):
            denied = self._check_auth(request)
            if denied is not None:
                return denied
            from conversation_native import readonly_native_run
            from conversation_material_runs import runtime_pin_verified
            try:
                item = admission(request.match_info['session_id'])
                if not item.get('native_chat') or not runtime_pin_verified(Path(api_server_runs.__file__).parent):
                    raise PermissionError('native_runtime_unverified')
                native = item['native_chat']
                return web.json_response(readonly_native_run(self._run_idempotency_store._db_path,
                    scope=self._run_idempotency_scope(request),key=native['key'],fingerprint=native['fingerprint'],
                    session_id=item['session_id'],owner_alive=api_server_runs._owner_alive))
            except (ValueError,PermissionError,OSError,KeyError,TypeError):
                return web.json_response({'error':'native_lookup_unavailable'},status=503)

        async def _conversation_history_for_session(self, session_id):
            item = admission(session_id)
            if item.get('native_chat'):
                from conversation_native import native_owner_scope
                with native_owner_scope(item):
                    return await super()._conversation_history_for_session(session_id)
            return await super()._conversation_history_for_session(session_id)

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
                           request.method == 'GET' and re.fullmatch(r'/v1/materials/mg_[a-f0-9]{64}', path) or
                           request.method == 'GET' and re.fullmatch(r'/v1/native/hc_[a-f0-9]{64}', path))
                if not allowed:
                    return web.json_response({'error': 'route_denied'}, status=403)
                if (request.method, path) == ('POST', '/v1/runs'):
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {'input', 'session_id'} or not isinstance(body['input'], str):
                        return web.json_response({'error': 'request_fields'}, status=400)
                    try:
                        item = admission(body['session_id'])
                        if item.get('native_chat'):
                            from conversation_material_runs import official_fingerprint,runtime_pin_verified
                            if (not runtime_pin_verified(Path(api_server_runs.__file__).parent) or
                                    getattr(self._run_idempotency_store,'durable',False) is not True or
                                    request.headers.get('Idempotency-Key') != item['native_chat']['key'] or
                                    official_fingerprint(body) != item['native_chat']['fingerprint']):
                                raise PermissionError('native_runtime_unverified')
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
                if (request.method,path) == ('POST','/v1/runs') and item.get('native_chat'):
                    from conversation_native import native_owner_scope
                    with native_owner_scope(item):
                        response = await handler(request)
                else:
                    response = await handler(request)
                if (request.method,path) == ('GET','/v1/capabilities') and response.status == 200:
                    from conversation_material_runs import runtime_pin_verified
                    value = json.loads(response.body)
                    value['fs_materials'] = {'verified_pin': runtime_pin_verified(Path(api_server_runs.__file__).parent)
                                             and getattr(self._run_idempotency_store,'durable',False) is True,
                                             'readonly_original_lookup': True, 'single_post': True}
                    value['fs_native_chat'] = {'version':'native_chat_v1','single_post':True,
                                               'readonly_original_lookup':True,'schema_relay':True}
                    return web.json_response(value)
                return response
            return approved_routes

        def _wire_plugin_handlers(self, app):
            pass  # No plugin HTTP extensions on this listener.

        def _create_agent(self, ephemeral_system_prompt=None, session_id=None, **kwargs):
            scope = _MATERIAL_RUN.get()
            if scope is None or scope[0] is not self:
                return self._create_admitted_agent(ephemeral_system_prompt, session_id, **kwargs)
            _material_note(self, scope[1], phase='agent_create')
            try:
                agent = self._create_admitted_agent(ephemeral_system_prompt, session_id, **kwargs)
            except BaseException as error:
                _material_note(self, scope[1], error=error)
                raise
            _material_note(self, scope[1], phase='agent_ready')
            return agent

        def _create_admitted_agent(self, ephemeral_system_prompt=None, session_id=None, **kwargs):
            item = admission(session_id)
            if item.get('native_chat'):
                return self._create_native_agent(item, **kwargs)
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

        def _create_native_agent(self, item, **kwargs):
            import functools
            import hashlib
            import model_tools
            from run_agent import AIAgent
            from hermes_cli.tools_config import _get_platform_tools
            from conversation_native import (NativeDockerBackend, install_native_backend_guards, canonical, validate_native_profile)
            install_native_backend_guards()
            fixed = item['native_chat']['binding']
            def active():
                current = admission(fixed['session_id'])
                if not (current.get('ready') is True and current.get('run_id') == fixed['run_id'] and
                        current.get('native_chat', {}).get('binding') == fixed):
                    return False
                checked = json.loads(call_tool('fs.native.check', {'binding': fixed},session_id=fixed['session_id']))
                return checked.get('authorized') is True
            backend = NativeDockerBackend(item, active)
            backend.data_call=lambda name,args:json.loads(call_tool('fs.native.user_data',
                {'binding':fixed,'name':name,'arguments':args},session_id=fixed['session_id']))
            backend.read_call=lambda path,params:json.loads(call_tool('fs.native.read',
                {'binding':fixed,'path':path,'params':params},session_id=fixed['session_id']))
            with backend.scope():
                config = validate_native_profile(hermes_config.load_config(),backend.profile)
                backend.ensure_environment()
                from tools.registry import registry
                from fs_native_readonly import register_scope
                register_scope(registry,str(backend.profile))
                from hermes_constants import resolve_reasoning_config
                reasoning = resolve_reasoning_config(config,item['model'])
                enabled = sorted(set(_get_platform_tools(config, 'api_server')) | {'fs_readonly'})
                callbacks = {key: kwargs[key] for key in ('stream_delta_callback','tool_progress_callback',
                    'tool_start_callback','tool_complete_callback','interim_assistant_callback','reasoning_callback',
                    'status_callback','event_callback') if key in kwargs}
                def pending(call_id, name, arguments, result):
                    backend.observe_pending(name, result, lambda value: call_tool(
                        'fs.native.pending_source', value, session_id=fixed['session_id']))
                    return None
                files = item['native_chat']['environment']['files']
                session_db=self._ensure_session_db()
                if session_db is None:
                    raise OSError('native_session_history_unavailable')
                prompt = ('Attachments in this conversation are available in /workspace. '
                          'Use the native tools as needed; save generated files in /workspace.\n' + canonical(files))
                agent = AIAgent(base_url=PROXY+'/v1', api_key=item['token'], provider='custom',
                    api_mode='chat_completions', model=item['model'], enabled_toolsets=enabled,
                    disabled_toolsets=['fs_materials','fs_fc_readonly'], session_id=fixed['session_id'],
                    cwd=backend.environment['workspace'], ephemeral_system_prompt=prompt, platform='api_server',
                    skip_context_files=False, load_soul_identity=True, skip_memory=False,
                    skip_background_review=False, fallback_model=None, quiet_mode=True,
                    max_tokens=MAX_HERMES_OUTPUT_TOKENS, reasoning_config=reasoning,
                    session_db=session_db, tool_result_metadata_callback=pending, **callbacks)
                raw = model_tools.get_tool_definitions(enabled_toolsets=agent.enabled_toolsets,
                    disabled_toolsets=agent.disabled_toolsets,quiet_mode=True,skip_tool_search_assembly=True)
                from agent.reasoning_params import unset_reasoning_default
                effective_reasoning=reasoning if reasoning is not None else unset_reasoning_default(agent)
                effort=('none' if effective_reasoning and effective_reasoning.get('enabled') is False else
                        (effective_reasoning or {}).get('effort','medium'))
                measured = {'reasoning_effort':effort, 'binding': fixed, 'model_schemas': agent.tools,
                            'catalog_sha256': hashlib.sha256(canonical(raw).encode()).hexdigest(),
                            'registry_generation': agent._tool_snapshot_generation}
                try:
                    receipt = json.loads(call_tool('fs.native.register_schemas', measured, session_id=fixed['session_id']))
                    if receipt.get('registered') is not True:
                        raise PermissionError('native_schema_not_registered')
                except BaseException:
                    agent.close()
                    raise
                install_native_compaction_relay(agent,fixed,effort,backend.check,lambda value:json.loads(call_tool(
                    'fs.native.compacted_request',value,session_id=fixed['session_id'])))
            original_run = agent.run_conversation
            @functools.wraps(original_run)
            def run(*args, **run_kwargs):
                with backend.scope():
                    # History keeps its cid session. Official tool/cache state
                    # is turn-scoped so a stopped writer cannot reach its successor.
                    if len(args)>3:
                        args=(*args[:3],fixed['turn_id'],*args[4:])
                        run_kwargs.pop('task_id',None)
                    else:run_kwargs['task_id']=fixed['turn_id']
                    return original_run(*args, **run_kwargs)
            agent.run_conversation = run
            original_close = agent.close
            @functools.wraps(original_close)
            def close():
                # Cleanup still needs the owner's environment-cache key after
                # terminal state/revocation. It grants no new model/tool work.
                with backend.scope(check=False):
                    try:return original_close()
                    finally:backend.close_environment()
            agent.close = close
            agent._hermes_api_runtime = {'provider':'custom','model':item['model'],'route_source':'fs_native_conversation',
                'fs_native_catalog_sha256':measured['catalog_sha256'],
                'fs_native_model_schema_sha256':hashlib.sha256(canonical(agent.tools).encode()).hexdigest()}
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

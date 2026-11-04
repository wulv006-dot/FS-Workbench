"""Bounded original SDK function bodies; no SDK import or provider execution.

The historical replay input is empty; plugins, image policy and token-pressure
estimators are explicit boundary fixtures. Actual text sanitizer, tool pairing,
ID/name normalization, canonicalization, outer assembly order and outbound
surrogate sanitizer execute unchanged pinned functions.
"""
import ast
import contextlib
import copy
from dataclasses import dataclass
from functools import partial
import json
import logging
from pathlib import Path
import re
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

_fixture=Path(__file__).parent/'fixtures/native_aad_consumer_sdk_71d34bad.py'
SOURCES=ast.literal_eval(next(n.value for n in ast.parse(_fixture.read_text(encoding='utf-8')).body if isinstance(n,ast.Assign)))
NEW=OLD=Path('pinned_sdk/agent')

def read_source(path):return SOURCES[Path(path).name]
USED=[]

def metadata_constants():
    values={}
    archive=ast.parse(read_source(NEW/'conversation_compression_archive.py'))
    for node in archive.body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('MERGED_DURABLE_ROWS','RETIRED_DURABLE_ROWS','UNNAMED_DURABLE_ROWS'):
                    values[target.id]=ast.literal_eval(node.value)
    for node in ast.parse(read_source(NEW/'message_metadata.py')).body:
        if isinstance(node,ast.AnnAssign) and node.value is not None:node=ast.Assign(targets=[node.target],value=node.value)
        if not isinstance(node,ast.Assign):continue
        try:value=ast.literal_eval(node.value)
        except (ValueError,TypeError):
            calls=[n for n in ast.walk(node.value) if isinstance(n,ast.Call)]
            if any(not isinstance(c.func,ast.Name) or c.func.id!='frozenset' for c in calls):continue
            try:value=eval(compile(ast.Expression(node.value),'<fixed-message-metadata>','eval'),{'frozenset':frozenset,**values})
            except (NameError,TypeError):continue
        for target in node.targets:
            if isinstance(target,ast.Name):values[target.id]=value
    return values

def functions(path,roots,namespace=None):
    source=read_source(path);tree=ast.parse(source)
    defs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    selected=set(roots);before=None
    while before!=selected:
        before=selected.copy()
        for name in before:
            selected.update(n.id for n in ast.walk(defs[name]) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id in defs)
    ns=dict(json=json,re=re,copy=copy,contextlib=contextlib,partial=partial,logger=logging.getLogger('fixed-sdk'),__name__=__name__)
    ns.update(namespace or {})
    for node in tree.body:
        if isinstance(node,ast.Assign):
            try:value=ast.literal_eval(node.value)
            except (ValueError,TypeError):continue
            if any(isinstance(target,(ast.Tuple,ast.List)) for target in node.targets):
                exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),ns)
            for target in node.targets:
                if isinstance(target,ast.Name):ns.setdefault(target.id,value)
    nodes=[defs[name] for name in sorted(selected)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])),str(path),'exec'),ns)
    wanted={n.id for node in nodes for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)} | set(roots)
    if path.name=='message_sanitization.py':wanted.update({'_sanitize_messages_surrogates','_sanitize_structure_surrogates'})
    for node in tree.body:
        if isinstance(node,ast.AnnAssign) and node.value is not None:
            node=ast.Assign(targets=[node.target],value=node.value)
        if not isinstance(node,ast.Assign) or not any(isinstance(t,ast.Name) and t.id in wanted for t in node.targets):continue
        try:value=ast.literal_eval(node.value)
        except (ValueError,TypeError):
            if not isinstance(node.value,ast.Call):continue
            fn=node.value.func
            safe=(isinstance(fn,ast.Name) and fn.id in ('partial','frozenset','object')) or (isinstance(fn,ast.Attribute) and isinstance(fn.value,ast.Name) and fn.value.id=='re' and fn.attr=='compile')
            if not safe:continue
            try:value=eval(compile(ast.Expression(node.value),str(path),'eval'),ns)
            except NameError:continue
        for target in node.targets:
            if isinstance(target,ast.Name):ns[target.id]=value
    USED.extend((str(path),name) for name in sorted(selected))
    return ns

def build_wire(messages,tools):
    metadata=metadata_constants()
    msg=functions(NEW/'message_sanitization.py',[
        'coalesce_tool_call_id','coerce_tool_name','tool_call_id_variants','tool_result_id_variants',
        '_sanitize_messages','_sanitize_structure','_sanitize_surrogates','sanitize_outbound_kwargs',
        'apply_reasoning_content_policy'],dict(DB_ROW_SNAPSHOT=metadata['DB_ROW_SNAPSHOT']))
    helper=functions(NEW/'agent_runtime_helpers.py',[
        'sanitize_api_messages','drop_thinking_only_and_merge_users','fill_empty_non_final_wire_payload',
        'copy_reasoning_content_for_api'],
        {k:msg[k] for k in ['coalesce_tool_call_id','coerce_tool_name','tool_call_id_variants','tool_result_id_variants']})
    # Real AIAgent static ID/name/thinking helpers. Tool-carrying assistant rows
    # short-circuit the thinking helper before non-used native compaction imports.
    source=read_source(OLD.parent/'run_agent.py')
    agent_def=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='AIAgent')
    names={'_get_tool_call_name_static','_is_thinking_only_assistant'}
    nodes=[copy.deepcopy(n) for n in agent_def.body if isinstance(n,ast.FunctionDef) and n.name in names]
    for node in nodes:node.decorator_list=[]
    ns={'__name__':__name__}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])),str(OLD.parent/'run_agent.py'),'exec'),ns)
    cls=SimpleNamespace(_VALID_API_ROLES=frozenset({'system','user','assistant','tool','function','developer'}),
        _get_tool_call_id_static=msg['coalesce_tool_call_id'],**{name:ns[name] for name in names})
    ns['AIAgent']=cls
    ra=ModuleType('run_agent');ra.AIAgent=cls;ra.logger=logging.getLogger('fixed-sdk')
    canon=functions(OLD/'conversation_loop.py',['_canonicalize_tool_call_arguments','_canonicalize_api_tool_calls','_clone_message_for_send'],
        dict(_CANON_ARGS_CACHE={},_canon_args_cache_bytes=0,_CANON_ARGS_CACHE_MAX=4096,_CANON_ARGS_CACHE_MAX_BYTES=1024*1024))
    def identity_context(agent,api,history,incoming,**kwargs):return api
    context=functions(NEW/'turn_context.py',['build_api_messages'],
        dict(PERSISTENCE_ONLY_MESSAGE_FIELDS=metadata['PERSISTENCE_ONLY_MESSAGE_FIELDS']))
    replay=functions(NEW/'replay_cleanup.py',['canonicalize_replay_history'])
    def image_none(api):
        assert all(not isinstance(m.get('content'),list) for m in api)
        return 0
    agent=SimpleNamespace(tools=tools,prefill_messages=[],_use_prompt_caching=False,provider='custom',api_mode='chat_completions',
        context_compressor=None,_force_ascii_payload=False,_usage_anchor=None,
        _current_turn_timestamp=0,ephemeral_system_prompt='',
        _reasoning_replay_route=lambda:(False,frozenset()),_should_sanitize_tool_calls=lambda:False,
        _sanitize_api_messages=helper['sanitize_api_messages'],
        _drop_thinking_only_and_merge_users=helper['drop_thinking_only_and_merge_users'])
    agent._copy_reasoning_content_for_api=helper['copy_reasoning_content_for_api'].__get__(agent)
    deps={
      'run_agent':ra,
      'agent.conversation_loop':SimpleNamespace(_CODEX_INCOMPLETE_NUDGE='synthetic-unused-nudge',
          _apply_context_engine_selection=identity_context,_canonicalize_api_tool_calls=canon['_canonicalize_api_tool_calls'],
          _clone_message_for_send=canon['_clone_message_for_send'],_midturn_request_pressure_tokens=lambda *a:1,_pressure_with_real_floor=lambda a,b:b),
      'agent.model_metadata':SimpleNamespace(estimate_messages_tokens_rough=lambda *a,**k:1,estimate_native_anthropic_messages_tokens_rough=lambda *a,**k:1),
      'agent.turn_context':SimpleNamespace(_agent_stale_thinking_on_wire=lambda a:False),
      'agent.replay_cleanup':SimpleNamespace(canonicalize_replay_history=replay['canonicalize_replay_history']),
      'agent.message_sanitization':SimpleNamespace(apply_reasoning_content_policy=msg['apply_reasoning_content_policy']),
      'agent.anthropic_thinking_replay':SimpleNamespace(apply_rejected_thinking_suppression=lambda *a:None),
      'agent.context_compressor':SimpleNamespace(evict_stale_outbound_tool_images=image_none,
          _DB_PERSISTED_MARKER=next(ast.literal_eval(n.value) for n in ast.parse(read_source(OLD/'context_compressor.py')).body
              if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_DB_PERSISTED_MARKER' for t in n.targets))),
      'agent.agent_runtime_helpers':SimpleNamespace(consume_pending_sanitizer_heal_notice=lambda:None,
          fill_empty_non_final_wire_payload=helper['fill_empty_non_final_wire_payload'])}
    assembly=functions(OLD/'turn_request_assembly.py',['assemble_api_request'],
        dict(build_api_messages=context['build_api_messages'],_sanitize_messages_surrogates=msg['_sanitize_messages_surrogates'],
             anchored_context_tokens=lambda *a:None))
    # Actual result dataclass, not a substitute assembly implementation.
    source=read_source(OLD/'turn_request_assembly.py')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='AssembledRequest')
    assembly['dataclass']=dataclass
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])),str(OLD/'turn_request_assembly.py'),'exec'),assembly)
    with patch.dict('sys.modules',deps):
        result=assembly['assemble_api_request'](agent,messages=messages,current_turn_user_idx=0,
            _ext_prefetch_cache=None,_plugin_user_context=None,moa_config=None,active_system_prompt='',
            original_user_message='synthetic',pending_moa_prepared_request=None,request_logger=logging.getLogger('fixed-sdk'))
        kwargs=dict(messages=result.api_messages,tools=result.tools_for_api)
        msg['sanitize_outbound_kwargs'](agent,kwargs)
    assert kwargs['tools']==tools
    return kwargs['messages']

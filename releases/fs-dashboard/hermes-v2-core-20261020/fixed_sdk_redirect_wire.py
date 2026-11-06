"""Original redirect/restart/iteration -> SDK assembly -> actual FS Proxy/SQLite.

No SDK process, real HTTP, credentials, production data, or product edits.
Only streaming middleware/delivery, SessionDB persistence and OS slot are fixtures.
"""
import ast
import contextlib
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import patch

CORE = Path(__file__).resolve().parent
PUBLIC = OWN_PUBLIC = HERE = Path('pinned_sdk')
_fixture = CORE / 'fixtures/native_redirect_sdk_71d34bad.py'
SOURCES = ast.literal_eval(next(n.value for n in ast.parse(_fixture.read_text(encoding='utf-8')).body
    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCES' for t in n.targets)))
from test_native_chat import NativeToolHistory
import fixed_sdk_aad_wire as sdk_wire

def read_source(path):
    return SOURCES[Path(path).name]

used = []

def original(path, names, ns):
    raw = read_source(path)
    nodes = [deepcopy(n) for n in ast.parse(raw).body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), ns)
    used.append(dict(path=str(path), sha256=hashlib.sha256(read_source(path).encode()).hexdigest(), names=sorted(names)))

def pure_module(path, name):
    module = ModuleType(name)
    exec(compile(read_source(path), str(path), 'exec'), module.__dict__)
    return module


def run_case(visible, *, more_tools=False, after_adopted=False, reused_ids=False):
    rep = pure_module(HERE / 'repetition_guard.py', 'isolated_repetition_guard')
    placeholders = pure_module(HERE / 'agent_runtime_helpers_placeholders.py', 'isolated_interrupt_placeholders')
    ns = dict(__name__=__name__, dataclass=dataclass, field=field, logger=logging.getLogger('isolated'),
              nullcontext=contextlib.nullcontext, stop_thinking_spinner=lambda *a: None,
              _should_stream=lambda agent: True, wall_time=time.time,
              is_runaway_repetition=rep.is_runaway_repetition,
              REPETITION_LOOP_INTERRUPTED=rep.REPETITION_LOOP_INTERRUPTED,
              hidden_interrupt_placeholder_row=placeholders.hidden_interrupt_placeholder_row)
    original(OWN_PUBLIC / 'agent/message_metadata.py', ['stamp_message_timestamp', 'append_message'], ns)
    loop = PUBLIC / 'agent/conversation_loop.py'
    source = ast.parse(read_source(loop))
    ns['_INTERRUPT_SCAFFOLD_MARKER'] = next(ast.literal_eval(n.value) for n in source.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_INTERRUPT_SCAFFOLD_MARKER' for t in n.targets))
    original(loop, ['_apply_active_turn_redirect', '_review_input_budget_exhausted'], ns)
    original(PUBLIC / 'agent/turn_api_call.py', ['ApiCallVerdict', 'perform_api_call'], ns)
    original(HERE / 'turn_iteration_prep.py', ['RetryRestartVerdict', 'IterationStart', 'apply_retry_restarts', 'begin_iteration'], ns)
    run_source = read_source(PUBLIC / 'run_agent.py')
    payload_method = deepcopy(next(n for n in ast.walk(ast.parse(run_source))
        if isinstance(n, ast.FunctionDef) and n.name == '_content_has_real_payload'))
    payload_method.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',
        names=[ast.alias(name='annotations')], level=0), payload_method], type_ignores=[])),
        str(PUBLIC / 'run_agent.py'), 'exec'), ns)
    # The prior focused wire fixture short-circuited at tool-carrying rows. Its
    # DTO class now receives the genuine payload helper for plain assistant rows.
    def namespace_with_payload(**kwargs):
        if '_VALID_API_ROLES' in kwargs:
            kwargs['_content_has_real_payload'] = ns['_content_has_real_payload']
        return NS(**kwargs)
    def build_wire(*args, **kwargs):
        with patch.object(sdk_wire, 'SimpleNamespace', namespace_with_payload):
            return sdk_wire.build_wire(*args, **kwargs)
    middleware = ModuleType('hermes_cli.middleware')
    middleware.run_llm_execution_middleware = lambda kwargs, callback, **extra: callback(kwargs)
    # The unused imported symbols belong to non-selected retry branches.
    def unselected_retry_branch(*args, **kwargs):
        raise AssertionError('non-redirect retry branch is outside this fixture')
    loop_module = NS(_apply_active_turn_redirect=ns['_apply_active_turn_redirect'],
                     _review_input_budget_exhausted=ns['_review_input_budget_exhausted'],
                     _HANDOFF_SKIP_FINAL_RESPONSE='unused-reference-handoff',
                     _should_skip_model_call_for_reference_handoff=unselected_retry_branch)
    with NativeToolHistory().history_fixture('high') as h:
        history = deepcopy(h.body['messages'])
        if after_adopted:
            NativeToolHistory.dispatch(None, h)
            history += h.replay(h.calls)
            discarded = deepcopy(h.calls)
            for call in discarded: call['id'] += '-discarded'
            h.responses.append(discarded)
        h.body['messages'] = build_wire(history, h.body['tools'])
        changes = ['Synthetic correction from the user']
        budget = NS(refunds=0, consumes=0)
        def refund(): budget.refunds += 1
        def consume(): budget.consumes += 1; return True
        budget.refund = refund; budget.consume = consume
        agent = NS(api_mode='chat_completions', session_id='synthetic-session', platform='api_server',
            model='deepseek-flash', provider='custom', base_url='http://127.0.0.1:8940/v1',
            _pending_redirect_lock=None, _has_pending_redirect=lambda: True,
            clear_interrupt=lambda **kw: True,
            _interruptible_streaming_api_call=lambda *a, **k: NativeToolHistory.dispatch(None, h),
            iteration_budget=budget, _drain_pending_redirect=lambda: changes.pop() if changes else None,
            _current_streamed_assistant_text=visible, _strip_think_blocks=lambda text: text,
            _persist_session=lambda *a: None, _checkpoint_mgr=NS(new_turn=lambda: None),
            _interrupt_requested=False, quiet_mode=True, _budget_grace_call=False, _touch_activity=lambda *a: None)
        retry = NS(restart_with_redirected_messages=False)
        modules = {'hermes_cli': ModuleType('hermes_cli'), 'hermes_cli.middleware': middleware,
                   'agent.conversation_loop': loop_module}
        with patch.dict(sys.modules, modules):
            verdict = ns['perform_api_call'](agent, api_kwargs=h.body, _original_api_kwargs=h.body,
                _llm_middleware_trace=[], _moa_prepared_request=None, _retry=retry, thinking_spinner=None,
                retry_count=0, api_call_count=1, api_request_id='synthetic-api', effective_task_id='fixture-task',
                turn_id='fixture-task', interrupted=False)
            assert verdict.action == 'break' and retry.restart_with_redirected_messages
            restart = ns['apply_retry_restarts'](agent, _retry=retry, response=None, interrupted=False,
                messages=history, conversation_history=[], user_message=history[0]['content'], api_kwargs=h.body,
                current_turn_user_idx=0, final_response=None, retry_count=0, max_retries=3, api_call_count=1,
                restart_count=0, length_continue_retries=0, _preflight_compression_blocked=False,
                _turn_exit_reason='unknown')
            assert restart.action == 'continue' and restart.api_call_count == 0 and budget.refunds == 1
            begin = ns['begin_iteration'](agent, messages=history, conversation_history=[],
                original_user_message=history[0]['content'], api_call_count=restart.api_call_count,
                interrupted=False, _turn_exit_reason='unknown')
            assert begin.action == 'fallthrough' and budget.consumes == 1
        assert history[-2]['role'] == 'assistant' and history[-1]['role'] == 'user'
        # The successor is generated by original functions, not manually supplied.
        h.body['messages'] = build_wire(history, h.body['tools'])
        if more_tools:
            batch = deepcopy(h.calls)
            for call in batch:
                if not reused_ids: call['id'] += '-adopted-after-redirect'
                else: call['index'] += 10
            h.responses.append(batch)
        rejected = None
        try:
            result = NativeToolHistory.dispatch(None, h)
            if more_tools:
                history += h.replay(batch)
                h.body['messages'] = build_wire(history, h.body['tools'])
                result = NativeToolHistory.dispatch(None, h)
            completed = result['choices'][0]['message']['content'] == 'synthetic answer'
        except ValueError as error:
            assert str(error) == 'provider_tool_history_changed'
            rejected = str(error); completed = False
        with h.db() as db:
            states = [tuple(row) for row in db.execute('SELECT state,COUNT(*) FROM model_calls GROUP BY state')]
        return dict(completed=completed, SDK_paid_reply_discarded=True,
            SDK_iteration_refund=budget.refunds, paid_reservations=states,
            provider_stubs=len(h.wire), rejected_safe_code=rejected,
            resumed_indexes=([c['index'] for c in h.wire[-1]['messages'][-3]['tool_calls']]
                             if completed and more_tools else None))

"""Constructor seam for the pinned native FS gateway, never a model-facing tool."""
import importlib.util
from functools import wraps
from pathlib import Path


def adapter():
    path = Path('/profile/plugins/fs-readonly/knowledge.py')
    spec = importlib.util.spec_from_file_location('fs_native_knowledge', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NativeKnowledge()


def trusted_info(options):
    from hermes_constants import get_hermes_home, profile_name_for_home
    return dict(session_id=options['session_id'], platform=options['platform'],
                profile_name=profile_name_for_home(get_hermes_home()))


def has_prior_context(database, session_id):
    if database is None:
        raise ValueError('native_knowledge_session_database_required')
    # Do not call get_session(): it flushes token counts. Only read existence flags.
    row = database._read_one(
        "SELECT EXISTS(SELECT 1 FROM messages WHERE session_id=? AND role IN ('assistant','tool','system')) OR "
        "EXISTS(SELECT 1 FROM sessions WHERE id=? AND "
        "(COALESCE(system_prompt,'')<>'' OR system_prompt_hash IS NOT NULL))",
        (session_id, session_id))
    return bool(row[0])


def construct_fs_agent(factory, **options):
    if options.get('platform') not in ('desktop', 'tui'):
        return factory(**options)
    knowledge = adapter()
    info = trusted_info(options)
    try:
        pin = knowledge.bound(info['session_id'])
        if any(pin[k] != info[k] for k in ('platform', 'profile_name')):
            raise ValueError('native_knowledge_session_identity_changed')
    except FileNotFoundError:
        if knowledge._policy().get('enabled') is not True:
            return factory(**options)
        if has_prior_context(options.get('session_db'), info['session_id']):
            return factory(**options)
        pin = knowledge.pin(info)
    if pin is None:
        return factory(**options)
    test = pin.get('readonly') is not None
    enabled, disabled = options.get('enabled_toolsets'), options.get('disabled_toolsets') or []
    if test:
        if 'fs_knowledge' in disabled:
            raise PermissionError('native_knowledge_test_explicitly_disabled')
        options.update(enabled_toolsets=['fs_knowledge'], skip_memory=True,
                       skip_background_review=True, skip_context_files=True)
    elif enabled == [] or 'fs_knowledge' in disabled:
        return factory(**options)
    else:
        if enabled is None:
            from hermes_cli.plugins import discover_plugins
            discover_plugins()
            from toolsets import get_all_toolsets, TOOLSET_SESSION_PLATFORMS
            enabled = [n for n in get_all_toolsets() if n not in TOOLSET_SESSION_PLATFORMS]
        options['enabled_toolsets'] = list(dict.fromkeys([*enabled, 'fs_knowledge']))
    class BoundFSAgent(factory):
        @wraps(factory.run_conversation)
        def run_conversation(self, *args, **kwargs):
            import fcntl
            with (knowledge.root / 'admission.lock').open('rb') as gate:
                fcntl.flock(gate.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                if test:
                    import inspect
                    call = inspect.signature(super().run_conversation).bind(*args, **kwargs)
                    task = call.arguments.get('task_id') or pin['readonly']['task_ids'][0]
                    verify(self, task)
                    # Desktop otherwise mints a UUID after this boundary, losing the approved task identity.
                    call.arguments['task_id'] = task
                    return super().run_conversation(*call.args, **call.kwargs)
                return super().run_conversation(*args, **kwargs)

        def _execute_tool_calls(self, assistant_message, messages, effective_task_id, api_call_count=0):
            if not test:
                return super()._execute_tool_calls(assistant_message, messages, effective_task_id, api_call_count)
            verify(self, effective_task_id)
            # Runs before native observers/parallel dispatch; observer exceptions cannot bypass this.
            for call in assistant_message.tool_calls:
                if knowledge.guard(call.function.name, {}, self.session_id, effective_task_id):
                    raise PermissionError('native_knowledge_test_tool_denied')
            return super()._execute_tool_calls(assistant_message, messages, effective_task_id, api_call_count)

    def verify(agent, task_id=None):
        tasks = pin['readonly']['task_ids']
        knowledge.verify_test_agent(agent, info['session_id'], task_id or tasks[0])

    instance = BoundFSAgent(**options)
    if test:
        verify(instance)
    return instance

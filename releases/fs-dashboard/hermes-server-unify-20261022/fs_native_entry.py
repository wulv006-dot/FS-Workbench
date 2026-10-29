"""Constructor seam for the pinned native FS gateway, never a model-facing tool."""
import importlib.util
import hashlib
import sys
from functools import wraps
from pathlib import Path
FS_SOURCE=Path('/fs-source')


def adapter():
    path = Path('/profile/plugins/fs-readonly/knowledge.py')
    spec = importlib.util.spec_from_file_location('fs_native_knowledge', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NativeKnowledge()


def trusted_info(options):
    from hermes_constants import get_hermes_home, profile_name_for_home
    return dict(session_id=options['session_id'], platform=options['platform'],
                owner=options.get('user_id'), chat_id=options.get('chat_id'), thread_id=options.get('thread_id'),
                profile_name=profile_name_for_home(get_hermes_home()))


def gateway_info(source, session_id):
    platform = getattr(source.platform, 'value', source.platform)
    return trusted_info(dict(session_id=session_id, platform=platform, user_id=source.user_id,
                             chat_id=source.chat_id, thread_id=source.thread_id))


def run_gateway_conversation(agent, source, inbound_message_id, user_message, **options):
    """Only the native main-answer runner calls this seam, after its original approval registration."""
    if (not getattr(agent, '_fs_task_knowledge', False) or not inbound_message_id
            or getattr(source.platform, 'value', source.platform) != 'feishu'):
        return agent.run_conversation(user_message, **options)
    agent._fs_gateway_turn = (gateway_info(source, agent.session_id), str(inbound_message_id))
    try:
        return agent.run_conversation(user_message, **options)
    finally:
        agent._fs_gateway_turn = None


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
    if options.get('platform') not in ('desktop', 'tui', 'feishu'):
        return factory(**options)
    knowledge = adapter()
    info = trusted_info(options)
    try:
        pin = knowledge.bound(info['session_id'])
        if any(pin[k] != info[k] for k in ('platform', 'profile_name')):
            raise ValueError('native_knowledge_session_identity_changed')
    except FileNotFoundError:
        pin = None
    task_mode = ((pin is None or pin.get('readonly') is None)
                 and info['session_id'] not in knowledge._policy().get('readonly_sessions', {}))
    task_mode = task_mode and knowledge.task_selection(info) is not None
    if pin is None and not task_mode:
        if options.get('platform') == 'feishu':
            return factory(**options)
        if knowledge._policy().get('enabled') is not True:
            return factory(**options)
        if has_prior_context(options.get('session_db'), info['session_id']):
            return factory(**options)
        pin = knowledge.pin(info)
    if pin is None and not task_mode:
        return factory(**options)
    test = pin is not None and pin.get('readonly') is not None
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
        _fs_task_knowledge = task_mode
        _fs_gateway_turn = None

        @wraps(factory.run_conversation)
        def run_conversation(self, *args, **kwargs):
            sys.path.insert(0,str(FS_SOURCE))
            from cache_retention import maintenance_reader
            with maintenance_reader(knowledge.root, create=False, session=True):
                if test:
                    import inspect
                    call = inspect.signature(super().run_conversation).bind(*args, **kwargs)
                    task = call.arguments.get('task_id') or pin['readonly']['task_ids'][0]
                    verify(self, task)
                    # Desktop otherwise mints a UUID after this boundary, losing the approved task identity.
                    call.arguments['task_id'] = task
                    return super().run_conversation(*call.args, **call.kwargs)
                if task_mode:
                    import inspect
                    import uuid
                    call = inspect.signature(super().run_conversation).bind(*args, **kwargs)
                    native_task_id = call.arguments.get('task_id') or str(uuid.uuid4())
                    turn_info = dict(info, session_id=self.session_id)
                    task_key = native_task_id
                    if info['platform'] == 'feishu':
                        if self._fs_gateway_turn is None:
                            return super().run_conversation(*args, **kwargs)
                        turn_info, inbound = self._fs_gateway_turn
                        task_key = 'feishu-' + hashlib.sha256(inbound.encode()).hexdigest()
                    call.arguments['task_id'] = native_task_id
                    with knowledge.activate_task(turn_info, task_key, native_task_id) as task_pin:
                        if task_pin is None:
                            return super().run_conversation(*call.args, **call.kwargs)
                        return self._fs_run_pinned(task_pin, call)
                return super().run_conversation(*args, **kwargs)

        def _fs_run_pinned(self, task_pin, call):
            previous = self.ephemeral_system_prompt
            section = knowledge.pin_prompt(task_pin)
            self.ephemeral_system_prompt = '\n\n'.join(x for x in (previous, section) if x)
            self._fs_active_pin = task_pin
            self._fs_compacted_aliases = set()
            try:
                return super().run_conversation(*call.args, **call.kwargs)
            finally:
                self.ephemeral_system_prompt = previous
                self._fs_active_pin = None
                for name in self._fs_compacted_aliases:
                    knowledge.unlink_task_session(name, task_pin)

        def _execute_tool_calls(self, assistant_message, messages, effective_task_id, api_call_count=0):
            if not test:
                active = getattr(self, '_fs_active_pin', None)
                if active is not None and self.session_id != active['session_id']:
                    name = knowledge.link_task_session(active, self.session_id, effective_task_id)
                    self._fs_compacted_aliases.add(name)
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

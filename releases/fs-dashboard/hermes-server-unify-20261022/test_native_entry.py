import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import test_native_knowledge as fixtures
import fs_native_entry as entry
from fs_readonly.knowledge import READ_TOOLS, register


def pin_process(root, info, results):
    from fs_readonly.knowledge import NativeKnowledge
    try:
        NativeKnowledge(root).pin(info)
        results.put(None)
    except Exception as error:
        results.put(repr(error))


class Factory:
    dispatched = []

    def __init__(self, **options):
        self.options = options
        self.session_id = options['session_id']
        self.ephemeral_system_prompt = options.get('ephemeral_system_prompt')
        names = READ_TOOLS if options.get('enabled_toolsets') == ['fs_knowledge'] else READ_TOOLS | {'terminal'}
        self.valid_tool_names = set(names)
        self.tools = [{'function': {'name': name}} for name in names]

    def _execute_tool_calls(self, message, messages, task, api_call_count=0):
        self.dispatched.extend(call.function.name for call in message.tool_calls)

    def run_conversation(self, user_message, system_message=None, conversation_history=None, task_id=None):
        return task_id


class Entry(unittest.TestCase):
    setUp = fixtures.Native.setUp
    save_index = fixtures.Native.save_index
    save_policy = fixtures.Native.save_policy

    def test_native_admission_loads_shared_helper_without_plugin_preload(self):
        agent=self.construct()
        (self.root/'admission.lock').touch(mode=0o600)
        source=Path(__file__).resolve().parents[3]/'releases/fs-dashboard/cache-archive-retention-20261025/source'
        old_path=list(sys.path)
        removed={name:module for name,module in list(sys.modules.items()) if name=='cache_retention' or name=='fs_readonly' or name.startswith('fs_readonly.')}
        try:
            for name in removed:sys.modules.pop(name,None)
            sys.path[:]=[p for p in sys.path if str(source) not in p and 'fs-readonly' not in p]
            with patch.object(entry,'FS_SOURCE',source):
                self.assertEqual(agent.run_conversation('fixture',task_id='existing-turn'),'existing-turn')
            self.assertEqual(Path(sys.modules['cache_retention'].__file__).resolve(),source/'cache_retention.py')
        finally:
            sys.path[:]=old_path
            for name in list(sys.modules):
                if name=='cache_retention' or name=='fs_readonly' or name.startswith('fs_readonly.'):sys.modules.pop(name,None)
            sys.modules.update(removed)

    def construct(self, **options):
        defaults = dict(session_id=self.info['session_id'], platform=self.info['platform'],
                        enabled_toolsets=['terminal', 'fs_readonly'], disabled_toolsets=[],
                        session_db=types.SimpleNamespace(_read_one=lambda *a: (False,)))
        defaults.update(options)
        with patch.object(entry, 'adapter', return_value=self.adapter), patch.object(entry, 'trusted_info', return_value=self.info):
            return entry.construct_fs_agent(Factory, **defaults)

    def test_actual_caller_symbol_changes_only_the_constructor(self):
        value = json.loads((Path(__file__).parent / 'native-entry-fixture.json').read_bytes())
        f = value['/opt/hermes/tui_gateway/server.py']['symbols'][0]['code']
        self.assertEqual(f.count('    agent = AIAgent('), 1)
        changed = f.replace('    agent = AIAgent(', '    agent = construct_fs_agent(AIAgent,', 1)
        namespace = {}
        import ast
        ast.parse(changed)
        self.assertIn('platform=platform, session_id=session_id or key', changed)
        self.assertIn('session_db=session_db if session_db is not None else _get_db()', changed)

    def test_normal_fs_adds_only_knowledge_preserving_other_grants(self):
        agent = self.construct()
        self.assertEqual(agent.options['enabled_toolsets'], ['terminal', 'fs_readonly', 'fs_knowledge'])
        self.assertNotIn('skip_memory', agent.options)
        self.assertIn('offline-fixed', self.adapter.prompt(self.info))

    def test_old_unpinned_context_keeps_original_constructor_and_no_knowledge(self):
        db = types.SimpleNamespace(_read_one=lambda *a: (True,))
        agent = self.construct(session_db=db)
        self.assertIs(type(agent), Factory)
        self.assertEqual(agent.options['enabled_toolsets'], ['terminal', 'fs_readonly'])
        self.assertEqual(self.adapter.prompt(self.info), '')
        with self.assertRaises(FileNotFoundError): self.adapter.bound(self.info['session_id'])

    def test_default_tools_include_plugins_discovered_at_construction(self):
        import toolsets
        plugin = types.ModuleType('hermes_cli.plugins'); groups = ['terminal']
        plugin.discover_plugins = lambda: groups.append('fs_readonly')
        toolsets.get_all_toolsets = lambda: groups
        with patch.dict(sys.modules, {'hermes_cli.plugins': plugin}):
            agent = self.construct(enabled_toolsets=None)
        self.assertEqual(agent.options['enabled_toolsets'], ['terminal', 'fs_readonly', 'fs_knowledge'])

    def test_disabled_and_other_platform_leave_constructor_untouched(self):
        self.policy['native']['enabled'] = False; self.save_policy()
        self.assertIs(type(self.construct()), Factory)
        with patch.object(entry, 'adapter', side_effect=AssertionError('must not inspect unrelated profile')):
            self.assertIs(type(entry.construct_fs_agent(Factory, session_id='other', platform='slack')), Factory)
        self.policy['native']['enabled'] = True; self.save_policy()
        agent = self.construct(enabled_toolsets=[])
        self.assertEqual(agent.options['enabled_toolsets'], [])

    def test_readonly_constructor_and_execution_guard_fail_closed(self):
        self.policy['native']['readonly_sessions'] = {self.info['session_id']: {'task_ids': ['actual-task']}}
        self.save_policy(); Factory.dispatched = []
        agent = self.construct()
        for flag in ('skip_memory', 'skip_background_review', 'skip_context_files'):
            self.assertTrue(agent.options[flag])
        def message(*names):
            return types.SimpleNamespace(tool_calls=[types.SimpleNamespace(function=types.SimpleNamespace(name=n)) for n in names])
        for names, task in [(('terminal',), 'actual-task'), (('fs_read_knowledge', 'execute_code'), 'actual-task'),
                            (('fs_read_knowledge',), 'spoofed-task')]:
            with self.assertRaises(PermissionError): agent._execute_tool_calls(message(*names), [], task)
        self.assertEqual(Factory.dispatched, [])
        # This boundary runs before the native fail-open observer and before parallel dispatch.
        agent._execute_tool_calls(message('fs_read_knowledge'), [], 'actual-task')
        self.assertEqual(Factory.dispatched, ['fs_read_knowledge'])
        agent.valid_tool_names.add('terminal')
        with self.assertRaises(PermissionError): agent._execute_tool_calls(message('fs_read_knowledge'), [], 'actual-task')

    def test_default_and_feishu_gating_use_frozen_native_selector(self):
        from unittest.mock import Mock
        ctx = Mock(); register(ctx)
        import toolsets
        value = json.loads((Path(__file__).parent / 'native-entry-fixture.json').read_bytes())
        symbol = next(s for d in value.values() for s in d['symbols'] if s['name'] == 'session_disabled_toolsets')
        namespace = {'Optional': __import__('typing').Optional,
                     'TOOLSET_SESSION_PLATFORMS': toolsets.TOOLSET_SESSION_PLATFORMS}
        exec(symbol['code'], namespace)
        fn = namespace['session_disabled_toolsets']
        for platform in ['api_server', 'cli', None]:
            self.assertIn('fs_knowledge', fn([], platform))
        self.assertEqual(fn([], 'desktop'), [])
        self.assertEqual(fn([], 'feishu'), [])

    def test_desktop_task_binding_precedes_native_turn_and_rejects_spoofed_ids(self):
        self.policy['native']['readonly_sessions'] = {self.info['session_id']: {'task_ids': ['actual-task']}}
        self.save_policy(); agent = self.construct()
        import inspect
        self.assertEqual(inspect.signature(agent.run_conversation), inspect.signature(Factory.run_conversation).replace(
            parameters=list(inspect.signature(Factory.run_conversation).parameters.values())[1:]))
        (self.root / 'admission.lock').touch(mode=0o600)
        import contextlib
        lock = types.SimpleNamespace(flock=lambda *a: None, LOCK_SH=1, LOCK_NB=4)
        # Windows checks call binding; formal Linux CI additionally uses actual flock.
        with patch.dict(sys.modules, {'fcntl': lock}) if sys.platform == 'win32' else contextlib.nullcontext():
            self.assertEqual(agent.run_conversation('question'), 'actual-task')
            self.assertEqual(agent.run_conversation('question', None, [], 'actual-task'), 'actual-task')
            with self.assertRaises(PermissionError): agent.run_conversation('question', task_id='spoofed-task')
            with self.assertRaises(PermissionError): agent.run_conversation('question', None, [], 'spoofed-task')

    def test_distinct_process_first_pin_never_overwrites(self):
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        results = context.Queue()
        procs = [context.Process(target=pin_process, args=(str(self.root), self.info, results)) for _ in range(4)]
        for process in procs: process.start()
        for process in procs:
            process.join(timeout=20)
            if process.is_alive():
                process.terminate(); process.join()
                self.fail('pin process timeout')
            self.assertEqual(process.exitcode, 0)
            self.assertIsNone(results.get(timeout=5))
        results.close(); results.join_thread()
        self.assertEqual(len(list((self.root / 'knowledge/native').glob('session-*.json'))), 1)
        self.assertEqual(list((self.root / 'knowledge/native').glob('.complete-*')), [])


if __name__ == '__main__': unittest.main()

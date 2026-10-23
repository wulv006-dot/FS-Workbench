"""Isolated real-native checks. No agent provider, production DB or service operations."""
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import types
from unittest.mock import patch, Mock


def verify(payloads):
    sys.path.insert(0, '/fs-source')
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
    from hermes_constants import get_hermes_home, profile_name_for_home
    import model_tools
    import toolsets
    from tools.registry import registry
    from run_agent import AIAgent
    from agent.agent_runtime_helpers import _pre_tool_block_message
    checked = []
    network = []

    def reject_network(*args, **kwargs):
        network.append(True)
        raise AssertionError('isolated_check_network_forbidden')

    with patch.object(socket.socket, 'connect', reject_network), tempfile.TemporaryDirectory(prefix='fs-knowledge-isolated-') as directory:
        root = Path(directory)
        before = Path('/opt/hermes/tui_gateway/server.py').read_bytes()
        native_patch = types.ModuleType('isolated_factory_patch')
        exec(compile(payloads['patch_factory.py'], '<isolated_factory_patch>', 'exec'), native_patch.__dict__)
        after = native_patch.patch_source(before)
        assert before != after
        checked.append('actual_native_factory_exact_patch_and_parse')
        module = types.ModuleType('isolated_fs_knowledge')
        exec(compile(payloads['knowledge.py'], '<isolated_fs_knowledge>', 'exec'), module.__dict__)
        knowledge_class = module.NativeKnowledge
        knowledge = knowledge_class(root)
        pointer = 'knowledge-releases/knowledge-layering-20261023-1/index.json'
        original = Path('/fs') / pointer
        raw = original.read_bytes(); index = json.loads(raw)
        assert hashlib.sha256(raw).hexdigest() == 'ba2a0ad4b38028cf08a0b73e6d1529a2ba255a29bd5cbc483b5f8f8c9ee095ba'
        target = root / pointer; target.parent.mkdir(parents=True); target.write_bytes(raw)
        ids = []
        for row in index['entries']:
            if row['layer'] == 'current' and row['status'] == 'effective' and set(row['modules']) & {'FS', 'FC27'}:
                path = index['source_root'] + '/' + row['source']['path']
                destination = root / path; destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((Path('/fs') / path).read_bytes()); ids.append(row['id'])
        assert ids
        info = dict(session_id='KL2-isolated-runtime-check', platform='desktop', profile_name=profile_name_for_home(get_hermes_home()))
        route = dict(platform=info['platform'], profile_name=info['profile_name'], catalog=pointer,
                     sha256=hashlib.sha256(raw).hexdigest(), modules=['FS', 'FC27'])
        policy = dict(contract='fs-knowledge-load-policy-v1', requests={}, native=dict(enabled=True, routes=[route],
                      readonly_sessions={info['session_id']: {'task_ids': ['isolated-readonly-task']}}))
        (root / 'knowledge-load-policy.json').write_text(json.dumps(policy))
        module.NativeKnowledge = lambda: knowledge
        manager = PluginManager()
        context = PluginContext(PluginManifest(name='fs-knowledge-isolated-runtime-check'), manager)
        module.register(context)
        checked.append('actual_PluginContext_registers_two_knowledge_tools')
        names = module.READ_TOOLS
        for platform in ('feishu', 'api_server', 'cli'):
            denied = toolsets.session_disabled_toolsets([], platform)
            assert not names & model_tools._select_tool_names(['fs_knowledge'], denied, True)
        assert not names & model_tools._select_tool_names(None, [], True)
        checked.append('actual_native_defaults_and_non_FS_platforms_exclude_knowledge')
        defs = model_tools.get_tool_definitions(enabled_toolsets=['fs_knowledge'], disabled_toolsets=[], quiet_mode=True)
        assert {d['function']['name'] for d in defs} == names
        feishu_defs = model_tools.get_tool_definitions(enabled_toolsets=['fs_knowledge'],
            disabled_toolsets=toolsets.session_disabled_toolsets([], 'feishu'), quiet_mode=True)
        assert not names & {d['function']['name'] for d in feishu_defs}
        assert {d['function']['name'] for d in model_tools.get_tool_definitions(
            enabled_toolsets=['fs_knowledge'], disabled_toolsets=[], quiet_mode=True)} == names
        checked.append('actual_schema_cache_FS_Feishu_FS_isolation')
        entry = types.ModuleType('isolated_fs_native_entry')
        exec(compile(payloads['fs_native_entry.py'], '<isolated_fs_native_entry>', 'exec'), entry.__dict__)
        entry.adapter = lambda: knowledge
        from hermes_state import SessionDB
        state_path = root / 'var/lib/fs-hermes-fc/profile/state.db'; state_path.parent.mkdir(parents=True)
        database = SessionDB(db_path=state_path)
        class NoProvider(AIAgent):
            def __init__(self, **options):
                self.session_id = options['session_id']; self.options = options
                self.tools = defs; self.valid_tool_names = set(names)
            def run_conversation(self, *args, **kwargs):
                raise AssertionError('a_provider_must_never_be_entered')
        agent = entry.construct_fs_agent(NoProvider, session_id=info['session_id'], platform='desktop',
                session_db=database, enabled_toolsets=['terminal'], disabled_toolsets=[])
        assert all(agent.options[n] for n in ('skip_memory', 'skip_background_review', 'skip_context_files'))
        assert agent.options['enabled_toolsets'] == ['fs_knowledge']
        checked.append('actual_native_subclass_construction_has_only_read_grants_no_provider_init')
        with patch('hermes_cli.plugins._dispatch_pre_tool_call_hooks', side_effect=RuntimeError('isolated_fault')):
            agent._current_turn_id = None; agent._current_api_request_id = None
            assert _pre_tool_block_message(agent, 'terminal', {}, 'isolated-readonly-task', 'call', [])[0] is None
            bad = types.SimpleNamespace(tool_calls=[types.SimpleNamespace(function=types.SimpleNamespace(name='terminal'))])
            try:
                agent._execute_tool_calls(bad, [], 'isolated-readonly-task')
            except PermissionError as error:
                assert str(error) == 'native_knowledge_test_tool_denied'
            else:
                raise AssertionError('native_fail_open_observer_bypassed_constructor_guard')
        checked.append('actual_native_fail_open_fault_cannot_reach_tool_dispatch')
        ids_context = model_tools._CallIds(session_id=info['session_id'], task_id='isolated-readonly-task',
                                          tool_call_id='isolated-call', turn_id='', api_request_id='')
        arguments = {'modules': ['FS', 'FC27'], 'entry_ids': ids}
        result = json.loads(model_tools._execute_tool('fs_read_knowledge', arguments, arguments, ids_context,
                           user_task=None, enabled_tools=sorted(names), skip_tool_execution_middleware=False))
        assert result['status'] == 'available' and {r['id'] for r in result['entries']} == set(ids)
        receipts = list((root / 'knowledge/native').glob('use-*.json'))
        assert len(receipts) == 1
        assert json.loads(receipts[0].read_bytes())['result']['selection_sha256'] == result['selection_sha256']
        checked.append('actual_native_dispatch_and_middleware_read_published_version_and_receipt')
        import fcntl
        gate = root / 'admission.lock'; gate.write_bytes(b'')
        with gate.open('rb') as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                agent.run_conversation('never dispatch')
            except BlockingIOError:
                pass
            else:
                raise AssertionError('actual_POSIX_gate_not_honored')
        checked.append('actual_POSIX_admission_gate_blocks_before_provider')
        release = types.ModuleType('isolated_native_release'); release.__file__ = str(root / 'native_release.py')
        exec(compile(payloads['native_release.py'], release.__file__, 'exec'), release.__dict__)
        db_path = release.native_database(root); db_path.parent.mkdir(parents=True, exist_ok=True)
        assert db_path == state_path
        try:
            fence = release.acquire_native_database(types.SimpleNamespace(no_target_link=lambda p: None), root, sqlite3.sqlite_version)
            try:
                assert database.acquire_session_turn_lease('isolated-lease', 'isolated-holder', wait_seconds=0,
                                                          acquire_patience_s=0.01) is False
            finally:
                fence.close()
            assert database.acquire_session_turn_lease('isolated-lease', 'isolated-holder', wait_seconds=0)
        finally:
            database.close()
        checked.append('actual_SessionDB_turn_admission_blocked_by_native_SQLite_fence')
        assert not network
        return dict(status='passed', checks=checked, actual_runtime=sys.version.split()[0],
                    live_catalog_sha256=hashlib.sha256(raw).hexdigest(), selection_sha256=result['selection_sha256'],
                    entry_ids=ids, candidate_sha256={n: hashlib.sha256(s.encode()).hexdigest() for n, s in payloads.items()},
                    provider_calls=0, external_connections=0, production_writes=0, service_operations=0,
                    limits=['no_real_AIAgent_provider_constructor', 'no_user_UI_session', 'no_image_build_or_live_switch',
                            'no_paid_model_quality_or_cost_acceptance'])


if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    payloads = {n: (here / n if n != 'knowledge.py' else here / 'fs_readonly/knowledge.py').read_text('utf-8')
                for n in ('knowledge.py', 'fs_native_entry.py', 'patch_factory.py')}
    payloads['native_release.py'] = (here.parent / 'knowledge-layering-20261023/deploy/native_release.py').read_text('utf-8')
    print(json.dumps(verify(payloads), ensure_ascii=True))

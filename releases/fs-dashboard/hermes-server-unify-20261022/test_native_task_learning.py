"""Task-scoped native reads; fixtures never construct a provider or send a message."""
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import fs_native_entry as entry
import patch_factory
import test_native_knowledge as fixtures
from fs_readonly.knowledge import NativeKnowledge, READ_TOOLS


class TaskLearning(unittest.TestCase):
    setUp = fixtures.Native.setUp
    save_index = fixtures.Native.save_index
    save_policy = fixtures.Native.save_policy

    def enable(self, platform='feishu'):
        self.info.update(owner='approved-user', platform=platform, chat_id='approved-chat', thread_id='thread-1')
        if platform == 'desktop':
            self.route.update(profile_name=self.info['profile_name'])
        route = dict(owner=self.info['owner'], project='FS', channel=platform, task_types=['conversation'],
            profile_name=self.info['profile_name'], chat_id=self.info['chat_id'], thread_id=self.info['thread_id'],
            catalog=self.route['catalog'], sha256=self.route['sha256'], modules=['FC27'])
        self.policy['task_routes'] = dict(enabled=True, routes=[route])
        self.policy['native']['enabled'] = False
        self.save_policy()
        return route

    def source(self, **changes):
        fields = dict(platform='feishu', user_id=self.info['owner'], chat_id=self.info['chat_id'],
                      thread_id=self.info['thread_id'])
        fields.update(changes)
        return types.SimpleNamespace(**fields)

    def construct(self):
        adapter = self.adapter
        class Factory:
            def __init__(self, **options):
                self.options = options; self.session_id = options['session_id']
                self.ephemeral_system_prompt = options.get('ephemeral_system_prompt')
                self._cached_system_prompt = 'original-frozen-profile-memory'
                names = READ_TOOLS if options.get('enabled_toolsets') == ['fs_knowledge'] else READ_TOOLS | {'terminal', 'skill_view'}
                self.valid_tool_names = set(names)
                self.tools = [{'function': {'name': n}} for n in names]

            def run_conversation(self, user_message, system_message=None, conversation_history=None, task_id=None):
                if user_message == 'compact':
                    self.session_id = 'native-compacted-child'
                    self._execute_tool_calls(None, [], task_id)
                return dict(prompt=self.ephemeral_system_prompt, cached=self._cached_system_prompt, task_id=task_id,
                    knowledge=adapter.call('fs_read_knowledge', {'modules': ['FC27']},
                        session_id=self.session_id, task_id=task_id))

            def _execute_tool_calls(self, *args):
                return None

        with patch.object(entry, 'adapter', return_value=self.adapter), patch.object(entry, 'trusted_info', return_value=self.info):
            return entry.construct_fs_agent(Factory, session_id=self.info['session_id'], platform=self.info['platform'],
                user_id=self.info['owner'], chat_id=self.info['chat_id'], thread_id=self.info['thread_id'],
                session_db=types.SimpleNamespace(_read_one=lambda *args: (False,)),
                enabled_toolsets=['terminal', 'skill_view'], disabled_toolsets=[], ephemeral_system_prompt='platform context')

    def run_turn(self, agent, inbound='message-1', source=None):
        (self.root / 'admission.lock').touch()
        lock = types.SimpleNamespace(flock=lambda *a: None, LOCK_SH=1, LOCK_NB=4)
        with patch.dict(sys.modules, {'fcntl': lock}) if sys.platform == 'win32' else contextlib.nullcontext():
            with patch.object(entry, 'gateway_info', side_effect=lambda src, sid: dict(self.info,
                    session_id=sid, owner=src.user_id, chat_id=src.chat_id, thread_id=src.thread_id)):
                return entry.run_gateway_conversation(agent, source or self.source(), inbound, 'question', task_id=agent.session_id)

    def test_gateway_cached_agent_refreshes_only_new_message_and_preserves_tools_memory_and_native_task(self):
        route = self.enable(); agent = self.construct()
        self.assertEqual(agent.options['enabled_toolsets'], ['terminal', 'skill_view', 'fs_knowledge'])
        self.assertNotIn('skip_memory', agent.options)
        first = self.run_turn(agent)
        self.assertIn('offline-fixed', first['prompt'])
        self.assertEqual(first['task_id'], self.info['session_id'])
        self.assertEqual(first['cached'], 'original-frozen-profile-memory')
        self.assertEqual(agent.ephemeral_system_prompt, 'platform context')
        self.index['release'] = 'later'; self.row['revision'] = 'v3'; self.save_index()
        route['sha256'] = self.route['sha256']; self.save_policy()
        # The same inbound id retains its task pin. Published artifacts are immutable in real use.
        repeat = self.run_turn(agent)
        self.assertEqual(repeat, first)
        next_turn = self.run_turn(agent, inbound='message-2')
        self.assertIn('later', next_turn['prompt'])
        self.assertEqual(next_turn['knowledge']['entries'][0]['revision'], 'v3')
        self.assertEqual(agent.ephemeral_system_prompt, 'platform context')
        self.assertEqual(list((self.root / 'knowledge/native').glob('active-*')), [])
        self.assertEqual(len(list((self.root / 'knowledge/native').glob('task-*'))), 2)

    def test_inflight_pin_retains_version_and_route_scope_cannot_expand_from_tool_args(self):
        route = self.enable()
        with self.adapter.activate_task(self.info, 'turn-1', 'native-1') as first:
            original = self.adapter.call('fs_read_knowledge', {'modules': ['FC27']},
                session_id=self.info['session_id'], task_id='native-1')
            self.index['release'] = 'later'; self.row['revision'] = 'v3'; self.save_index()
            route['sha256'] = self.route['sha256']; self.save_policy()
            self.assertEqual(self.adapter.call('fs_read_knowledge', {'modules': ['FC27']},
                session_id=self.info['session_id'], task_id='native-1'), original)
            for args in ({'modules': ['D4']}, {'modules': ['FC27'], 'owner': 'other'},
                         {'modules': ['FC27'], 'entry_ids': ['other.secret']}):
                with self.assertRaises(ValueError):
                    self.adapter.call('fs_read_knowledge', args, session_id=self.info['session_id'], task_id='native-1')
            self.assertEqual(first['release'], 'offline-fixed')
        with self.adapter.activate_task(self.info, 'turn-2', 'native-1') as second:
            self.assertEqual(second['release'], 'later')

    def test_owner_profile_chat_and_thread_require_exact_trusted_identity(self):
        self.enable()
        self.assertIsNotNone(self.adapter.task_selection(self.info))
        for key in ('owner', 'profile_name', 'chat_id', 'thread_id'):
            self.assertIsNone(self.adapter.task_selection(dict(self.info, **{key: 'other'})))
        self.assertIsNone(self.adapter.task_selection(dict(self.info, chat_id=None)))
        self.assertIsNone(self.adapter.task_selection(dict(self.info, owner=None)))
        self.adapter.pin_task(self.info, 'turn-1', 'native-1')
        with self.assertRaisesRegex(ValueError, 'task_identity_changed'):
            self.adapter.pin_task(dict(self.info, owner='other'), 'turn-1', 'native-1')

    def test_default_disabled_routes_keep_original_constructor(self):
        self.enable(); self.policy['task_routes']['enabled'] = False; self.save_policy()
        agent = self.construct()
        self.assertFalse(getattr(agent, '_fs_task_knowledge', False))
        self.assertEqual(agent.options['enabled_toolsets'], ['terminal', 'skill_view'])

    def test_readonly_declared_session_cannot_be_promoted_by_normal_task_route(self):
        self.enable('desktop'); self.policy['native']['enabled'] = True
        self.policy['native']['readonly_sessions'] = {self.info['session_id']: {'task_ids': ['approved-test']}}
        self.save_policy(); agent = self.construct()
        self.assertFalse(agent._fs_task_knowledge)
        self.assertEqual(agent.options['enabled_toolsets'], ['fs_knowledge'])
        self.assertEqual(agent.valid_tool_names, READ_TOOLS)
        self.assertTrue(agent.options['skip_memory'])
        self.assertTrue(agent.options['skip_background_review'])
        self.assertTrue(agent.options['skip_context_files'])

    def test_same_task_pin_is_frozen_and_cannot_read_outside_turn(self):
        self.enable()
        with self.adapter.activate_task(self.info, 'turn-1', 'native-1'):
            index = self.adapter.call('fs_get_knowledge_index', {}, session_id=self.info['session_id'], task_id='native-1')
            self.assertNotIn('current rule', json.dumps(index))
            self.assertEqual(index['reviewed_skills']['status'], 'not_configured')
        with self.assertRaises(FileNotFoundError):
            self.adapter.call('fs_read_knowledge', {'modules': ['FC27']}, session_id=self.info['session_id'], task_id='native-1')

    def test_task_index_preserves_explicit_history_and_route_entry_allowlist(self):
        (self.folder / 'old.md').write_bytes(b'old verified reason')
        self.index['entries'].append(dict(self.row, revision='v1', layer='archive', status='retired',
            source=dict(path='old.md', sha256=hashlib.sha256(b'old verified reason').hexdigest())))
        self.index['entries'].append(dict(self.row, id='private.other'))
        self.save_index(); route = self.enable(); route['entry_ids'] = ['fc.rule']; self.save_policy()
        ids = dict(session_id=self.info['session_id'], task_id='native-1')
        with self.adapter.activate_task(self.info, 'turn-1', 'native-1'):
            current = self.adapter.call('fs_get_knowledge_index', {}, **ids)
            self.assertEqual([r['revision'] for r in current['entries']], ['v2'])
            self.assertTrue(current['history_available'])
            history = self.adapter.call('fs_get_knowledge_index', {'history': True}, **ids)
            self.assertEqual({r['revision'] for r in history['entries']}, {'v1', 'v2'})
            past = self.adapter.call('fs_read_knowledge', dict(modules=['FC27'], entry_ids=['fc.rule'], history=True, revision='v1'), **ids)
            self.assertEqual(past['entries'][0]['content'], 'old verified reason')
            with self.assertRaisesRegex(ValueError, 'entry_scope'):
                self.adapter.call('fs_read_knowledge', dict(modules=['FC27'], entry_ids=['private.other']), **ids)

    def test_exception_restores_original_ephemeral_context_and_clears_active_alias(self):
        self.enable(); agent = self.construct()
        with patch.object(self.adapter, 'call', side_effect=RuntimeError('provider-or-tool-failure')):
            with self.assertRaisesRegex(RuntimeError, 'provider-or-tool-failure'):
                self.run_turn(agent)
        self.assertEqual(agent.ephemeral_system_prompt, 'platform context')
        self.assertIsNone(agent._fs_gateway_turn)
        self.assertEqual(list((self.root / 'knowledge/native').glob('active-*')), [])

    def test_native_compaction_child_keeps_current_task_pin_without_new_scope(self):
        self.enable(); agent = self.construct(); (self.root / 'admission.lock').touch()
        lock = types.SimpleNamespace(flock=lambda *a: None, LOCK_SH=1, LOCK_NB=4)
        with patch.dict(sys.modules, {'fcntl': lock}) if sys.platform == 'win32' else contextlib.nullcontext():
            with patch.object(entry, 'gateway_info', return_value=self.info):
                result = entry.run_gateway_conversation(agent, self.source(), 'message-1', 'compact', task_id='native-original')
        self.assertEqual(result['knowledge']['release'], 'offline-fixed')
        self.assertEqual(result['task_id'], 'native-original')
        self.assertEqual(list((self.root / 'knowledge/native').glob('active-*')), [])
        self.assertEqual(len(list((self.root / 'knowledge/native').glob('task-*'))), 1)

    def test_approved_skill_directory_is_frozen_without_granting_new_skill_tools(self):
        route = self.enable()
        helper_root = Path(__file__).parent.parent / 'hermes-memory-approval-20261022'
        with patch.object(sys, 'path', [str(helper_root), *sys.path]):
            import reviewed_skills
            skills_root = self.root / 'profile/skills'; skill = skills_root / 'methods/test-method'
            skill.mkdir(parents=True); (skill / 'SKILL.md').write_text('approved method', encoding='utf-8')
            pkg = reviewed_skills.package(skills_root, 'methods/test-method')
            item = dict(id='methods/test-method', package_sha256=pkg['sha256'], sha256=pkg['sha256'], files=pkg['entries'],
                modules=['FC27'], description='Read the approved exact method.', review_request_id='review-1')
            material = dict(contract=reviewed_skills.CONTRACT, items=[item])
            index = dict(material, sha256=reviewed_skills.digest(material))
            folder = self.root / 'knowledge'; folder.mkdir(exist_ok=True)
            (folder / 'reviewed-skills.json').write_text(json.dumps(index), encoding='utf-8')
            route['reviewed_skills'] = dict(index='knowledge/reviewed-skills.json', sha256=index['sha256'])
            self.save_policy(); self.adapter.profile_root = self.root / 'profile'
            agent = self.construct(); result = self.run_turn(agent)
            self.assertIn('methods/test-method', result['prompt'])
            self.assertIn('skill_view', agent.options['enabled_toolsets'])
            self.assertEqual(agent.options['enabled_toolsets'], ['terminal', 'skill_view', 'fs_knowledge'])
            self.assertNotIn('approved method', result['prompt'])
            pin = next((self.root / 'knowledge/native').glob('task-*'))
            self.assertEqual(json.loads(pin.read_bytes())['reviewed_skills']['index_sha256'], index['sha256'])
            (skill / 'SKILL.md').write_text('unreviewed replacement', encoding='utf-8')
            task_key = 'feishu-' + hashlib.sha256(b'message-1').hexdigest()
            with self.adapter.activate_task(self.info, task_key, agent.session_id):
                frozen = self.adapter.call('fs_read_knowledge', dict(modules=['FC27'], skill_id=item['id']),
                    session_id=agent.session_id, task_id=agent.session_id)
                self.assertEqual(frozen['content'], 'approved method')
                self.assertEqual(frozen['package_sha256'], pkg['sha256'])
                with self.assertRaisesRegex(ValueError, 'skill_scope'):
                    self.adapter.call('fs_read_knowledge', dict(modules=['FC27'], skill_id='unreviewed/skill'),
                        session_id=agent.session_id, task_id=agent.session_id)
            with self.assertRaisesRegex(ValueError, 'package_changed'):
                self.run_turn(agent, inbound='message-2')

    def test_current_approved_skill_index_advances_only_for_new_tasks_without_policy_rewrite(self):
        route = self.enable(); route['reviewed_skills'] = dict(source='approved_current'); self.save_policy()
        before = (self.root / 'knowledge-load-policy.json').read_bytes()
        helper_root = Path(__file__).parent.parent / 'hermes-memory-approval-20261022'
        item = dict(id='methods/approved', package_sha256='a' * 64, modules=['fc27'],
                    description='Approved reusable method', review_request_id='review-1')
        with patch.object(sys, 'path', [str(helper_root), *sys.path]):
            import reviewed_skills
            listing = dict(missing=False, sha256='b' * 64, items=[item])
            doc = dict(id=item['id'], content='approved', sha256=hashlib.sha256(b'approved').hexdigest(),
                       package_sha256=item['package_sha256'], path='SKILL.md', review_request_id='review-1')
            with patch.object(reviewed_skills, 'current_catalog', side_effect=lambda *args: copy.deepcopy(listing)) as read, \
                    patch.object(reviewed_skills, 'read_reviewed_skill', return_value=doc):
                first = self.adapter.pin_task(self.info, 'turn-1', 'native-1')
                self.assertEqual(first['reviewed_skills']['index_sha256'], 'b' * 64)
                self.assertEqual(read.call_args.args[1], Path('/approved-skills'))
                listing['sha256'] = 'c' * 64; listing['items'] = []
                self.assertEqual(self.adapter.pin_task(self.info, 'turn-1', 'native-1'), first)
                next_task = self.adapter.pin_task(self.info, 'turn-2', 'native-1')
                self.assertEqual(next_task['reviewed_skills']['index_sha256'], 'c' * 64)
                self.assertEqual(read.call_count, 2)
        self.assertEqual((self.root / 'knowledge-load-policy.json').read_bytes(), before)

    def test_readonly_session_cannot_read_reviewed_skill_with_knowledge_tool_name(self):
        self.policy['native']['readonly_sessions'] = {self.info['session_id']: dict(task_ids=['approved-test'])}
        self.save_policy(); self.adapter.test_admission(self.info, 'approved-test')
        with self.assertRaisesRegex(ValueError, 'skill_scope'):
            self.adapter.call('fs_read_knowledge', dict(modules=['FC27'], skill_id='methods/approved'),
                session_id=self.info['session_id'], task_id='approved-test')

    def test_stale_transient_alias_is_preserved_and_retired_only_under_new_turn_lease(self):
        self.enable(); old = self.adapter.pin_task(self.info, 'old-turn', 'native-1')
        alias = self.adapter.link_task_session(old, self.info['session_id'], 'native-1')
        original = (self.root / self.adapter._name('task', old['identity'])).read_bytes()
        with self.adapter.activate_task(self.info, 'new-turn', 'native-1') as current:
            self.assertEqual(current['identity']['task_key'], 'new-turn')
        self.assertEqual((self.root / self.adapter._name('task', old['identity'])).read_bytes(), original)
        self.assertFalse((self.root / alias).exists())
        retired = list((self.root / 'knowledge/native').glob('retired-active-*'))
        self.assertEqual(len(retired), 1)
        self.assertEqual(json.loads(retired[0].read_bytes())['previous_active']['pin_sha256'], old['receipt_sha256'])

    def test_gateway_patch_is_exact_and_leaves_background_agents_untouched(self):
        source = ('class TurnRunner:\n'
            '    def _build_fresh_agent(self):\n        return ctx.AIAgent(model="fixture")\n'
            '    def _run_conversation_with_approval(self):\n        with original_approval():\n'
            '                return agent.run_conversation(api_message, **kwargs)\n'
            '    def _background(self):\n        return ctx.AIAgent(model="background")\n')
        raw = source.encode()
        with patch.object(patch_factory, 'GATEWAY_SHA', hashlib.sha256(raw).hexdigest()):
            after = patch_factory.patch_gateway(raw).decode()
            self.assertIn('return construct_fs_agent(ctx.AIAgent,model="fixture")', after)
            self.assertIn('return ctx.AIAgent(model="background")', after)
            self.assertIn('run_gateway_conversation(agent, ctx.source, ctx.inbound_message_id, api_message, **kwargs)', after)
            with self.assertRaisesRegex(ValueError, 'source_drift'):
                patch_factory.patch_gateway(raw + b'\n')


if __name__ == '__main__':
    unittest.main()

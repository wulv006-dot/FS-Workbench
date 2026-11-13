"""Offline admission, identity and frozen-input checks; no model or service calls."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import re
import types
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path[:0] = [str(SOURCE), str(ROOT / 'releases/fs-dashboard/hermes-fc-pilot-20261013'),
               str(ROOT / 'releases/fs-dashboard/hermes-memory-approval-20261022')]
import knowledge_catalog as kc
import business_context as bc


class TaskSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        runtime = self.root / 'runtime'
        runtime.mkdir()
        self.baseline = b'complete baseline: orders, costs, product identities and learning stay available'
        for name, raw in [('business_context.py', b''), ('business-baseline.md', self.baseline),
                          ('data-archive-first.md', b'archive first'), ('learning-loop.md', b'learning loop')]:
            (runtime / name).write_bytes(raw)
        runtime_patch = patch.object(bc, '__file__', str(runtime / 'business_context.py'))
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)
        release = self.root / 'knowledge-releases/fixed'
        release.mkdir(parents=True)
        rule = b'published current rule'
        (release / 'rule.md').write_bytes(rule)
        self.index = dict(contract=kc.CONTRACT, release='offline-only', release_state='published', source_commit='a'*40,
                          source_root='knowledge-releases/fixed', entries=[dict(id='fc.rule', revision='v1',
                          layer='current', status='effective', modules=['FC27'], effective_at='2026-10-23',
                          owner='fixture owner', authority='git', supersedes=[], provenance=['fixture'],
                          source=dict(path='rule.md', sha256=hashlib.sha256(rule).hexdigest()))])
        catalog = release / 'index.json'
        catalog.write_text(json.dumps(self.index), encoding='utf-8')
        self.route = dict(owner='wulv', project='FS', channel='fs', task_types=['report', 'data', 'conversation'],
                          catalog='knowledge-releases/fixed/index.json', sha256=hashlib.sha256(catalog.read_bytes()).hexdigest(),
                          modules=['FC27'], baseline_compatibility=dict(mode='retain_full_baseline', sha256=hashlib.sha256(self.baseline).hexdigest()))
        self.policy = dict(contract='fs-knowledge-load-policy-v1', requests={}, task_routes=dict(enabled=False, routes=[self.route]))
        self.write_policy()

    def write_policy(self):
        path = self.root / 'knowledge-load-policy.json'
        path.write_text(json.dumps(self.policy), encoding='utf-8')
        path.chmod(0o600)

    def selected(self, **kwargs):
        return kc.task_selection(self.root, **dict(dict(owner='wulv', project='FS', channel='fs', task_type='conversation'), **kwargs))

    def enable(self):
        self.policy['task_routes']['enabled'] = True
        self.write_policy()

    def test_default_disabled_and_absent_policy_preserve_original_path(self):
        self.assertIsNone(self.selected())
        (self.root / 'knowledge-load-policy.json').unlink()
        self.assertIsNone(self.selected())

    def test_authenticated_owner_project_channel_and_task_scope_are_exact(self):
        self.enable()
        for field, value in [('owner', 'chenchao'), ('project', 'other'), ('channel', 'feishu'), ('task_type', 'pricing')]:
            with self.subTest(field=field):
                self.assertIsNone(self.selected(**{field: value}))
        for field in ('owner', 'project', 'channel', 'task_type'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'identity'):
                self.selected(**{field: None})
        value = self.selected()
        self.assertEqual(value['modules'], ['FC27'])
        self.assertEqual(value['route_identity']['owner'], 'wulv')
        self.assertEqual(value['catalog'], self.route['catalog'])
        kc.verify_selection(value)

    def test_native_declared_profile_chat_thread_cannot_be_omitted_or_changed(self):
        self.route.update(channel='feishu', profile_name='main', chat_id='approved-chat', thread_id='approved-thread')
        self.enable()
        args = dict(channel='feishu', profile_name='main', chat_id='approved-chat', thread_id='approved-thread')
        self.assertEqual(self.selected(**args)['status'], 'available')
        for field in ('profile_name', 'chat_id', 'thread_id'):
            for wrong in (None, 'someone-else'):
                with self.subTest(field=field, value=wrong):
                    self.assertIsNone(self.selected(**dict(args, **{field: wrong})))

    def test_native_policy_cannot_silently_omit_profile_or_chat_boundaries(self):
        self.route.update(channel='feishu')
        self.enable()
        with self.assertRaisesRegex(ValueError, 'profile_scope_required'):
            self.selected(channel='feishu', profile_name='main')
        self.route['profile_name'] = 'main'
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'chat_thread_scope_required'):
            self.selected(channel='feishu', profile_name='main', chat_id='approved-chat')
        self.route.update(chat_id='approved-chat', thread_id=None)
        self.write_policy()
        value = self.selected(channel='feishu', profile_name='main', chat_id='approved-chat')
        self.assertIsNone(value['route_identity']['thread_id'])
        self.assertIsNone(self.selected(channel='feishu', profile_name='main', chat_id='approved-chat', thread_id='new-thread'))

    def test_overlapping_routes_conflict_instead_of_choosing_first(self):
        self.policy['task_routes']['routes'].append(copy.deepcopy(self.route))
        self.enable()
        with self.assertRaisesRegex(ValueError, 'route_conflict'):
            self.selected()

    def test_pricing_cannot_be_enabled_as_a_task_route(self):
        self.route['task_types'].append('pricing')
        self.enable()
        with self.assertRaisesRegex(ValueError, 'not_supported'):
            self.selected(task_type='pricing')
        self.assertIsNone(kc.report_selection(self.root, dict(kind='hermes_report', mode='pricing'), owner='wulv'))

    def test_reports_and_data_tasks_use_same_owner_scoped_selection(self):
        self.enable()
        body = dict(kind='hermes_report', mode='daily', request_id='ordinary-new-task')
        self.assertIsNone(kc.report_selection(self.root, body))
        self.assertEqual(kc.report_selection(self.root, body, owner='wulv')['route_identity']['task_type'], 'report')
        self.assertEqual(kc.report_selection(self.root, dict(body, data_request={}), owner='wulv')['route_identity']['task_type'], 'data')
        self.assertIsNone(kc.report_selection(self.root, body, owner='chenchao'))

    def test_unpublished_release_and_wrong_modules_never_enter_input(self):
        self.enable()
        self.route['modules'] = ['D4']
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'not_available:missing_or_out_of_scope'):
            self.selected()
        self.route['modules'] = ['FC27']
        self.route['catalog'] = '../outside/index.json'
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'release_boundary'):
            self.selected()

    def test_complete_baseline_is_retained_and_compatibility_hash_is_enforced(self):
        self.enable()
        selected = self.selected()
        skills = dict(sha256='b'*64, version='fixture', text='method')
        value = bc.freeze_learning(self.root, skills, {}, 'daily', selection=selected, owner='wulv')
        self.assertIn(self.baseline.decode(), value['text'])
        self.assertIn('published current rule', value['text'])
        self.assertIn('runtime/business-baseline.md', [r['path'] for r in value['files']])
        (self.root / 'runtime/business-baseline.md').write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError, 'compatibility_changed'):
            bc.freeze_learning(self.root, skills, {}, 'daily', selection=selected, owner='wulv')
        self.assertEqual(bc.loaded_learning(self.root, value['version']), value)

    def test_future_task_can_change_route_while_prior_task_remains_pinned(self):
        self.enable()
        old = self.selected()
        skills = dict(sha256='b'*64, version='fixture', text='method')
        frozen = bc.freeze_learning(self.root, skills, {}, 'daily', selection=old, owner='wulv')
        release = self.root / 'knowledge-releases/fixed'
        (release / 'rule.md').write_bytes(b'new approved rule')
        self.index['entries'][0]['revision'] = 'v2'
        self.index['entries'][0]['source']['sha256'] = hashlib.sha256(b'new approved rule').hexdigest()
        (release / 'index.json').write_text(json.dumps(self.index), encoding='utf-8')
        self.route['sha256'] = hashlib.sha256((release / 'index.json').read_bytes()).hexdigest()
        self.write_policy()
        self.assertEqual(self.selected()['entries'][0]['revision'], 'v2')
        loaded = bc.loaded_learning(self.root, frozen['version'])
        self.assertEqual(loaded['selection']['entries'][0]['revision'], 'v1')
        self.assertIn('published current rule', loaded['text'])
        self.assertNotIn('new approved rule', loaded['text'])

    def test_fs_routes_require_explicit_full_baseline_compatibility(self):
        self.route.pop('baseline_compatibility')
        self.enable()
        with self.assertRaisesRegex(ValueError, 'compatibility_required'):
            self.selected()

    def reviewed_fixture(self):
        import reviewed_skills
        skills = self.root / 'profile/skills'
        skill = skills / 'reviewed/new-method'
        (skill / 'references').mkdir(parents=True)
        (skill / 'SKILL.md').write_text('new reviewed method, use source evidence', encoding='utf-8')
        (skill / 'references/details.md').write_text('reviewed details remain pinned', encoding='utf-8')
        (skill / 'unreviewed.txt').write_text('not injected as a method document', encoding='utf-8')
        pkg = reviewed_skills.package(skills, 'reviewed/new-method')
        item = dict(id=pkg['path'], relative_path=pkg['path'], sha256=pkg['sha256'], package_sha256=pkg['sha256'],
                    files=pkg['entries'], modules=['fc27'], description='method discovery fixture',
                    review_request_id='review-original-id', candidate_id='skill:original-id')
        index = dict(contract=reviewed_skills.CONTRACT, items=[item])
        index['sha256'] = reviewed_skills.digest(index)
        (self.root / 'knowledge').mkdir()
        path = self.root / 'knowledge/reviewed-skills.json'
        path.write_text(json.dumps(index), encoding='utf-8')
        self.route['reviewed_skills'] = dict(index='knowledge/reviewed-skills.json', sha256=index['sha256'])
        self.enable()
        return skills, skill

    def test_reviewed_skill_discovery_freezes_body_outside_system_and_tool_reads_it(self):
        skills_root, skill = self.reviewed_fixture()
        skills = dict(sha256='b'*64, version='fixture', text='method', methods_text='base methods', governance_text='base rules')
        knowledge = bc.freeze_learning(self.root, skills, {}, 'daily', selection=self.selected(), skill_root=skills_root, owner='wulv')
        self.assertIn('method discovery fixture', knowledge['text'])
        self.assertNotIn('new reviewed method, use source evidence', knowledge['text'])
        self.assertEqual(len(knowledge['reviewed_skills']['documents']), 2)
        path = ROOT / 'releases/fc-coins/fc-pricing-v2-20261022/source/conversation_service.py'
        function = next(x for x in ast.parse(path.read_text(encoding='utf-8')).body
                        if isinstance(x, ast.FunctionDef) and x.name == 'attach_current_learning')
        namespace = dict(re=re)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(path), 'exec'), namespace)
        book = types.SimpleNamespace(call=lambda name, args: dict(original_tool=name))
        modules = {'report_method': types.SimpleNamespace(method_bundle=lambda _: skills),
                   'learning_registry': types.SimpleNamespace(context=lambda _: '')}
        with patch.dict(sys.modules, modules):
            namespace['attach_current_learning'](book, self.root, knowledge)
            index = book.call('fc.read_skill', dict(topic='methods'))
            rows = list(index['sections'])
            while index['next_page']:
                index = book.call('fc.read_skill', dict(topic='methods', section_id=index['next_page']))
                rows.extend(index['sections'])
            method_row = next(r for r in rows if r['path'] == 'reviewed-skills/reviewed/new-method/SKILL.md')
            rule_row = next(r for r in rows if r['path'] == 'knowledge/fc.rule@v1')
            (skill / 'SKILL.md').write_text('later method change', encoding='utf-8')
            actual = book.call('fc.read_skill', dict(topic='methods', section_id=method_row['section_id']))
            self.assertEqual(actual['text'], 'new reviewed method, use source evidence')
            self.assertEqual(book.call('fc.read_skill', dict(topic='methods', section_id=rule_row['section_id']))['text'], 'published current rule')
            self.assertEqual(book.call('fc.other_existing_tool', {}), dict(original_tool='fc.other_existing_tool'))
        self.assertEqual(bc.loaded_learning(self.root, knowledge['version']), knowledge)
        with self.assertRaisesRegex(ValueError, 'package_changed'):
            bc.freeze_learning(self.root, skills, {}, 'daily', selection=self.selected(), skill_root=skills_root, owner='wulv')

    def test_reviewed_skill_index_requires_external_policy_hash_and_task_snapshot_detects_tamper(self):
        skills_root, _ = self.reviewed_fixture()
        self.route['reviewed_skills']['index'] = '../writable-profile/index.json'
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'reviewed_skills_policy'):
            self.selected()
        self.route['reviewed_skills']['index'] = 'knowledge/reviewed-skills.json'
        self.write_policy()
        skills = dict(sha256='b'*64, version='fixture', text='method')
        value = bc.freeze_learning(self.root, skills, {}, 'daily', selection=self.selected(), skill_root=skills_root, owner='wulv')
        path = self.root / 'knowledge' / (value['version']+'.json')
        value['reviewed_skills']['documents'][0]['content'] = 'tampered body'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'snapshot_changed'):
            bc.loaded_learning(self.root, value['version'])

    def test_freeze_cannot_reuse_another_authenticated_owners_selection(self):
        self.enable()
        skills = dict(sha256='b'*64, version='fixture', text='method')
        with self.assertRaisesRegex(PermissionError, 'owner_mismatch'):
            bc.freeze_learning(self.root, skills, {}, 'daily', selection=self.selected(), owner='someone-else')

    def test_current_approved_catalog_advances_for_new_task_without_policy_edit(self):
        import reviewed_skills
        skills_root, skill = self.reviewed_fixture()
        path = self.root / 'knowledge/reviewed-skills.json'
        approved = json.loads(path.read_text(encoding='utf-8'))
        versions = path.parent / 'versions'
        versions.mkdir()
        (versions / (approved['sha256']+'.json')).write_bytes(path.read_bytes())
        self.route['reviewed_skills'] = dict(source='approved_current')
        self.write_policy()
        selection = self.selected()
        policy_before = (self.root / 'knowledge-load-policy.json').read_bytes()
        skills = dict(sha256='b'*64, version='fixture', text='method')
        # The trusted-root reader is tested by its owner; this test checks admission and pin consumers.
        def current(root, published, modules):
            self.assertEqual(published, path.parent)
            return reviewed_skills.list_reviewed(root, path, modules, expected_index_sha=approved['sha256'])
        with patch.object(bc, 'APPROVED_SKILLS_ROOT', path.parent), patch.object(reviewed_skills, 'current_catalog', side_effect=current):
            first = bc.freeze_learning(self.root, skills, {}, 'daily', selection=selection, skill_root=skills_root, owner='wulv')
            (skill / 'SKILL.md').write_text('next day independently approved method', encoding='utf-8')
            pkg = reviewed_skills.package(skills_root, 'reviewed/new-method')
            approved['items'][0].update(sha256=pkg['sha256'], package_sha256=pkg['sha256'], files=pkg['entries'], review_request_id='review-day-2')
            approved['sha256'] = reviewed_skills.digest({k: v for k, v in approved.items() if k != 'sha256'})
            path.write_text(json.dumps(approved), encoding='utf-8')
            (versions / (approved['sha256']+'.json')).write_bytes(path.read_bytes())
            second = bc.freeze_learning(self.root, skills, {}, 'daily', selection=self.selected(), skill_root=skills_root, owner='wulv')
        self.assertEqual((self.root / 'knowledge-load-policy.json').read_bytes(), policy_before)
        self.assertNotEqual(first['version'], second['version'])
        self.assertEqual(first['selection']['selection_sha256'], second['selection']['selection_sha256'])
        self.assertEqual(bc.loaded_learning(self.root, first['version']), first)
        first_body = next(r['content'] for r in first['reviewed_skills']['documents'] if r['path'] == 'SKILL.md')
        second_body = next(r['content'] for r in second['reviewed_skills']['documents'] if r['path'] == 'SKILL.md')
        self.assertEqual(first_body, 'new reviewed method, use source evidence')
        self.assertEqual(second_body, 'next day independently approved method')

    def test_conversation_admission_freezes_selection_once_recovery_does_not_reload(self):
        path = ROOT / 'releases/fc-coins/fc-pricing-v2-20261022/source/conversation_service.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        calls = lambda name: [node for node in ast.walk(methods[name]) if isinstance(node, ast.Call)
                              and isinstance(node.func, ast.Name) and node.func.id == 'task_selection']
        self.assertEqual(len(calls('_dispatch')), 1)
        self.assertEqual(len(calls('_recover')), 0)
        values = {kw.arg: kw.value for kw in calls('_dispatch')[0].keywords}
        self.assertEqual(values['owner'].id, 'user')
        self.assertEqual(values['task_type'].value, 'conversation')

    def test_existing_conversation_contract_against_current_candidate(self):
        path = ROOT / 'releases/fs-dashboard/hermes-conversation-20261018/tests/test_conversation_service.py'
        spec = importlib.util.spec_from_file_location('fs_task_selection_legacy_contract', path)
        module = importlib.util.module_from_spec(spec)
        before = list(sys.path)
        try:
            spec.loader.exec_module(module)
            historical = module.SOURCE
            module.SOURCE = ROOT / 'releases/fc-coins/fc-pricing-v2-20261022/source'
            module.ServiceTests.setUpClass()
            module.SOURCE = historical
            module.ServiceTests.setUpClass = classmethod(lambda cls: None)
            # The live atomic API gained mode before this candidate; keep the old fixture compatible.
            module.ServiceTests.module.atomic = lambda *args, **kwargs: None
            sys.path[:0] = [str(ROOT / 'releases/fs-dashboard/fc-coins-workflow-20261022/source'),
                           str(ROOT / 'releases/fs-dashboard/hermes-fc-pilot-20261013')]
            result = unittest.TestResult()
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.ServiceTests)
            self.assertEqual(suite.countTestCases(), 10)
            suite.run(result)
            self.assertEqual(result.failures, [])
            self.assertEqual(result.errors, [])
        finally:
            sys.path[:] = before


if __name__ == '__main__':
    unittest.main()

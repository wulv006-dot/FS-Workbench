import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'source'),
               str(ROOT / 'releases/fs-dashboard/hermes-fc-pilot-20261013')]
import knowledge_catalog as kc
import business_context as bc


class Knowledge(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'rule.md').write_text('当前规则，程序强制校验。', encoding='utf-8')
        (self.root / 'old.md').write_text('旧日报，只解释当时。', encoding='utf-8')
        runtime = self.root / 'runtime'
        runtime.mkdir()
        for name in ('business_context.py', 'business-baseline.md', 'data-archive-first.md', 'learning-loop.md'):
            (runtime / name).write_text('existing method retained', encoding='utf-8')
        runtime_patch = patch.object(bc, '__file__', str(runtime / 'business_context.py'))
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)
        self.row = dict(id='fc.rule', revision='v2', layer='current', status='effective', modules=['FC27'],
                        effective_at='2026-10-22', owner='test-owner', authority='git', supersedes=['fc.rule@v1'],
                        provenance=['direct_user_fixture'], source=dict(path='rule.md', sha256=hashlib.sha256((self.root / 'rule.md').read_bytes()).hexdigest()))
        self.index = dict(contract=kc.CONTRACT, release='offline-fixture-only', release_state='published', source_commit='a'*40, entries=[self.row])
        self.save()

    def save(self):
        self.path = self.root / 'index.json'
        self.path.write_text(json.dumps(self.index, ensure_ascii=False), encoding='utf-8')
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def selected(self, **kwargs):
        return kc.select(self.root, 'index.json', self.sha, ['FC27'], **kwargs)

    def test_real_fc_current_version_and_only_rule_segment(self):
        path = ROOT / 'knowledge/index.json'
        sha = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        v = kc.select(ROOT, 'knowledge/index.json', sha, ['FC27'], ['fc.pricing.constraints'], preview=True)
        self.assertEqual(v['entries'][0]['revision'], 'fc27_dual20_d9_d2_v2')
        self.assertIn('合法单笔优惠仍可低毛利或亏损', v['entries'][0]['content'])
        for value in ('D-9至D-2的8个完整日','d9_d2_eight_closed_days_v1','不按每日率等权','未优惠实际采购毛利≥20%'):
            self.assertIn(value,v['entries'][0]['content'])
        self.assertNotIn('18:21最新自然验收', v['entries'][0]['content'])
        self.assertEqual(kc.select(ROOT, 'knowledge/index.json', sha, ['FC27'])['status'], 'not_published')

    def test_old_report_never_overrides_current_and_history_is_explicit(self):
        old = dict(self.row, revision='v1', layer='archive', status='archived', effective_at='2026-10-21',
                   source=dict(path='old.md', sha256=hashlib.sha256((self.root / 'old.md').read_bytes()).hexdigest()))
        self.index['entries'].append(old)
        self.save()
        self.assertEqual(self.selected()['entries'][0]['revision'], 'v2')
        old_result = self.selected(entry_ids=['fc.rule'], revision='v1', history=True)
        self.assertEqual(old_result['entries'][0]['effective_at'], '2026-10-21')
        self.assertIn('只解释当时', old_result['entries'][0]['content'])
        with self.assertRaisesRegex(ValueError, 'explicit_history'):
            self.selected(revision='v1')

    def test_candidate_conflict_does_not_enter_effective_content(self):
        self.index['entries'].append(dict(self.row, revision='candidate', layer='candidate', status='pending'))
        self.save()
        self.assertEqual([r['revision'] for r in self.selected()['entries']], ['v2'])

    def test_two_effective_versions_return_conflict_not_latest_edit(self):
        self.index['entries'].append(dict(self.row, revision='v3'))
        self.save()
        self.assertEqual(self.selected()['status'], 'conflict')

    def test_other_module_does_not_receive_fc_rule(self):
        result = kc.select(self.root, 'index.json', self.sha, ['D4'], ['fc.rule'])
        self.assertEqual(result['status'], 'missing_or_out_of_scope')
        self.assertEqual(kc.select(self.root,'index.json',self.sha,['D4','marketing'],['fc.rule'])['status'],'missing_or_out_of_scope')

    def test_real_marketing_uses_user_confirmed_fc_source(self):
        path=ROOT/'knowledge/index.json'
        sha=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        selected=kc.select(ROOT,'knowledge/index.json',sha,['FC27'],['fc.marketing.attribution'],preview=True)
        self.assertEqual(selected['status'],'available_preview')
        self.assertIn('归FC项目',selected['entries'][0]['content'])
        self.assertIn('不能因费用难分而排除真实成交',selected['entries'][0]['content'])
        self.assertNotIn('属全局品牌广告',selected['entries'][0]['content'])

    def test_explicit_unresolved_conflict_is_reported(self):
        self.row['status']='conflict'
        self.save()
        self.assertEqual(self.selected()['status'],'conflict')

    def test_missing_changed_and_candidate_release_preserve_old_snapshot(self):
        old = self.selected()
        self.index['release_state'] = 'candidate'
        self.save()
        self.assertEqual(self.selected()['status'], 'not_published')
        self.index['release_state'] = 'published'
        self.save()
        (self.root / 'rule.md').unlink()
        with self.assertRaises(FileNotFoundError):
            self.selected()
        self.assertIn('当前规则', old['entries'][0]['content'])
        (self.root / 'rule.md').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source_changed'):
            self.selected()

    def test_task_fixed_version_actual_input_and_tamper_check(self):
        selected = self.selected()
        skills = {'sha256': 'b'*64, 'version': 'method-fixture', 'text': 'method'}
        store = self.root / 'tasks'
        store.mkdir()
        first = bc.freeze_learning(store, skills, {}, 'daily', selection=selected)
        second = bc.freeze_learning(store, skills, {}, 'daily', selection=selected)
        self.assertEqual(first['version'], second['version'])
        (self.root / 'rule.md').write_text('later change', encoding='utf-8')
        loaded = bc.loaded_learning(store, first['version'])
        self.assertEqual(first, loaded)
        self.assertIn('existing method retained', loaded['text'])
        receipt = bc.effective_learning(loaded, [{'role': 'system', 'content': loaded['text']}])
        self.assertEqual(receipt['knowledge_entries'][0]['id'], 'fc.rule')
        with self.assertRaisesRegex(ValueError, 'missing'):
            bc.effective_learning(loaded, [{'role': 'user', 'content': loaded['text']}])
        broken = copy.deepcopy(selected)
        broken['entries'][0]['content'] = 'injected'
        with self.assertRaisesRegex(ValueError, 'selection_changed'):
            kc.context(broken)

    def test_legacy_pricing_default_and_teaching_remain_opt_in(self):
        skills = {'sha256': 'b'*64, 'version': 'method-fixture', 'text': 'method'}
        with patch.object(bc, 'learning_bundle', return_value=('原FC输入', hashlib.sha256('原FC输入'.encode()).hexdigest(), [])):
            value = bc.freeze_learning(self.root, skills, {}, 'pricing')
        self.assertEqual(value['text'], '原FC输入')
        self.assertNotIn('selection', value)
        with self.assertRaisesRegex(ValueError, 'pricing_owner'):
            bc.freeze_learning(self.root, skills, {}, 'pricing', selection=self.selected())

    def test_path_and_duplicate_identity_boundaries(self):
        with self.assertRaisesRegex(ValueError, 'boundary'):
            kc.read_bound(self.root, '../outside.md')
        self.index['entries'].append(dict(self.row))
        self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.selected()

    def test_crlf_is_explicit_content_hash_not_publisher_byte_hash(self):
        p = self.root / 'rule.md'
        p.write_bytes(b'a\r\nb\r\n')
        self.row['source'].update(hash_basis='utf8_lf', sha256=hashlib.sha256(b'a\nb\n').hexdigest())
        self.save()
        self.assertEqual(self.selected()['entries'][0]['content'], 'a\nb\n')

    def test_opt_in_policy_only_selects_named_reports(self):
        folder = self.root / 'knowledge-releases/fixture'
        folder.mkdir(parents=True)
        (folder / 'index.json').write_bytes(self.path.read_bytes())
        policy = dict(contract='fs-knowledge-load-policy-v1', requests={
            'isolated-readonly-fixture': dict(catalog='knowledge-releases/fixture/index.json', sha256=self.sha, modules=['FC27'])})
        p = self.root / 'knowledge-load-policy.json'
        p.write_text(json.dumps(policy), encoding='utf-8')
        p.chmod(0o600)
        self.assertIsNone(kc.report_selection(self.root, {'kind': 'hermes_report', 'mode': 'daily', 'request_id': 'ordinary-report'}))
        self.assertIsNone(kc.report_selection(self.root, {'kind': 'conversation', 'mode': 'daily', 'request_id': 'isolated-readonly-fixture'}))
        self.assertIsNone(kc.report_selection(self.root, {'kind': 'hermes_report', 'mode': 'pricing', 'request_id': 'isolated-readonly-fixture'}))
        selected = kc.report_selection(self.root, {'kind': 'hermes_report', 'mode': 'daily', 'request_id': 'isolated-readonly-fixture'})
        self.assertEqual(selected['entries'][0]['id'], 'fc.rule')

    def test_admission_hook_and_eof_restore_live_controller_baseline(self):
        import ast
        source = (Path(__file__).resolve().parents[1] / 'source/controller.py').read_text(encoding='utf-8')
        old = "knowledge=freeze_learning(self.root,load_bundle(self.source_root,question=body['question'],mode=body['mode']),self.proxy.background,body['mode'],owner=user,experience_manifest=experiences)"
        new = "from knowledge_catalog import report_selection\n            selection=report_selection(self.root,body,owner=user)\n            " + old[:-1] + ',selection=selection)'
        self.assertEqual(source.count(new), 1)
        self.assertTrue(source.endswith('\n') and not source.endswith('\n\n'))
        hook = "            if 'selection' in knowledge:\n                from conversation_service import attach_current_learning\n                attach_current_learning(book,self.root,knowledge)\n"
        self.assertEqual(source.count(hook), 1)
        def admission(text):
            node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='admission_guard')
            return ast.get_source_segment(text,node)
        baseline=(ROOT/'releases/fs-dashboard/fc-coins-workflow-20261022/source/controller.py').read_text(encoding='utf8')
        self.assertEqual(hashlib.sha256(admission(baseline).encode()).hexdigest(),'d2fc23f25e82ede5eb6fe8f4ad32f58d1414304b4ec743d05f17c7392df61f84')
        scheduled_delta=[
            ('def submit_scheduled(self,body):','def submit_scheduled(self,body,context=None):'),
            ('self.pool.submit(self.execute,key,owner,value)','self.pool.submit(self.execute,key,owner,value,scheduled_context=context)'),
            ('def execute(self,key,owner,body):','def execute(self,key,owner,body,scheduled_context=None):'),
            ('',"            if deadline is not None and scheduled_context is not None:\n                admission['prompt']+='\\n服务端夜间数据准备观察（不是区间完整性证明）：\\n'+encoded(scheduled_context)\n"),
        ]
        scheduled_restored=source
        for before,after in scheduled_delta:
            self.assertEqual(scheduled_restored.count(after),1)
            scheduled_restored=scheduled_restored.replace(after,before)
        self.assertEqual(hashlib.sha256(scheduled_restored.encode()).hexdigest(),'706b11a00319de14c32faf0e3ffcc68974cc2d20745bc954c2e01213bbde5c35')
        # Exclude only the tested scheduling/admission deltas; keep the original whole-file pin.
        restored=scheduled_restored.replace(admission(source),admission(baseline)).replace('from contextlib import contextmanager, ExitStack','from contextlib import contextmanager')
        original = restored.replace(new, old).replace(hook, '') + '\n'
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), '571f63637933e15ae0bf4bafdd6ff3b78d5f4b2c805afa76097a74df19de35af')
        ast.parse(source, feature_version=(3, 9))

    def test_release_source_root_reads_immutable_release_and_rejects_escape(self):
        folder=self.root/'knowledge-releases/fixed'
        folder.mkdir(parents=True)
        (folder/'rule.md').write_bytes((self.root/'rule.md').read_bytes())
        self.index['source_root']='knowledge-releases/fixed'
        self.save()
        self.assertEqual(self.selected()['entries'][0]['artifact_path'],'knowledge-releases/fixed/rule.md')
        self.index['source_root']='../outside'
        self.save()
        with self.assertRaisesRegex(ValueError,'boundary'):
            self.selected()

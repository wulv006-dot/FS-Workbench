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
        self.assertEqual(v['entries'][0]['revision'], 'fc27_dual20_d9_d2_platform_100k_v4')
        self.assertIn('合法单笔优惠仍可低毛利或亏损', v['entries'][0]['content'])
        for value in ('D-9至D-2的8个完整日','d9_d2_eight_closed_days_v1','不按每日率等权','八日平均20%'):
            self.assertIn(value,v['entries'][0]['content'])
        for value in ('PS、Xbox、PC','100K购买、实交100K','Lootbar','Arab-UT','ItemD2R辅助'):
            self.assertIn(value,v['entries'][0]['content'])
        self.assertNotIn('105K',v['entries'][0]['content'])
        self.assertNotIn('18:21最新自然验收', v['entries'][0]['content'])
        self.assertEqual(kc.select(ROOT, 'knowledge/index.json', sha, ['FC27'])['status'], 'not_published')

    def test_email_export_current_scope_not_old_paid_defaults(self):
        path = ROOT / 'knowledge/index.json'
        sha = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        result = kc.select(ROOT, 'knowledge/index.json', sha, ['FS'], ['fs.orders.email_export'], preview=True)
        self.assertEqual(result['status'], 'available_preview')
        text = result['entries'][0]['content']
        for value in ('progress', 'status', 'cid', 'aid', '不提交四条件', '没有注册', '725'):
            self.assertIn(value, text)
        self.assertEqual(kc.select(ROOT, 'knowledge/index.json', sha, ['FS'], ['fs.orders.email_export'])['status'], 'not_published')

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
        self.assertIn('真实FC订单及USD计FC广告成交',selected['entries'][0]['content'])
        self.assertIn('无已核分摊不套FC',selected['entries'][0]['content'])
        self.assertIn('归因渠道 ＞ 订单来源 ＞ 推广人及折扣码',selected['entries'][0]['content'])
        self.assertIn('其余未映射线索＝待归类，全无线索＝未知', selected['entries'][0]['content'])
        self.assertIn('同级冲突待核', selected['entries'][0]['content'])
        self.assertIn('每单收入计一次，原字段和协助保留', selected['entries'][0]['content'])
        for text in ('明确Direct的用码单及无上级归属的用码单，均按码细分于Direct',
                     '历史映射照用', '/admin/market/discount',
                     '张玲玲＝KOL', '董文鑫、陈宝＝广告投放', '刘晓辰、尹岚＝分销',
                     '张皓＝TikTok', '王修权＝SEO（自然搜索）',
                     '其他及未映射码＝运营', '无更高归属且仅券＝Direct/新人/活动', '码券并用按码',
                     '率＝总利润/同组Order销售', '缺记录或金额留空'):
            self.assertIn(text, selected['entries'][0]['content'])
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

    def test_native_report_route_preserves_admission_guard_and_controller_syntax(self):
        import ast
        source = (Path(__file__).resolve().parents[1] / 'source/controller.py').read_text(encoding='utf-8')
        tree=ast.parse(source,feature_version=(3,9))
        guard=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='admission_guard')
        # The security boundary is unchanged. A historical whole-controller hash
        # cannot stand in for the current native report behavior covered by the
        # real controller/store/worker tests.
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source,guard).encode()).hexdigest(),
                         'a8add6035c358abbaa2716638fcb70fcdcb9f21090f52b9c851bccca89cd988b')
        self.assertTrue(source.endswith('\n') and not source.endswith('\n\n'))
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='HermesService')
        methods={node.name:node for node in cls.body if isinstance(node,ast.FunctionDef)}
        imports=[node for node in ast.walk(methods['_submit_report']) if isinstance(node,ast.ImportFrom) and node.module=='native_reports']
        self.assertTrue(any(any(alias.name=='prepare_knowledge' for alias in node.names) for node in imports))
        self.assertIn('_execute_legacy',methods)

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

"""Exercise actual hash-pinned loading and prompt routing without network/model calls."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
WORKSPACE = next((root for root in HERE.parents
                  if (root / 'releases/fs-dashboard').is_dir()
                  or (root / 'hermes_report_tracks_20261015/source').is_dir()), HERE.parents[1])
BASE = WORKSPACE / 'hermes_report_tracks_20261015/source'
CANDIDATE = HERE / 'source'
ROOTS = [CANDIDATE, BASE,
         WORKSPACE / 'hermes_fs_research_integration_20261015/source',
         WORKSPACE / 'hermes_market_sources_20261015/regression',
         WORKSPACE / 'releases/fs-dashboard/hermes-fs-research-integration-20261015/source',
         WORKSPACE / 'releases/fs-dashboard/hermes-market-sources-20261015',
         WORKSPACE / 'releases/fs-dashboard/hermes-fc-pilot-20261013',
         WORKSPACE / 'releases/fs-dashboard/hermes-report-tracks-20261015/source',
         WORKSPACE / 'releases/fs-dashboard/hermes-report-tracks-20261015']
TRACKS_ROOT = next(root for root in ROOTS if (root / 'report_tracks.py').is_file())
sys.path.insert(0, str(TRACKS_ROOT))


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def assemble(destination, manifest, roots):
    for row in manifest['files']:
        path = next((root / row['path'] for root in roots
                     if (root / row['path']).is_file()
                     and hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']), None)
        if path is None:
            raise AssertionError('Missing exact baseline: ' + row['path'])
        target = destination / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (destination / 'skills/manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


class WeeklyBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / 'candidate'
        cls.manifest = json.loads((CANDIDATE / 'skills/manifest.json').read_text('utf-8'))
        assemble(cls.root, cls.manifest, ROOTS)
        cls.new = module(CANDIDATE / 'skill_bundle.py', 'weekly_candidate')
        semantics_root = next(root for root in ROOTS if (root / 'report_semantics.py').is_file())
        cls.semantics = module(semantics_root / 'report_semantics.py', 'weekly_semantics')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_real_ui_question_loads_weekly_and_prompt(self):
        bundle = self.new.load_bundle(self.root, question='请基于同口径证据撰写 FC 上周运营周报。', mode='investigation')
        self.assertEqual(bundle['report_track'], 'operations')
        self.assertEqual(bundle['permissions'], [])
        self.assertIn('3—4', bundle['weekly_method_text'])
        self.assertIn('SEO/Ads', bundle['methods_text'])
        self.assertIn('本次经营周报专用方法', self.new.prompt(bundle, {'instruction': '周报'}))

    def test_nightly_weekly_question_loads_weekly(self):
        bundle = self.new.load_bundle(self.root, question='FC27经营周报，复盘上一完整自然周。', mode='investigation')
        self.assertIn('上一完整周一至周日', bundle['weekly_method_text'])

    def test_daily_does_not_inject_weekly_reference(self):
        bundle = self.new.load_bundle(self.root, question='请写昨日经营日报。', mode='daily')
        self.assertEqual(bundle['weekly_method_text'], '')
        self.assertNotIn('本次经营周报专用方法', self.new.prompt(bundle, {}))

    def test_explicit_pricing_beats_weekly_keyword_and_keeps_fingerprint(self):
        after = self.new.load_bundle(self.root, question='周报背景的价格研究', mode='pricing')
        self.assertEqual(after['sha256'], '220f4c75a3fd9d78fec39614d2ea94dbeade3e746a7df7909e64edec3a68462d')
        self.assertEqual(hashlib.sha256(after['methods_text'].encode()).hexdigest(), 'e9211783316d23fecca49c7c163bafcbd43008b32dba03c34401320fe37fd1d1')
        self.assertEqual(hashlib.sha256(after['text'].encode()).hexdigest(), 'c34607d8c1d01bb1759efc5a30a9578576a23b6fddcb96f4520e27e73d2d3e1d')
        self.assertEqual(after['weekly_method_text'], '')

    def test_marketing_method_uses_real_tool_and_explains_available_scope(self):
        bundle = self.new.load_bundle(self.root, question='经营周报', mode='investigation')
        text = self.new.prompt(bundle, {})
        for expected in ('fc.query_marketing_snapshot', 'source_medium', 'Ads没有真实地域表', '不因没有FC专属归因只写“无法判断”'):
            self.assertIn(expected, text)
        question = (HERE / 'generation-prompt.txt').read_text('utf-8')
        for expected in ('fc.query_marketing_snapshot', '2026-10-05', '2026-09-28', '没有真实geo', '不是强制排班'):
            self.assertIn(expected, question)

    def test_weekly_format_teaches_existing_structured_cards(self):
        bundle = self.new.load_bundle(self.root, question='经营周报', mode='investigation')
        for text in (bundle['weekly_method_text'], (HERE / 'generation-prompt.txt').read_text('utf-8')):
            for expected in ('fs-report-v2', 'research_text', 'title/fact/hypothesis/action/source/published_at/event_at/applies/url/retrieved_at/evidence_ids', 'first_check', 'review_at', 'role'):
                self.assertIn(expected, text)

    def test_existing_schema_keeps_explicit_action_dates_and_role(self):
        eid = 'ev_' + '1' * 24
        value = {'report_contract': 'fs-report-v2', 'summary': '合成摘要。', 'research_text': '## 关键判断\n合成测试。',
                 'findings': [], 'limitations': [], 'intel': [], 'actions': [
                     {'target': '合成队列', 'action': '核查', 'condition': '有待查样本', 'cost_risk': '记录实际工时',
                      'first_check': '2026-10-16', 'review_at': '2026-10-19', 'success_check': '已核原因数',
                      'stop_condition': '证据冲突时暂停相关个案', 'role': '建议履约负责人', 'evidence_ids': [eid]}]}
        parsed = self.semantics.structured(value, {eid: {}})
        action = self.semantics.review_action(parsed['actions'][0])
        self.assertEqual(action['first_check'], '2026-10-16')
        self.assertEqual(action['review_at'], '2026-10-19')
        self.assertEqual(action['role'], '建议履约负责人')

    def test_chinese_intel_requires_same_document_url_and_observed_time(self):
        eid = 'ev_' + '2' * 24
        url = 'https://www.ea.com/games/ea-sports-fc/fc-27/news/synthetic-one'
        stamp = '2026-10-15T12:00:00+00:00'
        other_stamp = '2026-10-15T12:01:00+00:00'
        evidence = {eid: {'data': {'documents': [
            {'source_url': url, 'observed_at': stamp, 'published_at': '2026-10-10'},
            {'source_url': url.replace('one', 'two'), 'observed_at': other_stamp, 'published_at': '2026-10-10'}]}}}
        row = {'title': '合成中文消息', 'fact': '合成已证事实', 'hypothesis': '可能形成需求线索', 'action': '先核内容承接',
               'source': 'EA官方合成测试', 'published_at': '2026-10-10', 'event_at': '未知', 'applies': '分析周背景',
               'url': url, 'retrieved_at': stamp, 'evidence_ids': [eid]}
        value = {'period': {'start': '2026-10-05', 'end': '2026-10-11'}, 'intel': [row]}
        accepted, pending, _ = self.semantics.intelligence(value, evidence)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(pending, [])
        self.assertEqual(accepted[0]['fact'], '合成已证事实')
        row['retrieved_at'] = other_stamp
        accepted, pending, _ = self.semantics.intelligence(value, evidence)
        self.assertEqual(accepted, [])
        self.assertEqual(len(pending), 1)

    def test_pricing_marker_beats_weekly_keyword(self):
        bundle = self.new.load_bundle(self.root, question='【竞品与定价研究】依据周报作市场背景')
        self.assertEqual(bundle['report_track'], 'pricing')
        self.assertEqual(bundle['weekly_method_text'], '')

    def test_same_question_has_stable_hash_and_weekly_changes_hash(self):
        question = '请写周报'
        one = self.new.load_bundle(self.root, question=question, mode='investigation')
        two = self.new.load_bundle(self.root, question=question, mode='investigation')
        daily = self.new.load_bundle(self.root, question='请写日报', mode='daily')
        self.assertEqual(one['sha256'], two['sha256'])
        self.assertNotEqual(one['sha256'], daily['sha256'])

    def test_weekly_tampering_rejected_and_pricing_unaffected(self):
        path = self.root / 'skills/fs-fc-operations-analysis/references/weekly-report.md'
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\nchanged')
            with self.assertRaisesRegex(ValueError, 'skill_changed'):
                self.new.load_bundle(self.root, question='请写周报')
            self.assertEqual(self.new.load_bundle(self.root, mode='pricing')['report_track'], 'pricing')
        finally:
            path.write_bytes(original)

    def test_manifest_matches_candidate_bytes_and_no_permissions_added(self):
        self.assertEqual(self.manifest['permissions_added'], [])
        for name in ('skills/fs-fc-operations-analysis/SKILL.md',
                     'skills/fs-fc-operations-analysis/references/weekly-report.md'):
            row = next(row for row in self.manifest['files'] if row['path'] == name)
            data = (CANDIDATE / name).read_bytes()
            self.assertEqual(row['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(row['bytes'], len(data))


if __name__ == '__main__':
    unittest.main()

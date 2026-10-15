import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
from report_tracks import PRICING_MARKER,track_for_question
from skill_bundle import load_bundle,prompt


class ReportTrackTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.pricing='skills/fs-fc-pricing-research/SKILL.md'
        self.contents={
            'skills/fs-fc-operations-analysis/SKILL.md':'运营技能：日报、周报、月报。',
            'skills/fs-fc-operations-analysis/references/methods.md':'共同证据方法。',
            'skills/fs-fc-operations-analysis/references/metric-governance.md':'共同指标治理。',
            'skills/fs-fc-operations-analysis/references/report-contract.md':'经营报告专用合同。',
            self.pricing:(ROOT/'source'/self.pricing).read_text('utf-8')}
        rows=[]
        for name,text in self.contents.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            data=text.encode('utf-8');path.write_bytes(data)
            rows.append(dict(path=name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
        self.manifest={'version':'0.9.0-practical-research','active_skill':'fs-fc-operations-analysis',
            'permissions_added':[],'hermes_commit':'71d34bad1045610252eda02ee79549436896e784','files':rows}
        (self.root/'skills/manifest.json').write_text(json.dumps(self.manifest),'utf-8')

    def test_explicit_mode_or_prefix_only(self):
        self.assertEqual(track_for_question('研究当前市场',mode='pricing'),'pricing')
        self.assertEqual(track_for_question('  '+PRICING_MARKER+'FC27'),'pricing')
        for question in ('FC27日报提到定价','不要采用'+PRICING_MARKER,'FC27 pricing report',''):
            self.assertEqual(track_for_question(question),'operations')
        self.assertEqual(track_for_question('FC27周报',mode='investigation'),'operations')

    def test_default_bundle_remains_operations(self):
        bundle=load_bundle(self.root)
        self.assertEqual(bundle['version'],self.manifest['version'])
        self.assertEqual(bundle['report_track'],'operations')
        self.assertEqual(bundle['active_skill'],'fs-fc-operations-analysis')
        self.assertIn('经营报告专用合同',bundle['methods_text'])
        self.assertEqual(bundle['permissions'],[])

    def test_pricing_loads_independent_skill_and_shared_governance(self):
        bundle=load_bundle(self.root,mode='pricing')
        self.assertEqual(bundle['active_skill'],'fs-fc-pricing-research')
        self.assertIn('Coins',bundle['text']);self.assertIn('Items',bundle['text'])
        self.assertIn('共同证据方法',bundle['methods_text'])
        self.assertNotIn('经营报告专用合同',bundle['methods_text'])
        self.assertEqual(bundle['governance_text'],'共同指标治理。')
        self.assertEqual(bundle['permissions'],[])
        self.assertNotEqual(bundle['sha256'],load_bundle(self.root)['sha256'])

    def test_host_mode_and_worker_prefix_bind_identical_skill_receipts(self):
        host=load_bundle(self.root,question='市场研究',mode='pricing')
        worker=load_bundle(self.root,question=PRICING_MARKER+'市场研究\n格式说明')
        self.assertEqual(host,worker)

    def test_pricing_hash_tampering_rejected(self):
        with (self.root/self.pricing).open('a',encoding='utf-8') as stream:stream.write('changed')
        with self.assertRaisesRegex(ValueError,'skill_changed'):load_bundle(self.root,mode='pricing')

    def test_permission_metadata_cannot_expand(self):
        self.manifest['permissions_added']=['browser']
        (self.root/'skills/manifest.json').write_text(json.dumps(self.manifest),'utf-8')
        with self.assertRaisesRegex(ValueError,'skill_authority'):load_bundle(self.root,mode='pricing')

    def test_prompts_are_distinct_and_do_not_require_unverified_quote(self):
        operation=prompt(load_bundle(self.root),{'instruction':'FC27日报'})
        pricing=prompt(load_bundle(self.root,mode='pricing'),{'instruction':'市场研究'})
        self.assertIn('宏观经营策略、运营动作、专题与促销规划、履约和积压分析',operation)
        self.assertIn('Coins 与 Items 的市场行为、竞品网站比较和市场机会',pricing)
        self.assertIn('不推荐具体新售价',pricing)
        self.assertIn('只暂停依赖缺项的具体建议',pricing)
        self.assertNotIn('经营报告专用合同',pricing)


if __name__=='__main__':unittest.main()

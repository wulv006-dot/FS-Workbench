"""Synthetic review compatibility checks; no stored reports, network or model calls."""
import ast,copy,importlib.util,inspect,unittest
from html import unescape
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

renderer=module('review_compat_renderer',HERE/'source/report_html.py')
for relative in ('hermes_market_sources_20261015/regression/report_html.py','hermes-fc-pilot-20261013/report_html.py'):
    path=ROOT/relative
    if path.is_file():
        baseline=module('review_compat_baseline',path);break
else:raise FileNotFoundError('market sources regression/report_html.py')

EID='ev_'+'a'*24
EVIDENCE={EID:{'source':'合成来源','data':{}}}

def report(reviews):
    return {'summary':'完整摘要保持。','findings':[{'statement':'完整专题保持。','claim_type':'unreviewed','alternative':'其他解释保持。','missing':'局部缺口保持。','evidence_ids':[EID]}],
            'actions':[],'reviews':reviews,'limitations':['既有未核状态保持。'],'number_claims':[],'report_format':'structured_v2_recovered',
            'raw_model_text':'原稿不可变','research_text':'# 完整原稿\n\n全部研究段落保持。'}

class ReviewCompatibilityTests(unittest.TestCase):
    def rendered(self,reviews):
        value=report(reviews);before=copy.deepcopy(value)
        result=renderer.render_report(value,EVIDENCE,{'start':'2026-01-05','end':'2026-01-11'})
        self.assertEqual(value,before)
        for text in ('完整摘要保持。','完整专题保持。','其他解释保持。','局部缺口保持。','既有未核状态保持。'):
            self.assertIn(text,result)
        return result

    def test_legacy_review_fields_and_status_labels(self):
        for status,label in [('improved','改善'),('worse','恶化'),('pending','待核实'),('retracted','撤回')]:
            with self.subTest(status=status):
                result=self.rendered([{'old_report_id':'old-synthetic','status':status,'reason':'原文理由保持。','evidence_ids':[EID]}])
                self.assertIn('old-synthetic · '+label,result)
                self.assertIn('原文理由保持。',result)
                self.assertIn('尚未业务核验',result)

    def test_current_object_previous_current_and_chinese_status_preserved(self):
        review={'object':'示例复查对象','previous':'10/13之前判断保持。','current':'10/5–11期间观察保持。','status':'未再复现/改善（待核）','evidence_ids':[EID]}
        result=self.rendered([review])
        for text in ('示例复查对象','未再复现/改善（待核）','<b>前次</b>','<b>本次</b>',review['previous'],review['current']):self.assertIn(text,result)
        self.assertNotIn('未绑定历史报告',result)
        self.assertIn('尚未业务核验',result)

    def test_missing_optional_fields_do_not_imply_improvement(self):
        result=self.rendered([{}, {'object':'只给对象','extra_note':'额外原文保持。'}])
        self.assertIn('复查对象未提供 · 待核实',result)
        self.assertIn('只给对象 · 待核实',result)
        self.assertIn('额外原文保持。',result)
        self.assertNotIn(' · 改善',result)
        result=self.rendered([{'object':'完整对象','old_report_id':'原报告编号保持','status':'pending'}])
        self.assertIn('完整对象 · 待核实',result);self.assertIn('原报告编号保持',result)

    def test_xss_in_all_review_text_is_escaped(self):
        payload='<script>alert("x")</script><img src=x onerror=bad()>'
        result=self.rendered([{'object':payload,'previous':payload,'current':payload,'status':payload,'reason':payload,payload:payload,'evidence_ids':[EID]}])
        self.assertNotIn('<script>',result);self.assertNotIn('<img ',result)
        self.assertIn(renderer.text(payload),result)
        self.assertGreaterEqual(unescape(result).count(payload),7)

    def test_natural_report_body_is_not_changed_or_lost(self):
        value=report([{'object':'对象','current':'未核内容','evidence_ids':[EID]}])
        value.update(report_format='markdown',raw_model_text='# 完整研究\n\n所有段落保留，含 **原文重点**。\n\n<script>unsafe()</script>')
        before=copy.deepcopy(value)
        result=renderer.render_report(value,EVIDENCE)
        self.assertIn(renderer.markdown(value['raw_model_text'],EVIDENCE),result)
        self.assertEqual(value,before);self.assertNotIn('<script>unsafe()',result)

    def test_shared_interfaces_and_python39_syntax(self):
        self.assertEqual(inspect.signature(renderer.render_report),inspect.signature(baseline.render_report))
        source='# 标题\n\n**内容** [外链](https://invalid.test) <script>unsafe()</script>'
        self.assertEqual(renderer.markdown(source,EVIDENCE),baseline.markdown(source,EVIDENCE))
        ast.parse((HERE/'source/report_html.py').read_text('utf-8'),feature_version=(3,9))

if __name__=='__main__':unittest.main()

import copy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('boss_renderer',ROOT/'candidate/render_report.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
C=json.loads((ROOT/'fixtures/sample.content.json').read_text('utf-8'))
E=json.loads((ROOT/'fixtures/evidence-public.json').read_text('utf-8'))


class RendererTests(unittest.TestCase):
    def test_frozen_sample_values_unchanged(self):
        original=copy.deepcopy(C);original.pop('payment_evidence_ids')
        digest=hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest,json.loads((ROOT/'source-baseline.json').read_text('utf-8'))['sample_semantic_sha256'])
        html=r.render(C,E)
        self.assertIn('227,259.77',html)
        self.assertIn('3,426',html)
        self.assertEqual(sum(Decimal(str(x['current'])) for x in C['charts'][0]['rows']),Decimal('227259.77'))

    def test_arbitrary_closed_investigation_and_no_comparison(self):
        c=copy.deepcopy(C);c['report']['kind']='investigation';c['report']['period'].update(start='2026-10-07',end='2026-10-09',comparison_start=None,comparison_end=None)
        self.assertIn('未获取同口径对照',r.render(c,E))

    def test_bad_partial_comparison_and_open_date_rejected(self):
        c=copy.deepcopy(C);c['report']['period']['comparison_end']=None
        with self.assertRaises(ValueError):r.validate(c,E)
        c=copy.deepcopy(C);c['report']['kind']='daily';c['report']['period'].update(start='2026-10-15',end='2026-10-15')
        with self.assertRaises(ValueError):r.validate(c,E)

    def test_zero_one_two_and_five_actions_no_forced_count(self):
        for n in [0,1,2,5]:
            c=copy.deepcopy(C);c['actions']=c['actions'][:n];c['decisions']=[];c['executive']['decision']=''
            result=r.render(c,E)
            self.assertIn(str(n)+'项行动建议',result)
            self.assertNotIn('请老板决定的两件事',result)
            self.assertNotIn('3个主线',result)

    def test_zero_values_and_zero_orders(self):
        c=copy.deepcopy(C)
        for chart in c['charts']:
            for row in chart['rows']:
                for key in ['previous','current','value','amount','weekday','weekend','previous_orders','current_orders','previous_aov','current_aov']:
                    if key in row:row[key]=0
        html=r.render(c,E)
        self.assertNotRegex(html,r'\b(?:NaN|Infinity)\b')
        self.assertIsNone(r.ratio(0,0))
        self.assertNotIn('nan',html.lower())

    def test_dynamic_waterfall_large_and_negative_values(self):
        chart={'title':'合成量级','rows':[{'label':'基准','role':'total','value':1000000000},{'label':'变化','role':'delta','value':-2000000000},{'label':'本期','role':'total','value':-1000000000}]}
        html=r.waterfall(chart)
        for y,h in re.findall(r'<rect[^>]+y="([\d.-]+)"[^>]+height="([\d.-]+)"',html):
            self.assertGreaterEqual(float(y),24.9);self.assertLessEqual(float(y)+float(h),225.1)
        self.assertNotIn('280000',(ROOT/'candidate/render_report.py').read_text('utf-8'))

    def test_null_and_empty_charts_preserve_source_note(self):
        c=copy.deepcopy(C)
        for chart in c['charts']:chart['rows']=[]
        c['context']=[];c['research_url']=None
        html=r.render(c,E)
        self.assertIn('缺失数据，未绘制',html)
        self.assertIn(C['charts'][0]['scope'],html)
        chart=copy.deepcopy(C['charts'][3])
        for row in chart['rows']:row['previous']=row['current']=None
        self.assertIn('缺少有效数据',r.chart_figure(chart))

    def test_increase_red_decrease_green_flat_neutral(self):
        self.assertEqual(r.delta_color(1),r.RED);self.assertEqual(r.delta_color(-1),r.GREEN);self.assertEqual(r.delta_color(0),r.BLUE)
        self.assertEqual(r.delta_class('+0.00%'),'')
        html=r.bar_chart({'kind':'bars_compare','title':'合成','rows':[{'label':'涨','previous':1,'current':2},{'label':'跌','previous':2,'current':1}]})
        self.assertIn('fill="'+r.RED+'"',html);self.assertIn('fill="'+r.GREEN+'"',html)

    def test_dynamic_payment_references_and_unknown_rejected(self):
        c=copy.deepcopy(C);c['payment_evidence_ids']=[next(iter(E))]
        self.assertIn('href="#'+c['payment_evidence_ids'][0]+'"',r.render(c,E))
        c['payment_evidence_ids']=['ev_'+'f'*24]
        with self.assertRaises(ValueError):r.validate(c,E)

    def test_input_source_target_labels(self):
        c=copy.deepcopy(C);c['report'].update(source_policy='合成主源口径',target_basis='合成目标版本2026-10、同口径已确认',project_label='合成项目',method_note='测试渲染')
        html=r.render(c,E)
        self.assertIn('合成主源口径',html);self.assertIn('合成目标版本2026-10、同口径已确认',html)
        self.assertNotIn('目标版本未提供',html);self.assertNotIn('dot整理',html)

    def test_research_fallback_is_escaped(self):
        c=copy.deepcopy(C);c['research_text']='<script>alert("MODEL_HTML")</script>'
        with mock.patch.dict(sys.modules,{'report_html':None}):html=r.render(c,E)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(',html)

    def test_existing_safe_markdown_helper(self):
        helper_spec=importlib.util.spec_from_file_location('report_html',ROOT/'fixtures/report_html.py');helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
        c=copy.deepcopy(C);key=next(iter(E));c['research_text']='## 合成标题\n\n**保留结论** '+key+'\n\n<img src=x onerror=alert(1)>'
        with mock.patch.dict(sys.modules,{'report_html':helper}):html=r.render(c,E)
        self.assertIn('<h2>合成标题</h2>',html);self.assertIn('<strong>保留结论</strong>',html)
        self.assertNotIn('<img src=x',html);self.assertIn('完整研究正文',html)

    def test_parallel_reference_numbers_do_not_leak(self):
        def run(index):
            c=copy.deepcopy(C);c['executive']['summary']=str(index)
            return r.render(c,E)
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(run,range(4)))
        self.assertTrue(all('href="#'+C['payment_evidence_ids'][0]+'"' in value for value in values))


if __name__=='__main__':unittest.main()

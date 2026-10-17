"""Executive rendering checks with invented amounts and metadata only."""
import copy
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('executive_renderer_candidate',ROOT/'source/boss_renderer.py')
renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
EID='ev_'+'a'*24


def chart(identity,kind='bars_compare'):
    return {'id':identity,'title':identity,'kind':kind,'unit':'USD',
            'scope':'META_HOST_CHANNEL','period':'2026-01-05 — 2026-01-06',
            'as_of':'CAPTURE_METADATA','interpretation':'INTERPRETATION_METADATA',
            'note':'FORMULA_METADATA','rows':[],'evidence_ids':[EID]}


def content():
    charts=[chart('daily','line_compare'),chart('bridge','waterfall'),chart('platform'),
            chart('category'),chart('queue','bars'),chart('margin','line_compare')]
    charts[0]['rows']=[{'label':'01-05','previous_date':'2026-01-01','current_date':'2026-01-05',
                       'previous':100,'current':80,'previous_orders':10,'current_orders':8,
                       'previous_aov':10,'current_aov':10}]
    charts[1]['rows']=[{'label':'对照期','role':'total','value':100},
                       {'label':'Coins','role':'delta','value':-30},
                       {'label':'Items','role':'delta','value':10},
                       {'label':'本期','role':'total','value':80}]
    charts[4].update(period_basis='current_snapshot',snapshot_at='2026-01-07T00:00:00Z',labels=[],
                     period='当前订单',rows=[{'label':'over14d','value':2,'amount':20}])
    source={'system':'SYSTEM_METADATA','scope':{'reported_channels':['CHANNEL_METADATA']},
            'period':{'start':'2026-01-05','end':'2026-01-07'},'reference_margin_percent':'20',
            'captured_at':'CAPTURE_METADATA','source_data_as_of':None}
    estimate={'status':'estimated','period':{'start':'2026-01-05','end':'2026-01-06'},
              'main_revenue_usd':'80','reference_margin_percent':'20','amount_usd':'16',
              'formula':'FORMULA_METADATA','evidence_ids':[EID],'sources':[source]}
    text='先调查 PS Coins（'+EID+'），暂不调价。'
    return {'schema_version':'1.0',
            'business_model':{'fulfillment':'order_driven','holds_inventory':False,'supplier_settlement':'monthly'},
            'report':{'id':'synthetic','title':'合成经营报告','subtitle':'SUBTITLE_METADATA',
                      'kind':'investigation','filename':'synthetic.html','generated_at':'2026-01-10T00:00:00Z',
                      'period':{'start':'2026-01-05','end':'2026-01-06','comparison_start':'2026-01-01',
                                'comparison_end':'2026-01-02','timezone':'Asia/Shanghai'},
                      'source_policy':'SOURCE_POLICY_METADATA','business_data_captured_at':'CAPTURE_METADATA',
                      'source_data_as_of':None,'target_basis':'TARGET_METADATA','snapshot_id':'SYNTHETIC_SNAPSHOT',
                      'status':'供参考'},
            'executive':{'headline':'先调查 PS Coins','summary':text,'confidence_fact':'FACT_METADATA',
                         'confidence_unknown':'LIMIT_METADATA','now':[{'title':'核对页面','text':text}],
                         'decision':'先核对可比报价'},
            'metrics':[{'label':'销售额 USD','value':'80.00','delta':'-20%','previous':'100.00',
                        'status':'fact','evidence_ids':[EID]}],
            'charts':charts,'corrections':['CORRECTION_METADATA'],'key_findings':[],
            'quality_review':{'scope':'REVIEW_METADATA','issues':[{'location':'summary','severity':'warning',
                              'reasons':['REVIEW_WARNING_METADATA'],'evidence_ids':[EID]}]},
            'research_text':'RESEARCH_FULL_METADATA '+EID,'hypotheses':[],
            'payment':[{'label':'合成通道','previous':100,'current':80,'delta':-20}],
            'payment_evidence_ids':[EID],
            'context':[{'label':'说明','text':'CONTEXT_METADATA','evidence_ids':[EID]} for _ in range(3)],
            'finance':{'title':'FINANCE_TITLE_METADATA','basis':'FINANCE_BASIS_METADATA',
                       'next':'FINANCE_NEXT_METADATA','estimates':{'current':estimate}},
            'intel':[],'actions':[{'id':'action-1','priority':'优先','title':'核对页面','role':'运营',
                       'when':'建议明日','trigger':'发现差异','steps':text,'metric':'页面与报价是否一致',
                       'cost':'只读核查','risk':'不得自动改价','stop':'报价不可比则停止推断','evidence_ids':[EID]}],
            'timeline':[],'decisions':[],'gaps':['GAP_METADATA'],
            'provenance':{'evidence_count':1,'scope':'PROVENANCE_METADATA','research_html_sha256':'0'*64,
                          'package_sha256':'1'*64}}


class VisibleText(HTMLParser):
    def __init__(self):super().__init__();self.stack=[];self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag not in {'br','hr','img','meta','link','input'}:self.stack.append((tag,dict(attrs)))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:del self.stack[i:];break
    def handle_data(self,data):
        if any(tag in {'head','style','script','title'} for tag,_ in self.stack):return
        for i,(tag,attrs) in enumerate(self.stack):
            if tag=='details' and 'open' not in attrs and (i+1==len(self.stack) or self.stack[i+1][0]!='summary'):return
        self.parts.append(data)


class ExecutiveRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name)
        (path/'report.template.html').write_text('<html><head><title>@@TITLE@@</title></head><body>@@BODY@@</body></html>',encoding='utf-8')
        self.override=patch.object(renderer,'HERE',path);self.override.start();self.addCleanup(self.override.stop)

    def rendered(self,c=None):return renderer.render(c or content(),{EID:{'source':'EVIDENCE_METADATA'}})

    def test_changes_start_at_zero_and_totals_are_not_bars(self):
        ch=content()['charts'][1];ch['labels']=['2026-01-01 — 2026-01-02','2026-01-05 — 2026-01-06']
        result=renderer.waterfall(ch);image=ET.fromstring(result[result.index('<svg'):])
        bars=image.findall('rect')
        self.assertEqual(len(bars),2)
        self.assertEqual([bar.get('fill') for bar in bars],[renderer.GREEN,renderer.RED])
        self.assertAlmostEqual(float(bars[0].get('x'))+float(bars[0].get('width')),340)
        self.assertEqual(float(bars[1].get('x')),340)
        for value in ['-30.00','+10.00','-20.00','2026-01-01','2026-01-05','USD']:self.assertIn(value,result)

    def test_unexplained_residual_is_visible_even_below_one_cent(self):
        ch=content()['charts'][1];ch['rows'][-1]['value']='80.001'
        result=renderer.waterfall(ch)
        self.assertIn('+0.001 USD 未解释',result)
        self.assertNotIn('+0.00 USD 未解释',result)

    def test_missing_delta_is_not_zero_filled(self):
        ch=content()['charts'][1];ch['rows'][1]['value']=None
        result=renderer.waterfall(ch)
        self.assertIn('缺失',result);self.assertNotIn('<svg',result)

    def test_extra_total_is_not_misread_as_contribution(self):
        ch=content()['charts'][1];ch['rows'][1]['role']='total'
        self.assertIn('分项类型不完整',renderer.waterfall(ch))
        self.assertNotIn('<svg',renderer.waterfall(ch))

    def test_metadata_is_preserved_but_folded_by_default(self):
        result=self.rendered();parser=VisibleText();parser.feed(result);visible=' '.join(parser.parts)
        for text in ['META_HOST_CHANNEL','CAPTURE_METADATA','UNKNOWN','CHANNEL_METADATA',
                     'FORMULA_METADATA','RESEARCH_FULL_METADATA','SOURCE_POLICY_METADATA',EID]:
            self.assertIn(text,result);self.assertNotIn(text,visible)
        for text in ['先调查 PS Coins','2026-01-01','2026-01-05','USD','非实际结算','核对页面']:
            self.assertIn(text,visible)
        self.assertNotIn('<details open',result)
        self.assertNotIn('历史原文（',result)

    def test_citation_cleanup_keeps_amount_and_original(self):
        c=content();c['executive']['summary']='先核对 $12.34，来源（'+EID+'）。'
        result=self.rendered(c);parser=VisibleText();parser.feed(result);visible=' '.join(parser.parts)
        self.assertIn('$12.34',visible);self.assertNotIn(EID,visible)
        self.assertIn(renderer.esc(c['executive']['summary']),result)

    def test_hard_conflict_still_has_visible_notice(self):
        c=content();c['quality_review']['issues'][0]['severity']='error'
        result=self.rendered(c);parser=VisibleText();parser.feed(result)
        self.assertIn('个别判断与依据有冲突',' '.join(parser.parts))

    def test_input_is_unchanged_and_html_is_escaped(self):
        c=content();c['executive']['summary']='<script>unsafe()</script> $12.34';before=copy.deepcopy(c)
        result=self.rendered(c)
        self.assertEqual(c,before);self.assertNotIn('<script>unsafe()',result)
        self.assertIn('&lt;script&gt;unsafe()',result)


if __name__=='__main__':unittest.main()

import copy,importlib.util,sys,unittest
from pathlib import Path
from xml.etree import ElementTree as ET
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def sibling(underscore):
    for name in (underscore,underscore.replace('_','-')):
        path=ROOT/name
        if path.exists():return path
    raise FileNotFoundError(underscore)
INTEGRATION=sibling('hermes_fs_research_integration_20261015')
MARKET=sibling('hermes_market_sources_20261015')
sys.path[:0]=[str(HERE),str(INTEGRATION/'source'),str(MARKET/'regression')]
import boss_renderer as renderer
import boss_projection as projection
import report_semantics as semantics
spec=importlib.util.spec_from_file_location('baseline_render_tests',INTEGRATION/'tests/test_executive_render.py')
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline);baseline.renderer=renderer
ExecutiveRenderTests=baseline.ExecutiveRenderTests
spec=importlib.util.spec_from_file_location('pricing_consumer_tests',sibling('hermes_report_tracks_20261015')/'tests/test_pricing_report.py')
pricing_tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(pricing_tests)
PricingConsumerTests=pricing_tests.PricingReportTests

class VisualUpgradeTests(unittest.TestCase):
    def test_summary_complete_short_and_original_unchanged(self):
        original='第一句说明变化。第二句说明风险。第三句说明动作。第四句说明限制。'
        self.assertEqual(renderer.executive_brief(original),'第一句说明变化。第二句说明风险。第三句说明动作。')
        self.assertLessEqual(len(renderer.executive_brief('很长的没有分句段落'*100)),240)
        self.assertNotIn('…',renderer.executive_brief('很长的没有分句段落'*100))

    def test_actual_official_docs_fill_legacy_markdown_cards(self):
        eid=baseline.EID;url='https://www.ea.com/games/ea-sports-fc/fc-27/news/synthetic'
        document={'source_url':url,'title':'Synthetic official update','text':'Official event detail. Eligibility is defined in the announcement.','published_at':'2026-01-08T00:00:00Z','observed_at':'2026-01-10T00:00:00Z'}
        result={'period':{'start':'2026-01-05','end':'2026-01-11'},'research_text':'# Markdown old report','intel':[]}
        evidence={eid:{'data':{'documents':[document,dict(document)]}}};before=copy.deepcopy(evidence)
        cards,pending,note=semantics.intelligence(result,evidence)
        self.assertEqual(len(cards),1);self.assertEqual(pending,[]);self.assertEqual(evidence,before)
        self.assertEqual(cards[0]['published_at'],document['published_at']);self.assertIn('不以发布日期代替',cards[0]['event_at'])
        self.assertEqual(cards[0]['url'],url);self.assertIn('Official event detail.',cards[0]['fact'])
        self.assertIn('1 条',note)
        for item in evidence[eid]['data']['documents']:item['source_url']='https://example.com/fc-27/news/synthetic'
        self.assertEqual(semantics.intelligence(result,evidence)[0],[])

    def test_official_missing_text_or_observation_is_not_a_card(self):
        for document in [dict(source_url='https://www.ea.com/games/ea-sports-fc/fc-27/news/synthetic',observed_at='2026-01-10T00:00:00Z'),dict(source_url='https://www.ea.com/games/ea-sports-fc/fc-27/news/synthetic',text='content',observed_at='2026-01-10')]:
            self.assertEqual(semantics.intelligence({'intel':[]},{'ev_a':{'data':{'documents':[document]}}})[0],[])

    def test_daily_independent_axes_and_missing_gap(self):
        chart=baseline.content()['charts'][0]
        chart['rows']=[copy.deepcopy(chart['rows'][0]) for _ in range(3)];chart['rows'][1]['current_orders']=None
        result=renderer.daily_overview(chart)
        self.assertIn('两轴都从 0 起',result);self.assertIn('订单 · 单',result)
        image=ET.fromstring(result[result.index('<svg'):])
        self.assertEqual(len(image.findall('polyline')),2);self.assertEqual(len(image.findall('rect')),3)
        self.assertTrue(all(r.get('fill')==renderer.GREEN for r in image.findall('rect')))

    def test_current_pool_count_and_amount_are_both_visible(self):
        result=renderer.queue_chart(baseline.content()['charts'][4])
        self.assertIn('2 <small>当前单数',result);self.assertIn('$20.00',result)
        self.assertIn('同单位内比较',result);self.assertIn('超过14天',result)
        chart=baseline.content()['charts'][4];chart['rows'][0]['amount']=None
        self.assertIn('金额缺失',renderer.queue_chart(chart))

    def test_schedule_rolls_expired_recommendation_forward(self):
        plan=projection.action_schedule({'when':'2025-12-01 首查；2025-12-08复盘'},'2026-01-10T00:00:00Z')
        self.assertEqual(plan['first_check'],'2026-01-11');self.assertEqual(plan['review_at'],'2026-01-18')
        self.assertIn('已过',plan['schedule_note'])
        future=projection.action_schedule({'when':'2026-01-12首查；2026-01-19复盘'},'2026-01-10T00:00:00Z')
        self.assertEqual(future['first_check'],'2026-01-11');self.assertEqual(future['review_at'],'2026-01-12')
        explicit=projection.action_schedule({'when':'2026-01-19','source_first_check':'2026-01-12','source_review_at':'2026-01-19'},'2026-01-10T00:00:00Z')
        self.assertEqual(explicit['first_check'],'2026-01-12');self.assertEqual(explicit['review_at'],'2026-01-19')
        review_only=projection.action_schedule({'when':'2026-01-19','source_review_at':'2026-01-19'},'2026-01-10T00:00:00Z')
        self.assertEqual(review_only['first_check'],'2026-01-11');self.assertEqual(review_only['review_at'],'2026-01-19')

    def test_evidence_payload_is_not_exported(self):
        rendered=renderer.render(baseline.content(),{baseline.EID:{'source':'合成来源','data':{'email':'PRIVATE_MARKER@example.invalid'}}})
        self.assertNotIn('PRIVATE_MARKER',rendered);self.assertIn('原始证据保留于任务',rendered)
        for marker in ['toggle-body','章节目录','chart-focus','aria-controls','prefers-reduced-motion','id="intelligence"']:self.assertIn(marker,rendered)

    def test_marketing_exact_period_only_and_stale_not_headlined(self):
        period={'start':'2026-01-05','end':'2026-01-11'}
        data={'contract':'fc-marketing-read-v1','status':'partial','query':dict(period,profile='FC27'),'sources':{'ga4':{'status':{'status':'success','retained_previous':True},'coverage':{'complete_dates':True},'metrics':{'sessions':999}}}}
        context=projection.marketing_context({'ev_a':{'data':data}},period)
        self.assertNotIn('999',renderer.marketing_section(context));self.assertIn('待核实',renderer.marketing_section(context))
        data['query']['start']='2026-01-04';self.assertIsNone(projection.marketing_context({'ev_a':{'data':data}},period))

    def test_marketing_missing_metrics_ctr_and_comparison(self):
        row={'status':{'status':'success','retained_previous':False},'coverage':{'complete_dates':True},'metrics':None}
        context={'status':'partial','sources':{'ga4':copy.deepcopy(row),'gsc':dict(row,metrics={'ctr':'0.023'})},'ads_accounts':[dict(row,customer_id='synthetic',currency='USD',campaigns={'rows':[{'metrics':None}]})],'evidence_ids':[],'note':'合成背景'}
        result=renderer.marketing_section(context)
        self.assertIn('缺失',result);self.assertIn('2.30%',result)
        self.assertNotIn('existing_published_collector',result)
        context['sources']['ga4']['metrics']={'sessions':'200'}
        previous=copy.deepcopy(context);previous['sources']['ga4']['metrics']={'sessions':'100'}
        result=renderer.marketing_section(context,previous)
        self.assertIn('+100.00%',result);self.assertIn('两期对比',result)
        context['sources']['ga4']={'status':'not_available'}
        self.assertIn('待核实',renderer.marketing_section(context))

if __name__=='__main__':unittest.main()

"""Independent pricing-track contracts using synthetic values only."""
import copy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
for name in ('hermes_fs_research_integration_20261015','hermes-fs-research-integration-20261015'):
    shared=ROOT.parent/name/'source'
    if shared.is_dir():sys.path.append(str(shared));break
sys.path.insert(0,str(ROOT/'source'))
from pricing_report import PLATFORMS,SOURCES,project,render


def offer(platform,price,bonus=0,source=None):
    row={'platform':platform,'base_k':'100','bonus_k':str(bonus),'gross_usd':str(price),
         'currency':'USD','status':'available','freshness':'fresh','captured_at':'2026-01-08T00:00:00Z',
         'url':'https://www.mmoexp.com/Fc-27/Coins.html','auth_state':'public'}
    if source:row['source']=source;row['url']='https://www.u4gm.com/fc-27/coins'
    return row


def fixture():
    data={'contract':'fc27-existing-market-readonly-v1','profile':'FC27','captured_at':'2026-01-08T00:00:00Z',
          'collection_run_id':'synthetic-run','status':'available',
          'competitors':[offer(p,price,source=s) for p in PLATFORMS for s,price in zip(SOURCES,[10,8,12,11])],
          'storefront':{'rows':[offer(p,10,25) for p in PLATFORMS]},
          'costs':[{'platform':p,'status':'available','freshness':'fresh','unit':'CNY/K',
                    'cny_per_1k':'0.35'} for p in PLATFORMS],
          'fx':{'status':'available','freshness':'fresh','direction':'CNY per USD','cny_per_usd':'7'},
          'fee_scenario':{'rate':'0.05','fixed_fee_usd':None},'limitations':['合成条件未核齐']}
    evidence={'ev_market':{'data':data},'ev_total':{
        'source':'Admin FC支付明细','scope':'main','query':{'start':'2026-01-05','end':'2026-01-06','group_by':[],'filters':{}},
        'data':{'status':'available','filters_applied':{},'coverage':{'paid_complete':True,'missing_days':[]},
                'pagination':{'complete':True},'total':{'revenue_usd':'120','orders':10,'unpriced_orders':0}}}}
    result={'snapshot_id':'synthetic','period':{'start':'2026-01-05','end':'2026-01-06'},
            'summary':'经营摘要不得冒充定价结论。','research_text':'# 专题一 经营\n\nMACRO_ONLY\n\n# 专题五 行情与价格\n\n先比较含赠单价，价格原因仍待证。\n\n# 专题六 履约\n\nQUEUE_ONLY',
            'actions':[{'target':'问题单履约','action':'检查积压订单'},
                       {'target':'竞品报价','action':'复核四家同档报价','condition':'确认同平台同单位',
                        'stop_condition':'优惠或费用不可比时停止跟价推断','evidence_ids':['ev_market']}]}
    return result,evidence


class PricingReportTests(unittest.TestCase):
    def test_no_anchor_is_accepted_and_gifts_are_normalized(self):
        r,e=fixture();c=project(r,e)
        self.assertEqual(len(c['markets']),1)
        self.assertEqual(len(c['markets'][0]['quotes']),12)
        self.assertEqual(Decimal(c['markets'][0]['own'][0]['effective_usd_per_k']),Decimal('.08'))
        self.assertEqual(c['report']['kind'],'pricing')
        self.assertEqual(c['report']['version'],'pricing-v1')

    def test_market_position_and_cost_space_are_arithmetic_not_a_new_quote(self):
        r,e=fixture();c=project(r,e);m=c['markets'][0]
        self.assertEqual(m['positions'][0],{'platform':'PS','lower_than':3,'higher_than':0,'equal_to':1,'compared':4})
        self.assertEqual(Decimal(m['costs'][0]['usd_per_k']),Decimal('.05'))
        self.assertEqual(Decimal(m['costs'][0]['spread_usd_per_k']),Decimal('.03'))
        self.assertFalse(c['new_price_recommended']);self.assertFalse(c['actions_executed'])

    def test_stale_cost_fx_and_own_offer_do_not_certify_cost_space(self):
        for part in ('cost','fx','own'):
            r,e=fixture();data=e['ev_market']['data']
            row=data['costs'][0] if part=='cost' else data['fx'] if part=='fx' else data['storefront']['rows'][0]
            row['freshness']='stale'
            with self.subTest(part=part):self.assertIsNone(project(r,e)['markets'][0]['costs'][0]['spread_usd_per_k'])

    def test_invalid_unit_boolean_and_nonfinite_are_local_gaps(self):
        for field,value in [('currency','EUR'),('gross_usd',True),('gross_usd','NaN'),('base_k','1000')]:
            r,e=fixture();e['ev_market']['data']['competitors'][0][field]=value
            c=project(r,e)
            with self.subTest(field=field,value=value):
                self.assertFalse(c['markets'][0]['quotes'][0]['numeric_available'])
                self.assertIsNone(c['markets'][0]['quotes'][0]['relative'])
                self.assertIn('缺失',render(r,e))

    def test_same_round_duplicates_are_merged_but_conflicts_stay_separate(self):
        r,e=fixture();e['ev_market_copy']=copy.deepcopy(e['ev_market'])
        e['ev_market_copy']['data']['captured_at']='2026-01-08T00:01:00Z'
        c=project(r,e);self.assertEqual(len(c['markets']),1)
        self.assertEqual(c['markets'][0]['evidence_ids'],['ev_market','ev_market_copy'])
        e['ev_market_copy']['data']['competitors'][0]['gross_usd']='99'
        c=project(r,e);self.assertEqual(len(c['markets']),2)
        self.assertTrue(any('不同市场快照' in g for g in c['gaps']))

    def test_mixed_operating_text_and_actions_are_not_copied(self):
        r,e=fixture();c=project(r,e)
        self.assertNotIn('MACRO_ONLY',c['strategy_text']);self.assertNotIn('QUEUE_ONLY',c['strategy_text'])
        self.assertNotIn('经营摘要',c['summary']);self.assertEqual(len(c['actions']),1)
        self.assertEqual(c['actions'][0]['target'],'竞品报价')

    def test_report_track_from_result_or_metadata_enables_dedicated_research(self):
        for in_result in (True,False):
            r,e=fixture();r['research_text']='专属定价正文，不套经营六图。';r['summary']='定价判断。'
            context={} if in_result else {'report_track':'pricing'}
            if in_result:r['report_track']='pricing'
            c=project(r,e,context)
            self.assertEqual(c['strategy_text'],r['research_text']);self.assertEqual(c['summary'],'定价判断。')

    def test_mixed_acceptance_preview_cannot_become_formal_pricing_text(self):
        r,e=fixture();c=project(r,e,{'report_track':'pricing','template_preview':True})
        self.assertTrue(c['report']['template_preview']);self.assertIn('模板接线预览',c['report']['title'])
        self.assertNotIn('MACRO_ONLY',c['strategy_text'])

    def test_business_background_comes_from_frozen_totals_first(self):
        r,e=fixture();c=project(r,e,{'business_background':'手填句。第二句。'})
        self.assertIn('$120.00',c['business_background']);self.assertIn('10 单',c['business_background'])
        self.assertNotIn('手填',c['business_background'])

    def test_empty_market_still_explains_coins_and_items_separately(self):
        r,e=fixture();del e['ev_market'];c=project(r,e);html=render(r,e)
        self.assertEqual(c['markets'],[]);self.assertIn('不等于服务器没有金币行情',' '.join(c['gaps']))
        self.assertIn('物品竞品数据尚未接入',html)
        self.assertNotIn('销售与订单变化',html);self.assertNotIn('data-chart-tab',html)

    def test_injection_bad_links_and_unknown_event_dates_are_preserved_safely(self):
        r,e=fixture();r['pricing_summary']='<script>unsafe()</script>'
        e['ev_market']['data']['competitors'][0]['url']='javascript:alert(1)'
        e['ev_event']={'source':'EA官网FC27官方情报；只读','data':{'documents':[
            {'title':'活动','source_url':'https://www.ea.com/games/ea-sports-fc/fc-27/news/synthetic',
             'published_at':'2026-01-05','event_date':None,'text':'<img src=x onerror=bad()>'},
            {'title':'坏链接','source_url':'https://[','text':'未知'}]}}
        before=copy.deepcopy((r,e));html=render(r,e)
        self.assertNotIn('<script>unsafe()',html);self.assertIn('&lt;script&gt;unsafe()',html)
        self.assertNotIn('href="javascript:',html);self.assertNotIn('<img src=x',html)
        self.assertIn('事件日期：未独立核实',html);self.assertEqual((r,e),before)


if __name__=='__main__':unittest.main()

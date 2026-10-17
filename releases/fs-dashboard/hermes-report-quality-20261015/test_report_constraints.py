import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from decimal import Decimal

from test_support import SOURCE_ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from boss_projection import project
from boss_renderer import render
from report_constraints import review_paragraph,complete_projection,native_envelope
from report_delivery import deliver_output

HERE=Path(__file__).resolve().parent
QUEUE='ev_80552fde601a2693e42aa184'


class PrefacedEnvelope(unittest.TestCase):
    def setUp(self):
        f=json.loads((HERE/'inputs/real-07-fixture.json').read_text('utf-8'))
        self.result,self.evidence=f['result'],f['evidence']
        self.value={'report_contract':'fs-report-v2','summary':'两期金额已核；机制待证。',
            'comparison_period':{'start':'2026-10-06','end':'2026-10-07'},
            'research_text':'## 关键判断\n\n不用 sale_total≈order_count 推断单件或排除数量/组合效应。',
            'findings':[{'statement':'机制待证。','claim_type':'hypothesis','evidence_ids':[]}],
            'actions':[{'target':'当前未结池','action':'只读核队列。','condition':'依现行规则',
                'success_check':'老年池数量在两份快照间净减少，或每单有明确处置路径。','evidence_ids':[]}],
            'intel':{'status':'not_conducted','reason':'官方工具未接通。'},'limitations':[]}
        self.text='核平计算全部完成，现在输出成品。\n\n'+json.dumps(self.value,ensure_ascii=False)

    def test_delivery_recovers_one_prefaced_envelope_without_forging_original_format(self):
        book=SimpleNamespace(evidence=self.evidence,capture_id=self.result['snapshot_id'],target=self.result['period'])
        out=deliver_output(self.text,book)
        self.assertEqual(out['raw_model_text'],self.text)
        self.assertEqual(out['comparison_period'],self.value['comparison_period'])
        self.assertEqual(out['report_format'],'structured_v2_recovered')
        self.assertTrue(out['format_recovery'])
        self.assertEqual(len(out['actions']),1)
        self.assertEqual(out['intel'],[])
        self.assertTrue(any('intel' in x for x in out['limitations']))

    def test_saved_fallback_recovers_comparison_actions_and_both_profit_periods(self):
        import copy
        saved=dict(self.result,report_format='markdown',raw_model_text=self.text,research_text=self.text,
                   summary='未识别独立结论',findings=[],actions=[])
        saved.pop('comparison_period',None);before=copy.deepcopy(saved)
        c=project(saved,self.evidence,{'artifact_written_at':'2026-10-15T07:30:00+00:00'},'f'*64)
        self.assertEqual(c['report']['period']['comparison_start'],'2026-10-06')
        self.assertEqual(c['report']['period']['comparison_end'],'2026-10-07')
        self.assertEqual(len(c['actions']),1)
        self.assertEqual(c['finance']['estimates']['previous']['amount_usd'],'14709.61')
        self.assertIn('pool_outcome_unbound',{k for i in c['quality_review']['issues'] for k in i['codes']})
        self.assertIn('固定观察队列',c['actions'][0]['metric'])
        self.assertEqual(saved,before)

    def test_ambiguous_or_trailing_objects_are_not_silently_selected(self):
        self.assertIsNone(native_envelope(self.text+'\n{}'))
        self.assertIsNone(native_envelope('{}\n'+self.text))
        self.assertIsNone(native_envelope(self.text+'\n尾注'))

    def test_complete_group_population_can_supply_missing_standalone_total(self):
        ev={k:v for k,v in self.evidence.items() if not (v.get('query',{}).get('start')=='2026-10-06' and v.get('query',{}).get('group_by') in ([],['day']))}
        c=project(self.result,ev,{'artifact_written_at':'2026-10-15T07:30:00+00:00'},'f'*64)
        self.assertEqual(c['metrics'][0]['previous'],'$63,705.55')

    def test_incomplete_group_page_cannot_supply_population_total(self):
        ev={k:v for k,v in self.evidence.items() if v.get('query',{}).get('start')!='2026-10-06' or v.get('query',{}).get('group_by')==['country','payment']}
        ev={k:v for k,v in ev.items() if v.get('query',{}).get('start')!='2026-10-06' or v.get('data',{}).get('pagination',{}).get('complete') is True}
        c=project(self.result,ev,{'artifact_written_at':'2026-10-15T07:30:00+00:00'},'f'*64)
        self.assertIsNone(c['report']['period']['comparison_start'])

    def test_quantity_caution_is_kept_but_unverified_multi_item_assertion_is_withheld(self):
        bounds={'verified_quantity_price_discount':False,'payment_delta':{},'payment_evidence_ids':[]}
        self.assertEqual(review_paragraph(self.value['research_text'],bounds)[0],[])
        self.assertIn('quantity_mechanism_unbound',{k for k,_ in review_paragraph('样本含XBOX多件Items。',bounds)[0]})

    def test_percentage_band_trigger_remains_unapproved(self):
        self.value['actions'][0].update(target='参考利润率',condition='后续日率持续处于21-22%低位时',success_check='核实定义。')
        saved=dict(self.result,raw_model_text=json.dumps(self.value,ensure_ascii=False),report_format='markdown')
        c=project(saved,self.evidence,{'artifact_written_at':'2026-10-15T07:30:00+00:00'},'f'*64)
        self.assertIn('threshold_policy_unbound',{k for i in c['quality_review']['issues'] for k in i['codes']})


class TemporaryProfitPolicy(unittest.TestCase):
    def setUp(self):
        fixture=json.loads((HERE/'inputs/real-07-fixture.json').read_text('utf-8'))
        self.result,self.evidence=fixture['result'],fixture['evidence']
        self.native='ev_be331ab4c11f73e4e8f3cc49'
        self.prior='ev_ac89fcf9a5594bb7b2106c3b'
        self.daily='ev_48ea76821888959ebf86a9f4'

    def content(self):
        return project(self.result,self.evidence,{'artifact_written_at':'2026-10-15T06:10:00+00:00'},'f'*64)

    def records(self,key=None):
        return self.evidence[key or self.native]['data']['source_records']

    def metric(self):
        return next(iter(self.records().values()))['metrics']['profitMarginPct']

    def no_daily(self):
        self.evidence={k:r for k,r in self.evidence.items() if not r.get('source','').startswith('Order参考利润')}

    def test_real_period_formula_and_source_disclosure(self):
        c=self.content();now,prior=(c['finance']['estimates'][k] for k in ('current','previous'))
        self.assertEqual(now['amount_usd'],'14448.12');self.assertEqual(prior['amount_usd'],'14709.61')
        self.assertEqual(now['reference_margin_percent'],'26.31');self.assertEqual(prior['reference_margin_percent'],'23.09')
        self.assertEqual(now['method'],'period_amount_times_period_reference_percent')
        self.assertIn('www.mmoexp.com',now['sources'][0]['scope']['reported_channels'])
        self.assertIn('eldorado.gg',prior['sources'][0]['scope']['reported_channels'])
        self.assertTrue(now['sources'][0]['captured_at'])
        h=render(c,self.evidence)
        for text in ('14,448.12','14,709.61','非实际结算','26.31%','23.09%','order.p2pah.cn','渠道完整性未知'):
            self.assertIn(text,h)

    def test_estimate_rows_do_not_replace_the_report_title_period(self):
        h=render(self.content(),self.evidence)
        import re
        self.assertTrue(re.search(r'<title>(.*?)</title>',h)[1].endswith('2026-10-13—2026-10-14'))

    def test_native_record_selected_by_actual_system_not_primary_label(self):
        records=self.records();record=records.pop('primary');records['supplement']=record
        records['primary']={'system':'admin.p2pah.cn','status':'available','metrics':{'profitMarginPct':{'status':'available','unit':'percent','value':99}}}
        self.assertEqual(self.content()['finance']['estimates']['current']['amount_usd'],'14448.12')

    def test_valid_zero_is_not_missing(self):
        self.metric()['value']=0
        now=self.content()['finance']['estimates']['current']
        self.assertEqual(now['status'],'estimated');self.assertEqual(now['amount_usd'],'0.00')

    def test_negative_reference_allows_estimated_loss(self):
        self.metric()['value']=-5
        self.assertEqual(self.content()['finance']['estimates']['current']['amount_usd'],'-2745.75')

    def test_wrong_percent_unit_not_guessed(self):
        self.no_daily();self.metric()['value']=.2631;self.metric()['unit']='fraction'
        self.assertEqual(self.content()['finance']['estimates']['current']['status'],'missing')

    def test_missing_boolean_and_nonfinite_not_zero_filled(self):
        self.no_daily()
        for value in (None,True,'NaN','Infinity'):
            self.metric()['value']=value
            with self.subTest(value=value):
                now=self.content()['finance']['estimates']['current']
                self.assertEqual(now['status'],'missing');self.assertIsNone(now['amount_usd'])

    def test_wrong_period_not_borrowed(self):
        self.no_daily();next(iter(self.records().values()))['period']['end']='2026-10-16 00:00'
        self.assertEqual(self.content()['finance']['estimates']['current']['status'],'missing')

    def test_conflicting_native_rate_not_hidden_by_daily_fallback(self):
        row=copy.deepcopy(self.evidence[self.native]);row['data']['source_records']['primary']['metrics']['profitMarginPct']['value']=99
        self.evidence['ev_'+'f'*24]=row
        now=self.content()['finance']['estimates']['current']
        self.assertEqual(now['status'],'missing');self.assertIn('冲突',now['reason'])

    def test_missing_prior_does_not_erase_current(self):
        del self.evidence[self.prior]
        self.evidence={k:r for k,r in self.evidence.items() if not (r.get('source','').startswith('Order参考利润') and r['query']['start']=='2026-10-06')}
        estimates=self.content()['finance']['estimates']
        self.assertEqual(estimates['current']['amount_usd'],'14448.12');self.assertEqual(estimates['previous']['status'],'missing')

    def test_daily_fallback_multiplies_matched_days_and_never_averages_rates(self):
        del self.evidence[self.native]
        now=self.content()['finance']['estimates']['current']
        self.assertEqual(now['method'],'sum_matching_daily_amount_times_reference_percent')
        exact=sum(Decimal(row['main_revenue_usd'])*Decimal(row['reference_margin_percent'])/100 for row in now['daily_terms'])
        self.assertEqual(Decimal(now['amount_unrounded_usd']),exact)
        average=sum(Decimal(row['reference_margin_percent']) for row in now['daily_terms'])/2
        self.assertNotEqual(exact,Decimal(now['main_revenue_usd'])*average/100)

    def test_daily_missing_or_wrong_unit_or_wrong_date_is_not_used(self):
        del self.evidence[self.native];original=copy.deepcopy(self.evidence[self.daily])
        for change in ('missing','unit','date'):
            row=copy.deepcopy(original);value=row['data']['rows'][0]
            if change=='missing':value['profitMarginPct']=None
            elif change=='unit':value['marginUnit']='fraction'
            else:value['date']='2026-10-12'
            self.evidence[self.daily]=row
            with self.subTest(change=change):self.assertEqual(self.content()['finance']['estimates']['current']['status'],'missing')

    def test_daily_same_day_conflict_withheld(self):
        del self.evidence[self.native];row=copy.deepcopy(self.evidence[self.daily]);row['data']['rows'][0]['profitMarginPct']=99
        self.evidence['ev_'+'f'*24]=row
        now=self.content()['finance']['estimates']['current']
        self.assertEqual(now['status'],'missing');self.assertIn('冲突',now['reason'])


class Real07Constraints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=json.loads((HERE/'inputs/real-07-fixture.json').read_text('utf-8'))
        cls.result,cls.evidence=fixture['result'],fixture['evidence']

    def content(self,evidence=None,result=None):
        return project(result or self.result,evidence or self.evidence,{'artifact_written_at':'2026-10-15T05:03:09+00:00'},'f'*64)

    def test_complete_multi_axis_pool_is_projected_and_reconciled(self):
        chart=self.content()['charts'][4]
        self.assertEqual([r['value'] for r in chart['rows']],[92,86,137,255,587])
        self.assertEqual(sum(r['value'] for r in chart['rows']),1157)
        self.assertIn(QUEUE,chart['evidence_ids'])
        self.assertIn('2026-10-15',chart['snapshot_at'])

    def test_full_country_payment_pages_supply_known_country(self):
        context=self.content()['context'][0]
        self.assertIn('8,933.14',context['text'])
        self.assertTrue(context['evidence_ids'])

    def test_payment_residual_is_withheld_with_computed_expected_value(self):
        c=self.content();issues=c['quality_review']['issues']
        self.assertTrue(any('payment_residual_mismatch' in i['codes'] for i in issues))
        self.assertTrue(any('-4,541.44' in reason for i in issues for reason in i['reasons']))
        self.assertNotIn('其余通道净 −$464.60',c['reviewed_research_text'])
        self.assertIn('其余通道净 −$464.60',c['research_text'])

    def test_aggregate_identity_assertion_is_withheld_on_all_surfaces(self):
        c=self.content()
        self.assertFalse(c['evidence_constraints']['stable_order_intersection_verified'])
        self.assertTrue(any('cohort_intersection_unbound' in i['codes'] for i in c['quality_review']['issues']))
        self.assertNotIn('它们现在还挂在问题状态里',c['reviewed_research_text'])

    def test_unknown_unit_mechanism_is_not_a_verified_finding(self):
        c=self.content()
        self.assertFalse(c['evidence_constraints']['verified_quantity_price_discount'])
        self.assertTrue(any('quantity_mechanism_unbound' in i['codes'] for i in c['quality_review']['issues']))
        self.assertNotIn('也不是件数叠加',c['reviewed_research_text'])

    def test_unapproved_threshold_is_not_executable_action(self):
        c=self.content();action=c['actions'][1]
        self.assertNotIn('≥$200',action['steps'])
        self.assertIn('待确认',action['metric'])
        self.assertTrue(any('threshold_policy_unbound' in i['codes'] for i in c['quality_review']['issues']))

    def test_total_pool_ratio_is_not_successful_cohort_outcome(self):
        c=self.content();action=c['actions'][3]
        self.assertIn('真实完成',action['metric'])
        self.assertNotIn('over14d占比下降',action['metric'])
        self.assertTrue(any('pool_outcome_unbound' in i['codes'] for i in c['quality_review']['issues']))

    def test_summary_has_no_markdown_table_or_label_only_block(self):
        c=self.content()
        self.assertNotIn('|',c['executive']['summary'])
        self.assertNotEqual(c['executive']['summary'],'事实（观察）：')
        self.assertTrue(all('方法使用' not in h['text'] for h in c['hypotheses']))

    def test_comparison_and_all_original_inputs_are_preserved(self):
        before=json.dumps([self.result,self.evidence],sort_keys=True,ensure_ascii=False)
        c=self.content()
        self.assertEqual(c['report']['period']['comparison_start'],'2026-10-06')
        self.assertEqual(c['research_text'],self.result['raw_model_text'])
        self.assertEqual(before,json.dumps([self.result,self.evidence],sort_keys=True,ensure_ascii=False))

    def test_native_json_and_following_body_recovery_is_disclosed(self):
        book=SimpleNamespace(evidence=self.evidence,capture_id=self.result['snapshot_id'],target=self.result['period'])
        d=deliver_output(self.result['raw_model_text'],book)
        self.assertEqual(d['raw_model_text'],self.result['raw_model_text'])
        self.assertTrue(d['format_recovery'])
        self.assertEqual(d['report_format'],'structured_v2_recovered')
        self.assertEqual(len(d['findings']),7)
        self.assertEqual(len(d['actions']),5)
        self.assertEqual(d['delivery_status'],'ready')
        self.assertEqual(d['business_review_status'],'issues_withheld')
        self.assertTrue(d['summary'].startswith('[证据约束待复核]'))

    def test_real_html_has_public_review_and_pool_not_empty(self):
        c=self.content();html=render(c,self.evidence)
        self.assertIn('id="evidence-review"',html)
        self.assertIn('未作为审核后结论展示',html)
        self.assertTrue(c['charts'][4]['rows'])

    def test_short_pool_page_is_withheld(self):
        e=copy.deepcopy(self.evidence);e[QUEUE]['data']['groups'].pop()
        self.assertFalse(self.content(e)['charts'][4]['rows'])

    def test_filtered_pool_cannot_be_shown_as_all(self):
        e=copy.deepcopy(self.evidence);e[QUEUE]['query']['filters']={'platform':'PS'};e[QUEUE]['data']['filters_applied']={'platform':'PS'}
        self.assertFalse(self.content(e)['charts'][4]['rows'])

    def test_duplicate_group_tuple_is_rejected(self):
        e=copy.deepcopy(self.evidence);e[QUEUE]['data']['groups'][1]=copy.deepcopy(e[QUEUE]['data']['groups'][0])
        self.assertFalse(self.content(e)['charts'][4]['rows'])

    def test_different_capture_is_not_merged(self):
        e=copy.deepcopy(self.evidence);e[QUEUE]['captured_at']='2026-10-15T00:00:00+00:00'
        self.assertFalse(self.content(e)['charts'][4]['rows'])

    def test_missing_country_page_is_not_full_coverage(self):
        e={k:copy.deepcopy(r) for k,r in self.evidence.items() if not(r.get('query',{}).get('group_by')==['country','payment'] and r['query'].get('page')==3)}
        self.assertFalse(self.content(e)['context'][0]['evidence_ids'])

    def test_multi_axis_unknown_or_missing_grain_cannot_marginalize(self):
        for value in (None,'raw_order_lines'):
            with self.subTest(value=value):
                e=copy.deepcopy(self.evidence)
                if value is None:e[QUEUE]['data'].pop('source_grain',None)
                else:e[QUEUE]['data']['source_grain']=value
                self.assertFalse(self.content(e)['charts'][4]['rows'])

    def test_changed_group_total_is_rejected(self):
        e=copy.deepcopy(self.evidence);e[QUEUE]['data']['total']['orders']+=1
        self.assertFalse(self.content(e)['charts'][4]['rows'])

    def test_unpriced_group_is_rejected(self):
        e=copy.deepcopy(self.evidence);e[QUEUE]['data']['groups'][0]['unpriced_orders']=1
        self.assertFalse(self.content(e)['charts'][4]['rows'])


class GeneralizedReviewContracts(unittest.TestCase):
    def bounds(self):
        return {'joint_product_status':False,'stable_order_intersection_verified':False,'verified_quantity_price_discount':False,
                'payment_delta':{'bank_A':'-80','wallet_B':'20','wire_C':'5','card_D':'-15'},'payment_evidence_ids':[]}

    def test_residual_uses_selected_set_for_different_names_and_amounts(self):
        bad,_=review_paragraph('bank_A −$80、wallet_B +$20，其余净 −$5。',self.bounds())
        good,_=review_paragraph('bank_A −$80、wallet_B +$20，其余净 −$10。',self.bounds())
        self.assertTrue(any(code=='payment_residual_mismatch' for code,_ in bad));self.assertFalse(good)

    def test_nonprimary_net_is_valid_when_only_primary_excluded(self):
        reasons,_=review_paragraph('bank_A −$80，其余通道净 +$10。',self.bounds())
        self.assertFalse(reasons)

    def test_missing_payment_population_does_not_silently_pass_residual(self):
        bounds=self.bounds();bounds['payment_delta']={}
        reasons,_=review_paragraph('其余通道净 −$15。',bounds)
        self.assertTrue(any(code=='payment_partition_unavailable' for code,_ in reasons))

    def test_pronoun_after_comma_keeps_item_subject(self):
        reasons,_=review_paragraph('那8笔高价Items单，它们现在还挂在问题状态里。',self.bounds())
        self.assertTrue(any(code=='cohort_intersection_unbound' for code,_ in reasons))

    def test_caveat_in_another_clause_does_not_certify_single_item(self):
        reasons,_=review_paragraph('单件高价驱动，优惠未核实。',self.bounds())
        self.assertTrue(any(code=='quantity_mechanism_unbound' for code,_ in reasons))

    def test_unknown_unit_caveat_is_preserved(self):
        reasons,_=review_paragraph('sale_total单位未知，不能证明单件或排除多件。',self.bounds())
        self.assertFalse(reasons)

    def test_joint_grouping_does_not_certify_individual_identity(self):
        bounds=self.bounds();bounds['joint_product_status']=True
        reasons,_=review_paragraph('这些Items订单全部未交付。',bounds)
        self.assertTrue(any(code=='cohort_intersection_unbound' for code,_ in reasons))

    def test_two_separate_groups_with_unknown_intersection_are_kept(self):
        reasons,_=review_paragraph('10笔Items与10笔问题订单交集未知，不能说它们全部未交付。',self.bounds())
        self.assertFalse(reasons)

    def test_native_save_survives_optional_audit_without_marking_it_passed(self):
        book=SimpleNamespace(evidence={},capture_id='fc-detail-no-clock',target={'start':'2026-10-13','end':'2026-10-14'})
        text='当前没有可核业务证据，保留缺口。'
        result=deliver_output(text,book)
        self.assertEqual(result['raw_model_text'],text)
        self.assertEqual(result['quality_review']['status'],'not_evaluable')
        self.assertTrue(any('未能完成' in line for line in result['limitations']))


if __name__=='__main__':unittest.main()

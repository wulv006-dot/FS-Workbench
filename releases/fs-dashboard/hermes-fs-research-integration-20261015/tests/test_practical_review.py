"""Synthetic regressions derived from local frozen daily/weekly/pricing reports.

Only semantic wording is retained; all amounts, payment names and populations
below are invented test inputs, not operating data or copied report bodies.
"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from report_constraints import apply_constraints, review_paragraph, reviewed_text


def bounds(payments=None):
    return {'verified_quantity_price_discount': False,
            'stable_order_intersection_verified': False,
            'payment_delta': payments or {}, 'payment_evidence_ids': []}


def content(text='先调查 PS Coins；价格机制待证。'):
    return {'report': {'period': {'start': '2026-01-01', 'end': '2026-01-02'},
                       'snapshot_id': 'synthetic', 'business_data_captured_at': '2026-01-03T00:00:00Z'},
            'metrics': [{'status': 'fact'}], 'payment': [], 'payment_evidence_ids': [],
            'research_text': text, 'reviewed_research_text': text,
            'executive': {'summary': text}, 'key_findings': [], 'hypotheses': [],
            'actions': [], 'corrections': []}


class PracticalReviewTests(unittest.TestCase):
    def test_negative_daily_wording(self):
        # daily-reviewed-result: local semantic excerpt, no business values.
        text='不写"单件""数量驱动""降价"等未证表述。'
        self.assertEqual(review_paragraph(text, bounds())[0], [])

    def test_negative_weekly_wording(self):
        # weekly-reviewed-result: reproduced semantic sentence, no report body.
        text='数量、规格与优惠字段未取得：不推断“单件高价”或“提价”；'
        self.assertEqual(review_paragraph(text, bounds())[0], [])

    def test_pricing_unit_is_unverified(self):
        # pricing-final-result semantic excerpt; sample counts removed.
        text='商品样本部分分页、sale_total 单位未证、标题不可推数量。'
        self.assertEqual(review_paragraph(text, bounds())[0], [])

    def test_evidence_request_and_hypothesis_remain_visible(self):
        for text in ['核实单件数量、规格和优惠后再讨论。',
                     '假说：高客单可能由单件高价驱动，建议核对订单行。']:
            ledger=[]
            self.assertEqual(reviewed_text(text,bounds(),ledger,'test'), text)
            self.assertEqual(ledger, [])

    def test_unknown_payment_residual_keeps_direction(self):
        text='优先调查 PS Coins。其余通道 +$12.00，分组范围待核。'
        ledger=[]
        actual=reviewed_text(text,bounds(),ledger,'summary')
        self.assertIn(text,actual)
        self.assertEqual(ledger[0]['severity'],'warning')
        self.assertEqual(ledger[0]['status'],'visible_with_uncertainty')

    def test_one_cent_mismatch_is_visible_warning(self):
        text='FastPay +$3.00，其余通道 +$7.01。'
        ledger=[]
        actual=reviewed_text(text,bounds({'FastPay':'3','Card':'7'}),ledger,'test')
        self.assertIn(text,actual)
        self.assertEqual(ledger[0]['codes'],['payment_residual_mismatch'])
        self.assertEqual(ledger[0]['severity'],'warning')

    def test_opposite_payment_direction_blocks_only_related_sentence(self):
        text='先查 PS Coins。FastPay -$3.00。其余通道 +$7.00。PC继续观察。'
        ledger=[]
        actual=reviewed_text(text,bounds({'FastPay':'-3','Card':'-7'}),ledger,'test')
        self.assertIn('先查 PS Coins。',actual)
        self.assertIn('PC继续观察。',actual)
        self.assertNotIn('其余通道 +$7.00',actual)
        self.assertEqual(ledger[0]['severity'],'error')

    def test_withdrawn_payment_quote_is_not_a_new_assertion(self):
        text='撤回“FastPay +$3.00，其余通道 -$7.00”的旧说法。先核全量分组。'
        ledger=[]
        self.assertEqual(reviewed_text(text,bounds({'FastPay':'3','Card':'7'}),ledger,'test'),text)
        self.assertEqual(ledger,[])

    def test_unbound_quantity_assertion_does_not_hide_adjacent_action(self):
        text='客单变化值得调查。已证明由单件高价驱动。先核对规格。'
        ledger=[]
        actual=reviewed_text(text,bounds(),ledger,'test')
        self.assertIn('客单变化值得调查。',actual)
        self.assertIn('先核对规格。',actual)
        self.assertNotIn('已证明由单件高价驱动',actual)
        self.assertEqual(ledger[0]['codes'],['quantity_mechanism_unbound'])

    def test_unbound_individual_intersection_is_still_blocked(self):
        ledger=[]
        actual=reviewed_text('Items它们全部未完成。先检查页面。',bounds(),ledger,'test')
        self.assertNotIn('Items它们全部未完成',actual)
        self.assertIn('先检查页面。',actual)
        self.assertEqual(ledger[0]['codes'],['cohort_intersection_unbound'])

    def test_advice_after_assertion_does_not_excuse_assertion(self):
        ledger=[]
        actual=reviewed_text('这些Items全部未交付，建议核对关联。',bounds(),ledger,'test')
        self.assertNotIn('这些Items全部未交付',actual)
        self.assertEqual(ledger[0]['severity'],'error')

    def test_warning_does_not_change_original_line_reference(self):
        ledger=[]
        reviewed_text('其余通道 +$12.00。\n\n单件高价驱动。',bounds(),ledger,'test')
        self.assertEqual([entry['line'] for entry in ledger],[1,3])

    def test_schedule_age_filter_and_coverage_do_not_erase_actions(self):
        c=content()
        action={'title':'账龄观察','trigger':'观察账龄>14天的队列',
                'steps':'先核对20个样本，2天内复查页面和单位。','metric':'样本覆盖是否充分',
                'stop':'发现单位矛盾时暂停推断','risk':'不自动退款','evidence_ids':[]}
        c['actions']=[copy.deepcopy(action)]
        result=apply_constraints(c,{})
        for key in ['title','trigger','steps','metric','stop']:
            self.assertEqual(result['actions'][0][key],action[key])
        self.assertEqual(result['quality_review']['status'],'warnings_visible')
        self.assertFalse(result['quality_review']['actions_executed'])

    def test_pool_outcome_remains_signal_with_warning(self):
        c=content()
        c['actions']=[{'title':'账龄池复查','trigger':'观察','steps':'记录新流入和退出',
                       'metric':'高龄占比下降作为观察信号','stop':'无事件不作成效判断',
                       'risk':'只读观察','evidence_ids':[]}]
        result=apply_constraints(c,{})
        self.assertEqual(result['actions'][0]['metric'],'高龄占比下降作为观察信号')
        self.assertIn('固定队列',result['actions'][0]['risk'])
        self.assertEqual(result['quality_review']['issues'][0]['severity'],'warning')

    def test_warning_preserves_executive_and_original(self):
        text='先查 PS Coins。其余通道 +$12.00，分组待核。'
        c=apply_constraints(content(text),{})
        self.assertIn('先查 PS Coins',c['executive']['summary'])
        self.assertEqual(c['research_text'],text)
        self.assertEqual(c['quality_review']['status'],'warnings_visible')
        self.assertEqual(c['quality_review']['error_count'],0)
        self.assertGreater(c['quality_review']['warning_count'],0)
        self.assertIn('未测得',c['executive']['confidence_unknown'])

    def test_missing_population_is_not_passed(self):
        c=content();c['metrics'][0]['status']='missing'
        self.assertEqual(apply_constraints(c,{})['quality_review']['status'],'not_evaluable')


if __name__=='__main__':
    unittest.main()

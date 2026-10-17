import json,unittest
from types import SimpleNamespace
from report_validation import decode_output,validate_output
from report_html import render_report


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.ref='ev_'+'a'*24
        self.evidence={self.ref:{'source':'Admin FC支付明细','query':{'start':'2026-10-05','end':'2026-10-11','group_by':[],'filters':{}},'data':{'status':'available','total':{'orders':2,'revenue_usd':'10.00','known_revenue_usd':'10.00','average_order_usd':'5.00','unpriced_orders':0}}}}
        self.book=SimpleNamespace(evidence=self.evidence,capture_id='fixture')
        self.value={'summary':'合成调查。','findings':[{'statement':'已知金额$10.00。','claim_type':'fact','evidence_ids':[self.ref],'alternative':'','missing':''}],
                    'actions':[{'target':'样本','action':'复核$10.00金额。','condition':'仍待核验','cost_risk':'人工时间','review_at':'次日','success_check':'对应到证据','evidence_ids':[self.ref]}],
                    'reviews':[],'limitations':[],'number_claims':[{'report_field':'/findings/0/statement','text':'10.00','evidence_id':self.ref,'path':'/data/total/known_revenue_usd','scale':'as_stored'},{'report_field':'/actions/0/action','text':'10.00','evidence_id':self.ref,'path':'/data/total/known_revenue_usd','scale':'as_stored'}]}
    def test_intro_single_complete_json_preserves_values_and_ambiguity_refuses(self):
        raw=json.dumps(self.value,ensure_ascii=False)
        self.assertEqual(decode_output('调查结果如下。\n```json\n'+raw+'\n```'),self.value)
        for bad in ('```json\n'+raw+'\n```\n```json\n'+raw+'\n```','```json\n'+raw[:-2]+'\n```'):
            with self.assertRaises(ValueError):decode_output(bad)
    def test_only_real_action_pointer_alias_and_exact_amount(self):
        self.value['number_claims'][1]['report_field']='/actions/0/statement'
        output=validate_output(json.dumps(self.value),self.book)
        self.assertEqual(output['actions'],self.value['actions'])
        self.assertEqual(output['format_normalizations'][0]['to'],'/actions/0/action')
        self.value['actions'][0]['action']='复核其他对象。'
        with self.assertRaisesRegex(ValueError,'number_claim_reference'):validate_output(json.dumps(self.value),self.book)
    def test_short_date_is_label_but_amount_still_bound(self):
        self.value['findings'][0]['statement']='日期10-05 金额$10.00。'
        self.assertTrue(validate_output(json.dumps(self.value),self.book)['analysis_completed'])
        self.value['findings'][0]['statement']='日期10-05 金额$99.00。'
        with self.assertRaisesRegex(ValueError,'unbound_report_number'):validate_output(json.dumps(self.value),self.book)
        for statement in ('退款比例增加10-11个百分点','成本增加10-11 USD','订单减少10-11笔','金额$10-11','普通范围10-11'):
            self.value['findings'][0]['statement']=statement
            with self.assertRaisesRegex(ValueError,'unbound_report_number'):validate_output(json.dumps(self.value),self.book)
    def test_product_labels_require_cited_exact_title_and_do_not_exempt_values(self):
        self.evidence[self.ref]['query']['kind']='product_sales'
        self.evidence[self.ref]['data']['rows']=[{'title':'1500 K coins'}]
        self.value['findings'][0]['statement']='“1500 K coins”金额$10.00。'
        self.assertTrue(validate_output(json.dumps(self.value),self.book)['analysis_completed'])
        self.value['findings'][0]['statement']='“900 K coins”金额$10.00。'
        with self.assertRaisesRegex(ValueError,'unbound_report_number'):validate_output(json.dumps(self.value),self.book)
    def test_html_escapes_every_model_and_source_field_has_evidence_and_no_remote_assets(self):
        self.value['summary']='恶意文本 <script>bad()</script>'
        self.evidence[self.ref]['data']['label']='</pre><img src="https://invalid.test">'
        raw=render_report(self.value,self.evidence,{'start':'2026-10-05','end':'2026-10-11'})
        self.assertNotIn('<script',raw);self.assertNotIn('<img',raw)
        self.assertIn('&lt;script&gt;',raw);self.assertIn('id="'+self.ref+'"',raw)
        self.assertIn('href="#'+self.ref+'"',raw);self.assertIn('$10.00',raw)
        self.assertIn('未执行',raw);self.assertIn('@media print',raw)
    def test_html_does_not_add_totals_from_duplicate_dimensions_or_fill_missing_money(self):
        second='ev_'+'b'*24
        self.evidence[second]=json.loads(json.dumps(self.evidence[self.ref]))
        self.evidence[second]['query']['group_by']=['platform']
        self.evidence[second]['data']['total']['revenue_usd']=None
        raw=render_report(self.value,self.evidence,{'start':'2026-10-05','end':'2026-10-11'})
        self.assertEqual(raw.count('目标完整期间'),3)
        self.assertNotIn('$20.00',raw)

    def test_summary_only_numeric_reference_and_displayed_metric_have_offline_details(self):
        second='ev_'+'b'*24
        self.evidence[second]=json.loads(json.dumps(self.evidence[self.ref]))
        self.evidence[second]['query']['filters']={'platform':'PS'}
        self.value['findings'][0]['evidence_ids']=[second];self.value['actions'][0]['evidence_ids']=[second]
        self.value['summary']='已读$10.00。'
        for claim in self.value['number_claims']:claim['evidence_id']=second
        self.value['number_claims'].append({'report_field':'/summary','text':'10.00','evidence_id':self.ref,'path':'/data/total/known_revenue_usd','scale':'as_stored'})
        result=validate_output(json.dumps(self.value),self.book)
        raw=render_report(result,self.evidence,{'start':'2026-10-05','end':'2026-10-11'})
        self.assertIn('id="'+self.ref+'"',raw);self.assertIn('href="#'+self.ref+'"',raw)
        self.assertIn('id="'+second+'"',raw)


if __name__=='__main__':unittest.main()

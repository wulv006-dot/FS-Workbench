from copy import deepcopy
from pathlib import Path
import unittest
from research import ResearchBook, calculation
from skill_bundle import load_bundle


def dataset():
    row={'id':'NEVER-SEND-RAW-ORDER-ID','site_group':'main','platform':'PS','product':'Coins',
         'amount_cents':1000,'paid_at':'2026-10-05T12:00:00+08:00','created_at':'2026-10-05T11:00:00+08:00',
         'status':'问题单','issue':True,'backlog':True,'funding':False,'terminal':False,
         'country':'US','payment':'CardPay','device':'Mobile','password':'NEVER-SEND-SECRET'}
    other={**row,'id':'second','product':'Boosting','amount_cents':None,'country':'user@example.com'}
    return {'snapshot_id':'fc-detail-fixture','as_of':'2026-10-13T15:00:00+00:00',
            'coverage':{'period':{'start':'2026-09-28 00:00','end':'2026-10-12 00:00'},'paid_complete':True,
                        'missing_days':[],'backlog_status':'available'},'orders':[row,other],'backlog':[row,other]}


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.book=ResearchBook(dataset(),{}, {'start':'2026-10-05','end':'2026-10-11'},skills=load_bundle(Path(__file__).parent))

    def query(self,**change):
        args={'start':'2026-10-05','end':'2026-10-11','group_by':['country','product'],'filters':{},'page':1};args.update(change)
        return self.book.call('fc.query_business',args)

    def test_cross_dimensions_include_other_products_without_secret_or_order_ids(self):
        result=self.query();text=str(result)
        self.assertIn('Boosting',text)
        for value in ('NEVER-SEND','user@example.com','password'):self.assertNotIn(value,text)
        self.assertIsNone(result['data']['total']['revenue_usd'])
        self.assertEqual(result['data']['total']['known_revenue_usd'],'10.00')
        self.assertEqual(result['data']['total']['unpriced_orders'],1)

    def test_filtered_followup_adds_evidence_and_cannot_mutate_old_result(self):
        first=self.query();second=self.query(filters={'product':'Coins'},group_by=['platform'])
        self.assertNotEqual(first['evidence_id'],second['evidence_id'])
        self.assertEqual(second['data']['total']['orders'],1)
        first['data']['total']['orders']=999
        self.assertEqual(self.book.evidence[first['evidence_id']]['data']['total']['orders'],2)

    def test_partial_missing_day_is_not_complete_or_zero(self):
        self.book.data['coverage']['missing_days']=['2026-10-06']
        self.assertEqual(self.query()['data']['status'],'partial')
        self.assertEqual(self.query(start='2025-10-05',end='2025-10-11')['data']['status'],'not_covered')

    def test_queue_age_does_not_invent_delivery_progress(self):
        result=self.book.call('fc.query_queue',{'group_by':['age_band','progress','platform'],'filters':{},'page':1})
        self.assertEqual(result['data']['groups'][0]['group']['progress'],'not_provided')
        self.assertEqual(result['data']['groups'][0]['group']['age_band'],'7to14d')
        self.book.data['coverage']['backlog_status']='partial'
        self.assertEqual(self.book.call('fc.query_queue',{'group_by':[],'filters':{},'page':1})['data']['status'],'partial')

    def test_arbitrary_queries_and_paths_denied(self):
        for change in ({'sql':'DROP'},{'group_by':['password']},{'filters':{'country':'user@example.com'}},{'page':0}):
            with self.assertRaises((ValueError,TypeError)):self.query(**change)
        with self.assertRaises(PermissionError): self.book.research('shell',{})

    def test_sample_errors_and_reference_gaps_are_preserved(self):
        clues={'status':'not_sent','reason':'collector_busy'};self.book.clues=lambda:clues
        result=self.book.call('fc.get_problem_clues',{})
        self.assertEqual(result['data']['reason'],'collector_busy')
        result=self.book.call('fc.query_reference',{'profile':'FC27','start':'2026-10-05','end':'2026-10-11'})
        self.assertEqual(result['data']['status'],'not_available')

    def test_workbuddy_arithmetic_contradictions_recomputed(self):
        def compute(op,v):
            ref=self.book.register('fixture',{}, {'benchmark_values':v},'合成算术基准')['evidence_id']
            return self.book.call('fc.calculate',{'operation':op,'values':v,'evidence_ids':[ref],
                'value_paths':[{'evidence_id':ref,'path':f'/data/benchmark_values/{i}'} for i in range(len(v))],'assumptions':['']*len(v)})['data']['result']
        self.assertEqual(compute('interval_overlap',['92.62','97.67','88.48','93.98']),{'overlap':True,'start':'92.62','end':'93.98'})
        self.assertEqual(compute('extrema',['68.75','69.81','69.17'])['maximum'],'69.81')
        result=compute('difference',['31623.20','28085.29'])
        self.assertEqual(result['delta'],'-3537.91');self.assertEqual(result['relative_change_pct'],'-11.19')
        self.assertIsNone(compute('difference',['0','10'])['relative_change_pct'])

    def test_target_progress_and_unknown_reference_are_not_completion(self):
        result=calculation({'operation':'required_daily','values':['1000','500','5'],'evidence_ids':['fixture']})['result']
        self.assertEqual(result['required_daily'],'100.00');self.assertFalse(result['target_completed'])

    def test_calculation_requires_existing_evidence_and_no_code(self):
        with self.assertRaises(ValueError):self.book.call('fc.calculate',{'operation':'sum','values':['1'],'evidence_ids':['fabricated']})
        with self.assertRaises(ValueError):calculation({'operation':'sum','values':['__import__("os")'],'evidence_ids':['fixture']})

    def test_calculation_operands_bind_exact_fields_and_assumptions_stay_scenarios(self):
        ref=self.query()['evidence_id']
        args={'operation':'sum','values':['999.00'],'evidence_ids':[ref],
              'value_paths':[{'evidence_id':ref,'path':'/data/total/known_revenue_usd'}],'assumptions':['']}
        with self.assertRaisesRegex(ValueError,'calculation_operand_mismatch'):self.book.call('fc.calculate',args)
        args['values']=['10.00'];self.assertEqual(self.book.call('fc.calculate',args)['data']['result']['sum'],'10.00')
        args.update(values=['999.00'],value_paths=[None],assumptions=['假设销售目标，不是实际销售'])
        self.assertEqual(self.book.call('fc.calculate',args)['data']['basis'],'declared_scenario')

    def test_methods_are_loaded_on_request_only(self):
        result=self.book.call('fc.read_skill',{'topic':'methods'})
        self.assertIn('先核每行代表什么',result['text']);self.assertEqual(result['permissions'],[])

    def test_background_is_explicit_context_without_fact_authority(self):
        from fs_inprocess import approved_background
        self.book.background=approved_background(Path(__file__).parent)
        index=self.book.call('fc.read_skill',{'topic':'background'})
        section=self.book.call('fc.read_skill',{'topic':'background','section_id':index['sections'][1]['id']})
        self.assertEqual(section['authority'],'context_only');self.assertEqual(section['permissions'],[])
        with self.assertRaises(ValueError):self.book.call('fc.read_skill',{'topic':'background','section_id':'../../secret'})


if __name__=='__main__':unittest.main()

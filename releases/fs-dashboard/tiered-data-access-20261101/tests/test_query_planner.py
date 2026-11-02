import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from query_contract import normalize
from query_planner import plan
from date_policy import PolicyError


class Planner(unittest.TestCase):
    def setUp(self):
        self.cap=dict(contract='fs-data-capability-v2',policy_version='fixture',dataset_id='orders.detail',scope=dict(site_id='266',game_id='1327'),timezone='Asia/Shanghai',allowed_modes=['fresh','archive'],budget_profiles=['bounded'],
                      live=dict(enabled=True,earliest_available_date='2026-08-01',earliest_allowed_live_date='2026-08-01',latest_available_end_exclusive='2026-11-01',max_query_span=dict(unit='calendar_months',value=3)),
                      archive=dict(enabled=True,max_query_span=dict(unit='calendar_years',value=1),coverage_intervals=[dict(start='2026-08-01',end_exclusive='2026-11-01')]))
        self.dataset=dict(dataset_id='orders.detail',source='Admin',verified=True,kind='detail',grains=['detail'],fields=['order_id','amount'],filters={'status':['paid','refunded']},source_max_slice=dict(unit='days',value=28),date_semantics='paid_at')
        self.req=dict(dataset_id='orders.detail',site_id='266',game_id='1327',start='2026-08-01',end_exclusive='2026-11-01',timezone='Asia/Shanghai',grain='detail',fields=['amount','order_id'],mode='fresh',budget_profile='bounded',reason='fixture comparison',policy_version='fixture')
        self.budgets={'bounded':dict(max_requests=20,max_rows=10000,max_bytes=1000000,interactive_slices=2)}

    def test_three_month_request_pushes_every_scope_field_and_exact_range(self):
        value=plan(self.req,self.cap,self.dataset,self.budgets)
        self.assertEqual(value['status'],'queued'); self.assertFalse(value['complete'])
        self.assertIsNone(value['estimated_requests'])
        self.assertEqual(value['slices'][0]['start'],self.req['start'])
        self.assertEqual(value['slices'][-1]['end_exclusive'],self.req['end_exclusive'])
        for i,item in enumerate(value['slices']):
            self.assertEqual((item['site_id'],item['game_id']),('266','1327'))
            self.assertEqual(item['date_semantics'],'paid_at')
            self.assertEqual(item['fields'],['amount','order_id'])
            if i:self.assertEqual(value['slices'][i-1]['end_exclusive'],item['start'])

    def test_native_summary_is_whole_range_even_with_detail_slice_profile(self):
        self.dataset['kind']='native_summary'
        value=plan(self.req,self.cap,self.dataset,self.budgets)
        self.assertEqual(len(value['slices']),1)

    def test_archive_never_plans_source_requests(self):
        value=plan(dict(self.req,mode='archive'),self.cap,self.dataset,self.budgets)
        self.assertFalse(value['network_allowed']); self.assertEqual(value['slices'],[])

    def test_unknowns_sql_url_wrong_scope_or_missing_date_fail_before_plan(self):
        for change in [dict(sql='SELECT *'),dict(url='https://example.test'),dict(site_id=''),dict(site_id='other'),dict(start=''),dict(fields=['email']),dict(filters={'sql':'x'})]:
            with self.subTest(change=change),self.assertRaises(PolicyError):plan(dict(self.req,**change),self.cap,self.dataset,self.budgets)
        self.dataset['verified']=False
        with self.assertRaisesRegex(PolicyError,'verification'):plan(self.req,self.cap,self.dataset,self.budgets)

    def test_filter_hash_uses_same_normalization_and_is_not_full_cache_key(self):
        a=normalize(dict(self.req,filters={'status':'paid'}),self.cap,self.dataset)
        b=normalize(dict(self.req,fields=['order_id','amount'],reason='different reason',filters={'status':'paid'}),self.cap,self.dataset)
        c=normalize(dict(self.req,filters={'status':'refunded'}),self.cap,self.dataset)
        self.assertEqual(a['filter_hash'],b['filter_hash']); self.assertNotEqual(a['filter_hash'],c['filter_hash'])

    def test_budget_never_silent_truncates_or_accepts_unverified_cursor(self):
        self.budgets['bounded']['max_requests']=1
        with self.assertRaisesRegex(PolicyError,'budget_exhausted'):plan(self.req,self.cap,self.dataset,self.budgets)
        with self.assertRaisesRegex(PolicyError,'cursor_requires'):plan(dict(self.req,cursor='untrusted'),self.cap,self.dataset,self.budgets)

if __name__=='__main__':unittest.main()

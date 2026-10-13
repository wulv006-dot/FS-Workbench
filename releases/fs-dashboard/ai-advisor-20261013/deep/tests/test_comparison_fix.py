import copy,json,unittest
from test_model_fix import load,ROOT
from test_scope_fix import build
from test_deep import model_response
model=load('comparison_model',ROOT/'comparison_fix/source/fc_deep_model.py')
publisher=load('comparison_publisher',ROOT/'comparison_fix/deploy/release_navigation.py')

class ComparisonFix(unittest.TestCase):
    def response(self,refs,text='同比和前一工作日均走高'):
        e=build();raw=model_response(e);body=json.loads(raw['choices'][0]['message']['content']);f=body['findings'][0]
        f['refs']=refs;f['observation']=text;f['title']=text;f['verify']['metric']='average_order_usd'
        raw['choices'][0]['message']['content']=json.dumps(body,ensure_ascii=False)
        return e,raw,f
    def test_real_sunday_previous_day_not_called_workday(self):
        e,r,f=self.response(['compare.previous','compare.week_ago','compare.baseline7','compare.baseline30'])
        out=model.validate(r,model.project(e))['findings'][0]
        self.assertEqual(out['fact_origin'],'server_verified_period_comparisons')
        self.assertIn('前一完整日',out['observation']);self.assertIn('上周同日',out['observation'])
        self.assertNotIn('工作日',out['observation']);self.assertNotIn('同比',out['title'])
        self.assertEqual(out['action'],f['action']);self.assertEqual(out['verify'],f['verify'])
    def test_direction_comes_from_actual_values_not_model(self):
        e,r,_=self.response(['compare.previous'],'所有指标上涨')
        comparison=next(f['value'] for f in e['evidence'] if f['ref']=='compare.previous')
        comparison['values']['orders'].update(current=2,baseline=3)
        comparison['values']['revenue_usd'].update(current=5,baseline=4)
        comparison['values']['average_order_usd'].update(current=4,baseline=4)
        out=model.validate(r,model.project(e))['findings'][0]['observation']
        self.assertIn('订单量低于前一完整日',out);self.assertIn('销售额高于前一完整日',out);self.assertIn('客单价等于前一完整日',out)
    def test_longer_period_not_labeled_day(self):
        e,r,_=self.response(['compare.previous']);e['plan']['end']='2026-10-13'
        out=model.validate(r,model.project(e))['findings'][0]['observation']
        self.assertIn('前一等长完整期间',out);self.assertNotIn('前一完整日',out)
    def test_missing_values_remain_missing(self):
        e,r,_=self.response(['compare.previous'])
        c=next(f['value'] for f in e['evidence'] if f['ref']=='compare.previous');c['values']['orders']['baseline']=None
        self.assertIn('订单量缺少可比数据',model.validate(r,model.project(e))['findings'][0]['observation'])
    def test_unknown_period_fails_closed(self):
        e,r,_=self.response(['compare.previous']);next(f['value'] for f in e['evidence'] if f['ref']=='compare.previous')['baseline']='year_ago'
        with self.assertRaises(model.InvalidStatement):model.validate(r,model.project(e))
    def test_pool_and_problem_sample_still_use_separate_canonical_facts(self):
        e,r,_=self.response(['backlog.current','compare.previous'])
        self.assertEqual(model.validate(r,model.project(e))['findings'][0]['fact_origin'],'server_verified_backlog_populations')
    def test_prompt_and_projection_have_explicit_period_contract(self):
        p=model.project(build());self.assertEqual(p['contract'],'fc-owner-analysis-v6')
        self.assertIn('不是上年同比',model.messages(p)[0]['content']);self.assertIn('工作日历',model.messages(p)[0]['content'])
    def test_single_file_publisher_preserves_peer_final_boss(self):
        stage=ROOT/'comparison_fix/deploy';m=json.loads((stage/'approved-manifest.json').read_text())
        self.assertEqual(len(publisher.validate(m,stage)),1)
        guard=next(r for r in m['unchangedRequired'] if r['path'].endswith('/boss_insights.py'))
        self.assertEqual(guard['sha256'],'ab8e249864fdee350d3d35cdf83995e473112b17f86281a331f14581a65d189c')

if __name__=='__main__':unittest.main()

import copy,json,unittest
from test_model_fix import load,ROOT
from test_scope_fix import build
from test_deep import model_response
model=load('calendar_model',ROOT/'calendar_fix/source/fc_deep_model.py')
publisher=load('calendar_publisher',ROOT/'calendar_fix/deploy/release_navigation.py')

class CalendarFix(unittest.TestCase):
    def response(self,field,text,refs=None):
        e=build();raw=model_response(e);body=json.loads(raw['choices'][0]['message']['content']);item=body['findings'][0]
        item[field]=text
        if refs:item['refs']=refs
        raw['choices'][0]['message']['content']=json.dumps(body,ensure_ascii=False);return e,raw
    def test_calendar_is_computed_not_recalled(self):
        p=model.project(build());self.assertEqual(p['calendar']['start_weekday'],'星期一')
        self.assertFalse(p['calendar']['weekday_effect_verified']);self.assertEqual(p['contract'],'fc-owner-analysis-v5')
        self.assertEqual(model.calendar_context('2026-10-10','2026-10-12')['target_weekdays'],['星期一','星期六','星期日'])
    def test_unsupported_weekday_hypothesis_is_explicitly_qualified(self):
        e,r=self.response('hypothesis','周六本身或存在周末节奏差异。')
        f=model.validate(r,model.project(e))['findings'][0]
        self.assertEqual(f['qualification'],'weekday_effect_not_verified')
        self.assertNotIn('周六',f['hypothesis']);self.assertIn('不能',f['hypothesis'])
    def test_weekday_fact_is_not_published(self):
        for key in ('title','observation'):
            e,r=self.response(key,'周六销售强劲')
            with self.assertRaises(model.InvalidStatement):model.validate(r,model.project(e))
    def test_ordinary_period_comparison_stays_usable(self):
        e,r=self.response('observation','与前一完整日相比销售上升，但低于近七日日均。')
        f=model.validate(r,model.project(e))['findings'][0];self.assertNotIn('qualification',f)
    def test_sample_fact_not_replaced_by_duplicate_pool_fact(self):
        e,r=self.response('observation','样本值得核查',['order.problem_sample','backlog.current'])
        e['evidence'].append({'ref':'order.problem_sample','kind':'sample_clues','value':{'sampled':12,'categories':{'unclear':9,'credentials':3}}})
        f=model.validate(r,model.project(e))['findings'][0]
        self.assertEqual(f['fact_origin'],'server_verified_problem_sample');self.assertIn('多数',f['observation']);self.assertNotIn('至少一周',f['observation'])
    def test_single_model_publisher_protects_new_analysis(self):
        stage=ROOT/'calendar_fix/deploy';m=json.loads((stage/'approved-manifest.json').read_text())
        self.assertEqual(len(publisher.validate(m,stage)),1)
        guard=next(r for r in m['unchangedRequired'] if r['path'].endswith('/fc_deep_analysis.py'))
        self.assertEqual(guard['sha256'],'2879ab1d70f02af59e88d78cef563132fa9d98c1f273527de7d707d7185a4ceb')

if __name__=='__main__':unittest.main()

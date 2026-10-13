import json,unittest
from test_model_fix import load,ROOT
from test_scope_fix import build
from test_deep import model_response
model=load('fact_model',ROOT/'fact_fix/source/fc_deep_model.py')
publisher=load('fact_publisher',ROOT/'fact_fix/deploy/release_navigation.py')

class FactFix(unittest.TestCase):
    def response(self,refs):
        e=build();r=model_response(e);body=json.loads(r['choices'][0]['message']['content']);f=body['findings'][0]
        f['refs']=refs;f['title']='平台与品类合计增量';f['observation']='另一个平台下跌，所有日均都低于当日。'
        r['choices'][0]['message']['content']=json.dumps(body);return e,r,f
    def test_all_platforms_up_cannot_publish_invented_negative(self):
        e,r,f=self.response(['contribution.platform'])
        c=next(f for f in e['evidence'] if f['ref']=='contribution.platform')
        c['value']=[{'label':n,'revenue_delta_usd':v} for n,v in [('XBOX',1988.68),('PS',1007.89),('PC',201.8)]]
        out=model.validate(r,model.project(e))['findings'][0]
        self.assertEqual(out['fact_origin'],'server_verified_structure_contributions')
        self.assertIn('XBOX、PS、PC销售额增加',out['observation']);self.assertNotIn('减少',out['observation'])
        self.assertNotIn('日均',out['observation']);self.assertEqual(out['action'],f['action'])
    def test_signs_and_dimensions_are_kept_separate(self):
        e,r,_=self.response(['contribution.platform','contribution.product'])
        for ref,rows in [('contribution.platform',[('XBOX',2),('PC',0)]),('contribution.product',[('Coins',4),('Items',-2)])]:
            next(f for f in e['evidence'] if f['ref']==ref)['value']=[{'label':n,'revenue_delta_usd':v} for n,v in rows]
        out=model.validate(r,model.project(e))['findings'][0]['observation']
        self.assertIn('PC销售额持平',out);self.assertIn('Items销售额减少',out);self.assertIn('不能跨维度相加',out)
    def test_fact_without_supported_narrative_is_bounded(self):
        e,r,_=self.response(['target.main']);out=model.validate(r,model.project(e))['findings'][0]
        self.assertEqual(out['fact_origin'],'server_verified_evidence_boundary');self.assertNotIn('下跌',out['observation'])
    def test_all_findings_keep_model_action_and_canonical_fact_origin(self):
        e,r,_=self.response(['compare.previous']);out=model.validate(r,model.project(e))['findings'][0]
        self.assertEqual(out['fact_origin'],'server_verified_period_comparisons')
        self.assertEqual(model.project(e)['contract'],'fc-owner-analysis-v7')
    def test_publisher_only_model_with_peer_guard(self):
        stage=ROOT/'fact_fix/deploy';m=json.loads((stage/'approved-manifest.json').read_text())
        self.assertEqual(len(publisher.validate(m,stage)),1)
        self.assertIn('ab8e249864fdee350d3d35cdf83995e473112b17f86281a331f14581a65d189c',[x['sha256'] for x in m['unchangedRequired']])

if __name__=='__main__':unittest.main()

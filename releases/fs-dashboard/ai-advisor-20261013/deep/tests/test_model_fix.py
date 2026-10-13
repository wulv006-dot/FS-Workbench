import copy,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_deep import evidence,model_response

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
model=load('fc_deep_model_validation_fix',ROOT/'model_fix/source/fc_deep_model.py')
publisher=load('fc_deep_model_fix_publisher',ROOT/'model_fix/deploy/release_navigation.py')

class ModelFix(unittest.TestCase):
    def response(self,text,field='hypothesis'):
        raw=model_response(evidence());body=json.loads(raw['choices'][0]['message']['content']);body['findings'][0][field]=text
        raw['choices'][0]['message']['content']=json.dumps(body);return raw
    def test_honest_short_hypotheses_and_negated_claims(self):
        for text in ('暂无','待验证','无法确定根因','不能声称已退款','未确认已执行建议','避免自动改价'):
            with self.subTest(text=text):self.assertEqual(model.validate(self.response(text),model.project(evidence()))['status'],'succeeded')
    def test_positive_execution_and_separate_positive_clause_rejected(self):
        for text in ('已退款所有订单','确定根因是库存','不能批量改价；已退款所有订单','已经保证收益','建议立即调价'):
            with self.subTest(text=text),self.assertRaises(ValueError):model.validate(self.response(text),model.project(evidence()))
    def test_unknown_numbers_still_rejected(self):
        with self.assertRaises(model.InvalidStatement) as error:model.validate(self.response('预计增长百分之987654'),model.project(evidence()))
        self.assertEqual(error.exception.detail,{'field':'hypothesis','reason':'numeric_or_markup'})
    def test_safe_diagnostic_does_not_store_response_or_context(self):
        raw=self.response('预计增长百分之987654')
        with patch.object(model,'request_model',side_effect=lambda messages,p,validator,**kw:validator(raw,p)):
            result=model.explain(model.project(evidence()))
        self.assertEqual(result['validation_detail'],{'field':'hypothesis','reason':'numeric_or_markup'})
        self.assertNotIn('987654',json.dumps(result));self.assertEqual(result['response_id'],'receipt-test')
    def test_projection_revision_distinguishes_failed_original(self):
        self.assertEqual(model.project(evidence())['contract'],'fc-owner-analysis-v2')
    def test_nonempty_length_required(self):
        with self.assertRaises(ValueError):model.validate(self.response('   '),model.project(evidence()))
    def test_publisher_scope_exactly_one_existing_model(self):
        stage=ROOT/'model_fix/deploy';m=json.loads((stage/'approved-manifest.json').read_text('utf-8'))
        self.assertEqual(len(publisher.validate(m,stage)),1)
        self.assertEqual(publisher.expected_files(m),{'deep/fc_deep_model.py'})
        for mutation in ('absent_baseline','missing_shared_guard','extra_target'):
            bad=copy.deepcopy(m)
            if mutation=='absent_baseline':bad['files'][0]['beforeSha256']=None
            elif mutation=='missing_shared_guard':bad['unchangedRequired']=[r for r in bad['unchangedRequired'] if not r['path'].endswith('/boss_insights.py')]
            else:bad['files'].append(dict(bad['files'][0],candidate='deep/range_api.py'))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):publisher.validate(bad,stage)

if __name__=='__main__':unittest.main()

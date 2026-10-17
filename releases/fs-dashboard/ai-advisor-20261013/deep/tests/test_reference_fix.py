import json,unittest
from unittest.mock import patch
from test_model_fix import load,ROOT
from test_deep import evidence,model_response
model=load('fc_deep_reference_fix',ROOT/'reference_fix/source/fc_deep_model.py')
publisher=load('fc_deep_reference_fix_publisher',ROOT/'reference_fix/deploy/release_navigation.py')

class ReferenceFix(unittest.TestCase):
    def response(self,refs):
        raw=model_response(evidence());body=json.loads(raw['choices'][0]['message']['content']);body['findings'][0]['refs']=refs
        raw['choices'][0]['message']['content']=json.dumps(body);return raw
    def test_actual_nested_fact_is_canonicalized_without_guessing(self):
        p=model.project(evidence());r=model.validate(self.response(['target.main.orders','target.main.revenue_usd']),p)
        self.assertEqual(r['findings'][0]['refs'],['target.main'])
    def test_unknown_fact_or_child_still_rejected(self):
        p=model.project(evidence())
        for ref in ('made-up','target.main.net_profit','target.unknown.orders'):
            with self.subTest(ref=ref),self.assertRaises(model.InvalidReference) as failure:model.validate(self.response([ref]),p)
            self.assertEqual(failure.exception.detail['reason'],'unknown_evidence_reference')
    def test_broad_but_known_evidence_can_exceed_five_refs(self):
        p=model.project(evidence());refs=[f['ref'] for f in p['facts'][:6]]
        self.assertEqual(model.validate(self.response(refs),p)['findings'][0]['refs'],refs)
    def test_prompt_lists_literal_reference_allowlist(self):
        p=model.project(evidence());prompt=model.messages(p)[0]['content']
        self.assertIn(json.dumps([f['ref'] for f in p['facts']],ensure_ascii=False),prompt)
        self.assertEqual(p['contract'],'fc-owner-analysis-v3')
    def test_failure_diagnostic_is_specific_and_public_result_excludes_raw(self):
        raw=self.response(['missing.ref'])
        with patch.object(model,'save_failed_sample') as save,patch.object(model,'request_model',side_effect=lambda messages,p,validator,**kw:validator(raw,p)):
            r=model.explain(model.project(evidence()))
        save.assert_called_once();self.assertEqual(r['validation_detail'],{'field':'refs','reason':'unknown_evidence_reference','count':1,'references':['missing.ref']})
        self.assertNotIn('findings',r)
    def test_personal_context_or_question_is_not_retained_in_failure_sample(self):
        for p in ({'question':'私有问题'},{'memory':{'contexts':[{'text':'私有背景'}]}}):
            with patch('pathlib.Path') as path:model.save_failed_sample({},p,{});path.assert_not_called()
    def test_new_publisher_still_only_updates_model(self):
        stage=ROOT/'reference_fix/deploy';m=json.loads((stage/'approved-manifest.json').read_text('utf-8'))
        self.assertEqual([r['target'] for r in publisher.validate(m,stage)],['/opt/fs-exact-range-20261001/fc_deep_model.py'])

if __name__=='__main__':unittest.main()

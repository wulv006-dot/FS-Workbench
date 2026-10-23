import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('reference_view',Path(__file__).resolve().parents[1]/'source/reference_observer_view.py')
view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)


class ViewTests(unittest.TestCase):
    def test_projection_excludes_credentials_costs_and_unapproved_fields(self):
        record={'run_id':'same-id','status':'observed','costs':[{'secret':'must_not_leak'}],
                'itemd2r':[dict(source='ItemD2R',platform='PC',currency='USD',comparable=True,status='valid',
                               gross_usd='8.15',purchase_k='100',bonus_k='0',effective_usd_per_k='.0815',token='secret')],
                'simulation':{'status':'not_comparable_capture_span'}}
        result=view.project(record)
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(result['itemd2r'][0]['gross_usd'],'8.15')
        self.assertEqual(result['weighted'],[])

    def test_empty_and_corrupt_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'samples').mkdir()
            self.assertEqual(view.build_view(root)['observed_count'],0)
            (root/'samples/x.json').write_text('{')
            self.assertEqual(view.build_view(root)['read_failures'],1)

    def test_conditional_or_wrong_currency_not_valid(self):
        for changes in ({'currency':'EUR'},{'conditional':True},{'comparable':False}):
            row=dict(source='ItemD2R',platform='PS',status='valid',comparable=True,currency='USD',gross_usd='1')
            row.update(changes)
            self.assertIsNone(view.offers([row])[0]['gross_usd'])
        self.assertIsNone(view.number('NaN'))

    def test_original_lootbar_optional_comparable_contract(self):
        row=dict(source='Lootbar',platform='PS',status='valid',currency='USD',gross_usd='9.84',
                 purchase_k='100',bonus_k='5',effective_usd_per_k='0.093714285714285714')
        self.assertEqual(view.offers([row])[0]['status'],'valid')
        self.assertEqual(view.offers([row])[0]['bonus_k'],'5')

    def test_missing_view_and_unit_failure_explicit(self):
        with tempfile.TemporaryDirectory() as name,patch.object(view,'VIEW',Path(name)/'absent'),patch.object(view.subprocess,'run') as run:
            run.return_value.returncode=1
            result=view.read_view()
            self.assertEqual(result['observed_count'],0)
            self.assertEqual(result['service']['ActiveState'],'unknown')

    def test_partial_storefront_reason_and_absent_index_preserved(self):
        record={'simulation':{'status':'partial','weighted_platforms':{'PC':{
            'storefront_problem':'storefront_identity_unverified','unavailable_sources':{'IGGM':'missing'},
            'scenarios':[{'anchor_weight':'.6','weighted_unit':'.08'}, {'anchor_weight':'.7','weighted_unit':None}]}}}}
        result=view.project(record)
        self.assertEqual(len(result['weighted']),1)
        self.assertEqual(result['weighted'][0]['unavailable_sources'],['IGGM'])
        self.assertFalse(result['weighted'][0]['storefront_comparable'])

if __name__=='__main__':unittest.main()

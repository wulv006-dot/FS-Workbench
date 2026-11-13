import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import api
from fc_pricing_v3.ledger import Ledger
import pricing_operations as tools


class PricingReviewReads(unittest.TestCase):
    def test_review_state_keeps_financial_report_and_full_operation_read(self):
        report=dict(actual_profit_summary=dict(review_day=dict(paid_usd='12.34'),active_plan=dict(status='partial')))
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            db.put('metadata','latest_daily_review',report)
            for index in range(30):
                ident='00000000-0000-4000-8000-'+str(index).zfill(12)
                db.put('operations',ident,dict(operation_id=ident,created_at='2026-11-07T00:00:00+00:00',status='COMPLETED',
                    bundle=dict(action=dict(base_prices={'pc':'10'}),proof='x'*130000)))
            with patch.object(api,'ledger',return_value=db):
                original=api.read('state')
                compact=api.read('review-state')
                detail=api.read('operations/'+ident)
            self.assertGreater(len(json.dumps(original)),1024*1024)
            self.assertLess(len(json.dumps(compact)),1024*1024)
            self.assertEqual(compact['daily_review'],report)
            self.assertEqual(compact['daily_review_profit_status'],'available')
            self.assertEqual(len(compact['operations']),30)
            self.assertEqual(compact['operations'][0]['detail_source']['action'],'operation_read')
            self.assertEqual(detail['bundle']['proof'],'x'*130000)
            console_fields={'manual_execution','catalogue_readbacks'}
            self.assertEqual({key:original[key] for key in console_fields},
                             {'manual_execution':None,'catalogue_readbacks':{}})
            self.assertTrue(console_fields.isdisjoint(compact))
            self.assertEqual({k:v for k,v in original.items() if k not in console_fields | {'operations'}},
                             {k:v for k,v in compact.items() if k not in ('operations','daily_review_profit_status')})
            db.put('metadata','latest_daily_review',{'actual':{'orders':10}})
            with patch.object(api,'ledger',return_value=db):
                historical=api.read('review-state')
            self.assertEqual(historical['daily_review_profit_status'],'not_recorded')
            self.assertNotIn('actual_profit_summary',historical['daily_review'])

    def test_valid_quote_pointer_preserves_original_fragment(self):
        run='00000000-0000-4000-8000-000000000071'
        receipt={'sha256':'a'*64,'financial_proof':{'pass_all':True}}
        request=Mock(return_value=dict(run_id=run,path='/result/decision_receipt',value=receipt,original_quote_sha256='b'*64,execution_authorized=False))
        with patch.object(tools,'authorization',return_value=None):
            result=tools.call(Mock(),'owner','turn','lease',dict(action='read_quote',run_id=run,path='/result/decision_receipt'),request)
        request.assert_called_once_with('/quotes/'+run+'?'+urlencode({'path':'/result/decision_receipt'}),'owner')
        self.assertEqual(result['value'],receipt)
        self.assertFalse(result['execution_authorized'])

    def test_state_uses_compact_route_with_original_owner(self):
        request=Mock(return_value={'daily_review':{'actual_profit_summary':{'status':'partial'}}})
        with patch.object(tools,'authorization',return_value=None):
            result=tools.call(Mock(),'original-owner','turn','lease',{'action':'state'},request)
        request.assert_called_once_with('/pricing/v3/review-state','original-owner')
        self.assertIn('actual_profit_summary',result['daily_review'])

    def test_missing_quote_path_and_extra_state_path_return_action_requirements(self):
        request=Mock()
        for arguments,required in [({'action':'read_quote','run_id':'source'},['action','path','run_id']),
                                   ({'action':'state','path':'daily_review.actual_profit_summary'},['action'])]:
            with self.subTest(arguments=arguments):
                result=tools.call(Mock(),'owner','turn','lease',arguments,request)
                self.assertEqual(result['status'],'invalid_arguments')
                self.assertEqual(result['error_code'],'pricing_tool_fields')
                self.assertEqual(result['required_fields'],required)
                self.assertFalse(result['execution_authorized'])
        request.assert_not_called()
        schema=tools.schema()['function']
        self.assertIn('read_quote requires action, run_id, path',schema['description'])
        self.assertIn('/evidence',schema['parameters']['properties']['path']['description'])

    def test_original_smart_snapshot_reports_available_mode_without_recomputing(self):
        auth=dict(mode='daily_review',source_quote_run='source',source_quote_sha256='a'*64)
        saved=dict(snapshot_id='source',snapshot_sha256='a'*64,results={'smart':{'status':'experiment'}})
        request=Mock(return_value=saved)
        with patch.object(tools,'authorization',return_value=auth):
            missing=tools.call(Mock(),'owner','turn','lease',dict(action='compare_strategies',mode='daily'),request)
            valid=tools.call(Mock(),'owner','turn','lease',dict(action='compare_strategies',mode='smart'),request)
            self.assertEqual(missing['status'],'invalid_arguments')
            self.assertEqual(missing['error_code'],'pricing_review_mode_unavailable')
            self.assertEqual(missing['available_modes'],['smart'])
            self.assertEqual(valid['results'],saved['results'])
            saved['snapshot_sha256']='b'*64
            with self.assertRaisesRegex(ValueError,'pricing_review_run_basis_changed'):
                tools.call(Mock(),'owner','turn','lease',dict(action='compare_strategies',mode='smart'),request)
        self.assertTrue(all(len(call.args)==2 for call in request.call_args_list))

    def test_native_wire_limit_still_rejects_oversized_response(self):
        opener=Mock()
        opener.open.return_value=io.BytesIO(b'x'*(1024*1024+1))
        with patch.object(tools,'build_opener',return_value=opener):
            with self.assertRaisesRegex(ValueError,'pricing_native_reply_too_large'):
                tools.native('/pricing/v3/review-state','owner')


if __name__=='__main__':unittest.main()

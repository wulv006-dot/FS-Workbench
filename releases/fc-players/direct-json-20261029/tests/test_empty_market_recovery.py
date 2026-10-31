from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import test_direct_import as fixture
from 球员维护工具.admin_client import AdminHttpError
from player_web.repository import StateError

SCRIPT=Path(__file__).resolve().parents[2]/'empty-market-recovery-20261031/recover_original_eight.py'
spec=importlib.util.spec_from_file_location('empty_market_recovery',SCRIPT)
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)

direct=fixture.direct

class RecoveryBackend(fixture.Backend):
    def __init__(self,case):
        super().__init__(case);self.failed_dispatches=0;self.fail_corrected=False
    def intent(self,phase,fid):
        if phase!='add':return super().intent(phase,fid)
        events=self.case.repo.get_execution(self.case.execution,'operator')['events']
        found=[e for e in events if e['step'] in ('direct_add','direct_'+recovery.PHASE) and e['detail'].get('futbin_id')==fid]
        self.case.assertEqual(found[-1]['status'],'intent')
    def add_model(self,payload):
        if self.fail_corrected or any(e['value'] is None for e in payload['more']['extend']):
            self.failed_dispatches+=1
            raise AdminHttpError('null market',status=500,diagnostic={'http_status':500})
        return super().add_model(payload)

class EmptyMarketRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.DirectImportTests();self.case.setUp();self.addCleanup(self.case.tearDown)
        self.case.backend=RecoveryBackend(self.case)
        original=direct.build_model_payload
        def legacy(*args,**kwargs):
            value=original(*args,**kwargs)
            for e in value['more']['extend']:
                if e['key']=='pc_price':e['value']=None
            return value
        with patch.object(direct,'build_model_payload',legacy):self.case.plan(missing_pc=True,missing_policy='fallback_9999')
        self.patch=patch.object(recovery,'FIDS',{'23700'});self.patch.start();self.addCleanup(self.patch.stop)
        self.case.run_plan()
        self.assertEqual(self.case.backend.failed_dispatches,1)
    def recover(self,apply=True):
        c=self.case
        return recovery.recover_adds(c.settings,c.repo,c.backend,c.execution,c.frozen,apply=apply)
    def test_corrected_add_original_plan_then_normal_readback_and_zero_replay(self):
        c=self.case;before=deepcopy(c.frozen)
        report=self.recover(False);self.assertEqual(len(report),1);self.assertEqual(c.backend.calls,[])
        self.recover();result=c.run_plan()
        self.assertEqual(result['completed_futbin_ids'],['23700']);self.assertEqual(c.scopes(),[])
        self.assertEqual(c.frozen,before)
        self.assertEqual(c.backend.calls.count(('add','23700')),1)
        events=c.repo.get_execution(c.execution,'operator')['events']
        self.assertTrue(any(e['step']=='direct_add' and e['status']=='unknown' for e in events))
        calls=deepcopy(c.backend.calls);self.recover();c.run_plan();self.assertEqual(c.backend.calls,calls)
    def test_lost_corrected_response_reads_back_without_second_add(self):
        c=self.case;c.backend.lost_add.add('23700')
        with self.assertRaisesRegex(StateError,'NO_RETRY'):self.recover()
        calls=deepcopy(c.backend.calls);self.recover();self.assertEqual(c.backend.calls,calls)
        self.assertEqual(c.run_plan()['completed_futbin_ids'],['23700'])
    def test_corrected_error_cannot_dispatch_again(self):
        c=self.case;c.backend.fail_corrected=True
        for _ in range(2):
            with self.assertRaisesRegex(StateError,'NO_RETRY'):self.recover()
        self.assertEqual(c.backend.failed_dispatches,2)
        self.assertEqual(c.scopes(),['23700'])
    def test_wrong_original_result_or_foreign_payload_is_rejected(self):
        c=self.case
        with c.repo.connection() as db:
            db.execute("update events set detail_json=replace(detail_json,'500','502') where status='unknown'")
        with self.assertRaisesRegex(StateError,'ORIGINAL_HTTP500'):self.recover()
        self.assertEqual(c.backend.failed_dispatches,1)
        item=deepcopy(c.frozen['direct_items'][0]);item['payload']['more']['extend']=[{'key':'pc_price','value':'9999'}]
        with self.assertRaisesRegex(StateError,'NULL_PRICE_PROOF'):recovery.corrected_body(item)

if __name__=='__main__':unittest.main()

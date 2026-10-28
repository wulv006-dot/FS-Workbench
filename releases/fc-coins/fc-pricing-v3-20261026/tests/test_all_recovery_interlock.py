"""Original unsent ALL uses fresh proof without migrating an unresolved plan."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fixtures import fixture,NOW
from fc_pricing_v3 import runtime,adapters,uk_retirement
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.financial import LEGACY_FINANCIAL_CONTRACT_VERSION
import coin_all_sync_job as all_sync
from test_reconcile_original import all_step

PURPOSE='original_unsent_ALL_steps_only'
OP='00000000-0000-4000-8000-000000000080'


class ALLRecoveryInterlock(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        for name in ('jobs','executions','config'):(self.root/name).mkdir()
        self.db=Ledger(self.root/'control.sqlite3');self.db.activate_generation('g',[])
        self.addCleanup(patch.stopall)
        patch('fc_pricing_v3.ledger.clock',return_value=NOW).start()
        plan=self.db.create_plan('daily',['base:console','base:pc'],dict(base_prices=dict(console='20',pc='20'),region_coefficients={}))
        self.db.activate_plan(plan['plan_id']);self.plan=self.db.get('pricing_plans',plan['plan_id'])
        self.plan['financial_contract_version']=LEGACY_FINANCIAL_CONTRACT_VERSION
        self.db.put('pricing_plans',plan['plan_id'],self.plan)
        self.action=dict(base_prices=dict(console='20',pc='20'),region_coefficients={})
        self.op=dict(operation_id=OP,plan_id=plan['plan_id'],generation='g',resources=plan['resources'],status='UNKNOWN',
            steps=[dict(kind='base',step_id='original-base',state='CONFIRMED',dispatched_at=NOW.isoformat())],
            bundle=dict(plan_id=plan['plan_id'],action=self.action,mutable_resources=plan['resources'],budget_policy='none',
                        review_contract=runtime.PROGRAM_CONTRACT,financial_contract_version=LEGACY_FINANCIAL_CONTRACT_VERSION))
        self.db.put('operations',OP,self.op)
        self.data=fixture()[0];self.data['run_id']='original-all-refresh'
        self.job=dict(request=dict(v3_plan_id=plan['plan_id'],v3_operation_id=OP,v3_authorization_purpose=PURPOSE))
        self.save_job()
        self.audit=dict(execution_id=OP,status='PARTIAL',stage='all_baseline_pending',all_baseline=dict(status='pending'),
                        sync_confirmed=True,after=dict(rows=[dict(platform=p,b2c='.2') for p in runtime.PLATFORMS]))
        self.save_audit()
        (self.root/'config/v3-control.json').write_text(json.dumps(dict(enabled=True,generation='g')))
        patch.object(runtime,'ROOT',self.root).start();patch.object(runtime,'ledger',return_value=self.db).start()
        patch.object(runtime,'clock',return_value=NOW).start()
        self.base=patch.object(adapters,'dispatch_base',side_effect=AssertionError('no_new_Order_save_or_sync')).start()
        self.region=patch.object(adapters,'region_step',side_effect=AssertionError('no_region_write')).start()

    def save_job(self):
        (self.root/'jobs'/('original-all-refresh.json')).write_text(json.dumps(self.job))

    def save_audit(self):
        (self.root/'executions'/(OP+'.json')).write_text(json.dumps(self.audit))

    def quote(self,data=None):
        evidence=data or self.data
        return dict(evidence=evidence,result=runtime.calculate(evidence))

    def test_fresh_eight_day_front_door_preserves_original_id_price_unknown_and_double20(self):
        quote=self.quote();receipt=runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(runtime.PLATFORMS),
                                                       now=NOW,for_execution=True,purpose=PURPOSE)
        self.assertEqual(receipt['decision_bundle_id'],OP);self.assertEqual(receipt['original_operation_id'],OP)
        self.assertEqual(receipt['action'],self.action);self.assertEqual(receipt['steps'],[])
        self.assertTrue(receipt['financial_proof']['pass_all'])
        self.assertEqual(self.db.get('operations',OP),self.op)
        self.assertEqual(self.db.get('pricing_plans',self.plan['plan_id']),self.plan)
        self.base.assert_not_called();self.region.assert_not_called()
        with self.assertRaisesRegex(ValueError,'purpose_mismatch'):
            runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(runtime.PLATFORMS),now=NOW,for_execution=True)
        with self.assertRaisesRegex(ValueError,'margin_contract_changed'):
            runtime.verify_quote(quote,dict(minimum_gross_margin_pct='10'),list(runtime.PLATFORMS),now=NOW,for_execution=True,purpose=PURPOSE)

    def test_old_seven_day_evidence_cannot_enter_narrow_authority(self):
        data=fixture(legacy=True)[0];data['run_id']=self.data['run_id']
        with patch.object(runtime,'calculate_postwrite',side_effect=AssertionError('old_window_must_stop_before_authority')):
            with self.assertRaisesRegex(ValueError,'window_migration_required'):self.quote(data)
        self.assertEqual(self.db.get('operations',OP),self.op)

    def test_other_purposes_and_UK_new_write_keep_plan_migration_gate(self):
        for purpose in (None,'unknown',PURPOSE+'-other',uk_retirement.PURPOSE):
            with self.subTest(purpose=purpose):
                self.job['request']['v3_authorization_purpose']=purpose;self.save_job()
                with self.assertRaisesRegex(ValueError,'pricing_financial_plan_migration_required'):self.quote()
        self.base.assert_not_called();self.region.assert_not_called()

    def test_migration_still_rejects_unresolved_same_resource_without_mutation(self):
        self.plan['state']='SUSPENDED';self.db.put('pricing_plans',self.plan['plan_id'],self.plan)
        with self.assertRaisesRegex(ValueError,'pricing_resource_unresolved'):
            self.db.migrate_financial_contract(self.plan['plan_id'],self.plan['revision'],'operator')
        self.assertEqual(self.db.get('pricing_plans',self.plan['plan_id']),self.plan)
        self.assertEqual(self.db.get('operations',OP),self.op)

    def test_bad_history_missing_cost_and_unprofitable_catalog_still_reject(self):
        cases=[]
        data=deepcopy(self.data);data['historical_discount_mix']['sha256']='0'*64;cases.append((data,'historical_mix_hash_changed'))
        data=deepcopy(self.data);data['costs'].pop('PC');cases.append((data,None))
        data=deepcopy(self.data)
        for p in runtime.PLATFORMS:data['costs'][p]['cny_per_1k']='100'
        cases.append((data,None))
        for data,reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises((ValueError,KeyError)) as raised:self.quote(data)
                if reason:self.assertIn(reason,str(raised.exception))
                self.assertEqual(self.db.get('operations',OP),self.op)

    def test_exact_purpose_still_requires_original_operation_merchant_price_and_generation(self):
        self.audit['sync_confirmed']=False;self.save_audit()
        with self.assertRaisesRegex(ValueError,'merchant_unconfirmed'):self.quote()
        self.audit['sync_confirmed']=True;self.audit['after']['rows'][0]['b2c']='.21';self.save_audit()
        with self.assertRaisesRegex(ValueError,'actual_scope_invalid'):self.quote()
        self.audit['after']['rows'][0]['b2c']='.2';self.save_audit()
        changed=deepcopy(self.op);changed['generation']='retired';self.db.put('operations',OP,changed)
        with self.assertRaisesRegex(ValueError,'old_generation_read_only'):self.quote()
        self.db.put('operations',OP,self.op)
        self.job['request']['v3_operation_id']='missing-original';self.save_job()
        with self.assertRaisesRegex(ValueError,'original_operation_required'):self.quote()
        self.base.assert_not_called();self.region.assert_not_called()

    def test_fresh_authority_does_not_replay_any_dispatched_ALL_POST(self):
        quote=self.quote();steps=[all_step(p,'dispatching') for p in all_sync.PRODUCTS]
        record=dict(execution_id=OP,status='needs_reconcile',steps=steps)
        audit=dict(execution_id=OP,status='PARTIAL',sync_confirmed=True,
                   after=dict(rows=[dict(platform=p,b2c='12') for p in all_sync.PRODUCTS]))
        def api(manager,path,payload=None):
            self.assertIsNone(payload,'dispatched_ALL_must_never_POST_again')
            return dict(adminInfo=dict(username='approved'))
        with patch.object(all_sync,'api',side_effect=api),patch.object(all_sync,'allowed_admin_usernames',return_value={'approved'}),             patch.object(all_sync,'read_row',side_effect=lambda m,p,site:deepcopy(steps[list(all_sync.PRODUCTS).index(p)]['source' if site==266 else 'payload'])),             patch.object(all_sync,'drive',side_effect=AssertionError('already_dispatched_must_not_enter_writer')):
            result=all_sync.reconcile_original(object(),audit,record,lambda value:None,lambda value:None,lambda: {},
                                               current_quote=lambda:quote,sleep=lambda _:None)
        self.assertEqual(result['status'],'confirmed');self.assertEqual(result['all_posts_retried'],0)
        self.assertTrue(all(s['original_post_not_retried'] for s in steps))
        self.base.assert_not_called();self.region.assert_not_called()

    def test_unknown_ALL_not_at_target_stays_dispatching_even_with_fresh_authority(self):
        quote=self.quote();steps=[all_step(p,'dispatching') for p in all_sync.PRODUCTS]
        record=dict(execution_id=OP,status='needs_reconcile',steps=steps)
        audit=dict(execution_id=OP,status='PARTIAL',sync_confirmed=True,
                   after=dict(rows=[dict(platform=p,b2c='12') for p in all_sync.PRODUCTS]))
        with patch.object(all_sync,'api',return_value=dict(adminInfo=dict(username='approved'))) as api,             patch.object(all_sync,'allowed_admin_usernames',return_value={'approved'}),             patch.object(all_sync,'read_row',side_effect=lambda m,p,site:deepcopy(steps[list(all_sync.PRODUCTS).index(p)]['source' if site==266 else 'before'])),             patch.object(all_sync,'drive',side_effect=AssertionError('UNKNOWN_must_not_replay')):
            with self.assertRaisesRegex(ValueError,'coin_all_readback_mismatch'):
                all_sync.reconcile_original(object(),audit,record,lambda value:None,lambda value:None,lambda: {},
                                           current_quote=lambda:quote,sleep=lambda _:None)
        self.assertTrue(all(s['status']=='dispatching' for s in steps))
        self.assertTrue(all(len(c.args)<3 or c.args[2] is None for c in api.call_args_list))


if __name__=='__main__':unittest.main()

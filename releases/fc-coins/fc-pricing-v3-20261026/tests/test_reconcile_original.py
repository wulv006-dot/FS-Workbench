import json
import sqlite3
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import coin_all_sync_job as all_sync
import reconcile_original as recovery


OPERATION='00000000-0000-4000-8000-000000000080'


def all_step(platform,status):
    all_id,source_id,_=all_sync.PRODUCTS[platform]
    before=dict(id=all_id,unit_price='10',more=dict(price=['10'],gold=['100'],discount=['0'],give=['0']))
    source=dict(id=source_id,unit_price='12',more=dict(price=['12'],gold=['100'],discount=['0'],give=['0']))
    payload=deepcopy(before)
    payload['unit_price']='12'
    payload['more']['price']=['12']
    return dict(platform=platform,product_id=all_id,source_product_id=source_id,
                before=before,source=source,payload=payload,changed=True,status=status)


class OriginalReconciliation(unittest.TestCase):
    def test_all_dispatching_only_gets_confirmed_and_pending_needs_current_authority(self):
        steps=[all_step('PS','dispatching'),all_step('XBOX','pending'),all_step('PC','pending')]
        record=dict(execution_id=OPERATION,status='needs_reconcile',steps=steps)
        audit=dict(execution_id=OPERATION,status='PARTIAL',stage='all_baseline_pending',sync_confirmed=True,
                   after=dict(rows=[dict(platform=p,b2c='12') for p in all_sync.PRODUCTS]))
        actual={p:deepcopy(steps[i]['payload'] if i==0 else steps[i]['before']) for i,p in enumerate(all_sync.PRODUCTS)}
        persisted=[]
        def read_row(manager,platform,site):
            return deepcopy(steps[list(all_sync.PRODUCTS).index(platform)]['source'] if site==266 else actual[platform])
        def identity(manager,path,payload=None):
            self.assertIsNone(payload)
            return dict(adminInfo=dict(username='approved'))
        with patch.object(all_sync,'api',side_effect=identity),patch.object(all_sync,'read_row',side_effect=read_row),\
             patch.object(all_sync,'allowed_admin_usernames',return_value={'approved'}):
            result=all_sync.reconcile_original(object(),audit,record,lambda value:None,
                                                lambda value:persisted.append(deepcopy(value)),lambda: {},sleep=lambda _:None)
            self.assertEqual(result['status'],'requires_fresh_postwrite_authorization')
            self.assertEqual([s['status'] for s in steps],['confirmed','pending','pending'])
            self.assertEqual(audit['status'],'PARTIAL')
            actual={p:deepcopy(steps[i]['payload']) for i,p in enumerate(all_sync.PRODUCTS)}
            result=all_sync.reconcile_original(object(),audit,record,lambda value:None,
                                                lambda value:persisted.append(deepcopy(value)),lambda: {},sleep=lambda _:None)
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(audit['status'],'CONFIRMED')
        self.assertTrue(audit['sync_confirmed'])
        self.assertTrue(all(s['status']=='confirmed' for s in steps))
        self.assertTrue(all(s.get('original_post_not_retried') or s.get('observed_target_without_original_post_at') for s in steps))

    def test_all_unknown_dispatch_is_never_replayed_from_pending_looking_row(self):
        steps=[all_step(p,'dispatching' if p=='PS' else 'pending') for p in all_sync.PRODUCTS]
        record=dict(execution_id=OPERATION,status='needs_reconcile',steps=steps)
        audit=dict(execution_id=OPERATION,status='PARTIAL',sync_confirmed=True,
                   after=dict(rows=[dict(platform=p,b2c='12') for p in all_sync.PRODUCTS]))
        with patch.object(all_sync,'api',return_value=dict(adminInfo=dict(username='approved'))),\
             patch.object(all_sync,'allowed_admin_usernames',return_value={'approved'}),\
             patch.object(all_sync,'read_row',side_effect=lambda manager,p,site:deepcopy(
                 steps[list(all_sync.PRODUCTS).index(p)]['source'] if site==266 else steps[list(all_sync.PRODUCTS).index(p)]['before'])):
            with self.assertRaisesRegex(ValueError,'coin_all_readback_mismatch'):
                all_sync.reconcile_original(object(),audit,record,lambda value:None,lambda value:None,
                                            lambda: {},sleep=lambda _:None)
        self.assertEqual(steps[0]['status'],'dispatching')

    def test_only_unsent_all_steps_can_enter_original_drive_with_current_quote(self):
        steps=[all_step(p,'pending') for p in all_sync.PRODUCTS]
        record=dict(execution_id=OPERATION,status='needs_reconcile',steps=steps)
        audit=dict(execution_id=OPERATION,status='PARTIAL',sync_confirmed=True,
                   after=dict(rows=[dict(platform=p,b2c='12') for p in all_sync.PRODUCTS]))
        quote=lambda:dict(original='current_v3_verified')
        with patch.object(all_sync,'api',return_value=dict(adminInfo=dict(username='approved'))),\
             patch.object(all_sync,'allowed_admin_usernames',return_value={'approved'}),\
             patch.object(all_sync,'read_row',side_effect=lambda manager,p,site:deepcopy(
                 steps[list(all_sync.PRODUCTS).index(p)]['source'] if site==266 else steps[list(all_sync.PRODUCTS).index(p)]['before'])),\
             patch.object(all_sync,'drive',return_value=dict(status='confirmed')) as original_drive:
            result=all_sync.reconcile_original(object(),audit,record,lambda value:None,lambda value:None,
                                                lambda: {},current_quote=quote,sleep=lambda _:None)
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(original_drive.call_count,1)
        self.assertIs(original_drive.call_args.args[-1],quote)
        self.assertTrue(all(step['status']=='pending' for step in steps))

    def test_original_all_ps_step_uses_joint_console_proof_but_only_posts_ps(self):
        steps=[all_step(p,'pending') for p in all_sync.PRODUCTS]
        for step in steps[1:]:
            step['source']['unit_price']='10'
            step['source']['more']['price']=['10']
            step['payload']=deepcopy(step['before'])
            step['changed']=False
        actual={step['platform']:deepcopy(step['before']) for step in steps}
        record=dict(execution_id=OPERATION,status='reconciled_continuation',steps=steps)
        audit=dict(execution_id=OPERATION,status='PARTIAL',stage='all_baseline_pending',sync_confirmed=True)
        posts=[]
        def backend(manager,path,payload=None,observer=None):
            if payload is not None:
                posts.append(path)
                actual['PS']=deepcopy(payload)
            return {}
        def row(manager,platform,site):
            return deepcopy(steps[list(all_sync.PRODUCTS).index(platform)]['source'] if site==266 else actual[platform])
        with patch.object(all_sync,'validate',return_value={'PS':12,'XBOX':10,'PC':10}),\
             patch.object(all_sync,'api',side_effect=backend),patch.object(all_sync,'read_row',side_effect=row),\
             patch.object(all_sync,'verify_dispatch_readback'),\
             patch('automation_policy.hooks_before_write') as hooks:
            result=all_sync.drive(object(),audit,{},steps,record,lambda value:None,
                                  lambda value:None,lambda: {},current_quote=lambda:dict(valid=True))
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(hooks.call_args.args[1],['PS','XBOX'])
        self.assertEqual(posts,['/admin/goods.Goods/edit?id='+str(all_sync.PRODUCTS['PS'][0])])

    def test_original_all_pending_uses_current_postwrite_purpose_through_existing_hook(self):
        steps=[all_step(p,'pending') for p in all_sync.PRODUCTS]
        for step in steps[1:]:
            step['source']['unit_price']='10'
            step['source']['more']['price']=['10']
            step['payload']=deepcopy(step['before'])
            step['changed']=False
        actual={step['platform']:deepcopy(step['before']) for step in steps}
        record=dict(execution_id=OPERATION,status='reconciled_continuation',steps=steps)
        audit=dict(execution_id=OPERATION,status='PARTIAL',stage='all_baseline_pending',sync_confirmed=True)
        quote=dict(result=dict(decision_receipt=dict(authorization_purpose='original_unsent_ALL_steps_only')))
        posts=[]
        def backend(manager,path,payload=None,observer=None):
            if payload is not None:
                posts.append(path)
                actual['PS']=deepcopy(payload)
            return {}
        def row(manager,platform,site):
            return deepcopy(steps[list(all_sync.PRODUCTS).index(platform)]['source'] if site==266 else actual[platform])
        with patch.object(all_sync,'validate',return_value={'PS':12,'XBOX':10,'PC':10}),\
             patch.object(all_sync,'api',side_effect=backend),patch.object(all_sync,'read_row',side_effect=row),\
             patch.object(all_sync,'verify_dispatch_readback'),\
             patch('fc_pricing_v3.runtime.verify_quote',return_value=quote['result']['decision_receipt']) as verify:
            result=all_sync.drive(object(),audit,{},steps,record,lambda value:None,
                                  lambda value:None,lambda: dict(minimum_gross_margin_pct='20'),
                                  current_quote=lambda:quote)
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(posts,['/admin/goods.Goods/edit?id='+str(all_sync.PRODUCTS['PS'][0])])
        self.assertEqual(verify.call_args.args[2],['PS','XBOX'])
        self.assertEqual(verify.call_args.kwargs['purpose'],'original_unsent_ALL_steps_only')
        self.assertTrue(verify.call_args.kwargs['for_execution'])

    def test_deferred_all_does_not_make_original_audit_confirmed_without_fresh_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'executions').mkdir()
            (root/'all-coin-sync').mkdir()
            request=dict(execution_id=OPERATION,v3_operation_id=OPERATION,preview_id='preview',actor='operator',
                         platforms=['PS','XBOX'],policy_revision=3)
            before=[dict(platform=p,b2c='10',costPrice='5') for p in recovery.PLATFORMS]
            targets=[dict(platform=p,quote='12',targetCost='6') for p in recovery.PLATFORMS]
            audit=dict(execution_id=OPERATION,preview_id='preview',actor='operator',selected=['PS','XBOX'],
                       automation_policy_revision=3,status='CONFIRMED',sync_confirmed=True,
                       all_baseline=dict(status='deferred_before_dispatch'),before=dict(rows=before),targets=targets)
            path=root/'executions'/(OPERATION+'.json')
            path.write_text(json.dumps(audit))
            observed=dict(rows=[dict(platform=p,b2c='12' if p!='PC' else '10',
                                     costPrice='6' if p!='PC' else '5') for p in recovery.PLATFORMS])
            with patch.object(recovery,'read_admin',return_value=dict(basis='two_stable_original_admin_recipient_reads')),\
                 patch.object(recovery,'postwrite_quote',side_effect=ValueError('pricing_generation_retired')),\
                 patch.object(recovery,'atomic',side_effect=lambda target,value:target.write_text(json.dumps(value))),\
                 patch.object(recovery,'mirror_confirmed') as mirror:
                result=recovery.reconcile(request,root,order_reader=lambda _:observed,manager_factory=Mock())
            self.assertEqual(result['status'],'PARTIAL')
            self.assertEqual(result['reason'],'requires_fresh_postwrite_authorization')
            self.assertEqual(json.loads(path.read_text())['status'],'PARTIAL')
            mirror.assert_not_called()

    def test_fresh_all_authority_reads_existing_wal_without_initializing_ledger(self):
        run='00000000-0000-4000-8000-000000000081'
        action=dict(base_prices=dict(console='12',pc='12'),region_coefficients={})
        receipt=dict(action=action,engine_generation='generation-1',plan_id='plan-1',
                     decision_bundle_id=OPERATION,sha256='original-bundle-sha')
        operation=dict(operation_id=OPERATION,generation='generation-1',plan_id='plan-1',
                       dispatch_context=dict(actor='operator'),bundle=dict(action=action,plan_id='plan-1',sha256='original-bundle-sha',
                       resources=['base:console','base:pc'],mutable_resources=['base:console','base:pc']))
        plan=dict(plan_id='plan-1',revision=1,generation='generation-1',state='ACTIVE',ends_at='2030-01-01T00:00:00+00:00')
        audit=dict(actor='operator',run_id=run,pricing_decision_receipt=receipt,
                   after=dict(rows=[dict(platform=p,b2c='.12') for p in recovery.PLATFORMS]))
        quote=dict(evidence=dict(run_id=run),result=dict(decision_receipt=receipt))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'v3').mkdir()
            (root/'quotes').mkdir()
            (root/'quotes'/(run+'.json')).write_text(json.dumps(quote))
            owner=sqlite3.connect(root/'v3'/'control.sqlite3')
            try:
                owner.execute('PRAGMA journal_mode=WAL')
                for table in ('operations','pricing_plans','metadata','reservations'):
                    owner.execute('CREATE TABLE '+table+' (id TEXT PRIMARY KEY,body TEXT)')
                owner.execute('CREATE TABLE plan_ownership (resource TEXT PRIMARY KEY,plan_id TEXT,revision INTEGER,generation TEXT)')
                for table,key,value in [('operations',OPERATION,operation),('pricing_plans','plan-1',plan),
                                        ('metadata','generation',dict(id='generation-1')),
                                        ('reservations',OPERATION,dict(operation_id=OPERATION,plan_id='plan-1',state='RESERVED'))]:
                    owner.execute('INSERT INTO '+table+' VALUES (?,?)',(key,json.dumps(value)))
                for resource in ('base:console','base:pc'):
                    owner.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,'plan-1',1,'generation-1'))
                owner.commit()
                self.assertTrue((root/'v3'/'control.sqlite3-wal').exists())
                with patch('fc_pricing_v3.runtime.verify_quote',return_value=receipt) as verify,\
                     patch.object(recovery,'load_policy',return_value={}):
                    callback=recovery.postwrite_quote(OPERATION,audit,root)
                self.assertEqual(callback(),quote)
                self.assertTrue(verify.call_args.kwargs['for_execution'])
            finally:
                owner.close()

    def test_expired_original_plan_allows_same_generation_successor_only_for_original_all(self):
        run='00000000-0000-4000-8000-000000000082'
        original_action=dict(base_prices=dict(console='12',pc='12'),region_coefficients={'21:PS':'1.00'})
        fresh_action=dict(base_prices=dict(console='12.0',pc='12.00'),region_coefficients={'21:PS':'1.01'})
        original_receipt=dict(action=original_action,engine_generation='generation-1',plan_id='old-plan',
                              decision_bundle_id=OPERATION,sha256='original-sha')
        fresh_receipt=dict(action=fresh_action,engine_generation='generation-1',plan_id='new-plan',
                           revision=2,decision_bundle_id=OPERATION,sha256='fresh-sha',
                           authorization_purpose='original_unsent_ALL_steps_only')
        operation=dict(operation_id=OPERATION,generation='generation-1',plan_id='old-plan',
                       dispatch_context=dict(actor='operator'),bundle=dict(action=original_action,plan_id='old-plan',
                       sha256='original-sha',resources=['base:console'],mutable_resources=['base:console']))
        old=dict(plan_id='old-plan',revision=1,generation='generation-1',state='ENDING',
                 ends_at='2020-01-01T00:00:00+00:00')
        successor=dict(plan_id='new-plan',parent_plan_id='old-plan',revision=2,generation='generation-1',
                       state='ACTIVE',ends_at='2030-01-01T00:00:00+00:00')
        audit=dict(actor='operator',run_id=run,pricing_decision_receipt=original_receipt,
                   after=dict(rows=[dict(platform=p,b2c='.12') for p in recovery.PLATFORMS]))
        quote=dict(evidence=dict(run_id=run),result=dict(decision_receipt=fresh_receipt))
        authorization=dict(operation_id=OPERATION,original_operation_id=OPERATION,quote_run_id=run,
                           generation='generation-1',current_generation='generation-1',
                           authorizing_plan_id='new-plan',revision=2,quote_sha256='fresh-sha',
                           authorizes='original_unsent_ALL_steps_only')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'v3'/'postwrite-authorizations').mkdir(parents=True)
            (root/'quotes').mkdir()
            (root/'quotes'/(run+'.json')).write_text(json.dumps(quote))
            auth_path=root/'v3'/'postwrite-authorizations'/(OPERATION+'.json')
            auth_path.write_text(json.dumps(authorization))
            owner=sqlite3.connect(root/'v3'/'control.sqlite3')
            try:
                owner.execute('PRAGMA journal_mode=WAL')
                for table in ('operations','pricing_plans','metadata','reservations'):
                    owner.execute('CREATE TABLE '+table+' (id TEXT PRIMARY KEY,body TEXT)')
                owner.execute('CREATE TABLE plan_ownership (resource TEXT PRIMARY KEY,plan_id TEXT,revision INTEGER,generation TEXT)')
                for table,key,value in [('operations',OPERATION,operation),('pricing_plans','old-plan',old),
                                        ('pricing_plans','new-plan',successor),('metadata','generation',dict(id='generation-1')),
                                        ('reservations',OPERATION,dict(operation_id=OPERATION,plan_id='old-plan',state='RESERVED'))]:
                    owner.execute('INSERT INTO '+table+' VALUES (?,?)',(key,json.dumps(value)))
                owner.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',('base:console','new-plan',2,'generation-1'))
                owner.commit()
                with patch('fc_pricing_v3.runtime.verify_quote',return_value=fresh_receipt) as verify,\
                     patch.object(recovery,'load_policy',return_value={}):
                    callback=recovery.postwrite_quote(OPERATION,audit,root)
                self.assertEqual(callback(),quote)
                self.assertEqual(verify.call_args.kwargs['purpose'],'original_unsent_ALL_steps_only')
                self.assertTrue(verify.call_args.kwargs['for_execution'])
                owner.execute('UPDATE plan_ownership SET plan_id=?,revision=? WHERE resource=?',
                              ('old-plan',1,'base:console'))
                owner.commit()
                authorization.update(authorizing_plan_id='old-plan',revision=1)
                auth_path.write_text(json.dumps(authorization))
                fresh_receipt.update(plan_id='old-plan',revision=1)
                (root/'quotes'/(run+'.json')).write_text(json.dumps(quote))
                with patch('fc_pricing_v3.runtime.verify_quote',return_value=fresh_receipt),\
                     patch.object(recovery,'load_policy',return_value={}):
                    self.assertEqual(recovery.postwrite_quote(OPERATION,audit,root)(),quote)
                authorization['quote_sha256']='different-quote'
                auth_path.write_text(json.dumps(authorization))
                with patch('fc_pricing_v3.runtime.verify_quote',return_value=fresh_receipt),\
                     patch.object(recovery,'load_policy',return_value={}):
                    with self.assertRaisesRegex(ValueError,'original_postwrite_action_changed'):
                        recovery.postwrite_quote(OPERATION,audit,root)
            finally:
                owner.close()

    def test_real_postwrite_proof_and_original_reconciler_share_one_expired_plan_contract(self):
        from fc_pricing_v3 import runtime
        from fc_pricing_v3.ledger import Ledger
        from fixtures import fixture,NOW
        run='00000000-0000-4000-8000-000000000083'
        evidence,_,_=fixture();evidence['run_id']=run
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('v3','quotes','executions','config'):(root/name).mkdir()
            db=Ledger(root/'v3'/'control.sqlite3')
            db.activate_generation('g',[])
            anchor=dict(base_prices=dict(console='30',pc='30'),region_coefficients={})
            with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
                plan=db.create_plan('flash_sale',['base:console','base:pc'],anchor,
                                    starts_at=NOW.isoformat(),daily_budget='100')
                db.activate_plan(plan['plan_id'])
            plan.update(state='ENDING',ends_at=NOW.isoformat())
            db.put('pricing_plans',plan['plan_id'],plan)
            action=dict(base_prices=dict(console='20',pc='20'),region_coefficients={})
            original=dict(action=action,engine_generation='g',plan_id=plan['plan_id'],
                          decision_bundle_id=OPERATION,sha256='original-sha')
            bundle=dict(plan_id=plan['plan_id'],action=action,mutable_resources=plan['resources'],
                        sha256='original-sha',assignment_id='assignment',
                        budget_reservation={'console':{'concession':'99'}},
                        review_contract='inherited_hermes_review_with_explicit_v3_deterministic_path',
                        review_receipt=dict(phase='completed'))
            op=dict(operation_id=OPERATION,plan_id=plan['plan_id'],generation='g',resources=plan['resources'],
                    dispatch_context=dict(actor='operator'),bundle=bundle)
            db.put('operations',OPERATION,op)
            db.put('reservations',OPERATION,dict(operation_id=OPERATION,plan_id=plan['plan_id'],
                                                state='RESERVED',groups=bundle['budget_reservation']))
            audit=dict(execution_id=OPERATION,actor='operator',sync_confirmed=True,
                       pricing_decision_receipt=original,
                       after=dict(rows=[dict(platform=p,b2c='.2') for p in recovery.PLATFORMS]))
            (root/'executions'/(OPERATION+'.json')).write_text(json.dumps(audit))
            (root/'config'/'v3-control.json').write_text(json.dumps(dict(enabled=True,generation='g')))
            job=dict(request=dict(v3_operation_id=OPERATION))
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate_postwrite(evidence,job,db)
                quote=dict(evidence=evidence,result=result)
                (root/'quotes'/(run+'.json')).write_text(json.dumps(quote))
                receipt=result['decision_receipt']
                auth=dict(operation_id=OPERATION,original_operation_id=OPERATION,quote_run_id=run,
                          generation='g',current_generation='g',authorizing_plan_id=plan['plan_id'],
                          revision=plan['revision'],quote_sha256=receipt['sha256'],
                          authorizes='original_unsent_ALL_steps_only')
                (root/'v3'/'postwrite-authorizations').mkdir()
                (root/'v3'/'postwrite-authorizations'/(OPERATION+'.json')).write_text(json.dumps(auth))
                with patch.object(recovery,'load_policy',return_value=dict(minimum_gross_margin_pct='20')):
                    self.assertEqual(recovery.postwrite_quote(OPERATION,audit,root)(),quote)
                reservation=db.get('reservations',OPERATION)
                reservation['state']='SETTLED'
                db.put('reservations',OPERATION,reservation)
                with self.assertRaisesRegex(ValueError,'original_postwrite_budget_reservation_missing'):
                    recovery.postwrite_quote(OPERATION,audit,root)
                reservation['state']='RESERVED'
                db.put('reservations',OPERATION,reservation)
                op['bundle']['budget_policy']='none'
                db.put('operations',OPERATION,op)
                with db.transaction() as conn:conn.execute('DELETE FROM reservations WHERE id=?',(OPERATION,))
                with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
                    successor=db.create_plan('daily',plan['resources'],anchor,
                                             starts_at=NOW.isoformat(),daily_budget='100')
                    successor['parent_plan_id']=plan['plan_id']
                    db.put('pricing_plans',successor['plan_id'],successor)
                    db.activate_plan(successor['plan_id'])
                result=runtime.calculate_postwrite(evidence,job,db)
                quote=dict(evidence=evidence,result=result)
                (root/'quotes'/(run+'.json')).write_text(json.dumps(quote))
                receipt=result['decision_receipt']
                auth.update(authorizing_plan_id=successor['plan_id'],revision=successor['revision'],
                            quote_sha256=receipt['sha256'])
                (root/'v3'/'postwrite-authorizations'/(OPERATION+'.json')).write_text(json.dumps(auth))
                with patch.object(recovery,'load_policy',return_value=dict(minimum_gross_margin_pct='20')):
                    self.assertEqual(recovery.postwrite_quote(OPERATION,audit,root)(),quote)

    def test_partial_order_readback_preserves_original_unknown_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'executions').mkdir()
            request=dict(execution_id=OPERATION,v3_operation_id=OPERATION,preview_id='preview',actor='operator',
                         platforms=['PS','XBOX'],policy_revision=3)
            before=[dict(platform=p,b2c='10',costPrice='5') for p in recovery.PLATFORMS]
            targets=[dict(platform=p,quote='12',targetCost='6') for p in recovery.PLATFORMS]
            audit=dict(execution_id=OPERATION,preview_id='preview',actor='operator',selected=['PS','XBOX'],
                       automation_policy_revision=3,status='UNCERTAIN',sync_confirmed=False,
                       before=dict(rows=before),targets=targets)
            path=root/'executions'/(OPERATION+'.json')
            path.write_text(json.dumps(audit))
            observed=dict(rows=[dict(platform=p,b2c='10',costPrice='5') for p in recovery.PLATFORMS])
            manager=Mock()
            result=recovery.reconcile(request,root,order_reader=lambda _:observed,manager_factory=manager)
            self.assertEqual(result['status'],'UNCERTAIN')
            self.assertFalse(json.loads(path.read_text())['sync_confirmed'])
            manager.assert_not_called()


if __name__=='__main__':
    unittest.main()

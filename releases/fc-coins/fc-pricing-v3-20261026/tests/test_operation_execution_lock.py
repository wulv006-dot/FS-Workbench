"""Real per-operation locks and SQLite interleaving, with transport boundaries fake."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import runtime,adapters,scheduler
from fc_pricing_v3.ledger import Ledger


class OperationExecutionLock(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'executions').mkdir();self.db=Ledger(self.root/'v3/control.sqlite3')
        self.now=datetime.now(timezone.utc);self.stack=ExitStack();self.addCleanup(self.stack.close)
        for obj,name,value in ((runtime,'ledger',lambda:self.db),(scheduler,'ledger',lambda:self.db),(runtime,'ROOT',self.root),
                (runtime,'write_json',lambda p,v:p.write_text(json.dumps(v))),(runtime,'clock',lambda:self.now),(scheduler,'clock',lambda:self.now)):
            self.stack.enter_context(patch.object(obj,name,value))
        self.stack.enter_context(patch('fc_pricing_v3.ledger.clock',return_value=self.now))
        self.resources=['base:PS','base:XBOX','base:PC','region:21:PS','region:21:XBOX']
        self.before=dict(base_prices=dict(PS='7.19',XBOX='7.19',PC='7.25'),region_coefficients={'21:PS':'1','21:XBOX':'1'})
        self.action=dict(base_prices=dict(PS='6.87',XBOX='6.87',PC='7.46'),region_coefficients={'21:PS':'.9996','21:XBOX':'.9996'})
        self.db.put('metadata','generation',dict(id='g'))
        self.db.put('pricing_plans','plan',dict(plan_id='plan',revision=1,generation='g',state='ACTIVE',ends_at=None,resources=self.resources))
        bundle=dict(assignment_id='fixture',snapshot_id='run',action=self.action,before_action=self.before,mutable_resources=self.resources,
                    affected_platforms=['PS','XBOX','PC'],catalog={},budget_reference={},valid_until=(self.now+timedelta(minutes=15)).isoformat())
        state=deepcopy(self.before);state['base_prices']=deepcopy(self.action['base_prices'])
        steps=[dict(step_id='base',kind='base',state='PREPARED',intermediate=deepcopy(state))]
        for platform in ('PS','XBOX'):
            state['region_coefficients']['21:'+platform]='.9996'
            steps.append(dict(step_id='region:'+platform,kind='region',key='21:'+platform,state='PREPARED',intermediate=deepcopy(state)))
        self.op=dict(operation_id='original-operation',plan_id='plan',revision=1,generation='g',status='AUTHORIZED',resources=self.resources,bundle=bundle,steps=steps)
        self.db.put('operations',self.op['operation_id'],self.op)
        with self.db.transaction() as conn:
            for resource in self.resources:
                conn.execute('INSERT INTO plan_ownership VALUES(?,?,?,?)',(resource,'plan',1,'g'))
                conn.execute('INSERT INTO resource_leases VALUES(?,?)',(resource,self.op['operation_id']))

    def nochange_input(self):
        with self.db.transaction() as conn:
            conn.execute('DELETE FROM operations');conn.execute('DELETE FROM resource_leases')
        for name in ('jobs','quotes'):(self.root/name).mkdir(exist_ok=True)
        bundle=dict(self.op['bundle'],plan_id='plan',decision_bundle_id=self.op['operation_id'],resources=self.resources,steps=[])
        quote=dict(result=dict(decision_receipt=bundle),evidence=dict(storefront=dict(rows={p:dict(package_usd=self.action['base_prices'][p]) for p in runtime.PLATFORMS})))
        (self.root/'quotes/run.json').write_text(json.dumps(quote))
        (self.root/'jobs/run.json').write_text(json.dumps(dict(actor='system-automation',request={})))
        return bundle,SimpleNamespace(APP=self.root,run=Mock(return_value=(0,dict(status='review_only',preview_id='original-preview'))))

    def test_nochange_execute_and_reconcile_serialize_pending_then_verified_close(self):
        bundle,worker=self.nochange_input();entered=threading.Event();release=threading.Event();errors=[];results=[]
        def pending(operation,preview):
            entered.set()
            if not release.wait(5):raise AssertionError('fixture_nochange_release_missing')
            return dict(status='PUBLIC_PENDING',preview=preview)
        attempts=[0]
        def verify_once(operation,preview):
            attempts[0]+=1
            return pending(operation,preview) if attempts[0]==1 else dict(status='PUBLIC_CONFIRMED',no_change=True)
        def execute():
            try:results.append(runtime.execute_run('run'))
            except BaseException as error:errors.append(error)
        with patch.dict(sys.modules,{'fc27_cloud_worker':worker}),patch.object(runtime,'verify_quote',return_value=bundle),patch('automation_policy.load_policy',return_value=dict(revision=1)),patch.object(adapters,'verify_nochange',side_effect=verify_once) as check,patch.object(adapters,'reconcile_postwrite') as post:
            thread=threading.Thread(target=execute);thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(ValueError,'pricing_operation_busy'):runtime.reconcile(self.op['operation_id'])
                self.assertEqual(self.db.get('operations',self.op['operation_id'])['status'],'AUTHORIZED')
                with self.db.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM resource_leases').fetchone()[0],len(self.resources))
            finally:release.set();thread.join(5)
            self.assertEqual(errors,[]);self.assertEqual(results[0]['status'],'PUBLIC_PENDING');self.assertEqual(check.call_count,1)
            with self.db.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM resource_leases').fetchone()[0],len(self.resources))
            closed=runtime.reconcile(self.op['operation_id']);self.assertEqual(closed['status'],'NO_CHANGE');self.assertEqual(check.call_count,2)
            runtime.execute_run('run');runtime.reconcile(self.op['operation_id']);self.assertEqual(check.call_count,2)
            self.assertEqual(self.db.get('operations',self.op['operation_id'])['status'],'NO_CHANGE');post.assert_not_called()
            with self.db.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM resource_leases').fetchone()[0],0)
            worker.run.assert_called_once()

    def test_first_authorized_empty_cycle_requires_real_nochange_proof_and_stale_owner_rereads_terminal(self):
        bundle,worker=self.nochange_input();prepared=threading.Event();release=threading.Event();errors=[];results=[]
        original=self.db.prepare
        def prepare(*args,**kwargs):
            result=original(*args,**kwargs);prepared.set()
            if not release.wait(5):raise AssertionError('fixture_prepare_release_missing')
            return result
        def execute():
            try:results.append(runtime.execute_run('run'))
            except BaseException as error:errors.append(error)
        with patch.dict(sys.modules,{'fc27_cloud_worker':worker}),patch.object(runtime,'verify_quote',return_value=bundle),patch('automation_policy.load_policy',return_value=dict(revision=1)),patch.object(self.db,'prepare',side_effect=prepare),patch.object(adapters,'verify_nochange',side_effect=[dict(status='PUBLIC_CONFIRMED',no_change=True),dict(status='PUBLIC_PENDING')]) as check,patch.object(adapters,'reconcile_postwrite') as post:
            thread=threading.Thread(target=execute);thread.start()
            try:
                self.assertTrue(prepared.wait(5))
                closed=runtime.reconcile(self.op['operation_id']);self.assertEqual(closed['status'],'NO_CHANGE')
                self.assertEqual(check.call_count,1);self.assertEqual(check.call_args.args[1]['preview_id'],'original-preview')
            finally:release.set();thread.join(5)
            self.assertEqual(errors,[]);self.assertEqual(results[0]['status'],'NO_CHANGE');self.assertEqual(check.call_count,1)
            self.assertEqual(self.db.get('operations',self.op['operation_id'])['status'],'NO_CHANGE');post.assert_not_called()
            with self.db.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM resource_leases').fetchone()[0],0)

    def test_original_drive_blocks_early_close_and_players_then_retry_is_read_only(self):
        saved=threading.Event();release=threading.Event();errors=[];results=[]
        def base(operation):
            (self.root/'executions'/(operation['operation_id']+'.json')).write_text(json.dumps(dict(
                status='CONFIRMED',sync_confirmed=True,sync_message='修改价格已推送',all_baseline=dict(status='confirmed'))))
            saved.set()
            if not release.wait(5):raise AssertionError('fixture_driver_release_missing')
            return dict(status='CONFIRMED',confirmation_scope='Order_Admin_ALL')
        def region(operation,step_id,write=False):
            self.assertTrue(write)
            return dict(status='CONFIRMED',factor='.9996',rule_set_sha256='a'*64)
        def players(operation,*args):
            self.assertTrue(all(s['state']=='CONFIRMED' for s in operation['steps']))
            return operation
        base_write=Mock(side_effect=base);region_write=Mock(side_effect=region);followup=Mock(side_effect=players)
        self.db.enqueue('reconcile','original-reconcile',self.now,dict(operation_id=self.op['operation_id']))
        with self.db.transaction() as conn:conn.execute("UPDATE durable_jobs SET state='running' WHERE id='original-reconcile'")
        with self.db.connect() as conn:job=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original-reconcile'").fetchone())
        def drive():
            try:results.append(runtime.drive_steps(self.op,{}))
            except BaseException as error:errors.append(error)
        with patch.object(runtime,'verify_quote'),patch('automation_policy.load_policy',return_value={}),patch.object(adapters,'dispatch_base',base_write),patch.object(adapters,'region_step',region_write),patch.object(adapters,'reconcile_postwrite',return_value=dict(status='PUBLIC_CONFIRMED')),patch.object(runtime,'complete_player_followup',followup),patch.object(runtime,'_admin_observed_prices') as admin:
            thread=threading.Thread(target=drive);thread.start()
            try:
                self.assertTrue(saved.wait(5))
                scheduler.run_job(job)  # The actual durable error path must queue, never close/done.
                with self.db.connect() as conn:retry=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original-reconcile'").fetchone())
                self.assertEqual((retry['state'],retry['attempt']),('queued',1))
                self.assertEqual(json.loads(retry['body'])['error'],'pricing_operation_busy')
                self.assertEqual(retry['due_at'],(self.now+timedelta(minutes=5)).isoformat())
                self.assertNotIn('result',json.loads(retry['body']))
                current=self.db.get('operations',self.op['operation_id'])
                self.assertEqual([s['state'] for s in current['steps']],['DISPATCHED','PREPARED','PREPARED'])
                self.assertNotIn('target_not_completed',current);followup.assert_not_called();region_write.assert_not_called();admin.assert_not_called()
                with runtime.operation_execution('unrelated-operation'):pass
            finally:release.set();thread.join(5)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            self.assertEqual(results[0]['status'],'COMPLETED');self.assertNotIn('actual_action',results[0]);self.assertNotIn('target_not_completed',results[0])
            base_write.assert_called_once();self.assertEqual(region_write.call_count,2);self.assertEqual(followup.call_count,1)
            scheduler.run_job(retry)
            base_write.assert_called_once();self.assertEqual(region_write.call_count,2)
            with self.db.connect() as conn:self.assertEqual(conn.execute("SELECT state FROM durable_jobs WHERE id='original-reconcile'").fetchone()[0],'done')

    def test_terminal_or_cancelled_step_cannot_be_claimed_again(self):
        for status in ('COMPLETED','NO_CHANGE','CANCELLED_NOT_SENT','KNOWN_PARTIAL_EXIT_PENDING','KNOWN_PARTIAL_EXITED'):
            with self.subTest(status=status):
                operation=deepcopy(self.op);operation['status']=status;self.db.put('operations',operation['operation_id'],operation)
                self.assertIsNone(self.db.claim_dispatch(operation['operation_id'],'base'))
                self.assertEqual(self.db.get('operations',operation['operation_id']),operation)
        operation=deepcopy(self.op);operation['steps'][0]['state']='CANCELLED_NOT_SENT';self.db.put('operations',operation['operation_id'],operation)
        self.assertIsNone(self.db.claim_dispatch(operation['operation_id'],'base'));self.assertEqual(self.db.get('operations',operation['operation_id']),operation)

    def test_stale_drive_after_terminal_close_does_not_verify_or_send_again(self):
        closed=deepcopy(self.op);closed['status']='COMPLETED';closed['steps'][0]['state']='CONFIRMED'
        for step in closed['steps'][1:]:step['state']='CANCELLED_NOT_SENT'
        self.db.put('operations',closed['operation_id'],closed)
        with patch.object(runtime,'verify_quote') as verify,patch.object(adapters,'dispatch_base') as base,patch.object(adapters,'region_step') as region:
            result=runtime.drive_steps(self.op,{})
        self.assertEqual(result,closed);verify.assert_not_called();base.assert_not_called();region.assert_not_called()

    def test_lock_is_nonblocking_stable_inode_and_released_on_exception(self):
        with runtime.operation_execution('same'):
            with self.assertRaisesRegex(ValueError,'pricing_operation_busy'):
                with runtime.operation_execution('same'):pass
            with runtime.operation_execution('different'):pass
        path=self.db.path.parent/'operation-locks'/(runtime.fingerprint('same')+'.lock');inode=path.stat().st_ino
        with self.assertRaisesRegex(RuntimeError,'fixture_error'):
            with runtime.operation_execution('same'):raise RuntimeError('fixture_error')
        with runtime.operation_execution('same'):self.assertEqual(path.stat().st_ino,inode)
        self.assertTrue(path.exists())

    def test_same_operation_cross_process_lock_uses_original_inode(self):
        code="""import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from fc_pricing_v3 import runtime
runtime.ledger=lambda:SimpleNamespace(path=Path(sys.argv[2]))
try:
 with runtime.operation_execution('same'):raise AssertionError('cross_process_lock_was_not_held')
except ValueError as error:
 assert str(error)=='pricing_operation_busy'
 print('busy')
"""
        with runtime.operation_execution('same'):
            result=subprocess.run([sys.executable,'-B','-c',code,str(SOURCE),str(self.db.path)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'busy')


if __name__=='__main__':unittest.main()

import ast,json,os,shlex,subprocess,sys,tempfile,unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import adapters,runtime
from fc_pricing_v3.dispatch import prewrite_refusal
from fc_pricing_v3.ledger import Ledger

class PrewritePartial(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=Ledger(self.root/'v3/control.sqlite3')
        self.plan=dict(plan_id='plan',revision=3,generation='gen',state='ACTIVE',ends_at=None)
        before=dict(base_prices=dict(console='7.38',pc='7.46'),region_coefficients={'21:PS':'.9804','21:XBOX':'1'})
        actual=deepcopy(before);actual['region_coefficients']={'21:PS':'.9700','21:XBOX':'.9700'}
        target=deepcopy(actual);target['base_prices']=dict(console='8.12',pc='7.71')
        bundle=dict(schema_version=runtime.VERSION,snapshot_id='run',sha256='a'*64,assignment_id='assign',before_action=before,action=target,
                    valid_until=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),catalog={},affected_platforms=['PS','XBOX','PC'],
                    mutable_resources=['base:console','base:pc','region:21:PS','region:21:XBOX'])
        self.op=dict(operation_id='op',plan_id='plan',revision=3,generation='gen',status='UNKNOWN',bundle=bundle,resources=list(bundle['mutable_resources']),
                     steps=[dict(step_id='region1',kind='region',state='CONFIRMED',intermediate=deepcopy(actual)),
                            dict(step_id='region2',kind='region',state='CONFIRMED',intermediate=deepcopy(actual)),
                            dict(step_id='base',kind='base',state='UNKNOWN',dispatched_at='2026-10-28T10:51:02+00:00',receipt=dict(status='UNKNOWN',reason='pricing_admin_shared_source_timeout',exit_code=1))])
        self.db.put('operations','op',self.op);self.db.put('pricing_plans','plan',self.plan)
        with self.db.transaction() as con:
            for resource in self.op['resources']:
                con.execute('INSERT INTO resource_leases VALUES (?,?)',(resource,'op'))
                con.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,'plan',3,'gen'))
        self.addCleanup(patch.stopall)
        patch.object(runtime,'ledger',return_value=self.db).start();patch.object(runtime,'ROOT',self.root).start()

    def mark_actual_refusal(self):
        receipt=prewrite_refusal('{"status":"FAILED","reason":"pricing_admin_shared_source_timeout"}')
        receipt.update(exit_code=1)
        return self.db.step_result('op','base','UNKNOWN',receipt)

    def test_shell_only_emits_refusal_in_guard_branch_before_writer(self):
        for name in ('execute_price.sh','restore_price.sh'):
            text=(SOURCE/name).read_text('utf-8');guard=text.index('if guard_result=');refusal=text.index('prewrite_refusal');docker=text.index('docker run')
            self.assertLess(guard,refusal);self.assertLess(refusal,text.index('\nfi',guard));self.assertLess(refusal,docker)
            self.assertEqual(text.count('prewrite_refusal'),2)  # import and invocation on the same line
        value=prewrite_refusal('{"status":"FAILED","reason":"pricing_admin_shared_source_timeout"}')
        self.assertEqual((value['status'],value['stage']),('NOT_SENT','prewrite_source_guard'))
        self.assertIs(value['price_post_attempted'],False);self.assertIs(value['business_dispatch_started'],False)
        for raw in ('', 'not JSON', '{"reason":"https://secret.invalid/?token=private"}', '{"reason":"private@example.invalid"}'):
            self.assertEqual(prewrite_refusal(raw)['reason'],'pricing_live_constraints_unavailable')
            self.assertNotIn('private',json.dumps(prewrite_refusal(raw)))

    @unittest.skipUnless(Path('/bin/sh').exists(),'real shell guard runs on Linux')
    def test_real_linux_shell_calls_real_refusal_and_keeps_post_dispatch_unknown(self):
        app=self.root/'app';(app/'fc_pricing_v3').mkdir(parents=True);(self.root/'state').mkdir();(self.root/'requests').mkdir()
        (app/'fc_pricing_v3/__init__.py').write_text('');(app/'fc_pricing_v3/dispatch.py').write_bytes((SOURCE/'fc_pricing_v3/dispatch.py').read_bytes())
        fake=self.root/'bin';fake.mkdir();marker=self.root/'docker-called'
        docker=fake/'docker';docker.write_text('#!/bin/sh\nprintf called >> '+shlex.quote(str(marker))+'\nprintf \'%s\\n\' \'{"status":"UNKNOWN","reason":"after_writer_dispatch"}\'\nexit 1\n');docker.chmod(0o700)
        install=fake/'install';install.write_text('#!/bin/sh\nfor last do :; done\nmkdir -p "$last"\n');install.chmod(0o700)
        request=self.root/'requests/op.json';request.write_text('{}')
        for name in ('execute_price.sh','restore_price.sh'):
            shell=(SOURCE/name).read_text('utf-8').replace('/var/lib/fc27-cloud',str(self.root)).replace('/opt/fc27-cloud-browser',str(app)).replace('/opt/python39/bin/python3',shlex.quote(sys.executable))
            for reason in ('pricing_admin_shared_source_timeout','https://private.invalid/?token=secret'):
                (app/'pricing_sources.py').write_text('import json\nprint(json.dumps('+repr(dict(status='FAILED',reason=reason))+'))\nraise SystemExit(1)\n')
                result=subprocess.run(['/bin/sh','-s','--',str(request)],input=shell,capture_output=True,text=True,timeout=5,env=dict(os.environ,PATH=str(fake)+os.pathsep+os.environ['PATH']))
                value=json.loads(result.stdout.splitlines()[-1]);self.assertEqual(result.returncode,1,result.stderr)
                self.assertEqual(value['status'],'NOT_SENT');self.assertEqual(value['stage'],'prewrite_source_guard');self.assertIs(value['price_post_attempted'],False)
                self.assertEqual(value['reason'],reason if reason.startswith('pricing_') else 'pricing_live_constraints_unavailable')
                self.assertFalse(marker.exists());self.assertNotIn('secret',result.stdout)
            (app/'pricing_sources.py').write_text('print(\'{"status":"current_promotions_rechecked"}\')\n')
            result=subprocess.run(['/bin/sh','-s','--',str(request)],input=shell,capture_output=True,text=True,timeout=5,env=dict(os.environ,PATH=str(fake)+os.pathsep+os.environ['PATH']))
            self.assertEqual(json.loads(result.stdout.splitlines()[-1])['status'],'UNKNOWN');self.assertEqual(marker.read_text(),'called');marker.unlink()

    def test_original_history_kept_and_expired_partial_preserves_active_plan(self):
        op=self.mark_actual_refusal();base=op['steps'][-1]
        self.assertEqual(base['state'],'UNKNOWN');self.assertEqual(base['receipt']['status'],'NOT_SENT')
        self.assertEqual(base['receipt_history'][0]['receipt']['status'],'UNKNOWN')
        (self.root/'quotes').mkdir();(self.root/'quotes/run.json').write_text('{}')
        verify=Mock(side_effect=ValueError('pricing_authorization_expired_or_unowned'));dispatch=Mock(side_effect=AssertionError('new_base_write'))
        with patch.object(runtime,'verify_quote',verify),patch.object(adapters,'dispatch_base',dispatch),patch.object(adapters,'verify_known_partial',return_value=dict(status='PUBLIC_CONFIRMED')),patch.dict(sys.modules,automation_policy=SimpleNamespace(load_policy=lambda:{})):
            closed=runtime.reconcile('op')
        verify.assert_called_once();self.assertTrue(verify.call_args.kwargs['for_execution']);dispatch.assert_not_called()
        self.assertEqual(closed['status'],'COMPLETED');self.assertTrue(closed['target_not_completed'])
        self.assertEqual(closed['steps'][-1]['state'],'CANCELLED_NOT_SENT')
        self.assertEqual(self.db.get('pricing_plans','plan'),self.plan)
        self.assertEqual(closed['actual_action']['base_prices'],self.op['bundle']['before_action']['base_prices'])
        self.assertEqual(self.db.get('actual_price_windows','op')['resources'],['region:21:PS','region:21:XBOX'])
        with self.db.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM resource_leases').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM plan_ownership').fetchone()[0],4)
            self.assertEqual(con.execute("SELECT count(*) FROM durable_jobs WHERE kind='exit'").fetchone()[0],0)
        with patch.dict(sys.modules,fc27_cloud_worker=SimpleNamespace(load_player_sync_policy=Mock(side_effect=AssertionError('Players touched')))):
            self.assertEqual(runtime.reconcile('op'),closed)

    def test_future_plan_continues_but_actual_deadline_and_ending_still_exit(self):
        for state,ends,continuing in [('ACTIVE',datetime.now(timezone.utc)+timedelta(hours=1),True),('ACTIVE',datetime.now(timezone.utc)-timedelta(seconds=1),False),('ENDING',None,False),('SUSPENDED',None,False)]:
            with self.subTest(state=state,ends=ends):
                self.db.put('operations','op',deepcopy(self.op));self.mark_actual_refusal()
                plan=dict(self.plan,state=state,ends_at=ends.isoformat() if ends else None);self.db.put('pricing_plans','plan',plan)
                deadline=Mock(wraps=self.db.deadline)
                with patch.object(adapters,'verify_known_partial',return_value=dict(status='PUBLIC_CONFIRMED')),patch.object(self.db,'deadline',deadline):
                    result=runtime.stop_unissued_and_exit(self.db.get('operations','op'),'pricing_authorization_expired')
                self.assertEqual(result['status'],'COMPLETED' if continuing else 'KNOWN_PARTIAL_EXIT_PENDING')
                self.assertEqual(deadline.call_count,0 if continuing else 1)

    def test_unproven_unknown_and_transport_claim_remain_unresolved(self):
        for claimed in (False,True):
            op=deepcopy(self.op)
            if claimed:
                op['steps'][-1]['receipt']=prewrite_refusal('');op['steps'][-1]['transport_claimed_at']='original-claim'
            self.db.put('operations','op',op)
            with patch.object(adapters,'verify_known_partial',side_effect=AssertionError('unknown must not close')):
                self.assertEqual(runtime.stop_unissued_and_exit(op,'pricing_authorization_expired'),op)

    def test_worker_rejects_only_partial_without_confirmed_base(self):
        tree=ast.parse((SOURCE/'fc27_cloud_worker.py').read_text('utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='v3_player_completion')
        namespace={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'real-worker-completion','exec'),namespace)
        op=deepcopy(self.op);op.update(status='COMPLETED',target_not_completed=True);op['bundle']['snapshot_id']='run';self.db.put('operations','op',op)
        with self.assertRaisesRegex(ValueError,'player_sync_base_not_confirmed'):namespace['v3_player_completion']('op','run')
        op['steps'][-1]['state']='CONFIRMED';self.db.put('operations','op',op)
        self.assertEqual(namespace['v3_player_completion']('op','run')['status'],'COMPLETED')

    def test_post_writer_failure_is_not_reclassified_as_refusal(self):
        worker=SimpleNamespace(APP=SOURCE,run=Mock(return_value=(1,dict(status='FAILED',reason='uncertain_after_dispatch',business_dispatch_started=True))))
        op=deepcopy(self.op);op['dispatch_context']=dict(preview={'preview_id':'preview'},actor='wulv',selected=['PS','XBOX','PC'],policy_revision=42,automatic=False)
        (self.root/'requests').mkdir()
        def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
        with patch.object(runtime,'STORE',self.root/'v3'),patch.object(runtime,'write_json',write),patch.dict(sys.modules,fc27_cloud_worker=worker):
            result=adapters.dispatch_base(op)
        self.assertEqual(result['status'],'UNKNOWN');worker.run.assert_called_once()

if __name__=='__main__':unittest.main()

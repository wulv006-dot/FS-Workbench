"""Isolated Order/public acceptance and publication tests; no live requests."""
import ast,importlib.util,json,sys,tempfile,types,unittest
from pathlib import Path
from contextlib import nullcontext,redirect_stdout
from io import StringIO
from unittest.mock import Mock,patch
from copy import deepcopy
HERE=Path(__file__).resolve().parent

def function(name,file,namespace):
    tree=ast.parse((HERE/'source'/file).read_text(encoding='utf-8'))
    selected=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[selected],type_ignores=[]),file,'exec'),namespace)
    return namespace[name]

JID='11111111-1111-4111-8111-111111111111'
def basis():
    rows=[{'platform':p,'b2c':'0.1'} for p in ('PS','XBOX','PC')]
    execution={'execution_id':JID,'status':'CONFIRMED','sync_confirmed':True,
        'selected':['PC'],'after':{'rows':rows},'before':{'rows':deepcopy(rows)},
        'targets':[{'platform':p,'quote':'0.1'} for p in ('PS','XBOX','PC')],
        'all_baseline':{'status':'deferred_before_dispatch','reason':'coin_auth_unavailable',
        'execution_id':JID,'price_post_attempted':False,'success_scope':'order_b2c_and_public_price'}}
    job={'job_id':JID,'status':'ready','result':{'status':'confirmed','execution_id':JID},
        'public_page_readback':{'status':'verified','platforms':['PC'],'checked_at':'2026-10-13T15:48:06Z'}}
    return job,execution

class OrderProofTests(unittest.TestCase):
    def setUp(self):self.check=function('order_public_without_all','probe_worker.py',{})
    def test_confirmed_order_public_no_dispatch_is_accepted(self):
        self.assertTrue(self.check(*basis(),False))
    def test_any_all_ledger_keeps_protection(self):
        self.assertFalse(self.check(*basis(),True))
    def test_scope_status_identity_or_public_failure_rejected(self):
        job,execution=basis()
        for path,value in [('status','failed'),('job_id','another')]:
            changed=deepcopy(job);changed[path]=value
            self.assertFalse(self.check(changed,execution,False))
        for path,value in [('status','PARTIAL'),('sync_confirmed',False),('execution_id','another')]:
            changed=deepcopy(execution);changed[path]=value
            self.assertFalse(self.check(job,changed,False))
        for path,value in [('price_post_attempted',True),('reason','TimeoutError'),('success_scope','other')]:
            changed=deepcopy(execution);changed['all_baseline'][path]=value
            self.assertFalse(self.check(job,changed,False))
        changed=deepcopy(job);changed['public_page_readback']['status']='unconfirmed'
        self.assertFalse(self.check(changed,execution,False))
    def test_incomplete_or_changed_price_not_accepted(self):
        job,execution=basis()
        for rows in (execution['after']['rows'][:2], [{'platform':'PC','b2c':'NaN'}]*3):
            changed=deepcopy(execution);changed['after']['rows']=rows
            self.assertFalse(self.check(job,changed,False))
        execution['after']['rows'][2]['b2c']='0.2'
        self.assertFalse(self.check(job,execution,False))

class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'all-coin-sync').mkdir()
        self.policy={'revision':30,'system_enabled':True,'mode':'auto'}
        self.mirror=Mock();self.stage=Mock()
        ns={'ROOT':self.root,'PLATFORMS':('PS','XBOX','PC'), 'load_policy':lambda:dict(self.policy),
            'mirror_confirmed':self.mirror,'save_audit':Mock(),'stage':self.stage}
        self.call=function('mirror_after_order_confirmation','price_writer.py',ns)
        self.record=basis()[1]
    def test_existing_all_success_unchanged(self):
        self.mirror.return_value={'status':'confirmed'}
        self.assertEqual(self.call(self.record),{'status':'confirmed'})
        self.stage.assert_not_called()
    def test_only_zero_dispatch_auth_failure_can_defer(self):
        self.mirror.side_effect=ValueError('coin_auth_unavailable')
        self.assertEqual(self.call(self.record)['status'],'deferred_before_dispatch')
        self.assertFalse(self.record['all_baseline']['price_post_attempted'])
        self.mirror.assert_called_once()
    def test_ledger_even_empty_prevents_defer(self):
        (self.root/'all-coin-sync'/(JID+'.json')).write_text('{}')
        self.mirror.side_effect=ValueError('coin_auth_unavailable')
        with self.assertRaises(ValueError):self.call(self.record)
        self.stage.assert_not_called()
    def test_transport_rejection_and_unknown_do_not_defer(self):
        for error in (TimeoutError(),ValueError('coin_backend_request_rejected'),ValueError('coin_all_readback_mismatch')):
            self.mirror.side_effect=error
            with self.assertRaises(type(error)):self.call(self.record)
        self.stage.assert_not_called()
    def test_policy_change_or_unconfirmed_order_keeps_protection(self):
        def fail(*args):self.policy['revision']=31;raise ValueError('coin_auth_unavailable')
        self.mirror.side_effect=fail
        with self.assertRaises(ValueError):self.call(self.record)
        self.mirror.side_effect=ValueError('coin_auth_unavailable');self.record['sync_confirmed']=False
        with self.assertRaises(ValueError):self.call(self.record)
        self.stage.assert_not_called()

class ReportTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('acceptance_report',HERE/'source/report.py')
        self.report=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.report)
    def run_report(self,coin,all_record=None,player=None,issues=None):
        return self.report.report({'captured_at':'2026-10-13T15:48:06Z'}, {'issues':issues or []},{},
            {'coin':coin,'all':all_record or {},'player':player or {}})
    def test_deferred_auth_is_visible_warning(self):
        result=self.run_report({'result':'confirmed','order_public_confirmed_without_all':True})
        self.assertEqual(result['issues'],[{'level':'warning','code':'all_auth_deferred_before_dispatch'}])
    def test_missing_proof_or_actual_unknown_remains_critical(self):
        for coin,ledger in [({'result':'confirmed'},{}),({'result':'confirmed','order_public_confirmed_without_all':True},{'status':'needs_reconcile'})]:
            self.assertEqual(self.run_report(coin,ledger)['status'],'critical')
    def test_accepted_player_links_to_coin_not_missing_all(self):
        coin={'result':'confirmed','execution_id':JID,'order_public_confirmed_without_all':True,'player_expected':True,'player_job_id':'player'}
        player={'status':'confirmed','coin_execution_id':JID,'category_response':'accepted'}
        self.assertEqual(self.run_report(coin,player=player)['status'],'warning')
        player['coin_execution_id']='wrong';self.assertEqual(self.run_report(coin,player=player)['status'],'critical')
    def test_new_warning_has_plain_chinese_explanation(self):
        tree=ast.parse((HERE/'source/hooks_notifier.py').read_text(encoding='utf-8'))
        value=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ISSUE_TEXT' for t in n.targets))
        text=ast.literal_eval(value)['all_auth_deferred_before_dispatch']
        self.assertIn('不阻塞金币自动改价',text)
        self.assertIn('未派发写价',text)
    def test_publication_or_player_failures_still_critical(self):
        coin={'result':'confirmed','order_public_confirmed_without_all':True,'player_expected':True}
        self.assertEqual(self.run_report(coin)['status'],'critical')
        coin['player_expected']=False
        self.assertEqual(self.run_report(coin,issues=[{'level':'critical','code':'published_price_unverified'}])['status'],'critical')


@unittest.skipIf(sys.platform=='win32','Directory fsync requires Linux')
class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        (self.root/'rollback').mkdir()
        self.stage=self.root/'stage';self.stage.mkdir()
        (self.stage/'candidate').mkdir()
        self.runtime=self.root/'runtime';self.runtime.mkdir()
        self.state=self.root/'state';self.state.mkdir()
        (self.state/'price-writer.lock').write_text('')
        for site in ('IGGM','U4GM','U7Buy'):(self.state/(site+'.lock')).write_text('')
        self.mapping={}
        targets={}
        for name,remote in {'price_writer.py':'/opt/fc27-cloud-browser/price_writer.py',
                            'report.py':'/opt/fc-ops-readonly-monitor/report.py', 'probe_worker.py':'/opt/fc-ops-readonly-monitor/probe_worker.py',
                            'hooks_notifier.py':'/opt/fc-ops-readonly-monitor/hooks_notifier.py'}.items():
            target=self.runtime/name;target.write_bytes(b'value=1\n')
            candidate=self.stage/'candidate'/name;candidate.write_bytes(b'value=2\n')
            self.mapping[remote]=target
            import hashlib
            targets[name]={'target':remote,'before':hashlib.sha256(target.read_bytes()).hexdigest(),
                           'after':hashlib.sha256(candidate.read_bytes()).hexdigest()}
        self.manifest={'targets':targets,'before':{r['target']:r['before'] for r in targets.values()}}
        control=self.runtime/'control.json';control.write_text(json.dumps({'mode':'RULES_ARMED','unknown_operations':[], 'policy_revision':30}))
        self.mapping['/var/lib/fc-ops-readonly-monitor/gates/control.json']=control
        stub=types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:None)
        with patch.dict(sys.modules,{'fcntl':stub,'automation_tick':types.SimpleNamespace(queue_mutation=nullcontext,retry_guard=lambda:'ready')}):
            spec=importlib.util.spec_from_file_location('scoped_publisher',HERE/'publish.py')
            self.pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.pub)
        self.pub.ROOT=self.root;self.pub.STAGE=self.stage;self.pub.HARDENING=True;self.pub.ORDER_PUBLIC=True
        self.commands=[]
        self.monitor={'health':{'worker':'ok'},'automation':{'revision':30,'schedule':{'status':'waiting'}},'player_sync':{}}
        self.pub.command=lambda *args:self.commands.append(args)
        self.pub.urlopen=lambda *a,**kw:StringIO(json.dumps(self.monitor))
        self.pub.Path=lambda name:self.mapping.get(str(name),Path(name))
        self.pub.idle=lambda:None
        self.uid=patch.object(self.pub.os,'geteuid',lambda:0,create=True);self.uid.start();self.addCleanup(self.uid.stop)
        self.chown=patch.object(self.pub.os,'chown',lambda *a:None,create=True);self.chown.start();self.addCleanup(self.chown.stop)
    def run_publish(self,apply=True):
        (self.stage/'manifest.json').write_text(json.dumps(self.manifest))
        with patch.object(sys,'argv',['publisher']+(['--apply'] if apply else [])),redirect_stdout(StringIO()):
            self.pub.main()
    def test_exact_four_targets_apply_without_service_restart(self):
        self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=2\n' for p in self.mapping.values() if p.suffix=='.py'))
        self.assertFalse(any('stop' in cmd or 'start' in cmd for cmd in self.commands))
    def test_check_only_does_not_replace_files(self):
        self.run_publish(False)
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
        self.assertFalse(list((self.root/'rollback').iterdir()))
    def test_extra_or_remapped_target_is_rejected(self):
        self.manifest['targets']['price_writer.py']['target']='/opt/unrelated.py'
        with self.assertRaisesRegex(ValueError,'exact_fc_hardening_scope'):self.run_publish()
    def test_baseline_or_payload_drift_is_rejected(self):
        self.runtime.joinpath('price_writer.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'baseline_changed'):self.run_publish()
    def test_partial_rename_failure_restores_both_original_files(self):
        original=self.pub.swap;counter=[0]
        def swap(source,target):
            original(source,target);counter[0]+=1
            if counter[0]==2:raise OSError('simulated fsync failure after second rename')
        self.pub.swap=swap
        with self.assertRaises(OSError):self.run_publish()
        self.assertEqual(counter[0],6)
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_health_failure_restores_original_files(self):
        self.monitor['health']['worker']='unverified'
        with patch.object(self.pub.time,'sleep',lambda _:None):
            with self.assertRaisesRegex(RuntimeError,'runtime_rule_not_effective'):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_known_unknown_operation_blocks_publication(self):
        self.mapping['/var/lib/fc-ops-readonly-monitor/gates/control.json'].write_text(json.dumps(
            {'mode':'RULES_ARMED','unknown_operations':[{'id':'original'}],'policy_revision':30}))
        self.pub.retry_guard=lambda:'all_sync_unconfirmed'
        with self.assertRaisesRegex(RuntimeError,'order_public_unresolved_operation'):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_busy_collector_lock_prevents_any_replacement(self):
        count=[0]
        def lock(*args):
            count[0]+=1
            if count[0]==2:raise BlockingIOError('real collector still active')
        self.pub.fcntl.flock=lock
        with self.assertRaises(BlockingIOError):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))

if __name__=='__main__':unittest.main()

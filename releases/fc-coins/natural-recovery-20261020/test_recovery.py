import ast
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from contextlib import nullcontext
sys.path.insert(0,str(Path(__file__).parent/'source'))
from player_auto_recovery import candidate, recovery_job_id

PID='00000000-0000-4000-8000-000000000001'
CID='00000000-0000-4000-8000-000000000002'
RUN='00000000-0000-4000-8000-000000000003'
NOW=datetime(2026,10,20,tzinfo=timezone.utc)

def function(name, file, bindings):
    tree=ast.parse((Path(__file__).parent/'source'/file).read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),file,'exec'),bindings)
    return bindings[name]

class Eligibility(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for folder in ['jobs','queue','executions','all-coin-sync','player-sync']:(self.root/folder).mkdir()
        self.old={'job_id':PID,'kind':'player_sync','actor':'system-automation','status':'failed',
                  'created_at':(NOW-timedelta(hours=1)).isoformat(),'completed_at':NOW.isoformat(),
                  'error':'player_sync_not_confirmed','error_detail':'chenchao_auth_unavailable',
                  'sync_result':{'status':'blocked_before_write','reason':'chenchao_auth_unavailable'},
                  'request':{'coin_execution_id':CID,'config_revision':9}}
        self.audit={'execution_id':CID,'status':'CONFIRMED','automatic':True,'sync_confirmed':True,
                    'created_at':(NOW-timedelta(hours=2)).isoformat(),'all_baseline':{'status':'confirmed'}}
        self.put('jobs',PID,self.old);self.put('executions',CID,self.audit);self.put('all-coin-sync',CID,{'status':'confirmed'})
    def put(self,folder,key,value):(self.root/folder/(key+'.json')).write_text(json.dumps(value))
    def run_candidate(self,**kw):return candidate(self.root,{'enabled':True,'revision':9},RUN,
        lambda k:(self.root/k).read_bytes(),lambda a:a.get('status')=='CONFIRMED',at=NOW,**kw)
    def test_valid_narrow_prewrite_failure(self):self.assertEqual(self.run_candidate()['old_player_job_id'],PID)
    def test_old_record_unchanged(self):
        before=(self.root/'jobs'/f'{PID}.json').read_bytes();self.run_candidate();self.assertEqual(before,(self.root/'jobs'/f'{PID}.json').read_bytes())
    def test_write_ledger_blocks_even_prewrite_error(self):
        self.put('player-sync',PID,{'status':'running'});self.assertRaises(ValueError,self.run_candidate)
    def test_dangling_ledger_symlink_blocks(self):
        (self.root/'player-sync'/f'{PID}.json').symlink_to(self.root/'missing');self.assertRaises(ValueError,self.run_candidate)
    def test_unknown_execution_blocks(self):
        self.put('executions',CID,{**self.audit,'status':'UNKNOWN'});self.assertRaises(ValueError,self.run_candidate)
    def test_unconfirmed_all_blocks(self):
        self.put('all-coin-sync',CID,{'status':'unknown'});self.assertRaises(ValueError,self.run_candidate)
    def test_wrong_failure_and_success_not_retried(self):
        for change in [{'status':'ready'},{'status':'interrupted'},{'error_detail':'TimeoutError'},
                       {'sync_result':{'status':'needs_reconcile','reason':'chenchao_auth_unavailable'}},
                       {'result':{'status':'confirmed'}},{'actor':'manual'}]:
            with self.subTest(change=change):
                self.put('jobs',PID,{**self.old,**change});self.assertRaises(ValueError,self.run_candidate)
    def test_future_completion_blocks(self):
        self.put('jobs',PID,{**self.old,'completed_at':(NOW+timedelta(seconds=1)).isoformat()});self.assertRaises(ValueError,self.run_candidate)
    def test_missing_directory_blocks(self):
        (self.root/'player-sync').rmdir();self.assertRaises(ValueError,self.run_candidate)
    def test_corrupt_ledger_blocks(self):
        (self.root/'executions'/f'{CID}.json').write_text('{bad');self.assertRaises(ValueError,self.run_candidate)
    def test_queue_busy(self):
        self.put('queue',RUN,{});self.assertRaises(ValueError,self.run_candidate)
    def test_other_running(self):
        self.put('jobs','other',{'status':'running','job_id':'other'});self.assertRaises(ValueError,self.run_candidate)
    def test_current_cycle_running_allowed(self):
        self.put('jobs',RUN,{'status':'running','job_id':RUN});self.run_candidate()
    def test_newer_player_failure_not_bypassed(self):
        self.put('jobs',RUN,{**self.old,'job_id':RUN,'created_at':(NOW+timedelta(seconds=1)).isoformat(),'error_detail':'unknown'});self.assertRaises(ValueError,self.run_candidate)
    def test_live_recovery_child_allowed_only_exact_binding(self):
        rid=recovery_job_id(RUN);row={'job_id':rid,'kind':'player_sync','status':'running','request':{'automatic_basis':{'parent_id':RUN}}}
        self.put('jobs',rid,row);self.run_candidate(active_job_id=rid)
        self.put('jobs',rid,{**row,'request':{}});self.assertRaises(ValueError,self.run_candidate,active_job_id=rid)
    def test_automatic_coin_required(self):
        self.put('executions',CID,{**self.audit,'automatic':False});self.assertRaises(ValueError,self.run_candidate)
    def test_disabled_and_revision_changed(self):
        for config in [{'enabled':False,'revision':9},{'enabled':True,'revision':10}]:
            with self.subTest(config=config):self.assertRaises(ValueError,candidate,self.root,config,RUN,lambda k:(self.root/k).read_bytes(),lambda a:True,at=NOW)

class Probe(unittest.TestCase):
    def setup_probe(self,result=(0,{'status':'preflight_ready'})):
        self.job={'job_id':RUN,'request':{'policy_revision':38}}
        self.b={'coin_execution_id':CID}
        self.env={'datetime':datetime,'timezone':timezone,'subprocess':subprocess,
          'load_player_sync_policy':Mock(return_value={'enabled':True,'revision':9}),
          'queue_mutation':nullcontext,'recovery_basis':Mock(return_value=self.b),
          'save_job':Mock(),'run_writer_request':Mock(return_value=result),
          'load_policy':Mock(return_value={'system_enabled':True,'mode':'auto','revision':38})}
        return function('probe_player_recovery','fc27_cloud_worker.py',self.env)
    def test_probe_readonly_bounded_and_once(self):
        f=self.setup_probe();self.assertTrue(f(self.job));self.assertFalse(f(self.job))
        call=self.env['run_writer_request'].call_args
        self.assertTrue(call.args[2]['dry_run']);self.assertTrue(call.args[2]['recovery_preflight']);self.assertEqual(call.args[3],180)
        self.env['run_writer_request'].assert_called_once()
    def test_failed_probe_no_retry_same_cycle(self):
        f=self.setup_probe((1,{'status':'blocked_before_write'}));self.assertFalse(f(self.job));self.assertFalse(f(self.job));self.env['run_writer_request'].assert_called_once()
    def test_probe_timeout_stops(self):
        f=self.setup_probe();self.env['run_writer_request'].side_effect=subprocess.TimeoutExpired('probe',180)
        self.assertFalse(f(self.job));self.assertEqual(self.job['player_recovery']['status'],'blocked')
    def test_basis_change_stops(self):
        f=self.setup_probe();self.env['recovery_basis'].side_effect=[self.b,{'coin_execution_id':'changed'}];self.assertFalse(f(self.job))
    def test_user_off_stops(self):
        f=self.setup_probe();self.env['load_policy'].return_value={'system_enabled':False,'mode':'auto','revision':38};self.assertFalse(f(self.job))
    def test_failure_rechecked_in_new_cycle(self):
        f=self.setup_probe((1,{}));self.assertFalse(f(self.job));self.assertFalse(f({'job_id':CID,'request':{'policy_revision':38}}));self.assertEqual(self.env['run_writer_request'].call_count,2)

class Schedule(unittest.TestCase):
    def test_recovered_gate_does_not_trigger_early(self):
        env={'datetime':datetime,'timezone':timezone,'timedelta':timedelta,'utc':lambda s:datetime.fromisoformat(s),'retry_plan':lambda *a:None,'player_sync_gate':lambda:'ready'}
        f=function('due','automation_tick.py',env)
        policy={'system_enabled':True,'mode':'auto','platforms':['PS'],'revision':38,'interval_minutes':120}
        last={'status':'ready','request':{'policy_revision':38},'created_at':NOW.isoformat(),'completed_at':NOW.isoformat(),'result':{'status':'deferred_player_sync'}}
        self.assertEqual(f(policy,last,NOW+timedelta(minutes=1)),'waiting');self.assertEqual(f(policy,last,NOW+timedelta(minutes=120)),'due')

class ReadonlyCycle(unittest.TestCase):
    def test_scheduled_retry_only_without_write_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ['requests','executions','all-coin-sync','player-sync']:(root/name).mkdir()
            env={'ROOT':root,'valid_job_id':lambda x:x==RUN,'read_record':lambda p:json.loads(p.read_text()),'resolved_execution':lambda r:r['status']=='CONFIRMED'}
            f=function('proven_readonly_cycle_failure','automation_tick.py',env)
            j={'job_id':RUN,'kind':'auto_cycle','status':'failed','error':'collection_incomplete','completed_at':NOW.isoformat(),'request':{'policy_revision':38}}
            self.assertTrue(f(j,38))
            for key in ['writer_result','result','changed','write_started','player_sync']:
                self.assertFalse(f({**j,key:{}},38))
            for error in ['writer_not_confirmed','TimeoutExpired','unknown']:
                self.assertFalse(f({**j,'error':error},38))
            self.assertFalse(f(j,39))
            (root/'executions'/f'{RUN}.json').write_text('{}');self.assertFalse(f(j,38))
    def test_readonly_failure_waits_for_natural_deadline(self):
        env={'datetime':datetime,'timezone':timezone,'timedelta':timedelta,'utc':lambda s:datetime.fromisoformat(s),'retry_plan':Mock(),'proven_readonly_cycle_failure':lambda *a:True}
        f=function('due','automation_tick.py',env)
        p={'system_enabled':True,'mode':'auto','platforms':['PS'],'revision':38,'interval_minutes':120}
        j={'status':'failed','request':{'policy_revision':38},'completed_at':NOW.isoformat()}
        self.assertEqual(f(p,j,NOW+timedelta(minutes=119)),'waiting');self.assertEqual(f(p,j,NOW+timedelta(minutes=120)),'due');env['retry_plan'].assert_not_called()

class CycleIntegration(unittest.TestCase):
    def setup_handle(self,probe):
        self.job={'kind':'auto_cycle','job_id':RUN,'request':{'policy_revision':38}}
        p={'system_enabled':True,'revision':38,'mode':'auto','platforms':['PS']}
        env={'load_policy':lambda:p,'collect_quote':Mock(return_value={'run_id':RUN}),
             'save_job':Mock(),'player_sync_gate':lambda:'needs_reconcile',
             'probe_player_recovery':Mock(return_value=probe),
             'previous_public_write_gap':Mock(return_value={'blocked':True})}
        return function('handle','fc27_cloud_worker.py',env),env
    def test_recovery_probe_runs_after_new_collection(self):
        f,e=self.setup_handle(True);r=f(self.job)
        e['collect_quote'].assert_called_once();e['probe_player_recovery'].assert_called_once_with(self.job)
        e['previous_public_write_gap'].assert_called_once();self.assertEqual(r['status'],'previous_public_price_unconfirmed')
    def test_failed_recovery_never_reaches_writer_path(self):
        f,e=self.setup_handle(False);r=f(self.job);self.assertEqual(r['status'],'deferred_player_sync');e['previous_public_write_gap'].assert_not_called()
    def test_in_progress_does_not_probe(self):
        f,e=self.setup_handle(True);e['player_sync_gate']=lambda:'in_progress';r=f(self.job);self.assertEqual(r['status'],'deferred_player_sync');e['probe_player_recovery'].assert_not_called()

if __name__=='__main__':unittest.main()

"""Isolated retry decisions and queue publication; no production access or writes."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK/'source'), '/opt/fc27-cloud-browser']
player_spec = importlib.util.spec_from_file_location('player_sync_policy', TASK/'tests/legacy_player_sync_policy.py')
player_policy = importlib.util.module_from_spec(player_spec)
player_spec.loader.exec_module(player_policy)
sys.modules['player_sync_policy'] = player_policy
spec = importlib.util.spec_from_file_location('candidate_tick', TASK/'source/automation_tick.py')
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)


class Selfheal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ('queue','jobs','runs','quotes','previews','requests','executions','all-coin-sync','player-sync','state','config'):
            (self.root/folder).mkdir()
        for name in tick.RETRY_LOCKS:
            (self.root/'state'/name).touch()
        self.now = datetime.now(timezone.utc)
        self.policy = {'system_enabled':True,'mode':'auto','platforms':['PS','XBOX','PC'],
                       'revision':28,'schedule_revision':28,'interval_minutes':120}
        self.job = {'job_id':str(uuid.uuid4()),'kind':'auto_cycle','status':'failed',
                    'created_at':(self.now-timedelta(minutes=12)).isoformat(),
                    'completed_at':(self.now-timedelta(minutes=10)).isoformat(),
                    'error':'collection_incomplete','request':{'policy_revision':28}}
        self.addCleanup(patch.stopall)
        patch.object(tick,'ROOT',self.root).start()
        patch.object(tick,'POLICY_FILE',self.root/'config/automation.json').start()
        patch.object(tick,'load_policy',return_value=deepcopy(self.policy)).start()
        patch.object(tick,'player_sync_gate',return_value='ready').start()
        self.reason('IGGM:http_blocked')

    def save(self, folder, identity, value):
        (self.root/folder/(identity+'.json')).write_text(json.dumps(value), encoding='utf-8')

    def reason(self, value):
        self.job['error_detail'] = value
        self.job['snapshot'] = {'run_id':self.job['job_id'],'status':'incomplete',
                                'quote_status':'NO_QUOTE','reason':value}
        self.save('runs',self.job['job_id'],self.job['snapshot'])
        self.save('jobs',self.job['job_id'],self.job)

    def rejection(self):
        self.job['error'] = 'writer_not_confirmed'
        self.job['error_detail'] = 'hook_scope_paused'
        self.job['writer_result'] = {'status':'FAILED','reason':'hook_scope_paused'}
        self.save('jobs',self.job['job_id'],self.job)

    def test_exact_initial_hook_rejection_only_and_readonly_preview_allowed(self):
        self.rejection()
        for folder in ('quotes','previews'):
            self.save(folder,self.job['job_id'],{'run_id':self.job['job_id']})
        self.assertTrue(tick.proven_prewrite_rejection(self.job,28))
        self.assertFalse(tick.proven_prewrite_rejection(self.job,29))
        for key,value in (('changed',[]),('result',{}),('sent',False),
                          ('error_detail','unknown'),('writer_result',{'status':'FAILED','reason':'hook_scope_paused','changed':[]}),
                          ('completed_at',(self.now+timedelta(hours=1)).isoformat()),('job_id','wrong')):
            changed = deepcopy(self.job); changed[key] = value
            self.assertFalse(tick.proven_prewrite_rejection(changed,28))
        for folder in ('requests','executions','all-coin-sync','player-sync'):
            self.save(folder,self.job['job_id'],{})
            self.assertFalse(tick.proven_prewrite_rejection(self.job,28))
            (self.root/folder/(self.job['job_id']+'.json')).unlink()
        (self.root/'executions'/('run-'+self.job['job_id']+'.used')).touch()
        self.assertFalse(tick.proven_prewrite_rejection(self.job,28))

    def test_rejection_requires_directories_and_no_unknown_execution(self):
        self.rejection()
        (self.root/'requests').rmdir()
        self.assertFalse(tick.proven_prewrite_rejection(self.job,28))
        (self.root/'requests').mkdir()
        self.save('executions',str(uuid.uuid4()),{'status':'UNKNOWN'})
        self.assertFalse(tick.proven_prewrite_rejection(self.job,28))

    def test_rejection_guard_propagates_pause_stale_revision_and_unknown(self):
        self.rejection()
        policy_module = sys.modules['automation_policy']
        for error in ('hook_scope_paused','hook_control_stale_or_changed','hook_control_unavailable'):
            with patch.object(policy_module,'hooks_before_write',side_effect=ValueError(error)) as guarded:
                self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['blocked_reason'],error)
                guarded.assert_called_once_with(self.policy,self.policy['platforms'],automatic=True)

    def test_two_clean_monitor_observations_then_original_timer_new_cycle(self):
        self.rejection()
        before = (self.root/'jobs'/(self.job['job_id']+'.json')).read_bytes()
        hook_spec = importlib.util.spec_from_file_location('original_hooks', TASK/'tests/legacy_hooks.py')
        hooks = importlib.util.module_from_spec(hook_spec); hook_spec.loader.exec_module(hooks)
        value = {'coin':{'config':self.policy,'job':{'job_id':self.job['job_id']}},
                 'issues':[{'level':'critical','code':'latest_coin_job_failed'}],
                 'publication':{'platforms':[{'platform':p,'status':'matched'} for p in self.policy['platforms']]},
                 'unknown_operations':[]}
        with patch.object(hooks,'bot_ready',return_value=False):
            control = hooks.controls(value,at=self.now)
            def guarded(policy,selected,automatic):
                self.assertEqual((policy,selected,automatic),(self.policy,self.policy['platforms'],True))
                if any(control['platforms'][p]['reasons'] for p in selected): raise ValueError('hook_scope_paused')
            with patch.object(sys.modules['automation_policy'],'hooks_before_write',side_effect=guarded):
                self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['status'],'retry_blocked')
                value['issues'] = [{'level':'warning','code':'historical_prewrite_failure'}]
                control = hooks.controls(value,control,at=self.now)
                self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['status'],'retry_blocked')
                control = hooks.controls(value,control,at=self.now)
                self.assertEqual(control['platforms']['PS']['phase'],'AWAITING_CYCLE')
                self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['status'],'retry_due')
                fake_fcntl = ModuleType('fcntl'); fake_fcntl.LOCK_EX=1; fake_fcntl.LOCK_NB=2
                fake_fcntl.flock = lambda *_:None
                with patch.dict(sys.modules,{'fcntl':fake_fcntl}), patch.object(tick,'queue_mutation',side_effect=nullcontext), \
                     (patch.object(tick,'sync_directory') if os.name=='nt' else nullcontext()):
                    result = tick.tick()
                self.assertEqual(result['status'],'queued')
                self.assertNotEqual(result['job_id'],self.job['job_id'])
                value['coin']['job'] = {'job_id':result['job_id'],'result':'no_price_change'}
                control = hooks.controls(value,control,at=self.now)
                self.assertEqual(control['platforms']['PS']['phase'],'RECOVERED')
        self.assertEqual((self.root/'jobs'/(self.job['job_id']+'.json')).read_bytes(),before)

    def test_retry_lineage_can_mix_timeout_parent_and_hook_rejection(self):
        root = deepcopy(self.job)
        root['created_at'] = (self.now-timedelta(hours=2)).isoformat()
        root['completed_at'] = (self.now-timedelta(hours=1)).isoformat()
        self.save('jobs',root['job_id'],root)
        self.job = deepcopy(root); self.job['job_id'] = str(uuid.uuid4())
        self.job['created_at'] = (self.now-timedelta(minutes=40)).isoformat()
        self.job['completed_at'] = (self.now-timedelta(minutes=30)).isoformat()
        self.job['request'].update(collection_retry_attempt=1,collection_retry_of=root['job_id'],
                                   collection_retry_root=root['job_id'])
        self.rejection()
        with patch.object(sys.modules['automation_policy'],'hooks_before_write'):
            plan = tick.retry_plan(self.policy,self.job,self.now)
        self.assertEqual((plan['status'],plan['delay_minutes'],plan['next_attempt']),('retry_due',15,2))

    def test_only_noncore_http_and_original_timeouts(self):
        for reason in ('IGGM:http_blocked','U4GM:http_blocked:PS','U7Buy:http_blocked',
                       'IGGM:http_blocked;U4GM:http_blocked;U7Buy:page_navigation_timeout',
                       'Lootbar:page_navigation_timeout','P2PAH:order_page_read_timeout:15'):
            with self.subTest(reason=reason):
                self.reason(reason)
                self.assertTrue(tick.proven_prewrite_timeout(self.job,28))
                self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['status'],'retry_due')

    def test_core_http_auth_price_identity_and_mixed_failure_rejected(self):
        for reason in ('Lootbar:http_blocked','IGGM:http_blocked;Lootbar:http_blocked',
                       'P2PAH:http_blocked','BOC:http_blocked','IGGM:price_invalid',
                       'IGGM:http_blocked;U4GM:identity_changed','U4GM:authentication_failed',
                       'IGGM:http_blocked:UNKNOWN','IGGM:http_blocked;','IGGM:collector_failed'):
            with self.subTest(reason=reason):
                self.reason(reason)
                self.assertFalse(tick.proven_prewrite_timeout(self.job,28))
                self.assertEqual(tick.due(self.policy,self.job,self.now),'paused_after_failure')

    def test_job_evidence_identity_and_revision_preserved(self):
        for key, value in (('result',{}),('writer_result',{}),('run_id',self.job['job_id'])):
            altered = deepcopy(self.job); altered[key] = value
            self.assertFalse(tick.proven_prewrite_timeout(altered,28))
        self.assertFalse(tick.proven_prewrite_timeout(self.job,29))
        changed = deepcopy(self.job); changed['snapshot']['run_id'] = str(uuid.uuid4())
        self.assertFalse(tick.proven_prewrite_timeout(changed,28))
        changed = deepcopy(self.job); changed['error_detail'] = 'U4GM:http_blocked'
        self.assertFalse(tick.proven_prewrite_timeout(changed,28))

    def test_existing_write_or_preview_artifacts_prevent_retry(self):
        for folder in ('quotes','previews','requests','executions','all-coin-sync','player-sync'):
            with self.subTest(folder=folder):
                self.save(folder,self.job['job_id'],{})
                self.assertFalse(tick.proven_prewrite_timeout(self.job,28))
                (self.root/folder/(self.job['job_id']+'.json')).unlink()
        self.save('previews',str(uuid.uuid4()),{'run_id':self.job['job_id']})
        self.assertFalse(tick.proven_prewrite_timeout(self.job,28))

    def test_unknown_execution_and_running_job_keep_guard(self):
        unknown = str(uuid.uuid4()); self.save('executions',unknown,{'status':'UNKNOWN'})
        self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['blocked_reason'],'write_unconfirmed')
        (self.root/'executions'/(unknown+'.json')).unlink()
        self.save('jobs',unknown,{'status':'running'})
        self.assertEqual(tick.retry_plan(self.policy,self.job,self.now)['blocked_reason'],'job_running')

    def test_original_backoff_attempt_bounds_and_user_switches(self):
        self.assertEqual(tick.RETRY_MINUTES,(5,15,30,60))
        for attempt in (-1,True,1000001):
            changed = deepcopy(self.job); changed['request']['collection_retry_attempt'] = attempt
            self.assertIsNone(tick.retry_plan(self.policy,changed,self.now))
        changed = deepcopy(self.job); changed['completed_at'] = self.now.isoformat()
        plan = tick.retry_plan(self.policy,changed,self.now)
        self.assertEqual((plan['status'],plan['delay_minutes']),('retry_waiting',5))
        self.assertIsNone(tick.retry_plan(dict(self.policy,system_enabled=False),self.job,self.now))
        self.assertIsNone(tick.retry_plan(dict(self.policy,mode='manual'),self.job,self.now))

    def test_new_uuid_queue_preserves_failed_operation_and_single_job(self):
        before = (self.root/'jobs'/(self.job['job_id']+'.json')).read_bytes()
        fake_fcntl = ModuleType('fcntl'); fake_fcntl.LOCK_EX=1; fake_fcntl.LOCK_NB=2
        fake_fcntl.flock = lambda *_:None
        # Native Linux lock/ownership enforcement is unchanged; this tests only publication logic.
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}), patch.object(tick,'queue_mutation',side_effect=nullcontext), \
             (patch.object(tick,'sync_directory') if os.name=='nt' else nullcontext()):
            result = tick.tick()
            self.assertEqual(result['status'],'queued')
            self.assertNotEqual(result['job_id'],self.job['job_id'])
            self.assertEqual(str(uuid.UUID(result['job_id'])),result['job_id'])
            queued = json.loads((self.root/'queue'/(result['job_id']+'.json')).read_text())
            self.assertEqual(queued['request'],{'policy_revision':28,'collection_retry_attempt':1,
                             'collection_retry_of':self.job['job_id'],'collection_retry_root':self.job['job_id']})
            self.assertEqual(tick.tick()['status'],'in_progress')
        self.assertEqual(len(list((self.root/'queue').glob('*.json'))),1)
        self.assertEqual((self.root/'jobs'/(self.job['job_id']+'.json')).read_bytes(),before)
        self.assertEqual(list((self.root/'executions').glob('*.json')),[])


if __name__ == '__main__':
    unittest.main()

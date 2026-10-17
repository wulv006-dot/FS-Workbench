"""Isolated regressions for transient reads, landed POSTs, and exact publishing."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE/'source'))
import coin_all_sync_job as coins

legacy_path = HERE/'fixtures/test_coin_all_sync.py'
spec = importlib.util.spec_from_file_location('legacy_all_tests', legacy_path)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

class LandedTimeoutManager(legacy.Manager):
    mode = 'landed'
    def request(self,path,data=None,token=None):
        if data is not None and path.endswith('163329309'):
            if self.mode == 'not_landed':
                self.posts.append(163329309)
                raise TimeoutError('private backend details must not be persisted')
            result = super().request(path,data,token)
            if self.mode == 'protected_changed':
                self.rows[163329309]['is_rec'] = 0
            if self.mode == 'source_changed':
                self.rows[163329311]['unit_price'] = .999
            raise TimeoutError('private backend details must not be persisted')
        return super().request(path,data,token)

class WriteRecoveryTests(legacy.AllBaselineTest):
    def setUp(self):
        super().setUp()
        self.pause = patch.object(coins.time,'sleep',lambda _:None)
        self.pause.start()
        self.addCleanup(self.pause.stop)
        self.gate = patch.dict(sys.modules,{'automation_policy':types.SimpleNamespace(hooks_before_write=lambda *a,**kw:None)})
        self.gate.start()
        self.addCleanup(self.gate.stop)
    def test_timeout_landed_is_proven_twice_without_reposting(self):
        self.manager = LandedTimeoutManager(self.rows)
        result = self.run_sync()
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(self.manager.posts,[163329309,163329275,163329343])
        proof = self.ledger['steps'][0]['timeout_readback']
        self.assertEqual(proof['status'],'confirmed')
        self.assertEqual(len(proof['rounds']),2)
        self.assertEqual(proof['price_posts_retried'],0)
        self.assertEqual(self.ledger['steps'][0]['post_response']['transport_error'],'TimeoutError')
        self.assertNotIn('private backend',json.dumps(self.ledger))
    def test_unproven_or_changed_timeout_stops_and_never_posts_next_product(self):
        for mode in ('not_landed','protected_changed','source_changed'):
            with self.subTest(mode=mode):
                self.setUp()
                self.manager = LandedTimeoutManager(self.rows)
                self.manager.mode = mode
                with self.assertRaises(ValueError):self.run_sync()
                self.assertEqual(self.manager.posts,[163329309])
                self.assertEqual(self.ledger['status'],'needs_reconcile')
    def test_confirmed_post_rejection_is_not_recovered_as_timeout(self):
        self.manager.reject=True
        with self.assertRaisesRegex(ValueError,'request_rejected'):self.run_sync()
        self.assertEqual(self.manager.posts,[163329309])
        self.assertNotIn('timeout_readback',self.ledger['steps'][0])
    def test_policy_change_during_timeout_stops_before_next_product(self):
        self.manager=LandedTimeoutManager(self.rows)
        original=self.manager.request
        def request(path,data=None,token=None):
            if data is not None:
                try:return original(path,data,token)
                finally:self.policy['revision']+=1
            return original(path,data,token)
        self.manager.request=request
        with self.assertRaisesRegex(ValueError,'preflight_changed'):self.run_sync()
        self.assertEqual(self.manager.posts,[163329309])
    def test_timeout_readback_expiry_is_not_confirmation(self):
        self.manager=LandedTimeoutManager(self.rows)
        original=coins.confirm_timed_out_write
        times=iter([0,31])
        def expired(*args):
            return original(*args,clock=lambda:next(times),sleep=lambda _:None)
        with patch.object(coins,'confirm_timed_out_write',expired):
            with self.assertRaisesRegex(ValueError,'deadline'):self.run_sync()
        self.assertEqual(self.manager.posts,[163329309])

class FakeCollectorTimeout(TimeoutError):pass
playwright_api = types.SimpleNamespace(sync_playwright=lambda:None,TimeoutError=FakeCollectorTimeout)
with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':playwright_api}):
    spec=importlib.util.spec_from_file_location('active_collector',HERE/'source/collect_competitor_browser.py')
    browser=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(browser)

class ReadRecoveryTests(unittest.TestCase):
    def collect(self, effects, times=(0,0), context_count=1):
        collector=Mock(side_effect=effects)
        chromium=Mock()
        chromium.connect_over_cdp.return_value.contexts=[object()]*context_count
        manager=Mock()
        manager.__enter__=Mock(return_value=types.SimpleNamespace(chromium=chromium))
        manager.__exit__=Mock(return_value=False)
        output=StringIO()
        with patch.object(sys,'argv',['collector','IGGM']),patch.object(browser,'sync_playwright',return_value=manager),\
             patch.dict(browser.COLLECTORS,{'IGGM':collector}),patch.object(browser.time,'sleep',lambda _:None),\
             patch.object(browser.time,'monotonic',side_effect=times),redirect_stdout(output):
            status=browser.main()
        return status,json.loads(output.getvalue()),collector
    def test_known_read_timeout_reopens_once_and_discards_partial_data(self):
        rows=[{'platform':p} for p in browser.PLATFORMS]
        status,result,call=self.collect([FakeCollectorTimeout('Locator.click: private page text'),rows])
        self.assertEqual(status,0);self.assertEqual(call.call_count,2)
        self.assertEqual(result['read_retries'][0]['reason'],'platform_click_timeout')
        self.assertNotIn('private page',json.dumps(result))
    def test_second_timeout_is_terminal_and_keeps_original_diagnostic(self):
        status,result,call=self.collect([FakeCollectorTimeout('Locator.click: x'),FakeCollectorTimeout('Page.goto: y')])
        self.assertEqual(status,1);self.assertEqual(call.call_count,2)
        self.assertEqual(result['reason'],'page_navigation_timeout')
        self.assertEqual(len(result['read_retries']),1)
    def test_validation_http_or_close_error_is_not_retried(self):
        for error in (ValueError('platform_mismatch'),ValueError('http_blocked'),FakeCollectorTimeout('Page.close: x')):
            status,result,call=self.collect([error])
            self.assertEqual(status,1);self.assertEqual(call.call_count,1)
    def test_remaining_wrapper_budget_does_not_expand(self):
        status,result,call=self.collect([FakeCollectorTimeout('Locator.click: x')],times=(0,60))
        self.assertEqual(status,1);self.assertEqual(call.call_count,1)
    def test_ambiguous_contexts_or_missing_platforms_fail_closed(self):
        status,_,call=self.collect([],context_count=2)
        self.assertEqual(status,1);self.assertEqual(call.call_count,0)
        status,_,call=self.collect([[{'platform':'PS'}]])
        self.assertEqual(status,1);self.assertEqual(call.call_count,1)

@unittest.skipIf(sys.platform=='win32','Publisher directory fsync requires Linux; verified there before release')
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
        for name,remote in {'coin_all_sync_job.py':'/opt/fc27-cloud-browser/coin_all_sync_job.py',
                            'collect_competitor_browser.py':'/opt/fc27-cloud-browser/collector/collect_competitor_browser.py'}.items():
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
        with patch.dict(sys.modules,{'fcntl':stub,'automation_tick':types.SimpleNamespace(queue_mutation=nullcontext)}):
            spec=importlib.util.spec_from_file_location('scoped_publisher',HERE/'publish.py')
            self.pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.pub)
        self.pub.ROOT=self.root;self.pub.STAGE=self.stage;self.pub.HARDENING=True
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
    def test_exact_two_targets_apply_without_service_restart(self):
        self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=2\n' for p in self.mapping.values() if p.suffix=='.py'))
        self.assertFalse(any('stop' in cmd or 'start' in cmd for cmd in self.commands))
    def test_check_only_does_not_replace_files(self):
        self.run_publish(False)
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
        self.assertFalse(list((self.root/'rollback').iterdir()))
    def test_extra_or_remapped_target_is_rejected(self):
        self.manifest['targets']['coin_all_sync_job.py']['target']='/opt/unrelated.py'
        with self.assertRaisesRegex(ValueError,'exact_fc_hardening_scope'):self.run_publish()
    def test_baseline_or_payload_drift_is_rejected(self):
        self.runtime.joinpath('coin_all_sync_job.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'baseline_changed'):self.run_publish()
    def test_partial_rename_failure_restores_both_original_files(self):
        original=self.pub.swap;counter=[0]
        def swap(source,target):
            original(source,target);counter[0]+=1
            if counter[0]==2:raise OSError('simulated fsync failure after second rename')
        self.pub.swap=swap
        with self.assertRaises(OSError):self.run_publish()
        self.assertEqual(counter[0],4)
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_health_failure_restores_original_files(self):
        self.monitor['health']['worker']='unverified'
        with patch.object(self.pub.time,'sleep',lambda _:None):
            with self.assertRaisesRegex(RuntimeError,'runtime_rule_not_effective'):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_known_unknown_operation_blocks_publication(self):
        self.mapping['/var/lib/fc-ops-readonly-monitor/gates/control.json'].write_text(json.dumps(
            {'mode':'RULES_ARMED','unknown_operations':[{'id':'original'}],'policy_revision':30}))
        with self.assertRaisesRegex(RuntimeError,'hook_runtime_control_not_ready'):self.run_publish()
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

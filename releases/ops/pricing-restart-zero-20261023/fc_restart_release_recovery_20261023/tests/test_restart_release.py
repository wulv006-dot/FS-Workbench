import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value
legacy=load('original_lifecycle_tests',ROOT/'fc_browser_recovery_20261023/tests/test_lifecycle.py')
m=load('new_lifecycle',ROOT/'fc_restart_release_recovery_20261023/source/browser_lifecycle.py')
legacy.m=m
PROBE_FUNCTION=m.probe
LifecycleTests=legacy.LifecycleTests
MaintenanceBoundaries=legacy.MaintenanceBoundaries

class RestartRelease(MaintenanceBoundaries):
    def original(self,state='verified_after_unknown'):
        previous=dict(state=state,event_id='original',action='restart',
                      before_container=dict(id='same',started_at='before'),readback={'global_workers':0})
        (self.root/'state/browser-lifecycle.json').write_text(json.dumps(previous))
        return previous

    def test_existing_recovered_restart_is_released_once(self):
        self.original()
        result=m.maintain()
        self.assertEqual(result['status'],'restart_idle_verified')
        self.assertEqual(self.probe.call_args_list[-1].args,('release',))
        saved=json.loads((self.root/'state/browser-lifecycle.json').read_text())
        self.assertEqual(saved['idle_release']['event_id'],'original')
        self.probe.reset_mock()
        self.assertEqual(m.maintain()['status'],'healthy')
        self.probe.assert_called_once_with()
        self.command.assert_not_called()

    def test_unknown_restart_release_uses_original_id(self):
        self.original('unknown')
        result=m.maintain()
        self.assertEqual(result['event_id'],'original')
        self.assertEqual(result['outcome'],'verified_after_unknown')
        self.assertTrue((self.root/'recovery-receipts/browser-lifecycle-original.json').exists())
        self.command.assert_not_called()

    def test_stale_restart_or_foreign_container_never_releases(self):
        prior=self.original()
        for current in [dict(id='other',started_at='new',running=True,restarting=False),
                        dict(id='same',started_at='before',running=True,restarting=False)]:
            self.assertFalse(m.release_required(prior,current))

    def test_failed_release_not_accepted(self):
        self.original()
        self.probe.side_effect=[{'status':'ok'},{'status':'failed','reason':'test_timeout'}]
        self.assertEqual(m.maintain()['status'],'restart_idle_unverified')
        saved=json.loads((self.root/'state/browser-lifecycle.json').read_text())
        self.assertNotIn('idle_release',saved)
        self.command.assert_not_called()

    def test_new_event_does_not_inherit_old_acceptance(self):
        self.original()
        with patch.object(m,'release_required',return_value=False), patch.object(m,'memory_bytes',return_value=m.MEMORY_LIMIT):
            m.maintain()
        saved=json.loads((self.root/'state/browser-lifecycle.json').read_text())
        self.assertNotEqual(saved['event_id'],'original')
        self.assertNotIn('readback',saved)

    def test_release_closes_old_document_and_verifies_browser_worker(self):
        self.assertIn("os.environ['FC27_CDP_ENDPOINT']='http://127.0.0.1:9225'",m.PROBE)
        self.assertIn('_release_product_document(page,deadline=',m.PROBE)
        self.assertIn("session.send('Target.getTargets')",m.PROBE)
        self.assertNotIn('page.reload(',m.PROBE)
        self.assertIn("pages=[x for x in b.contexts[0].pages if x.url==IDLE_URL]",m.PROBE)
        self.assertIn("raise ValueError('product_target_release_unverified')",m.PROBE)
        compile(m.PROBE,'probe','exec')

    def test_probe_deadline_covers_container_children(self):
        import subprocess
        for action,seconds,outer in [('check','6s',8),('release','13s',16)]:
            with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{"status":"ok"}\n','')) as run:
                self.assertEqual(PROBE_FUNCTION(action),{'status':'ok'})
            args=run.call_args.args[0]
            self.assertIn('timeout',args);self.assertIn(seconds,args)
            self.assertEqual(run.call_args.kwargs['timeout'],outer)
            if action=='check':self.assertIn('--fc-health',args)

    def test_empty_successful_process_is_not_browser_evidence(self):
        import subprocess
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')):
            self.assertEqual(PROBE_FUNCTION()['status'],'failed')

if __name__=='__main__':unittest.main()

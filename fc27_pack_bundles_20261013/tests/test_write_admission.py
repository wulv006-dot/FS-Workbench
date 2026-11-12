"""The publisher shares the dispatch lock; accepted writes finish before code restart."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'src/pack_bundles_server.py'
spec=importlib.util.spec_from_file_location('bundle_admission_test',SOURCE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class WriteAdmission(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.folder=Path(folder.name);self.store=mod.Store(self.folder)

    def other_process(self):
        script="""
import importlib.util,sys
from pathlib import Path
s=importlib.util.spec_from_file_location('other_bundle',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
try:
 a=m.WriteAdmission(Path(sys.argv[2]));a.close();print('acquired')
except ValueError as e:
 print(str(e))
"""
        result=subprocess.run([sys.executable,'-c',script,str(SOURCE),str(self.folder/'write-admission.lock')],
                              capture_output=True,text=True,check=True)
        return result.stdout.strip()

    def handler(self):
        handler=object.__new__(mod.Handler);handler.store=self.store
        handler.path='/api/write-prices';handler.headers={'Content-Length':'2'}
        handler.rfile=io.BytesIO(b'{}');handler._https_required=lambda:True;handler._json=Mock()
        return handler

    def test_process_lock_refuses_new_dispatch_until_original_result_is_recorded(self):
        self.assertTrue(hasattr(mod,'WriteAdmission'))
        admission=mod.WriteAdmission(self.folder/'write-admission.lock')
        self.addCleanup(admission.close)
        self.assertEqual(self.other_process(),'write_in_progress_or_maintenance')
        admission.close()
        self.assertEqual(self.other_process(),'acquired')

    def test_accepted_manual_request_holds_lock_before_202_until_worker_log_completion(self):
        self.assertTrue(hasattr(mod,'WriteAdmission'))
        handler=self.handler();captured={}
        class Thread:
            def __init__(self, target, args, daemon):captured.update(target=target,args=args)
            def start(self):pass
        with patch.object(mod.threading,'Thread',Thread):handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0],202)
        self.assertEqual(self.other_process(),'write_in_progress_or_maintenance')
        with patch.object(mod,'execute_write') as write:
            captured['target'](*captured['args'])
            self.assertIsNotNone(write.call_args.kwargs.get('_admission'))
        self.assertEqual(self.other_process(),'acquired')
        self.assertFalse(mod.WRITE_LOCK.locked())

    def test_publisher_admission_returns_409_before_thread_or_acceptance(self):
        self.assertTrue(hasattr(mod,'WriteAdmission'))
        with mod.WriteAdmission(self.folder/'write-admission.lock'):
            handler=self.handler()
            with patch.object(mod.threading,'Thread') as thread:handler.do_POST()
            self.assertEqual(handler._json.call_args.args[0],409)
            thread.assert_not_called()
        self.assertFalse(mod.WRITE_LOCK.locked())

    def test_direct_execution_retains_admission_through_terminal_log(self):
        self.assertTrue(hasattr(mod,'WriteAdmission'))
        def dispatch(*args,**kwargs):
            self.assertEqual(self.other_process(),'write_in_progress_or_maintenance')
            return {'results':[]}
        with patch.object(mod,'_execute_write_locked',side_effect=dispatch):
            mod.execute_write(self.store)
        self.assertEqual(self.other_process(),'acquired')

    def test_worker_unknown_logs_once_under_same_lock_and_never_replays(self):
        handler=self.handler();admission=mod.WriteAdmission(self.folder/'write-admission.lock')
        self.assertTrue(mod.WRITE_LOCK.acquire(blocking=False))
        def recorded(result):
            self.assertEqual(self.other_process(),'write_in_progress_or_maintenance')
            self.assertEqual(result['action'],'error')
        with patch.object(mod,'execute_write',side_effect=TimeoutError('unknown')) as write, \
             patch.object(self.store,'_append_write_log',side_effect=recorded) as log:
            handler._write_job(None,None,admission)
            write.assert_called_once();log.assert_called_once()
        self.assertEqual(self.other_process(),'acquired')

    def test_automatic_dispatch_uses_same_admission_without_changing_switches(self):
        self.store.config['settings'].update(write_enabled=True,write_auto=True,write_dry_run=False)
        with mod.WriteAdmission(self.folder/'write-admission.lock'), \
             patch.object(self.store,'download_players',return_value=0), \
             patch.object(self.store,'get_rates',return_value=({},{})), \
             patch.object(self.store,'_overlay_order_b2c',return_value={}), \
             patch.object(mod,'execute_write') as write:
            result=self.store.refresh()
            write.assert_not_called()
        self.assertEqual(result['write'],{'skipped':'write_in_progress'})
        self.assertTrue(self.store.settings()['write_enabled'])
        self.assertTrue(self.store.settings()['write_auto'])


if __name__=='__main__':unittest.main()

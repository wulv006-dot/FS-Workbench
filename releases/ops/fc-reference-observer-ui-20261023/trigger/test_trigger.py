import ast
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).parent/'source/observe.py'
spec=importlib.util.spec_from_file_location('observer_trigger',SOURCE)
observe=importlib.util.module_from_spec(spec);spec.loader.exec_module(observe)


class Trigger(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);(self.root/'jobs').mkdir()
        self.replace=patch.object(observe,'FC',self.root);self.replace.start();self.addCleanup(self.replace.stop)
        self.clock=0

    def job(self,name,**values):
        path=self.root/'jobs'/(name+'.json');path.write_text(json.dumps(values),encoding='utf-8');return path

    def sleep(self,seconds):self.clock+=seconds

    def clocked(self):
        return patch.object(observe.time,'monotonic',side_effect=lambda:self.clock)

    def test_original_main_business_locks_and_id_handling_unchanged(self):
        text=SOURCE.read_text(encoding='utf-8')
        main=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='main')
        # Only this reviewed read-reuse branch may differ; retain the original locks/IDs checksum.
        reuse="""            reference=snapshot.get('reference_competitors')
            if reference is None:
                rows=public_read()
            elif reference.get('status')=='captured' and reference.get('run_id')==jid:
                rows=reference['offers']
            else:
                raise ValueError('original_cycle_itemd2r_unavailable_no_refetch')"""
        source=ast.get_source_segment(text,main)
        self.assertEqual(source.count(reuse),1)
        source=source.replace(reuse,'            rows=public_read()',1)
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),
                         '93370ac11c2bc41fc5e87cabd2f1e1157f39558d87be762f8078e5865fe8271d')

    def test_progress_updates_wait_in_same_process_until_ready(self):
        self.job('old',kind='auto_cycle',status='ready',created_at='2026-10-23T06:56:00+00:00')
        self.job('new',kind='auto_cycle',status='running',created_at='2026-10-23T08:59:00+00:00')
        def progress(seconds):
            self.sleep(seconds)
            self.job('new',kind='auto_cycle',status='ready' if self.clock>=6 else 'running',created_at='2026-10-23T08:59:00+00:00')
        with self.clocked(),patch.object(observe.time,'sleep',side_effect=progress),patch.object(observe,'main',return_value={'status':'observed','run_id':'new'}) as main:
            self.assertEqual(observe.run_coalesced()['run_id'],'new')
        self.assertEqual(self.clock,6);main.assert_called_once()

    def test_latest_ready_uses_created_time_not_touched_old_mtime(self):
        self.job('new',kind='auto_cycle',status='ready',created_at='2026-10-23T08:59:00+00:00')
        self.job('old',kind='auto_cycle',status='ready',created_at='2026-10-23T06:56:00+00:00')
        self.assertEqual(observe.latest_completed()['created_at'],'2026-10-23T08:59:00+00:00')

    def test_pending_includes_other_business_writers(self):
        self.job('preview',kind='preview',status='running')
        self.assertTrue(observe.business_job_pending())

    def test_incomplete_atomic_temporary_is_not_a_business_job(self):
        (self.root/'jobs/.tmp-half.json').write_text('{',encoding='utf-8')
        self.assertFalse(observe.business_job_pending())
        self.assertIsNone(observe.latest_completed())

    def test_idle_lock_contention_coalesces_then_uses_original_entry(self):
        with self.clocked(),patch.object(observe.time,'sleep',side_effect=self.sleep),patch.object(observe,'main',side_effect=[BlockingIOError(),{'status':'observed'}]) as main:
            self.assertEqual(observe.run_coalesced()['status'],'observed')
        self.assertEqual(self.clock,2);self.assertEqual(main.call_count,2)

    def test_wait_budget_is_bounded_and_never_collects_while_busy(self):
        self.job('new',kind='auto_cycle',status='running')
        with self.clocked(),patch.object(observe.time,'sleep',side_effect=self.sleep),patch.object(observe,'main') as main:
            with self.assertRaisesRegex(BlockingIOError,'wait_budget'):
                observe.run_coalesced()
        self.assertEqual(self.clock,300);main.assert_not_called()

    def test_idle_already_observed_does_not_collect_again(self):
        with patch.object(observe,'main',return_value={'status':'already_observed'}) as main,patch.object(observe.time,'sleep') as sleep:
            self.assertEqual(observe.run_coalesced()['status'],'already_observed')
        main.assert_called_once();sleep.assert_not_called()

    def cli(self,outcome,export_error=None):
        exporter=types.ModuleType('reference_observer_view')
        called=[]
        def publish():
            called.append('published')
            if export_error:raise export_error
        exporter.publish_view=publish
        out,err=io.StringIO(),io.StringIO()
        action={'side_effect':outcome} if isinstance(outcome,Exception) else {'return_value':outcome}
        with patch.dict('sys.modules',{'reference_observer_view':exporter}),patch.object(observe,'run_coalesced',**action),redirect_stdout(out),redirect_stderr(err):
            code=observe.cli()
        return code,called,out.getvalue(),err.getvalue()

    def test_success_and_noop_always_publish_after_original_result(self):
        for status in ('observed','already_observed','no_completed_cycle'):
            code,calls,out,err=self.cli({'status':status})
            self.assertEqual(code,0);self.assertEqual(calls,['published']);self.assertEqual(err,'')
            self.assertEqual(json.loads(out)['status'],status)

    def test_export_failure_does_not_change_sample_or_retry_fetch(self):
        result={'status':'observed','run_id':'original','price_write_performed':False}
        code,calls,out,err=self.cli(result,PermissionError())
        self.assertEqual(code,2);self.assertEqual(calls,['published'])
        self.assertEqual(json.loads(out),result)
        self.assertEqual(json.loads(err)['status'],'view_export_failed')
        self.assertTrue(json.loads(err)['sample_state_unchanged'])

    def test_budget_deferred_keeps_original_restart_exit_and_publishes(self):
        code,calls,out,err=self.cli(BlockingIOError())
        self.assertEqual(code,75);self.assertEqual(calls,['published'])
        self.assertEqual(json.loads(out)['status'],'deferred_business_busy')


if __name__=='__main__':unittest.main()

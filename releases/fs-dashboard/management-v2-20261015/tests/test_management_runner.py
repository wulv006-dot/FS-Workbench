import unittest,tempfile,json,sys
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source/backend'))
import management_v2_runner as r
class Runner(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'work';self.public=Path(self.tmp.name)/'public.json';self.status=Path(self.tmp.name)/'status.json';self.targets=Path(self.tmp.name)/'targets.json';self.targets.write_text('{}');self.now=datetime(2026,10,15,1,tzinfo=r.SH)
 def run_at(self,**kw):return r.run(root=self.root,public=self.public,status=self.status,targets=self.targets,clock=lambda:self.now,reader=lambda _:None,**kw)
 def facts(self,*args,**kw):return {'contract':r.CONTRACT,'snapshotId':'management-'+'a'*24,'status':'partial','businessDate':'2026-10-15','validUntil':'2026-10-16T00:00:00+08:00'}
 def test_daytime_does_not_touch_files(self):
  self.now=self.now.replace(hour=7);self.assertEqual(self.run_at()['status'],'outside_nightly_window');self.assertFalse(self.root.exists());self.assertFalse(self.public.exists())
 def test_once_per_day_and_manual_not_forced_replay(self):
  with patch.object(r,'collect',side_effect=self.facts) as call:
   self.assertEqual(self.run_at()['status'],'facts_ready');before=self.public.read_bytes();self.assertEqual(self.run_at(manual=True)['status'],'already_completed');self.assertEqual(call.call_count,1);self.assertEqual(self.public.read_bytes(),before)
  self.assertEqual(json.loads(before)['analysis']['status'],'pending')
  self.assertEqual(json.loads(self.status.read_text())['fact_status'],'partial')
 def test_failure_preserves_previous_publication(self):
  self.public.write_text('{"previous":true}')
  with patch.object(r,'collect',side_effect=OSError('not exposed')):self.assertEqual(self.run_at()['status'],'failed')
  self.assertEqual(self.public.read_text(),'{"previous":true}');self.assertEqual(json.loads(self.status.read_text())['error_code'],'collection_failed')
 def test_failed_day_can_retry_without_replaying_model(self):
  with patch.object(r,'collect',side_effect=TimeoutError('source_timeout')):self.assertEqual(self.run_at()['status'],'failed')
  with patch.object(r,'collect',side_effect=self.facts):self.assertEqual(self.run_at()['status'],'facts_ready')
 def test_late_finish_not_published(self):
  def late(*a,**k):self.now=self.now.replace(hour=7);return self.facts()
  with patch.object(r,'collect',side_effect=late):self.assertEqual(self.run_at()['status'],'failed')
  self.assertFalse(self.public.exists())
 def test_concurrent_collector_not_started(self):
  with r.lock(self.root/'run.lock') as held:
   self.assertTrue(held)
   with patch.object(r,'collect') as call:self.assertEqual(self.run_at()['status'],'already_running');call.assert_not_called()
if __name__=='__main__':unittest.main()

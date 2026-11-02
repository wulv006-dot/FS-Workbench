import contextlib,sys,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from admin_live_admission import LiveAdminAdmission,LiveBusy

class Admission(unittest.TestCase):
 def test_shared_pool_and_single_live_slot_reject_concurrent_without_queue(self):
  started=threading.Event();release=threading.Event();calls=[]
  def work():calls.append('live');started.set();release.wait(2);return 'done'
  with ThreadPoolExecutor(max_workers=1) as pool:
   gate=LiveAdminAdmission(pool,contextlib.nullcontext)
   result=[];thread=threading.Thread(target=lambda:result.append(gate.run(work,1)))
   thread.start();self.assertTrue(started.wait(1))
   with self.assertRaises(LiveBusy):gate.run(lambda:calls.append('extra'),1)
   release.set();thread.join(2);self.assertEqual(result,['done']);self.assertEqual(calls,['live'])
 def test_timeout_does_not_release_running_slot_or_start_second_source(self):
  started=threading.Event();release=threading.Event();calls=[]
  def slow():calls.append('live');started.set();release.wait(2)
  with ThreadPoolExecutor(max_workers=1) as pool:
   gate=LiveAdminAdmission(pool,contextlib.nullcontext)
   with self.assertRaises(TimeoutError):gate.run(slow,.05)
   self.assertTrue(started.is_set())
   with self.assertRaises(LiveBusy):gate.run(lambda:calls.append('extra'),1)
   release.set();pool.shutdown(wait=True);self.assertEqual(calls,['live'])
 def test_queued_timeout_cancels_before_source_and_releases_slot(self):
  started=threading.Event();release=threading.Event();calls=[]
  def occupied():started.set();release.wait(2)
  with ThreadPoolExecutor(max_workers=1) as pool:
   pool.submit(occupied);self.assertTrue(started.wait(1));gate=LiveAdminAdmission(pool,contextlib.nullcontext)
   with self.assertRaises(TimeoutError):gate.run(lambda:calls.append('late'),.05)
   release.set();pool.shutdown(wait=True);self.assertEqual(calls,[])
 def test_maintenance_denied_never_calls_source(self):
  calls=[]
  @contextlib.contextmanager
  def unavailable():raise BlockingIOError('maintenance');yield
  with ThreadPoolExecutor(max_workers=1) as pool:
   gate=LiveAdminAdmission(pool,unavailable)
   with self.assertRaises(LiveBusy):gate.run(lambda:calls.append('source'),1)
  self.assertEqual(calls,[])
 def test_slot_released_after_source_error(self):
  def fail():raise ValueError('source_failed')
  with ThreadPoolExecutor(max_workers=1) as pool:
   gate=LiveAdminAdmission(pool,contextlib.nullcontext)
   with self.assertRaises(ValueError):gate.run(fail,1)
   self.assertEqual(gate.run(lambda:'recovered',1),'recovered')

if __name__=='__main__':unittest.main(verbosity=2)

"""One non-queued live request, using the host's existing Admin pool and lease."""
import threading,time
from concurrent.futures import TimeoutError as FutureTimeout

class LiveBusy(Exception):pass

class LiveAdminAdmission:
 def __init__(self,executor,maintenance,clock=time.monotonic):
  if not callable(getattr(executor,'submit',None)) or not callable(maintenance) or not callable(clock):raise ValueError('host_admission_required')
  self.executor,self.maintenance,self.clock=executor,maintenance,clock
  self.slot=threading.BoundedSemaphore(1)
 def run(self,operation,timeout_seconds):
  if not callable(operation) or isinstance(timeout_seconds,bool) or not isinstance(timeout_seconds,(int,float)) or not 0<timeout_seconds<=10:raise ValueError('invalid_admission')
  if not self.slot.acquire(blocking=False):raise LiveBusy('live_busy')
  deadline=self.clock()+timeout_seconds
  def task():
   try:
    if self.clock()>=deadline:raise TimeoutError('source_timeout')
    try:
     with self.maintenance():
      if self.clock()>=deadline:raise TimeoutError('source_timeout')
      return operation()
    except BlockingIOError:raise LiveBusy('maintenance_in_progress') from None
   finally:self.slot.release()
  try:future=self.executor.submit(task)
  except BaseException:
   self.slot.release();raise
  future.add_done_callback(lambda result:self.slot.release() if result.cancelled() else None)
  try:return future.result(timeout=max(0,deadline-self.clock()))
  except FutureTimeout:
   future.cancel();raise TimeoutError('source_timeout') from None

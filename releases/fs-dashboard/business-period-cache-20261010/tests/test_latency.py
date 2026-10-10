import sys,unittest
from pathlib import Path
from threading import Event
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from live_summary import SummaryCache,query,SHANGHAI
from test_live_summary import PROFILES,params,record

class LatencyTests(unittest.TestCase):
 def test_separate_queued_reading_finished_without_extra_workers(self):
  gate=Event();started=Event();calls=[];clock=[0]
  def order(q):calls.append(q['start']);started.set();gate.wait(2);return record(q,'Order')
  cache=SummaryCache(record,order,PROFILES,clock=lambda:clock[0]);self.addCleanup(cache.close);self.addCleanup(gate.set)
  qs=[query(params(start=d,end=d),PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI)) for d in ['2026-10-09','2026-10-08']]
  cache.get(qs[0]);self.assertTrue(started.wait(1));clock[0]=2;cache.get(qs[1])
  cache.pools['Admin'].submit(lambda:None).result(1)
  self.assertEqual(cache.get(qs[0])[1]['sources']['Order']['phase'],'reading')
  self.assertEqual(cache.get(qs[1])[1]['sources']['Order']['phase'],'queued')
  self.assertEqual(calls,['2026-10-09'])
  clock[0]=5;gate.set();cache.pools['Order'].submit(lambda:None).result(1)
  data=cache.get(qs[1])[1];self.assertEqual(data['sources']['Order']['phase'],'available');self.assertEqual(data['sources']['Order']['queueSeconds'],3)
  cache.get(qs[1]);self.assertEqual(len(calls),2)
 def test_deferred_and_read_failure_are_distinct_and_safe(self):
  for exc,phase,error in [(BlockingIOError('private detail'),'deferred','collector_busy'),(OSError('scheduled_collection_due'),'deferred','scheduled_collection_due'),(OSError('private detail'),'failed','source_read_failed')]:
   def fail(q,exc=exc):raise exc
   cache=SummaryCache(record,fail,PROFILES)
   try:
    q=query(params(start='2026-10-09',end='2026-10-09'),PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI));cache.get(q)
    for pool in cache.pools.values():pool.submit(lambda:None).result(1)
    data=cache.get(q)[1];self.assertEqual(data['sources']['Order']['phase'],phase);self.assertEqual(data['sources']['Order']['error'],error)
    self.assertNotIn('private detail',str(data));self.assertEqual(data['profile']['supplement']['status'],'available')
   finally:cache.close()
 def test_late_order_retry_uses_cached_admin_cutoff(self):
  clock=[0];calls=[]
  def order(q):calls.append(q['period']);return record(q,'Order')
  def fail(q):raise OSError('source failed')
  cache=SummaryCache(record,fail,PROFILES,clock=lambda:clock[0]);self.addCleanup(cache.close)
  q=query(params(),PROFILES,datetime(2026,10,10,16,30,tzinfo=SHANGHAI));cache.get(q)
  for pool in cache.pools.values():pool.submit(lambda:None).result(1)
  clock[0]=31;cache.readers['Order']=order;later={**q,'period':{**q['period'],'end':'2026-10-10 16:31'}};cache.get(later)
  cache.pools['Order'].submit(lambda:None).result(1)
  result=cache.get(later)[1];self.assertEqual(calls,[q['period']]);self.assertEqual(result['profile']['primary']['status'],'available')
 def test_refresh_new_cutoff_renews_both_sources(self):
  clock=[0];calls=[]
  def read(q):calls.append(q['period']);return record(q)
  cache=SummaryCache(read,read,PROFILES,clock=lambda:clock[0]);self.addCleanup(cache.close)
  q=query(params(),PROFILES,datetime(2026,10,10,16,30,tzinfo=SHANGHAI));cache.get(q)
  for pool in cache.pools.values():pool.submit(lambda:None).result(1)
  # Order completed later and its independent cache lifetime has not expired yet.
  from live_summary import key_of
  cache.entries[key_of(q)]['Order']['at']=4
  clock[0]=900;later={**q,'period':{**q['period'],'end':'2026-10-10 16:32'}};cache.get(later)
  for pool in cache.pools.values():pool.submit(lambda:None).result(1)
  result=cache.get(later)[1];self.assertEqual(len(calls),4);self.assertEqual(result['profile']['primary']['period'],later['period']);self.assertEqual(result['profile']['supplement']['period'],later['period'])

if __name__=='__main__':unittest.main()

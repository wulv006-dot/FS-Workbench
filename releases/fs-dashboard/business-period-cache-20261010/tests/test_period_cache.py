import sys,unittest
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from live_summary import query,key_of,SummaryCache,SHANGHAI
from test_live_summary import PROFILES,params,record

class PeriodCacheTests(unittest.TestCase):
 def test_today_closed_history_and_custom_ttls(self):
  now=datetime(2026,10,10,16,30,tzinfo=SHANGHAI)
  for start,end,ttl,mode in [('2026-10-10','2026-10-10',900,'today'),('2026-10-09','2026-10-09',7200,'historical'),('2026-10-03','2026-10-09',7200,'historical'),('2026-10-03','2026-10-10',900,'today')]:
   q=query(params(start=start,end=end),PROFILES,now);self.assertEqual(q['cacheSeconds'],ttl);self.assertEqual(q['cachePolicy'],mode)
 def test_midnight_closure_gets_distinct_key_and_complete_cutoff(self):
  before=query(params(),PROFILES,datetime(2026,10,10,23,59,tzinfo=SHANGHAI));after=query(params(),PROFILES,datetime(2026,10,11,0,1,tzinfo=SHANGHAI))
  self.assertNotEqual(key_of(before),key_of(after));self.assertEqual(after['period']['end'],'2026-10-11 00:00');self.assertEqual(after['cacheSeconds'],7200)
 def test_history_hit_and_exact_expiry_refreshes_both(self):
  now=[0];calls=[]
  def read(q):calls.append(q);return record(q)
  cache=SummaryCache(read,read,PROFILES,clock=lambda:now[0]);self.addCleanup(cache.close)
  q=query(params(start='2026-10-09',end='2026-10-09'),PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI));cache.get(q)
  for pool in cache.pools.values():pool.submit(lambda:None).result(1)
  now[0]=7199;cache.get(q);self.assertEqual(len(calls),2)
  now[0]=7200;cache.get(q)
  for pool in cache.pools.values():pool.submit(lambda:None).result(1)
  self.assertEqual(len(calls),4);self.assertEqual(cache.get(q)[1]['refreshSeconds'],7200)
 def test_source_capture_guard_stays_120_seconds(self):
  from live_summary import CAPTURE_MAX_AGE
  self.assertEqual(CAPTURE_MAX_AGE,120)

if __name__=='__main__':unittest.main()

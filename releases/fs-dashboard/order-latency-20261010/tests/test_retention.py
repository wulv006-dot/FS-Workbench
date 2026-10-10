import sys,unittest,copy
from pathlib import Path
from threading import Event
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from live_summary import SummaryCache,query,SHANGHAI,STALE_LIMIT
from test_live_summary import PROFILES,params,record

class RetentionTests(unittest.TestCase):
 def test_ttl_refresh_keeps_bounded_coherent_value_and_authoritative_omission(self):
  clock=[0];gate=Event();started=Event();omit=[False]
  def order(q):
   started.set();gate.wait(2);v=record(q,'Order');v['metrics']={'profitMarginPct':{'value':20,'status':'available'}}
   if omit[0]:v['metrics']={}
   return v
  cache=SummaryCache(record,order,PROFILES,clock=lambda:clock[0]);self.addCleanup(cache.close);self.addCleanup(gate.set)
  q=query(params(),PROFILES,datetime(2026,10,10,16,30,tzinfo=SHANGHAI));gate.set();cache.get(q)
  for pool in cache.pools.values():pool.submit(lambda:None).result(1)
  complete=cache.get(q)[1];old=copy.deepcopy(complete['profile']['primary']['metrics']);self.assertTrue(old)
  gate.clear();started.clear();clock[0]=121;later={**q,'period':{**q['period'],'end':'2026-10-10 16:32'}};cache.get(later);self.assertTrue(started.wait(1));cache.pools['Admin'].submit(lambda:None).result(1)
  pending=cache.get(later)[1];self.assertEqual(pending['profile']['primary']['metrics'],old);self.assertTrue(pending['profile']['primary']['stale']);self.assertTrue(pending['stale']);self.assertEqual(pending['profile']['primary']['period'],pending['profile']['supplement']['period']);self.assertEqual(pending['profile']['period'],q['period'])
  other=query(params(start='2026-10-09',end='2026-10-09'),PROFILES,datetime(2026,10,10,16,32,tzinfo=SHANGHAI));cache.get(other);cache.pools['Admin'].submit(lambda:None).result(1);self.assertEqual(cache.get(other)[1]['profile']['primary']['metrics'],{})
  clock[0]=STALE_LIMIT+1;expired=cache.get(later)[1];self.assertEqual(expired['profile']['primary']['metrics'],{})
  omit[0]=True;gate.set();cache.pools['Order'].submit(lambda:None).result(1);self.assertEqual(cache.get(later)[1]['profile']['primary']['metrics'],{})

if __name__=='__main__':unittest.main()

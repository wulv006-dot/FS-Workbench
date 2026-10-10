import sys, json, unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from threading import Event
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'source'))
from live_summary import SummaryCache, query, key_of, SHANGHAI
from admin_summary import collect

PROFILES = {'MMOEXP': ('MMOEXP','MMOEXP',0,'','mmoexp'), 'FC27': ('FC27','FC27',1322,1327,'sports')}
def params(profile='MMOEXP', start='2026-10-10', end='2026-10-10', grain='day'):
    return {k:[v] for k,v in dict(mode='summary',profile=profile,start=start,end=end,grain=grain).items()}
def q(): return query(params(), PROFILES, datetime(2026,10,10,16,30,tzinfo=SHANGHAI))
def record(query, system='Admin'):
    return {'status':'available','system':system,'period':query['period'],'currency':'USD',
            'capturedAt':datetime.now(timezone.utc).isoformat(),'metrics':{},'dimensions':{}}
def fail(_): raise OSError('do not expose upstream content')

class CacheTests(unittest.TestCase):
    def make(self, admin=record, order=record, fallback=None):
        self.now=0; self.cache=SummaryCache(admin,order,PROFILES,fallback,lambda:self.now)
        self.addCleanup(self.cache.close); return self.cache
    def drain(self):
        for pool in self.cache.pools.values(): pool.submit(lambda:None).result(timeout=3)
    def test_cache_hit_expiry_and_no_snapshot_dependency(self):
        calls=[]
        def read(query): calls.append(query); return record(query)
        cache=self.make(read,read); self.assertEqual(cache.get(q())[0],202); self.drain()
        self.assertEqual(cache.get(q())[1]['stale'],False); self.assertEqual(len(calls),2)
        self.now=119; cache.get(q()); self.assertEqual(len(calls),2)
        self.now=120; cache.get(q()); self.drain(); self.assertEqual(len(calls),4)
    def test_concurrent_identical_queries_merge(self):
        gate=Event(); calls=[]
        def read(query): calls.append(query); gate.wait(3); return record(query)
        cache=self.make(read,read)
        with ThreadPoolExecutor(max_workers=12) as pool:
            replies=list(pool.map(lambda _:cache.get(q())[0],range(24)))
        gate.set(); self.drain(); self.assertTrue(all(s==202 for s in replies));self.assertEqual(len(calls),2)
    def test_order_pending_never_blocks_admin(self):
        gate=Event()
        def order(query): gate.wait(3); return record(query,'Order')
        cache=self.make(record,order); cache.get(q());cache.pools['Admin'].submit(lambda:None).result(2)
        status, result=cache.get(q());gate.set()
        self.assertEqual(status,200);self.assertEqual(result['profile']['primary']['status'],'pending')
        self.assertFalse(result['stale'])
    def test_order_failure_preserves_admin_and_missing_values(self):
        cache=self.make(record,fail);cache.get(q());self.drain();status,value=cache.get(q())
        self.assertEqual(status,200);self.assertEqual(value['profile']['supplement']['status'],'available')
        self.assertIsNone(value['profile']['primary']['orders']);self.assertEqual(value['sources']['Order']['status'],'unavailable')
    def test_admin_failure_no_fake_zero(self):
        cache=self.make(fail,record);cache.get(q());self.drain();status,value=cache.get(q())
        self.assertEqual(status,503);self.assertNotIn('profile',value)
    def test_last_success_marked_stale(self):
        cache=self.make();cache.get(q());self.drain();self.now=120;cache.readers={'Admin':fail,'Order':fail}
        cache.get(q());self.drain();status,value=cache.get(q());self.assertEqual(status,200);self.assertTrue(value['stale'])
        self.assertEqual(value['expiresInSeconds'],0)
    def test_snapshot_fallback_explicitly_stale(self):
        cache=self.make(fail,fail,lambda query:{'supplement':record(query),'primary':record(query)})
        cache.get(q());self.drain();status,value=cache.get(q());self.assertEqual(status,200)
        self.assertEqual(value['origin'],'historical-snapshot');self.assertTrue(value['stale'])
        self.assertTrue(value['sources']['Order']['stale'])
    def test_date_and_profile_keys_do_not_share(self):
        cache=self.make();cache.get(q());self.drain()
        yesterday=query(params(start='2026-10-09',end='2026-10-09'),PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI))
        self.assertEqual(cache.get(yesterday)[0],202)
        fc=query(params(profile='FC27'),PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI))
        self.assertNotEqual(key_of(q()),key_of(fc));self.assertNotEqual(key_of(q()),key_of(yesterday))
        later={**q(),'period':{**q()['period'],'end':'2026-10-10 16:31'}}
        self.assertEqual(key_of(q()),key_of(later))
    def test_denial_clears_fallback(self):
        def denied(_):raise PermissionError('denied')
        cache=self.make(denied,record,lambda query:{'supplement':record(query),'primary':record(query)})
        cache.get(q());self.drain();status,value=cache.get(q());self.assertEqual(status,403);self.assertNotIn('profile',value)
    def test_old_source_capture_rejected(self):
        def old(query):return {**record(query),'capturedAt':(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()}
        cache=self.make(old,record);cache.get(q());self.drain();self.assertEqual(cache.get(q())[0],503)
    def test_actual_watermark_unknown_and_cutoff_distinct(self):
        cache=self.make();cache.get(q());self.drain();value=cache.get(q())[1]
        self.assertIsNone(value['sources']['Admin']['sourceDataAsOf'])
        self.assertEqual(value['sources']['Admin']['asOfStatus'],'upstream_watermark_unknown')
        self.assertNotEqual(value['generatedAt'],value['profile']['period']['end'])
    def test_queue_bound_without_stress(self):
        gate=Event()
        def slow(query):gate.wait(3);return record(query)
        cache=self.make(slow,slow)
        statuses=[]
        for day in range(4,9):
            statuses.append(cache.get(query(params(start=f'2026-10-{day:02}',end=f'2026-10-{day:02}'),PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI)))[0])
        gate.set();self.drain();self.assertEqual(statuses,[202,202,202,202,429])

class ContractTests(unittest.TestCase):
    def test_invalid_filters_and_future(self):
        for bad in ({**params(),'site':['eldorado.gg']},params(profile='UNKNOWN'),params(start='2026-10-11',end='2026-10-11'),params(start='2026-10-10',end='2026-10-09'),{**params(),'profile':['MMOEXP','FC27']}):
            with self.assertRaises(ValueError):query(bad,PROFILES,datetime(2026,10,10,16,tzinfo=SHANGHAI))
    def test_day_hour_boundaries(self):
        now=datetime(2026,10,10,16,30,tzinfo=SHANGHAI)
        yesterday=query(params(start='2026-10-09',end='2026-10-09'),PROFILES,now)
        self.assertEqual(yesterday['period'],{'start':'2026-10-09 00:00','end':'2026-10-10 00:00'})
        self.assertEqual(query(params(start='2026-10-10 15:00',end='2026-10-10 16:00',grain='hour'),PROFILES,now)['period']['end'],'2026-10-10 16:30')
    def test_admin_aggregate_only_contract(self):
        calls=[]
        def request(path,**kwargs):
            calls.append((path,kwargs));return 200,json.dumps({'code':1,'data':{'total':2,'amount':'100','site_rank':{'www.mmoexp.com':{'num':2,'amount':'100'}},'customer_phone':'DO_NOT_KEEP','orders_raw':[{'email':'DO_NOT_KEEP'}]}})
        result=collect(request,'1327','2026-10-09 00:00','2026-10-10 00:00')
        self.assertEqual(result['metrics']['orders']['value'],2);self.assertNotIn('DO_NOT_KEEP',json.dumps(result))
        self.assertEqual(calls[0][1]['data']['game'],'1327');self.assertEqual(calls[0][1]['data']['site'],'')
        self.assertIsNone(result['sourceDataAsOf'])
    def test_admin_denial_is_not_a_zero_result(self):
        with self.assertRaises(PermissionError):collect(lambda *a,**kw:(403,'{}'),'','2026-10-09 00:00','2026-10-10 00:00')

if __name__=='__main__':unittest.main()

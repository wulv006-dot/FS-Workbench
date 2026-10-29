import json, sys, tempfile, types, unittest
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'candidate'),str(ROOT/'tests/helpers')]
if sys.platform=='win32':
    flock=types.ModuleType('fcntl');flock.LOCK_EX=2;flock.LOCK_NB=4;flock.flock=lambda *a:None;sys.modules['fcntl']=flock
from profit_queries import ProfitQueries

class Pool:
    def __init__(self):self.work=[]
    def submit(self,fn,*args):self.work.append((fn,args))
    def run(self):
        fn,args=self.work.pop(0);fn(*args)

class Profit(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.pool=Pool();self.calls=[]
        self.today=datetime.now(timezone(timedelta(hours=8))).date();self.clock=[100]
        if sys.platform=='win32':
            # POSIX dir_fd/flock is exercised by Linux ApplyTests; keep Windows batching synthetic.
            from contextlib import nullcontext
            guard=patch('profit_queries.cache_guard',side_effect=lambda path:nullcontext())
            guard.start();self.addCleanup(guard.stop)
        self.api=ProfitQueries({'RS':('RS','RS',506,506,'general')},self.read,self.pool,self.root,self.root/'days',clock=lambda:self.clock[0])
        self.q={'profile':'RS','start':str(self.today-timedelta(days=7)),'end':str(self.today),'grain':'day'}
    def tearDown(self):self.tmp.cleanup()
    def read(self,container,reader,requests,timeout):
        self.calls.append(requests)
        return {r['key']:{'system':'order.p2pah.cn','endpoint':'/stats/admin_order/index.html','normalisedScope':'all-websites',
          'timezone':'Asia/Shanghai','currency':'USD','status':'available','period':{'start':r['start'],'end':r['end']},
          'filters':{'gid':str(r['gid']),'tid':'','status':r['status'],'start_paytime':r['start'],'end_paytime':r['end']},
          'capturedAt':datetime.now(timezone.utc).isoformat(),'labelsVerified':True,'orders':2,'revenueUsd':10,
          'metrics':{'profitMarginPct':{'value':-15,'unit':'percent','field':'利润率','source':'primary','status':'available'}}} for r in requests}
    def test_batches_yield_and_today_is_excluded_and_fresh_cache_reused(self):
        status,first=self.api.get(self.q,'catalog-test',self.today)
        self.assertEqual(status,200);self.assertEqual(first['status'],'pending');self.assertEqual(first['requestedDays'],7)
        self.pool.run();self.assertEqual(len(self.calls[0]),4);self.assertEqual(len(self.pool.work),1)
        _,partial=self.api.get(self.q,'catalog-test',self.today);self.assertEqual(partial['cachedDays'],4)
        self.pool.run();_,done=self.api.get(self.q,'catalog-test',self.today)
        self.assertEqual(done['status'],'available');self.assertEqual(done['cachedDays'],7)
        self.assertTrue(all(r['profitMarginPct']==-15 and r['date']<str(self.today) and r['profitUsd'] is None for r in done['history']['daily']))
        self.api.get(self.q,'catalog-test',self.today);self.assertEqual(len(self.calls),2)
    def test_failure_preserves_missing_without_inventing_values_or_auto_retry(self):
        self.api.call=lambda *a:(_ for _ in ()).throw(OSError('failure'))
        self.api.get(self.q,'catalog-test',self.today);self.pool.run();_,failed=self.api.get(self.q,'catalog-test',self.today)
        self.assertEqual(failed['status'],'partial');self.assertEqual(failed['history']['daily'],[])
        self.assertEqual(len(self.pool.work),0);self.assertEqual(failed['lastError'],'source_read_failed')
    def test_wrong_period_and_scope_are_not_cached(self):
        original=self.read
        def wrong(*args):
            values=original(*args)
            for v in values.values():v['filters']['gid']='999'
            return values
        self.api.call=wrong;self.api.get(self.q,'catalog-test',self.today);self.pool.run()
        self.assertEqual(list((self.root/'days').glob('*.json')),[])
    def test_real_posix_shared_lock_contention_fails_without_source_read(self):
        if sys.platform=='win32':
            with patch('profit_queries.fcntl.flock',side_effect=BlockingIOError()):
                self.api.get(self.q,'catalog-test',self.today);self.pool.run()
        else:
            import fcntl
            with (self.root/'collector.lock').open('a+b') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.api.get(self.q,'catalog-test',self.today);self.pool.run()
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()

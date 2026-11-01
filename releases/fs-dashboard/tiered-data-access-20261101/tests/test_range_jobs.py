from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event,RLock
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import test_query_planner as fixtures
from query_planner import plan
from range_jobs import Engine
from date_policy import PolicyError


class Jobs(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.Planner();fixture.setUp()
        fixture.dataset['source_max_slice']=dict(unit='calendar_months',value=3)
        self.plan=plan(fixture.req,fixture.cap,fixture.dataset,fixture.budgets)
        self.grants={user:dict(scope_hash='trusted-scope',permission_epoch='1',policy_version='fixture') for user in ('a','b')}
        self.now=0
        self.jobs,self.subs,self.cache={},{},{}
        self.engine=Engine(jobs=self.jobs,subscriptions=self.subs,cache=self.cache,authorize=lambda u,q:deepcopy(self.grants.get(u)),secret=b'x'*32,lock=RLock(),clock=lambda:self.now)

    def submit(self,user='a',**kw):return self.engine.submit(user,self.plan,watermark='fixed-fixture',source_contract='fixture-source-v1',**kw)
    def key(self,handle):return self.subs[handle]['key']
    def reply(self,rows=None,**kw):return dict(rows=rows if rows is not None else [dict(order_id='o1',amount='1')],watermark='fixed-fixture',complete=True,next_cursor=None,confirmed_empty=rows==[],**kw)

    def test_ten_subscribers_singleflight_one_exact_scoped_chain(self):
        with ThreadPoolExecutor(max_workers=10) as pool:handles=list(pool.map(lambda _:self.submit(),range(10)))
        self.assertEqual(len(self.jobs),1);requests=[]
        def adapter(request):requests.append(request);return self.reply()
        for handle in handles:self.engine.step(self.key(handle),adapter)
        self.assertEqual(len(requests),1)
        self.assertEqual((requests[0]['start'],requests[0]['end_exclusive'],requests[0]['site_id'],requests[0]['game_id']),('2026-08-01','2026-11-01','266','1327'))
        self.assertTrue(self.engine.status('a',handles[-1])['complete'])

    def test_one_subscription_cancel_does_not_cancel_another(self):
        a=self.submit('a');b=self.submit('b');self.engine.cancel('a',a)
        self.engine.step(self.key(b),lambda r:self.reply())
        self.assertEqual(self.engine.status('a',a)['status'],'cancelled')
        self.assertTrue(self.engine.status('b',b)['complete'])

    def test_cancel_during_io_discards_late_result_and_cache(self):
        handle=self.submit();entered,release=Event(),Event()
        def adapter(request):entered.set();self.assertTrue(release.wait(5));return self.reply()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.engine.step,self.key(handle),adapter)
            self.assertTrue(entered.wait(5));self.engine.cancel('a',handle);release.set();future.result()
        self.assertEqual(self.jobs[self.key(handle)]['rows'],[]);self.assertFalse(self.cache)
        self.assertEqual(self.engine.status('a',handle)['status'],'cancelled')

    def test_permission_rechecked_on_status_cache_page_and_during_io(self):
        handle=self.submit()
        def adapter(request):self.grants['a']['permission_epoch']='2';return self.reply()
        self.engine.step(self.key(handle),adapter)
        self.assertFalse(self.cache);self.assertEqual(self.jobs[self.key(handle)]['status'],'cancelled')
        with self.assertRaises(PolicyError):self.engine.status('a',handle)
        self.grants['a']['permission_epoch']='1';handle=self.submit();self.engine.step(self.key(handle),lambda r:self.reply())
        self.assertTrue(self.cache)
        self.grants.pop('a')
        with self.assertRaises(PolicyError):self.submit()
        with self.assertRaises(PolicyError):self.engine.page('a',handle)

    def test_signed_cursor_is_bound_to_subscriber_and_current_permission(self):
        handle=self.submit();self.engine.step(self.key(handle),lambda r:self.reply([dict(order_id=str(i),amount='1') for i in range(3)]))
        page=self.engine.page('a',handle,limit=1);cursor=page['next_cursor']
        self.assertEqual(self.engine.page('a',handle,cursor=cursor,limit=1)['data'][0]['order_id'],'1')
        other=self.submit('b')
        with self.assertRaises(PolicyError):self.engine.page('b',other,cursor=cursor)
        with self.assertRaises(PolicyError):self.engine.page('a',handle,cursor=cursor+'x')
        self.grants['a']['policy_version']='changed'
        with self.assertRaisesRegex(PolicyError,'policy_changed'):self.engine.page('a',handle,cursor=cursor)

    def test_budget_exhaustion_is_partial_and_not_downloadable(self):
        self.plan['budget']['max_rows']=1
        handle=self.submit();self.engine.step(self.key(handle),lambda r:self.reply([dict(order_id=str(i),amount='1') for i in range(2)]))
        value=self.engine.status('a',handle)
        self.assertEqual(value['status'],'partial');self.assertFalse(value['complete']);self.assertFalse(self.cache)
        with self.assertRaisesRegex(PolicyError,'result_not_complete'):self.engine.page('a',handle)

    def test_source_failure_is_not_negative_cache_and_empty_requires_complete(self):
        handle=self.submit()
        class Limited(Exception):code='source_rate_limited'
        def adapter(request):raise Limited()
        self.engine.step(self.key(handle),adapter)
        self.assertEqual(self.engine.status('a',handle)['error'],'source_rate_limited');self.assertFalse(self.cache)
        handle=self.submit();self.engine.step(self.key(handle),lambda r:self.reply([]))
        self.assertTrue(self.engine.status('a',handle)['complete']);self.assertEqual(self.engine.page('a',handle)['data'],[])
        self.assertEqual(self.cache[self.key(handle)]['expires'],30)

    def test_unstable_watermark_schema_and_cursor_fail_without_partial_success(self):
        for page in [dict(self.reply(),watermark='changed'),dict(self.reply(),rows=[dict(order_id='o',email='forbidden')]),dict(self.reply(),complete=False,next_cursor=None)]:
            handle=self.submit();self.engine.step(self.key(handle),lambda r:page)
            self.assertEqual(self.engine.status('a',handle)['status'],'failed');self.assertFalse(self.cache)

    def test_cache_expiry_refetches_only_same_range_and_different_grant_isolated(self):
        handle=self.submit(ttl=1);self.engine.step(self.key(handle),lambda r:self.reply())
        self.now=2;next_handle=self.submit();requests=[]
        self.engine.step(self.key(next_handle),lambda r:requests.append(r) or self.reply())
        self.assertEqual(len(requests),1);self.assertEqual(requests[0]['start'],'2026-08-01')
        self.grants['b']['scope_hash']='other-trusted-scope'
        other=self.submit('b');self.assertNotEqual(self.key(other),self.key(next_handle))

if __name__=='__main__':unittest.main()

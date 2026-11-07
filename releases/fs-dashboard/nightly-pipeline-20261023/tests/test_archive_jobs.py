import io,json,os,sys,tempfile,time,unittest
from contextlib import ExitStack
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.error import HTTPError,URLError
from http.client import IncompleteRead
PACKAGE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PACKAGE/'source'),str(PACKAGE.parent/'dashboard-refresh-20261025/source'),str(PACKAGE.parent/'dashboard-refresh-20261025/tests/fixtures')]
import archive_jobs as jobs
from daily_archive import encoded

class Clock:
    at=datetime(2026,10,28,14,tzinfo=jobs.TZ)
    fromisoformat=datetime.fromisoformat
    @classmethod
    def now(cls,tz):return cls.at.astimezone(tz)

class Jobs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        Clock.at=datetime(2026,10,28,14,tzinfo=jobs.TZ)
        self.marketing=dict(profile='marketing',start='2026-10-26',end='2026-10-26')
        self.business=dict(mode='summary',profile='FC27',start='2026-10-26',end='2026-10-26')
        self.other=dict(self.business,profile='AION2')
        self.store=Mock();self.store.get.return_value=None
        self.work=[self.marketing,self.business,self.other]
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in [('ROOT',self.root),('datetime',Clock),('Archive',lambda:self.store),('profiles',lambda:{'FC27':('FC27','FC27',1322,1327,'sports'),'AION2':('AION2','Aion2',826,891,'rpg')}),('candidates',lambda *a:iter(self.work)),('atomic',lambda p,v:p.write_bytes(encoded(v)))]:
            self.stack.enter_context(patch.object(jobs,name,value))
        self.stack.enter_context(patch.object(jobs,'complete_summary',side_effect=lambda v:v.get('fixture_complete') is True))
        self.stack.enter_context(patch.object(jobs,'complete_native',side_effect=lambda v:v.get('fixture_complete') is True))
    def key(self,args,daily=True):return jobs.hashlib.sha256(encoded(dict(cadence='daily' if daily else 'history',query=args))).hexdigest()
    def state(self):
        p=self.root/'scheduler-state.json';return json.loads(p.read_text()) if p.exists() else {}
    def seed(self,args,**values):
        s=self.state();s[self.key(args)]=dict(query=args,**values);(self.root/'scheduler-state.json').write_bytes(encoded(s))
    def test_pending_is_one_observation_and_does_not_wait_or_block_other_profile(self):
        for q in self.work:self.seed(q,status='pending',failures=0,retryAfter=0)
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read,patch.object(jobs.time,'sleep') as sleep:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,3);sleep.assert_not_called()
        self.assertEqual(result['missingCount'],3)
        self.assertTrue(all(v['status']=='pending' and v['failures']==0 for v in self.state().values()))
    def test_fast_source_admissions_use_original_budget_instead_of_a_four_job_burst(self):
        self.work=[dict(self.business,start=f'2026-10-{day:02}',end=f'2026-10-{day:02}') for day in range(1,13)]
        clock=[0.0];starts=[];rejected=[];sleeps=[]
        def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
        def read(*args,**kwargs):
            if sum(t+2>clock[0] for t in starts)>=4:rejected.append(clock[0]);return 429,dict(status='busy')
            starts.append(clock[0]);return 202,dict(status='pending')
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs.time,'sleep',side_effect=sleep),patch.object(jobs,'read_route',side_effect=read):
            jobs.run_once(True,65)
        self.assertEqual(starts,[0,10,20,30,40,50,60]);self.assertEqual(rejected,[])
        self.assertEqual(sum(sleeps),60);self.assertLessEqual(clock[0],65)
        self.assertTrue(all(sum(at<=other<at+60 for other in starts)<=6 for at in starts))
    def test_slow_source_keeps_four_slot_bound_and_stops_after_first_429(self):
        self.work=[dict(self.business,start=f'2026-10-{day:02}',end=f'2026-10-{day:02}') for day in range(1,13)]
        clock=[0.0];starts=[];rejected=[]
        def read(*args,**kwargs):
            if sum(t+90>clock[0] for t in starts)>=4:rejected.append(clock[0]);return 429,dict(status='busy')
            starts.append(clock[0]);return 202,dict(status='pending')
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)),patch.object(jobs,'read_route',side_effect=read) as requests:
            jobs.run_once(True,120)
        self.assertEqual(starts,[0,10,20,30]);self.assertEqual(rejected,[40]);self.assertEqual(requests.call_count,5)
        self.assertEqual(clock[0],40)
    def test_native_and_summary_share_pacing_without_delaying_or_repeating_catalog(self):
        native=dict(self.business);native.pop('mode');native['archiveFamily']='native';self.work=[native,self.other]
        clock=[0.0];seen=[]
        def read(params,port=8931,**unused):
            seen.append((params.get('mode'),port,clock[0]));return (200,dict(catalogId='original_catalog')) if params.get('mode')=='catalog' else (202,dict(status='pending'))
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)),patch.object(jobs,'read_route',side_effect=read):
            jobs.run_once(True,20)
        self.assertEqual(seen,[('catalog',8931,0),(None,8931,0),('summary',8931,10)])
    def test_existing_pending_and_marketing_are_not_delayed_by_new_admission_pacing(self):
        later=dict(self.business,start='2026-10-25',end='2026-10-25');self.work=[self.business,self.other,self.marketing,later]
        for q in self.work:self.seed(q,status='busy',retryAfter=0)
        self.seed(self.other,status='pending',retryAfter=0,attemptStartedAt='2026-10-01T00:00:00+00:00')
        clock=[0.0];seen=[]
        def read(params,port,**unused):
            seen.append((params.get('profile'),port,clock[0]));return (200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat())) if port==8935 else (202,dict(status='pending'))
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)),patch.object(jobs,'read_route',side_effect=read):
            jobs.run_once(True,20)
        self.assertEqual(seen,[('FC27',8931,0),('AION2',8931,0),(None,8935,0),('FC27',8931,10)])
        self.assertEqual(self.state()[self.key(self.other)]['attemptStartedAt'],'2026-10-01T00:00:00+00:00')
    def test_insufficient_pacing_budget_keeps_unvisited_key_and_other_port_work(self):
        self.work=[self.business,self.other,self.marketing];self.seed(self.other,status='busy',failures=0,retryAfter=0,rangeId='original_range')
        original=self.state()[self.key(self.other)];clock=[0.0]
        def read(params,port,**unused):return (200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat())) if port==8935 else (202,dict(status='pending'))
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs.time,'sleep') as sleep,patch.object(jobs,'read_route',side_effect=read) as requests:
            result=jobs.run_once(True,5)
        sleep.assert_not_called();self.assertEqual(requests.call_count,2);self.assertEqual(result['completed'],1)
        self.assertEqual(self.state()[self.key(self.other)],original)
    def test_sleep_overshoot_does_not_start_another_source_after_budget(self):
        self.work=[self.business,self.other];clock=[0.0]
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds+1)),patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as requests:
            jobs.run_once(True,10.5)
        self.assertEqual(requests.call_count,1);self.assertNotIn(self.key(self.other),self.state())
    def test_permission_failure_stops_only_its_item_not_same_port(self):
        self.work=[self.business,self.other]
        with patch.object(jobs,'read_route',side_effect=[(403,dict(error='source_permission_denied')),(200,dict(fixture_complete=True))]) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,2);self.assertEqual(result['completed'],1)
        failure=self.state()[self.key(self.business)]
        self.assertEqual((failure['status'],failure['reason'],failure['retryable']),('failed','permission_denied',False))
        with patch.object(jobs,'read_route') as read:jobs.run_once(True,5)
        read.assert_not_called()
    def test_incomplete_http_body_retries_only_its_query_and_continues_next(self):
        class Response:
            status=200
            def __init__(self,incomplete):self.incomplete=incomplete
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):
                if self.incomplete:raise IncompleteRead(b'{"status":',10)
                return b'{"fixture_complete":true}'
        self.work=[self.business,self.other]
        opener=Mock();opener.open.side_effect=[Response(True),Response(False)]
        with patch.object(jobs,'build_opener',return_value=opener):result=jobs.run_once(True,5)
        self.assertEqual(opener.open.call_count,2);self.assertEqual(result['completed'],1)
        failure=self.state()[self.key(self.business)]
        self.assertEqual((failure['status'],failure['httpStatus'],failure['retryable']),('unavailable',503,True))
        self.assertEqual(failure['failures'],1);self.assertEqual(failure['reason'],'local_route_temporarily_unavailable')
        self.assertGreater(failure['retryAfter'],jobs.time.time())
        self.assertEqual(self.state()[self.key(self.other)]['status'],'complete')
    def test_argument_422_does_not_abort_next_family(self):
        self.work=[self.business,self.marketing]
        with patch.object(jobs,'read_route',side_effect=[(422,dict(error='invalid_parameters')),(200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat()))]):
            result=jobs.run_once(True,5)
        self.assertEqual(result['completed'],1);self.assertEqual(result['terminalCount'],1)
        self.assertEqual(self.state()[self.key(self.business)]['httpStatus'],422)
    def test_catalog_failure_does_not_abort_summary_or_marketing(self):
        native=dict(self.business);native.pop('mode');native['archiveFamily']='native';self.work=[native,self.business,self.marketing]
        with patch.object(jobs,'read_route',side_effect=[(502,dict(status='unavailable')),(200,dict(fixture_complete=True)),(200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat()))]) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(result['completed'],2);self.assertEqual(read.call_count,3)
        self.assertEqual(self.state()[self.key(native)]['status'],'unavailable')
    def test_502_preserves_original_request_and_original_backoff(self):
        self.work=[self.business];self.seed(self.business,status='unavailable',failures=2,retryAfter=0,requestedAt='2026-10-01T00:00:00+00:00')
        with patch.object(jobs,'read_route',return_value=(502,dict(status='unavailable'))):jobs.run_once(True,5)
        value=self.state()[self.key(self.business)]
        self.assertEqual(value['requestedAt'],'2026-10-01T00:00:00+00:00');self.assertEqual(value['failures'],3)
        self.assertTrue(value['retryable']);self.assertAlmostEqual(value['retryAfter']-jobs.time.time(),1200,delta=2)
    def test_busy_preserves_failure_history_and_retries_next_five_minute_tick(self):
        self.work=[self.business];self.seed(self.business,status='busy',failures=100,retryAfter=0)
        with patch.object(jobs,'read_route',return_value=(429,dict(status='busy'))):result=jobs.run_once(True,5)
        value=self.state()[self.key(self.business)]
        self.assertEqual(value['failures'],100);self.assertTrue(value['retryable']);self.assertEqual(result['repeatedFailureCount'],1)
        self.assertAlmostEqual(value['retryAfter']-jobs.time.time(),300,delta=2)
    def test_429_yields_its_port_without_touching_later_keys_or_blocking_other_port(self):
        self.work=[self.business,self.other,self.marketing]
        self.seed(self.other,status='pending',failures=2,retryAfter=0,rangeId='original_range_id',requestedAt='2026-10-01T00:00:00+00:00')
        original=self.state()[self.key(self.other)]
        def reply(params,port,**unused):return (429,dict(status='busy')) if port==8931 else (200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat()))
        with patch.object(jobs,'read_route',side_effect=reply) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,2);self.assertEqual([row.args[1] for row in read.call_args_list],[8931,8935])
        self.assertEqual(self.state()[self.key(self.other)],original);self.assertEqual(result['completed'],1)
    def test_pending_complete_archive_reconciles_after_same_port_429_without_http(self):
        native=dict(self.other);native.pop('mode');native['archiveFamily']='native';self.work=[self.business,native]
        self.seed(self.business,status='busy',retryAfter=0,lastObservedAt='2026-10-27T00:00:00+00:00')
        original='2026-10-28T01:00:01+00:00'
        self.seed(native,status='pending',failures=7,retryAfter=0,lastObservedAt=original,
                  requestedAt=original,attemptStartedAt=original,rangeId='original_pending_range')
        self.store.get.side_effect=lambda family,q:dict(fixture_complete=True) if q['profile']=='AION2' else None
        with patch.object(jobs,'read_route',return_value=(429,dict(status='busy'))) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertEqual((result['reused'],result['missingCount']),(1,1))
        value=self.state()[self.key(native)]
        self.assertEqual((value['status'],value['reason'],value['failures']),('complete','existing_complete_archive',0))
        self.assertEqual((value['requestedAt'],value['attemptStartedAt'],value['rangeId']),(original,original,'original_pending_range'))
    def test_pending_cache_miss_after_429_preserves_original_state_without_http(self):
        self.work=[self.business,self.other]
        self.seed(self.other,status='pending',failures=7,retryAfter=0,rangeId='original_pending_range')
        original=self.state()[self.key(self.other)]
        with patch.object(jobs,'read_route',return_value=(429,dict(status='busy'))) as read:
            jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertEqual(self.store.get.call_count,2)
        self.assertEqual(self.state()[self.key(self.other)],original)
    def test_nonpending_keys_stay_untouched_after_429_even_if_archive_exists(self):
        self.work=[self.business,self.other]
        self.seed(self.other,status='busy',failures=12,retryAfter=0,rangeId='original_busy_range')
        original=self.state()[self.key(self.other)]
        self.store.get.side_effect=lambda family,q:dict(fixture_complete=True) if q['profile']=='AION2' else None
        with patch.object(jobs,'read_route',return_value=(429,dict(status='busy'))) as read:
            jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertEqual(self.store.get.call_count,1)
        self.assertEqual(self.state()[self.key(self.other)],original)
    def test_marketing_429_does_not_block_business_or_mark_unobserved_keys(self):
        later=dict(self.marketing,start='2026-10-25',end='2026-10-25');self.work=[self.marketing,later,self.business]
        with patch.object(jobs,'read_route',side_effect=[(429,dict(status='busy')),(200,dict(fixture_complete=True))]) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,2);self.assertEqual([row.args[1] for row in read.call_args_list],[8935,8931])
        self.assertNotIn(self.key(later),self.state());self.assertEqual(result['unobservedCount'],1)
    def test_catalog_429_also_yields_business_port_without_requesting_native_data(self):
        native=dict(self.business);native.pop('mode');native['archiveFamily']='native'
        self.work=[native,self.other,self.marketing]
        with patch.object(jobs,'read_route',side_effect=[(429,dict(status='busy')),(200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat()))]) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,2);self.assertEqual(read.call_args_list[0].args[0],{'mode':'catalog'})
        self.assertEqual(read.call_args_list[1].args[1],8935);self.assertEqual(result['completed'],1)
        self.assertNotIn(self.key(self.other),self.state())
    def test_950_old_busy_keys_make_one_rejected_request_and_resume_on_next_tick(self):
        stamp=Clock.now(jobs.timezone.utc).timestamp()
        self.work=[dict(self.business,start=(Clock.at.date()-timedelta(days=i+1)).isoformat(),end=(Clock.at.date()-timedelta(days=i+1)).isoformat()) for i in range(950)]
        original={self.key(q):dict(query=q,status='busy',retryable=True,failures=12,retryAfter=stamp+14400,
                    requestedAt='2026-10-01T00:00:00+00:00',rangeId='original_'+str(i),
                    lastObservedAt=(Clock.now(jobs.timezone.utc)-timedelta(minutes=10)).isoformat()) for i,q in enumerate(self.work)}
        (self.root/'scheduler-state.json').write_bytes(encoded(original))
        with patch.object(jobs.time,'time',return_value=stamp),patch.object(jobs,'read_route',return_value=(429,dict(status='busy'))) as read:
            jobs.run_once(True,5)
        self.assertEqual(read.call_count,1)
        current=self.state();self.assertEqual(len(current),950)
        self.assertTrue(all(current[self.key(q)]==original[self.key(q)] for q in self.work[1:]))
        with patch.object(jobs.time,'time',return_value=stamp+300),patch.object(jobs,'read_route',side_effect=[(200,dict(fixture_complete=True)),(429,dict(status='busy'))]) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,2);self.assertEqual(result['completed'],1)
        self.assertEqual(read.call_args_list[0].args[0]['start'],self.work[1]['start'])
    def test_old_four_hour_busy_wait_recovers_without_clearing_original_metadata(self):
        self.work=[self.business];stamp=Clock.now(jobs.timezone.utc).timestamp()
        original='2026-10-01T00:00:00+00:00'
        self.seed(self.business,status='busy',failures=7,retryAfter=stamp+14400,
                  lastObservedAt=(Clock.now(jobs.timezone.utc)-timedelta(minutes=10)).isoformat(),
                  requestedAt=original,attemptStartedAt=original,rangeId='original_range_id')
        with patch.object(jobs.time,'time',return_value=stamp),patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:
            jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertEqual(list(self.state()),[self.key(self.business)])
        value=self.state()[self.key(self.business)]
        self.assertEqual((value['requestedAt'],value['attemptStartedAt'],value['rangeId']),(original,original,'original_range_id'))
        self.assertEqual(value['failures'],7);self.assertEqual(value['status'],'pending')
    def test_new_busy_observation_waits_five_minutes_without_counting_source_failure(self):
        self.work=[self.business];stamp=Clock.now(jobs.timezone.utc).timestamp()
        with patch.object(jobs.time,'time',return_value=stamp),patch.object(jobs,'read_route',return_value=(429,dict(status='busy',retryAfter=10))):
            jobs.run_once(True,5)
        self.assertEqual(self.state()[self.key(self.business)]['failures'],0)
        with patch.object(jobs.time,'time',return_value=stamp+299),patch.object(jobs,'read_route') as read:
            jobs.run_once(True,5)
        read.assert_not_called()
        with patch.object(jobs.time,'time',return_value=stamp+300),patch.object(jobs,'read_route',return_value=(200,dict(fixture_complete=True))) as read:
            result=jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertEqual(result['completed'],1)
    def test_source_failure_still_honors_its_original_four_hour_wait(self):
        self.work=[self.business];stamp=Clock.now(jobs.timezone.utc).timestamp()
        self.seed(self.business,status='unavailable',failures=7,retryAfter=stamp+14400,
                  lastObservedAt=(Clock.now(jobs.timezone.utc)-timedelta(minutes=10)).isoformat())
        with patch.object(jobs.time,'time',return_value=stamp),patch.object(jobs,'read_route') as read:
            jobs.run_once(True,5)
        read.assert_not_called();self.assertEqual(self.state()[self.key(self.business)]['retryAfter'],stamp+14400)
    def test_pending_continuation_preserves_attempt_time(self):
        self.work=[self.business];self.seed(self.business,status='pending',failures=0,retryAfter=0,attemptStartedAt='2026-10-01T00:00:00+00:00')
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))):jobs.run_once(True,5)
        self.assertEqual(self.state()[self.key(self.business)]['attemptStartedAt'],'2026-10-01T00:00:00+00:00')
    def test_pending_does_not_inherit_terminal_flags_from_prior_complete(self):
        self.work=[self.marketing];self.seed(self.marketing,status='complete',retryable=False,reason='existing_complete_archive',retryAfter=0,at='2026-10-27T01:00:00+08:00')
        observed=[]
        def read(*args,**kwargs):
            observed.append(self.state()[self.key(self.marketing)]);return 202,dict(status='pending')
        with patch.object(jobs,'read_route',side_effect=read):result=jobs.run_once(True,5)
        self.assertEqual(observed[0]['reason'],'source_pending');self.assertTrue(observed[0]['retryable']);self.assertEqual(observed[0]['retryAfter'],0)
        self.assertEqual(result['terminalCount'],0)
    def test_complete_existing_archive_marks_original_pending_complete_without_source(self):
        self.work=[self.business];self.seed(self.business,status='pending',failures=3,retryAfter=jobs.time.time()+500)
        self.store.get.return_value=dict(fixture_complete=True)
        with patch.object(jobs,'read_route') as read:result=jobs.run_once(True,5)
        read.assert_not_called();value=self.state()[self.key(self.business)]
        self.assertEqual(value['status'],'complete');self.assertEqual(value['reason'],'existing_complete_archive');self.assertEqual(value['failures'],0)
        self.assertEqual(result['reused'],1)
    def test_incomplete_existing_archive_is_not_marked_complete(self):
        self.work=[self.business];self.store.get.return_value=dict(fixture_complete=False)
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertEqual(self.state()[self.key(self.business)]['status'],'pending')
    def test_complete_archive_can_resolve_terminal_failure_without_retrying_source(self):
        self.work=[self.business];self.seed(self.business,status='failed',retryable=False,failures=1)
        self.store.get.return_value=dict(fixture_complete=True)
        with patch.object(jobs,'read_route') as read:jobs.run_once(True,5)
        read.assert_not_called();self.assertEqual(self.state()[self.key(self.business)]['status'],'complete')
    def test_one_daily_marketing_refresh_then_timeout_continues_without_new_refresh(self):
        self.work=[self.marketing]
        with patch.object(jobs,'read_route',return_value=(503,dict(status='unavailable'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_args.args[0]['refresh'],'true')
        original=self.state()[self.key(self.marketing)];original['retryAfter']=0
        (self.root/'scheduler-state.json').write_bytes(encoded({self.key(self.marketing):original}));Clock.at+=timedelta(minutes=5)
        with patch.object(jobs,'read_route',return_value=(200,dict(status='available',generatedAt=original['attemptStartedAt']))) as read:jobs.run_once(True,5)
        self.assertNotIn('refresh',read.call_args.args[0]);self.assertEqual(self.state()[self.key(self.marketing)]['status'],'complete')
    def test_next_daily_correction_refreshes_once_after_prior_day_completed(self):
        self.work=[self.marketing];self.seed(self.marketing,status='complete',at='2026-10-27T01:00:00+08:00',correctionDay='2026-10-27')
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_args.args[0]['refresh'],'true')
        s=self.state();s[self.key(self.marketing)]['retryAfter']=0;(self.root/'scheduler-state.json').write_bytes(encoded(s))
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertNotIn('refresh',read.call_args.args[0])
    def test_explicit_refresh_deferred_retries_unsent_start_once_then_polls(self):
        self.work=[self.marketing]
        with patch.object(jobs,'read_route',return_value=(200,dict(status='available',generatedAt=Clock.now(jobs.timezone.utc).isoformat(),archive=dict(refreshDeferred=True)))):jobs.run_once(True,5)
        s=self.state();key=self.key(self.marketing);self.assertTrue(s[key]['refreshPending']);self.assertEqual(s[key]['status'],'busy')
        s[key]['retryAfter']=0;(self.root/'scheduler-state.json').write_bytes(encoded(s))
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_args.args[0]['refresh'],'true');s=self.state();self.assertFalse(s[key]['refreshPending'])
        s[key]['retryAfter']=0;(self.root/'scheduler-state.json').write_bytes(encoded(s))
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertNotIn('refresh',read.call_args.args[0])
    def test_invalid_arguments_stop_only_that_query_and_do_not_increment_forever(self):
        invalid=dict(self.business,start='not-a-date');self.work=[invalid,self.other]
        with patch.object(jobs,'read_route',return_value=(200,dict(fixture_complete=True))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_count,1);self.assertFalse(self.state()[self.key(invalid)]['retryable'])
        with patch.object(jobs,'read_route') as read:jobs.run_once(True,5)
        read.assert_not_called();self.assertEqual(self.state()[self.key(invalid)]['failures'],1)
    def test_never_attempted_query_precedes_seen_marketing(self):
        self.work=[self.marketing,self.business];self.seed(self.marketing,status='unavailable',at='2026-10-01T00:00:00+00:00',retryAfter=0)
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_args_list[0].args[0]['profile'],'FC27')
    def test_oldest_observation_runs_first(self):
        self.work=[self.business,self.other]
        self.seed(self.business,status='unavailable',failures=0,lastObservedAt='2026-10-28T05:00:00+00:00',retryAfter=0)
        self.seed(self.other,status='unavailable',failures=0,lastObservedAt='2026-10-28T03:00:00+00:00',retryAfter=0)
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_args_list[0].args[0]['profile'],'AION2')
    def test_due_missing_item_precedes_old_complete_archive_scan(self):
        self.work=[self.business,self.other]
        self.seed(self.business,status='complete',at='2026-09-01T00:00:00+00:00')
        self.seed(self.other,status='unavailable',at='2026-10-28T00:00:00+00:00',retryAfter=0)
        with patch.object(jobs,'read_route',return_value=(202,dict(status='pending'))) as read:jobs.run_once(True,5)
        self.assertEqual(read.call_args_list[0].args[0]['profile'],'AION2')
    def test_fair_rotation_after_budget_cut_does_not_restart_first_query(self):
        self.work=[self.marketing,self.business];clock=[0]
        def read(*args,**kwargs):clock[0]+=kwargs['timeout'];return 202,dict(status='pending')
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs,'read_route',side_effect=read):jobs.run_once(True,1)
        self.assertEqual(list(self.state()),[self.key(self.marketing)])
        clock[0]=0
        with patch.object(jobs.time,'monotonic',side_effect=lambda:clock[0]),patch.object(jobs,'read_route',side_effect=read) as observe:jobs.run_once(True,1)
        self.assertEqual(observe.call_args_list[0].args[0]['profile'],'FC27')
    def test_history_runs_after_seven_without_force(self):
        self.work=[self.business]
        with patch.dict(jobs.os.environ,{},clear=True),patch.object(jobs,'read_route',return_value=(200,dict(fixture_complete=True))) as read:
            self.assertEqual(jobs.run_once(False,5)['completed'],1)
        self.assertEqual(read.call_count,1)
    def test_schema_error_is_terminal_and_retains_specific_safe_reason(self):
        self.work=[self.business]
        with patch.object(jobs,'read_route',return_value=(503,dict(status='unavailable',reason='source_period_mismatch'))):jobs.run_once(True,5)
        s=self.state()[self.key(self.business)];self.assertEqual(s['status'],'failed');self.assertFalse(s['retryable']);self.assertEqual(s['reason'],'source_period_mismatch')
    def test_timer_is_all_day_five_minutes_and_original_service_budget_unchanged(self):
        timer=(PACKAGE/'deploy/fs-data-archive.timer').read_text()
        self.assertIn('OnCalendar=*-*-* *:00/5:00',timer);self.assertNotIn('01,02,03,04,05,06:',timer)
        service=(PACKAGE.parent/'daily-archive-20261021/deploy/fs-data-archive.service').read_text()
        self.assertIn('TimeoutStartSec=10min',service);self.assertIn('Nice=10',service);self.assertIn('IOSchedulingClass=idle',service)
    def test_scheduled_daily_precedes_bounded_history_on_each_catchup_invocation(self):
        clock=[0];starts=[];self.store.prune.return_value={}
        def run(daily,budget):
            starts.append((daily,budget,clock[0]));clock[0]+=budget
            return dict(status='deferred',missingCount=900)
        with patch.dict(sys.modules,{'fcntl':Mock(LOCK_EX=1,LOCK_NB=2)}),patch.object(sys,'argv',['archive_jobs.py','--scheduled']),patch.object(jobs,'run_once',side_effect=run),patch('sys.stdout',new_callable=io.StringIO):
            jobs.main();jobs.main()
        self.assertEqual(starts,[(True,120,0),(False,360,120),(True,120,480),(False,360,600)])
        self.assertEqual(self.store.prune.call_count,2)
    def test_midnight_retains_daily_only_budget_despite_history_backlog(self):
        Clock.at=datetime(2026,10,28,0,1,tzinfo=jobs.TZ);self.store.prune.return_value={}
        with patch.dict(sys.modules,{'fcntl':Mock(LOCK_EX=1,LOCK_NB=2)}),patch.object(sys,'argv',['archive_jobs.py','--scheduled']),patch.object(jobs,'run_once',return_value=dict(status='deferred')) as run,patch('sys.stdout',new_callable=io.StringIO):
            jobs.main()
        run.assert_called_once_with(True,480)
    @unittest.skipIf(os.name!='posix','requires real Linux flock')
    def test_existing_scheduler_lock_is_nonblocking_and_does_not_reenter(self):
        import fcntl
        with (self.root/'scheduler.lock').open('a+b') as owner:
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB);started=time.monotonic()
            with patch.object(sys,'argv',['archive_jobs.py','--scheduled']),patch.object(jobs,'run_once') as run,patch('sys.stdout',new_callable=io.StringIO) as output:
                jobs.main()
            run.assert_not_called();self.assertIn('archive_job_running',output.getvalue());self.assertLess(time.monotonic()-started,.5)

class Transport(unittest.TestCase):
    def response(self,status,raw):
        value=io.BytesIO(raw);value.status=status;return value
    def test_http_422_body_retained_and_classified_without_raising(self):
        with patch.object(jobs,'build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError('http://127.0.0.1',422,'fixture',{},io.BytesIO(b'{"error":"invalid_parameters"}'))
            code,value=jobs.read_route({})
        self.assertEqual(jobs.unavailable(code,value),('failed','invalid_archive_arguments',False))
    def test_gateway_html_is_transient_not_schema_terminal(self):
        with patch.object(jobs,'build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError('http://127.0.0.1',502,'fixture',{},io.BytesIO(b'<html>gateway</html>'))
            code,value=jobs.read_route({})
        self.assertEqual(jobs.unavailable(code,value),('unavailable','source_http_502',True))
    def test_200_malformed_reply_is_terminal(self):
        with patch.object(jobs,'build_opener') as opener:
            opener.return_value.open.return_value=self.response(200,b'not json')
            code,value=jobs.read_route({})
        self.assertEqual(jobs.unavailable(code,value),('failed','archive_response_schema_invalid',False))
    def test_timeout_is_transient(self):
        with patch.object(jobs,'build_opener') as opener:
            opener.return_value.open.side_effect=URLError(TimeoutError())
            code,value=jobs.read_route({})
        self.assertTrue(jobs.unavailable(code,value)[2])

class ScheduledScopes(unittest.TestCase):
    def test_daily_warms_exact_page_keys_without_repeating_native_reads(self):
        import types
        sys.modules.setdefault('pilot',types.SimpleNamespace(encoded=encoded,digest=lambda v:jobs.hashlib.sha256(encoded(v)).hexdigest()))
        from live_summary import query
        from daily_archive import summary_key
        today=jobs.date(2026,11,7)
        definitions={'FC27':('FC27','FC27',1322,1327,'sports'),'RS':('RS','RS',1,2,'general')}
        work=list(jobs.candidates(today,definitions,True))
        for profile in definitions:
            scope=[q for q in work if q['profile']==profile and q['start']=='2026-10-08' and q['end']=='2026-11-06']
            keys=[summary_key(query({k:[v] for k,v in q.items()},definitions)) for q in scope if q.get('mode')=='summary']
            self.assertEqual(len(keys),len({json.dumps(k,sort_keys=True) for k in keys}))
            self.assertEqual(sum(q.get('archiveFamily')=='native' for q in scope),1)
            filters=[dict(rs_site='all',rs_server='all',rs_category='all')] if profile=='RS' else [dict(profit_site=site,profit_category='-1') for site in ('all','main')]
            for selection in filters:
                page=dict(mode='summary',profile=profile,start='2026-10-08',end='2026-11-06',grain='day',profit_basis='shipping',**selection)
                self.assertIn(summary_key(query({k:[v] for k,v in page.items()},definitions)),keys)
        self.assertEqual(len(work),len({json.dumps(q,sort_keys=True) for q in work}))

if __name__=='__main__':unittest.main()

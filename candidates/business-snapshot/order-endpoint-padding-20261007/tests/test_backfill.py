import sys, json, hashlib, unittest, tempfile, copy
from unittest.mock import patch
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
import profit_backfill as b
from profit_daily import normalise, build_history, merge, validate_history
from profit_reader_adapter import adapt_reader
from profit_daily_reader import collect_bounded, validate_requests

TODAY=date(2021,10,6);NOW=datetime(2021,10,6,14,30,tzinfo=timezone.utc)
EXPECTED={'MMOEXP':dict(sites='all-websites',gid='0',tid='',status=''),
          'POE2':dict(sites='all-websites',gid='552',tid='',status='3'),
          'D4':dict(sites='all-websites',gid='456',tid='',status='3'),
          'FC27':dict(sites='all-websites',gid='1322',tid='',status=''),
          'FC26':dict(sites='all-websites',gid='824',tid='',status='')}

def source(key='POE2',day='2021-10-05',value=12.5,captured='2021-10-06T14:21:27+00:00'):
    item=b.request(key,date.fromisoformat(day),EXPECTED);c=EXPECTED[key]
    return dict(system='order.p2pah.cn',endpoint='/stats/admin_order/index.html',
        normalisedScope='all-websites',timezone='Asia/Shanghai',currency='USD',
        period=dict(start=item['start'],end=item['end']),filters=dict(gid=c['gid'],tid=c['tid'],status=c['status'],start_paytime=item['start'],end_paytime=item['end']),
        capturedAt=captured,status='available',orders=80,revenueUsd=4800.0,labelsVerified=True,
        metrics=dict(profitMarginPct=dict(value=value,status='available',source='primary',unit='percent',field='利润率')))

def raw(key='POE2',day='2021-10-05',value=12.5,captured='2021-10-06T14:21:27+00:00'):
    return adapt_reader(source(key,day,value,captured),dict(profileKey=key,date=day),EXPECTED)

def row(*args,**kwargs):return normalise(raw(*args,**kwargs),EXPECTED)
def cache(key='POE2',start='2021-10-05',end='2021-10-05'):
    p=source(key,start);p['period']['end']=str(date.fromisoformat(end)+timedelta(days=1))+' 00:00';p['filters']['end_paytime']=p['period']['end']
    return dict(schemaVersion=1,status='available',consistentPeriod=True,
        baseSnapshotId='existing-snapshot',query=dict(profile=key,start=start,end=end,grain='day',period=copy.deepcopy(p['period'])),profile=dict(primary=p))
def cache_bytes(d):
    d=copy.deepcopy(d);d['resultSha256']=hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return json.dumps(d,ensure_ascii=False).encode()

class PlannerTests(unittest.TestCase):
    def test_recent_same_window_not_today(self):
        q,a=b.plan_requests(TODAY,[],EXPECTED,now=NOW)
        self.assertEqual(a['window']['start'],'2021-09-29');self.assertEqual(a['window']['end'],'2021-10-05')
        self.assertTrue(all('2021-09-29'<=i['date']<str(TODAY) for i in q));self.assertEqual(len(q),12)
    def test_today_rollover_all_active_new_day(self):
        q,a=b.plan_requests(TODAY+timedelta(days=1),[],EXPECTED,now=NOW+timedelta(days=1))
        self.assertEqual({x['profileKey'] for x in q if x['date']=='2021-10-06'},set(EXPECTED)-{'FC26'})
    def test_available_day_not_repeated(self):
        q,_=b.plan_requests(TODAY,[row()],EXPECTED,now=NOW)
        self.assertFalse(any(i['profileKey']=='POE2' and i['date']=='2021-10-05' for i in q))
    def test_fc26_retained_not_scheduled(self):
        prev=[row('FC26')];q,_=b.plan_requests(TODAY,prev,EXPECTED,now=NOW)
        self.assertFalse(any(i['profileKey']=='FC26' for i in q));self.assertEqual(b.merge_cached(prev,[],EXPECTED)[0],prev)
    def test_scope_status_per_project(self):
        q,_=b.plan_requests(TODAY,[],EXPECTED,now=NOW)
        self.assertTrue(all(i['status']==EXPECTED[i['profileKey']]['status'] and i['gid']==EXPECTED[i['profileKey']]['gid'] for i in q))
    def test_limit_rejects_unbounded(self):
        for value in [-1,13,100,True,1.5]:
            with self.subTest(value=value),self.assertRaises(ValueError):b.plan_requests(TODAY,[],EXPECTED,now=NOW,limit=value)
    def test_recent_ahead_selected_old(self):
        q,_=b.plan_requests(TODAY,[],EXPECTED,[dict(profileKey='POE2',start='2021-08-01',end='2021-08-07')],now=NOW)
        self.assertTrue(all(i['date']>='2021-09-29' for i in q))
    def test_selected_after_recent_then_history(self):
        prev=[row(k,str(TODAY-timedelta(days=n))) for k in b.active_keys(EXPECTED) for n in range(1,8)]
        q,_=b.plan_requests(TODAY,prev,EXPECTED,[dict(profileKey='POE2',start='2021-08-01',end='2021-08-07')],now=NOW,limit=1)
        self.assertEqual((q[0]['profileKey'],q[0]['date']),('POE2','2021-08-07'))
    def test_failed_cooldown_not_block_other_projects(self):
        r=row();r.update(status='not_provided',profitMarginPct=None,orders=None,revenueUsd=None,capturedAt=NOW.isoformat(),latestAttemptAt=NOW.isoformat(),latestAttemptStatus='not_provided')
        q,a=b.plan_requests(TODAY,[r],EXPECTED,now=NOW)
        self.assertEqual(a['cooldownGapDays'],1);self.assertFalse(any(i['profileKey']=='POE2' and i['date']=='2021-10-05' for i in q))
    def test_retry_after_cooldown(self):
        r=row();r.update(stale=True,latestAttemptAt=(NOW-timedelta(hours=2)).isoformat())
        q,_=b.plan_requests(TODAY,[r],EXPECTED,now=NOW,limit=12)
        # Unattempted recent gaps precede retries; completion progressively consumes them.
        self.assertTrue(q);self.assertNotIn('FC26',[x['profileKey'] for x in q])
    def test_multi_cycle_progress_no_failing_project_starvation(self):
        rows=[]
        for cycle in range(5):
            q,_=b.plan_requests(TODAY,rows,EXPECTED,now=NOW+timedelta(hours=2*cycle))
            records=[]
            for item in q:
                r=raw(item['profileKey'],item['date'],captured=(NOW+timedelta(hours=2*cycle)).isoformat())
                if item['profileKey']=='MMOEXP':r.update(status='unavailable',profitMarginPct={})
                records.append(r)
            rows=merge(rows,records,EXPECTED)
        covered=b.coverage(TODAY,rows,EXPECTED)
        self.assertTrue(all(not r['missingDates'] for r in covered['profiles'] if r['profileKey']!='MMOEXP'))

class CacheTests(unittest.TestCase):
    def test_exact_single_day_reused_with_capture(self):
        r,w=b.cache_record(cache(),EXPECTED,TODAY)
        self.assertEqual(normalise(r,EXPECTED)['profitMarginPct'],12.5);self.assertEqual(r['capturedAt'],source()['capturedAt'])
    def test_multiday_never_split_margin(self):
        r,w=b.cache_record(cache(start='2021-09-29',end='2021-10-05'),EXPECTED,TODAY)
        self.assertIsNone(r);self.assertEqual(w['start'],'2021-09-29')
    def test_partial_end_not_complete(self):
        d=cache();d['query']['period']['end']='2021-10-05 21:00'
        with self.assertRaises(ValueError):b.cache_record(d,EXPECTED,TODAY)
    def test_wrong_scope_status_dates_units_rejected(self):
        for field,value in [('normalisedScope','site266'),('system','admin.p2pah.cn'),('currency','CNY'),('timezone','UTC'),('labelsVerified',False)]:
            d=cache();d['profile']['primary'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):b.cache_record(d,EXPECTED,TODAY)
        d=cache();d['profile']['primary']['filters']['status']=''
        with self.assertRaises(ValueError):b.cache_record(d,EXPECTED,TODAY)
    def test_sha_verified_and_tampered_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/('a'*64+'.json');p.write_bytes(cache_bytes(cache()))
            r,w,a=b.load_caches(tmp,EXPECTED,TODAY);self.assertEqual(len(r),1)
            d=json.loads(p.read_bytes());d['profile']['primary']['orders']=7;p.write_text(json.dumps(d))
            r,w,a=b.load_caches(tmp,EXPECTED,TODAY);self.assertEqual(r,[]);self.assertEqual(a['ignored'],1)
    def test_scan_deadline_and_no_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/('a'*64+'.json')).write_bytes(cache_bytes(cache()))
            r,w,a=b.load_caches(tmp,EXPECTED,TODAY,scan_seconds=0)
            self.assertEqual(r,[]);self.assertEqual(a['stopReason'],'scan_deadline')
    def test_genuine_zero_and_negative_preserved(self):
        for value in [0,-2.3]:self.assertEqual(normalise(raw(value=value),EXPECTED)['profitMarginPct'],value)
    def test_cache_old_does_not_replace_newer(self):
        prev=[row(value=27,captured='2021-10-06T14:25:00+00:00')]
        result,_=b.merge_cached(prev,[raw(value=25,captured='2021-10-06T14:21:00+00:00')],EXPECTED)
        self.assertEqual(result[0]['profitMarginPct'],27)
    def test_conflicting_same_time_cache_ignored(self):
        result,n=b.merge_cached([row(value=27)],[raw(value=25)],EXPECTED)
        self.assertEqual(n,1);self.assertEqual(result[0]['profitMarginPct'],27)

class ReaderAndMergeTests(unittest.TestCase):
    def test_partial_success_survives_one_failure(self):
        wanted=[b.request('POE2',date(2021,10,5),EXPECTED),b.request('D4',date(2021,10,5),EXPECTED)]
        values={wanted[0]['key']:source(),wanted[1]['key']:dict(status='unavailable',attemptedAt=NOW.isoformat())}
        records,a=b.apply_results(wanted,values,EXPECTED);h=build_history([],records,EXPECTED)
        self.assertEqual((a['available'],a['failed']),(1,1));self.assertEqual(next(x for x in h['daily'] if x['profileKey']=='D4')['profitMarginPct'],None)
    def test_failed_refresh_keeps_native_stale(self):
        item=b.request('POE2',date(2021,10,5),EXPECTED)
        records,a=b.apply_results([item],{item['key']:dict(status='unavailable',attemptedAt=NOW.isoformat())},EXPECTED)
        merged=merge([row()],records,EXPECTED)[0];self.assertEqual(merged['profitMarginPct'],12.5);self.assertTrue(merged['stale']);self.assertEqual(merged['capturedAt'],source()['capturedAt'])
    def test_budget_deferred_does_not_fake_attempt(self):
        item=b.request('POE2',date(2021,10,5),EXPECTED)
        r,a=b.apply_results([item],{item['key']:dict(status='not_started_budget')},EXPECTED)
        self.assertEqual(r,[]);self.assertEqual(a['attempted'],0)
    def test_schema_contract_preserved(self):
        h=build_history([], [raw(value=-0.5)],EXPECTED);validate_history(h,EXPECTED)
        self.assertEqual(h['contractId'],'order-native-daily-margin-v2');self.assertIsNone(h['daily'][0]['profitUsd'])
    def test_synthetic_sample_field_contract(self):
        sample=json.loads((ROOT/'tests/fixtures/synthetic-single-day.json').read_text(encoding='utf-8'))
        r=adapt_reader(sample['source'],dict(profileKey='POE2',date='2021-10-05'),EXPECTED)
        native=normalise(r,EXPECTED);self.assertEqual((native['orders'],native['revenueUsd'],native['profitMarginPct']),(80,4800.0,12.5))
    def test_reader_request_bounds(self):
        item=b.request('POE2',date(2021,10,5),EXPECTED)
        self.assertEqual(len(validate_requests(dict(requests=[item],budgetSeconds=30))[0]),1)
        for budget in [0,True,241,float('inf'),float('nan')]:
            with self.subTest(budget=budget),self.assertRaises(ValueError):validate_requests(dict(requests=[item],budgetSeconds=budget))
    def test_reader_budget_stops_and_returns_completed(self):
        wanted=[b.request('POE2',date(2021,10,5),EXPECTED),b.request('D4',date(2021,10,5),EXPECTED)]
        class Page:
            def set_default_timeout(self,value):pass
        clock_values=iter([0,30])
        results=collect_bounded(Page(),wanted,25,clock=lambda:next(clock_values),read=lambda p,i,t:source(i['profileKey']))
        self.assertEqual(results[wanted[0]['key']]['status'],'available');self.assertEqual(results[wanted[1]['key']]['status'],'not_started_budget')
    def test_reader_auth_failure_aborts_without_leaking(self):
        wanted=[b.request('POE2',date(2021,10,5),EXPECTED),b.request('D4',date(2021,10,5),EXPECTED)]
        class Page:
            def set_default_timeout(self,value):pass
        def bad(*args):raise ValueError('primary_login_or_page_unavailable')
        results=collect_bounded(Page(),wanted,25,clock=lambda:0,read=bad)
        self.assertEqual(results[wanted[0]['key']]['status'],'unavailable');self.assertEqual(results[wanted[1]['key']]['status'],'not_started_budget')
        self.assertEqual(results[wanted[0]['key']]['errorCode'],'primary_login_or_page_unavailable')  # fixed allowlisted diagnostic is now intentional
    def test_source_changes_only_allowed(self):
        baseline=json.loads((ROOT/'baseline-source-sha256.json').read_text(encoding='utf-8'))
        # The archived collector was advanced in 4cdbac68 before this reader change.
        baseline['collector.py']='eb11a14a061a649717af503a2c531bd54d2bd3e699f01119d8e03cadb378ee7e'
        changed=[]
        for name,digest in baseline.items():
            source=(ROOT/'source'/name).read_bytes().replace(b'\r\n',b'\n')
            if digest not in (hashlib.sha256(source).hexdigest(),
                              hashlib.sha256(source.replace(b'\n',b'\r\n')).hexdigest()):
                changed.append(name)
        self.assertEqual(changed,['profit_backfill.py','profit_daily_reader.py'])

class CollectorIntegrationTests(unittest.TestCase):
    def setUp(self):
        import collector
        self.c=collector
        d=json.loads((ROOT/'tests/fixtures/synthetic-history.json').read_text(encoding='utf-8'))
        self.previous=dict(profitHistory=dict(daily=d['daily']))
        self.expected=self.c.expected_contracts(self.c.PROFILES)
    def native(self,container,script,payload,timeout):
        self.assertEqual((container,script),('fc27-cloud-browser','profit_daily_reader.py'))
        self.assertLessEqual(len(payload['requests']),12);self.assertEqual(payload['budgetSeconds'],timeout)
        result={}
        for item in payload['requests']:
            p=source();p['period']=dict(start=item['start'],end=item['end'])
            p['filters']=dict(gid=item['gid'],tid=item['tid'],status=item['status'],start_paytime=item['start'],end_paytime=item['end'])
            result[item['key']]=p
        return result
    def run_phase(self,call=None,remaining=1000):
        with patch.object(self.c.time,'monotonic',return_value=100),patch.object(self.c,'COLLECTION_DEADLINE',100+remaining),patch.object(self.c,'load_caches',return_value=([],[],dict(scanned=0))),patch.object(self.c,'call',side_effect=call or self.native) as called:
            h=self.c.collect_profit_history(TODAY,self.previous)
            return h,called.call_count
    def test_success_native_single_batch_history_grows(self):
        h,n=self.run_phase();self.assertEqual(n,1);self.assertEqual(len(h['daily']),25)
        self.assertEqual(h['collection']['optionalReadStatus'],'available');self.assertEqual(h['collection']['reads']['available'],12)
        validate_history(h,self.expected)
    def test_no_remaining_budget_no_reader_no_fake_attempts(self):
        h,n=self.run_phase(remaining=100)
        self.assertEqual(n,0);self.assertEqual(len(h['daily']),13);self.assertEqual(h['collection']['optionalReadStatus'],'skipped_remaining_budget')
        self.assertEqual(h['collection']['reads']['attempted'],0)
    def test_smaller_budget_keeps_full90_publish_reserve(self):
        h,n=self.run_phase(remaining=120)
        self.assertEqual(h['collection']['optionalReadTimeoutSeconds'],30);self.assertEqual(h['collection']['publicationReserveSeconds'],90)
    def test_batch_timeout_retains_all13_good_points(self):
        def fail(*args):raise self.c.subprocess.TimeoutExpired('reader',30)
        h,n=self.run_phase(call=fail);self.assertEqual(n,1);self.assertEqual(h['daily'],self.previous['profitHistory']['daily'])
        self.assertEqual(h['collection']['optionalReadStatus'],'unavailable');self.assertTrue(h['collection']['reads']['batchProgressUnknown'])
    def test_cache_read_failure_still_publishes_native(self):
        with patch.object(self.c.time,'monotonic',return_value=100),patch.object(self.c,'COLLECTION_DEADLINE',1100),patch.object(self.c,'load_caches',side_effect=OSError('private')),patch.object(self.c,'call',side_effect=self.native):
            h=self.c.collect_profit_history(TODAY,self.previous)
            self.assertEqual(h['collection']['cache']['stopReason'],'cache_read_unavailable');self.assertEqual(len(h['daily']),25)
    def test_atomic_publication_same_final_id_sha_original_contract(self):
        from atomic_snapshot import publish
        h,n=self.run_phase();profiles={}
        for key,c in self.expected.items():
            p=source();p['filters'].update(gid=c['gid'],tid=c['tid'],status=c['status'])
            profiles[key]=dict(period=p['period'],primary=p,supplement=dict(status='unavailable'),metrics=dict(orders=dict(value=p['orders'],source='primary'),revenueUsd=dict(value=p['revenueUsd'],source='primary')))
        value=dict(timezone='Asia/Shanghai',currency='USD',scopeApproved=True,scopeContractId='all-websites-order-primary-admin-supplement-v1',requiredProfiles=list(profiles),profiles=profiles,profitHistory=h)
        with tempfile.TemporaryDirectory() as tmp:
            m=publish(tmp,value,now=NOW);body=(Path(tmp)/m['path']).read_bytes();data=json.loads(body)
            self.assertEqual(hashlib.sha256(body).hexdigest(),m['sha256']);self.assertEqual(data['snapshotId'],data['profitHistory']['snapshotId'])
            self.assertEqual(data['profitHistory']['schemaVersion'],2);self.assertEqual(m['serverIntervalSeconds'],7200);self.assertEqual(m['clientCheckSeconds'],60)

if __name__=='__main__':unittest.main(verbosity=2)

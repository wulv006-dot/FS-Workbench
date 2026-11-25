"""Regression counterexamples for PDB-01/02/03; no network or production imports."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import test_backfill as base
from test_backfill import ROOT,TODAY,NOW,EXPECTED,source,raw,row,cache,cache_bytes
import profit_backfill as b
from profit_daily import normalise,merge,build_history,validate_history
from profit_daily_reader import parse_daily_label,read_one,collect_bounded

class MalformedOptionalTests(unittest.TestCase):
    def test_null_array_and_bad_nested_cache_keep_good_file(self):
        bad=[None,[],dict(cache(),query=[1]),dict(cache(),profile=[1]),dict(cache(),profile=dict(primary=[1]))]
        for field in ['metrics','filters','period']:
            d=cache();d['profile']['primary'][field]=[1];bad.append(d)
        d=cache();d['profile']['primary']['metrics']['profitMarginPct']=[1];bad.append(d)
        d=cache();d['profile']['primary']['capturedAt']='not-a-timestamp';bad.append(d)
        for value in bad:
            with self.subTest(value=type(value).__name__),tempfile.TemporaryDirectory() as tmp:
                (Path(tmp)/('a'*64+'.json')).write_bytes(cache_bytes(cache()))
                body=json.dumps(value).encode() if not isinstance(value,dict) else cache_bytes(value)
                (Path(tmp)/('b'*64+'.json')).write_bytes(body)
                records,selected,audit=b.load_caches(tmp,EXPECTED,TODAY)
                self.assertEqual(len(records),1);self.assertEqual(audit['ignored'],1)
    def test_bad_batch_envelope_no_fake_day_attempt(self):
        wanted=[b.request('POE2',date(2021,10,5),EXPECTED)]
        for result in [None,[],[1],'wrong',42]:
            with self.subTest(result=result):
                r,a=b.apply_results(wanted,result,EXPECTED)
                self.assertEqual(r,[]);self.assertEqual(a['attempted'],0);self.assertTrue(a['batchProgressUnknown'])
    def test_mixed_result_good_point_and_malformed_points_isolated(self):
        wanted=[b.request('POE2',date(2021,10,5),EXPECTED),b.request('D4',date(2021,10,5),EXPECTED)]
        bad=[[],[1],42,dict(status='unavailable',attemptedAt='not-a-timestamp'),dict(status='unavailable',attemptedAt='2021-10-06T14:30:00')]
        for field in ['metrics','filters','period']:
            p=source('D4');p[field]=[1];bad.append(p)
        p=source('D4');p['metrics']['profitMarginPct']=None;bad.append(p)
        for value in bad:
            with self.subTest(value=value):
                records,a=b.apply_results(wanted,{wanted[0]['key']:source(),wanted[1]['key']:value},EXPECTED)
                h=build_history([],records,EXPECTED)
                self.assertEqual(next(r for r in h['daily'] if r['profileKey']=='POE2')['profitMarginPct'],12.5)
                self.assertEqual(a['available'],1)
                if isinstance(value,dict) and value.get('attemptedAt') in ['not-a-timestamp','2021-10-06T14:30:00']:
                    self.assertEqual(a['attempted'],1);self.assertFalse(any(r['profileKey']=='D4' for r in h['daily']))
    def test_merge_invalid_optional_timestamp_does_not_drop_good_point(self):
        valid=raw('D4');invalid=raw();invalid['capturedAt']='not-a-timestamp'
        result,rejected=b.merge_cached([row()], [None,[],invalid,valid],EXPECTED)
        self.assertEqual(rejected,3);self.assertEqual(len(result),2)
    def test_persisted_corruption_remains_explicit(self):
        corrupt=row();corrupt['capturedAt']='not-a-timestamp'
        with self.assertRaises(ValueError):b.merge_cached([corrupt],[],EXPECTED)
    def test_bad_naive_attempt_never_marks_good_old_stale(self):
        item=b.request('POE2',date(2021,10,5),EXPECTED)
        for attempted in [None,'bad','2021-10-06T14:30:00',[],42]:
            r,a=b.apply_results([item],{item['key']:dict(status='unavailable',attemptedAt=attempted)},EXPECTED)
            kept,n=b.merge_cached([row()],r,EXPECTED)
            self.assertEqual(kept,[row()]);self.assertEqual(a['rejected'],1)

class MixedCollectorTests(unittest.TestCase):
    setUp=base.CollectorIntegrationTests.setUp
    native=base.CollectorIntegrationTests.native
    run_phase=base.CollectorIntegrationTests.run_phase
    def test_bad_batch_arrays_preserve_old_history_and_publish(self):
        for response in [None,[],[1],42]:
            with self.subTest(response=response):
                h,n=self.run_phase(call=lambda *args:response)
                self.assertEqual(h['daily'],self.previous['profitHistory']['daily'])
                self.assertEqual(h['collection']['optionalReadStatus'],'unavailable')
                self.publish_same_version(h)
    def test_mixed_good_bad_metrics_time_and_scalar_still_publish(self):
        def mixed(*args):
            payload=args[2];out=self.native(*args);items=payload['requests']
            out[items[1]['key']]['metrics']=[1]
            out[items[2]['key']]=dict(status='unavailable',attemptedAt='not-a-timestamp')
            out[items[3]['key']]=[1]
            return out
        h,n=self.run_phase(call=mixed)
        self.assertEqual(h['collection']['optionalReadStatus'],'partial')
        self.assertEqual(h['collection']['reads']['available'],9)
        self.assertEqual(h['collection']['reads']['rejected'],2)
        self.assertTrue(any(r['profileKey']=='POE2' and r['date']=='2021-10-05' and r['status']=='available' for r in h['daily']))
        for old in self.previous['profitHistory']['daily']:
            self.assertIn(old,h['daily'])
        self.publish_same_version(h)
    def test_invalid_merge_record_isolated_at_collector_boundary(self):
        bad=raw();bad['capturedAt']='bad'
        good=raw('D4');good['capturedAt']='2021-10-06T14:35:00+00:00'
        with patch.object(self.c.time,'monotonic',return_value=100),patch.object(self.c,'COLLECTION_DEADLINE',1100),patch.object(self.c,'load_caches',return_value=([],[],dict(scanned=0))),patch.object(self.c,'call',side_effect=self.native),patch.object(self.c,'apply_results',return_value=([bad,good],dict(attempted=2,available=2,failed=0,deferred=0,rejected=0))):
            h=self.c.collect_profit_history(TODAY,self.previous)
        self.assertEqual(h['collection']['reads']['mergeRejected'],1)
        self.assertEqual(h['collection']['optionalReadStatus'],'partial')
        self.assertTrue(any(r['profileKey']=='D4' and r['date']=='2021-10-05' and r['status']=='available' for r in h['daily']))
        self.publish_same_version(h)
    def test_optional_os_error_retains_history(self):
        def unavailable(*args):raise OSError('arbitrary exception text must not leave the boundary')
        h,n=self.run_phase(call=unavailable)
        self.assertEqual(h['daily'],self.previous['profitHistory']['daily'])
        self.assertEqual(h['collection']['optionalReadStatus'],'unavailable')
        self.assertNotIn('arbitrary exception',json.dumps(h))
        self.publish_same_version(h)
    def publish_same_version(self,h):
        from atomic_snapshot import publish
        profiles={}
        for key,c in self.expected.items():
            p=source();p['filters'].update(gid=c['gid'],tid=c['tid'],status=c['status'])
            profiles[key]=dict(period=p['period'],primary=p,supplement=dict(status='unavailable'),metrics=dict(orders=dict(value=80,source='primary'),revenueUsd=dict(value=4800.0,source='primary')))
        body=dict(timezone='Asia/Shanghai',currency='USD',scopeApproved=True,scopeContractId='all-websites-order-primary-admin-supplement-v1',profiles=profiles,requiredProfiles=list(profiles),profitHistory=h)
        with tempfile.TemporaryDirectory() as tmp:
            m=publish(tmp,body,now=NOW);payload=(Path(tmp)/m['path']).read_bytes();d=json.loads(payload)
            self.assertEqual(hashlib.sha256(payload).hexdigest(),m['sha256']);self.assertEqual(d['snapshotId'],d['profitHistory']['snapshotId'])

class NativeDateLabelTests(unittest.TestCase):
    def fake_page(self,labels,counts=None,amounts=None,orders=80,sales=4800.0,avg=60.0):
        counts=counts if counts is not None else [orders]*len(labels)
        amounts=amounts if amounts is not None else [sales]*len(labels)
        item=b.request('POE2',date(2021,10,5),EXPECTED)
        vals=[str(orders),'$'+str(sales),'12.5%','100%','$'+str(avg)]
        names=[label+' '+v for label,v in zip(['订单数量','订单金额','利润率','发货完成率','单均价'],vals)]
        raw=dict(origin='https://order.p2pah.cn',path='/stats/admin_order/index.html',login=False,
            filters=source()['filters'],names=names,metrics=vals,
            charts=[dict(title=['订单数量和金额'],labels=labels,series=[dict(name='订单数',data=counts),dict(name='订单金额',data=amounts)])])
        class Reader:
            def native_order_stats(self, filters, *, timeout):
                return copy.deepcopy(raw)
        return Reader(),item
    def test_wrong_previous_right_end_invalid_calendar_and_hours_rejected(self):
        labels=['2021-10-04','2021-10-06','10-06','2021-10-05 24','2021-10-05 99','2021-10-06 00','2021-02-30','02-30','2021-13-01','2021-10-04 23']
        for label in labels:
            with self.subTest(label=label):
                page,item=self.fake_page([label])
                with self.assertRaises(ValueError):read_one(page,item,20000)
    def test_valid_actual_calendar_labels_only_then_verified(self):
        for label in ['2021-10-05','10-05','2021-10-05 00','2021-10-05 23','2021-10-05 23:00']:
            with self.subTest(label=label):
                page,item=self.fake_page([label]);r=read_one(page,item,20000)
                self.assertTrue(r['labelsVerified']);self.assertEqual(r['orders'],80)
    def test_duplicates_aliases_and_mixed_grain_rejected(self):
        for labels in [['10-05','2021-10-05'],['2021-10-05 01','2021-10-05 01:00'],['2021-10-05','2021-10-05 01']]:
            with self.subTest(labels=labels):
                page,item=self.fake_page(labels,counts=[40,40],amounts=[2400.0,2400.0])
                with self.assertRaises(ValueError):read_one(page,item,20000)
    def test_empty_chart_is_missing_but_valid_dated_zero_is_real(self):
        page,item=self.fake_page([],orders=0,sales=0,avg=0)
        with self.assertRaises(ValueError):read_one(page,item,20000)
        page,item=self.fake_page(['10-05'],orders=0,sales=0,avg=0)
        r=read_one(page,item,20000);self.assertTrue(r['labelsVerified']);self.assertEqual((r['orders'],r['revenueUsd']),(0,0))
    def test_cross_year_mmdd_exclusive_end(self):
        begin=datetime(2021,12,31);stop=datetime(2022,1,1)
        self.assertEqual(parse_daily_label('12-31',begin,stop),('2021-12-31','day'))
        with self.assertRaises(ValueError):parse_daily_label('01-01',begin,stop)
    def test_leap_day_and_nonleap_date(self):
        begin=datetime(2024,2,29);stop=datetime(2024,3,1)
        self.assertEqual(parse_daily_label('02-29',begin,stop),('2024-02-29','day'))
        self.assertEqual(parse_daily_label('2024-02-29 23',begin,stop),('2024-02-29 23:00','hour'))
        for label in ['02-29','2021-02-29']:
            with self.assertRaises(ValueError):parse_daily_label(label,datetime(2021,2,28),datetime(2021,3,1))
    def test_bad_label_becomes_unavailable_keeps_old_point(self):
        page,item=self.fake_page(['10-06'])
        result=collect_bounded(page,[item],30,clock=lambda:0)
        self.assertEqual(result[item['key']]['status'],'unavailable')
        records,a=b.apply_results([item],result,EXPECTED)
        kept,ignored=b.merge_cached([row()],records,EXPECTED)
        self.assertEqual(kept[0]['profitMarginPct'],12.5)

class RetryAgingTests(unittest.TestCase):
    def failed_grid(self):
        start=datetime(2021,10,6,0,30,tzinfo=timezone.utc);rows=[]
        for key in b.active_keys(EXPECTED):
            for n in range(1,8):
                day=str(TODAY-timedelta(days=n));r=row(key,day,captured=(start-timedelta(hours=2)).isoformat())
                if key in ['POE2','D4']:
                    r.update(status='not_provided',profitMarginPct=None,orders=None,revenueUsd=None,latestAttemptStatus='not_provided')
                rows.append(r)
        return start,rows
    def attempt_all(self,rows,requests,at,recover=()):
        incoming=[]
        for item in requests:
            r=raw(item['profileKey'],item['date'],captured=at.isoformat())
            if (item['profileKey'],item['date']) not in recover:r.update(status='unavailable',profitMarginPct={})
            incoming.append(r)
        return merge(rows,incoming,EXPECTED)
    def test_exact14_retries_all_seen_in_two_cycles_limit12(self):
        start,rows=self.failed_grid();seen=set()
        targets={(key,str(TODAY-timedelta(days=n))) for key in ['POE2','D4'] for n in range(1,8)}
        for cycle in range(2):
            now=start+timedelta(hours=cycle*2);q,a=b.plan_requests(TODAY,rows,EXPECTED,now=now)
            self.assertEqual(len(q),12);seen.update((x['profileKey'],x['date']) for x in q)
            rows=self.attempt_all(rows,q,now)
        self.assertTrue(targets<=seen)
    def test_oldest_day_recovers_other_project_persists_failure(self):
        start,rows=self.failed_grid();recovered=('POE2','2021-09-29');selected_cycles=[]
        for cycle in range(6):
            now=start+timedelta(hours=cycle*2);q,a=b.plan_requests(TODAY,rows,EXPECTED,now=now)
            selected={(i['profileKey'],i['date']) for i in q};selected_cycles.append(selected)
            rows=self.attempt_all(rows,q,now,recover=[recovered])
            self.assertLessEqual(len(q),12);self.assertFalse(any(i['profileKey']=='FC26' for i in q))
        self.assertIn(recovered,selected_cycles[1]);self.assertTrue(all(recovered not in s for s in selected_cycles[2:]))
        self.assertEqual(next(r for r in rows if (r['profileKey'],r['date'])==recovered)['status'],'available')
        self.assertTrue(all(r['status']=='not_provided' for r in rows if r['profileKey']=='D4'))
    def test_beijing_rollover_new_day_then_aged_current_window_retry(self):
        start,rows=self.failed_grid();current=date(2021,10,7);now=datetime(2021,10,6,17,30,tzinfo=timezone.utc)
        # Every project's new complete day is independently native; two fail as before.
        for key in b.active_keys(EXPECTED):
            r=row(key,'2021-10-06',captured=now.isoformat())
            if key in ['POE2','D4']:continue  # unattempted new gaps still take priority
            rows.append(r)
        seen=set();targets={(k,str(current-timedelta(days=n))) for k in ['POE2','D4'] for n in range(1,8)}
        for cycle in range(3):
            at=now+timedelta(hours=cycle*2);q,a=b.plan_requests(current,rows,EXPECTED,now=at)
            if cycle==0:self.assertEqual({i['profileKey'] for i in q[:2]}, {'POE2','D4'});self.assertTrue(all(i['date']=='2021-10-06' for i in q[:2]))
            seen.update((i['profileKey'],i['date']) for i in q);rows=self.attempt_all(rows,q,at)
            self.assertEqual(a['window']['start'],'2021-09-30');self.assertEqual(a['window']['end'],'2021-10-06')
            self.assertLessEqual(len(q),12)
        self.assertTrue(targets<=seen)

if __name__=='__main__':unittest.main(verbosity=2)

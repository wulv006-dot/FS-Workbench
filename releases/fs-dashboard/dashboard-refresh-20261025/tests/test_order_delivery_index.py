import io
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib import request

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'source'))
import channel_cache
import order_delivery_index as index

DAY, NEXT = '2026-11-16', '2026-11-17'
SITE = index.MAIN_SITE


def delivery(identity, order, at, cost='1.23', **extra):
    return dict(delivery_id=str(identity),source=SITE,sn=order,trade_at=at,genre=1,
                cost_total=cost,sale_total='3.45',qty='500',gift='5',**extra)


class DeliveryIndexTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def publish(self, rows, *, name='delivery-days/'+DAY+'.json', generated=NEXT+'T00:05:00+08:00', **period):
        channel_cache.atomic(self.root/name, dict(contract='channel-order-deliveries-v1',
            period=period or dict(start=DAY,end=DAY), generatedAt=generated, complete=True, rows=rows))

    def lookup(self, *numbers, **kwargs):
        return index.read_orders(((SITE,n) for n in numbers),root=self.root,**kwargs)

    def test_exact_windows_bind_same_revision_rows_and_drop_retained_rolling_rows(self):
        baseline = self.lookup('A')
        self.assertEqual(baseline['reason'],'index_missing')
        self.assertFalse((self.root/index.DATABASE).exists())
        trade = DAY+' 23:59:58'
        self.publish([delivery('1','A',trade,operator='discard-me',payee='discard-me')])
        self.publish([delivery('2','A',NEXT+' 00:00:04','5.55'),delivery('3','A',DAY+' 07:11:00','9999')],
            name='order-deliveries.json',generated=NEXT+'T00:10:00+08:00',
            start=NEXT,end=NEXT,until=NEXT+' 00:08')
        revision = index.sync(self.root)
        out = self.lookup('A','A','missing')
        self.assertEqual((out['status'],out['revision']),('available',revision))
        self.assertEqual(out['legacyReason'],'rolling_retained_rows')
        self.assertEqual(out['rollingWindow']['since'],NEXT+' 00:00:00')
        self.assertEqual([(row['delivery_id'],row['cost_total']) for row in out['rows']],[('1','1.23'),('2','5.55')])
        self.assertNotIn('discard-me',json.dumps(out))
        self.assertEqual(self.lookup('A',since=NEXT+' 00:00:00',until=NEXT+' 00:01:00')['rows'],out['rows'][1:])
        self.assertEqual(self.lookup()['windows'],out['windows'])
        self.assertEqual(index.read_orders([(SITE,'A'),('www.other.test','A')],root=self.root)['reason'],'unsupported_source')
        kwargs = dict(source=SITE,since=trade,until=NEXT+' 00:08:59')
        self.assertTrue(index.covers_window(out['windows'],as_of=NEXT+'T00:10:00+08:00',**kwargs))
        self.assertFalse(index.covers_window(out['windows'],as_of=NEXT+'T00:09:59+08:00',**kwargs))
        self.assertFalse(index.covers_window(out['windows'][1:],as_of=NEXT+'T00:15:00+08:00',**kwargs))
        self.assertFalse(index.covers_window(out['windows'],SITE,trade,NEXT+' 00:09:00',as_of=NEXT+'T00:15:00+08:00'))

    def test_read_evidence_binds_adjacent_windows_and_provenance_to_the_same_revision(self):
        first, last = DAY+' 00:00:00', NEXT+' 00:09:59'
        row = delivery('2', 'A', NEXT+' 00:03:00')
        self.publish([])
        rev_day = index.sync(self.root)
        self.publish([row], name='order-deliveries.json', generated=NEXT+'T00:12:00+08:00',
                     start=NEXT, end=NEXT, until=NEXT+' 00:09')
        rev_rolling = index.sync(self.root)
        args = dict(root=self.root, since=first, until=last)
        evidence = index.read_evidence([(SITE,'A')], as_of=NEXT+'T00:12:00+08:00', **args)
        self.assertEqual(evidence['intervals'], [(first,last)])
        self.assertEqual(evidence['rows'], [row])
        self.assertEqual(evidence['revision'], rev_rolling)
        self.assertEqual([proof['revision'] for proof in evidence['provenance']], [rev_day, rev_rolling])
        self.assertTrue(all(proof['indexRevision']==rev_rolling for proof in evidence['provenance']))
        with self.assertRaisesRegex(index.InvalidDeliveryEvidence, 'invalid_delivery_index_window'):
            index.read_evidence([(SITE,'A')], as_of=NEXT+'T00:11:00+08:00', **args)
        day = index.read_evidence([(SITE,'A')], as_of=NEXT+'T00:11:00+08:00', root=self.root,
                                  since=first, until=DAY+' 23:59:59')
        self.assertEqual(day['revision'], rev_rolling)
        self.assertEqual(day['rows'], [])
        self.assertEqual(day['generatedAt'], '2026-11-16T16:05:00+00:00')

    def test_correction_removes_old_association_only_in_complete_scope_and_replays_old_revision(self):
        old_rows = [delivery('1','A',DAY+' 11:01:00'),delivery('2','A',DAY+' 11:02:00'),
                    delivery('3','C',DAY+' 07:11:00','6.78')]
        self.publish(old_rows)
        old = index.sync(self.root)
        next_rows = [delivery('1','B',DAY+' 11:01:00','9.28')]
        self.publish(next_rows,name='order-deliveries.json',generated=NEXT+'T00:12:00+08:00',
                     start=DAY,end=DAY,since=DAY+' 11:00',until=DAY+' 12:00')
        self.assertEqual(self.lookup('A')['status'],'stale')
        new = index.sync(self.root)
        self.assertNotEqual(old,new)
        self.assertEqual(self.lookup('A')['rows'],[])
        self.assertEqual(self.lookup('B','C')['rows'],[old_rows[2],next_rows[0]])
        self.assertEqual(self.lookup('A','C',revision=old)['rows'],[old_rows[2],*old_rows[:2]])
        self.assertEqual(index.sync(self.root),new)
        self.assertTrue(self.lookup('A')['legacyCompatible'])
        channel_cache.atomic(self.root/'order-supplements.json', {})
        self.assertEqual(self.lookup('A')['legacyReason'],'order_supplements_present')
        # An older archive carried in later cannot resurrect current tombstones/reassigned IDs.
        self.publish(old_rows,generated=NEXT+'T00:07:00+08:00')
        self.assertNotEqual(index.sync(self.root),new)
        self.assertEqual(self.lookup('A')['rows'],[])
        self.assertEqual(self.lookup('B')['rows'],next_rows)

    def test_failed_capture_leaves_old_revision_and_last_known_rows(self):
        row = delivery('1','A',DAY+' 10:00:00')
        self.publish([row])
        old = index.sync(self.root)
        self.publish([row,row],generated=NEXT+'T00:06:00+08:00')
        with self.assertRaisesRegex(ValueError,'invalid_delivery_index_identity'):
            index.sync(self.root)
        self.assertIsNone(index.sync_after_publish(self.root))
        self.assertEqual(self.lookup('A')['status'],'stale')
        self.assertEqual(self.lookup('A',revision=old)['rows'],[row])

    def test_concurrent_reentry_and_repeat_queries_do_not_duplicate_publication(self):
        self.publish([delivery('1','A',DAY+' 10:00:00')])
        start = Barrier(3)
        def run():
            start.wait()
            return index.sync(self.root)
        with ThreadPoolExecutor(max_workers=3) as workers:
            pending = [workers.submit(run) for _ in range(3)]
            versions = [item.result(timeout=5) for item in pending]
        self.assertEqual(len(set(versions)),1)
        path = self.root/index.DATABASE
        before = path.read_bytes()
        for _ in range(4):
            self.assertEqual(self.lookup('A')['revision'],versions[0])
        self.assertEqual(path.read_bytes(),before)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM batches').fetchone()[0],1)

    def test_daily_producer_reuses_completed_day_checks_index_even_before_es(self):
        auth_session = Mock()
        fcntl = SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=Mock())
        shared = SimpleNamespace(read=lambda scope: dict(rows=[],coverage=dict(admin_complete=False,missing_days=[DAY])))
        row = delivery('1','A',DAY+' 12:05:00')
        with patch.dict(sys.modules,dict(fcntl=fcntl,p2pah_auth=SimpleNamespace(Session=Mock(return_value=auth_session)),
                                         shared_es_facts=shared)), patch('channel_cost_source.collect',return_value=[row]) as raw:
            first = channel_cache.cache_day(DAY,self.root,shared=True)
            second = channel_cache.cache_day(DAY,self.root,shared=True)
            self.assertEqual(first,second)
            self.assertEqual(first['status'],'partial')
            self.assertEqual(first['deliveryIndexStatus'],'complete')
            raw.assert_called_once_with(auth_session,DAY,DAY)
            self.assertEqual(self.lookup('A')['rows'],[row])
            raw.return_value=[dict(row,cost_total='6.99')]
            new=channel_cache.cache_day(DAY,self.root,shared=True,recheck=True)
            self.assertNotEqual(new['deliveryIndexRevision'],first['deliveryIndexRevision'])
            self.assertEqual(self.lookup('A')['rows'][0]['cost_total'],'6.99')
            self.assertEqual(self.lookup('A',revision=first['deliveryIndexRevision'])['rows'],[row])

    def test_historical_recheck_prioritizes_yesterday_and_never_forces_yesterday(self):
        yesterday=(datetime.now(index.TZ).date()-timedelta(days=1)).isoformat()
        fcntl = SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=Mock())
        with patch.dict(sys.modules,dict(fcntl=fcntl)), patch.object(channel_cache,'ROOT',self.root), \
             patch.object(sys,'argv',['channel_cache','--day',DAY,'--recheck']), \
             patch.object(channel_cache,'cache_day',return_value={'status':'partial','deliveryIndexRevision':'published'}) as producer, \
             patch('builtins.print'):
            channel_cache.main()
        self.assertEqual([(call.args[0],call.kwargs['recheck']) for call in producer.call_args_list],
                         [(yesterday,False),(DAY,True)])

    def test_backfill_repairs_gaps_before_rotating_one_older_day_and_reuses_completion(self):
        now = datetime.fromisoformat('2026-11-19T01:00:00+08:00')
        self.publish([])
        self.assertIsNone(channel_cache.rotation_day([NEXT,DAY],self.root,now))
        self.publish([],name='delivery-days/'+NEXT+'.json',start=NEXT,end=NEXT)
        oldest = self.root/'delivery-days'/f'{DAY}.json'
        newer = self.root/'delivery-days'/f'{NEXT}.json'
        for path,delta in [(oldest,2),(newer,1)]:
            timestamp = (now-timedelta(days=delta)).timestamp()
            os.utime(path,(timestamp,timestamp))
        fcntl = SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=Mock())
        def run(day, *, shared, recheck):
            if recheck:
                os.utime(oldest,(now.timestamp(),now.timestamp()))
            return dict(status='partial',deliveryIndexRevision='published')
        with patch.dict(sys.modules,dict(fcntl=fcntl)), patch.object(channel_cache,'ROOT',self.root), \
             patch.object(sys,'argv',['channel_cache','--backfill']), patch('builtins.print'), \
             patch('daily_archive.cutoff',return_value=datetime.fromisoformat(DAY).date()), \
             patch.object(channel_cache,'datetime',wraps=datetime) as clock, \
             patch.object(channel_cache.time,'sleep'), patch.object(channel_cache,'cache_day',side_effect=run) as producer:
            clock.now.return_value = now
            channel_cache.main()
            channel_cache.main()
        self.assertEqual([(call.args[0],call.kwargs['recheck']) for call in producer.call_args_list],
                         [('2026-11-18',False),(DAY,True),('2026-11-18',False)])

    def test_rolling_producer_only_downloads_new_tail_after_same_cutoff_reuse(self):
        import channel_source

        session = Mock()
        modules = dict(fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=Mock()),
                       p2pah_auth=SimpleNamespace(Session=lambda:session))
        start = datetime.fromisoformat(NEXT+'T02:10:00+08:00')
        prefix = delivery('1','A',DAY+' 14:03:00','3.27')
        prior_tail = delivery('2','A',NEXT+' 02:08:00','6.50')
        corrected = delivery('2','B',NEXT+' 02:08:00','9.75')
        suffix = delivery('3','A',NEXT+' 02:15:00','7.30')
        def collect():
            return channel_source.enrich(dict(period=dict(start=DAY,end=NEXT),orders=[],
                                               sources=dict(cost={}),include_cost_delivery_rows=True))
        with patch.dict(sys.modules,modules), patch.object(channel_source,'ROOT',self.root), \
             patch.object(channel_source,'SALES',self.root/'sales'), \
             patch.object(channel_source,'datetime',wraps=datetime) as clock, \
             patch.object(request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{"ready":true}')), \
             patch('channel_cost_source.collect',side_effect=[[prefix,prior_tail],[corrected,suffix]]) as native:
            clock.now.return_value=start
            first = collect()
            original = self.lookup('A')['revision']
            repeat = collect()
            self.assertEqual(native.call_count,1)
            self.assertEqual(first['cost_delivery_rows'],repeat['cost_delivery_rows'])
            clock.now.return_value=start+timedelta(minutes=15)
            next_result = collect()
        self.assertEqual(native.call_count,2)
        self.assertEqual(native.call_args_list[0].args,(session,DAY,NEXT))
        self.assertNotIn('since',native.call_args_list[0].kwargs)
        self.assertEqual(native.call_args_list[1].args,(session,NEXT,NEXT))
        self.assertEqual(native.call_args_list[1].kwargs,dict(since=NEXT+' 02:05:00',until=NEXT+' 02:24'))
        self.assertEqual(next_result['sources']['cost']['period']['since'],NEXT+' 02:05:00')
        out = self.lookup('A','B')
        self.assertEqual(out['rows'],[prefix,corrected,suffix])
        self.assertEqual(self.lookup('A',revision=original)['rows'],[prefix,prior_tail])
        self.assertTrue(index.covers_window(out['windows'],SITE,DAY+' 00:00:00',NEXT+' 02:24:59',
                                           as_of=start+timedelta(minutes=15)))


    def test_hourly_wait_preserves_fixed_cutoff_and_collects_only_verified_increment(self):
        import channel_source

        old_time = NEXT + 'T02:10:00+08:00'
        through = NEXT + ' 02:12:59'
        old = delivery('1', 'A', NEXT + ' 02:08:00', '5')
        corrected = dict(old, cost_total='9')
        self.publish([old], name='order-deliveries.json', generated=old_time, start=DAY, end=NEXT,
                     until=NEXT + ' 02:09')
        index.sync(self.root)
        session = Mock()
        flock = Mock(side_effect=[BlockingIOError(), None])
        clock = SimpleNamespace(monotonic=Mock(return_value=1), sleep=Mock())
        modules = dict(fcntl=SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=flock),
                       p2pah_auth=SimpleNamespace(Session=lambda: session))
        data = dict(period=dict(start=DAY, end=NEXT), orders=[], sources=dict(cost={'status':'partial'}))
        with patch.dict(sys.modules, modules), patch.object(channel_source, 'ROOT', self.root), \
                patch.object(channel_source, 'SALES', self.root/'sales'), \
                patch.object(channel_source, 'time', clock), \
                patch.object(channel_source, 'datetime', wraps=datetime) as dates, \
                patch.object(request, 'urlopen', return_value=io.BytesIO(b'{"ready":true}')), \
                patch('channel_cost_source.collect', return_value=[corrected]) as native:
            dates.now.return_value = datetime.fromisoformat(NEXT + 'T02:16:00+08:00')
            result = channel_source.enrich(data, required_until=through, lock_deadline=5)
        self.assertEqual(flock.call_count, 2)
        clock.sleep.assert_called_once_with(1)
        native.assert_called_once_with(session, NEXT, NEXT, since=NEXT+' 02:05:00', until=NEXT+' 02:12')
        self.assertEqual(result['sources']['cost']['period']['until'], NEXT+' 02:12')
        self.assertEqual(self.lookup('A')['rows'], [corrected])

    def test_hourly_wait_reuses_other_producers_exact_revision_and_frontend_stays_nonblocking(self):
        import channel_source

        through = NEXT + ' 02:12:59'
        now = datetime.fromisoformat(NEXT + 'T02:16:00+08:00')
        observed = delivery('1', 'A', NEXT + ' 02:08:00', '9')
        def after_other_producer(_):
            self.publish([observed], name='order-deliveries.json', generated=now.isoformat(), start=DAY,
                         end=NEXT, until=NEXT+' 02:12')
            index.sync(self.root)
        time = SimpleNamespace(monotonic=Mock(return_value=1), sleep=Mock(side_effect=after_other_producer))
        flock = Mock(side_effect=[BlockingIOError(), BlockingIOError(), None, BlockingIOError()])
        modules = dict(fcntl=SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=flock))
        def data():
            return dict(period=dict(start=DAY, end=NEXT), orders=[], sources=dict(cost={'status':'partial'}),
                        include_cost_delivery_rows=True)
        with patch.dict(sys.modules, modules), patch.object(channel_source, 'ROOT', self.root), \
                patch.object(channel_source, 'SALES', self.root/'sales'), patch.object(channel_source, 'time', time), \
                patch.object(channel_source, 'datetime', wraps=datetime) as dates, \
                patch.object(request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{"ready":true}')), \
                patch('channel_cost_source.collect') as native:
            dates.now.return_value = now
            front = channel_source.enrich(data())
            background = channel_source.enrich(data(), required_until=through, lock_deadline=5)
            expired = channel_source.enrich(data(), required_until=through, lock_deadline=1)
        self.assertIn('limitation', front['sources']['cost'])
        self.assertNotIn('refresh_reason', front['sources']['cost'])
        self.assertEqual(background['cost_delivery_rows'], [observed])
        self.assertEqual(expired['sources']['cost']['refresh_reason'], 'order_delivery_lock_wait_timeout')
        self.assertEqual(expired['sources']['cost']['status'], 'partial')
        time.sleep.assert_called_once_with(1)
        native.assert_not_called()


if __name__ == '__main__':
    unittest.main()

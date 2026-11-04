import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mmoexp_google_data.seo import daily, snapshot, store

NIGHT = dt.datetime(2026, 11, 4, 19, 20, tzinfo=dt.timezone.utc)


class Source:
    name = 'gsc'
    timezone = 'America/Los_Angeles'
    calls = 0

    def pages(self, game, day, cursor=0):
        self.calls += 1
        yield dict(rows=[dict(key='total', metrics=dict(clicks='3', impressions='10', position='4'))],
                   next_cursor=None, source_timezone='America/Los_Angeles', status='available', quality={'data_state': 'final'})


class DailySnapshot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = store.Store(self.root)
        self.source = Source()

    def run_batch(self, **kw):
        return daily.run_daily(self.store, [self.source], clock=lambda: NIGHT, **kw)

    def test_daytime_has_no_upstream_calls(self):
        result = daily.run_daily(self.store, [self.source], clock=lambda: NIGHT + dt.timedelta(hours=7))
        self.assertEqual(result['status'], 'outside_night_window')
        self.assertEqual(self.source.calls, 0)

    def test_once_per_day_and_reads_never_open_work_db(self):
        receipt = self.run_batch()
        self.assertEqual(receipt['status'], 'published')
        calls = self.source.calls
        self.assertEqual(self.run_batch()['snapshot_id'], receipt['snapshot_id'])
        self.assertEqual(self.source.calls, calls)
        before = snapshot.read(self.root, receipt['snapshot_id'], 'history', 'FC27')
        with self.store.db() as db:
            db.execute('DELETE FROM facts')
        with patch.object(store.Store, 'db', side_effect=AssertionError('work db read')):
            self.assertEqual(snapshot.read(self.root, receipt['snapshot_id'], 'history', 'FC27'), before)

    def test_ai_storage_failure_cannot_change_publication(self):
        (self.root / 'seo-ai').write_text('simulate AI volume unavailable')
        result = self.run_batch()
        self.assertEqual(result['status'], 'published')
        self.assertEqual(snapshot.current(self.root)['facts_hash'], result['facts_hash'])

    def test_failed_candidate_retains_previous_date(self):
        old = self.run_batch()
        with patch.object(snapshot, 'build', side_effect=ValueError('INVALID_CANDIDATE')):
            with self.assertRaises(ValueError):
                daily.run_daily(self.store, [self.source], clock=lambda: NIGHT + dt.timedelta(days=1))
        self.assertEqual(snapshot.current(self.root)['snapshot_id'], old['snapshot_id'])

    def test_all_sources_failed_does_not_publish_empty_success(self):
        with patch.object(self.source, 'pages', side_effect=PermissionError('upstream denied')) as call:
            result = self.run_batch()
        self.assertEqual(result['status'], 'no_usable_data')
        self.assertEqual(call.call_count,1)
        self.assertFalse((self.root / 'current.json').exists())

    def test_source_history_independent_and_calendar_holes_preserved(self):
        result = self.run_batch()
        rows = snapshot.read(self.root, result['snapshot_id'], 'history', 'D4')['rows']
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0]['source_date'], '2026-10-06')
        self.assertEqual(rows[-1]['source_date'], '2026-11-04')
        status = snapshot.read(self.root, result['snapshot_id'], 'sources', 'D4')['rows']
        self.assertTrue(all(r['source_timezone'] == 'America/Los_Angeles' for r in status))

    def test_backfill_more_than_old_request_reference_is_not_stopped(self):
        class ManyPages(Source):
            def pages(self, game, day, cursor=0):
                for n in range(cursor, 3):
                    self.calls += 1
                    yield dict(rows=[dict(key=str(n), metrics=dict(clicks='1', impressions='2', position='3'))],
                               next_cursor=n+1 if n < 2 else None, source_timezone='America/Los_Angeles',
                               status='available', quality={})
        source = ManyPages()
        result = daily.run_daily(self.store, [source], clock=lambda: NIGHT)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(source.calls, 348)

    def test_tampered_snapshot_is_rejected(self):
        result = self.run_batch()
        path = self.root / 'snapshots' / (result['snapshot_id'] + '.sqlite')
        with path.open('ab') as out:
            out.write(b'tampered')
        with self.assertRaises(ValueError):
            snapshot.read(self.root, result['snapshot_id'], 'history', 'D4')

    def test_crash_after_manifest_reconciles_pointer_without_recollection(self):
        original=snapshot.atomic_json
        def crash(path,value):
            if Path(path).name=='current.json':raise OSError('injected pointer crash')
            return original(path,value)
        with patch.object(snapshot,'atomic_json',side_effect=crash):
            with self.assertRaises(OSError):self.run_batch()
        calls=self.source.calls
        result=self.run_batch()
        self.assertEqual(snapshot.current(self.root)['snapshot_id'],result['snapshot_id'])
        self.assertEqual(self.source.calls,calls)

    def test_build_finishing_after_deadline_does_not_publish(self):
        old=self.run_batch();clock=[NIGHT+dt.timedelta(days=1)]
        original=snapshot.build
        def slow_build(*args,**kw):
            result=original(*args,**kw)
            clock[0]=dt.datetime(2026,11,5,22,30,1,tzinfo=dt.timezone.utc)
            return result
        with patch.object(snapshot,'build',side_effect=slow_build):
            result=daily.run_daily(self.store,[self.source],clock=lambda:clock[0])
        self.assertEqual(result['status'],'publication_deadline')
        self.assertEqual(snapshot.current(self.root)['snapshot_id'],old['snapshot_id'])


if __name__ == '__main__':
    unittest.main()

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from mmoexp_google_data.seo import store, contracts


class StoreTests(unittest.TestCase):
    def test_empty_refresh_preserves_last_good_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            page=dict(rows=[dict(key='total',metrics={'clicks':'3'})],next_cursor=None,source_timezone='America/Los_Angeles',status='available',quality={})
            core.ingest_page('gsc','FC27','2026-11-01',page,'2026-11-04T19:00:00+00:00')
            core.ingest_page('gsc','FC27','2026-11-01',dict(page,rows=[],status='no_rows'),'2026-11-05T19:00:00+00:00')
            with core.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT status FROM coverage').fetchone()[0],'stale')

    def test_restart_fills_recent_gaps_without_moving_initial_window_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=store.Store(tmp)
            initial=core.initial_window('2026-10-06','2026-11-04')
            context=contracts.make_daily_context(dt.datetime(2026,11,25,19,tzinfo=dt.timezone.utc))
            days={d for d,c in core.slices('gsc','D4',context)}
            self.assertIn('2026-11-06',days)
            self.assertEqual(core.initial_window(context.history_start,context.report_date),initial)


if __name__=='__main__':unittest.main()

from datetime import datetime,timezone
from pathlib import Path
import importlib.util
import tempfile
import sys
from hashlib import sha256
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('weekly_news',ROOT/'source/mmoexp_news.py')
news=importlib.util.module_from_spec(spec);spec.loader.exec_module(news)

class Weekly(unittest.TestCase):
    def test_weekdays_skip_network_model_and_writes(self):
        for day in ('2026-10-11','2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'):
            with self.subTest(day=day),patch.object(news,'read_snapshot',return_value={'status':'partial','documents':[{'title':'cached'}]}) as read,patch.object(news,'atomic') as write:
                fetch=Mock(side_effect=AssertionError('no network'));model=Mock(side_effect=AssertionError('no model'))
                result=news.refresh(datetime.fromisoformat(day+'T00:05:00+08:00'),fetcher=fetch,translator=model)
                self.assertEqual(result['refresh_skipped'],'weekly_schedule');self.assertEqual(result['documents'][0]['title'],'cached')
                fetch.assert_not_called();model.assert_not_called();write.assert_not_called();read.assert_called_once()

    def test_friday_utc_is_saturday_in_beijing_and_remains_weekly_fresh(self):
        at=datetime(2026,10,16,16,5,tzinfo=timezone.utc)
        raw=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        with tempfile.TemporaryDirectory() as tmp:
            fetch=Mock(return_value=raw);model=Mock()
            result=news.refresh(at,root=Path(tmp),fetcher=fetch,translator=model)
            fetch.assert_called_once();model.assert_not_called()
            self.assertEqual(result['stale_after'],'2026-10-24T07:00:00+08:00')
            self.assertTrue((Path(tmp)/'seo-news.status.json').is_file())

    def test_saturday_utc_after_beijing_midnight_sunday_skips(self):
        with patch.object(news,'read_snapshot',return_value={'status':'not_available','documents':[]}),patch.object(news,'collect') as collect:
            result=news.refresh(datetime(2026,10,17,16,5,tzinfo=timezone.utc))
            self.assertEqual(result['refresh_skipped'],'weekly_schedule');collect.assert_not_called()

    def test_saturday_failure_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot=Path(tmp)/'seo-news.json';snapshot.write_bytes(b'last successful snapshot')
            result=news.refresh(datetime.fromisoformat('2026-10-17T00:05:00+08:00'),root=Path(tmp),fetcher=Mock(side_effect=OSError('403')))
            self.assertEqual(result['status'],'unavailable');self.assertEqual(snapshot.read_bytes(),b'last successful snapshot')

    def test_release_stays_two_existing_modules(self):
        spec=importlib.util.spec_from_file_location('weekly_release',ROOT/'release_backend.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        self.assertEqual(release.TARGETS,{'source/mmoexp_news.py':'/opt/fs-boss-workspaces/backend/mmoexp_news.py','source/game_intelligence.py':'/opt/fs-boss-workspaces/backend/game_intelligence.py'})
        self.assertEqual(release.NEWS_BASELINE,'331eb022a1bff3f2913011072802ecdd6bd67cd92f1b886e1a57b288325e313a')

    def test_official_snapshot_lasts_until_next_saturday_deadline(self):
        spec=importlib.util.spec_from_file_location('weekly_official',ROOT/'source/game_intelligence.py')
        official=importlib.util.module_from_spec(spec);spec.loader.exec_module(official)
        batch={'collected_at':'2026-10-17T00:10:00+08:00','documents':[{'document_id':'one'}],'coverage':{},'source_status':[]}
        value=official.build_snapshot(batch,{'status':'succeeded','events':[],'model':'existing','receipt':'one','tokens':0})
        self.assertEqual(value['stale_after'],'2026-10-24T07:00:00+08:00')

    def test_existing_timer_change_is_exact_and_cas_protected(self):
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location('weekly_timer',ROOT/'release_timer.py')
        timer=importlib.util.module_from_spec(spec);spec.loader.exec_module(timer)
        raw=b'[Unit]\nDescription=FS game monitor daily at 00:05 Shanghai\n\n[Timer]\nOnCalendar=*-*-* 00:05:00\nPersistent=false\nUnit=fs-boss-game-monitor.service\n\n[Install]\nWantedBy=timers.target\n'
        with patch.object(timer,'BEFORE',sha256(raw).hexdigest()):
            changed=timer.candidate(raw)
            self.assertIn(b'OnCalendar=Sat *-*-* 00:05:00',changed)
            self.assertIn(b'Persistent=false',changed);self.assertIn(b'Unit=fs-boss-game-monitor.service',changed)
            with self.assertRaises(ValueError):timer.candidate(raw+b'changed')

if __name__=='__main__':unittest.main()

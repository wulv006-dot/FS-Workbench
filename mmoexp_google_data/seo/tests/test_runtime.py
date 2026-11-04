import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mmoexp_google_data.seo import runtime, store
from test_daily_snapshot import NIGHT


class Runtime(unittest.TestCase):
    def test_unconfigured_upstreams_report_gap_without_paid_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=runtime.run(dict(data_root=tmp,sources={},resource_policy=None),clock=lambda:NIGHT)
        self.assertEqual(result['status'],'resource_baseline_missing')
        self.assertEqual(result['missing_sources'],['gsc','ga4','orders'])

    def test_daytime_does_not_load_credentials_or_initialize_store(self):
        with patch.object(store,'Store',side_effect=AssertionError('daytime initialized store')):
            self.assertEqual(runtime.run({},clock=lambda:NIGHT+dt.timedelta(hours=8))['status'],'outside_night_window')

    def test_missing_work_database_with_existing_snapshot_needs_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'current.json').write_text('{}')
            with self.assertRaises(ValueError):store.Store(tmp)


if __name__=='__main__':unittest.main()

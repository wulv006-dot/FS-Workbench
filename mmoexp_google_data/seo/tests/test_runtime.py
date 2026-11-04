import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mmoexp_google_data.seo import runtime, store
from test_daily_snapshot import NIGHT, Source


class Runtime(unittest.TestCase):
    def test_unconfigured_upstreams_report_gap_without_paid_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=runtime.run(dict(data_root=tmp,sources={},resource_policy=None),clock=lambda:NIGHT)
        self.assertEqual(result['status'],'resource_baseline_missing')
        self.assertEqual(result['missing_sources'],['gsc','ga4','admin'])

    def test_daytime_does_not_load_credentials_or_initialize_store(self):
        with patch.object(store,'Store',side_effect=AssertionError('daytime initialized store')):
            self.assertEqual(runtime.run({},clock=lambda:NIGHT+dt.timedelta(hours=8))['status'],'outside_night_window')

    def test_missing_work_database_with_existing_snapshot_needs_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'current.json').write_text('{}')
            with self.assertRaises(ValueError):store.Store(tmp)

    def test_unavailable_ai_storage_cannot_block_real_base_entry(self):
        from mmoexp_google_data.seo import retention
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'core';work=store.Store(root)
            page=dict(rows=[dict(key='day',metrics=dict(clicks='3',impressions='10',position='4'))],next_cursor=None,source_timezone='America/Los_Angeles',status='available',quality={})
            work.ingest_page('gsc','FC27','2026-11-02',page,NIGHT.isoformat())
            ai=Path(tmp)/'ai';ai.mkdir();(ai/'ai.db').write_bytes(b'broken report database')
            gb=1024**3
            config=dict(data_root=str(root),ai_root=str(ai),sources={'gsc':dict(resource='sc-domain:mmoexp.com',timezone='America/Los_Angeles')},resource_policy=dict(warning_bytes=gb,operating_ceiling_bytes=2*gb,emergency_stop_bytes=3*gb,host_reserve_bytes=1024,measured_basis='isolated fixture'),memory_policy={'fixture':True},temporary_reserve_bytes=4096,publication_finish_seconds=0,http=dict(response_emergency_bytes=1048576,connect_seconds=1,idle_seconds=1))
            def measured(path):
                if Path(path)==ai:raise OSError('isolated AI storage unavailable')
                return retention.footprint(path)
            with patch.object(runtime,'GoogleSource',return_value=Source()),patch.object(runtime,'footprint',side_effect=measured),patch.object(runtime,'memory_admission',return_value=dict(allowed=True,state='normal',rss_bytes=1024)):
                receipt=runtime.run(config,clock=lambda:NIGHT)
            self.assertEqual(receipt['status'],'published')
            self.assertEqual(receipt['maintenance']['ai_cleanup']['status'],'failed')
            self.assertEqual(receipt['resource_states']['ai_storage']['status'],'unavailable')


if __name__=='__main__':unittest.main()

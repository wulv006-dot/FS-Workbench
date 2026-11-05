import datetime as dt
import tempfile
import unittest
from unittest.mock import patch

from mmoexp_google_data.seo import api,ai_policy,daily,snapshot,store
from mmoexp_google_data.seo.retention import backup_verified,cleanup_owned_data
from test_daily_snapshot import NIGHT,Source

RUN='manual-seo-20261105T085500Z'


class ManualSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.core=store.Store(self.temp.name);self.source=Source()
        self.base=daily.run_daily(self.core,[self.source],clock=lambda:NIGHT)
        self.original=snapshot.digest_file(self.core.root/'snapshots/seo-2026-11-05.sqlite')
        self.history=snapshot.read(self.core.root,self.base['snapshot_id'],'history','FC27')['rows']
        self.page=dict(rows=[dict(key='query',keyword='fc27 coins',country='US',brand='MMOEXP',rank=3,status='found',observed_at=(NIGHT+dt.timedelta(hours=12)).isoformat())],next_cursor=None,source_timezone='Asia/Shanghai',status='available',quality=dict(sample_kind='point_observation',manual_run_id=RUN,manual_daytime_exception=True))
        self.core.ingest_page('serp','FC27','2026-11-05',self.page,(NIGHT+dt.timedelta(hours=12)).isoformat())

    def publish(self):
        candidate,meta=snapshot.build_manual(self.core,self.base['snapshot_id'],RUN)
        return snapshot.publish_once(self.core.root,candidate,meta)

    def test_manual_result_is_visible_with_original_business_rows_and_dates(self):
        meta=self.publish()
        self.assertRegex(meta['snapshot_id'],r'^seo-2026-11-05-manual-[a-f0-9]{12}$')
        self.assertEqual(meta['report_date'],'2026-11-04')
        self.assertEqual(meta['observation_date'],'2026-11-05')
        self.assertEqual(meta['base_snapshot_id'],self.base['snapshot_id'])
        self.assertNotEqual(meta['facts_hash'],self.base['facts_hash'])
        self.assertEqual(snapshot.digest_file(self.core.root/'snapshots/seo-2026-11-05.sqlite'),self.original)
        actor=ai_policy.Actor('viewer',('FC27',),False,False)
        service=api.Service(self.core.root,None)
        with patch.object(store.Store,'db',side_effect=AssertionError('published reads must not use core')):
            for kind in ['history','markets']:
                status,result=service.handle('GET','/api/seo/v1/snapshots/'+meta['snapshot_id']+'/'+kind,{'game':'FC27'},actor)
                self.assertEqual(status,200);self.assertEqual(result['facts_hash'],meta['facts_hash'])
                if kind=='history':self.assertEqual(result['rows'],self.history)
                else:self.assertEqual(result['rows'][0]['source_date'],'2026-11-05')
            self.assertIn(meta['snapshot_id'],list(service.export(meta['snapshot_id'],'FC27',actor))[1])
            from mmoexp_google_data.seo.web import Application,Csv
            app=Application(self.core.root,self.core.root/'control',authenticate=lambda *args:(200,'viewer'))
            status,export=app.handle('GET','/dashboard/analytics/seo/api/v1/snapshots/'+meta['snapshot_id']+'/export.csv?game=FC27',{},b'')
            self.assertEqual(status,200);self.assertIsInstance(export,Csv)
            self.assertIn(meta['snapshot_id'],export.text)

    def test_unknown_run_or_wrong_observation_date_cannot_publish(self):
        with self.assertRaises(ValueError):snapshot.build_manual(self.core,self.base['snapshot_id'],'manual-seo-20261105T000000Z')
        bad=dict(self.page,rows=[dict(self.page['rows'][0],observed_at='2026-11-04T12:00:00+08:00')])
        self.core.ingest_page('serp','FC27','2026-11-05',bad,NIGHT.isoformat())
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(snapshot.current(self.core.root),{k:v for k,v in self.base.items() if k!='status'})

    def test_same_day_retry_keeps_manual_version_and_backup_restores_it(self):
        meta=self.publish();calls=self.source.calls
        self.assertEqual(daily.run_daily(self.core,[self.source],clock=lambda:NIGHT)['snapshot_id'],meta['snapshot_id'])
        self.assertEqual(self.source.calls,calls)
        self.assertTrue(backup_verified(self.core)['restore_checked'])
        cleanup_owned_data(self.core,dt.date(2026,11,5))
        self.assertEqual(snapshot.current(self.core.root),meta)
        self.assertEqual(snapshot.read(self.core.root,meta['snapshot_id'],'history','FC27')['rows'],self.history)

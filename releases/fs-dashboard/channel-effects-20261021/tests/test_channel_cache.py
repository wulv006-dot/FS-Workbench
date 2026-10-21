import json
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import channel_cache as cache
from channel_effects import ChannelService, TZ
import test_channel_effects as fixtures

FCNTL = SimpleNamespace(flock=lambda *args:None, LOCK_EX=1, LOCK_NB=2)


class Archive(unittest.TestCase):
    def fixture(self):
        case=fixtures.Effects();case.setUp();data=case.data()
        data['sources'].update(cost={'source':'fixture'},customer={'status':'complete'})
        return data

    def test_partition_merge_empty_day_and_old_capture_cannot_replace_new(self):
        data=self.fixture();data['period']['start']='2026-10-19'
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'fcntl':FCNTL}):
            root=Path(folder);cache.store_days(data,root)
            merged=cache.compose(data['period'],root)
            self.assertEqual(merged['orders'],data['orders'])
            self.assertEqual(merged['sources']['cache']['days'],2)
            self.assertEqual(cache.compose({'start':'2026-10-19','end':'2026-10-19'},root)['orders'],[])
            old=deepcopy(data);old['generatedAt']='2026-10-01T00:00:00+08:00';old['orders']=[]
            cache.store_days(old,root)
            self.assertEqual(cache.compose(data['period'],root)['orders'],data['orders'])
            self.assertIsNone(cache.compose({'start':'2026-10-18','end':'2026-10-20'},root))

    def test_partial_or_out_of_range_never_replaces_complete_day(self):
        data=self.fixture()
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'fcntl':FCNTL}):
            root=Path(folder);cache.store_days(data,root)
            before=(root/'days/2026-10-20.json').read_bytes()
            bad=deepcopy(data);bad['sources']['coupons']['status']='partial'
            with self.assertRaises(ValueError):cache.store_days(bad,root)
            bad=deepcopy(data);bad['orders'][0]['day']='2026-10-19'
            with self.assertRaises(ValueError):cache.store_days(bad,root)
            self.assertEqual((root/'days/2026-10-20.json').read_bytes(),before)

    def test_cost_days_deduplicate_latest_capture_and_keep_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);row=dict(delivery_id='1',genre=1,source='www.mmoexp.com',sn='A',sale_total='70',cost_total='35')
            for name,stamp,cost in [('order-deliveries.json','2026-10-20T00:00:00+08:00','35'),('delivery-days/2026-10-20.json','2026-10-21T00:00:00+08:00','40')]:
                cache.atomic(root/name,dict(contract='channel-order-deliveries-v1',complete=True,generatedAt=stamp,rows=[dict(row,cost_total=cost)]))
            data=cache.apply_delivery_cache(self.fixture(),root)
            self.assertEqual(data['orders'][0]['costCny'],40)
            self.assertEqual(data['orders'][0]['deliveryRows'],1)
            self.assertIsNone(data['orders'][1]['costCny'])
            self.assertIn('SCM',data['sources']['cost']['limitation'])

    def test_cached_closed_period_returns_without_upstream_job_and_refresh_still_works(self):
        data=self.fixture()
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'fcntl':FCNTL}):
            root=Path(folder);cache.store_days(data,root)
            service=ChannelService(root,lambda user:True)
            service.pool.shutdown();service.pool=Mock()
            with patch('channel_source.apply_customer_types',side_effect=lambda d:d),patch('channel_source.apply_cost_overrides',side_effect=lambda d:d):
                params={k:[v] for k,v in data['period'].items()}
                code,result=service.get(params,'admin')
                self.assertEqual(code,200);self.assertFalse(result['refreshing']);self.assertFalse(result['stale'])
                service.pool.submit.assert_not_called()
                code,result=service.get(dict(params,refresh=['1']),'admin')
                self.assertEqual(code,200);self.assertTrue(result['refreshing'])
                service.pool.submit.assert_called_once()

    def test_nightly_defaults_to_shanghai_yesterday_and_idle_window_does_no_daytime_read(self):
        current=datetime(2026,10,21,20,0,tzinfo=TZ)
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}),patch.object(cache,'ROOT',Path(folder)),patch.object(cache,'datetime') as clock,patch.object(cache,'cache_day',return_value={'status':'complete'}) as collect:
            clock.now.return_value=current
            with patch.object(sys,'argv',['cache']):cache.main()
            collect.assert_called_once_with('2026-10-20')
            collect.reset_mock()
            with patch.object(sys,'argv',['cache','--backfill']):cache.main()
            collect.assert_not_called()

    def test_old_archive_returns_immediately_and_preserves_automatic_refresh(self):
        self.assert_stale_archive(False)

    def test_busy_sources_still_return_existing_archive_then_retry_refresh(self):
        self.assert_stale_archive(True)

    def assert_stale_archive(self, busy):
        data=self.fixture();data['generatedAt']='2026-10-21T00:00:00+08:00'
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'fcntl':FCNTL}):
            root=Path(folder);cache.store_days(data,root)
            service=ChannelService(root,lambda user:True)
            service.pool.shutdown();service.pool=Mock()
            if busy:service.jobs.update(other='pending',another='cost_pending')
            with patch('channel_source.apply_customer_types',side_effect=lambda d:d),patch('channel_source.apply_cost_overrides',side_effect=lambda d:d):
                params={k:[v] for k,v in data['period'].items()}
                code,result=service.get(params,'admin')
                self.assertEqual(code,200);self.assertEqual(result['summary']['orders'],3)
                self.assertTrue(result['stale']);self.assertTrue(result['refreshing'])
                if busy:
                    service.pool.submit.assert_not_called();service.jobs.clear()
                    code,result=service.get(params,'admin')
                service.pool.submit.assert_called_once()

    def test_scheduled_busy_does_not_claim_success_and_can_retry(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}),patch.object(cache,'ROOT',Path(folder)),patch.object(cache,'cache_day',side_effect=BlockingIOError):
            with patch.object(sys,'argv',['cache']):
                with self.assertRaises(SystemExit) as error:cache.main()
            self.assertEqual(error.exception.code,75)
            self.assertEqual(json.loads((Path(folder)/'daily-status.json').read_text())['status'],'deferred')


if __name__=='__main__':unittest.main()

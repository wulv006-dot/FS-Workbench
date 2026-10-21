import json
import os
import sys
import tempfile
import unittest
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
for name in ('fs_daily_archive_20261021','daily-archive-20261021'):
    candidate=Path(__file__).resolve().parents[2]/name/'source'
    if candidate.is_dir():sys.path.insert(0,str(candidate))
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

    def test_old_income_schema_is_recollected_before_new_method(self):
        data=self.fixture();old=deepcopy(data)
        for row in old['orders']:row.pop('adminSaleCny')
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}),patch('channel_source.collect',return_value=data) as source:
            root=Path(folder);cache.store_days(old,root)
            result=cache.collect_period(data['period'],root)
            source.assert_called_once_with(data['period'])
            self.assertTrue(all('adminSaleCny' in row for row in result['orders']))
    def test_open_status_rechecks_admin_but_final_history_reuses_archive(self):
        data=self.fixture()
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}),patch('channel_source.collect',return_value=data) as source:
            root=Path(folder);cache.store_days(data,root)
            cache.collect_period(data['period'],root);source.assert_not_called()
            data['orders'][0]['status']='发货中';data['generatedAt']=datetime.now(TZ).isoformat()
            cache.store_days(data,root)
            cache.collect_period(data['period'],root);source.assert_called_once_with(data['period'])

    def test_partially_cached_period_only_reads_missing_days(self):
        data=self.fixture();empty=deepcopy(data);empty.update(period=dict(start='2026-10-19',end='2026-10-19'),orders=[])
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}),patch('channel_source.collect',return_value=empty) as source:
            root=Path(folder);cache.store_days(data,root)
            result=cache.collect_period(dict(start='2026-10-19',end='2026-10-20'),root)
            source.assert_called_once_with(dict(start='2026-10-19',end='2026-10-19'))
            self.assertEqual(result['orders'],data['orders'])
            self.assertEqual(result['sources']['cache']['days'],1)
            source.reset_mock();cache.collect_period(result['period'],root,force=True)
            source.assert_called_once_with(result['period'])

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

    def test_exact_order_supplement_merges_without_double_count_and_is_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);row=dict(delivery_id='1',genre=1,source='www.mmoexp.com',sn='A',sale_total='70',cost_total='35')
            value=dict(contract='channel-order-deliveries-v1',complete=True,generatedAt='2026-10-21T00:00:00+08:00',rows=[row])
            cache.atomic(root/'order-deliveries.json',value)
            cache.atomic(root/'order-supplements.json',dict(value,scope='exact_orders',orderNos=['A']))
            original_stamp=(root/'order-supplements.json').stat().st_mtime_ns
            result=cache.apply_delivery_cache(self.fixture(),root)
            self.assertEqual((result['orders'][0]['costCny'],result['orders'][0]['deliveryRows']),(35,1))
            cache.atomic(root/'order-supplements.json',dict(value,scope='exact_orders',orderNos=['B']))
            os.utime(root/'order-supplements.json',ns=(original_stamp,original_stamp))
            with self.assertRaisesRegex(ValueError,'supplement_order_scope'):cache.apply_delivery_cache(self.fixture(),root)

    def test_new_complete_day_removes_stale_members_but_retains_next_day(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            row=dict(delivery_id='1',genre=1,source='www.mmoexp.com',sn='A',sale_total='70',cost_total='35',trade_at='2026-10-20 21:00:00')
            old=dict(contract='channel-order-deliveries-v1',complete=True,generatedAt='2026-10-21T00:43:00+08:00',period=dict(start='2026-10-20',end='2026-10-21',until='2026-10-21 00:32'),rows=[row,dict(row,delivery_id='2'),dict(row,delivery_id='3',sn='B',trade_at='2026-10-21 00:20:00')])
            cache.atomic(root/'order-deliveries.json',old)
            cache.atomic(root/'delivery-days/2026-10-20.json',dict(old,generatedAt='2026-10-21T00:48:00+08:00',period=dict(start='2026-10-20',end='2026-10-20'),rows=[dict(row,delivery_id='2')]))
            data=cache.apply_delivery_cache(self.fixture(),root)
            self.assertEqual((data['orders'][0]['costCny'],data['orders'][0]['deliveryRows']),(35,1))
            self.assertEqual(data['orders'][1]['costCny'],35)
            cache.atomic(root/'delivery-days/2026-10-20.json',dict(old,generatedAt='2026-10-21T00:49:00+08:00',period=dict(start='2026-10-20',end='2026-10-20'),rows=[]))
            self.assertIsNone(cache.apply_delivery_cache(data,root)['orders'][0]['costCny'])

    def test_fresh_window_replaces_members_and_keeps_outside_records(self):
        import io
        import channel_source
        row=dict(delivery_id='1',genre=1,source='www.mmoexp.com',sn='A',sale_total='70',cost_total='35',trade_at='2026-10-20 21:00:00')
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'fcntl':FCNTL,'p2pah_auth':SimpleNamespace(Session=lambda:SimpleNamespace(close=lambda:None))}):
            root=Path(folder)
            old=dict(contract='channel-order-deliveries-v1',complete=True,generatedAt='2026-10-21T00:43:00+08:00',period=dict(start='2026-10-19',end='2026-10-20'),rows=[row,dict(row,delivery_id='2',trade_at='2026-10-19 23:59:59')])
            cache.atomic(root/'order-deliveries.json',old)
            fresh=[dict(row,delivery_id='3',trade_at='2026-10-21 00:40:00')]
            data=self.fixture()
            with patch.object(channel_source,'ROOT',root),patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ready":true}')),patch('channel_cost_source.collect',return_value=fresh),patch.object(channel_source,'load_costs',return_value=(fresh,{})):
                channel_source.enrich(data,force=True)
            saved=json.loads((root/'order-deliveries.json').read_text())
            self.assertEqual({r['delivery_id'] for r in saved['rows']},{'2','3'})
            before=(root/'order-deliveries.json').read_bytes()
            with patch.object(channel_source,'ROOT',root),patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ready":true}')),patch('channel_cost_source.collect',side_effect=ValueError('incomplete')):
                with self.assertRaisesRegex(ValueError,'incomplete'):channel_source.enrich(data,force=True)
            self.assertEqual((root/'order-deliveries.json').read_bytes(),before)

    def test_incomplete_day_cannot_remove_previous_members(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cache.atomic(root/'delivery-days/2026-10-20.json',dict(contract='channel-order-deliveries-v1',complete=False,generatedAt='2026-10-21T00:49:00+08:00',period=dict(start='2026-10-20',end='2026-10-20'),rows=[]))
            with self.assertRaisesRegex(ValueError,'invalid_delivery_day_cache'):
                cache.apply_delivery_cache(self.fixture(),root)

    def test_delivery_closed_day_includes_final_minute_and_rejects_outside_window(self):
        from channel_cost_source import collect
        def page(stamp):
            cells=['','42','订单发货','www.mmoexp.com','A',stamp,'Game','1','0','35','35','70','50','','','','','','']
            return '<table class="table-list"><thead><tr><th>商户订单号</th></tr></thead><tbody><tr>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr></tbody></table>'
        session=SimpleNamespace(get_order=Mock(return_value=(200,page('26-10-13 23:59:35'))))
        result=collect(session,'2026-10-13','2026-10-13')
        self.assertEqual(result[0]['trade_at'],'2026-10-13 23:59:35')
        self.assertEqual(session.get_order.call_args.kwargs['end'],'2026-10-13 23:59:59')
        collect(session,'2026-10-13','2026-10-13',since='2026-10-13 23:59',until='2026-10-13 23:59')
        self.assertEqual(session.get_order.call_args.kwargs['start'],'2026-10-13 23:59:00')
        self.assertEqual(session.get_order.call_args.kwargs['end'],'2026-10-13 23:59:59')
        session.get_order.return_value=(200,page('26-10-14 00:00:00'))
        with self.assertRaisesRegex(ValueError,'delivery_filter_not_honored'):collect(session,'2026-10-13','2026-10-13')
        with self.assertRaisesRegex(ValueError,'invalid_delivery_window'):collect(session,'2026-10-13','2026-10-13',until='2026-10-14 00:00')

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

    def test_late_cost_refresh_reuses_complete_order_archive(self):
        data=self.fixture();data.update(generatedAt='2026-10-21T00:00:00+08:00',deliveryDayComplete=True)
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}):
            root=Path(folder);cache.store_days(data,root)
            service=ChannelService(root,lambda user:True)
            with patch('channel_source.collect',side_effect=AssertionError('complete orders must be reused')),patch('channel_source.enrich',side_effect=lambda value,force=False:value) as enrich:
                service.capture(data['period'],'late',root/'late.json',cost_only=True)
            self.assertEqual(service.jobs['late'],'available');enrich.assert_called_once()
            self.assertEqual(json.loads((root/'late.json').read_text())['orders'],data['orders'])
            service.pool.shutdown()

    def test_complete_history_still_refreshes_late_costs_after_ten_minutes(self):
        self.assert_stale_archive(False, complete=True)

    def test_busy_sources_still_return_existing_archive_then_retry_refresh(self):
        self.assert_stale_archive(True)

    def assert_stale_archive(self, busy, complete=False):
        data=self.fixture();data['generatedAt']='2026-10-21T00:00:00+08:00';data['deliveryDayComplete']=complete
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
                self.assertEqual(service.pool.submit.call_args.kwargs['cost_only'],complete)

    def test_scheduled_busy_does_not_claim_success_and_can_retry(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fcntl':FCNTL}),patch.object(cache,'ROOT',Path(folder)),patch.object(cache,'cache_day',side_effect=BlockingIOError):
            with patch.object(sys,'argv',['cache']):
                with self.assertRaises(SystemExit) as error:cache.main()
            self.assertEqual(error.exception.code,75)
            self.assertEqual(json.loads((Path(folder)/'daily-status.json').read_text())['status'],'deferred')


if __name__=='__main__':unittest.main()

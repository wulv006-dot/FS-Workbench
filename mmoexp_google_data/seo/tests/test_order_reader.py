import datetime as dt
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mmoexp_google_data.seo import daily, runtime, store, snapshot
from mmoexp_google_data.seo.order_reader import NativeOrderFactsReader
from mmoexp_google_data.seo.order_source import OrderSource
from test_order_source import facts, DAY, NIGHT
import test_order_source as order_fixture


class NativeReaderTests(unittest.TestCase):
    def test_original_batch_collects_other_sources_before_waiting_for_shared_report_day(self):
        from mmoexp_google_data.seo.contracts import BUSINESS_TZ, GAMES
        from test_daily_snapshot import Source
        timeline=[]
        clock_value=dt.datetime.fromisoformat('2026-11-05T03:20:00+08:00')
        day='2026-11-04'
        historical='2026-11-03'
        target=clock_value.replace(hour=4,minute=18)
        def readiness(when):
            self.assertEqual(when,day)
            return clock_value>=target
        def wait(seconds):
            nonlocal clock_value
            timeline.append(('wait',seconds))
            clock_value=target
        class Early(Source):
            name='admin'
            timezone='Asia/Shanghai'
            def pages(self, scope, when, cursor=0):
                nonlocal clock_value
                timeline.append(('admin',scope,when))
                if when==historical:
                    clock_value=clock_value.replace(hour=6,minute=20)
                for page in super().pages(scope,when,cursor):
                    yield dict(page,source_timezone=self.timezone)
        def collect(scopes):
            timeline.append(('orders',clock_value.astimezone(BUSINESS_TZ).strftime('%H:%M')))
            return [facts(game,day) for game in GAMES]
        reader=NativeOrderFactsReader(clock=lambda:clock_value,collect_many=collect,readiness=readiness,wait=wait)
        with tempfile.TemporaryDirectory() as tmp, patch.object(store.Store,'slices',return_value=[(day,0),(historical,0)]):
            root=Path(tmp); order_source=OrderSource(reader)
            receipt=daily.run_daily(store.Store(root),[Early(),order_source],clock=lambda:clock_value,finish_margin_seconds=600)
            self.assertEqual(receipt['status'],'published')
            self.assertEqual(timeline,[*(('admin',g,day) for g in GAMES),('wait',30),
                                       ('orders','04:18'),('admin','FC27',historical)])
            persisted=snapshot.read(root,receipt['snapshot_id'],'history','FC27')
            self.assertEqual(persisted['rows'][-1]['metrics']['orders']['paid_orders'],1)
            self.assertEqual(daily.run_daily(store.Store(root),[Early(),order_source],clock=lambda:clock_value)['snapshot_id'],
                             receipt['snapshot_id'])

    def test_wait_stops_at_0505_when_the_report_day_has_not_arrived(self):
        now=dt.datetime.fromisoformat('2026-11-05T05:04:43+08:00')
        def wait(seconds):
            nonlocal now
            now += dt.timedelta(seconds=seconds)
        check=Mock(return_value=False)
        read=NativeOrderFactsReader(clock=lambda:now,readiness=check,wait=wait)
        read.wait_for_day('2026-11-04',lambda:True)
        self.assertEqual(now.time(),dt.time(5,5))
        self.assertEqual(check.call_count,2)

    def test_busy_shared_probe_leaves_original_read_to_report_source_failure(self):
        busy=sqlite3.OperationalError('private path or upstream detail')
        read=NativeOrderFactsReader(clock=lambda:NIGHT,readiness=Mock(side_effect=busy),
                                    collect_many=Mock(side_effect=busy),wait=Mock())
        self.assertFalse(read.defer_day(DAY))
        read.wait_for_day(DAY,lambda:True)
        read.wait.assert_not_called()
        with self.assertRaisesRegex(ValueError,'ORDER_FACTS_SHARED_DATABASE_UNAVAILABLE') as error:
            read('FC27',DAY)
        self.assertNotIn('private path',str(error.exception))

    def test_real_shared_projection_through_reader_to_nightly_snapshot(self):
        root = Path(__file__).resolve().parents[3]
        paths = [str(root/'releases/fs-dashboard/dashboard-refresh-20261025/source'),
                 str(root/'releases/fs-dashboard/cache-archive-retention-20261025/source')]
        paths_patch = patch.object(sys,'path',paths+sys.path)
        paths_patch.start()
        self.addCleanup(paths_patch.stop)
        from order_facts_runtime import collect_many
        native = dict(id=1,site_id=266,site={'full_title':'www.mmoexp.com'},gid=1327,
            order_no='private-native-order',paytime=DAY+' 10:00:00',pay_status='1',
            amount_usd_format='50',amount_rmb_format='350',status_format='completed')
        def reader(scope, **kwargs):
            return dict(status='available',rows=[native] if scope['gid']=='1327' else [],dataset=None,identity_catalog=None,
                        coverage=dict(admin_complete=True,admin_date_basis='paytime',admin_snapshot=True,
                                      source_revision='shared-r1',publication_id='uw_fixed'))
        reader = Mock(side_effect=reader)
        with tempfile.TemporaryDirectory() as tmp:
            def collect(scopes):
                return collect_many(scopes,reader=reader,db=Path(tmp)/'absent.db',costs=Path(tmp)/'absent.json')
            read = NativeOrderFactsReader(clock=lambda:NIGHT,collect_many=collect)
            config = order_fixture.OrderSourceTests().config(str(Path(tmp)/'seo'))
            with patch.object(runtime,'memory_admission',return_value=dict(allowed=True,state='normal',rss_bytes=1024)), patch.object(store.Store,'slices',return_value=[(DAY,0)]):
                result=runtime.run(config,clock=lambda:NIGHT,order_reader=read)
            self.assertEqual(result['status'],'published')
            self.assertEqual(result['upstream_requests'],0)
            self.assertEqual(reader.call_count,4)
            self.assertEqual([call.kwargs['publication_id'] for call in reader.call_args_list],[None]+['uw_fixed']*3)
            data=snapshot.read(Path(config['data_root']),result['snapshot_id'],'history','FC27')
            row=next(r for r in data['rows'] if r['source_date']==DAY)
            self.assertEqual(row['metrics']['orders']['paid_orders'],1)
            self.assertIsNone(row['metrics']['orders']['seo_orders'])
            self.assertNotIn('private-native-order',str(data))
            self.assertFalse((Path(tmp)/'absent.db').exists())

    def test_four_games_share_one_local_batch_and_make_no_upstream_requests(self):
        def collect(scopes):
            return [facts(scope,scopes[0]['start']) for scope in ('FC27','D4','AION2','WOW_FOREVER')]
        collect = Mock(side_effect=collect)
        read = NativeOrderFactsReader(clock=lambda:NIGHT,collect_many=collect)
        for scope in ('FC27','D4','AION2','WOW_FOREVER'):
            result = next(OrderSource(read).pages(scope,DAY))
            self.assertEqual(result['rows'][0]['metrics']['revenue_usd'],'50')
        collect.assert_called_once()
        read('FC27','2026-11-03')
        self.assertEqual(collect.call_count,2)
        self.assertEqual(read.day,'2026-11-03')

    def test_daytime_and_unended_date_never_use_cached_or_native_data(self):
        collect = Mock()
        for now,day,code in [(NIGHT+dt.timedelta(hours=8),DAY,'NIGHT_DEADLINE'),(NIGHT,'2026-11-05','SOURCE_DAY_NOT_ENDED')]:
            read=NativeOrderFactsReader(clock=lambda:now,collect_many=collect)
            with self.assertRaisesRegex(ValueError,code):read('FC27',day)
        collect.assert_not_called()

    def test_missing_installed_module_is_explicit_source_failure(self):
        read=NativeOrderFactsReader(clock=lambda:NIGHT)
        with patch.dict(sys.modules,{'order_facts_runtime':None}):
            with self.assertRaisesRegex(ValueError,'ORDER_FACTS_READER_NOT_INSTALLED') as error:
                read('FC27',DAY)
        self.assertTrue(error.exception.stop_source)
        self.assertIsNone(read.day)

    def test_partial_batch_never_populates_cache(self):
        read=NativeOrderFactsReader(clock=lambda:NIGHT,collect_many=Mock(return_value=[]))
        with self.assertRaisesRegex(ValueError,'BATCH_INCOMPLETE'):read('FC27',DAY)
        self.assertIsNone(read.day);self.assertEqual(read.values,{})

    def test_cli_binds_reader_only_when_orders_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'config.json'
            for enabled in (True,False):
                config.write_text(json.dumps({'sources':{'orders':{'enabled':enabled}}}))
                with patch.object(sys,'argv',['seo','--config',str(config)]), patch.object(runtime,'run',return_value={'status':'published'}) as run, patch('builtins.print'):
                    self.assertEqual(runtime.main(),0)
                reader=run.call_args.kwargs['order_reader']
                self.assertEqual(isinstance(reader,NativeOrderFactsReader),enabled)


if __name__=='__main__':unittest.main()

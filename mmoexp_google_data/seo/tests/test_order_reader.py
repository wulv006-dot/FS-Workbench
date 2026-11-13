import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mmoexp_google_data.seo import runtime, store, snapshot
from mmoexp_google_data.seo.order_reader import NativeOrderFactsReader
from mmoexp_google_data.seo.order_source import OrderSource
from test_order_source import facts, DAY, NIGHT
import test_order_source as order_fixture


class NativeReaderTests(unittest.TestCase):
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
        request = Mock(return_value=(200,json.dumps({'code':1,'data':{'list':[native],'total':1}}).encode()))
        with tempfile.TemporaryDirectory() as tmp:
            def collect(scopes, request):
                return collect_many(scopes,request=request,db=Path(tmp)/'absent.db',
                    costs=Path(tmp)/'absent.json',dataset_reader=Mock())
            read = NativeOrderFactsReader(clock=lambda:NIGHT,collect_many=collect,request=request)
            config = order_fixture.OrderSourceTests().config(str(Path(tmp)/'seo'))
            with patch.object(runtime,'memory_admission',return_value=dict(allowed=True,state='normal',rss_bytes=1024)), patch.object(store.Store,'slices',return_value=[(DAY,0)]):
                result=runtime.run(config,clock=lambda:NIGHT,order_reader=read)
            self.assertEqual(result['status'],'published')
            self.assertEqual(result['upstream_requests'],1)
            request.assert_called_once()
            data=snapshot.read(Path(config['data_root']),result['snapshot_id'],'history','FC27')
            row=next(r for r in data['rows'] if r['source_date']==DAY)
            self.assertEqual(row['metrics']['orders']['paid_orders'],1)
            self.assertIsNone(row['metrics']['orders']['seo_orders'])
            self.assertNotIn('private-native-order',str(data))
            self.assertFalse((Path(tmp)/'absent.db').exists())

    def test_four_games_share_one_date_read_and_count_actual_requests(self):
        request = Mock(return_value=(200,b'{}'))
        def collect(scopes, request):
            request('/synthetic',method='GET')
            return [facts(scope,scopes[0]['start']) for scope in ('FC27','D4','AION2','WOW_FOREVER')]
        collect = Mock(side_effect=collect)
        read = NativeOrderFactsReader(clock=lambda:NIGHT,collect_many=collect,request=request)
        for scope in ('FC27','D4','AION2','WOW_FOREVER'):
            result = next(OrderSource(read).pages(scope,DAY))
            self.assertEqual(result['rows'][0]['metrics']['revenue_usd'],'50')
        collect.assert_called_once();request.assert_called_once()
        self.assertEqual(read.calls,1)
        read('FC27','2026-11-03')
        self.assertEqual(collect.call_count,2)
        self.assertEqual(read.day,'2026-11-03')

    def test_daytime_and_unended_date_never_use_cached_or_native_data(self):
        collect = Mock()
        for now,day,code in [(NIGHT+dt.timedelta(hours=8),DAY,'NIGHT_DEADLINE'),(NIGHT,'2026-11-05','SOURCE_DAY_NOT_ENDED')]:
            read=NativeOrderFactsReader(clock=lambda:now,collect_many=collect,request=Mock())
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
        read=NativeOrderFactsReader(clock=lambda:NIGHT,collect_many=Mock(return_value=[]),request=Mock())
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

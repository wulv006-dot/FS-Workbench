import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
sys.path.append(str(Path(__file__).resolve().parent/'fixtures'))
import daily_archive as archive


class Store(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        self.today = date(2026, 10, 21)
        self.store = archive.Archive(self.root, lambda: self.today)
        self.store.safe(True)
        (self.root/'policy.json').write_text(json.dumps({'retentionBasis':'business_date'}))
        self.query = dict(profile='FC27', start='2026-10-20', end='2026-10-20', contractId='one')

    def test_exact_contract_checksum_source_time_and_compression(self):
        value = dict(generatedAt='2026-10-21T01:00:00+08:00', records=['fictional'] * 10000)
        version = self.store.put('summary', self.query, value)
        got = self.store.get('summary', self.query)
        self.assertEqual(got['generatedAt'], value['generatedAt'])
        self.assertEqual(got['archive']['version'], version)
        self.assertEqual(got['archive']['sourceCapturedAt'], '2026-10-20T17:00:00+00:00')
        self.assertIsNone(self.store.get('summary', dict(self.query, contractId='two')))
        path = next(self.root.rglob('*.gz'))
        self.assertLess(path.stat().st_size, len(archive.encoded(value)) / 10)
        path.write_bytes(b'corrupt')
        self.assertIsNone(self.store.get('summary', self.query))

    def test_today_hourly_and_outside_retention_do_not_enter_archives(self):
        for change in (dict(start='2026-10-21', end='2026-10-21'),dict(grain='hour'),dict(start='2026-07-20')):
            q = dict(self.query, **change)
            self.assertIsNone(self.store.put('summary', q, {}))
        self.assertFalse(list(self.root.rglob('*.gz')))

    def test_late_old_capture_cannot_replace_new_source(self):
        self.store.put('native', self.query, {'generatedAt':'2026-10-21T02:00:00Z','orders':5})
        self.store.put('native', self.query, {'generatedAt':'2026-10-21T01:00:00Z','orders':2})
        self.assertEqual(self.store.get('native', self.query)['orders'], 5)

    def test_calendar_month_retention_only_cleans_managed_objects(self):
        self.assertEqual(archive.cutoff(date(2026,5,31)), date(2026,2,28))
        self.assertEqual(archive.cutoff(date(2028,5,31)), date(2028,2,29))
        self.store.put('summary',dict(self.query,start='2026-08-20',end='2026-08-20'),{})
        self.store.put('summary',self.query,{})
        unrelated=self.root/'report.json';unrelated.write_text('retained')
        self.today=date(2027,1,2)
        self.assertEqual(self.store.prune()['objects'],1)
        self.assertEqual(len(list(self.root.rglob('*.gz'))),2)
        self.store.prune(False)
        self.assertEqual(len(list(self.root.rglob('*.gz'))),1)
        self.assertEqual(unrelated.read_text(),'retained')

    def test_private_path_cannot_follow_a_link(self):
        if os.name != 'posix': return  # Symlink creation needs a separate Windows privilege.
        link=Path(self.temp.name)/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'archive_symlink'):archive.Archive(link).get('summary',self.query)

    def test_incomplete_closed_label_is_not_full_day_evidence(self):
        q=dict(self.query,period={'start':'2026-10-20 00:00','end':'2026-10-20 03:18'})
        value=dict(status='available',query=q,profile={'primary':{'status':'available'},'supplement':{'status':'available'}})
        self.assertFalse(archive.complete_native(value))

    def test_catalog_rebinding_preserves_frozen_source_identity(self):
        q=dict(self.query,grain='day',baseSnapshotId='new')
        value={'rangeId':'source-range','baseSnapshotId':'old','resultSha256':'old-sha','archive':{},'orders':3}
        result=archive.rebind_native(value,q)
        self.assertEqual(result['archive']['sourceBaseSnapshotId'],'old')
        self.assertEqual(result['archive']['sourceResultSha256'],'old-sha')
        self.assertEqual(result['baseSnapshotId'],'new');self.assertEqual(result['orders'],3)
        self.assertNotEqual(archive.native_key(q,['FC27',1322]),archive.native_key(q,['FC27',999]))

    def test_old_business_date_is_not_extended_by_recent_collection(self):
        q=dict(self.query,start='2025-10-20',end='2025-10-20')
        self.assertIsNone(self.store.put('summary',q,dict(generatedAt='2026-10-21T01:00:00Z')))
        self.assertIsNone(self.store.get('summary',q))
        first=self.store.put('summary',self.query,dict(generatedAt='2026-10-21T01:00:00Z'))
        self.assertEqual(first,self.store.put('summary',self.query,dict(generatedAt='2026-10-21T01:00:00Z')))
        self.assertEqual(len(list(self.root.rglob('*.gz'))),1)

    def test_rpg_paid_native_key_preserves_old_archive_and_non_rpg_identity(self):
        rpg=('AION2','Aion 2',826,891,'rpg')
        q=dict(self.query,profile='AION2',grain='day')
        paid=archive.native_key(q,rpg);legacy={k:v for k,v in paid.items() if k!='adminCohort'}
        self.assertEqual(paid['contract'],'native-closed-v2')
        self.assertEqual(paid['adminCohort'],'paid-all-status-v2')
        self.store.put('native',legacy,{'orders':181})
        self.assertIsNone(self.store.get('native',paid))
        self.store.put('native',paid,{'orders':186})
        self.assertEqual(self.store.get('native',legacy)['orders'],181)
        self.assertEqual(self.store.get('native',paid)['orders'],186)
        sports=('FC27','FC27',1322,1327,'sports')
        key=archive.native_key(dict(q,profile='FC27'),sports)
        expected={k:q[k] for k in ('start','end','grain')};expected.update(profile='FC27',contract='native-closed-v2',profileDefinition=archive.hashlib.sha256(archive.encoded(sports)).hexdigest())
        self.assertEqual(key,expected)

    def test_completed_only_native_capture_cannot_seed_current_paid_archive(self):
        q=dict(self.query,profile='AION2',period=dict(start='2026-10-20 00:00',end='2026-10-21 00:00'))
        value=dict(status='available',query=q,scopeContractId='all-websites-order-primary-admin-supplement-v1',profile=dict(primary=dict(status='available'),supplement=dict(status='available',filters=dict(order_status='101'))))
        self.assertFalse(archive.complete_native(value))
        value['profile']['supplement']['filters']['order_status']=''
        self.assertTrue(archive.complete_native(value))

    def test_actual_seed_preserves_181_and_only_imports_proved_paid_186(self):
        import ast,copy
        script=Path(__file__).resolve().parents[4]/'releases/fs-dashboard/nightly-pipeline-20261023/source/archive_jobs.py'
        function=next(n for n in ast.parse(script.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='import_existing')
        rpg=('AION2','Aion 2',826,891,'rpg')
        q=dict(self.query,profile='AION2',grain='day',period=dict(start='2026-10-20 00:00',end='2026-10-21 00:00'))
        old=dict(status='available',scopeContractId='all-websites-order-primary-admin-supplement-v1',query=q,orders=181,profile=dict(primary=dict(status='available',filters=dict(gid=826)),supplement=dict(status='available',filters=dict(order_status='101',pay_status=1))))
        selector={k:v for k,v in q.items() if k!='period'}
        legacy={k:v for k,v in archive.native_key(selector,rpg).items() if k!='adminCohort'}
        original=self.store.put('native',legacy,old)
        missing=copy.deepcopy(old);missing['profile']['supplement']['filters']={}
        paid=copy.deepcopy(old);paid.update(orders=186);paid['query']['adminCohort']='paid-all-status-v2';paid['profile']['supplement']['filters']['order_status']=''
        inputs=self.root/'seed-input';inputs.mkdir()
        for name,value in [('old',old),('missing-proof',missing),('paid',paid)]:
            (inputs/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
        namespace=dict(Path=lambda path:inputs if str(path)=='/var/lib/fs-business-ranges' else self.root/'empty',json=json,profiles=lambda:{'AION2':rpg},complete_native=archive.complete_native,native_key=archive.native_key)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'actual-archive-seed','exec'),namespace)
        result=namespace['import_existing'](self.store)
        self.assertEqual(result['native'],1)
        self.assertEqual(self.store.get('native',legacy)['archive']['version'],original)
        self.assertEqual(self.store.get('native',legacy)['orders'],181)
        key=archive.native_key(paid['query'],rpg)
        self.assertEqual(self.store.get('native',key)['orders'],186)
        paid['profile']['supplement']['filters']={}
        self.assertFalse(archive.complete_native(paid))


class Consumers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        patcher=patch.object(archive,'ROOT',self.root/'archive');patcher.start();self.addCleanup(patcher.stop)
        day=(datetime.now(archive.TZ).date()-timedelta(days=1)).isoformat()
        self.args=dict(profile='FC27',start=day,end=day)

    def test_summary_capture_persists_and_new_process_cache_uses_no_source(self):
        from live_summary import SummaryCache,query
        profiles={'FC27':('FC27','FC 27',1322,1327,'sports')}
        q=query({k:[v] for k,v in dict(self.args,mode='summary').items()},profiles)
        def reader(q):
            return dict(status='available',period=q['period'],capturedAt=datetime.now(timezone.utc).isoformat(),currency='USD',system='fixture',orders=3,revenueUsd=30,metrics={},dimensions={})
        old=SummaryCache(reader,reader,profiles)
        old.get(q);old.close()
        got=archive.read('summary',archive.summary_key(q))
        self.assertIsNotNone(got)
        source=Mock(side_effect=AssertionError('unexpected upstream'))
        new=SummaryCache(source,source,profiles)
        try:
            got['archive']['sourceCapturedAt']='2026-10-01T00:00:00+00:00'
            with patch.object(archive,'read',return_value=got):code,result=new.get(q)
            self.assertEqual(code,200);self.assertEqual(result['profile']['primary']['orders'],3)
            self.assertEqual(result['origin'],'dated-archive');source.assert_not_called()
        finally:new.close()

    def test_disabled_native_source_is_not_opened_by_archive(self):
        from source_snapshots import SnapshotStore
        reader=Mock(return_value={'status':'available','authoritative_fields':{'orders':{'value':3}}})
        store=SnapshotStore(self.root/'source-snapshots')
        valid=lambda value:value.get('status')=='available'
        store.get('native-statistics',self.args,reader,valid)
        reader.reset_mock()
        result=store.get('native-statistics',self.args,reader,valid)
        self.assertIn('archive',result);reader.assert_not_called()
        with self.assertRaises(PermissionError):store.get('native-statistics',self.args,reader,valid,enabled=False)
        reader.assert_not_called()

    def test_current_queue_and_price_sources_retain_existing_live_path(self):
        from source_snapshots import SnapshotStore
        with patch.object(archive,'read',side_effect=AssertionError('must not archive live queue/price')):
            source=SnapshotStore(self.root/'source-snapshots')
            for family in ('paid-detail','native-loss'):
                source.get(family,self.args,lambda:{'status':'available'},lambda value:False)

    def test_daily_financial_derivation_does_not_sum_people_or_rates(self):
        from live_summary import query
        profiles={'FC27':('FC27','FC27',1322,1327,'sports')}
        second=date.fromisoformat(self.args['end']);first=(second-timedelta(days=1)).isoformat()
        for day,orders,revenue in [(first,2,20),(self.args['end'],3,45)]:
            q=query({k:[v] for k,v in dict(self.args,start=day,end=day,mode='summary').items()},profiles)
            source=dict(status='available',period=q['period'],capturedAt=datetime.now(timezone.utc).isoformat(),system='fixture',currency='USD',normalisedScope='same',metrics={k:dict(value=v,status='available') for k,v in [('orders',orders),('revenueUsd',revenue),('pureSalesUsd',revenue),('newCustomers',5),('repeatRatePct',50),('profitMarginPct',20)]})
            value=dict(status='available',stale=False,query=q,profile=dict(primary=source,supplement=source,period=q['period']),generatedAt=source['capturedAt'],sources={k:dict(status='available',stale=False,capturedAt=source['capturedAt']) for k in ('Admin','Order')})
            archive.save('summary',archive.summary_key(q),value)
        selector=dict(archive.summary_key(q),start=first)
        result=archive.derive_summary(selector)
        self.assertEqual(result['profile']['supplement']['revenueUsd'],65)
        self.assertEqual(result['profile']['supplement']['orders'],5)
        self.assertEqual(result['profile']['metrics']['orders']['value'],5)
        self.assertIsNone(result['profile']['supplement']['metrics']['newCustomers']['value'])
        self.assertIsNone(result['profile']['primary']['metrics']['profitMarginPct']['value'])
        self.assertEqual(result['archive']['days'],2);self.assertTrue(result['stale'])
        self.assertFalse(archive.complete_summary(result))
        self.assertIsNone(archive.derive_summary(dict(selector,start=(second-timedelta(days=2)).isoformat())))


if __name__=='__main__':unittest.main()

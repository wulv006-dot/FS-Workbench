import ast
from contextlib import contextmanager,closing
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import cache_retention as r
NOW=datetime(2026,10,25,tzinfo=timezone.utc)


def write(path,value):
    path.write_bytes(json.dumps(value,sort_keys=True,separators=(',',':')).encode());os.chmod(path,0o600)


class Cache(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);os.chmod(self.root,0o700)
        self.refs=self.root/'reports';self.refs.mkdir(mode=0o700)

    def tearDown(self):self.temp.cleanup()

    def snapshot(self,age=2,pointed=False):
        v=dict(family='paid-detail',key='a'*64,saved_at=(NOW-timedelta(days=age)).isoformat(),value={'data':'same historical money '*1000})
        raw=json.dumps(v,sort_keys=True,separators=(',',':')).encode();version=hashlib.sha256(raw).hexdigest()
        path=self.root/(version+'.data.json');path.write_bytes(raw);os.chmod(path,0o600)
        if pointed:write(self.root/('a'*64+'.json'),dict(version=version))
        return version,path,raw

    def collect(self,now=NOW,apply=True,databases=None):
        return r.collect(self.root,now,paths=[self.refs],databases=databases or [],apply=apply)

    def test_expired_unreferenced_compressed_and_restored_exactly(self):
        version,p,raw=self.snapshot();result=self.collect()
        self.assertFalse(p.exists());self.assertEqual(result['recycled_bytes'],len(raw))
        self.assertLess(result['compressed_bytes'],len(raw));r.restore(p)
        self.assertEqual(p.read_bytes(),raw)

    def test_current_pointer_and_report_references_are_kept(self):
        version,p,_=self.snapshot(pointed=True);self.assertFalse(self.collect()['candidates']);self.assertTrue(p.exists())
        (self.root/('a'*64+'.json')).unlink();write(self.refs/'receipt.json',{'source_cache':{'version':version}})
        self.assertFalse(self.collect()['candidates']);self.assertTrue(p.exists())

    def test_database_reference_is_protected(self):
        version,p,_=self.snapshot();db=self.root/'tasks.sqlite3'
        with closing(sqlite3.connect(db)) as c,c:c.execute('create table evidence(content TEXT)');c.execute('insert into evidence values(?)',(json.dumps({'version':version}),))
        os.chmod(db,0o644)
        self.assertFalse(self.collect(databases=[db])['candidates']);self.assertTrue(p.exists())

    def test_existing_worker_owned_receipts_still_protect_versions(self):
        version,_,_=self.snapshot();write(self.refs/'worker.json',{'version':version})
        with patch.object(r.os,'geteuid',return_value=11027,create=True):
            refs,_=r.reference_versions(self.root,[self.refs],[])
        self.assertIn(version,refs)

    def test_unexpired_data_and_unknown_reference_source_are_not_removed(self):
        _,p,_=self.snapshot(age=0);self.assertFalse(self.collect()['candidates'])
        with self.assertRaisesRegex(ValueError,'root_missing'):r.collect(self.root,NOW,paths=[self.root/'missing'],databases=[],apply=True)
        self.assertTrue(p.exists())

    def test_seven_day_recycle_rechecks_new_reference(self):
        version,p,_=self.snapshot();self.collect();cold=self.root/'.recycle'/(version+'.data.json.gz')
        write(self.refs/'new.json',{'version':version})
        self.assertEqual(self.collect(NOW+timedelta(days=8))['purged_files'],0);self.assertTrue(cold.exists())
        (self.refs/'new.json').unlink();self.assertEqual(self.collect(NOW+timedelta(days=9))['purged_files'],1)
        self.assertFalse(cold.exists())

    def test_corruption_or_receipt_failure_never_loses_original(self):
        _,p,raw=self.snapshot()
        with patch.object(r,'atomic',side_effect=OSError('receipt failure')):
            with self.assertRaises(OSError):self.collect()
        self.assertEqual(p.read_bytes(),raw)
        self.collect();cold=next((self.root/'.recycle').glob('*.gz'));cold.write_bytes(b'bad')
        with self.assertRaises((OSError,ValueError)):r.restore(p)
        self.assertFalse(p.exists())

    def test_dry_run_and_reentrant_lock(self):
        _,p,_=self.snapshot()
        with r.cache_lock(self.root),r.cache_lock(self.root):result=self.collect(apply=False)
        self.assertEqual(len(result['candidates']),1);self.assertTrue(p.exists());self.assertFalse((self.root/'.recycle').exists())

    def test_actual_snapshot_read_recovers_version_without_refreshing_its_time(self):
        _,p,raw=self.snapshot();self.collect()
        import source_snapshots
        store=source_snapshots.SnapshotStore(self.root)
        value=store.read(p);self.assertEqual(value,json.loads(raw));self.assertEqual(p.read_bytes(),raw)
    def test_native_archive_lookup_is_versioned_before_read_or_live_cache(self):
        import source_snapshots
        store=source_snapshots.SnapshotStore(self.root)
        old_query=dict(profile='FC27',start='2026-10-24',end='2026-10-24')
        new_value={'status':'available','orders':2};old_value={'status':'available','orders':1}
        archive=types.SimpleNamespace(read=Mock(side_effect=lambda family,q:old_value if q==old_query else None),save=Mock())
        store.get_live=Mock(return_value=new_value)
        with patch.dict(sys.modules,daily_archive=archive):
            self.assertEqual(store.get('native-statistics',old_query,lambda:None,lambda v:True),new_value)
        query=archive.read.call_args.args[1]
        self.assertEqual(query['admin_summary_contract'],'admin-paid-order-labelled-supplement-v2')
        self.assertEqual(store.get_live.call_args.args[1],query);self.assertEqual(archive.save.call_args.args[1],query)
        self.assertNotIn('admin_summary_contract',old_query)
    def test_archive_observations_preserve_scoped_missing_retry_and_terminal(self):
        import source_snapshots as snapshots
        query=dict(profile='FC27',start='2026-10-24',end='2026-10-24')
        row=lambda status,**kw:dict(query=query,family='summary',status=status,**kw)
        states={'complete':row('complete'),'pending':row('pending',reason='source_running',retryable=False,retryAfter=123,failures=0),
                'terminal':row('failed',reason='source_permission_denied',retryable=False,retryAfter=0,failures=1),
                'other':dict(row('failed'),query=dict(query,profile='AION2')),
                'old':dict(row('failed'),query=dict(query,start='2026-10-01',end='2026-10-01'))}
        write(self.root/'scheduler-state.json',states)
        result=snapshots.archive_status(query,self.root)
        self.assertEqual((result['status'],result['observedCount'],result['missingCount'],result['terminalCount']),('partial',3,2,1))
        self.assertEqual(result['missing'][0]['retryAfter'],123)
        self.assertFalse(result['missing'][1]['retryable']);self.assertFalse(result['blocks_publication'])
        self.assertIsNone(result['coverage_complete'])
        write(self.root/'scheduler-state.json',{'complete':row('complete')})
        result=snapshots.archive_status(query,self.root)
        self.assertEqual(result['status'],'no_recorded_gaps');self.assertIsNone(result['coverage_complete'])
        self.assertEqual(snapshots.archive_status(dict(query,profile='RS'),self.root)['status'],'unobserved')
        (self.root/'scheduler-state.json').unlink()
        self.assertIsNone(snapshots.archive_status(query,self.root)['missingCount'])
    def test_native_pending_exposes_archive_state_without_filling_or_resaving(self):
        import source_snapshots as snapshots
        store=snapshots.SnapshotStore(self.root);query=dict(profile='FC27',start='2026-10-24',end='2026-10-24')
        pending={'status':'pending','authoritative_fields':{'orders':{'value':None}}}
        store.get_live=Mock(return_value=pending)
        archive=types.SimpleNamespace(read=Mock(return_value=None),save=Mock())
        observed={'status':'partial','missingCount':1,'blocks_publication':False}
        with patch.dict(sys.modules,daily_archive=archive),patch.object(snapshots,'archive_status',return_value=observed):
            value=store.get('native-statistics',query,lambda:None,lambda v:v.get('status')=='available')
        self.assertEqual(value['status'],'pending');self.assertIsNone(value['authoritative_fields']['orders']['value'])
        self.assertEqual(value['archive_status'],observed);self.assertNotIn('archive_status',pending);archive.save.assert_not_called()
        complete={'status':'available','orders':0};archive.read.return_value=complete
        with patch.dict(sys.modules,daily_archive=archive),patch.object(snapshots,'archive_status',side_effect=AssertionError('valid archive must stay usable')):
            self.assertIs(store.get('native-statistics',query,lambda:None,lambda v:v.get('status')=='available'),complete)

    def test_active_tasks_defer_and_bad_ledger_fails_closed(self):
        _,p,_=self.snapshot()
        with patch.object(r,'busy',return_value=True),patch.object(r,'collect',side_effect=AssertionError('must defer')):
            self.assertEqual(r.run(self.root,apply=True)['status'],'deferred_active_task')
        self.collect();recycle=self.root/'.recycle'
        write(recycle/'index.json',{'../../outside':{'moved_at':NOW.isoformat()}})
        with self.assertRaisesRegex(ValueError,'retention_ledger'):self.collect(NOW+timedelta(days=9))
        self.assertTrue(next(recycle.glob('*.gz')).exists())


def excel_module(name):
    source=(SOURCE/name).read_text(encoding='utf-8');tree=ast.parse(source)
    names={'_excel_private','archive_access','_excel_atomic','_excel_sync','_excel_digest','_excel_metadata','excel_path','maintain_archive','archive_files'}
    scope=dict(Path=Path,threading=threading,json=json,hashlib=hashlib,re=re,datetime=datetime,date=NOW.date().__class__,timedelta=timedelta,
               timezone=timezone,SHANGHAI=timezone(timedelta(hours=8)),ARCHIVE_LOCK=threading.RLock(),_EXCEL_DEPTH=threading.local(),
               contextmanager=contextmanager,MAX_FILE=32*1024*1024,MAX_ARCHIVE_BYTES=512*1024*1024,MAX_ARCHIVE_FILES=512,
               ARCHIVE_RESERVE_BYTES=64*1024*1024,RULE_VERSION='exact-rules')
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),name,'exec'),scope)
    return types.SimpleNamespace(**scope)


class Excel(unittest.TestCase):
    def test_session_unit_changes_only_verified_image_reference(self):
        sys.path.insert(0,str(SOURCE.parent))
        from prepare_session_unit import candidate,OLD_TAG
        raw=('ExecStart=docker run --memory=2g --mount existing '+OLD_TAG+'\n').encode()
        new='sha256:'+'a'*64
        self.assertEqual(candidate(raw,new).replace(new.encode(),OLD_TAG.encode()),raw)
        with self.assertRaises(ValueError):candidate(raw+OLD_TAG.encode(),new)
        with self.assertRaises(ValueError):candidate(raw,'latest')

    def test_both_readers_archive_restore_and_recent_redline_data_remain_hot(self):
        for name in ('es_order_structure.py','session_es_order_structure.py'):
            with self.subTest(reader=name),tempfile.TemporaryDirectory() as d:
                root=Path(d);os.chmod(root,0o700);e=excel_module(name)
                old=b'exact original historical export';recent=b'current redline original'
                old_id=hashlib.sha256(old).hexdigest();new_id=hashlib.sha256(recent).hexdigest()
                for digest,data,end in ((old_id,old,'2025-10-24'),(new_id,recent,'2026-10-24')):
                    (root/(digest+'.xlsx')).write_bytes(data);os.chmod(root/(digest+'.xlsx'),0o600)
                    write(root/(digest+'.json'),dict(query={'profile':'ALL','start':end,'end':end},file_sha256=[digest]))
                result=e.maintain_archive(root,now=NOW,apply=False);self.assertEqual(len(result['candidates']),1)
                self.assertTrue((root/(old_id+'.xlsx')).exists())
                result=e.maintain_archive(root,now=NOW);self.assertEqual(result['archived_files'],1)
                self.assertFalse((root/(old_id+'.xlsx')).exists());self.assertTrue((root/(new_id+'.xlsx')).exists())
                with e.archive_access(root):restored=e.excel_path(root,old_id)
                self.assertEqual(restored.read_bytes(),old);self.assertEqual((root/'.cold'/(old_id+'.xlsx')).read_bytes(),old)
                self.assertEqual(e.maintain_archive(root,now=datetime.now(timezone.utc))['archived_files'],0)
                # The original writer must tolerate both the cold directory and its lock.
                e.archive_files([recent],dict(profile='ALL',start='2026-10-24',end='2026-10-24'),root)

    def test_cold_corruption_and_receipt_failure_preserve_originals(self):
        e=excel_module('es_order_structure.py')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);os.chmod(root,0o700);raw=b'old original';digest=hashlib.sha256(raw).hexdigest();p=root/(digest+'.xlsx')
            p.write_bytes(raw);os.chmod(p,0o600);write(root/'manifest.json',dict(query={'start':'2025-10-01','end':'2025-10-02'},file_sha256=[digest]))
            namespace=e.maintain_archive.__globals__;original=namespace['_excel_atomic'];namespace['_excel_atomic']=lambda *a:(_ for _ in ()).throw(OSError('receipt'))
            with self.assertRaises(OSError):e.maintain_archive(root,now=NOW)
            self.assertEqual(p.read_bytes(),raw);namespace['_excel_atomic']=original;e.maintain_archive(root,now=NOW)
            cold=root/'.cold'/p.name;cold.write_bytes(b'corrupt')
            with e.archive_access(root),self.assertRaisesRegex(ValueError,'integrity'):e.excel_path(root,digest)
            self.assertFalse(p.exists())

    def test_shared_original_needed_by_recent_manifest_is_not_archived(self):
        e=excel_module('es_order_structure.py')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);os.chmod(root,0o700);raw=b'shared original';digest=hashlib.sha256(raw).hexdigest();p=root/(digest+'.xlsx');p.write_bytes(raw);os.chmod(p,0o600)
            for n,end in enumerate(('2025-10-01','2026-10-24')):write(root/(str(n)+'.json'),dict(query={'start':end,'end':end},file_sha256=[digest]))
            self.assertEqual(e.maintain_archive(root,now=NOW)['archived_files'],0);self.assertTrue(p.exists())


class SnapshotConcurrency(unittest.TestCase):
    def setUp(self):
        import source_snapshots as snapshots
        self.snapshots=snapshots;self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'private'
        self.clock=[NOW];self.store=snapshots.SnapshotStore(self.root,clock=lambda:self.clock[0])
        self.query={'profile':'FC27','start':'2026-10-24','end':'2026-10-24'}

    def tearDown(self):self.temp.cleanup()
    def valid(self,value):return value.get('status')=='available'
    def value(self,marker=1):return {'status':'available','orders':7,'marker':marker}
    def get(self,query=None,reader=None,family='native-loss'):
        return self.store.get_live(family,query or self.query,reader or (lambda:self.value()),self.valid)

    def test_distinct_cold_readers_and_existing_warm_hit_do_not_block_each_other(self):
        from concurrent.futures import ThreadPoolExecutor
        first=threading.Event();second=threading.Event();release=threading.Event()
        warm_query=dict(self.query,profile='D4');self.get(warm_query,lambda:self.value('warm-D4'),family='paid-detail')
        def read(event,marker):
            event.set()
            if not release.wait(3):raise TimeoutError('fixture_wait')
            return self.value()
        with ThreadPoolExecutor(max_workers=3) as pool:
            a=pool.submit(self.get,dict(self.query,profile='AION2'),lambda:read(first,'AION2'))
            b=None
            try:
                self.assertTrue(first.wait(1));b=pool.submit(self.get,self.query,lambda:read(second,'FC-official'),family='official-index')
                self.assertTrue(second.wait(1),'independent cold key serialized behind reader')
                reader=Mock(side_effect=AssertionError('existing warm reply must not reread'))
                warm=pool.submit(self.get,warm_query,reader,'paid-detail').result(timeout=.5)
                self.assertTrue(warm['source_cache']['reused']);self.assertEqual(warm['marker'],'warm-D4');reader.assert_not_called()
            finally:
                release.set();a.result(timeout=2)
                if b is not None:b.result(timeout=2)

    def test_same_key_is_singleflight_and_busy_does_not_wait_or_invent_counts(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        entered=threading.Event();release=threading.Event();calls=[]
        def read():
            calls.append(1);entered.set()
            if not release.wait(3):raise TimeoutError('fixture_wait')
            return self.value()
        with ThreadPoolExecutor(max_workers=1) as pool:
            owner=pool.submit(self.get,reader=read)
            try:
                self.assertTrue(entered.wait(1));reader=Mock(side_effect=AssertionError('duplicate source read'))
                started=time.monotonic();busy=self.get(reader=reader)
                self.assertLess(time.monotonic()-started,.5);self.assertEqual(busy['status'],'busy')
                self.assertEqual(busy['source_cache']['status'],'pending');self.assertIsNone(busy['source_cache']['saved_at'])
                self.assertNotIn('orders',busy);reader.assert_not_called()
            finally:release.set();owner.result(timeout=2)
        cached=self.get(reader=Mock(side_effect=AssertionError('fresh result must coalesce')))
        self.assertTrue(cached['source_cache']['reused']);self.assertEqual(len(calls),1)

    def test_failed_and_invalid_reader_do_not_publish_or_poison_next_attempt(self):
        self.get();before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        self.clock[0]+=timedelta(days=1)
        with self.assertRaises(OSError):self.get(reader=Mock(side_effect=OSError('fixture_network_failure')))
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.assertEqual(self.get(reader=lambda:{'status':'unavailable'}),{'status':'unavailable'})
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        value=self.get(reader=lambda:self.value(2));self.assertEqual(value['marker'],2)
        self.assertFalse(value['source_cache']['reused'])

    def test_explicit_refresh_reads_again_and_concurrent_refresh_exposes_original_stale_value(self):
        from concurrent.futures import ThreadPoolExecutor
        q=dict(self.query,refresh='1');first=self.get(q);second=self.get(q,lambda:self.value(2))
        self.assertFalse(second['source_cache']['reused']);self.assertNotEqual(first['source_cache']['version'],second['source_cache']['version'])
        entered=threading.Event();release=threading.Event()
        def read():
            entered.set()
            if not release.wait(3):raise TimeoutError('fixture_wait')
            return self.value(3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            owner=pool.submit(self.get,q,read)
            try:
                self.assertTrue(entered.wait(1));busy=self.get(q,Mock(side_effect=AssertionError('duplicate refresh')))
                self.assertEqual((busy['status'],busy['marker'],busy['orders']),('busy',2,7))
                self.assertTrue(busy['stale']);self.assertTrue(busy['source_cache']['stale'])
                self.assertEqual(busy['source_cache']['saved_at'],second['source_cache']['saved_at'])
            finally:release.set();self.assertEqual(owner.result(timeout=2)['marker'],3)

    def test_permissive_validator_never_archives_busy_pending_or_stale_as_complete(self):
        archive=types.SimpleNamespace(read=Mock(return_value=None),save=Mock())
        values=[{'status':'busy'},{'status':'pending'},{'status':'available','stale':True,'orders':7},
                {'status':'available','source_cache':{'status':'pending'}},
                {'status':'available','source_cache':{'stale':True}}]
        with patch.dict(sys.modules,daily_archive=archive),patch.object(self.snapshots,'archive_status',return_value={'status':'partial'}):
            for value in values:
                with self.subTest(value=value),patch.object(self.store,'get_live',return_value=value):
                    result=self.store.get('native-statistics',self.query,lambda:None,lambda v:True)
                    expected='stale' if value['status']=='available' else value['status']
                    self.assertEqual(result['status'],expected);archive.save.assert_not_called()
            complete=self.value()
            with patch.object(self.store,'get_live',return_value=complete):self.store.get('native-statistics',self.query,lambda:None,lambda v:True)
            archive.save.assert_called_once()

    def test_managed_reader_stale_metadata_is_not_relabelled_as_fresh_by_permissive_validator(self):
        archive=types.SimpleNamespace(read=Mock(return_value=None),save=Mock())
        value=dict(self.value(),source_cache={'stale':True,'saved_at':'2026-10-24T00:00:00+00:00'})
        with patch.dict(sys.modules,daily_archive=archive),patch.object(self.snapshots,'archive_status',return_value={'status':'partial'}):
            result=self.store.get('native-statistics',self.query,lambda:value,lambda v:True)
        self.assertEqual(result['status'],'stale');self.assertEqual(result['orders'],7)
        self.assertEqual(result['source_cache']['saved_at'],value['source_cache']['saved_at'])
        self.assertFalse(list(self.root.glob('*.json')));archive.save.assert_not_called()

    def test_complete_archive_fastpath_survives_but_refresh_and_bad_states_cannot_bypass_guard(self):
        complete=self.value();archive=types.SimpleNamespace(read=Mock(return_value=complete),save=Mock())
        with patch.dict(sys.modules,daily_archive=archive),patch.object(self.store,'get_live',side_effect=AssertionError('full archive should stay fast')):
            self.assertIs(self.store.get('native-statistics',self.query,lambda:None,lambda v:True),complete)
        with patch.dict(sys.modules,daily_archive=archive),patch.object(self.store,'get_live',return_value=self.value(2)) as live:
            value=self.store.get('native-statistics',dict(self.query,refresh='1'),lambda:None,lambda v:True)
            self.assertEqual(value['marker'],2);live.assert_called_once();archive.save.assert_called_once()
        archive.save.reset_mock()
        for bad in ({'status':'busy'},{'status':'pending'},dict(complete,stale=True)):
            archive.read.return_value=bad
            with self.subTest(bad=bad),patch.dict(sys.modules,daily_archive=archive),patch.object(self.store,'get_live',return_value=complete) as live:
                self.store.get('native-statistics',self.query,lambda:None,lambda v:True);live.assert_called_once()

    def test_actual_managed_stale_reply_retains_values_but_never_resaves_or_claims_complete(self):
        from concurrent.futures import ThreadPoolExecutor
        archive=types.SimpleNamespace(read=Mock(return_value=None),save=Mock());entered=threading.Event();release=threading.Event()
        def get(reader):return self.store.get('native-statistics',self.query,reader,lambda value:True)
        def read():
            entered.set()
            if not release.wait(3):raise TimeoutError('fixture_wait')
            return self.value(2)
        with patch.dict(sys.modules,daily_archive=archive),patch.object(self.snapshots,'archive_status',return_value={'status':'partial'}):
            original=get(lambda:self.value());self.clock[0]+=timedelta(days=1)
            with ThreadPoolExecutor(max_workers=1) as pool:
                owner=pool.submit(get,read)
                try:
                    self.assertTrue(entered.wait(1));stale=get(Mock(side_effect=AssertionError('duplicate read')))
                    self.assertEqual((stale['status'],stale['orders'],stale['marker']),('busy',7,1))
                    self.assertTrue(stale['stale']);self.assertEqual(stale['source_cache']['saved_at'],original['source_cache']['saved_at'])
                    self.assertEqual(archive.save.call_count,1);self.assertEqual(stale['archive_status']['status'],'partial')
                finally:release.set();owner.result(timeout=2)
            self.assertEqual(archive.save.call_count,2)

    def test_retention_can_run_during_reader_and_never_unlinks_the_key_lock_inode(self):
        from concurrent.futures import ThreadPoolExecutor
        self.get();lock=next(self.root.glob('.refresh-*.lock'));inode=lock.stat().st_ino
        refs=self.root/'reports';refs.mkdir(mode=0o700)
        saved={'family':'paid-detail','key':'a'*64,'saved_at':(NOW-timedelta(days=3)).isoformat(),'value':{'unused':True}}
        raw=self.snapshots.encoded(saved);version=hashlib.sha256(raw).hexdigest();write(self.root/(version+'.data.json'),saved)
        self.clock[0]+=timedelta(days=1);entered=threading.Event();release=threading.Event()
        def read():
            entered.set()
            if not release.wait(3):raise TimeoutError('fixture_wait')
            return self.value(2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            owner=pool.submit(self.get,reader=read)
            try:
                self.assertTrue(entered.wait(1));result=r.collect(self.root,self.clock[0],paths=[refs],databases=[],apply=True)
                self.assertEqual(len(result['candidates']),1);self.assertTrue(lock.exists());self.assertEqual(lock.stat().st_ino,inode)
                busy=self.get();self.assertEqual(busy['status'],'busy');self.assertEqual(lock.stat().st_ino,inode)
            finally:release.set();owner.result(timeout=2)
        r.collect(self.root,self.clock[0]+timedelta(days=9),paths=[refs],databases=[],apply=True)
        self.assertTrue(lock.exists());self.assertEqual(lock.stat().st_ino,inode)

    def test_reader_cannot_publish_under_mutated_query_or_mismatched_source_version(self):
        q=dict(self.query,config={'revision':1})
        def mutate():q['config']['revision']=2;return self.value()
        with self.assertRaisesRegex(ValueError,'snapshot_query_changed'):self.get(q,mutate)
        self.assertFalse(list(self.root.glob('*.json')))
        q=dict(self.query,source_version='a'*64)
        with self.assertRaisesRegex(ValueError,'snapshot_source_changed'):
            self.get(q,lambda:dict(self.value(),source_sha256='b'*64),'published-source')
        self.assertFalse(list(self.root.glob('*.json')))

    def test_newer_valid_pointer_published_during_read_wins_over_old_result(self):
        self.get();self.clock[0]+=timedelta(days=1)
        q=self.query;family='native-loss';key=hashlib.sha256(self.snapshots.encoded({'family':family,'query':q,'contract':1})).hexdigest()
        def read():
            saved={'contract':1,'key':key,'family':family,'query':q,'saved_at':self.clock[0].isoformat(),'value':self.value(9)}
            version=hashlib.sha256(self.snapshots.encoded(saved)).hexdigest()
            with self.snapshots.LOCK,r.cache_lock(self.root):
                self.snapshots.atomic(self.root/(version+'.data.json'),saved);self.snapshots.atomic(self.root/(key+'.json'),{'version':version})
            return self.value(2)
        result=self.get(reader=read)
        self.assertEqual(result['marker'],9);self.assertTrue(result['source_cache']['reused'])
        self.assertEqual(len(list(self.root.glob('*.data.json'))),2)

    def test_open_business_day_keeps_original_live_bypass(self):
        q=dict(self.query,start='2026-10-25',end='2026-10-25');reader=Mock(side_effect=[self.value(),self.value(2)])
        self.assertEqual(self.get(q,reader)['marker'],1);self.assertEqual(self.get(q,reader)['marker'],2)
        self.assertEqual(reader.call_count,2);self.assertFalse(self.root.exists())

    @unittest.skipUnless(os.name=='posix','real cross-process Linux file lock')
    def test_other_process_key_owner_returns_busy_without_waiting_or_duplicate_reader(self):
        import select,subprocess,time
        self.get();self.clock[0]+=timedelta(days=1);lock=next(self.root.glob('.refresh-*.lock'))
        program='import fcntl,os,sys;fd=os.open(sys.argv[1],os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX);print("READY",flush=True);sys.stdin.read(1);os.close(fd)'
        process=subprocess.Popen([sys.executable,'-B','-c',program,str(lock)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertTrue(select.select([process.stdout],[],[],2)[0]);self.assertEqual(process.stdout.readline().strip(),'READY')
            reader=Mock(side_effect=AssertionError('cross-process duplicate source'))
            started=time.monotonic();value=self.get(reader=reader)
            self.assertLess(time.monotonic()-started,.5);self.assertEqual(value['status'],'busy');reader.assert_not_called()
        finally:
            if process.poll() is None:
                process.stdin.write('x');process.stdin.flush()
            try:process.communicate(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.communicate(timeout=2)
        self.assertEqual(self.get(reader=lambda:self.value(2))['marker'],2)

    @unittest.skipUnless(os.name=='posix','real lock inode replacement')
    def test_changed_lock_inode_fails_before_publish(self):
        def replace_lock():
            lock=next(self.root.glob('.refresh-*.lock'));lock.unlink();fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            return self.value()
        with self.assertRaisesRegex(ValueError,'snapshot_refresh_lock_changed'):self.get(reader=replace_lock)
        self.assertFalse(list(self.root.glob('*.json')))



if __name__=='__main__':unittest.main()

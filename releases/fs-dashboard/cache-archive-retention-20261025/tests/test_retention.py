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
from unittest.mock import patch

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
        os.chmod(db,0o600)
        self.assertFalse(self.collect(databases=[db])['candidates']);self.assertTrue(p.exists())

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


def excel_module(name):
    source=(SOURCE/name).read_text(encoding='utf-8');tree=ast.parse(source)
    names={'_excel_private','archive_access','_excel_atomic','_excel_sync','_excel_digest','excel_path','maintain_archive','archive_files'}
    scope=dict(Path=Path,threading=threading,json=json,hashlib=hashlib,re=re,datetime=datetime,date=NOW.date().__class__,timedelta=timedelta,
               timezone=timezone,SHANGHAI=timezone(timedelta(hours=8)),ARCHIVE_LOCK=threading.RLock(),_EXCEL_DEPTH=threading.local(),
               contextmanager=contextmanager,MAX_FILE=32*1024*1024,MAX_ARCHIVE_BYTES=512*1024*1024,MAX_ARCHIVE_FILES=512,
               ARCHIVE_RESERVE_BYTES=64*1024*1024,RULE_VERSION='exact-rules')
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),name,'exec'),scope)
    return types.SimpleNamespace(**scope)


class Excel(unittest.TestCase):
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


if __name__=='__main__':unittest.main()

import ast
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fs_cleanup', ROOT / 'candidate/fs_cleanup.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
archive_path = ROOT.parents[1] / 'dashboard-refresh-20261025/source/daily_archive.py'
archive_spec = importlib.util.spec_from_file_location('cleanup_archive_contract', archive_path)
archive = importlib.util.module_from_spec(archive_spec)
archive_spec.loader.exec_module(archive)
NOW = datetime(2026, 10, 14, 22, 30, tzinfo=timezone.utc)


def row(**extra):
    value = dict(profileKey='FC27', date='2025-09-30', period={'start': '2025-09-30 00:00', 'end': '2025-10-01 00:00'}, timezone='Asia/Shanghai', currency='USD',
                 scope=dict(sites='all-websites', orderGameId='1322', orderProductType='', orderStatus=''), profitMarginPct=20.0, orders=1, revenueUsd=10.0, profitUsd=None, costUsd=None,
                 status='available', source='order.p2pah.cn', endpoint='/stats/admin_order/index.html', capturedAt='2025-10-01T00:00:00+00:00', latestAttemptAt='2025-10-01T00:00:00+00:00',
                 latestAttemptStatus='available', collectionKind='on-demand-native-day', marginUnit='percent', stale=False)
    value.update(extra)
    return value


def dated_row(day):
    end = day + timedelta(days=1)
    captured = str(end) + 'T00:00:00+00:00'
    return row(date=str(day), period={'start': str(day)+' 00:00', 'end': str(end)+' 00:00'}, capturedAt=captured, latestAttemptAt=captured)


def put(root, value, name=None):
    scope = value['scope']
    expected = dict(sites=scope['sites'], gid=scope['orderGameId'], tid=scope['orderProductType'], status=scope['orderStatus'])
    name = name or hashlib.sha256(json.dumps([value['profileKey'], value['date'], expected], sort_keys=True).encode()).hexdigest() + '.json'
    path = root / name
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def current_writer():
    path=ROOT.parents[1]/'shipping-profit-20261024/source/profit_queries.py'
    spec=importlib.util.spec_from_file_location('current_cleanup_writer',path)
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,fs_cleanup=c),patch.object(sys,'path',[str(ROOT/'tests/helpers'),*sys.path]):
        spec.loader.exec_module(module)
    return module,path


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        daily = patch.dict(sys.modules, daily_archive=archive)
        daily.start();self.addCleanup(daily.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_expired_verified_row(self):
        old = put(self.root, row())
        (self.root / 'task.db').write_bytes(b'database')
        (self.root / 'snapshot.json').write_text('{}')
        (self.root / 'rollback').mkdir()
        (self.root / 'rollback/old.json').write_text('{}')
        result = c.plan(self.root, NOW, set())
        self.assertEqual([r['name'] for r in result['rows']], [old.name])
        self.assertEqual(result['preservedFiles'], 3)

    def test_semantic_time_ignores_mtime(self):
        path = put(self.root, row(capturedAt=NOW.isoformat(), latestAttemptAt=NOW.isoformat()))
        os.utime(path, (0, 0))
        self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0)

    def test_reference_preserved(self):
        path = put(self.root, row())
        self.assertEqual(c.plan(self.root, NOW, {path.stem})['eligibleFiles'], 0)

    def test_failure_missing_future_and_wrong_scope_preserved(self):
        for change in [dict(status='not_provided'), dict(latestAttemptStatus='failed'), dict(stale=True), dict(collectionKind='historical-seed'), dict(capturedAt='2026-10-20T00:00:00+00:00'),
                       dict(capturedAt='2026-10-01T00:00:00'), dict(capturedAt='2026-10-01T08:00:00+08:00'), dict(orders=True), dict(revenueUsd=float('nan')), dict(marginUnit='USD')]:
            put(self.root, row(**change))
            self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0, change)

    def test_bad_name_and_json_preserved(self):
        path = put(self.root, row(), 'a' * 64 + '.json')
        self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0)
        path.write_text('[]')
        self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0)
        path.write_text('not JSON')
        self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0)

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            c.plan(self.root / '..' / 'escape', NOW, set())
        with self.assertRaises(ValueError):
            c.plan(Path('relative'), NOW, set())

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            c.plan(self.root, NOW.replace(tzinfo=None), set())

    def test_window(self):
        self.assertTrue(c.inside_window(NOW))
        self.assertTrue(c.inside_window(NOW + timedelta(minutes=70)))
        self.assertTrue(c.inside_window(NOW + timedelta(minutes=78, seconds=59)))
        self.assertFalse(c.inside_window(NOW + timedelta(minutes=79)))
        self.assertFalse(c.inside_window(NOW + timedelta(minutes=80)))
        self.assertFalse(c.inside_window(NOW + timedelta(hours=8)))

    def test_current_archive_year_and_reader_cutoffs_are_both_preserved(self):
        today = NOW.astimezone(c.SHANGHAI).date()
        year = archive.retention_cutoff(today)
        self.assertEqual(year,archive.cutoff(today,months=12))
        self.assertLess(year, archive.cutoff(today))
        for day in (year, year+timedelta(days=1), today-timedelta(days=120), today-timedelta(days=15)):
            with self.subTest(day=day):
                value=dated_row(day);path=put(self.root,value)
                self.assertFalse(c.expired_row(path.read_bytes(),path.name,NOW))
        value=dated_row(year-timedelta(days=1));path=put(self.root,value)
        self.assertTrue(c.expired_row(path.read_bytes(),path.name,NOW))
        for today in (datetime(2024,2,29).date(),datetime(2025,2,28).date()):
            now=datetime.combine(today,datetime.min.time(),c.SHANGHAI)
            path=put(self.root,dated_row(archive.retention_cutoff(today)))
            self.assertFalse(c.expired_row(path.read_bytes(),path.name,now))

    def test_empty_plan_and_apply_never_scan_unneeded_references(self):
        put(self.root,dated_row(NOW.astimezone(c.SHANGHAI).date()-timedelta(days=15)))
        with patch.object(c,'references',side_effect=AssertionError('unneeded reference scan')):
            preview=c.plan(self.root,NOW)
            self.assertEqual(preview['eligibleFiles'],0)
            self.assertEqual(c.apply(preview,self.root,NOW,clock=lambda:NOW)['removedFiles'],0)
        old=put(self.root,row())
        with patch.object(c,'references',return_value={old.stem}) as refs:
            self.assertEqual(c.plan(self.root,NOW)['eligibleFiles'],0);refs.assert_called_once()

    def test_error_receipt_keeps_fixed_reason_without_exception_contents(self):
        import io
        from contextlib import redirect_stdout
        for error,reason in ((ValueError('reference_scan_limit'),'reference_scan_limit'),(ValueError('private untrusted text'),'cleanup_ValueError'),(OSError('private path'),'cleanup_filesystem_unavailable')):
            records=[];output=io.StringIO()
            with patch.object(sys,'argv',['fs_cleanup.py','--apply']),patch.object(c,'plan',side_effect=error),patch.object(c,'audit',side_effect=lambda record:records.append(dict(record)) or 'synthetic-audit'),redirect_stdout(output):
                c.main()
            self.assertEqual(records[0]['reason'],reason);self.assertEqual(json.loads(output.getvalue())['reason'],reason)
            self.assertNotIn('private',output.getvalue());self.assertNotIn('private',json.dumps(records))

    def test_reference_hardlinks_add_protection_without_relaxing_deletion_targets(self):
        old=put(self.root,row());reports=self.root/'reports';reports.mkdir();first=reports/'first.md'
        first.write_text(old.stem)
        try:os.link(first,reports/'second.md')
        except OSError as error:self.skipTest(str(error))
        self.assertGreater(first.stat().st_nlink,1)
        self.assertEqual(c.references([reports]),{old.stem})
        with patch.object(c,'REFERENCES',(reports,)),patch.object(c,'references',return_value=c.references([reports])):
            self.assertEqual(c.plan(self.root,NOW)['eligibleFiles'],0)

    def test_reference_internal_directory_alias_is_deduplicated_without_losing_hash(self):
        old=put(self.root,row());reports=self.root/'reports';reports.mkdir();real=reports/'canonical';real.mkdir()
        (real/'report.md').write_text(old.stem)
        try:
            (reports/'alias').symlink_to(real,target_is_directory=True)
            (real/'cycle').symlink_to(reports,target_is_directory=True)
            (reports/'ignored-file').symlink_to(self.root/'unread-private')
        except OSError as error:self.skipTest(str(error))
        self.assertEqual(c.references([reports]),{old.stem})
        outside=self.root/'outside';outside.mkdir();external=reports/'external'
        external.symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'reference_scan_linked_directory'):c.references([reports])
        external.unlink();(reports/'supported.json').symlink_to(real/'report.md')
        with self.assertRaisesRegex(ValueError,'reference_scan_linked_file'):c.references([reports])

    def test_reference_text_budget_excludes_unread_binary_files_but_keeps_limits(self):
        old=put(self.root,row());marker=old.stem;file=self.root/'reference.md';file.write_text(marker)
        with patch.object(c.os,'walk',return_value=[(str(self.root),[],['ignored.pyc']*30001+['reference.md'])]):
            self.assertEqual(c.references([self.root]),{marker})
        with patch.object(c.os,'walk',return_value=[(str(self.root),[],['reference.md']*30001)]):
            with self.assertRaisesRegex(ValueError,'reference_scan_limit'):c.references([self.root])
        with file.open('wb') as stream:
            stream.seek(51*1024*1024);stream.write(b'!'+marker.encode()+b'!')
        self.assertEqual(c.references([self.root],identifiers={marker}),{marker})
        original=c.references
        with patch.object(c,'references',side_effect=lambda identifiers:original([self.root],identifiers)):
            self.assertEqual(c.plan(self.root,NOW)['eligibleFiles'],0)
        self.assertTrue(old.exists())

    def test_reference_stream_boundaries_match_original_regex_and_only_keep_wanted(self):
        import io,re
        marker=b'b'*64;other=b'c'*64;block=64*1024
        class Bounded(io.BytesIO):
            def read(self,size=-1):
                if size!=block:raise AssertionError('unbounded reference read')
                return super().read(size)
        cases=[marker,b'!'+marker,marker+b'!',b'a'*65,b'a'*200,b'!'*(block-32)+marker+b'!',
               b'!'*(block-67)+b'a'*65+b'!!'+marker+b'!',b'!'*(block-66)+b'a'*65+b'!'+marker,
               marker+b'!'+other+b'!',b'!'*(block-1)+marker+b'!']
        for raw in cases:
            with self.subTest(length=len(raw)):
                expected={value.decode() for value in re.findall(rb'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])',raw)}
                self.assertEqual(c.reference_hashes(Bounded(raw)),expected)
                self.assertEqual(c.reference_hashes(Bounded(raw),{marker}),expected&{marker.decode()})
        raw=b'a'*65+b'!!'+marker+b'!'+b'c'*64+b'!'+b'd'*200+marker
        class Fragmented(Bounded):
            def read(self,size=-1):
                if size!=block:raise AssertionError('unbounded reference read')
                return io.BytesIO.read(self,fragment)
        expected={value.decode() for value in re.findall(rb'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])',raw)}
        for fragment in (1,2,3,31,63,64,65,66,127):
            with self.subTest(fragment=fragment):self.assertEqual(c.reference_hashes(Fragmented(raw)),expected)

    def test_original_transaction_current_files_alias_keeps_canonical_snapshot_references(self):
        old=put(self.root,row());web=self.root/'transactions';snapshot=web/'snapshots'/'version';snapshot.mkdir(parents=True)
        (snapshot/'snapshot.json').write_text(json.dumps({'reference':old.stem}))
        try:(web/'current-files').symlink_to('snapshots/version',target_is_directory=True)
        except OSError as error:self.skipTest(str(error))
        with patch.object(c,'REFERENCES',(web,)):
            self.assertEqual(c.references([web]),{old.stem})
            (web/'current-files').unlink();(web/'current-files').symlink_to(self.root,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'reference_scan_linked_directory'):c.references([web])

    def test_text_references_never_export_content(self):
        path = put(self.root, row())
        refs = self.root / 'reports'
        refs.mkdir()
        (refs / 'report.json').write_text(json.dumps({'rangeId': path.stem, 'private': 'do-not-export'}))
        self.assertEqual(c.references([refs]), {path.stem})

    def test_symlink_and_hardlink_preserved(self):
        target = put(self.root, row())
        link = self.root / ('b' * 64 + '.json')
        try:
            os.symlink(target, link)
            os.link(target, self.root / 'held-copy')
        except OSError as error:
            self.skipTest(str(error))
        self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0)
        with self.assertRaises(ValueError):
            c.references([self.root])

    def test_hardlinked_cache_preserved(self):
        target = put(self.root, row())
        try:
            os.link(target, self.root / 'copy')
        except OSError as error:
            self.skipTest(str(error))
        self.assertEqual(c.plan(self.root, NOW, set())['eligibleFiles'], 0)

    def test_writer_logic_and_signatures_preserved(self):
        original = ROOT / 'baseline/profit_queries.py'
        before = next(x for x in ast.parse(original.read_text('utf-8')).body if isinstance(x, ast.ClassDef))
        after = next(x for x in ast.parse((ROOT / 'candidate/profit_queries.py').read_text('utf-8')).body if isinstance(x, ast.ClassDef))
        for a, b in zip(before.body, after.body):
            self.assertEqual(a.name, b.name)
            self.assertEqual(ast.dump(a.args), ast.dump(b.args))
            if a.name == 'load':
                self.assertEqual(ast.dump(ast.Module(body=a.body, type_ignores=[])), ast.dump(ast.Module(body=b.body[1].body, type_ignores=[])))
            elif a.name == 'save':
                self.assertEqual(ast.dump(ast.Module(body=a.body, type_ignores=[])), ast.dump(ast.Module(body=b.body[:-1] + b.body[-1].body, type_ignores=[])))
            else:
                self.assertEqual(ast.dump(a), ast.dump(b))

    def test_current_writer_pin_and_same_guard_save_contract_are_verified(self):
        module,path=current_writer()
        self.assertEqual(hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),c.WRITER_SHA)
        self.assertIs(module.cache_guard,c.cache_guard)
        before=next(x for x in ast.parse((ROOT/'candidate/profit_queries.py').read_text()).body if isinstance(x,ast.ClassDef))
        after=next(x for x in ast.parse(path.read_text()).body if isinstance(x,ast.ClassDef))
        old_save=next(x for x in before.body if isinstance(x,ast.FunctionDef) and x.name=='save')
        new_save=next(x for x in after.body if isinstance(x,ast.FunctionDef) and x.name=='save')
        self.assertEqual(ast.dump(old_save),ast.dump(new_save))
        load=next(x for x in after.body if isinstance(x,ast.FunctionDef) and x.name=='load')
        self.assertEqual(ast.dump(load.body[1].items[0].context_expr),ast.dump(ast.parse('cache_guard(self.cache)',mode='eval').body))


@unittest.skipUnless(os.name == 'posix', 'POSIX file descriptors/flock require Linux QA')
class ApplyTests(unittest.TestCase):
    setUp = PlannerTests.setUp
    tearDown = PlannerTests.tearDown
    def test_apply_exact_expired_file_only(self):
        path = put(self.root, row())
        (self.root / 'current.json').write_text('{}')
        actions = []
        result = c.apply(c.plan(self.root, NOW, set()), self.root, NOW, set(), clock=lambda: NOW, action=lambda event, row: actions.append(event))
        self.assertEqual(result['removedFiles'], 1)
        self.assertFalse(path.exists())
        self.assertTrue((self.root / 'current.json').exists())
        self.assertEqual(actions, ['delete_planned', 'deleted'])

    def test_new_reference_and_file_replacement_preserved(self):
        path = put(self.root, row())
        preview = c.plan(self.root, NOW, set())
        self.assertEqual(c.apply(preview, self.root, NOW, {path.stem}, clock=lambda: NOW)['removedFiles'], 0)
        path.write_text('{}')
        self.assertEqual(c.apply(preview, self.root, NOW, set(), clock=lambda: NOW)['removedFiles'], 0)

    def test_nested_lock_is_reentrant_and_other_writer_waits(self):
        started = threading.Event()
        finished = threading.Event()
        def writer():
            started.set()
            with c.cache_guard(self.root):
                finished.set()
        with c.cache_guard(self.root) as fd:
            with c.cache_guard(self.root) as nested:
                self.assertEqual(fd, nested)
            thread = threading.Thread(target=writer)
            thread.start()
            started.wait(1)
            self.assertFalse(finished.wait(.05))
        thread.join(1)
        self.assertTrue(finished.is_set())

    def test_plan_path_traversal_and_symlink_swap_no_delete(self):
        path = put(self.root, row())
        preview = c.plan(self.root, NOW, set())
        preview['rows'][0]['name'] = '../outside.json'
        self.assertEqual(c.apply(preview, self.root, NOW, set(), clock=lambda: NOW)['removedFiles'], 0)
        path.unlink()
        outside = self.root / 'outside.json'
        outside.write_text('preserve')
        path.symlink_to(outside)
        preview['rows'][0]['name'] = path.name
        with self.assertRaises(OSError):
            c.apply(preview, self.root, NOW, set(), clock=lambda: NOW)
        self.assertEqual(outside.read_text(), 'preserve')

    def test_0749_stops_before_first_deletion(self):
        path = put(self.root, row())
        preview = c.plan(self.root, NOW, set())
        result = c.apply(preview, self.root, NOW, set(), clock=lambda: NOW + timedelta(minutes=79))
        self.assertEqual(result['removedFiles'], 0)
        self.assertTrue(path.exists())

    def test_apply_rechecks_retention_and_references_after_planning(self):
        path=put(self.root,row());preview=c.plan(self.root,NOW,set())
        with patch.object(c,'references',return_value={path.stem}) as refs:
            self.assertEqual(c.apply(preview,self.root,NOW,clock=lambda:NOW)['removedFiles'],0);refs.assert_called_once()
        with patch.object(archive,'retention_cutoff',return_value=datetime(2025,9,1).date()):
            self.assertEqual(c.apply(preview,self.root,NOW,set(),clock=lambda:NOW)['removedFiles'],0)
        self.assertTrue(path.exists())

    def test_real_current_writer_uses_shared_guard_and_frozen_cache_stays_readable(self):
        module,_=current_writer();cache=self.root/'days';cache.mkdir(mode=0o700)
        api=module.ProfitQueries({'FC27':('FC','FC',1322,1322,'general')},None,None,self.root,cache)
        today=datetime.now(archive.TZ).date();value=dated_row(today-timedelta(days=15))
        started=threading.Event();finished=threading.Event();errors=[]
        def save():
            started.set()
            try:api.save(value)
            except Exception as error:errors.append(error)
            finally:finished.set()
        with c.cache_guard(cache):
            thread=threading.Thread(target=save);thread.start();self.assertTrue(started.wait(1));self.assertFalse(finished.wait(.05))
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(api.load('FC27',value['date']),value)
        self.assertEqual(c.plan(cache,datetime.now(timezone.utc),set())['eligibleFiles'],0)

    def test_real_apply_streams_new_large_reference_before_unlink(self):
        path=put(self.root,row());before=path.read_bytes();preview=c.plan(self.root,NOW,set())
        self.assertEqual(preview['eligibleFiles'],1)
        reports=self.root/'reports';reports.mkdir()
        with (reports/'large.json').open('wb') as stream:
            stream.seek(51*1024*1024-32);stream.write(path.stem.encode()+b'!')
        original=c.references;observed=[]
        def actual_references(identifiers=None):
            self.assertEqual(identifiers,{path.stem})
            result=original([reports],identifiers);observed.append(result);return result
        with patch.object(c,'references',side_effect=actual_references):
            result=c.apply(preview,self.root,NOW,clock=lambda:NOW)
        self.assertEqual(observed,[{path.stem}]);self.assertEqual(result['removedFiles'],0)
        self.assertEqual(path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()

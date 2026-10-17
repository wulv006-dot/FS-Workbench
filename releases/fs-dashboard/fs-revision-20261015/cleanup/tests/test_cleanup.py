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

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fs_cleanup', ROOT / 'candidate/fs_cleanup.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
NOW = datetime(2026, 10, 14, 22, 30, tzinfo=timezone.utc)


def row(**extra):
    value = dict(profileKey='FC27', date='2026-09-30', period={'start': '2026-09-30 00:00', 'end': '2026-10-01 00:00'}, timezone='Asia/Shanghai', currency='USD',
                 scope=dict(sites='all-websites', orderGameId='1322', orderProductType='', orderStatus=''), profitMarginPct=20.0, orders=1, revenueUsd=10.0, profitUsd=None, costUsd=None,
                 status='available', source='order.p2pah.cn', endpoint='/stats/admin_order/index.html', capturedAt='2026-10-01T00:00:00+00:00', latestAttemptAt='2026-10-01T00:00:00+00:00',
                 latestAttemptStatus='available', collectionKind='on-demand-native-day', marginUnit='percent', stale=False)
    value.update(extra)
    return value


def put(root, value, name=None):
    scope = value['scope']
    expected = dict(sites=scope['sites'], gid=scope['orderGameId'], tid=scope['orderProductType'], status=scope['orderStatus'])
    name = name or hashlib.sha256(json.dumps([value['profileKey'], value['date'], expected], sort_keys=True).encode()).hexdigest() + '.json'
    path = root / name
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

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
        self.assertFalse(c.inside_window(NOW + timedelta(minutes=29)))
        self.assertFalse(c.inside_window(NOW + timedelta(minutes=30)))
        self.assertFalse(c.inside_window(NOW + timedelta(hours=8)))

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

    def test_0659_stops_before_first_deletion(self):
        path = put(self.root, row())
        preview = c.plan(self.root, NOW, set())
        result = c.apply(preview, self.root, NOW, set(), clock=lambda: NOW + timedelta(minutes=29))
        self.assertEqual(result['removedFiles'], 0)
        self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()

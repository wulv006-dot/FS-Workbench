"""Exercise the existing publisher's two-file scope and partial-swap rollback."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name('publish_worker.py')
if not SOURCE.exists():
    SOURCE = Path(__file__).resolve().parents[3] / 'fc27_public_readback_retry_20261009/publish_worker.py'
stub = types.ModuleType('automation_tick')
stub.queue_mutation = contextlib.nullcontext
modules = {'automation_tick': stub}
if sys.platform == 'win32':
    lock = types.ModuleType('fcntl')
    lock.LOCK_EX, lock.LOCK_NB = 1, 2
    lock.flock = lambda *args: None
    modules['fcntl'] = lock
with patch.dict(sys.modules, modules):
    spec = importlib.util.spec_from_file_location('cache_publisher', SOURCE)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'state').mkdir()
        (self.root / 'state/price-writer.lock').touch()
        (self.root / 'rollback').mkdir()
        self.stage = self.root / 'stage'
        (self.stage / 'candidate').mkdir(parents=True)
        self.targets = {}
        self.before = {}
        for name in publisher.TARGETS:
            target = self.root / name
            target.write_text('old = 1\n')
            candidate = self.stage / 'candidate' / name
            candidate.write_text('new = 2\n')
            self.before[str(target)] = publisher.digest(target)
            self.targets[name] = {'target': str(target), 'before': publisher.digest(target),
                                  'after': publisher.digest(candidate)}
        self.manifest = {'targets': self.targets, 'before': self.before}
        (self.stage / 'manifest.json').write_text(json.dumps(self.manifest))
        self.patches = [patch.object(publisher, 'ROOT', self.root),
                        patch.object(publisher, 'STAGE', self.stage),
                        patch.object(publisher, 'TARGETS', {n:r['target'] for n,r in self.targets.items()}),
                        patch.object(publisher.os, 'geteuid', return_value=0, create=True),
                        patch.object(publisher.os, 'O_NOFOLLOW', getattr(publisher.os, 'O_NOFOLLOW', 0), create=True),
                        patch.object(publisher, 'command'),
                        patch.object(publisher, 'wait_health', return_value={
                            'health': {'worker':'ok'}, 'automation': {'revision':30}}),
                        patch('builtins.print')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    @staticmethod
    def swap(source, target):
        target.write_bytes(source.read_bytes())

    def test_check_changes_nothing(self):
        with patch.object(publisher, 'swap') as swap:
            self.assertEqual(publisher.main(False)['status'], 'checked')
        swap.assert_not_called()
        self.assertEqual(list((self.root / 'rollback').iterdir()), [])

    def test_both_files_installed_and_legacy_worker_only_still_supported(self):
        for worker_only in (False, True):
            if worker_only:
                self.manifest['targets'] = {'fc27_cloud_worker.py': self.targets['fc27_cloud_worker.py']}
                for n, row in self.targets.items():
                    Path(row['target']).write_text('old = 1\n')
                (self.stage / 'manifest.json').write_text(json.dumps(self.manifest))
            with patch.object(publisher, 'swap', side_effect=self.swap):
                if worker_only:
                    # Give the second fixture a distinct existing backup parent.
                    (self.root / 'rollback').rename(self.root / 'first-backups')
                    (self.root / 'rollback').mkdir()
                receipt = publisher.main(True)
            self.assertEqual(len(receipt['installed_sha256']), 1 if worker_only else 2)

    def test_partial_second_swap_is_rolled_back(self):
        count = 0
        def failing_swap(source, target):
            nonlocal count
            self.swap(source, target)
            count += 1
            if count == 2:
                raise OSError('simulated post-rename failure')
        with patch.object(publisher, 'swap', side_effect=failing_swap):
            with self.assertRaisesRegex(OSError, 'post-rename'):
                publisher.main(True)
        self.assertEqual(count, 4)
        for path, wanted in self.before.items():
            self.assertEqual(publisher.digest(path), wanted)

    def test_health_failure_restores_both(self):
        with patch.object(publisher, 'swap', side_effect=self.swap), \
             patch.object(publisher, 'wait_health', side_effect=RuntimeError('runtime_not_ready')):
            with self.assertRaisesRegex(RuntimeError, 'runtime_not_ready'):
                publisher.main(True)
        for path, wanted in self.before.items():
            self.assertEqual(publisher.digest(path), wanted)

    def test_extra_targets_and_cas_drift_are_rejected(self):
        self.manifest['targets']['other.py'] = {'target':'/tmp/other.py'}
        (self.stage / 'manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(RuntimeError, 'deployment_scope_invalid'):
            publisher.main(False)
        del self.manifest['targets']['other.py']
        (self.stage / 'manifest.json').write_text(json.dumps(self.manifest))
        Path(self.targets['fc27_cloud_worker.py']['target']).write_text('parallel = 3\n')
        with self.assertRaisesRegex(RuntimeError, 'baseline_changed'):
            publisher.main(False)

    def test_confirmed_write_still_checking_public_price_blocks_publish(self):
        (self.root / 'jobs').mkdir()
        (self.root / 'jobs/active.json').write_text(json.dumps({
            'kind':'auto_cycle', 'status':'ready', 'result':{'status':'confirmed'}}))
        with self.assertRaisesRegex(RuntimeError, 'job_not_idle'):
            publisher.main(False)

    @unittest.skipUnless(sys.platform != 'win32', 'Linux ownership/fsync check')
    def test_real_swap_preserves_metadata(self):
        target = Path(self.targets['fc27_cloud_worker.py']['target'])
        target.chmod(0o640)
        before = target.stat()
        publisher.swap(self.stage / 'candidate/fc27_cloud_worker.py', target)
        after = target.stat()
        self.assertEqual((before.st_uid, before.st_gid, before.st_mode),
                         (after.st_uid, after.st_gid, after.st_mode))
        self.assertEqual(publisher.digest(target), self.targets['fc27_cloud_worker.py']['after'])

    @unittest.skipUnless(sys.platform != 'win32', 'Linux atomic swap cleanup check')
    def test_pre_rename_failure_removes_only_own_temp(self):
        target = Path(self.targets['fc27_cloud_worker.py']['target'])
        with patch.object(publisher.os, 'replace', side_effect=OSError('rename failed')):
            with self.assertRaisesRegex(OSError, 'rename failed'):
                publisher.swap(self.stage / 'candidate/fc27_cloud_worker.py', target)
        self.assertEqual(publisher.digest(target), self.before[str(target)])
        self.assertFalse(target.with_name('.' + target.name + '.readback-tmp').exists())


if __name__ == '__main__':
    unittest.main()

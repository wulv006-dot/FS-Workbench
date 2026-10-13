"""Single-file shared update, using the isolated existing publisher test harness."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import types
import unittest
from unittest.mock import patch

import test_backend_release as harness

ROOT, load = harness.ROOT, harness.load


class InsightsRelease(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BackendRelease('test_exact_scope_and_preview_are_readonly')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        self.builder = load('single_insights_builder', ROOT / 'build_insights_release.py')
        self.builder.ROOT = f.builder.ROOT
        shutil.copyfile(ROOT / 'backend/boss_insights.py', self.builder.ROOT / 'backend/boss_insights.py')
        self.old = (self.builder.BASE.parents[1] / 'source/boss_insights.py').read_bytes()
        self.assertEqual(hashlib.sha256(self.old).hexdigest(), self.builder.BEFORE)
        f.write(self.builder.TARGET, self.old)
        self.dependencies = []
        for path in sorted(self.builder.SHARED):
            data = f.protected.get(path, b'protected-shared-file')
            f.write(path, data)
            f.protected[path] = data
            self.dependencies.append({'path': path, 'sha256': hashlib.sha256(data).hexdigest()})
        self.dependencies.append({'path': self.builder.TARGET, 'sha256': self.builder.BEFORE})
        self.depfile = self.builder.ROOT / 'coordination/single-dependencies.json'
        self.depfile.write_text(json.dumps(self.dependencies))
        with contextlib.redirect_stdout(io.StringIO()): self.builder.build(self.depfile)
        f.stage = self.builder.ROOT / 'insights-release'
        f.publisher = load('single_insights_publisher', f.stage / 'release_navigation.py')
        f.manifest = json.loads((f.stage / 'approved-manifest.json').read_text())
        f.manifest['releaseReady'] = True
        f.write('/var/www/dashboard/fs-home/transactions/collector.lock', b'')
        def systemctl(argv, **kwargs):
            if argv[:2] == ['systemctl', 'show']: return f.systemctl(argv, **kwargs)
            f.actions.append(argv)
            self.assertIn(argv, [['systemctl', 'restart', 'fs-business-range.service'],
                                 ['systemctl', 'is-active', '--quiet', 'fs-business-range.service']])
            return types.SimpleNamespace(returncode=0)
        def health(url, timeout):
            self.assertEqual(url, 'http://127.0.0.1:8931/health')
            self.assertEqual(timeout, 1)
            return io.BytesIO(b'{"ok":true}')
        patches = [patch.object(f.publisher.subprocess, 'run', systemctl),
                   patch.object(f.publisher.urllib.request, 'urlopen', health)]
        if os.name == 'nt':
            patches.append(patch.object(f.publisher, 'directory_sync', lambda path: self.assertTrue(path.is_dir())))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_one_file_apply_rollback_and_range_only_restart(self):
        f = self.fixture
        self.assertEqual(len(f.manifest['files']), 1)
        self.assertEqual(f.manifest['files'][0]['target'], self.builder.TARGET)
        result = f.apply()
        backup = Path(result['backup'])
        self.assertEqual((backup / 'files' / self.builder.CANDIDATE).read_bytes(), self.old)
        self.assertEqual(f.publisher.digest(f.root / self.builder.TARGET.lstrip('/')), f.manifest['files'][0]['sha256'])
        f.publisher.rollback(backup, f.sha, f.root)
        self.assertEqual((f.root / self.builder.TARGET.lstrip('/')).read_bytes(), self.old)
        self.assertEqual(len(f.actions), 4)
        f.assert_preserved()

    def test_target_baseline_and_all_four_dependency_drift_rejected(self):
        f = self.fixture
        for path in [self.builder.TARGET, *sorted(self.builder.SHARED)]:
            original = (f.root / path.lstrip('/')).read_bytes()
            f.write(path, b'parallel-change')
            with self.assertRaises(ValueError): f.apply()
            f.write(path, original)
        self.assertEqual(f.actions, [])

    def test_exact_manifest_scope_and_required_protection(self):
        f = self.fixture
        for variant in ('before', 'extra', 'target', 'protected', 'runtime'):
            m = copy.deepcopy(f.manifest)
            if variant == 'before': m['files'][0]['beforeSha256'] = None
            elif variant == 'extra': m['files'].append(copy.deepcopy(m['files'][0]))
            elif variant == 'target': m['files'][0]['target'] = '/opt/other.py'
            elif variant == 'protected': m['unchangedRequired'] = [r for r in m['unchangedRequired'] if r['path'] not in self.builder.SHARED]
            else: m['runtimeRequired'] = {}
            with self.assertRaises(ValueError): f.publisher.validate(m, f.stage)

    def test_builder_rejects_missing_or_invalid_shared_hash(self):
        for variant in ('missing', 'hash', 'before'):
            deps = copy.deepcopy(self.dependencies)
            if variant == 'missing': deps.pop(0)
            elif variant == 'hash': deps[0]['sha256'] = 'bad'
            else: deps[-1]['sha256'] = '0' * 64
            self.depfile.write_text(json.dumps(deps))
            with self.assertRaises(ValueError): self.builder.build(self.depfile)


if __name__ == '__main__':
    unittest.main(verbosity=2)

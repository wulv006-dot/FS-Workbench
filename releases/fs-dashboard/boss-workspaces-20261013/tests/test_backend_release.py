"""Isolated eight-file publisher checks; Windows POSIX metadata is simulated."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackendRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.root = self.work / 'live'
        self.root.mkdir()
        self.builder = load('boss_builder_test', ROOT / 'build_backend_release.py')
        self.builder.ROOT = self.work / 'fixture'
        for directory in ('backend', 'deploy', 'source/management'):
            dest = self.builder.ROOT / directory
            dest.mkdir(parents=True)
        for name in self.builder.TARGETS:
            leaf = name.split('/')[-1]
            relative = ('deploy/' + leaf if name.startswith('units/') else
                        'source/management/targets.json' if leaf == 'targets.json' else 'backend/' + leaf)
            shutil.copyfile(ROOT / relative, self.builder.ROOT / relative)
        self.protected = {'/var/www/dashboard/index.html': b'original-business-html',
                          '/etc/localtime': b'fake-shanghai-zone',
                          '/opt/fs-exact-range-20261001/fc_daily.py': b'fake-shared-ledger-source',
                          '/opt/fs-exact-range-20261001/fc_daily_model.py': b'fake-model-definition',
                          '/opt/fs-exact-range-20261001/ai_advisor_model.py': b'fake-provider-source'}
        for path, data in self.protected.items():
            self.write(path, data)
        baseline = self.builder.ROOT / 'baseline/live.json'
        baseline.parent.mkdir()
        model_path = '/opt/fs-exact-range-20261001/fc_daily_model.py'
        baseline.write_text(json.dumps({'files': {model_path: {'sha256': hashlib.sha256(self.protected[model_path]).hexdigest()}},
                            'protected_hashes': {'/var/www/dashboard/index.html':
                            hashlib.sha256(self.protected['/var/www/dashboard/index.html']).hexdigest()}}))
        (baseline.parent / 'scheduler.json').write_text(json.dumps({'timezone': 'Asia/Shanghai', 'systemd_version': 219,
            'localtime_sha256': hashlib.sha256(self.protected['/etc/localtime']).hexdigest()}))
        dependency = self.builder.ROOT / 'coordination/backend-dependency.json'
        dependency.parent.mkdir()
        dependency.write_text(json.dumps([{'path': path, 'sha256': hashlib.sha256(data).hexdigest()}
                                         for path, data in self.protected.items() if path.startswith('/opt/') and path != model_path]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.builder.build()
        self.stage = self.builder.ROOT / 'backend-release'
        self.publisher = load('boss_publisher_test', self.stage / 'release_navigation.py')
        self.manifest = json.loads((self.stage / 'approved-manifest.json').read_text())
        self.manifest['releaseReady'] = True
        self.links = {}
        for unit in ('dashboard-pipeline.service', 'dashboard-publish.service', 'dashboard-fallback.service'):
            path = self.write('/etc/systemd/system/' + unit, b'/dev/null')
            self.links[path] = PurePosixPath('/dev/null')
            if os.name != 'nt':
                path.unlink()
                path.symlink_to('/dev/null')
        self.sentinels = {self.write(path, b'existing-data'): b'existing-data' for path in (
            '/var/lib/fs-boss-workspaces/journal/game-monitor/old.json',
            '/var/lib/fs-boss-workspaces/public/game-monitor.json',
            '/var/lib/fs-boss-workspaces/history/management/old.json',
            '/var/lib/fs-business-ranges/fc-daily/model.sqlite3',
            '/opt/release-radar/data/events.json')}
        self.actions = []
        self.reload_failure = False
        self.active = True
        patches = [patch.object(self.publisher.subprocess, 'run', self.systemctl)]
        if os.name == 'nt':
            original_stat, original_link, original_readlink = Path.stat, Path.is_symlink, Path.readlink
            def posix_stat(path, *args, **kwargs):
                info = original_stat(path, *args, **kwargs)
                values = list(info)
                values[0] &= ~0o022
                values[4] = values[5] = 0
                return os.stat_result(values)
            import msvcrt
            def flock(fd, flags):
                self.assertEqual(flags, 6)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            patches += [patch.object(Path, 'stat', posix_stat),
                        patch.object(Path, 'is_symlink', lambda path: path in self.links or original_link(path)),
                        patch.object(Path, 'readlink', lambda path: self.links[path] if path in self.links else original_readlink(path)),
                        patch.object(os, 'geteuid', lambda: 0, create=True),
                        patch.dict(sys.modules, {'fcntl': types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=flock)}),
                        patch.object(self.publisher, 'directory_sync', lambda path: self.assertTrue(path.is_dir()))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def write(self, relative, data):
        path = self.root / relative.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def systemctl(self, argv, **kwargs):
        if argv[:2] == ['systemctl', 'show']:
            text = ('ActiveState=' + ('active' if self.active else 'inactive') + '\n'
                    if argv[2] == 'fs-business-range.service' else 'UnitFileState=disabled\nActiveState=inactive\n')
            return types.SimpleNamespace(returncode=0, stdout=text, stderr='')
        self.actions.append(argv)
        self.assertEqual(argv, ['systemctl', 'daemon-reload'])
        if self.reload_failure:
            self.reload_failure = False
            raise RuntimeError('injected daemon-reload failure')
        return types.SimpleNamespace(returncode=0)

    def apply(self):
        self.raw = json.dumps(self.manifest).encode()
        self.sha = hashlib.sha256(self.raw).hexdigest()
        return self.publisher.apply(self.manifest, self.stage, self.sha, self.raw,
                                    'nav-20261013T010000Z', self.root)

    def assert_preserved(self):
        for path, data in self.sentinels.items():
            self.assertEqual(path.read_bytes(), data)
        for path, data in self.protected.items():
            self.assertEqual((self.root / path.lstrip('/')).read_bytes(), data)

    def test_exact_scope_and_preview_are_readonly(self):
        self.assertEqual(len(self.manifest['files']), 8)
        self.assertEqual({r['target'] for r in self.manifest['files']}, set(self.builder.TARGETS.values()))
        self.assertTrue(all(row['beforeSha256'] is None for row in self.manifest['files']))
        result = self.publisher.inspect(self.manifest, self.stage, self.root)
        self.assertEqual(result['staticFiles'], 8)
        self.assertFalse(result['mutations'])
        self.assertEqual(self.actions, [])
        self.assert_preserved()

    def test_apply_backup_and_rollback_only_daemon_reload(self):
        result = self.apply()
        backup = Path(result['backup'])
        self.assertEqual((backup / 'approved-manifest.json').read_bytes(), self.raw)
        for row in self.manifest['files']:
            self.assertEqual(self.publisher.digest(self.root / row['target'].lstrip('/')), row['sha256'])
        self.assertEqual(self.actions, [['systemctl', 'daemon-reload']])
        self.publisher.rollback(backup, self.sha, self.root)
        self.assertEqual(len(self.actions), 2)
        for row in self.manifest['files']:
            self.assertFalse((self.root / row['target'].lstrip('/')).exists())
            self.assertTrue((backup / 'removed-new-files' / row['candidate']).is_file())
        self.assert_preserved()

    def test_scope_target_and_existing_baseline_rejected(self):
        for change in ('scope', 'target', 'before'):
            m = copy.deepcopy(self.manifest)
            if change == 'scope': m['scope'] = 'fc-daily-20261013'
            elif change == 'target': m['files'][0]['target'] = '/etc/unsafe'
            else: m['files'][0]['beforeSha256'] = 'a' * 64
            with self.assertRaises(ValueError): self.publisher.validate(m, self.stage)

    def test_candidate_hash_and_target_absence_cas(self):
        row = self.manifest['files'][0]
        candidate = self.stage / 'candidate' / row['candidate']
        old = candidate.read_bytes()
        candidate.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.apply()
        candidate.write_bytes(old)
        self.write(row['target'], b'parallel-owner-change')
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.actions, [])
        self.assert_preserved()

    def test_dependency_and_runtime_drift_block(self):
        for path in ('/opt/fs-exact-range-20261001/fc_daily.py', '/opt/fs-exact-range-20261001/fc_daily_model.py'):
            self.write(path, b'drift')
            with self.assertRaises(ValueError): self.apply()
            self.write(path, self.protected[path])
        self.active = False
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.actions, [])

    def test_daemon_reload_failure_rolls_back_without_starting_tasks(self):
        self.reload_failure = True
        with self.assertRaisesRegex(RuntimeError, 'daemon-reload'): self.apply()
        self.assertEqual(self.actions, [['systemctl', 'daemon-reload']] * 2)
        self.assertTrue(all(not (self.root / row['target'].lstrip('/')).exists() for row in self.manifest['files']))
        self.assert_preserved()

    def prepare_update(self):
        previous = self.stage / 'approved-manifest.json'
        previous.write_text(json.dumps(self.manifest))
        previous_raw = previous.read_bytes()
        self.original_sources = {}
        for row in self.manifest['files']:
            data = (self.stage / 'candidate' / row['candidate']).read_bytes()
            self.write(row['target'], data)
            self.original_sources[row['target']] = data
        source = self.builder.ROOT / 'backend/boss_daily.py'
        source.write_bytes(source.read_bytes() + b'\n# isolated candidate update\n')
        with contextlib.redirect_stdout(io.StringIO()):
            self.builder.build(update_from=previous)
        self.assertEqual(previous.read_bytes(), previous_raw)
        self.stage = self.builder.ROOT / 'backend-update-release'
        evidence = self.stage / ('previous-manifest.' + hashlib.sha256(previous_raw).hexdigest() + '.json')
        self.assertEqual(evidence.read_bytes(), previous_raw)
        self.publisher = load('boss_update_publisher_test', self.stage / 'release_navigation.py')
        if os.name == 'nt':
            item = patch.object(self.publisher, 'directory_sync', lambda path: self.assertTrue(path.is_dir()))
            item.start()
            self.addCleanup(item.stop)
        self.manifest = json.loads((self.stage / 'approved-manifest.json').read_text())
        self.assertFalse(self.manifest['releaseReady'])
        self.manifest['releaseReady'] = True

    def test_update_apply_and_rollback_preserve_exact_existing_bytes(self):
        self.prepare_update()
        self.assertEqual(self.manifest['scope'], self.builder.UPDATE_SCOPE)
        for row in self.manifest['files']:
            self.assertEqual(row['beforeSha256'], hashlib.sha256(self.original_sources[row['target']]).hexdigest())
        result = self.apply()
        backup = Path(result['backup'])
        for row in self.manifest['files']:
            self.assertEqual(self.publisher.digest(self.root / row['target'].lstrip('/')), row['sha256'])
            self.assertEqual((backup / 'files' / row['candidate']).read_bytes(), self.original_sources[row['target']])
        self.publisher.rollback(backup, self.sha, self.root)
        for path, data in self.original_sources.items():
            self.assertEqual((self.root / path.lstrip('/')).read_bytes(), data)
        self.assertEqual(self.actions, [['systemctl', 'daemon-reload']] * 2)
        self.assert_preserved()

    def test_update_before_drift_blocks_without_daemon_reload(self):
        self.prepare_update()
        self.write(self.manifest['files'][0]['target'], b'parallel-update')
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.actions, [])
        self.assert_preserved()

    def test_update_manifest_missing_before_hash_or_target_tamper_rejected(self):
        self.prepare_update()
        for value in (None, '', 'x' * 64):
            changed = copy.deepcopy(self.manifest)
            changed['files'][0]['beforeSha256'] = value
            with self.assertRaises(ValueError): self.publisher.validate(changed, self.stage)
        self.manifest['files'][0]['target'] = '/opt/other-module/source.py'
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.actions, [])

    def test_update_previous_manifest_requires_exact_approved_hashes_and_paths(self):
        original = self.stage / 'approved-manifest.json'
        original_bytes = original.read_bytes()
        for variant in ('missing_sha', 'bad_sha', 'target', 'extra', 'duplicate', 'scope', 'not_approved'):
            manifest = copy.deepcopy(self.manifest)
            if variant == 'missing_sha': del manifest['files'][0]['sha256']
            elif variant == 'bad_sha': manifest['files'][0]['sha256'] = 'not-a-sha'
            elif variant == 'target': manifest['files'][0]['target'] = '/etc/other-file'
            elif variant == 'extra': manifest['files'].append(copy.deepcopy(manifest['files'][0]))
            elif variant == 'duplicate': manifest['files'][1] = copy.deepcopy(manifest['files'][0])
            elif variant == 'scope': manifest['scope'] = 'fc-daily-20261013'
            else: manifest['releaseReady'] = False
            fake = self.work / 'invalid-approved.json'
            fake.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): self.builder.build(update_from=fake)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertFalse((self.builder.ROOT / 'backend-update-release').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)

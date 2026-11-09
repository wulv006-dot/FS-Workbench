"""Offline archive guards; never execute an installed publisher or service."""
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import importlib.util
import json
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def module(folder):
    spec = importlib.util.spec_from_file_location('archive_release', folder / 'release.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ArchiveContract(unittest.TestCase):
    def test_manifest_targets_hashes_and_range_only_hotfixes(self):
        for sub, count in (('', 41), ('curl-fix', 4), ('cardinality-fix', 1)):
            with self.subTest(sub=sub):
                folder = HERE / sub
                release = module(folder)
                manifest = json.loads((folder / 'manifest.json').read_text())
                targets = json.loads((folder / 'targets.json').read_text())
                self.assertEqual(len(targets), count)
                self.assertEqual(len(manifest['files']), count)
                self.assertEqual({r['candidate']: r['target'] for r in manifest['files']}, targets)
                self.assertEqual(len(set(targets.values())), count)
                self.assertFalse(manifest['businessWrites'])
                self.assertFalse(manifest['timersChanged'])
                for row in manifest['files']:
                    for key in ('sha256', 'beforeSha256'):
                        if key == 'beforeSha256' and row[key] is None:
                            self.assertEqual(sub, '')  # Initial release adds new files.
                            continue
                        self.assertRegex(row[key], r'^[0-9a-f]{64}$')
                self.assertEqual(len(release.PINS), 3)
                for digest in release.PINS.values():
                    self.assertRegex(digest, r'^[0-9a-f]{64}$')
                if sub:
                    self.assertEqual(release.UNITS, ('fs-business-range.service',))
                    self.assertEqual(release.TARGETS, targets)
                    self.assertEqual(release.ROLLBACK_BASELINES,
                                     {r['target']: r['beforeSha256'] for r in manifest['files']})

    def test_publisher_drift_rejected_before_execution(self):
        for sub in ('', 'curl-fix', 'cardinality-fix'):
            release = module(HERE / sub)
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name in release.PINS:
                    (root / name).write_text('raise AssertionError("must not execute")')
                with patch.object(release, 'PUBLISHER', root):
                    with self.assertRaisesRegex(ValueError, 'existing_publisher_drift'):
                        release.load(HERE / sub)

    def test_original_cas_and_manifest_bytes_forwarded(self):
        for sub in ('', 'curl-fix', 'cardinality-fix'):
            release = module(HERE / sub)
            base = SimpleNamespace(apply=Mock(return_value={'ok': True}))
            with patch.object(release, 'load', return_value=base), patch.object(
                    release.sys, 'argv', ['release.py', 'apply', 'expected-manifest-hash', 'release-id']), redirect_stdout(StringIO()):
                release.main()
            args = base.apply.call_args.args
            self.assertEqual(args[2], 'expected-manifest-hash')
            self.assertEqual(args[3], (HERE / sub / 'manifest.json').read_bytes())
            self.assertEqual(args[4], 'release-id')

    def test_hotfix_rollback_rejects_wrong_baseline_before_delegate(self):
        for sub in ('curl-fix', 'cardinality-fix'):
            release = module(HERE / sub)
            original = Mock(return_value='rolled-back')
            base = SimpleNamespace(locks=lambda root: nullcontext(), hermes_quiescent=Mock(),
                                   atomic=Mock(), rollback_journal=original)
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'release_ui_finish.py').write_text('def publisher():\n    return fixture_base\n')
                # Inject only a synthetic publisher; the archived pin rejection is tested above.
                real_exec = exec
                def fixture_exec(code, scope):
                    scope['fixture_base'] = base
                    real_exec(code, scope)
                with patch.object(release, 'PUBLISHER', root), patch.object(release, 'PINS', {}), patch.object(release, 'exec', fixture_exec, create=True):
                    loaded = release.load(HERE / sub)
                rows = [{'candidate': key, 'target': target, 'beforeSha256': release.ROLLBACK_BASELINES[target]}
                        for key, target in release.TARGETS.items()]
                bad = [dict(row) for row in rows]
                bad[0]['beforeSha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'rollback_requires_pinned'):
                    loaded.rollback_journal(root, {'files': bad}, root)
                original.assert_not_called()
                self.assertEqual(loaded.rollback_journal(root, {'files': rows}, root), 'rolled-back')
                original.assert_called_once()


if __name__ == '__main__':
    unittest.main()

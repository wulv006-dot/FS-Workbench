import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import package

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location('package_adapter_contract', HERE.parent / 'publisher/adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class PackageTests(unittest.TestCase):
    def test_fixed_git_inputs_complete_manifest_and_baseline_cas(self):
        reads = []
        def read_git(path):
            reads.append(path)
            return (ROOT / path).read_bytes()
        original = b'# synthetic nginx baseline\n'
        with patch.object(package, 'prepare_nginx', return_value=original + b'# exact routes\n') as nginx:
            candidates, manifest = package.build('a' * 40, read_git, original)
        nginx.assert_called_once_with(original)
        self.assertEqual(set(candidates), set(adapter.TARGETS))
        self.assertEqual(len(reads), 10)
        self.assertEqual(len(set(reads)), 10)
        adapter.contract(manifest)
        for row in manifest['files']:
            self.assertEqual(row['sha256'], hashlib.sha256(candidates[row['candidate']]).hexdigest())
            self.assertEqual(row['target'], adapter.TARGETS[row['candidate']])
            if row['candidate'] == 'formal.locations.conf':
                self.assertEqual(row['beforeSha256'], hashlib.sha256(original).hexdigest())
            elif row['candidate'] in ('page.js', 'range_api.py', 'data-workspace.js'):
                raw = (HERE / 'fixtures' / row['candidate']).read_bytes()
                self.assertEqual(row['beforeSha256'], hashlib.sha256(raw).hexdigest())
            else:
                self.assertIsNone(row['beforeSha256'])
        self.assertEqual(manifest['sourceCommit'], 'a' * 40)

    def test_invalid_commit_does_not_read(self):
        for sha in ('main', 'a' * 39, 'A' * 40, None):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                package.build(sha, lambda _: self.fail('must reject before reading'), b'')

    def test_real_nginx_baseline_guard_propagates(self):
        with self.assertRaises(ValueError):
            package.build('a' * 40, lambda p: (ROOT / p).read_bytes(), b'wrong baseline')


if __name__ == '__main__':
    unittest.main()

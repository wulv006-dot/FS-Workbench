"""Exact nine-target publisher contract and rollback guards in temporary files."""
import ast
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('account_publisher', HERE / 'deploy/release_navigation.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-account-publisher-')
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'
        self.files = []
        for rel, target in publisher.ACCOUNT_TARGETS.items():
            source = self.stage / 'candidate' / rel
            source.parent.mkdir(parents=True, exist_ok=True); source.write_text('synthetic new code')
            old = publisher.rooted(self.root, target)
            old.parent.mkdir(parents=True, exist_ok=True)
            before = None
            if rel != 'account-runtime/account_management.py':
                old.write_text('synthetic old code'); before = publisher.digest(old)
            self.files.append(dict(candidate=rel, target=target, beforeSha256=before, sha256=publisher.digest(source)))
        self.manifest = dict(schemaVersion=1, scope=publisher.ACCOUNT_SCOPE, files=self.files, releaseReady=False,
            runtimeRequired={'auth-portal.service': {'ActiveState': 'active'}},
            unchangedRequired=[dict(path='/var/www/dashboard/index.html', sha256='a' * 64)])

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_nine_targets_and_unchanged_release_protections(self):
        self.assertEqual(9, len(publisher.validate(self.manifest, self.stage)))
        record = json.loads((HERE / 'deploy/publisher-derivation.json').read_text())
        base = (HERE / record['base']).read_text(encoding='utf-8')
        original = {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(base).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        changed = {node.name: ast.dump(node, include_attributes=False) for node in ast.parse((HERE / 'deploy/release_navigation.py').read_text()).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        touched = {name for name in original if original[name] != changed[name]}
        self.assertEqual({'expected_files', 'target_for', 'validate', 'rollback_journal', 'restart_for', 'apply'}, touched)
        for name in ('locks', 'guards', 'atomic', 'retirement', 'hermes_admission_fence', 'model_release_lock'):
            self.assertEqual(original[name], changed[name])

    def test_new_module_is_the_only_absent_target_allowed(self):
        self.files[0]['beforeSha256'] = None
        with self.assertRaises(ValueError):
            publisher.validate(self.manifest, self.stage)

    def test_unknown_scope_extra_file_and_tampered_source_fail(self):
        bad = dict(self.manifest, files=self.files + [dict(self.files[0])])
        with self.assertRaises(ValueError): publisher.validate(bad, self.stage)
        with self.assertRaises(ValueError): publisher.validate(dict(self.manifest, scope='unreviewed'), self.stage)
        (self.stage / 'candidate' / self.files[0]['candidate']).write_text('changed after review')
        with self.assertRaises(ValueError): publisher.validate(self.manifest, self.stage)

    def test_active_auth_and_business_protection_required(self):
        with self.assertRaises(ValueError): publisher.validate(dict(self.manifest, runtimeRequired={}), self.stage)
        with self.assertRaises(ValueError): publisher.validate(dict(self.manifest, unchangedRequired=[]), self.stage)

    def test_schema5_rollback_refused_before_restoring_code(self):
        path = publisher.rooted(self.root, '/opt/auth-portal/data/registration-approval/registration.sqlite3')
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA user_version=5')
        journal = dict(manifest=self.manifest, approvedManifestSha256='a' * 64, files=[])
        with patch.object(publisher, 'rollback_credentials'):
            with self.assertRaisesRegex(ValueError, 'pre-schema5'):
                publisher.rollback_journal(self.root / 'backup', journal, self.root)
        self.assertTrue(all(publisher.digest(publisher.rooted(self.root, row['target'])) == row['beforeSha256'] for row in self.files))

    def test_default_inspect_never_replaces_files(self):
        before = [publisher.digest(publisher.rooted(self.root, row['target'])) for row in self.files]
        with patch.object(publisher, 'guards'), patch.object(publisher, 'retirement'):
            result = publisher.inspect(self.manifest, self.stage, self.root)
        self.assertFalse(result['mutations'])
        self.assertEqual(before, [publisher.digest(publisher.rooted(self.root, row['target'])) for row in self.files])


if __name__ == '__main__':
    unittest.main()

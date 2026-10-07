"""Native root contract tests against actual frozen source bytes, no runtime fixture."""
import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'source'
ORIGINAL = SOURCE.parent.parent / 'player-supersession-20261007-v4-2' / 'source'
SOURCE_SHA = '8f97e23b3a63480fd8fd142ab977a85558203a7c7400739cb31186120b50c90f'
OLD_SOURCE_SHA = '540e45f50ec2357943fb5ffa5ffbeda349fe47546241198212b99a7c56ef147f'
digest = lambda raw: hashlib.sha256(raw).hexdigest()

def actual_bundle(root, wanted):
    files = {p.relative_to(root).as_posix(): p.read_bytes()
             for p in root.rglob('*') if p.is_file()}
    raw = files['SOURCE-MANIFEST.json']
    assert digest(raw) == wanted, 'actual_manifest_hash_changed'
    manifest = json.loads(raw)
    assert len(manifest['files']) == 25
    assert set(files) == set(manifest['files']) | {'SOURCE-MANIFEST.json'}
    for name, expected in manifest['files'].items():
        assert digest(files[name]) == expected, name
    dirs = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir()}
    return files, dirs, manifest

class ActualArtifactContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert sys.platform == 'linux' and os.geteuid() == 0 and os.getegid() == 0
        assert sys.version_info[:3] == (3, 9, 18), sys.version
        cls.files, cls.dirs, cls.manifest = actual_bundle(SOURCE, SOURCE_SHA)
        cls.old_files, cls.old_dirs, cls.old_manifest = actual_bundle(ORIGINAL, OLD_SOURCE_SHA)
        cls.namespace = {'__name__': 'approved_contract_validation'}
        exec(compile(cls.files['launch.py'], 'verified-inline-launch', 'exec'), cls.namespace)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='fc421-contract-', dir='/root'))
        os.chmod(self.root, 0o700)
        self.artifact = self.root / 'artifact'
        self.private = self.root / 'private'
        self.private.mkdir(mode=0o700)
        self.install(self.files)

    def tearDown(self):
        assert self.root.parent == Path('/root') and self.root.name.startswith('fc421-contract-')
        shutil.rmtree(self.root)

    def install(self, files):
        if self.artifact.exists():
            shutil.rmtree(self.artifact)
        self.artifact.mkdir(mode=0o700)
        for name, raw in files.items():
            target = self.artifact / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(raw)
            os.chown(target, 0, 11028)
            os.chmod(target, 0o640)

    def inline(self, wanted=None, launcher=None):
        result = subprocess.run([
            sys.executable, '-I', '-S', '-B', '-c',
            (launcher or self.files['launch.py']).decode('utf-8'),
            '--artifact', str(self.artifact),
            '--manifest-sha', wanted or digest((self.artifact / 'SOURCE-MANIFEST.json').read_bytes()),
            '--binding', str(self.private / 'intentionally-absent.json'),
            '--binding-sha', '0' * 64,
        ], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '', result.stderr)
        rows = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(rows), 1, result.stdout)
        report = json.loads(rows[0])
        self.assertEqual(report['status'], 'stopped_without_business_replay')
        self.assertEqual(report['business_posts'], 0)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'artifact', 'private'})
        self.assertEqual(list(self.private.iterdir()), [])
        return report

    def set_manifest(self, value):
        target = self.artifact / 'SOURCE-MANIFEST.json'
        target.write_bytes((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        os.chown(target, 0, 11028)
        os.chmod(target, 0o640)

    def test_actual_frozen_manifest_and_all_25_source_bytes_validate(self):
        validated = self.namespace['validate_bundle'](self.files, self.dirs, SOURCE_SHA)
        self.assertEqual(validated, self.manifest)
        self.assertEqual(set(validated), {'version', 'files', 'operation', 'business_replay'})

    def test_original_real_inline_failure_is_reproduced_without_synthetic_manifest(self):
        self.install(self.old_files)
        report = self.inline(OLD_SOURCE_SHA, self.old_files['launch.py'])
        self.assertEqual(report['reason'], 'source_manifest_schema_invalid')

    def test_fixed_real_inline_passes_bundle_and_requires_actual_private_binding(self):
        # FileNotFoundError is at the binding read after full bundle validation.
        # This is deliberately not a successful runtime preflight claim.
        report = self.inline(SOURCE_SHA)
        self.assertEqual(report['reason'], 'FileNotFoundError')

    def test_inline_rejects_every_wrong_schema_semantic_before_binding_read(self):
        def altered(key, value):
            item = json.loads(self.files['SOURCE-MANIFEST.json'])
            item[key] = value
            return item
        cases = [
            ('wrong_operation', altered('operation', 'different_operation')),
            ('wrong_operation_type', altered('operation', None)),
            ('business_replay_true', altered('business_replay', True)),
            ('business_replay_zero', altered('business_replay', 0)),
            ('business_replay_string', altered('business_replay', 'false')),
            ('wrong_version', altered('version', 5)),
            ('float_version', altered('version', 4.0)),
            ('non_dict_files', altered('files', [])),
            ('non_object_manifest', []),
        ]
        for key in ['version', 'files', 'operation', 'business_replay']:
            item = json.loads(self.files['SOURCE-MANIFEST.json'])
            item.pop(key)
            cases.append(('missing_' + key, item))
        item = json.loads(self.files['SOURCE-MANIFEST.json'])
        item['unexpected'] = False
        cases.append(('extra_field', item))
        item = json.loads(self.files['SOURCE-MANIFEST.json'])
        item.pop('operation'); item.pop('business_replay')
        cases.append(('legacy_two_field_contract', item))
        self.assertEqual(len(cases), 15)
        for label, value in cases:
            with self.subTest(case=label):
                self.set_manifest(value)
                self.assertEqual(self.inline()['reason'], 'source_manifest_schema_invalid')

    def test_inline_rejects_manifest_sha_change_before_schema(self):
        self.assertEqual(self.inline('0' * 64)['reason'], 'source_manifest_changed')

    def test_inline_rejects_changed_candidate_before_candidate_import(self):
        target = self.artifact / 'runner.py'
        target.write_bytes(target.read_bytes() + b'\nraise RuntimeError("must never execute")\n')
        self.assertEqual(self.inline(SOURCE_SHA)['reason'], 'candidate_hash_changed_before_import')

    def test_inline_rejects_extra_shadow_file(self):
        target = self.artifact / 'datetime.py'
        target.write_bytes(b'raise RuntimeError("must never execute")\n')
        os.chown(target, 0, 11028); os.chmod(target, 0o640)
        self.assertEqual(self.inline(SOURCE_SHA)['reason'], 'artifact_extra_or_missing_entry')

    def test_inline_rejects_extra_directory(self):
        (self.artifact / 'leftovers').mkdir(mode=0o700)
        self.assertEqual(self.inline(SOURCE_SHA)['reason'], 'artifact_extra_or_missing_entry')

    def test_only_launcher_payload_changed_and_manifest_tracks_it(self):
        self.assertEqual(set(self.manifest['files']), set(self.old_manifest['files']))
        changed = {name for name in self.manifest['files']
                   if self.files[name] != self.old_files[name]}
        self.assertEqual(changed, {'launch.py'})
        self.assertEqual(self.manifest['files']['launch.py'], digest(self.files['launch.py']))
        for name in set(self.manifest['files']) - {'launch.py'}:
            self.assertEqual(self.manifest['files'][name], self.old_manifest['files'][name])
        for key in ['version', 'operation', 'business_replay']:
            self.assertEqual(self.manifest[key], self.old_manifest[key])

    def test_private_contract_auditor_requires_real_binding_without_generating_one(self):
        audit = SOURCE.parent / 'private_contract_audit.py'
        result = subprocess.run([
            sys.executable, '-I', '-S', '-B', str(audit),
            '--artifact', str(self.artifact),
            '--binding', str(self.private / 'intentionally-absent.json'),
            '--binding-sha', '0' * 64,
        ], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        report = json.loads(result.stdout)
        self.assertEqual(report['reason'], 'FileNotFoundError')
        self.assertEqual(report['business_posts'], 0)
        self.assertEqual(report['metadata_writes'], 0)
        self.assertEqual(list(self.private.iterdir()), [])

    def test_actual_binding_schema_declares_launcher_runner_literal_scope_fields(self):
        # Structural audit only; no fake binding is treated as real server evidence.
        schema = json.loads(self.files['BINDING-SCHEMA.json'])
        self.assertEqual(schema['version'], 4)
        declared = set(schema['required_types'])
        self.assertEqual(len(declared), 38)
        self.assertTrue(set(schema['required_types'].values()) <= {'str', 'int', 'bool', 'dict', 'list'})
        for filename in ['launch.py', 'runner.py']:
            parsed = ast.parse(self.files[filename].decode('utf-8'), feature_version=(3, 9))
            used = set()
            for node in ast.walk(parsed):
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'scope':
                    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        used.add(node.slice.value)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == 'scope' and node.func.attr == 'get':
                        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            used.add(node.args[0].value)
            self.assertTrue(used <= declared, (filename, sorted(used - declared)))
        self.assertEqual(self.files['BINDING-SCHEMA.json'], self.old_files['BINDING-SCHEMA.json'])
        self.assertEqual(self.files['runner.py'], self.old_files['runner.py'])

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ActualArtifactContractTests)
    expected_count = 11
    assert suite.countTestCases() == expected_count
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({
        'phase': 'actual_artifact_inline_contract',
        'python': sys.version,
        'uid': os.geteuid(),
        'gid': os.getegid(),
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'negative_schema_cases': 15,
        'source_manifest_sha256': SOURCE_SHA,
        'old_source_manifest_sha256': OLD_SOURCE_SHA,
        'production_access': False,
        'real_runtime_binding_validated': False,
        'business_posts': 0,
    }, sort_keys=True))
    if not result.wasSuccessful() or result.testsRun != expected_count or result.skipped:
        raise SystemExit(1)

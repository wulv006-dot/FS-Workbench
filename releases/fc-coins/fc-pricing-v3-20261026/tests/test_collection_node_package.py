import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))


class NodePackage(unittest.TestCase):
    def test_exported_control_accepts_explicit_recheck_and_refuses_missing_original_state(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_collection_node', root / 'deploy/build_collection_node.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            bundle = folder / 'control.zip'
            builder.build(bundle, 'control')
            with zipfile.ZipFile(bundle) as archive:
                code = folder / 'code'
                archive.extractall(code)
            missing = folder / 'missing-state'
            result = subprocess.run([sys.executable, '-I', '-B', str(code / 'entry.py'), 'unused-config',
                str(missing), 'original-recheck', '--recheck-of', 'original'], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'pilot_original_required', result.stderr)
            self.assertFalse(missing.exists())

    def test_exported_node_can_report_health_over_real_subprocess_pipes(self):
        from fc_collection.ssh_client import Session
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_collection_node', root / 'deploy/build_collection_node.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            bundle = folder / 'node.zip'
            builder.build(bundle)
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(set(archive.namelist()), {'manifest.json', 'entry.py'} | {
                    'fc_collection/' + name for name in ('__init__.py', 'contracts.py', 'worker.py', 'adapters.py',
                                                       'protocol.py', 'public_sources.py', 'server.py', 'lootbar.py', 'package_reader.py')})
                code = folder / 'code'
                archive.extractall(code)
            (folder / 'node.json').write_text(json.dumps(dict(node_id='187', spool=str(folder / 'spool'),
                                                              socket=str(folder / 'unused.sock'))))
            digest = hashlib.sha256((code / 'manifest.json').read_bytes()).hexdigest()
            with Session([sys.executable, '-I', '-B', str(code / 'entry.py'), 'stdio'], max_seconds=10) as session:
                result = session.health('187', digest)
                self.assertEqual(result['adapters']['ArabUT'], 'arab-public-quote-collection-v3')
                self.assertEqual(result['adapters']['Lootbar'], 'lootbar-public-browser-v1')
                self.assertEqual('U4GM' in result['adapters'], 'IGGM' in result['adapters'])
                session.send(dict(method='shell', command='must-not-execute'))
                message = session.read()
                self.assertEqual(message['kind'], 'error')

    def test_node_builder_never_overwrites_existing_artifact(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_collection_node', root / 'deploy/build_collection_node.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'keep.zip'
            output.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                builder.build(output)
            self.assertEqual(output.read_bytes(), b'keep')

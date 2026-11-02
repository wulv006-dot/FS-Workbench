import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))


class NodePackage(unittest.TestCase):
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
                                                       'protocol.py', 'public_sources.py', 'server.py')})
                code = folder / 'code'
                archive.extractall(code)
            (folder / 'node.json').write_text(json.dumps(dict(node_id='187', spool=str(folder / 'spool'),
                                                              socket=str(folder / 'unused.sock'))))
            digest = hashlib.sha256((code / 'manifest.json').read_bytes()).hexdigest()
            with Session([sys.executable, '-I', '-B', str(code / 'entry.py'), 'stdio'], max_seconds=10) as session:
                result = session.health('187', digest)
                self.assertEqual(result['adapters'], {'ArabUT': 'arab-public-quote-collection-v1'})
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

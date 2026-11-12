from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch


class WorkerPackage(unittest.TestCase):
    def test_package_has_only_worker_modules_and_exact_lootbar_activity_source(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_collection_worker', root / 'deploy/build_collection_worker.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'worker.zip'
            builder.build(output)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertNotIn('fc_collection/coordinator.py', names)
                self.assertEqual(names, {
                    'fc_collection/__init__.py', 'fc_collection/contracts.py', 'fc_collection/worker.py',
                    'fc_collection/adapters.py', 'lootbar/lootbar_server_collector.py',
                    'lootbar/background.js', 'manifest.json'})
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['lootbar']['lootbar_server_collector.py'],
                    'a950c08208df92a40183cbcbe0ea73b7c22e8d79f386336239f6d27079642384')
                self.assertFalse(manifest['production_ready'])
                self.assertEqual(manifest['credentials'], [])
                # Loading the exported parser needs no Chrome extension API or storage.
                subprocess.run(['node', '-e', "require('vm').runInNewContext(require('fs').readFileSync(0,'utf8'),{})"],
                               input=archive.read('lootbar/background.js'), check=True, timeout=10)
                archive.extractall(Path(folder) / 'unpacked')
                subprocess.run([sys.executable, '-I', '-B', '-c',
                    'import sys;sys.path.insert(0,sys.argv[1]);from fc_collection.worker import Worker',
                    str(Path(folder)/'unpacked')], check=True, capture_output=True, timeout=10)
                reader_spec = importlib.util.spec_from_file_location('exported_lootbar',
                    Path(folder) / 'unpacked/lootbar/lootbar_server_collector.py')
                reader = importlib.util.module_from_spec(reader_spec)
                with patch.dict(os.environ, {}, clear=True):
                    reader_spec.loader.exec_module(reader)
                self.assertTrue(callable(reader.load_reader))
                self.assertTrue(reader.load_reader().startswith('function readVisibleOffer()'))
                with self.assertRaisesRegex(reader.CollectionError, 'owned_browser_endpoint_required'):
                    reader._collect_attached()

    def test_existing_output_is_never_overwritten(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_collection_worker', root / 'deploy/build_collection_worker.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'worker.zip'
            output.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                builder.build(output)
            self.assertEqual(output.read_bytes(), b'existing')

import base64
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NodeInstall(unittest.TestCase):
    def test_private_operator_umask_does_not_hide_code_from_low_privilege_worker(self):
        installer = load('install_collection_node')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'new-role'
            old = os.umask(0o077)
            try:
                installer.code_directories(root)
            finally:
                os.umask(old)
            for path in (root, root / 'code', root / 'code/fc_collection'):
                self.assertTrue(path.is_dir())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o555, 0o555)

    def test_controller_role_cannot_be_installed_as_worker(self):
        installer = load('install_collection_node')
        builder = load('build_collection_node')
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / 'controller.zip'
            builder.build(bundle, 'control')
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            files = installer.read_bundle(bundle, digest, 'control')
            self.assertIn('fc_collection/coordinator.py', files)
            self.assertIn('fc_collection/worker.py', files)
            self.assertNotIn('fc_collection/server.py', files)
            self.assertNotIn('fc_pricing_v3/sources.py', files)
            with self.assertRaises(ValueError):
                installer.read_bundle(bundle, digest)

    def test_controller_host_key_must_match_the_trusted_183_fingerprint(self):
        from unittest.mock import patch
        controller = load('prepare_collection_control')
        wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 ' + b'k' * 32
        key = 'ssh-ed25519 ' + base64.b64encode(wire).decode()
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(wire).digest()).decode().rstrip('=')
        with self.assertRaises(ValueError):
            controller.host_key(key)
        with patch.object(controller, 'EXPECTED_HOST_KEY', fingerprint):
            self.assertEqual(controller.host_key(key), key)

    def test_only_exact_hashed_node_package_can_be_prepared(self):
        installer = load('install_collection_node')
        builder = load('build_collection_node')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'node.zip'
            builder.build(output)
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            files = installer.read_bundle(output, digest)
            self.assertIn('entry.py', files)
            with self.assertRaises(ValueError):
                installer.read_bundle(output, '0' * 64)
            malicious = Path(folder) / 'bad.zip'
            with zipfile.ZipFile(malicious, 'w') as archive:
                archive.writestr('../escape.py', 'untrusted')
            with self.assertRaises(ValueError):
                installer.read_bundle(malicious, hashlib.sha256(malicious.read_bytes()).hexdigest())

    def test_public_key_options_or_multiple_keys_cannot_change_forced_command(self):
        installer = load('install_collection_node')
        wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 ' + b'k' * 32
        key = 'ssh-ed25519 ' + base64.b64encode(wire).decode()
        self.assertEqual(installer.public_key(key + ' comment'), key)
        for value in ('command="sh" ' + key, key + '\n' + key, 'ssh-ed25519 invalid'):
            with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                installer.public_key(value)

    def test_existing_owned_file_is_preserved_on_conflicting_input(self):
        installer = load('install_collection_node')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'keep'
            path.write_bytes(b'original')
            with self.assertRaises(ValueError):
                installer.write_exact(path, b'other', 0o600)
            self.assertEqual(path.read_bytes(), b'original')

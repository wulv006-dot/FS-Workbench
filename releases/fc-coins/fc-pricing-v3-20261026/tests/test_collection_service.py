from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))


class ServiceBoundary(unittest.TestCase):
    def test_health_rejects_remote_root_worker_even_with_matching_digest(self):
        from fc_collection.ssh_client import Session
        session = object.__new__(Session)
        session.send = lambda _: None
        session.read = lambda: dict(kind='health', protocol=1, node_id='183', node_boot_id='a' * 32,
            worker_digest='b' * 64, adapters={'ArabUT': 'arab-public-quote-collection-v3'},
            clock_utc=datetime.now(timezone.utc).isoformat(), uid=0)
        with self.assertRaisesRegex(ValueError, 'health'):
            session.health('183', 'b' * 64)

    def test_ssh_client_rejects_writable_credentials_or_host_trust(self):
        from fc_collection.ssh_client import ssh_command
        config = dict(host='172.18.108.183', user='fs-fc-collector', identity_file='/private/id_ed25519',
                      known_hosts='/private/known_hosts', worker_digest='b' * 64)
        class Unsafe:
            def __init__(self, name):
                self.name = name
            def is_absolute(self):
                return True
            def is_symlink(self):
                return False
            def is_file(self):
                return True
            def stat(self):
                from types import SimpleNamespace
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_uid=0, st_nlink=1)
        with patch('fc_collection.ssh_client.os.name', 'posix'), patch('fc_collection.ssh_client.Path', Unsafe), \
                self.assertRaisesRegex(ValueError, 'file'):
            ssh_command(config)

    def test_service_reports_same_boot_and_no_business_capability(self):
        from fc_collection.protocol import read_message, write_message
        from fc_collection.server import Collector
        with tempfile.TemporaryDirectory() as folder:
            collector = Collector('183', Path(folder) / 'spool', 'a' * 64)
            answers = []
            for _ in range(2):
                request, response = BytesIO(), BytesIO()
                write_message(request, {'method': 'health'})
                request.seek(0)
                collector.handle(request, response)
                response.seek(0)
                answers.append(read_message(response))
            self.assertEqual(answers[0]['node_boot_id'], answers[1]['node_boot_id'])
            self.assertEqual(answers[0]['adapters'], {'ArabUT': 'arab-public-quote-collection-v3'})
            request = BytesIO(b'{"method":"shell","command":"id"}\n')
            with self.assertRaises(ValueError):
                collector.handle(request, BytesIO())

    def test_verified_manifest_rejects_changed_code_before_serving(self):
        import hashlib
        from fc_collection.server import verified_manifest
        files = {'fc_collection/' + name for name in ('__init__.py', 'contracts.py', 'worker.py',
            'adapters.py', 'protocol.py', 'public_sources.py', 'server.py')} | {'entry.py'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hashes = {}
            for name in files:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
                hashes[name] = hashlib.sha256(b'fixture').hexdigest()
            (root / 'manifest.json').write_text(json.dumps(dict(sha256=hashes)))
            self.assertEqual(len(verified_manifest(root)), 64)
            (root / 'fc_collection/contracts.py').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                verified_manifest(root)

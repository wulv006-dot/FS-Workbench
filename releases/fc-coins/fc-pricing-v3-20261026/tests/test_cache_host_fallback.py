"""A successful host cache clear must replace the container's failed stdout receipt."""
import ast
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
import uuid

SOURCE = Path(__file__).resolve().parents[1] / 'source'
IDENT = '00000000-0000-4000-8000-000000000001'


def functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class CacheHostFallback(unittest.TestCase):
    def parser(self):
        namespace = dict(json=json, hashlib=hashlib, re=re, uuid=uuid, datetime=datetime, timezone=timezone)
        return functions(SOURCE / 'clear_cache_after_write.py', ['response_details', 'host_receipt'], namespace)['host_receipt']

    def test_json_whitespace_and_http_success_produce_standard_cleared_receipt(self):
        result = self.parser()(IDENT, b'{"code": 1, "msg": "ok", "data": {"token": "do-not-export"}}\n200')
        self.assertEqual(result['status'], 'cleared')
        self.assertEqual(result['scope'], 'all')
        self.assertTrue(result['host_fallback'])
        self.assertEqual(result['responses'][0]['api_code'], 1)
        self.assertNotIn('do-not-export', json.dumps(result))
        self.assertNotIn('token', json.dumps(result))

    def test_business_denial_bad_json_wrong_http_and_string_code_stay_unconfirmed(self):
        for raw in [b'{"code":0}\n200', b'{"code":401}\n200', b'not json\n200',
                    b'{"code":1}\n500', b'{"code":"1"}\n200', b'']:
            with self.subTest(raw=raw):
                self.assertEqual(self.parser()(IDENT, raw)['status'], 'unconfirmed')

    def test_existing_worker_accepts_fallback_receipt_without_public_price_check(self):
        result = self.parser()(IDENT, b'{"code": 1}\n200')
        namespace = dict(APP=Path('/opt/fc27-cloud-browser'), subprocess=subprocess,
                         run=Mock(return_value=(0, result)))
        worker = functions(SOURCE / 'fc27_cloud_worker.py', ['refresh_backend_cache'], namespace)
        self.assertEqual(worker['refresh_backend_cache']({'job_id': IDENT})['status'], 'cleared')
        namespace['run'].assert_called_once()

    def test_real_host_cli_needs_no_container_session_module(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'clear_cache_after_write.py'
            script.write_bytes((SOURCE / script.name).read_bytes())
            # The exact standalone host file has no image-only module installed beside it.
            for raw, expected in [(b'{"code": 1, "data": {"token": "do-not-export"}}\n200', 'cleared'),
                                  (b'{"code":1}\n500', 'unconfirmed'),
                                  (b'{"code":"1"}\n200', 'unconfirmed')]:
                with self.subTest(expected=expected, raw=raw):
                    result = subprocess.run([sys.executable, '-I', '-B', str(script), '--host-receipt', IDENT],
                                            input=raw, capture_output=True, cwd=root)
                    self.assertEqual(result.returncode, 0 if expected == 'cleared' else 2, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['status'], expected)
                    self.assertNotIn(b'do-not-export', result.stdout)
                    self.assertNotIn(b'ModuleNotFoundError', result.stderr)

    @unittest.skipUnless(Path('/bin/sh').exists(), 'shell integration also runs on Linux')
    def test_real_shell_host_success_replaces_failed_container_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'executions').mkdir(); (root / 'v3').mkdir()
            (root / 'executions' / (IDENT + '.json')).write_text('{}')
            fake = root / 'bin'; fake.mkdir()
            docker = fake / 'docker'; docker.write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"status":"unconfirmed","reason":"container_unavailable"}\'\nexit 2\n'); docker.chmod(0o700)
            # Transport and backend are fixtures; this test never reaches a production endpoint.
            curl = fake / 'curl'; curl.write_text('#!/bin/sh\nprintf \'%s\\n%s\' \'{"code": 1, "msg": "ok"}\' \'200\'\n'); curl.chmod(0o700)
            helper = root / 'clear_cache_after_write.py'
            helper.write_bytes((SOURCE / helper.name).read_bytes())
            shell = (SOURCE / 'clear_cache_after_write.sh').read_text(encoding='utf8')
            shell = shell.replace('/var/lib/fc27-cloud', str(root)).replace('/opt/python39/bin/python3', sys.executable).replace('/opt/fc27-cloud-browser/clear_cache_after_write.py', str(helper))
            result = subprocess.run(['/bin/sh', '-s', '--', IDENT], input=shell, text=True, capture_output=True,
                                    env=dict(os.environ, PATH=str(fake) + os.pathsep + os.environ['PATH']))
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual(json.loads(lines[0])['status'], 'unconfirmed')
            self.assertEqual(json.loads(lines[-1])['status'], 'cleared')


if __name__ == '__main__':
    unittest.main()

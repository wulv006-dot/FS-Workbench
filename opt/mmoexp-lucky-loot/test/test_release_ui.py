"""Execute the real static publisher in a redirected temporary filesystem."""
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class StaticRelease(unittest.TestCase):
    def test_static_apply_and_rollback_preserve_runtime_and_never_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            stage = sandbox / 'release'
            (stage / 'src').mkdir(parents=True)
            names = ('giveaway.html', 'giveaway.css', 'giveaway.js')
            expected = {}
            for base in ('opt/mmoexp-lucky-loot', 'opt/bot-console/static'):
                for name in names:
                    target = sandbox / base / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b'old-ui')
                    expected[str(target)] = hashlib.sha256(b'old-ui').hexdigest()
            sentinel = sandbox / 'opt/mmoexp-lucky-loot/state.enc'
            sentinel.write_bytes(b'current-encrypted-state')
            for name in names:
                (stage / 'src' / name).write_bytes(b'new-ui')
            (stage / 'expected.json').write_text(json.dumps(expected))
            spec = importlib.util.spec_from_file_location('ui_publisher', Path(__file__).parents[1] / 'deploy/release_v11.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.ROOT = stage
            module.MANIFEST = stage / 'receipt.json'
            real_open = builtins.open
            def mapped_path(value):
                value = str(value)
                return sandbox / value.lstrip('/') if value.startswith('/opt/') else Path(value)
            def mapped_open(value, *args, **kwargs):
                if str(value).startswith('/var/lock/'):
                    value = sandbox / 'publisher.lock'
                return real_open(value, *args, **kwargs)
            calls = []
            def run(*args):
                calls.append(args)
                return 'active'
            with patch.object(module, 'Path', mapped_path), patch.object(module, 'run', run), patch('builtins.open', mapped_open), patch.object(sys, 'argv', ['release_v11.py', 'apply', '--static-only']):
                module.main('apply')
                self.assertTrue(all(Path(target).read_bytes() == b'new-ui' for target in expected))
                self.assertEqual(sentinel.read_bytes(), b'current-encrypted-state')
                self.assertTrue(json.loads(module.MANIFEST.read_text())['static_only'])
                module.main('rollback')
            self.assertTrue(all(Path(target).read_bytes() == b'old-ui' for target in expected))
            self.assertEqual(sentinel.read_bytes(), b'current-encrypted-state')
            self.assertFalse(any(args[0] == 'systemctl' and args[1] != 'is-active' for args in calls))


if __name__ == '__main__':
    unittest.main()

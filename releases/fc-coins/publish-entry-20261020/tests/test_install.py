import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallDirectoryTests(unittest.TestCase):
    def run_function(self, path):
        script = (Path(__file__).parents[1] / 'install.sh').read_text()
        function = script.split('ensure_directory() {', 1)[1].split('\n}', 1)[0]
        shell = 'set -eu; die() { exit 1; }; say() { :; }; ensure_directory() {' + function + '\n}; ensure_directory "$1" 0755'
        return subprocess.run(['bash', '-c', shell, 'test', str(path)], capture_output=True)

    def test_existing_mode_and_owner_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing'
            path.mkdir(mode=0o700)
            before = path.stat()
            self.assertEqual(self.run_function(path).returncode, 0)
            after = path.stat()
            self.assertEqual((before.st_mode, before.st_uid, before.st_gid),
                             (after.st_mode, after.st_uid, after.st_gid))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'link'
            path.symlink_to(directory)
            self.assertNotEqual(self.run_function(path).returncode, 0)

    def test_regular_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file'
            path.write_text('unchanged')
            self.assertNotEqual(self.run_function(path).returncode, 0)
            self.assertEqual(path.read_text(), 'unchanged')

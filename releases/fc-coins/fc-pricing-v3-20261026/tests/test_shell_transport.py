"""Scripts shipped to Linux retain executable POSIX line endings and syntax."""
from pathlib import Path
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'source'


class ShellTransportTest(unittest.TestCase):
    def test_published_shell_scripts_are_lf_and_parse_on_linux(self):
        scripts = sorted(SOURCE.glob('*.sh'))
        self.assertEqual({script.name for script in scripts}, {
            'clear_cache_after_write.sh', 'execute_price.sh', 'reconcile_price.sh', 'restore_price.sh'})
        for script in scripts:
            with self.subTest(script=script.name):
                body = script.read_bytes()
                self.assertTrue(body.startswith(b'#!/bin/sh\n'))
                self.assertNotIn(b'\r', body)
                if Path('/bin/sh').exists():
                    result = subprocess.run(['/bin/sh', '-n', str(script)], capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


if __name__ == '__main__':
    unittest.main()

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import fcntl
from statistics_refresh import run


class StatisticsRefresh(unittest.TestCase):
    def setup_files(self, directory, code):
        root = Path(directory)
        state = root / 'state'
        state.mkdir(mode=0o700)
        (state / 'status.json').write_text(json.dumps({'schemaVersion': 1, 'lastSuccessfulRunAt': '2026-10-30T00:00:00Z'}))
        worker = root / 'worker.py'
        worker.write_text(code)
        return root, state, worker, root / 'job.lock'

    def test_success_partial_and_output_never_relays_private_subprocess_text(self):
        for exit_code, expected in [(0, 'success'), (2, 'partial'), (1, 'failed')]:
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                root, state, worker, lock = self.setup_files(directory, "import sys; print('fixture-private-token'); sys.stderr.write('fixture-private-token'); sys.exit(%d)" % exit_code)
                code, result = run(sys.executable, worker, state, lock)
                self.assertEqual(code, exit_code)
                self.assertEqual(result['status'], expected)
                self.assertNotIn('fixture-private-token', json.dumps(result))
                self.assertEqual(json.loads((state / 'status.json').read_text())['lastSuccessfulRunAt'], '2026-10-30T00:00:00Z')

    def test_real_single_instance_lock_does_not_start_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root, state, worker, lock = self.setup_files(directory, "raise RuntimeError('should not run')")
            with lock.open('w') as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                code, result = run(sys.executable, worker, state, lock)
                self.assertEqual(code, 75)
                self.assertEqual(result['status'], 'busy')

    def test_timeout_kills_descendant_and_retains_last_success(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'orphan-marker'
            child = "import time; from pathlib import Path; time.sleep(0.5); Path(%r).write_text('bad')" % str(marker)
            code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); time.sleep(30)" % child
            root, state, worker, lock = self.setup_files(directory, code)
            exit_code, result = run(sys.executable, worker, state, lock, timeout=0.1)
            self.assertEqual(exit_code, 124)
            self.assertEqual(result['reason'], 'RUN_TIMEOUT_OR_INTERRUPTED')
            saved = json.loads((state / 'status.json').read_text())
            self.assertEqual(saved['lastAttempt']['status'], 'failed')
            self.assertEqual(saved['lastSuccessfulRunAt'], '2026-10-30T00:00:00Z')
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_start_failure_is_recorded_without_destroying_prior_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root, state, worker, lock = self.setup_files(directory, '')
            code, result = run(root / 'missing-node', worker, state, lock)
            self.assertEqual(code, 1)
            self.assertEqual(result['reason'], 'RUN_START_FAILED')
            self.assertEqual(json.loads((state / 'status.json').read_text())['lastSuccessfulRunAt'], '2026-10-30T00:00:00Z')


if __name__ == '__main__':
    unittest.main()

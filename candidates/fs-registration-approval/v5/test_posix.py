"""Prepared POSIX failure tests; skipped on Windows, never claimed as Linux proof."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from integrated_server import Environment
import native_integration


@unittest.skipUnless(sys.platform.startswith('linux'),'requires existing local Linux runtime')
class PosixTests(unittest.TestCase):
    def test_open_failure_same_thread_reacquires_and_real_process_cannot_enter(self):
        import fcntl
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            env=Environment(root)
            try:
                p=Path(root)/'namespace.lock';p.unlink();p.mkdir()
                with self.assertRaises(OSError):
                    with env.namespace.fence(): self.fail('entered')
                self.assertEqual(getattr(env.namespace.depth,'value',0),0);p.rmdir()
                real=fcntl.flock
                with patch('fcntl.flock',wraps=real) as calls:
                    with env.namespace.fence():
                        with env.namespace.fence():pass
                        child=subprocess.run([sys.executable,'-c',"import sys,fcntl; f=open(sys.argv[1],'a+b');\ntry: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); print('BAD')\nexcept BlockingIOError: print('blocked')",str(p)],capture_output=True,text=True,timeout=10)
                        self.assertEqual(child.stdout.strip(),'blocked',child.stderr)
                    self.assertEqual(sum(c.args[1]==fcntl.LOCK_EX for c in calls.call_args_list),1)
            finally:env.close()
    def test_acquire_unlock_close_exceptions_reset_before_next_actual_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            env=Environment(root)
            try:
                real=fcntl.flock;close=os.close
                for stage in ('acquire','unlock','close'):
                    def fault(fd,mode):
                        if stage=='acquire' and mode==fcntl.LOCK_EX:raise OSError('synthetic acquire')
                        result=real(fd,mode)
                        if stage=='unlock' and mode==fcntl.LOCK_UN:raise OSError('synthetic post-unlock')
                        return result
                    def closing(fd):
                        close(fd)
                        if stage=='close':raise OSError('synthetic post-close')
                    with patch('fcntl.flock',side_effect=fault),patch.object(native_integration.os,'close',side_effect=closing):
                        with self.assertRaises(OSError):
                            with env.namespace.fence():pass
                    self.assertEqual(env.namespace.depth.value,0)
                    with patch('fcntl.flock',wraps=real) as calls:
                        with env.namespace.fence():pass
                        self.assertTrue(any(c.args[1]==fcntl.LOCK_EX for c in calls.call_args_list))
            finally:env.close()

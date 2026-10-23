"""Linux-only deployment contract: real process locks, no Docker or account access."""
import fcntl
from pathlib import Path
import os
import tempfile
import unittest


class LinuxRuntimeTests(unittest.TestCase):
    def child_try_lock(self,path,expected_busy):
        child=os.fork()
        if child==0:
            try:
                with path.open('a+b') as handle:
                    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);busy=False
                    except BlockingIOError:busy=True
                os._exit(0 if busy==expected_busy else 1)
            except BaseException:os._exit(2)
        _,status=os.waitpid(child,0)
        self.assertTrue(os.WIFEXITED(status))
        self.assertEqual(os.WEXITSTATUS(status),0)

    def test_other_process_cannot_take_active_job_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'job.lock'
            with path.open('a+b') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.child_try_lock(path,True)
            self.child_try_lock(path,False)


if __name__=='__main__':unittest.main(verbosity=2)


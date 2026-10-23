"""Linux-only deployment contract: real process locks, no Docker or account access."""
import fcntl
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LinuxRuntimeTests(unittest.TestCase):
    def test_other_process_cannot_take_active_job_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'job.lock'
            with path.open('a+b') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                code="import fcntl,sys\nf=open(sys.argv[1],'a+b')\ntry: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(0)\nsys.exit(1)"
                result=subprocess.run([sys.executable,'-c',code,str(path)],timeout=5)
                self.assertEqual(result.returncode,0)
            result=subprocess.run([sys.executable,'-c',"import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)",str(path)],timeout=5)
            self.assertEqual(result.returncode,0)


if __name__=='__main__':unittest.main(verbosity=2)

"""Linux-only physical admission gate in isolated CI; no network/provider."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import unittest,json
from unittest.mock import patch
from test_release import ReleaseTests

class AdmissionProcessTest(ReleaseTests):
    def setUp(self):
        super().setUp()
        # Always isolate service control, including a failing-test cleanup path.
        service_mock=patch.object(self.publisher.subprocess,'run')
        service_mock.start();self.addCleanup(service_mock.stop)

    def test_bootstrap_fence_blocks_legacy_writer_until_process_stops_and_new_admission_stays_closed(self):
        from contextlib import closing
        import sqlite3,subprocess,sys
        from controller import admission_guard
        path=self.root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE requests(state TEXT)')
        worker="import sqlite3,sys;db=sqlite3.connect(sys.argv[1],timeout=30);print('ready',flush=True);db.execute(\"INSERT INTO requests VALUES('PREPARING')\");db.commit();print('admitted',flush=True)"
        with self.publisher.hermes_admission_fence(self.update_manifest(),self.root) as fence:
            process=subprocess.Popen([sys.executable,'-c',worker,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            self.addCleanup(lambda:process.kill() if process.poll() is None else None)
            self.assertEqual(process.stdout.readline().strip(),'ready')
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)
            events=[]
            def systemctl(args,**unused):
                if args[1]=='stop':
                    self.assertIsNotNone(fence.db);process.terminate();process.wait(timeout=5);events.append('old_process_stopped')
                elif args[1]=='restart':
                    self.assertIsNone(fence.db);events.append('new_process_started')
                return type('Result',(),{'returncode':0})()
            class Health:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,*args):return b'{"ok":true}'
            fence.modified=True
            with patch.object(self.publisher.subprocess,'run',side_effect=systemctl),patch.object(self.publisher.urllib.request,'urlopen',return_value=Health()):
                self.publisher.restart_for(self.update_manifest(),fence)
            self.assertEqual(events,['old_process_stopped','new_process_started'])
            with admission_guard(path.with_name('admission.lock')) as allowed:self.assertFalse(allowed)
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)
            process.communicate(timeout=5)
        with admission_guard(path.with_name('admission.lock')) as allowed:self.assertTrue(allowed)


if __name__=='__main__':
    suite=unittest.TestSuite([AdmissionProcessTest('test_bootstrap_fence_blocks_legacy_writer_until_process_stops_and_new_admission_stays_closed')])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'admission_process_gate':'pass' if result.wasSuccessful() and not result.skipped else 'fail','old_writer_blocked_until_stopped':result.wasSuccessful(),'new_admission_closed_through_startup':result.wasSuccessful(),'real_model_call':False}))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)

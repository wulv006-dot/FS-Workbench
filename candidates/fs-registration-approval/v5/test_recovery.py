"""Actual local file/SQLite/process failure recovery, no production inputs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import native_integration
from auth_candidate import COOKIE, PREFIX
from integrated_server import Environment, create_server
from test_integration import Client
EVIDENCE = []


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='fs-registration-')
        self.env=Environment(self.tmp.name,'synthetic-recovery-secret-32-only')
        self.server=create_server(self.env)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(5)
        self.env.close();self.tmp.cleanup()
    def admin(self):
        c=Client(self.server); self.assertEqual(c.native('fstech')[0],200); c.boot(); return c
    def child(self,root,script,extra=()):
        return subprocess.run([sys.executable,'-c',script,str(root),*extra],cwd=Path(__file__).parent,
                              capture_output=True,text=True,timeout=25)

    @unittest.skipUnless(os.name == 'nt','Windows msvcrt branch only; POSIX separately tested')
    def test_real_open_failure_same_thread_reacquires_os_lock(self):
        lock=Path(self.tmp.name)/'namespace.lock';lock.unlink();lock.mkdir()
        with self.assertRaises(OSError):
            with self.env.namespace.fence(): self.fail('entered on failed open')
        self.assertEqual(getattr(self.env.namespace.depth,'value',0),0)
        lock.rmdir()
        import msvcrt
        real=msvcrt.locking
        with patch('msvcrt.locking',wraps=real) as calls:
            with self.env.namespace.fence():
                with self.env.namespace.fence(): self.assertEqual(self.env.namespace.depth.value,2)
            self.assertEqual(sum(c.args[1]==msvcrt.LK_LOCK for c in calls.call_args_list),1)
        with self.env.namespace.fence():
            result=self.child(self.tmp.name,"import os,msvcrt,sys; f=os.open(sys.argv[1]+'/namespace.lock',os.O_RDWR);\ntry: msvcrt.locking(f,msvcrt.LK_NBLCK,1); print('BAD')\nexcept OSError: print('blocked')\nfinally: os.close(f)")
            self.assertEqual(result.stdout.strip(),'blocked',result.stderr)

    @unittest.skipUnless(os.name == 'nt','Windows msvcrt branch only; POSIX separately tested')
    def test_acquire_unlock_close_failures_never_leave_reentrant_marker(self):
        import msvcrt
        real=msvcrt.locking
        for stage in ('acquire','unlock','close'):
            def failing(fd,mode,n):
                if stage=='acquire' and mode==msvcrt.LK_LOCK: raise OSError('synthetic acquire failure')
                result=real(fd,mode,n)
                if stage=='unlock' and mode==msvcrt.LK_UNLCK: raise OSError('synthetic post-unlock failure')
                return result
            close=os.close
            def closing(fd):
                close(fd)
                if stage=='close': raise OSError('synthetic post-close failure')
            with patch('msvcrt.locking',side_effect=failing), patch.object(native_integration.os,'close',side_effect=closing):
                with self.assertRaises(OSError):
                    with self.env.namespace.fence(): pass
            self.assertEqual(self.env.namespace.depth.value,0,stage)
            with patch('msvcrt.locking',wraps=real) as calls:
                with self.env.namespace.fence(): pass
                self.assertTrue(any(c.args[1]==msvcrt.LK_LOCK for c in calls.call_args_list),stage)

    def test_all_initialization_checkpoints_real_process_death_then_restart(self):
        script="""import os,sys
from integrated_server import Environment
def crash(phase):
 if phase==sys.argv[2]: os._exit(77)
Environment(sys.argv[1],'synthetic-crash-secret-32-only',checkpoint=crash)
"""
        for phase in ('journal_staged','journal','group_dashboard_staged','group_dashboard','group_deploy_staged','group_deploy','database_opened','schema_before_commit','schema_committed','registry','ready'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
                result=self.child(root,script,(phase,));self.assertEqual(result.returncode,77,result.stderr)
                env=Environment(root,'synthetic-crash-secret-32-only')
                try:
                    self.assertEqual(json.loads((Path(root)/'synthetic-init.json').read_text())['phase'],'ready')
                    self.assertEqual(env.store.path.exists(),True)
                    self.assertEqual(env.portal.authenticate('fstech','Local-synthetic-admin-42'),['dashboard','deploy'])
                    with env.store.connection() as db:
                        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
                        self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],0)
                    EVIDENCE.append({'initialization_phase':phase,'child_exit':result.returncode,'restart':'ready schema3; zero registered users; source admin authenticates'})
                finally: env.close()

    def test_first_initialization_two_real_processes(self):
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            code="import sys; from integrated_server import Environment; e=Environment(sys.argv[1],'synthetic-concurrent-init-only'); print(len(e.namespace.names())); e.close()"
            children=[subprocess.Popen([sys.executable,'-c',code,root],cwd=Path(__file__).parent,
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
            for c in children:
                out,err=c.communicate(timeout=25);self.assertEqual(c.returncode,0,err);self.assertEqual(out.strip(),'5')

    def test_unknown_partial_and_ready_missing_inputs_never_reseed(self):
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            p=Path(root)/'dashboard.synthetic-htpasswd';p.write_bytes(b'unknown')
            with self.assertRaises(ValueError): Environment(root)
            self.assertEqual(p.read_bytes(),b'unknown')
        group=Path(self.env.portal.GROUPS['dashboard']);group.unlink()
        with self.assertRaises(ValueError): Environment(self.tmp.name)
        self.assertFalse(group.exists())

    def test_partial_journal_unknown_group_and_database_fail_closed(self):
        script="import os,sys; from integrated_server import Environment; Environment(sys.argv[1],checkpoint=lambda p: os._exit(77) if p=='journal' else None)"
        for kind in ('group','database'):
            with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
                self.assertEqual(self.child(root,script).returncode,77)
                p=Path(root)/('dashboard.synthetic-htpasswd' if kind=='group' else 'candidate.sqlite3')
                p.write_bytes(b'unknown-owned-by-someone-else')
                with self.assertRaises(Exception): Environment(root)
                self.assertEqual(p.read_bytes(),b'unknown-owned-by-someone-else')

    def test_native_logout_during_identity_outage_revokes_after_restore_restart(self):
        c=self.admin(); original=dict(c.cookies); csrf=c.csrf
        path=Path(self.env.portal.GROUPS['dashboard']); saved=path.read_bytes();path.unlink()
        copied=Client(self.server);copied.cookies=dict(original)
        self.assertEqual(copied.call('GET','/dashboard/')[0],503)
        self.assertEqual(c.call('GET',PREFIX+'/api/bootstrap')[0],503)
        self.assertEqual(c.csrf,csrf)
        self.assertEqual(c.call('POST',PREFIX+'/api/logout')[0],200)
        self.assertEqual(c.cookies[COOKIE],'');self.assertEqual(c.cookies['MMOEXP_AUTH'],'')
        path.write_bytes(saved)
        self.assertEqual(copied.call('GET','/dashboard/')[0],401)
        e=Environment(self.tmp.name,'synthetic-recovery-secret-32-only')
        try: self.assertEqual(e.adapter.verify(original,'GET','/dashboard/')[0],401)
        finally: e.close()

    def test_logout_denylist_write_failure_rolls_back_no_success_or_clear(self):
        c=self.admin(); cookies=dict(c.cookies)
        with self.env.store.connection() as db:
            db.execute("CREATE TRIGGER fail_revoke BEFORE INSERT ON native_revocations BEGIN SELECT RAISE(ABORT,'synthetic revoke failure'); END")
        path=Path(self.env.portal.GROUPS['dashboard']);saved=path.read_bytes();path.unlink()
        code,result=c.call('POST',PREFIX+'/api/logout')
        self.assertEqual(code,503);self.assertNotIn('ok',result);self.assertEqual(c.cookies,cookies)
        self.assertIsNotNone(self.env.store.session(c.cookies[COOKIE]))
        with self.env.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM native_revocations').fetchone()[0],0)
            db.execute('DROP TRIGGER fail_revoke')
        path.write_bytes(saved)
        # A reported failure has not revoked the token: explicit retry is required.
        self.assertEqual(c.call('GET','/dashboard/')[0],200)
        self.assertEqual(c.call('POST',PREFIX+'/api/logout')[0],200)
        self.assertEqual(self.env.adapter.verify(cookies,'GET','/dashboard/')[0],401)

    def test_outage_logout_still_requires_session_origin_csrf_and_exact_fields(self):
        c=self.admin(); cookies=dict(c.cookies)
        path=Path(self.env.portal.GROUPS['dashboard']);saved=path.read_bytes();path.unlink()
        for extra,data in [({'X-CSRF-Token':'bad'},{}),({'Origin':'https://invalid.example'},{}),({}, {'admin':True})]:
            self.assertIn(c.call('POST',PREFIX+'/api/logout',data,extra)[0],(400,403))
        no_session=Client(self.server);no_session.cookies={'MMOEXP_AUTH':cookies['MMOEXP_AUTH']}
        self.assertEqual(no_session.call('POST',PREFIX+'/api/logout')[0],401)
        path.write_bytes(saved)
        self.assertEqual(self.env.adapter.verify(cookies,'GET','/dashboard/')[0],200)

    def test_outage_dual_principal_logout_removes_registered_and_native_atomically(self):
        c=self.admin(); user=Client(self.server);user.registered('recovery.reader')
        original=dict(user.cookies);original['MMOEXP_AUTH']=c.cookies['MMOEXP_AUTH'];user.cookies=dict(original)
        path=Path(self.env.portal.GROUPS['deploy']);saved=path.read_bytes();path.unlink()
        self.assertEqual(user.call('POST',PREFIX+'/api/logout')[0],200)
        self.assertIsNone(self.env.store.session(original[COOKIE]))
        path.write_bytes(saved)
        self.assertEqual(self.env.adapter.verify(original,'GET','/dashboard/')[0],401)


if __name__=='__main__': unittest.main()

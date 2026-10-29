"""Real Linux leases: publication drains dependent sessions before source reads."""
import ast
from contextlib import contextmanager,ExitStack
import importlib.util
import os
from pathlib import Path
import select
import sys
import tempfile
from threading import Event,Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
CACHE=ROOT/'releases/fs-dashboard/cache-archive-retention-20261025/source'
sys.path.insert(0,str(CACHE))
import cache_retention as reader
spec=importlib.util.spec_from_file_location('fair_publisher',Path(__file__).resolve().parents[1]/'deploy/concurrent_release.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
try:import fcntl
except ImportError:fcntl=None


@unittest.skipUnless(fcntl is not None,'real Linux flock required')
class FairAdmission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.fs=self.root/'var/lib/fs-hermes-fc/fs'
        self.fs.mkdir(parents=True,mode=0o700)
        def rooted(root,name):return Path(root)/name.lstrip('/')
        def no_link(path):
            if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlink')
        self.base=SimpleNamespace(rooted=rooted,no_target_link=no_link)
        for name in (*publisher.RELEASE_LOCKS,*publisher.LEGACY_LOCKS):
            p=rooted(self.root,name);p.parent.mkdir(parents=True,exist_ok=True);p.touch(mode=0o600)
        for name in publisher.QUERY_ROOTS:rooted(self.root,name).mkdir(parents=True,exist_ok=True)
        with reader.maintenance_reader(self.fs):pass
        self.stopped=False;self.restores=[];self.pauses=[];outer=self
        class Control:
            paused=[]
            def remember(self,manifest):pass
            def preview(self,manifest):pass
            def idle(self):pass
            def pause(self,manifest):outer.pauses.append('pause')
            def stopped(self):outer.stopped=True
            def restore(self,allow):outer.restores.append(allow)
        self.control=Control()
        @contextmanager
        def original_admission(manifest,root):
            with publisher.lease(self.base,root,publisher.ADMISSION):
                yield SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=lambda:None)
        @contextmanager
        def global_locks(root):
            with ExitStack() as stack:
                for name in publisher.RELEASE_LOCKS:stack.enter_context(publisher.lease(self.base,root,name))
                yield
        @contextmanager
        def web(manifest,root):yield
        self.base.__dict__.update(HERMES_HISTORY_SCOPE=publisher.SCOPE,locks=global_locks,live_lock=web,
            hermes_admission_fence=original_admission,guards=lambda *a,**k:None,
            inspect=lambda *a:dict(mutations=False),rollback_journal=lambda *a:None)
        self.base=publisher.extend(self.base,lambda root:self.control)
        self.manifest=dict(scope=publisher.SCOPE)

    def wait(self,condition,seconds=3):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if condition():return
            time.sleep(.01)
        self.fail('timed out observing isolated lease transition')

    def exclusive(self,name):
        p=self.base.rooted(self.root,name)
        try:fd=os.open(p,os.O_RDONLY)
        except FileNotFoundError:return False
        try:
            try:fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB);return False
            except BlockingIOError:return True
        finally:os.close(fd)

    def child_session(self):
        ready_r,ready_w=os.pipe();end_r,end_w=os.pipe();pid=os.fork()
        if pid==0:
            try:
                os.close(ready_r);os.close(end_w)
                with reader.maintenance_reader(self.fs,session=True):
                    os.write(ready_w,b'1');os.read(end_r,1)
                os._exit(0)
            except BaseException:os._exit(2)
        os.close(ready_w);os.close(end_r)
        self.assertTrue(select.select([ready_r],[],[],3)[0]);self.assertEqual(os.read(ready_r,1),b'1');os.close(ready_r)
        return pid,end_w

    def test_old_native_can_finish_cross_process_range_then_writer_drains_existing_range(self):
        pid,end=self.child_session();body=Event();finish=Event();errors=[]
        def publish():
            try:
                with self.base.locks(self.root),self.base.live_lock(self.manifest,self.root):
                    body.set();finish.wait(3)
            except BaseException as error:errors.append(error)
        thread=Thread(target=publish);thread.start()
        try:
            self.wait(lambda:self.exclusive(publisher.PUBLICATION))
            with self.assertRaises(BlockingIOError):
                with reader.maintenance_reader(self.fs,session=True):self.fail('new session cut in')
            # A different process from the old native session can still serve its tool.
            with reader.maintenance_reader(self.fs):
                os.write(end,b'1');os.close(end);end=None
                self.assertEqual(os.waitpid(pid,0)[1],0);pid=None
                self.wait(lambda:self.exclusive(publisher.READER_ENTRY))
                outcomes=[]
                def new_range():
                    try:
                        with reader.maintenance_reader(self.fs):outcomes.append('entered')
                    except BlockingIOError:outcomes.append('busy')
                fresh=Thread(target=new_range);fresh.start();fresh.join(2)
                self.assertEqual(outcomes,['busy']);self.assertFalse(body.is_set())
                # Same-thread already-admitted nested reads do not deadlock themselves.
                with reader.maintenance_reader(self.fs):pass
            self.assertTrue(body.wait(2));self.assertTrue(self.stopped)
        finally:
            if end is not None:os.write(end,b'1');os.close(end)
            if pid is not None:os.waitpid(pid,0)
            finish.set();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        with reader.maintenance_reader(self.fs,session=True):pass

    def test_drain_timeout_releases_reservation_without_restoring_untouched_services(self):
        errors=[]
        with reader.maintenance_reader(self.fs):
            def publish():
                try:
                    with self.base.locks(self.root),self.base.live_lock(self.manifest,self.root):self.fail('live writer reached')
                except BaseException as error:errors.append(error)
            with patch.object(publisher,'DRAIN_SECONDS',.12):
                thread=Thread(target=publish);thread.start()
                self.wait(lambda:self.exclusive(publisher.PUBLICATION))
                self.stopped=True  # Another operator changes state while we only wait.
                thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
            self.assertEqual(str(errors[0]),'p4_admission_drain_timeout')
            self.assertEqual(self.pauses,[]);self.assertEqual(self.restores,[]);self.assertTrue(self.stopped)
            with reader.maintenance_reader(self.fs,session=True):pass
        with self.base.locks(self.root):pass

    def test_publisher_body_busy_error_is_not_replayed_and_leases_are_released(self):
        calls=[]
        with self.assertRaisesRegex(BlockingIOError,'body failed'):
            with self.base.locks(self.root),self.base.live_lock(self.manifest,self.root):
                calls.append(1);raise BlockingIOError('body failed')
        self.assertEqual(calls,[1])
        with reader.maintenance_reader(self.fs,session=True):pass

    def test_nonbusy_admission_error_is_not_retried(self):
        calls=[]
        @contextmanager
        def denied():
            calls.append(1);raise ValueError('active or unreconciled Hermes task; defer update');yield
        with self.assertRaisesRegex(ValueError,'unreconciled'):
            with publisher.drain(denied,time.monotonic()+1):self.fail('invalid admission reached')
        self.assertEqual(calls,[1])

    def test_shared_deadline_does_not_restart_after_first_wait(self):
        clock=[0.];first_calls=[];second_calls=[]
        @contextmanager
        def first():
            first_calls.append(1)
            if len(first_calls)<3:raise BlockingIOError()
            yield
        @contextmanager
        def second():
            second_calls.append(1)
            if len(second_calls)>3:raise AssertionError('wait budget restarted')
            raise BlockingIOError();yield
        with patch.object(publisher.time,'monotonic',side_effect=lambda:clock[0]),patch.object(publisher.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            with publisher.drain(first,.25):
                with self.assertRaisesRegex(ValueError,'drain_timeout'):
                    with publisher.drain(second,.25):pass
        self.assertEqual(len(first_calls),3);self.assertEqual(len(second_calls),2)

    def test_process_exit_clears_kernel_reservation_without_deleting_lock_inode(self):
        ready_r,ready_w=os.pipe();end_r,end_w=os.pipe();pid=os.fork()
        if pid==0:
            try:
                os.close(ready_r);os.close(end_w)
                with publisher.lease(self.base,self.root,publisher.PUBLICATION,create=True):
                    os.write(ready_w,b'1');os.read(end_r,1);os._exit(23)
            except BaseException:os._exit(2)
        os.close(ready_w);os.close(end_r)
        try:
            self.assertTrue(select.select([ready_r],[],[],3)[0]);self.assertEqual(os.read(ready_r,1),b'1')
            path=self.fs/'publication.lock';inode=path.stat().st_ino
            with self.assertRaises(BlockingIOError):
                with reader.maintenance_reader(self.fs,session=True):pass
        finally:os.write(end_w,b'1');os.close(end_w);os.close(ready_r)
        self.assertEqual(os.waitpid(pid,0)[1],23<<8)
        with reader.maintenance_reader(self.fs,session=True):pass
        self.assertEqual(path.stat().st_ino,inode);self.assertEqual(path.stat().st_size,0)

    def test_readonly_inspect_reuses_original_global_locks_and_does_not_initialize_missing_gate(self):
        def snapshot():return {str(p.relative_to(self.root)):(p.stat().st_ino,p.stat().st_size,p.stat().st_mode) for p in self.root.rglob('*')}
        before=snapshot()
        self.assertFalse((self.fs/'publication.lock').exists())
        self.assertEqual(self.base.inspect(self.manifest,self.root,self.root),dict(mutations=False))
        self.assertEqual(snapshot(),before);self.assertEqual(self.pauses,[])
        p=self.base.rooted(self.root,publisher.RELEASE_LOCKS[0]);p.unlink()
        with self.assertRaises(FileNotFoundError):self.base.inspect(self.manifest,self.root,self.root)
        self.assertFalse(p.exists())

    def test_global_alias_is_supported_but_substituted_file_or_parent_is_rejected(self):
        folder=self.root/'var/lock';target=self.root/'run/lock';target.parent.mkdir()
        folder.rename(target);folder.symlink_to(target,target_is_directory=True)
        with publisher.lease(self.base,self.root,publisher.RELEASE_LOCKS[0]):pass
        p=target/'fs-navigation-release.lock';p.rename(target/'saved.lock');p.symlink_to(target/'saved.lock')
        with self.assertRaisesRegex(ValueError,'release_lock_link'):
            with publisher.lease(self.base,self.root,publisher.RELEASE_LOCKS[0]):pass
        p.unlink();(target/'saved.lock').rename(p);folder.unlink();folder.symlink_to(target.parent,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'release_lock_link'):
            with publisher.lease(self.base,self.root,publisher.RELEASE_LOCKS[0]):pass

    def test_second_publisher_cannot_cut_in(self):
        with self.base.locks(self.root):
            with self.assertRaisesRegex(ValueError,'source_or_query_busy'):
                with self.base.locks(self.root):pass

    def test_unsafe_shared_gate_and_missing_native_admission_fail_closed(self):
        for name in ('publication.lock','reader-entry.lock'):
            path=self.fs/name
            if path.exists():path.unlink()
            path.symlink_to(self.fs/'admission.lock')
            with self.assertRaises(ValueError):
                with reader.maintenance_reader(self.fs,session=True):pass
            path.unlink()
        (self.fs/'admission.lock').unlink()
        with self.assertRaises(FileNotFoundError):
            with reader.maintenance_reader(self.fs,create=False,session=True):pass
        self.assertFalse((self.fs/'admission.lock').exists())

    def test_controller_busy_bool_and_body_error_contract_use_same_helper(self):
        source=ROOT/'releases/fs-dashboard/knowledge-layering-20261023/source/controller.py'
        node=next(n for n in ast.parse(source.read_text(encoding='utf8')).body if isinstance(n,ast.FunctionDef) and n.name=='admission_guard')
        namespace=dict(contextmanager=contextmanager,ExitStack=ExitStack,Path=Path)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'current-controller-admission','exec'),namespace)
        guard=namespace['admission_guard']
        with publisher.lease(self.base,self.root,publisher.PUBLICATION,create=True):
            with guard(self.fs/'admission.lock') as accepted:self.assertFalse(accepted)
        calls=[]
        with self.assertRaisesRegex(OSError,'body failure'):
            with guard(self.fs/'admission.lock') as accepted:
                self.assertTrue(accepted);calls.append(1);raise OSError('body failure')
        self.assertEqual(calls,[1])

    def test_existing_plain_reader_cannot_upgrade_to_new_session_past_waiting_publisher(self):
        with reader.maintenance_reader(self.fs):
            with publisher.lease(self.base,self.root,publisher.PUBLICATION,create=True):
                with self.assertRaises(BlockingIOError):
                    with reader.maintenance_reader(self.fs,session=True):self.fail('new session upgraded past publication')
                with reader.maintenance_reader(self.fs):pass

    def test_forked_process_does_not_inherit_thread_local_admission_qualification(self):
        with reader.maintenance_reader(self.fs):
            with publisher.lease(self.base,self.root,publisher.READER_ENTRY):
                read,write=os.pipe();pid=os.fork()
                if pid==0:
                    os.close(read)
                    try:
                        with reader.maintenance_reader(self.fs):os.write(write,b'bad')
                    except BlockingIOError:os.write(write,b'busy')
                    os._exit(0)
                os.close(write)
                try:
                    self.assertTrue(select.select([read],[],[],3)[0]);self.assertEqual(os.read(read,4),b'busy')
                finally:os.close(read);os.waitpid(pid,0)

    def test_legacy_reader_ignoring_new_gate_only_times_out_without_stopping_it(self):
        errors=[]
        with publisher.lease(self.base,self.root,publisher.PUBLICATION,create=True):
            fd=os.open(self.fs/'admission.lock',os.O_RDONLY)
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            try:
                with self.assertRaisesRegex(ValueError,'drain_timeout'):
                    with publisher.drain(lambda:publisher.lease(self.base,self.root,publisher.ADMISSION),time.monotonic()+.03):pass
            finally:os.close(fd)
        self.assertFalse(self.stopped);self.assertEqual(self.pauses,[])


if __name__=='__main__':unittest.main()

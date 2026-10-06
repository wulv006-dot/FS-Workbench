"""Run only in a separately authorized isolated Linux QA environment as root.
Uses temporary synthetic trees only; no production paths or services are opened.
Windows skips are deliberately reported as unverified native coverage.
"""
import os,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secure_fs import Directory,SecureFS

@unittest.skipUnless(os.name=='posix' and getattr(os,'geteuid',lambda:-1)()==0,'native isolated Linux root QA not available')
class NativeLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fc27-reconcile-isolated-qa-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);os.chmod(self.root,0o700)
        self.directory=Directory(str(self.root),{'uid':0,'gid':0,'mode':'0o700'});self.addCleanup(self.directory.close)
    def newfile(self,name='input.json'):
        p=self.root/name;p.write_bytes(b'{}');os.chmod(p,0o600);return p
    def fs(self):
        fs=SecureFS.__new__(SecureFS);fs.scope={'state_root':str(self.root),'rollback_root':str(self.root),'player_job_id':'synthetic-player','lock_metadata':{}}
        fs.dirs={str(self.root):self.directory};fs.locks={};fs.tx=None;return fs
    def test_parent_directory_symlink_rejected(self):
        (self.root/'outside').mkdir();(self.root/'parent').symlink_to(self.root/'outside',target_is_directory=True)
        with self.assertRaises(OSError):Directory(str(self.root/'parent'),{'uid':0,'gid':0,'mode':'0o755'},self.directory,'parent')
    def test_opened_parent_replacement_rejected(self):
        p=self.root/'parent';p.mkdir(mode=0o700);d=Directory(str(p),{'uid':0,'gid':0,'mode':'0o700'},self.directory,'parent')
        try:
            p.rename(self.root/'old-parent');p.mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError,'fd_path_changed'):d.check()
        finally:d.close()
    def test_transaction_symlink_rejected(self):
        (self.root/'outside').mkdir();(self.root/'player-reconcile-v2-synthetic-player').symlink_to(self.root/'outside',target_is_directory=True)
        with self.assertRaises(OSError):self.fs().open_transaction(False)
    def test_untrusted_owner_rejected(self):
        p=self.newfile();os.chown(p,12345,0)
        with self.assertRaisesRegex(ValueError,'owner_changed'):self.directory.read(p.name,{'uid':0,'gid':0,'mode':'0o600'})
    def test_hardlink_rejected(self):
        p=self.newfile();os.link(p,self.root/'second.json')
        with self.assertRaisesRegex(ValueError,'hardlink'):self.directory.read(p.name)
    def test_file_symlink_rejected(self):
        p=self.newfile();(self.root/'link.json').symlink_to(p)
        with self.assertRaises(OSError):self.directory.read('link.json')
    def test_held_lock_inode_replacement_rejected(self):
        p=self.newfile('writer.lock');s=os.lstat(p);fs=self.fs();fs.scope['lock_metadata'][p.name]={'uid':0,'gid':0,'mode':'0o600','device':s.st_dev,'inode':s.st_ino};fs.lock(p.name)
        try:
            p.rename(self.root/'old.lock');self.newfile('writer.lock')
            with self.assertRaisesRegex(ValueError,'inode_changed'):fs.check()
        finally:
            for fd,_ in fs.locks.values():os.close(fd)
    def test_real_private_file_and_directory_fsync(self):
        fs=self.fs();fs.open_transaction(True)
        try:
            fs.tx_write('proofs-0.json',b'[]');self.assertEqual(fs.tx_read('proofs-0.json'),b'[]')
            self.assertEqual(stat.S_IMODE(os.lstat(fs.tx.path).st_mode),0o700)
            self.assertEqual(stat.S_IMODE(os.lstat(Path(fs.tx.path)/'proofs-0.json').st_mode),0o600)
        finally:fs.tx.close()
    def test_stage_fsync_before_publication_checkpoint(self):
        from secure_fs import digest
        p=self.newfile();fs=self.fs();fs.open_transaction(True);calls=[]
        try:
            def checkpoint():calls.append('checkpoint');raise ValueError('synthetic stale proof')
            with self.assertRaisesRegex(ValueError,'stale'):fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},checkpoint)
            self.assertEqual(p.read_bytes(),b'{}');self.assertEqual(calls,['checkpoint']);self.assertTrue((Path(fs.tx.path)/'publish-job.json').exists())
        finally:fs.tx.close()
    def test_directory_fsync_failure_after_job_rename_preserves_evidence(self):
        from secure_fs import digest
        p=self.newfile();fs=self.fs();fs.open_transaction(True)
        try:
            real=Directory.fsync
            def fail_target(directory):
                if directory is self.directory:raise OSError('synthetic target directory fsync failure')
                return real(directory)
            with patch.object(Directory,'fsync',fail_target):
                with self.assertRaises(OSError):fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},lambda:None)
            self.assertEqual(p.read_bytes(),b'{"after":true}');self.assertTrue(Path(fs.tx.path).exists())
        finally:fs.tx.close()
    def test_leftover_stage_retries_file_fsync_twice_then_succeeds(self):
        from secure_fs import digest
        p=self.newfile();fs=self.fs();fs.open_transaction(True);attempts=[];remaining=[2];real=os.fsync
        try:
            def injected(fd):
                if stat.S_ISREG(os.fstat(fd).st_mode):
                    attempts.append('file_fsync')
                    if remaining[0]:remaining[0]-=1;raise OSError('synthetic staging file fsync failure')
                return real(fd)
            with patch('secure_fs.os.fsync',injected):
                for _ in range(2):
                    with self.assertRaises(OSError):fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},lambda:None)
                    self.assertEqual(p.read_bytes(),b'{}');self.assertEqual((Path(fs.tx.path)/'publish-job.json').read_bytes(),b'{"after":true}')
                fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},lambda:None)
            self.assertEqual(attempts,['file_fsync']*3);self.assertEqual(p.read_bytes(),b'{"after":true}')
        finally:fs.tx.close()
    def test_leftover_stage_retries_tx_dir_fsync_twice_then_succeeds(self):
        from secure_fs import digest
        p=self.newfile();fs=self.fs();fs.open_transaction(True);attempts=[];remaining=[2];real=Directory.fsync
        try:
            def injected(directory):
                if directory is fs.tx:
                    attempts.append('tx_dir_fsync')
                    if remaining[0]:remaining[0]-=1;raise OSError('synthetic source directory fsync failure')
                return real(directory)
            with patch.object(Directory,'fsync',injected):
                for _ in range(2):
                    with self.assertRaises(OSError):fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},lambda:None)
                    self.assertEqual(p.read_bytes(),b'{}');self.assertTrue((Path(fs.tx.path)/'publish-job.json').exists())
                fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},lambda:None)
            self.assertEqual(len(attempts),4);self.assertEqual(p.read_bytes(),b'{"after":true}')
        finally:fs.tx.close()
    def test_source_dir_fsync_after_rename_failure_exact_retry_syncs_both(self):
        from secure_fs import digest
        from storage import Storage
        p=self.newfile();fs=self.fs();fs.open_transaction(True);attempts=[];real=Directory.fsync
        try:
            def injected(directory):
                attempts.append(directory.path)
                if directory is fs.tx and attempts.count(directory.path)==2:raise OSError('synthetic post-rename source fsync failure')
                return real(directory)
            with patch.object(Directory,'fsync',injected):
                with self.assertRaises(OSError):fs.publish('publish-job.json',str(p),b'{"after":true}',{digest(b'{}')},{'uid':0,'gid':0,'mode':'0o600'},lambda:None)
            self.assertEqual(p.read_bytes(),b'{"after":true}');self.assertFalse((Path(fs.tx.path)/'publish-job.json').exists())
            storage=Storage.__new__(Storage);storage.fs=fs;storage.root=str(self.root);storage.scope={'expected_files':{p.name:'synthetic'},'file_metadata':{p.name:{'uid':0,'gid':0,'mode':'0o600'}}}
            syncs=[]
            def recorded(directory):syncs.append(directory.path);return real(directory)
            with patch.object(Directory,'fsync',recorded):storage.sync_visible(p.name)
            self.assertEqual(syncs,[str(self.root),fs.tx.path])
        finally:fs.tx.close()

if __name__=='__main__':unittest.main(verbosity=2)

"""Only the exact existing policy-owner compatibility increment; no old57 rerun."""
import json,os,stat,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import test_v4 as fixtures
import launch
import secure_fs

class PolicyOwnerIncrementTests(unittest.TestCase):
    def binding(self):
        scope,schema=fixtures.LoaderTests().binding()
        scope['trusted_service_uids']=[0,994,11027]
        for item in scope['policy_lock_metadata'].values():item.update(uid=994,gid=11028,mode='0o660')
        return scope,schema
    def validate(self,scope,schema):launch.validate_binding(scope,schema,'a'*64,'/synthetic/artifact')
    def test_exact_service_identity_approved(self):self.validate(*self.binding())
    def test_arbitrary_owner_refused(self):
        for uid in [995,11027]:
            with self.subTest(uid=uid):
                s,c=self.binding();next(iter(s['policy_lock_metadata'].values()))['uid']=uid
                with self.assertRaisesRegex(ValueError,'policy_lock_metadata_invalid'):self.validate(s,c)
    def test_other_group_or_mode_refused(self):
        for field,value in [('gid',0),('mode','0o644'),('mode','0o666'),('mode','0o664')]:
            with self.subTest(field=field,value=value):
                s,c=self.binding();next(iter(s['policy_lock_metadata'].values()))[field]=value
                with self.assertRaisesRegex(ValueError,'policy_lock_metadata_invalid'):self.validate(s,c)
    def test_dedicated_service_must_be_explicitly_bound(self):
        s,c=self.binding();s['trusted_service_uids']=[0,11027]
        with self.assertRaisesRegex(ValueError,'policy_lock_metadata_invalid'):self.validate(s,c)
    def test_exact_policy_paths_and_inode_required(self):
        s,c=self.binding();item=s['policy_lock_metadata'].pop('/var/lib/fc27-cloud/config/player-sync.lock');s['policy_lock_metadata']['/var/lib/fc27-cloud/config/other.lock']=item
        with self.assertRaisesRegex(ValueError,'policy_locks_incomplete'):self.validate(s,c)
        s,c=self.binding();next(iter(s['policy_lock_metadata'].values()))['inode']=0
        with self.assertRaisesRegex(ValueError,'policy_lock_metadata_invalid'):self.validate(s,c)
    def test_previous_root_branch_unchanged(self):self.validate(*fixtures.LoaderTests().binding())
    def model(self,busy=False):
        paths=['/synthetic/config/automation.lock','/synthetic/config/player-sync.lock']
        expected={p:{'uid':994,'gid':11028,'mode':'0o660','device':1,'inode':i+2} for i,p in enumerate(paths)}
        fs=object.__new__(secure_fs.SecureFS);fs.scope={'state_root':'/synthetic/state','policy_lock_metadata':expected,'trusted_service_uids':[0,994,11027],'service_gid':11028}
        fs.check=lambda:None;calls=[];closed=[]
        def open_file(name,metadata):calls.append(name);return (10+len(calls),None)
        directory=types.SimpleNamespace(fd=90,open_file=open_file)
        fs.split=lambda path:(directory,path.rsplit('/',1)[1])
        def info(metadata):return types.SimpleNamespace(st_mode=stat.S_IFREG|0o660,st_uid=994,st_gid=11028,st_nlink=1,st_dev=1,st_ino=metadata['inode'])
        def flock(fd,flags):
            if busy and fd==12:raise BlockingIOError('busy')
        mockfcntl=types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=flock)
        return fs,calls,closed,expected,info,mockfcntl
    def test_policy_guard_uses_both_exact_bound_existing_descriptors(self):
        fs,calls,closed,expected,info,fcntl=self.model()
        with patch.dict(sys.modules,{'fcntl':fcntl}),patch.object(secure_fs.os,'stat',side_effect=lambda name,**kw:info(expected['/synthetic/config/'+name])),patch.object(secure_fs.os,'fstat',side_effect=lambda fd:info(expected[list(expected)[fd-11]])),patch.object(secure_fs.os,'close',side_effect=closed.append):
            with fs.policy_guard() as check:check()
        self.assertEqual(calls,['automation.lock','player-sync.lock']);self.assertEqual(closed,[12,11])
    def test_second_policy_busy_closes_first_without_publication(self):
        fs,calls,closed,expected,info,fcntl=self.model(True)
        with patch.dict(sys.modules,{'fcntl':fcntl}),patch.object(secure_fs.os,'close',side_effect=closed.append):
            with self.assertRaises(BlockingIOError):
                with fs.policy_guard():self.fail('publication after busy')
        self.assertEqual(closed,[12,11])

@unittest.skipUnless(sys.platform=='linux' and hasattr(os,'geteuid') and os.geteuid()==0,'requires real Linux root')
class NativePolicyOwnerIncrementTests(unittest.TestCase):
    def native(self,symlink=False):
        temp=tempfile.TemporaryDirectory(prefix='fc-policy-owner-',dir='/run');root=Path(temp.name);config=root/'config';config.mkdir(mode=0o750)
        metadata={}
        for name in ['automation.lock','player-sync.lock']:
            path=config/name;path.write_bytes(b'');os.chown(path,994,11028);os.chmod(path,0o660);st=path.stat()
            metadata[str(path)]={'uid':994,'gid':11028,'mode':'0o660','device':st.st_dev,'inode':st.st_ino}
        if symlink:
            path=config/'player-sync.lock';target=config/'outside.lock';path.rename(target);path.symlink_to(target)
        st=config.stat();directory=secure_fs.Directory(str(config),{'uid':st.st_uid,'gid':st.st_gid,'mode':oct(st.st_mode&0o777)})
        fs=object.__new__(secure_fs.SecureFS);fs.scope={'state_root':str(root/'state'),'policy_lock_metadata':metadata,'service_gid':11028,'trusted_service_uids':[0,994,11027]};fs.dirs={str(config):directory};fs.locks={}
        return temp,config,directory,fs
    def test_exact_service_owned_locks_flock_and_release(self):
        import fcntl
        temp,config,directory,fs=self.native()
        try:
            with fs.policy_guard():
                fd=os.open(config/'player-sync.lock',os.O_RDONLY)
                try:
                    with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                finally:os.close(fd)
            fd=os.open(config/'player-sync.lock',os.O_RDONLY)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:os.close(fd)
        finally:directory.close();temp.cleanup()
    def test_policy_symlink_refused_before_publication(self):
        temp,config,directory,fs=self.native(True)
        try:
            with self.assertRaises(OSError):
                with fs.policy_guard():self.fail('symlink publication')
        finally:directory.close();temp.cleanup()

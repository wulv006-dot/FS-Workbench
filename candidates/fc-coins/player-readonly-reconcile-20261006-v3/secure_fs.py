"""POSIX descriptor-relative access within explicitly frozen trusted directories."""
import os,stat,re,hashlib,secrets

def fail(reason):raise ValueError(reason)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def identity(st):return (st.st_dev,st.st_ino)
def validate_stat(st,expected,kind,private=False):
    if kind=='dir' and not stat.S_ISDIR(st.st_mode):fail('trusted_path_not_directory')
    if kind=='file' and (not stat.S_ISREG(st.st_mode) or st.st_nlink!=1):fail('trusted_file_not_regular_single_link')
    if any(getattr(st,attr)!=expected[key] for attr,key in [('st_uid','uid'),('st_gid','gid')]):fail('trusted_owner_changed')
    if stat.S_IMODE(st.st_mode)!=int(expected['mode'],8):fail('trusted_mode_changed')
    if 'device' in expected and identity(st)!=(expected['device'],expected['inode']):fail('trusted_inode_changed')
    if private and (st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=(0o700 if kind=='dir' else 0o600)):fail('private_transaction_trust_failed')

class Directory:
    def __init__(self,path,expected,parent=None,name=None):
        self.path=path;self.expected=expected;self.parent=parent;self.name=name
        self.fd=os.open(name if parent else path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,**({'dir_fd':parent.fd} if parent else {}))
        try:validate_stat(os.fstat(self.fd),expected,'dir');self.check()
        except BaseException:os.close(self.fd);raise
    def check(self):
        if self.parent:self.parent.check();current=os.stat(self.name,dir_fd=self.parent.fd,follow_symlinks=False)
        else:current=os.lstat(self.path)
        validate_stat(current,self.expected,'dir')
        if identity(current)!=identity(os.fstat(self.fd)):fail('directory_fd_path_changed')
    @staticmethod
    def name_check(name):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in ['.','..']:fail('unsafe_flat_file_name')
    def open_file(self,name,expected=None):
        self.check();self.name_check(name);fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=self.fd)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:fail('file_type_or_hardlink_changed')
            if expected:validate_stat(before,expected,'file')
            current=os.stat(name,dir_fd=self.fd,follow_symlinks=False)
            if identity(current)!=identity(before):fail('file_fd_path_changed')
            return fd,before
        except BaseException:os.close(fd);raise
    def read(self,name,expected=None):
        fd,before=self.open_file(name,expected)
        try:
            parts=[];length=0
            while True:
                part=os.read(fd,1048576)
                if not part:break
                parts.append(part);length+=len(part)
                if length>32000000:fail('bounded_file_size_exceeded')
            after=os.fstat(fd);current=os.stat(name,dir_fd=self.fd,follow_symlinks=False);self.check()
            if identity(current)!=identity(after) or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):fail('file_changed_during_read')
            return b''.join(parts)
        finally:os.close(fd)
    def exists(self,name):
        self.check();self.name_check(name)
        try:os.stat(name,dir_fd=self.fd,follow_symlinks=False);return True
        except FileNotFoundError:return False
    def fsync(self):self.check();os.fsync(self.fd)
    def write_private(self,name,raw):
        self.check();self.name_check(name);validate_stat(os.fstat(self.fd),{'uid':0,'gid':0,'mode':'0o700'},'dir',True)
        if self.exists(name):self.read(name,{'uid':0,'gid':0,'mode':'0o600'})
        temp='.reconcile-'+secrets.token_hex(12);fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=self.fd)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            self.check();os.replace(temp,name,src_dir_fd=self.fd,dst_dir_fd=self.fd);self.fsync()
        finally:
            if self.exists(temp):os.unlink(temp,dir_fd=self.fd);self.fsync()
    def close(self):os.close(self.fd)

class SecureFS:
    def __init__(self,scope):
        if os.name!='posix':fail('native_posix_required')
        self.scope=scope;self.dirs={};self.locks={};self.tx=None
        for path,expected in sorted(scope['trusted_directories'].items(),key=lambda x:(x[0].count('/'),len(x[0]))):
            group_writable={'/var/lib/fc27-cloud/player-sync','/var/lib/fc27-cloud/executions','/var/lib/fc27-cloud/all-coin-sync','/var/lib/fc27-cloud/config','/var/lib/fc27-cloud/queue','/var/lib/fc27-gallery'}
            mode=int(expected['mode'],8)
            if expected['uid']!=0 or mode&0o002:fail('directory_owner_or_world_write_untrusted')
            if mode&0o020 and not (path in group_writable and expected['gid']==11028 and mode==0o2770):fail('directory_group_write_untrusted')
            if path==scope['artifact_root'] and (expected['gid']!=0 or mode!=0o700):fail('artifact_directory_not_root_private')
            if path=='/':self.dirs[path]=Directory(path,expected)
            else:
                parent,name=path.rsplit('/',1);parent=parent or '/'
                if parent not in self.dirs:fail('unbound_parent_directory')
                self.dirs[path]=Directory(path,expected,self.dirs[parent],name)
    def split(self,path):
        parent,name=path.rsplit('/',1)
        if parent not in self.dirs:fail('path_outside_frozen_directories')
        return self.dirs[parent],name
    def read_path(self,path,expected=None):directory,name=self.split(path);return directory.read(name,expected)
    def check(self):
        for directory in self.dirs.values():directory.check()
        for name,(fd,expected) in self.locks.items():
            current=os.stat(name,dir_fd=self.dirs[self.scope['state_root']].fd,follow_symlinks=False);validate_stat(current,expected,'file')
            if identity(current)!=identity(os.fstat(fd)):fail('lock_inode_replaced')
    def lock(self,name):
        import fcntl
        directory=self.dirs[self.scope['state_root']];expected=self.scope['lock_metadata'][name];fd,_=directory.open_file(name,expected)
        if expected['uid']!=0 or int(expected['mode'],8)&0o022:os.close(fd);fail('lock_owner_or_write_mode_untrusted')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.locks[name]=(fd,expected);self.check()
        except BaseException:os.close(fd);raise
    def lock_free(self,name):
        import fcntl
        directory=self.dirs[self.scope['state_root']];fd,_=directory.open_file(name,self.scope['lock_metadata'][name])
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.check()
        finally:os.close(fd)
    def open_transaction(self,create=False):
        parent=self.dirs[self.scope['rollback_root']];name='player-reconcile-v2-'+self.scope['player_job_id'];parent.check()
        if self.tx:
            self.tx.check();return True
        if not parent.exists(name):
            if not create:return False
            os.mkdir(name,0o700,dir_fd=parent.fd);parent.fsync()
        self.tx=Directory(parent.path+'/'+name,{'uid':0,'gid':0,'mode':'0o700'},parent,name)
        return True
    def tx_read(self,name):
        if not self.tx:fail('transaction_absent')
        return self.tx.read(name,{'uid':0,'gid':0,'mode':'0o600'})
    def tx_write(self,name,raw):
        if not self.tx:fail('transaction_absent')
        self.tx.write_private(name,raw)
    def publish(self,source_name,target_path,raw,expected_current,metadata,before_replace):
        """Private staging then rename. Caller creates durable ready receipt before job publication."""
        self.check();target,name=self.split(target_path)
        if digest(target.read(name,metadata)) not in expected_current:fail('publication_cas_changed')
        self.tx.name_check(source_name)
        existing=self.tx.exists(source_name)
        if existing:
            if digest(self.tx.read(source_name,metadata))!=digest(raw):fail('leftover_publication_bytes_changed')
            fd,_=self.tx.open_file(source_name,metadata)
        else:
            fd=os.open(source_name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=self.tx.fd)
        try:
            if not existing:
                os.fchown(fd,metadata['uid'],metadata['gid']);os.fchmod(fd,int(metadata['mode'],8))
                with os.fdopen(fd,'wb',closefd=False) as stream:stream.write(raw);stream.flush()
            staged_stat=os.fstat(fd);validate_stat(staged_stat,metadata,'file');staged=identity(staged_stat)
            # Both new and leftover staging require successful data and source-dir sync.
            os.fsync(fd);self.tx.fsync()
            self.check();self.tx.check()
            if identity(os.stat(source_name,dir_fd=self.tx.fd,follow_symlinks=False))!=staged:fail('publication_staging_inode_changed')
            if digest(target.read(name,metadata)) not in expected_current:fail('publication_final_cas_changed')
            before_replace()
            os.replace(source_name,name,src_dir_fd=self.tx.fd,dst_dir_fd=target.fd);target.fsync();self.tx.fsync()
            if identity(os.stat(name,dir_fd=target.fd,follow_symlinks=False))!=staged:fail('published_file_inode_changed')
        finally:
            os.close(fd)
            # A leftover staging file is evidence; never unlink it on error.
            self.check()
    def close(self):
        for fd,_ in self.locks.values():os.close(fd)
        if self.tx:self.tx.close()
        for directory in reversed(list(self.dirs.values())):directory.close()

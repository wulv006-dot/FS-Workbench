"""Exact live inputs and root-private transaction, all through anchored descriptors."""
import json,os,stat
from secure_fs import SecureFS,digest,fail

class Storage:
    def __init__(self,scope):
        self.scope=scope;self.fs=SecureFS(scope);self.root=scope['state_root'].rsplit('/',1)[0]
        self.backup_path=scope['rollback_root']+'/player-reconcile-v2-'+scope['player_job_id']
    def path(self,key):
        if key not in self.scope['expected_files']:fail('live_key_outside_scope')
        return key if key.startswith('/') else self.root+'/'+key
    def metadata(self,key):return {k:v for k,v in self.scope['file_metadata'][key].items() if k in ['uid','gid','mode']}
    def read_live(self,key):
        meta=self.metadata(key)
        if meta['uid'] not in [0,994,11027] or meta['gid'] not in [0,11028] or int(meta['mode'],8)&0o002:fail('live_file_owner_or_write_mode_untrusted')
        if int(meta['mode'],8)&0o020 and not (key=='/var/lib/fc27-gallery/settings.json' and meta=={'uid':0,'gid':11028,'mode':'0o660'}):fail('live_file_group_write_untrusted')
        return self.fs.read_path(self.path(key),meta)
    def tx_exists(self):return self.fs.open_transaction(create=False)
    def create_tx(self):
        if self.fs.open_transaction(create=False):fail('transaction_already_exists')
        self.fs.open_transaction(create=True)
    def tx_read(self,name):return self.fs.tx_read(name)
    def tx_write(self,name,raw):self.fs.tx_write(name,raw)
    def publish(self,key,raw,allowed,checkpoint):
        names={self.scope['allowed_metadata_targets'][0]:'publish-ledger.json',self.scope['allowed_metadata_targets'][1]:'publish-job.json'}
        if key not in names:fail('publication_target_outside_scope')
        with self.fs.policy_guard() as policy_check:
            def protected_checkpoint():
                policy_check();checkpoint();policy_check()
            self.fs.publish(names[key],self.path(key),raw,allowed,self.metadata(key),protected_checkpoint)
    def sync_visible(self,key):
        directory,name=self.fs.split(self.path(key));fd,_=directory.open_file(name,self.metadata(key))
        try:os.fsync(fd);directory.fsync();self.fs.tx.fsync();self.fs.check()
        finally:os.close(fd)
    def json_directory(self,name):
        directory=self.fs.dirs[self.root+'/'+name];directory.check();out=[]
        for filename in os.listdir(directory.fd):
            if not filename.endswith('.json'):
                if name=='queue':fail('queue_non_json_record_needs_audit')
                continue
            st=os.stat(filename,dir_fd=directory.fd,follow_symlinks=False)
            if st.st_uid not in self.scope['trusted_service_uids'] or st.st_gid not in [0,self.scope['service_gid']] or stat.S_IMODE(st.st_mode)&0o022:fail('runtime_record_owner_mode_untrusted')
            raw=directory.read(filename,{'uid':st.st_uid,'gid':st.st_gid,'mode':oct(stat.S_IMODE(st.st_mode)),'device':st.st_dev,'inode':st.st_ino})
            out.append(json.loads(raw))
        directory.check();return out
    def source_bytes(self,path):return self.fs.read_path(path,{k:v for k,v in self.scope['source_metadata'][path].items() if k in ['uid','gid','mode','device','inode']})
    def close(self):self.fs.close()

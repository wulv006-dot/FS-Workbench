"""Reference-aware collection of rebuildable snapshots; original Excel is never purged."""
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import threading
import time

TZ=timezone(timedelta(hours=8))
HASH=re.compile(r'(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])')
MAX_FILE=64*1024*1024
GUARD=threading.RLock()
OWNED=threading.local()


@contextmanager
def maintenance_reader(root=Path('/var/lib/fs-hermes-fc/fs')):
    """Share the original Hermes admission inode; publication owns its exclusive lease."""
    path=Path(root)/'admission.lock'
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('maintenance_admission_link')
    fd=os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        info=os.fstat(fd);current=private(path)
        if (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino):raise ValueError('maintenance_admission_changed')
        try:
            if os.name=='posix':
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            else:
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        except OSError as error:
            import errno
            if error.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise
            raise BlockingIOError('maintenance_in_progress') from None
        yield
    finally:os.close(fd)


def private(path, directory=False):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('retention_symlink')
    s=path.stat()
    if (not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode))
            or (os.name=='posix' and (s.st_uid!=os.geteuid() or s.st_mode&0o077)) or (not directory and s.st_nlink!=1)):
        raise ValueError('retention_permissions')
    return s


def reference_file(path):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('retention_reference_symlink')
    s=path.stat()
    if not stat.S_ISREG(s.st_mode) or (os.name=='posix' and s.st_mode&0o002):raise ValueError('retention_reference_permissions')
    return s


def atomic(path,value):
    fd,temp=tempfile.mkstemp(prefix='.retention-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def sync_directory(path):
    if os.name!='posix':return
    fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)


@contextmanager
def cache_lock(root):
    root=Path(root)
    with GUARD:
        private(root,True)
        depths=getattr(OWNED,'depths',{})
        key=str(root.resolve())
        if depths.get(key):
            depths[key]+=1
            try:yield
            finally:depths[key]-=1
            return
        path=root/'.retention.lock'
        fd=os.open(str(path),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            private(path)
            if os.name=='posix':
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX)
            else:
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_LOCK,1)
            OWNED.depths=depths;depths[key]=1
            yield
        finally:
            depths.pop(key,None);os.close(fd)


def reference_versions(root,paths=None,databases=None):
    """Only emit hashes; failure to inspect any declared source prevents collection."""
    root=Path(root);fs=root.parent
    if paths is None:
        paths=[fs/p for p in ('reports','desktop-reports','nightly-data','reconciliation','contexts','customer-tracking')]
        paths.extend(Path('/var/lib/fc27-cloud')/p for p in
                     ('jobs','quotes','executions','previews','runs','evidence','all-coin-sync','player-sync','monitor'))
    if databases is None:databases=[fs/'tasks.sqlite3',fs/'conversations/conversations.db']
    refs=set();scanned=0;read_bytes=0;deadline=time.monotonic()+30
    for base in paths:
        if not base.exists():raise ValueError('retention_reference_root_missing')
        if any(p.is_symlink() for p in (base,*base.parents)):raise ValueError('retention_reference_symlink')
        s=base.stat()
        if not stat.S_ISDIR(s.st_mode) or (os.name=='posix' and s.st_mode&0o002):raise ValueError('retention_reference_root_permissions')
        for p in base.rglob('*'):
            if p.is_symlink():raise ValueError('retention_reference_symlink')
            if not p.is_file() or p.suffix not in ('.json','.jsonl','.md','.html','.txt'):continue
            s=reference_file(p)
            if s.st_size>MAX_FILE:raise ValueError('retention_reference_size')
            read_bytes+=s.st_size
            if read_bytes>1024*1024*1024 or time.monotonic()>deadline:raise ValueError('retention_reference_budget')
            # Existing unprivileged workers own some receipts; these reads only pin data.
            with p.open('rb') as f:
                tail=b''
                while True:
                    chunk=f.read(65536)
                    if not chunk:break
                    data=tail+chunk;refs.update(HASH.findall(data.decode('utf-8','ignore')));tail=data[-128:]
            scanned+=1
            if scanned>20000:raise ValueError('retention_reference_capacity')
    # Preparation receipts in this directory are durable references, not cache data.
    for p in root.glob('*.json'):
        if p.name.endswith('.data.json') or re.fullmatch(r'[a-f0-9]{64}\.json',p.name):continue
        if p.name.startswith('.'):continue
        private(p);refs.update(HASH.findall(p.read_text('utf-8')))
    for p in databases:
        reference_file(p)
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            db.set_progress_handler(lambda:1 if time.monotonic()>deadline else 0,10000)
            db.execute('BEGIN')
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for table in tables:
                quote=lambda v:'"'+v.replace('"','""')+'"'
                cols=[r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')
                      if not r[2] or any(t in r[2].upper() for t in ('TEXT','CHAR','BLOB'))]
                if not cols:continue
                for row in db.execute('SELECT '+','.join(map(quote,cols))+' FROM '+quote(table)):
                    for value in row:
                        if isinstance(value,str):
                            read_bytes+=len(value)
                            if read_bytes>1024*1024*1024 or time.monotonic()>deadline:raise ValueError('retention_reference_budget')
                            refs.update(HASH.findall(value))
    return refs,scanned


def _data(root,version):
    path=root/(version+'.data.json');s=private(path)
    if s.st_size>MAX_FILE:raise ValueError('retention_snapshot_size')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=version:raise ValueError('retention_snapshot_integrity')
    value=json.loads(raw)
    at=datetime.fromisoformat(value['saved_at'])
    if at.tzinfo is None:raise ValueError('retention_snapshot_time')
    return path,raw,value,at


def plan(root,now=None,paths=None,databases=None,references=None):
    root=Path(root);now=now or datetime.now(timezone.utc)
    refs,scanned=references if references is not None else reference_versions(root,paths,databases)
    refs=set(refs)
    for p in root.glob('*.json'):
        if re.fullmatch(r'[a-f0-9]{64}\.json',p.name):
            private(p);v=json.loads(p.read_text('utf-8')).get('version')
            if not isinstance(v,str) or re.fullmatch('[a-f0-9]{64}',v) is None:raise ValueError('retention_index')
            refs.add(v)
    candidates=[];protected=0
    for p in root.glob('*.data.json'):
        version=p.name[:-10]
        if re.fullmatch('[a-f0-9]{64}',version) is None:raise ValueError('retention_filename')
        if version in refs:protected+=1;continue
        _,raw,value,at=_data(root,version)
        ttl=7200 if value['family']=='native-loss' else 21600 if value['family']=='official-index' else 86400
        if (now-at).total_seconds()<ttl:continue
        candidates.append(dict(version=version,bytes=len(raw),saved_at=at.isoformat()))
    return dict(candidates=candidates,protected_versions=protected,scanned_reference_files=scanned,refs=refs)


def restore(path):
    path=Path(path);root=path.parent;version=path.name[:-10]
    if re.fullmatch(r'[a-f0-9]{64}\.data\.json',path.name) is None:raise FileNotFoundError(path)
    with cache_lock(root):
        if path.exists():return
        source=root/'.recycle'/(version+'.data.json.gz');private(source)
        fd,temp=tempfile.mkstemp(prefix='.restore-',dir=str(root));h=hashlib.sha256();size=0
        try:
            with gzip.open(source,'rb') as src,os.fdopen(fd,'wb') as dst:
                while True:
                    raw=src.read(65536)
                    if not raw:break
                    size+=len(raw)
                    if size>MAX_FILE:raise ValueError('retention_restore_size')
                    h.update(raw);dst.write(raw)
                dst.flush();os.fsync(dst.fileno())
            if h.hexdigest()!=version:raise ValueError('retention_restore_integrity')
            os.replace(temp,path)
            sync_directory(root)
        finally:
            if os.path.exists(temp):os.unlink(temp)


def collect(root,now=None,paths=None,databases=None,apply=False):
    root=Path(root);now=now or datetime.now(timezone.utc)
    # Scan durable references before the short storage mutation lock.
    references=reference_versions(root,paths,databases)
    with cache_lock(root):
        result=plan(root,now,paths,databases,references);refs=result.pop('refs')
        result.update(at=now.isoformat(),applied=apply,recycled_bytes=0,compressed_bytes=0,purged_files=0)
        if not apply:return result
        recycle=root/'.recycle';recycle.mkdir(mode=0o700,exist_ok=True);private(recycle,True)
        sync_directory(root)
        ledger_path=recycle/'index.json'
        if ledger_path.exists():private(ledger_path)
        ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        if not isinstance(ledger,dict):raise ValueError('retention_ledger')
        for version,item in ledger.items():
            if re.fullmatch('[a-f0-9]{64}',version) is None or not isinstance(item,dict):raise ValueError('retention_ledger')
            at=datetime.fromisoformat(item['moved_at'])
            if at.tzinfo is None:raise ValueError('retention_ledger_time')
        for item in result['candidates']:
            version=item['version'];p,raw,_,_=_data(root,version);target=recycle/(version+'.data.json.gz')
            fd,temp=tempfile.mkstemp(prefix='.compress-',dir=str(recycle))
            try:
                with os.fdopen(fd,'wb') as f:
                    with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(raw)
                    f.flush();os.fsync(f.fileno())
                with gzip.open(temp,'rb') as f:
                    if hashlib.sha256(f.read(MAX_FILE+1)).hexdigest()!=version:raise ValueError('retention_compressed_integrity')
                os.replace(temp,target)
                sync_directory(recycle)
            finally:
                if os.path.exists(temp):os.unlink(temp)
            ledger[version]=dict(moved_at=now.isoformat(),bytes=len(raw),compressed_bytes=target.stat().st_size)
            atomic(ledger_path,ledger)
            if hashlib.sha256(p.read_bytes()).hexdigest()!=version:raise ValueError('retention_source_changed')
            p.unlink();sync_directory(root);result['recycled_bytes']+=len(raw);result['compressed_bytes']+=target.stat().st_size
        # Only disposable cache copies expire; Excel archives have no purge path.
        for version,item in list(ledger.items()):
            if version in refs or (now-datetime.fromisoformat(item['moved_at'])).total_seconds()<7*86400:continue
            target=recycle/(version+'.data.json.gz')
            if target.exists():private(target);target.unlink();result['purged_files']+=1
            ledger.pop(version)
        atomic(ledger_path,ledger)
        atomic(root/'.retention-status.json',result)
        return result


def busy(root):
    fs=Path(root).parent
    for path,query in (
        (fs/'tasks.sqlite3',"SELECT count(*) FROM tasks WHERE state IN ('QUEUED','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')"),
        (fs/'tasks.sqlite3',"SELECT count(*) FROM requests WHERE state IN ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')"),
        (fs/'conversations/conversations.db',"SELECT count(*) FROM turns WHERE state NOT IN ('completed','failed','cancelled','interrupted')")):
        reference_file(path)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            if db.execute(query).fetchone()[0]:return True
    for p in Path('/var/lib/fc27-cloud/jobs').glob('*.json'):
        if json.loads(p.read_text()).get('status') in ('queued','running'):return True
    return False


def run(root,apply=False):
    root=Path(root);now=datetime.now(timezone.utc)
    if apply and busy(root):
        result=dict(at=now.isoformat(),status='deferred_active_task',applied=False)
    else:
        result=collect(root,now,apply=apply)
        from es_order_structure import maintain_archive
        result['excel']=maintain_archive(now=now,apply=apply)
        result['status']='completed' if apply else 'preview'
    if apply:atomic(root/'.retention-status.json',result)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    root=Path('/var/lib/fs-hermes-fc/fs/source-snapshots')
    try:print(json.dumps(run(root,args.apply)))
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        if args.apply:atomic(root/'.retention-status.json',dict(at=datetime.now(timezone.utc).isoformat(),status='failed',error=type(error).__name__+':'+str(error)[:160]))
        raise

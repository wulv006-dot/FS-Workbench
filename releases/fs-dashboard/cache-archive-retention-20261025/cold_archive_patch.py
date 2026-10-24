"""Apply one identical cold-store contract to the host and existing Admin ES readers."""
from pathlib import Path

HELPERS=r'''

_EXCEL_DEPTH=threading.local()


def _excel_private(path,directory=False):
    import os,stat
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('es_cold_symlink')
    s=path.stat()
    if (not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) or (os.name=='posix' and (s.st_uid!=os.geteuid() or s.st_mode&0o077)) or (not directory and s.st_nlink!=1)):raise ValueError('es_cold_permissions')
    return s


@contextmanager
def archive_access(root):
    import os
    root=Path(root)
    with ARCHIVE_LOCK:
        _excel_private(root,True)
        depths=getattr(_EXCEL_DEPTH,'depths',{});key=str(root.resolve())
        if depths.get(key):
            depths[key]+=1
            try:yield
            finally:depths[key]-=1
            return
        fd=os.open(str(root/'.archive-retention.lock'),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            _excel_private(root/'.archive-retention.lock')
            if os.name=='posix':
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX)
            else:
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_LOCK,1)
            _EXCEL_DEPTH.depths=depths;depths[key]=1
            yield
        finally:depths.pop(key,None);os.close(fd)


def _excel_atomic(path,value):
    import os,tempfile
    fd,temp=tempfile.mkstemp(prefix='.excel-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        _excel_sync(path.parent)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def _excel_sync(path):
    import os
    if os.name!='posix':return
    fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)


def _excel_digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
    return h.hexdigest()


def _excel_metadata(path):
    if not path.exists():return {}
    if _excel_private(path).st_size>1024*1024:raise ValueError('es_cold_metadata')
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or any(re.fullmatch('[a-f0-9]{64}',k) is None for k in value):raise ValueError('es_cold_metadata')
    return value


def excel_path(root,digest):
    import os,shutil,tempfile
    if re.fullmatch('[a-f0-9]{64}',digest) is None:raise ValueError('es_archive_integrity')
    path=root/(digest+'.xlsx')
    if path.exists():return path
    source=root/'.cold'/(digest+'.xlsx');_excel_private(source)
    if source.stat().st_size>MAX_FILE or _excel_digest(source)!=digest:raise ValueError('es_cold_integrity')
    fd,temp=tempfile.mkstemp(prefix='.excel-restore-',dir=str(root))
    try:
        with source.open('rb') as src,os.fdopen(fd,'wb') as dst:
            shutil.copyfileobj(src,dst,65536);dst.flush();os.fsync(dst.fileno())
        if _excel_digest(Path(temp))!=digest:raise ValueError('es_cold_integrity')
        os.replace(temp,path)
        _excel_sync(root)
        access=root/'.cold/access.json'
        saved=_excel_metadata(access)
        saved[digest]=datetime.now(timezone.utc).isoformat();_excel_atomic(access,saved)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return path


def maintain_archive(root=Path('/var/lib/fc27-es-exports'),now=None,apply=True):
    import os,shutil,tempfile
    root=Path(root);now=now or datetime.now(timezone.utc)
    with archive_access(root):
        cold=root/'.cold'
        if cold.exists():_excel_private(cold,True)
        access=_excel_metadata(cold/'access.json')
        refs=set();hot=set()
        for p in root.glob('*.json'):
            if p.name.startswith('.'):continue
            if _excel_private(p).st_size>1024*1024:raise ValueError('es_archive_manifest')
            v=json.loads(p.read_text());ids=set(v['file_sha256'])
            if any(re.fullmatch('[a-f0-9]{64}',d) is None for d in ids):raise ValueError('es_archive_integrity')
            refs.update(ids)
            end=date.fromisoformat(v['query']['end'])
            if end>=(now.astimezone(SHANGHAI).date()-timedelta(days=31)):hot.update(ids)
        hot.update(d for d,at in access.items() if (now-datetime.fromisoformat(at)).total_seconds()<86400)
        candidates=[]
        for digest in sorted(refs-hot):
            p=root/(digest+'.xlsx')
            if not p.exists():
                original=cold/p.name;_excel_private(original)
                if _excel_digest(original)!=digest:raise ValueError('es_cold_integrity')
                continue
            if _excel_private(p).st_size>MAX_FILE or _excel_digest(p)!=digest:raise ValueError('es_archive_integrity')
            candidates.append(dict(digest=digest,bytes=p.stat().st_size))
        result=dict(at=now.isoformat(),candidates=candidates,archived_files=0,archived_bytes=0,apply=apply,
                    protected_recent_files=len(hot),originals_deleted=0)
        if not apply:return result
        cold.mkdir(mode=0o700,exist_ok=True);_excel_private(cold,True);_excel_sync(root)
        ledger=cold/'index.json';saved=_excel_metadata(ledger)
        for item in candidates:
            digest=item['digest'];p=root/(digest+'.xlsx');target=cold/p.name
            if target.exists():
                _excel_private(target)
                if _excel_digest(target)!=digest:raise ValueError('es_cold_integrity')
            else:
                fd,temp=tempfile.mkstemp(prefix='.archive-',dir=str(cold))
                try:
                    with p.open('rb') as src,os.fdopen(fd,'wb') as dst:
                        shutil.copyfileobj(src,dst,65536);dst.flush();os.fsync(dst.fileno())
                    if _excel_digest(Path(temp))!=digest:raise ValueError('es_cold_integrity')
                    os.replace(temp,target)
                    _excel_sync(cold)
                finally:
                    if os.path.exists(temp):os.unlink(temp)
            saved[digest]=dict(archived_at=now.isoformat(),bytes=item['bytes']);_excel_atomic(ledger,saved)
            if _excel_digest(p)!=digest:raise ValueError('es_archive_changed')
            p.unlink();_excel_sync(root);result['archived_files']+=1;result['archived_bytes']+=item['bytes']
        _excel_atomic(cold/'last-maintenance.json',result)
        return result
'''


def patch(source):
    if 'def maintain_archive(' in source:raise ValueError('already_patched')
    source=source.replace('from collections import defaultdict','from contextlib import contextmanager\nfrom collections import defaultdict',1)
    source=source.replace('    with ARCHIVE_LOCK:\n        if any(p.is_symlink()', "    if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('es_archive_symlink')\n    root.mkdir(mode=0o700,parents=True,exist_ok=True)\n    with archive_access(root):\n        if any(p.is_symlink()",1)
    anchor='        for path in root.iterdir():\n            info=path.lstat()'
    assert source.count(anchor)==1
    source=source.replace(anchor,"        for path in root.iterdir():\n            if path.name=='.cold':_excel_private(path,True);continue\n            if path.name=='.archive-retention.lock':_excel_private(path);continue\n            info=path.lstat()",1)
    original='        path=root/(digest+\'.xlsx\')\n        info=path.lstat()'
    assert source.count(original)==1
    source=source.replace(original,"        path=excel_path(root,digest)\n        info=path.lstat()",1)
    wrapper="""def archived_dataset(args,root=Path('/var/lib/fc27-es-exports')):
    if not root.exists():return None
    with SERVER_LOCK,archive_access(root):
        return _archived_dataset(args,root)


"""
    start=source.index('def archived_dataset(')
    if 'def _archived_dataset(' in source:
        end=source.index('def _archived_dataset(',start)
        source=source[:start]+wrapper+source[end:]
    else:
        source=source[:start]+wrapper+source[start:].replace('def archived_dataset(', 'def _archived_dataset(',1)
        source=source.replace("def _archived_dataset(args,root=Path('/var/lib/fc27-es-exports')):","def _archived_dataset(args,root):",1)
    return source+HELPERS


if __name__=='__main__':
    for name in ('es_order_structure.py','session_es_order_structure.py'):
        p=Path(__file__).parent/'source'/name
        p.write_bytes(patch(p.read_text(encoding='utf-8')).encode())

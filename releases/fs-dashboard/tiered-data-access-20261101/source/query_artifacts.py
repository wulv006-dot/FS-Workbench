"""Bounded JSONL artifacts under existing Archive root; no automatic deletion."""
from contextlib import closing,contextmanager
import hashlib,os,re,tempfile,time,uuid
from pathlib import Path
from range_jobs import encode
from date_policy import PolicyError


class Artifacts:
    def __init__(self,archive,clock=time.time):self.archive,self.clock=archive,clock

    def initialize(self):
        with closing(self.archive.database(True)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS range_query_artifacts(id TEXT PRIMARY KEY,handle TEXT,key TEXT,generation TEXT,expires REAL,bytes INTEGER,sha256 TEXT,pins INTEGER)')

    def path(self,ident):
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):raise PolicyError('artifact_id')
        self.archive.safe()
        path=self.archive.root/'query-artifacts'/(ident+'.jsonl')
        if any(p.is_symlink() for p in (path,*path.parents)):raise PolicyError('artifact_symlink')
        return path

    def create(self,engine,identity,handle,ttl=86400):
        if type(ttl) is not int or not 0<ttl<=86400:raise ValueError('artifact_ttl')
        with engine.lock:
            sub,job=engine.access(identity,handle)
            if not sub['active'] or job['status']!='complete':raise PolicyError('result_not_complete')
            key,generation=sub['key'],job['generation']
        ident=uuid.uuid4().hex;path=self.path(ident);path.parent.mkdir(mode=0o700,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.query-',dir=path.parent);size=0;checksum=hashlib.sha256();published=False
        try:
            with os.fdopen(fd,'wb') as output:
                cursor=None
                while True:
                    page=engine.page(identity,handle,cursor=cursor,limit=100)
                    for row in page['data']:
                        raw=encode(row)+b'\n';size+=len(raw)
                        if size>8*1024*1024:raise ValueError('artifact_budget')
                        checksum.update(raw);output.write(raw)
                    cursor=page['next_cursor']
                    if cursor is None:break
                output.flush();os.fsync(output.fileno())
            with engine.lock:
                sub,job=engine.access(identity,handle)
                if not sub['active'] or job['generation']!=generation:raise PolicyError('cancelled')
                os.replace(temp,path)
                with closing(self.archive.database(True)) as db,db:
                    db.execute('INSERT INTO range_query_artifacts VALUES(?,?,?,?,?,?,?,0)',(ident,handle,key,generation,self.clock()+ttl,size,checksum.hexdigest()))
                published=True
            return dict(artifact_id=ident,bytes=size,sha256=checksum.hexdigest())
        finally:
            if os.path.exists(temp):os.unlink(temp)
            if not published and path.exists():path.unlink()  # Only this newly generated candidate file.

    def allowed(self,engine,identity,handle,meta):
        with engine.lock:
            sub,job=engine.access(identity,handle)
            if not sub['active'] or meta['handle']!=handle or meta['key']!=sub['key'] or meta['generation']!=job['generation'] or self.clock()>=meta['expires']:raise PolicyError('artifact_unavailable')

    @contextmanager
    def download(self,engine,identity,handle,ident):
        path=self.path(ident)
        with engine.lock,closing(self.archive.database(True)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM range_query_artifacts WHERE id=?',(ident,)).fetchone()
            if row is None:raise PolicyError('artifact_unavailable')
            meta=dict(row);self.allowed(engine,identity,handle,meta)
            db.execute('UPDATE range_query_artifacts SET pins=pins+1 WHERE id=?',(ident,))
        stream=None
        try:
            def chunks():
                fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                with os.fdopen(fd,'rb') as source:
                    checksum=hashlib.sha256();size=0
                    while True:
                        self.allowed(engine,identity,handle,meta)
                        raw=source.read(65536)
                        if not raw:break
                        size+=len(raw)
                        if size>meta['bytes']:raise ValueError('artifact_integrity')
                        checksum.update(raw);yield raw
                    if size!=meta['bytes'] or checksum.hexdigest()!=meta['sha256']:raise ValueError('artifact_integrity')
            stream=chunks()
            yield stream
        finally:
            if stream is not None:stream.close()
            with closing(self.archive.database(True)) as db,db:db.execute('UPDATE range_query_artifacts SET pins=pins-1 WHERE id=? AND pins>0',(ident,))

    def expired_candidates(self):
        with closing(self.archive.database()) as db:
            return [dict(row) for row in db.execute('SELECT id,bytes FROM range_query_artifacts WHERE expires<=? AND pins=0',(self.clock(),))]

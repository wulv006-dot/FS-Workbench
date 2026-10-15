"""A separate, provenance-bearing report catalogue. No task/model/fee writes."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

CONTRACT='fs-imported-reports-v1'
MAX_FILE=2*1024*1024
MAX_CATALOG=1024*1024
ID=re.compile(r'import-[a-f0-9]{32}')
SHA=re.compile(r'[a-f0-9]{64}')

def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def sha(value):return hashlib.sha256(value).hexdigest()

def unlinked(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('import_path_linked')
    return path

def read_bytes(path,limit):
    path=unlinked(path)
    with path.open('rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('import_file_not_regular')
        value=f.read(limit+1)
    if len(value)>limit:raise ValueError('import_size')
    value.decode('utf-8')
    return value

def atomic(path,value):
    path=unlinked(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o750)
    fd,tmp=tempfile.mkstemp(prefix='.import-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:f.write(value);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o640);os.replace(tmp,path)
        if os.name!='nt':
            directory=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

@contextmanager
def catalogue_lock(root):
    root=unlinked(root);root.mkdir(parents=True,exist_ok=True,mode=0o750)
    with unlinked(root/'catalog.lock').open('a+b') as f:
        if os.name=='nt':
            import msvcrt
            if not f.tell():f.write(b'0');f.flush()
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX)
        try:yield
        finally:
            if os.name=='nt':f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f,fcntl.LOCK_UN)

def checked_text(value,limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or re.search(r'[<>\x00-\x1f\x7f]',value):raise ValueError('import_metadata')
    return value

def validate(record):
    if set(record)!={'id','owner','author','version','title','start','end','report_kind','imported_at','source_manifest_sha256','html_sha256','markdown_sha256'}:raise ValueError('import_record_fields')
    if not ID.fullmatch(record['id']) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',record['owner']):raise ValueError('import_identity')
    for k,limit in [('author',100),('version',100),('title',200)]:checked_text(record[k],limit)
    lo,hi=date.fromisoformat(record['start']),date.fromisoformat(record['end'])
    if lo>hi or lo.isoformat()!=record['start'] or hi.isoformat()!=record['end'] or (hi-lo).days>366:raise ValueError('import_period')
    if record['report_kind'] not in {'daily','weekly','monthly','pricing'}:raise ValueError('import_report_kind')
    if datetime.fromisoformat(record['imported_at']).tzinfo is None:raise ValueError('import_time')
    for k in ['source_manifest_sha256','html_sha256','markdown_sha256']:
        if not isinstance(record[k],str) or not SHA.fullmatch(record[k]):raise ValueError('import_digest')
    identity={k:v for k,v in record.items() if k not in {'id','imported_at','source_manifest_sha256'}}
    if record['id']!='import-'+sha(encoded(identity))[:32]:raise ValueError('import_identity')
    return record

class ImportedReports:
    def __init__(self,fs_root):
        # Outside the Desktop /fs bind: importing requires the server operator.
        self.root=unlinked(Path(fs_root).parent/'imported-reports')
        self.catalog=self.root/'catalog.json'

    def load(self):
        if not self.catalog.exists():return []
        model=json.loads(read_bytes(self.catalog,MAX_CATALOG))
        if set(model)!={'contract','items'} or model['contract']!=CONTRACT or not isinstance(model['items'],list) or len(model['items'])>1000:raise ValueError('import_catalog')
        rows=[validate(v) for v in model['items']]
        if len({v['id'] for v in rows})!=len(rows):raise ValueError('import_duplicate')
        return rows

    @staticmethod
    def job(row):
        return {'id':row['id'],'state':'IMPORTED','owner':row['owner'],
                'body':{'kind':'imported_report','start':row['start'],'end':row['end'],'question':row['title'],
                        'mode':'pricing' if row['report_kind']=='pricing' else 'investigation','report_kind':row['report_kind']},
                'imported':{k:row[k] for k in ['author','version','imported_at','source_manifest_sha256','html_sha256','markdown_sha256']},
                'can_delete':False,'can_followup':False,'can_continue':False,'model_usage':{'calls':0,'total_tokens':0}}

    def listed(self,user,shared,params):
        scope=params.get('scope',['shared'])[0]
        if scope=='trash':return []
        rows=self.load()
        if not shared or scope=='mine':rows=[r for r in rows if r['owner']==user]
        for key in ['start','end']:
            if key in params:rows=[r for r in rows if r[key]==params[key][0]]
        query=params.get('q',[''])[0].casefold()
        if query:rows=[r for r in rows if query in ' '.join(str(v) for v in r.values()).casefold()]
        return [self.job(r) for r in sorted(rows,key=lambda r:(r['imported_at'],r['id']),reverse=True)]

    def get(self,params,user,shared):
        key=params['id'][0]
        if not ID.fullmatch(key):return 404,{'error':'not_found'}
        row=next((r for r in self.load() if r['id']==key and (shared or r['owner']==user)),None)
        if row is None:return 404,{'error':'not_found'}
        if 'evidence' in params:return 404,{'error':'not_found'}
        if 'thread' in params:return (200,{'items':[]}) if params['thread']==['1'] else (422,{'error':'invalid_parameters'})
        if 'artifact' not in params:return 200,self.job(row)
        kind=params['artifact'][0]
        if kind not in {'html','boss','md'}:return 404,{'error':'report_artifact_not_found'}
        html=kind in {'html','boss'};name='report.html' if html else 'report.md'
        raw=read_bytes(self.root/key/name,MAX_FILE)
        if sha(raw)!=row['html_sha256' if html else 'markdown_sha256']:return 409,{'error':'import_artifact_changed'}
        return 200,{'content':raw.decode('utf-8'),'mime':'text/html; charset=utf-8' if html else 'text/markdown; charset=utf-8',
                    'filename':row['title']+('.html' if html else '.md'),'sha256':sha(raw)}

    def register(self,source,manifest,plans,owner='wulv',apply=False,expected_catalog_sha256=None,expected_source_manifest_sha256=None):
        source=unlinked(source);manifest=unlinked(manifest)
        if manifest.parent!=source or manifest.name!='MANIFEST.json':raise ValueError('import_manifest_path')
        mb=read_bytes(manifest,MAX_CATALOG)
        if expected_source_manifest_sha256 is not None and sha(mb)!=expected_source_manifest_sha256:raise ValueError('import_source_manifest_changed')
        metadata=json.loads(mb)
        if metadata.get('contract')!='hermes-desktop-reports-v1':raise ValueError('import_source_contract')
        if not isinstance(metadata.get('files'),list) or len(metadata['files'])>100:raise ValueError('import_source_files')
        listed={r['file']:r for r in metadata['files']}
        if len(listed)!=len(metadata['files']):raise ValueError('import_source_duplicate')
        if not isinstance(plans,list) or not 1<=len(plans)<=20:raise ValueError('import_plan')
        prepared=[];stamp=datetime.now(timezone.utc).isoformat()
        for plan in plans:
            if set(plan)!={'html','markdown','author','version','title','start','end','report_kind'}:raise ValueError('import_plan_fields')
            payload={}
            for kind,extension in [('html','.html'),('markdown','.md')]:
                name=plan[kind]
                if not isinstance(name,str) or Path(name).name!=name or any(c in name for c in '/\\:') or not name.endswith(extension):raise ValueError('import_filename')
                info=listed.get(name)
                if not info:raise ValueError('import_file_not_manifested')
                raw=read_bytes(source/name,MAX_FILE)
                if info.get('sha256')!=sha(raw) or info.get('bytes')!=len(raw):raise ValueError('import_source_changed')
                if kind=='html' and not re.search(r'<html\b',raw.decode(),re.I):raise ValueError('import_html_required')
                payload[kind]=raw
            identity={k:plan[k] for k in ['author','version','title','start','end','report_kind']}
            identity.update(owner=owner,html_sha256=sha(payload['html']),markdown_sha256=sha(payload['markdown']))
            row=validate(dict(identity,id='import-'+sha(encoded(identity))[:32],imported_at=stamp,source_manifest_sha256=sha(mb)))
            prepared.append((row,payload))
        if len({r['id'] for r,_ in prepared})!=len(prepared):raise ValueError('import_duplicate_plan')
        preview={'contract':CONTRACT,'applied':False,'model_calls':0,'task_rows_written':0,'items':[self.job(r) for r,_ in prepared]}
        if not apply:return preview
        with catalogue_lock(self.root):
            actual=sha(read_bytes(self.catalog,MAX_CATALOG)) if self.catalog.exists() else None
            if expected_catalog_sha256!=actual:raise ValueError('import_catalog_changed')
            rows=self.load();ids={r['id'] for r in rows};new=[]
            for row,payload in prepared:
                folder=unlinked(self.root/row['id'])
                for name,kind in [('report.html','html'),('report.md','markdown')]:
                    dest=folder/name
                    if dest.exists():
                        if read_bytes(dest,MAX_FILE)!=payload[kind]:raise ValueError('import_artifact_conflict')
                    else:atomic(dest,payload[kind])
                if row['id'] not in ids:rows.append(row);new.append(row['id']);ids.add(row['id'])
            if len(rows)>1000:raise ValueError('import_catalog_full')
            if new:atomic(self.catalog,encoded({'contract':CONTRACT,'items':rows}))
            return dict(preview,applied=True,new_ids=new,reused=len(prepared)-len(new),catalog_sha256=sha(read_bytes(self.catalog,MAX_CATALOG)))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Operator-only, hash-verified report import. No model call.')
    parser.add_argument('--fs-root',type=Path,required=True);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--owner',default='wulv')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--expected-catalog-sha256');parser.add_argument('--expected-source-manifest-sha256')
    args=parser.parse_args()
    if args.apply and not args.expected_source_manifest_sha256:parser.error('--apply requires --expected-source-manifest-sha256 from the approved preview')
    value=ImportedReports(args.fs_root).register(args.source,args.source/'MANIFEST.json',json.loads(args.plan.read_text('utf-8')),args.owner,args.apply,args.expected_catalog_sha256,args.expected_source_manifest_sha256)
    print(json.dumps(value,ensure_ascii=True))

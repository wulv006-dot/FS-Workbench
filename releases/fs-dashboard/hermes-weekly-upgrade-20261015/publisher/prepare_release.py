"""Prepare only an isolated stage for the existing publisher; no live replacement."""
import hashlib,json,sqlite3,subprocess,sys,zipfile
from pathlib import Path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    out={}
    with sqlite3.connect('file:/var/lib/fs-hermes-fc/fs/tasks.sqlite3?mode=ro',uri=True) as db:
        for name in ('requests','tasks','evidence','nightly_requests','report_trash'):
            rows=db.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()
            raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()
            out[name]={'rows':len(rows),'sha256':hashlib.sha256(raw).hexdigest()}
    out['services']=subprocess.check_output(['systemctl','show','fs-business-range.service','fs-hermes-fc.service','fs-hermes-desktop.service','fc27-cloud-api.service','fc27-cloud-worker.service','-p','Id','-p','ActiveState','-p','MainPID'],text=True)
    return out


def main():
    stage=Path(__file__).resolve().parent
    spec=json.loads((stage/'release-input.json').read_text())
    bundle=stage/'candidate.zip'
    if digest(bundle)!=spec['zip_sha256']:raise ValueError('candidate archive changed')
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            target=(stage/info.filename).resolve()
            if stage not in target.parents or info.filename.startswith('/') or info.is_dir():raise ValueError('invalid candidate path')
            if target.exists():raise ValueError('stage already populated; reconcile')
        archive.extractall(stage)
    mapping=spec['mapping'];files=[]
    for row in mapping['files']:
        p=Path(row['runtime']);before=digest(p) if p.is_file() else None
        if before!=row['beforeSha256']:raise ValueError('runtime drift: '+str(p))
        source=stage/'candidate'/row['candidate']
        if digest(source)!=row['sha256']:raise ValueError('candidate changed')
        files.append({'candidate':row['candidate'],'target':row['runtime'],'sha256':row['sha256'],'beforeSha256':before})
    protected=[{'path':p,'sha256':digest(Path(p))} for p in spec['protected']]
    manifest={'schemaVersion':1,'scope':mapping['scope'],'sourceCommit':spec['sourceCommit'],'imageId':spec['imageId'],
              'businessWrites':False,'timersChanged':False,'files':files,'unchangedRequired':protected,'runtimeRequired':spec['runtimeRequired']}
    (stage/'before.json').write_text(json.dumps(snapshot(),ensure_ascii=False,indent=2))
    raw=json.dumps(manifest,ensure_ascii=False,indent=2).encode();(stage/'approved-manifest.json').write_bytes(raw)
    import release_navigation
    release_navigation.validate(manifest,stage)
    result=release_navigation.inspect(manifest,stage)
    print(json.dumps({'prepared':True,'manifest_sha256':hashlib.sha256(raw).hexdigest(),'targets':len(files),'protected':len(protected),'inspect':result},ensure_ascii=False))

if __name__=='__main__':main()

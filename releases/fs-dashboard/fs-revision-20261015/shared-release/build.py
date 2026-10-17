"""Freeze the eight shared UI assets after the native release, without publishing."""
import hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
rows=[]
for row in json.loads((ROOT/'navigation/candidate-runtime-map.json').read_text('utf-8'))['rows']:
    rel=row['candidate']
    if not rel.startswith('mutable/') or rel=='mutable/navigation.js':continue
    name=rel.removeprefix('mutable/')
    source=ROOT/'navigation/candidate'/rel
    target=HERE/'candidate/revision'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    rows.append(dict(candidate='revision/'+name,target=row['baselineTarget'],beforeSha256=row['beforeSha256'],sha256=digest(source)))
for name in ('index.html','brain.js','brain.css'):
    source=ROOT/'brain'/name;target=HERE/'candidate/revision/brain'/name
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    rows.append(dict(candidate='revision/brain/'+name,target='/var/www/dashboard/fs-home/brain/'+name,beforeSha256=None,sha256=digest(source)))
native=json.loads((ROOT/'frontend-release/stage/release-manifest.json').read_text('utf-8'))
protected={r['path']:r['sha256'] for r in native['unchangedRequired']}
protected.update({r['target']:r['sha256'] for r in native['immutableAssets']+native['targets']})
for row in rows:protected.pop(row['target'],None)
manifest=dict(schemaVersion=1,scope='fs-revision-ui-20261015',releaseReady=False,files=rows,
              unchangedRequired=[dict(path=p,sha256=s) for p,s in sorted(protected.items())],runtimeRequired={})
(HERE/'candidate-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'targets':len(rows),'protected':len(protected),'afterNative':native['releaseId'],'releaseReady':False}))

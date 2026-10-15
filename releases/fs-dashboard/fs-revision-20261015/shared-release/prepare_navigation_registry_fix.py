"""Prepare the two-file consumer fix after the verified eight-target UI release; no publish."""
from pathlib import Path
import hashlib,json,shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
manifest_path=HERE/'candidate-manifest.json'
archive=HERE/'pre-registry-fix-8target-manifest.json'
if not archive.exists():
    original=manifest_path.read_bytes()
    assert len(json.loads(original)['files'])==8,'An exact original eight-target release is required'
    archive.write_bytes(original)
manifest=json.loads(archive.read_text('utf-8'))
live=json.loads((HERE/'navigation-live-baseline.json').read_text('utf-8-sig'))
for row in manifest['files']:
    assert live['files'][row['target']]['sha256']==row['sha256'],row['target']
    row['beforeSha256']=row['sha256']
    candidate=HERE/'candidate'/row['candidate']
    if row['candidate']=='revision/brain/brain.js':
        source=ROOT/'brain/brain.js'
        assert digest(source)=='a751e85b9f3f103ffe5ac1b871ee4ce469dc5a9a037f61a310bcc39998e42f6d'
        shutil.copyfile(source,candidate)
    row['sha256']=digest(candidate)
native=ROOT/'frontend-release/stage/assets/navigation.json'
native_runtime='/var/lib/fs-navigation-formal-static/workspace-native-20261006-261bedcc395a/navigation.json'
assert live['files'][native_runtime]['sha256']==digest(native)
target='/var/www/dashboard/fs-home/navigation.json'
before=next((r['sha256'] for r in manifest['unchangedRequired'] if r['path']==target),None)
if before is not None:assert before==live['files'][target]['sha256']
else:before=live['files'][target]['sha256']
candidate=HERE/'candidate/revision/navigation.json'
shutil.copyfile(native,candidate)
manifest['files'].append(dict(candidate='revision/navigation.json',target=target,beforeSha256=before,sha256=digest(candidate)))
manifest['unchangedRequired']=[r for r in manifest['unchangedRequired'] if r['path']!=target]
assert len(manifest['files'])==9
manifest['releaseReady']=False
manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n','utf-8')
result=dict(releaseReady=False,targets=9,contentChanges=[r for r in manifest['files'] if r['beforeSha256']!=r['sha256']],
            nativeNavigationSource=native_runtime,baselineEvidence='navigation-live-baseline.json',
            previousEightTargetManifest='pre-registry-fix-8target-manifest.json',productionWrites=0)
(HERE/'navigation-registry-fix.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps(result))

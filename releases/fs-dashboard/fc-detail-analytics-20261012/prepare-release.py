"""Freeze this FC payload for the existing two publishers; never deploys."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/('fs_on_demand_20261012' if (ROOT.parent/'fs_on_demand_20261012').exists() else 'on-demand-20261012')
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((ROOT/'baseline-readback.json').read_text('utf-8-sig'))
m=json.loads((BASE/'native-boundary/release-manifest.json').read_text())
m.update(scope='fc-detail-analytics-20261012',releaseReady=True)
m['files']=[{'candidate':'fc/'+p.name,'target':'/opt/fs-exact-range-20261001/'+p.name,'beforeSha256':baseline['hashes']['/opt/fs-exact-range-20261001/'+p.name],'sha256':digest(p)}for p in sorted((ROOT/'source').iterdir())if p.suffix in ('.py','.json')]
assert len(m['files'])==5
targets={r['target']for r in m['files']}
m['unchangedRequired']=[{'path':r['path'],'sha256':baseline['hashes'][r['path']]}for r in m['unchangedRequired']if r['path']not in targets]
assert all(r['sha256'] for r in m['unchangedRequired'])
(ROOT/'deploy/approved-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n','utf-8')
f=json.loads((ROOT/'frontend/release-contract.json').read_text());f['releaseReady']=True
(ROOT/'frontend/approved-manifest.json').write_text(json.dumps(f,ensure_ascii=False,indent=2)+'\n','utf-8')
with zipfile.ZipFile(ROOT/'release-payload.zip','w',zipfile.ZIP_DEFLATED)as z:
 for name in ('deploy','frontend'):
  paths=list((ROOT/name).rglob('*'))
  for p in paths:
   rel=p.relative_to(ROOT).as_posix()
   if p.is_file() and '__pycache__'not in p.parts and (name=='deploy' or rel.startswith(('frontend/assets/','frontend/candidate/')) or p.name in ('release-contract.json','approved-manifest.json','release_workspace.py','release_navigation.py')):z.write(p,rel)
print(json.dumps({'frontend':f['releaseId'],'backendManifest':digest(ROOT/'deploy/approved-manifest.json'),'frontendManifest':digest(ROOT/'frontend/approved-manifest.json'),'payload':digest(ROOT/'release-payload.zip')}))

from pathlib import Path
import json,hashlib,shutil,importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('backendpub',ROOT/'release/publish_backend.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
files={name:(ROOT/'source/backend'/name).read_bytes() for name in pub.TARGETS}
rid='management-v2-'+hashlib.sha256(b''.join(n.encode()+files[n] for n in sorted(files))).hexdigest()[:12]
stage=ROOT/'release'/rid
if stage.exists():raise SystemExit('immutable stage exists')
stage.mkdir()
rows=[]
for name,target in pub.TARGETS.items():
 (stage/name).write_bytes(files[name]);baseline=ROOT/'release/management-v2-74a2c7d67093'/name
 rows.append({'candidate':name,'target':target,'beforeSha256':hashlib.sha256(baseline.read_bytes()).hexdigest() if baseline.is_file() else None,'sha256':hashlib.sha256(files[name]).hexdigest()})
protected=[('/opt/fs-hermes-fc/research.py','55f7e8cc93dafa7603606ebe8f9ab3532d6cdedc73553e74f9fc90772e8332eb'),('/opt/fs-boss-workspaces/backend/boss_daily.py','9b102d43b11792e72e374af46819b2904b84b061a4da712ed4c44bc86048a8d1'),('/opt/fs-boss-workspaces/backend/nightly_http.py','733a8c0e0bdc01fe73016ce55b80bc8c961985829eff2335edf84662f3d5ba54'),('/opt/fs-boss-workspaces/source/management/targets.json','2985f9a48902b577cfe6955b95c82f191a2f34d1bc10302aad8c5d4581ce8102'),('/etc/systemd/system/fs-boss-management.timer','acc10079b5c2915d2bcb3286310845adfae14d3e616c3bb171f7affd98a8353c')]
m={'scope':'fs-management-v2-backend','releaseId':rid,'businessWrites':False,'credentialsChanged':False,'files':rows,'unchangedRequired':[{'path':p,'sha256':s} for p,s in protected]}
(stage/'contract.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n');shutil.copy(ROOT/'release/publish_backend.py',stage/'publish_backend.py')
shutil.copy(ROOT/'baseline/release_navigation_base.py',stage/'release_navigation_base.py')
print(stage);print(hashlib.sha256((stage/'contract.json').read_bytes()).hexdigest())

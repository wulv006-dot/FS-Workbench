from pathlib import Path
import hashlib,json,shutil,datetime
P=Path(__file__).parent;C=P/'candidate/fc';C.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
root=Path('/opt/fs-exact-range-20261001')
if sha(root/'fc_detail_model.py')!='684f9ea5dd53d3c40f359e82c40c115136ffb44173181d939c71154b46184dda':raise ValueError('model_baseline_drift')
rows=[]
for n in ['range_api.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json']:
 if n!='fc_detail_model.py':shutil.copyfile(root/n,C/n)
 rows.append({'candidate':'fc/'+n,'target':str(root/n),'beforeSha256':sha(root/n),'sha256':sha(C/n),'mode':'0o644','owner':'0:0'})
previous=json.loads(Path('/opt/fs-release-stage/customer-pool-lifecycle-20261019/approved-manifest.json').read_text())
paths={r['path'] for r in previous['unchangedRequired']}|{r['target'] for r in previous['files']}
guards=[{'path':t,'sha256':sha(Path(t))} for t in sorted(paths-{r['target'] for r in rows})]
m={'schemaVersion':1,'scope':'fc-order-wait-sort-20261020','releaseReady':True,'businessWrites':False,'timersChanged':False,'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'}},'files':rows,'unchangedRequired':guards,'baselineObservedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}
raw=json.dumps(m,indent=2).encode();(P/'approved-manifest.json').write_bytes(raw);print('MANIFEST',hashlib.sha256(raw).hexdigest(),'GUARDS',len(guards))

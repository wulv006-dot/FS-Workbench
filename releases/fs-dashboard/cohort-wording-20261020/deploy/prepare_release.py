from pathlib import Path
import hashlib,json,re
P=Path(__file__).parent;C=P/'candidate';C.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
old='workspace-native-20261006-afff372192a3';new='workspace-native-20261006-916087de9ef6'
index=Path('/var/lib/fs-navigation-formal-static')/old/'tools-index.html';conf=Path('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf')
assert sha(index)=='a0eaeb20622b456bd3592758f94458a8889a553e92185f01f6c39980fbeae913'
assert sha(conf)=='5c1a37a5202f8507d543658bf999a6b37709fccb8b85a41e2ee0d7d03d2a345d'
a='/dashboard/workspace-assets/'+old+'/data-workspace.js';b=a.replace(old,new)
s=index.read_text();assert s.count(a)==1;s=s.replace(a,b);(C/'tools-index.html').write_text(s)
s=conf.read_text();match=re.search(r'location = '+re.escape(a)+r' \{.*?\n\}',s,re.S);assert match
block=match.group();assert 'auth_request /__nav_formal_native_session;' in block
assert b not in s;s+='\n\n# Cohort wording only; identical existing auth and static boundary.\n'+block.replace(old,new)+'\n';(C/'formal.conf').write_text(s)
target=Path('/var/lib/fs-navigation-formal-static')/new/'data-workspace.js';assert not target.exists()
T={'data-workspace.js':(target,None),'tools-index.html':(index,sha(index)),'formal.conf':(conf,sha(conf))}
base=json.loads(Path('/opt/fs-release-stage/fc-order-wait-sort-20261020/approved-manifest.json').read_text())
paths={r['path'] for r in base['unchangedRequired']}|{r['target'] for r in base['files']}
guards=[{'path':t,'sha256':sha(Path(t))} for t in sorted(paths-{str(x[0]) for x in T.values()})]
m={'schemaVersion':1,'scope':'traffic-source-tabs-ui-finish-20261019','releaseReady':True,'businessWrites':False,'timersChanged':False,'runtimeRequired':{'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}},'unchangedRequired':guards,'files':[{'candidate':r,'target':str(t),'beforeSha256':before,'sha256':sha(C/r)} for r,(t,before) in T.items()]}
(P/'targets.json').write_text(json.dumps({r:str(t) for r,(t,_) in T.items()}));raw=json.dumps(m,indent=2).encode();(P/'manifest.json').write_bytes(raw);print('MANIFEST',hashlib.sha256(raw).hexdigest())

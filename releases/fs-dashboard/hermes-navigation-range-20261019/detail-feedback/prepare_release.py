from pathlib import Path
import json,hashlib
P=Path(__file__).parent;C=P/'candidate'
R='/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
T={'page.js':(R+'page.js','7584b337ac09f1c4d3c86114af0355731be3f4a472db82eac481becdf1059701'),'customer-index.html':(R+'index.html','ec7814903309a5babc7d27d2bf745d07ad13c5230b079bb2a3ff079b75d89f61'),'detail-feedback.css':(R+'detail-feedback.css',None)}
for name,(target,sha) in T.items():
 if digest(Path(target))!=sha:raise ValueError('baseline drift: '+target)
# Preserve current protected requirements from the independently verified prior release.
b=json.loads(Path('/opt/fs-release-stage/hermes-navigation-range-20261019/polish/manifest.json').read_text())
b['files']=[{'candidate':n,'target':t,'beforeSha256':sha,'sha256':digest(C/n)} for n,(t,sha) in T.items()]
for row in b['unchangedRequired']:
 if digest(Path(row['path']))!=row['sha256']:raise ValueError('protected drift: '+row['path'])
(P/'targets.json').write_text(json.dumps({n:t for n,(t,sha) in T.items()}))
raw=json.dumps(b,indent=2).encode();(P/'manifest.json').write_bytes(raw);print('MANIFEST',hashlib.sha256(raw).hexdigest())

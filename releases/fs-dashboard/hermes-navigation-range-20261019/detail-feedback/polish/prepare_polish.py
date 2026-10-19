from pathlib import Path
import json,hashlib
P=Path(__file__).parent;B=P.parent
m=json.loads((B/'manifest.json').read_text());old={r['candidate']:r for r in m['files']};files=[]
for name in ['page.js','customer-index.html','page.css']:
 if name=='page.css':target=old['page.js']['target'].replace('page.js','page.css');before='5204d0d9e5cadaddcb7195d8c5ba559fd9deb21b63f9081373713a1752bf6f66'
 else:target=old[name]['target'];before=old[name]['sha256']
 if hashlib.sha256(Path(target).read_bytes()).hexdigest()!=before:raise ValueError('baseline drift '+target)
 files.append({'candidate':name,'target':target,'beforeSha256':before,'sha256':hashlib.sha256((P/'candidate'/name).read_bytes()).hexdigest()})
m['files']=files;(P/'targets.json').write_text(json.dumps({r['candidate']:r['target'] for r in files}));raw=json.dumps(m,indent=2).encode();(P/'manifest.json').write_bytes(raw);print('MANIFEST',hashlib.sha256(raw).hexdigest())

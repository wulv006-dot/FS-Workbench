from pathlib import Path
import json,hashlib
P=Path(__file__).parent;B=P.parent
m=json.loads((B/'manifest.json').read_text());keep={'page.js','hermes-index.html','hermes-nav.css'}
m['files']=[dict(r,beforeSha256=r['sha256'],sha256=hashlib.sha256((P/'candidate'/r['candidate']).read_bytes()).hexdigest()) for r in m['files'] if r['candidate'] in keep]
assert len(m['files'])==3
(P/'targets.json').write_text(json.dumps({r['candidate']:r['target'] for r in m['files']}))
raw=json.dumps(m,indent=2).encode();(P/'manifest.json').write_bytes(raw);print('MANIFEST',hashlib.sha256(raw).hexdigest())

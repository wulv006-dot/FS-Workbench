"""Two static files: compact chart and visible Ads metrics; no data/service changes."""
from pathlib import Path
import hashlib,json,sys
BASE=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
sys.path.insert(0,str(BASE))
import release_ui_finish as ui
TARGETS={r:'/var/lib/fs-navigation-formal-static/workspace-native-20261019-traffic-v3/'+r.split('/')[-1] for r in ('ui/google.js','ui/google.css')}
BEFORE={'ui/google.js':'31757295fd6108023d87e3820f27c5491101e00438d2026417f54d61a3048429','ui/google.css':'e7824dd9d6e69f78c2c3a91a72a85c3b9efa0c27637acae408c4dd3df510343a'}
def main():
 p=Path(__file__).parent;b=ui.publisher();b.expected_files=lambda m:set(TARGETS) if m.get('scope')==ui.SCOPE else set();b.target_for=lambda r:TARGETS[r]
 m=json.loads((BASE/'css-manifest.json').read_text());m['unchangedRequired']=[r for r in m['unchangedRequired'] if r['path'] not in TARGETS.values()]
 m['files']=[dict(candidate=r,target=t,beforeSha256=BEFORE[r],sha256=hashlib.sha256((p/'candidate'/r).read_bytes()).hexdigest()) for r,t in TARGETS.items()]
 raw=json.dumps(m,indent=2).encode();sha=hashlib.sha256(raw).hexdigest()
 if sys.argv[1]=='inspect':(p/'manifest.json').write_bytes(raw);print(sha);print(b.inspect(m,p))
 elif sys.argv[1]=='apply':print(b.apply(m,p,sys.argv[2],raw,sys.argv[3]))
 elif sys.argv[1]=='rollback':print(b.rollback(Path(sys.argv[2]),sys.argv[3]))
 else:raise ValueError('unsupported action')
if __name__=='__main__':main()

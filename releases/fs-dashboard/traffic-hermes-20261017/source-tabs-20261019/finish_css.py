"""One-file responsive hotfix; preserve every other released artifact."""
from pathlib import Path
import hashlib,json,sys
import release_ui_finish as ui
def main():
 p=Path(__file__).parent;b=ui.publisher();rel='ui/google.css';target=ui.TARGETS[rel]
 b.expected_files=lambda m:{rel} if m.get('scope')==ui.SCOPE else set()
 b.target_for=lambda r:target if r==rel else None
 m=json.loads((p/'ui-manifest.json').read_text());old=next(r for r in m['files'] if r['candidate']==rel)
 protected=m['unchangedRequired']+[{'path':r['target'],'sha256':r['sha256']} for r in m['files'] if r['candidate']!=rel]
 candidate=p/'candidate'/rel
 m.update(files=[dict(candidate=rel,target=target,beforeSha256=old['sha256'],sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())],unchangedRequired=protected)
 raw=json.dumps(m,indent=2).encode();sha=hashlib.sha256(raw).hexdigest()
 if sys.argv[1]=='inspect':
  (p/'css-manifest.json').write_bytes(raw);print(sha);print(b.inspect(m,p))
 elif sys.argv[1]=='apply':print(b.apply(m,p,sys.argv[2],raw,sys.argv[3]))
 elif sys.argv[1]=='rollback':print(b.rollback(Path(sys.argv[2]),sys.argv[3]))
 else:raise ValueError('unsupported action')
if __name__=='__main__':main()

import hashlib, json, tempfile, unittest
from pathlib import Path
import publish as p

class Release(unittest.TestCase):
 def test_target_boundary(self):
  self.assertEqual(p.target('app/analytics/production-server.mjs'),'/opt/fs-campaign-dashboard/analytics/production-server.mjs')
  for path in ['app/../../etc/passwd','secret.pem','app/data.db','other/index.html']:
   with self.assertRaises(ValueError):p.target(path)
 def test_payload_change_and_rollback_binding(self):
  with tempfile.TemporaryDirectory() as tmp:
   stage=Path(tmp);rows=[]
   for name in list(p.SPECIAL)+['app/index.html']:
    file=stage/'candidate'/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('fixture')
    rows.append(dict(candidate=name,target=p.target(name),sha256=hashlib.sha256(file.read_bytes()).hexdigest(),beforeSha256=None))
   manifest=dict(schemaVersion=1,scope=p.SCOPE,targets={r['candidate']:r['target'] for r in rows},files=rows)
   self.assertEqual(len(p.validate(manifest,stage)),5)
   raw=json.dumps(manifest).encode();(stage/'approved-manifest.json').write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
   p.m.rollback_credentials(stage,dict(manifest=manifest,files=rows,approvedManifestSha256=sha),sha)
   (stage/'candidate/app/index.html').write_text('changed')
   with self.assertRaises(ValueError):p.validate(manifest,stage)
if __name__=='__main__':unittest.main()

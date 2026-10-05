from pathlib import Path
import tempfile,json,hashlib,unittest
from unittest.mock import patch
import release_gateway
from release_gateway import publish,Lock,Refused
sha=lambda b:hashlib.sha256(b).hexdigest()
HTML='FSBusinessSnapshots( currentExact() id="supplement-insights" profit-sales fs-dashboard-release '
class ReleaseTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.stage=self.root/'stage';self.stage.mkdir();self.live=self.root/'var/www/dashboard/index.html';self.live.parent.mkdir(parents=True);self.live.write_bytes(b'old');self.state=None
 def tearDown(self):self.temp.cleanup()
 def spec(self,version,name,body=HTML):
  data=body.encode();(self.stage/'dashboard.html').write_bytes(data)
  deps=[]
  for path in sorted(release_gateway.REQUIRED_DEPENDENCIES):
   dep=self.root/path.lstrip('/');dep.parent.mkdir(parents=True,exist_ok=True)
   if not dep.exists():dep.write_bytes(b'valid')
   deps.append({'path':path,'sha256':sha(dep.read_bytes())})
  m={'releaseId':name,'version':version,'source':'dashboard.html','sha256':sha(data),'expectedLiveSha256':sha(self.live.read_bytes()),'expectedReleaseId':self.state['releaseId'] if self.state else None,'dependencies':deps};p=self.stage/'manifest.json';p.write_text(json.dumps(m));return p
 def test_forward_old_concurrent_and_explicit_rollback(self):
  self.state=publish(self.root,self.spec(2,'new2'));p=self.spec(1,'old1')
  with self.assertRaisesRegex(Refused,'older'):publish(self.root,p)
  p=self.spec(3,'new3')
  with Lock(self.root/'var/lock/fs-dashboard-release.lock'):
   with self.assertRaisesRegex(Refused,'lock'):publish(self.root,p)
  p=self.spec(3,'new3',HTML+'v3');self.state=publish(self.root,p)
  p=self.spec(2,'new2');r=publish(self.root,p,True);self.assertTrue(r['intentionalRollback']);self.assertEqual(self.live.read_text(),HTML)
 def test_stale_baseline_and_unmanaged_writes(self):
  p=self.spec(2,'new2');self.live.write_text('changed')
  with self.assertRaisesRegex(Refused,'baseline'):publish(self.root,p)
  self.state=publish(self.root,self.spec(2,'new2'));self.live.write_text('unmanaged')
  with self.assertRaisesRegex(Refused,'unmanaged'):publish(self.root,self.spec(3,'new3'))
 def test_missing_contract_and_digest(self):
  with self.assertRaisesRegex(Refused,'contracts'):publish(self.root,self.spec(2,'legacy','old html'))
  p=self.spec(2,'new2');(self.stage/'dashboard.html').write_text('tampered')
  with self.assertRaisesRegex(Refused,'bytes'):publish(self.root,p)
 def test_unknown_rollback_refused(self):
  self.state=publish(self.root,self.spec(2,'new2'))
  with self.assertRaisesRegex(Refused,'recorded'):publish(self.root,self.spec(1,'unknown'),True)
 def test_external_write_between_check_and_replace(self):
  p=self.spec(2,'new2');original=release_gateway.atomic_json
  def intervening(path,obj):
   original(path,obj)
   if path.name=='pending.json':self.live.write_text('external-writer')
  with patch.object(release_gateway,'atomic_json',intervening):
   with self.assertRaisesRegex(Refused,'during staging'):publish(self.root,p)
  self.assertEqual(self.live.read_text(),'external-writer')
 def test_dependency_write_between_check_and_replace(self):
  dep=self.root/'var/www/dashboard/fs-home/transactions/snapshot-client.js';dep.parent.mkdir(parents=True);dep.write_text('valid')
  p=self.spec(2,'new2');original=release_gateway.atomic_json
  def intervening(path,obj):
   original(path,obj)
   if path.name=='pending.json':dep.write_text('changed-dependency')
  with patch.object(release_gateway,'atomic_json',intervening):
   with self.assertRaisesRegex(Refused,'dependency changed'):publish(self.root,p)
  self.assertEqual(self.live.read_bytes(),b'old')
if __name__=='__main__':unittest.main()

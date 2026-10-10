"""Synthetic CAS/rollback checks; Windows does not prove POSIX ownership/locks."""
import contextlib,copy,hashlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('live_publish',ROOT/'deploy/backend/release_navigation.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class PublisherTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.stage=ROOT/'deploy/backend'
  self.m=json.loads((self.stage/'approved-manifest.json').read_text());self.m['releaseReady']=True
  for row in self.m['files']:
   if row['beforeSha256']:
    p=r.rooted(self.root,row['target']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'BASE');row['beforeSha256']=r.digest(p)
  self.raw=json.dumps(self.m).encode();self.sha=hashlib.sha256(self.raw).hexdigest();self.calls=[]
  self.patches=[patch.object(r,'guards',lambda *a:None),patch.object(r,'retirement',lambda *a:None),patch.object(r,'restart_for',lambda m:self.calls.append(m['scope'])),patch.object(r,'live_lock',lambda *a:contextlib.nullcontext())]
  if os.name=='nt':self.patches.extend([patch.object(r,'locks',lambda *a:contextlib.nullcontext()),patch.object(r,'directory_sync',lambda *a:None)])
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def apply(self):return r.apply(self.m,self.stage,self.sha,self.raw,'nav-20261010T070000Z',self.root)
 def restored(self):
  for row in self.m['files']:self.assertEqual(row['beforeSha256'],r.digest(r.rooted(self.root,row['target'])))
 def test_apply_and_code_only_rollback(self):
  data=r.rooted(self.root,'/opt/auth-portal/data/keep.db');data.parent.mkdir(parents=True);data.write_bytes(b'KEEP')
  result=self.apply();self.assertEqual(8,result['staticFiles']);self.assertEqual([r.LIVE_SCOPE],self.calls)
  r.rollback(Path(result['backup']),self.sha,self.root);self.restored();self.assertEqual(b'KEEP',data.read_bytes())
 def test_not_ready(self):
  self.m['releaseReady']=False
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual([],self.calls)
 def test_target_drift(self):
  row=self.m['files'][0];r.rooted(self.root,row['target']).write_bytes(b'PEER')
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual(b'PEER',r.rooted(self.root,row['target']).read_bytes());self.assertEqual([],self.calls)
 def test_exact_scope(self):
  m=copy.deepcopy(self.m);m['files'].append(dict(candidate='extra.py',target='/opt/extra.py',sha256='0'*64,beforeSha256=None))
  with self.assertRaises(ValueError):r.validate(m,self.stage)
 def test_wrong_baseline_presence(self):
  m=copy.deepcopy(self.m);m['files'][0]['beforeSha256']=None
  with self.assertRaises(ValueError):r.validate(m,self.stage)
 def test_health_failure_restores_all(self):
  calls=[]
  def restart(m):
   calls.append(m['scope'])
   if len(calls)==1:raise ValueError('HEALTH')
  with patch.object(r,'restart_for',restart):
   with self.assertRaises(ValueError):self.apply()
  self.restored();self.assertEqual(2,len(calls))
if __name__=='__main__':unittest.main(verbosity=2)

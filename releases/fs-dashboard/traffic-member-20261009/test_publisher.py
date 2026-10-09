import contextlib,copy,hashlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('traffic_publish',ROOT/'deploy/release_navigation.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class PublisherTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.stage=ROOT/'deploy'
  self.manifest=json.loads((self.stage/'approved-manifest.json').read_text())
  for row in self.manifest['files']:
   if row['beforeSha256']:
    p=r.rooted(self.root,row['target']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'SYNTHETIC_BASELINE');row['beforeSha256']=r.digest(p)
  self.raw=json.dumps(self.manifest).encode();self.sha=hashlib.sha256(self.raw).hexdigest();self.calls=[]
  self.patches=[patch.object(r,'guards',lambda *args:None),patch.object(r,'retirement',lambda *args:None),patch.object(r,'restart_for',lambda m:self.calls.append(m['scope']))]
  if os.name=='nt':self.patches.extend([patch.object(r,'locks',lambda *a:contextlib.nullcontext()),patch.object(r,'directory_sync',lambda *a:None)])
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def apply(self):return r.apply(self.manifest,self.stage,self.sha,self.raw,'nav-20261009T100000Z',self.root)
 def test_exact_apply_and_code_only_rollback(self):
  data=r.rooted(self.root,'/opt/auth-portal/data/registration-approval/registration.sqlite3');data.parent.mkdir(parents=True);data.write_bytes(b'KEEP_DATA')
  result=self.apply();self.assertEqual(9,result['staticFiles']);self.assertEqual(['fs-traffic-member-20261009'],self.calls)
  r.rollback(Path(result['backup']),self.sha,self.root);self.assertEqual(b'KEEP_DATA',data.read_bytes())
  for row in self.manifest['files']:self.assertEqual(row['beforeSha256'],r.digest(r.rooted(self.root,row['target'])))
 def test_not_ready(self):
  self.manifest['releaseReady']=False
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual([],self.calls)
 def test_target_drift(self):
  row=next(x for x in self.manifest['files'] if x['beforeSha256']);r.rooted(self.root,row['target']).write_bytes(b'OTHER_TASK')
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual(b'OTHER_TASK',r.rooted(self.root,row['target']).read_bytes());self.assertEqual([],self.calls)
 def test_extra_target_refused(self):
  m=copy.deepcopy(self.manifest);m['files'].append(dict(candidate='other.py',target='/opt/other.py',sha256='0'*64,beforeSha256=None))
  with self.assertRaises(ValueError):r.validate(m,self.stage)
 def test_session_image_guard(self):
  m=copy.deepcopy(self.manifest);m['sessionBaseImage']='unknown'
  with self.assertRaises(ValueError):r.validate(m,self.stage)
 def test_activation_failure_restores_code(self):
  attempts=[]
  def restart(m):
   attempts.append(m['scope'])
   if len(attempts)==1:raise ValueError('SYNTHETIC_HEALTH_FAILURE')
  with patch.object(r,'restart_for',restart):
   with self.assertRaises(ValueError):self.apply()
  self.assertEqual(2,len(attempts))
  for row in self.manifest['files']:self.assertEqual(row['beforeSha256'],r.digest(r.rooted(self.root,row['target'])))
if __name__=='__main__':unittest.main(verbosity=2)

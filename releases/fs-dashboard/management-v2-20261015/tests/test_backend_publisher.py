import unittest,tempfile,importlib.util,json,contextlib,shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];STAGE=ROOT/'release/management-v2-07ac5252c4a5'
spec=importlib.util.spec_from_file_location('mg_backend_pub',STAGE/'publish_backend.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class Fence:
 def __init__(self,root):self.modified=False;self.confirmed=False;self.stopped=False;self.closed=False
 def stop_then_unlock_database(self):self.stopped=True
 def close(self):self.closed=True
class BackendPublisher(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'root';self.root.mkdir();self.stage=Path(self.tmp.name)/'owned-stage';shutil.copytree(STAGE,self.stage,ignore=shutil.ignore_patterns('__pycache__'));self.stage.chmod(0o755)
  for f in self.stage.rglob('*'):f.chmod(0o755 if f.is_dir() else 0o644)
  self.raw=(STAGE/'contract.json').read_bytes();self.m=json.loads(self.raw)
  for r in self.m['files']:
   if r['beforeSha256']:self.atomic(p.at(self.root,r['target']),(ROOT/'release/management-v2-74a2c7d67093'/r['candidate']).read_bytes(),0o644)
  self.fences=[]
  def make(root):f=Fence(root);self.fences.append(f);return f
  self.fake=SimpleNamespace(atomic=self.atomic,locks=lambda root:contextlib.nullcontext(),directory_sync=lambda path:None,HermesAdmissionFence=make)
  for name,value in [('base',self.fake),('provider_fence',contextlib.nullcontext()),('guards',None)]:
   patcher=patch.object(p,name,return_value=value);patcher.start();self.addCleanup(patcher.stop)
 def atomic(self,path,data,mode):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(mode)
 def test_success_holds_fence_and_reads_files(self):
  with patch.object(p,'runtime',return_value='active'):out=p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  self.assertFalse(out['modelStarted']);self.assertTrue(self.fences[0].stopped);self.assertTrue(self.fences[0].confirmed);self.assertTrue(self.fences[0].closed)
  for r in self.m['files']:self.assertEqual(p.digest(p.at(self.root,r['target'])),r['sha256'])
  self.assertFalse(p.pending(self.root).exists())
 def test_start_failure_rolls_back_then_restarts_original(self):
  failed=[]
  def runtime(args):
   if args==['systemctl','start','fs-business-range.service'] and not failed:failed.append(True);raise RuntimeError('startup')
   return 'active'
  with patch.object(p,'runtime',side_effect=runtime):
   with self.assertRaisesRegex(RuntimeError,'startup'):p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  for r in self.m['files']:
   self.assertEqual(p.digest(p.at(self.root,r['target'])),r['beforeSha256'] or r['sha256'])
  self.assertTrue(self.fences[0].confirmed);self.assertFalse(p.pending(self.root).exists())
 def test_peer_change_refuses_stop(self):
  target=p.at(self.root,p.TARGETS['controller.py']);target.write_text('peer')
  with self.assertRaisesRegex(ValueError,'before_sha_drift'):p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  self.assertFalse(self.fences[0].stopped);self.assertEqual(target.read_text(),'peer')
 def test_explicit_rollback(self):
  with patch.object(p,'runtime',return_value='active'):
   out=p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
   r=p.rollback(Path(out['backup']),p.sha(self.raw),self.root)
  self.assertEqual(r['status'],'rolled_back_new_helpers_retained')
  self.assertEqual(p.digest(p.at(self.root,p.TARGETS['controller.py'])),next(x['beforeSha256'] for x in self.m['files'] if x['candidate']=='controller.py'))
if __name__=='__main__':unittest.main()

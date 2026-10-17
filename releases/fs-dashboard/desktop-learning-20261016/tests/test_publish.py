import unittest,tempfile,importlib.util,contextlib,json,shutil,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];STAGE=ROOT/'desktop-learning-8641c3d1a740'
s=importlib.util.spec_from_file_location('pub',STAGE/'publish_backend.py');p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
class Publication(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'root';self.root.mkdir();self.stage=Path(self.tmp.name)/'stage';shutil.copytree(STAGE,self.stage,ignore=shutil.ignore_patterns('__pycache__'))
  self.stage.chmod(0o755)
  for f in self.stage.rglob('*'):f.chmod(0o755 if f.is_dir() else 0o644)
  self.m=json.loads((self.stage/'contract.json').read_text());self.old=b'# synthetic old module\n';self.m['files'][0]['beforeSha256']=p.sha(self.old);self.raw=json.dumps(self.m).encode();(self.stage/'contract.json').write_bytes(self.raw)
  old=p.HERE;p.HERE=self.stage;self.addCleanup(lambda:setattr(p,'HERE',old));self.atomic(p.at(self.root,p.TARGETS['business_context.py']),self.old,0o644)
  self.fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=lambda:None,close=lambda:None)
  self.base=SimpleNamespace(atomic=self.atomic,locks=lambda root:contextlib.nullcontext(),directory_sync=lambda path:None,HermesAdmissionFence=lambda root:self.fence)
  for name,value in [('base',self.base),('provider_fence',contextlib.nullcontext()),('guards',None)]:
   z=patch.object(p,name,return_value=value);z.start();self.addCleanup(z.stop)
 def atomic(self,path,data,mode):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(mode)
 def test_one_module_no_desktop_or_research_restart(self):
  with patch.object(p,'runtime',return_value='active') as r:out=p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  self.assertEqual(len(self.m['files']),1);self.assertFalse(out['modelStarted']);self.assertTrue(self.fence.confirmed)
  self.assertFalse(any('fs-hermes' in str(c) for c in r.call_args_list))
 def test_failure_restores_module(self):
  failed=[]
  def run(args):
   if args==['systemctl','start','fs-business-range.service'] and not failed:failed.append(True);raise RuntimeError('startup')
   return 'active'
  with patch.object(p,'runtime',side_effect=run):
   with self.assertRaises(RuntimeError):p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  self.assertEqual(p.at(self.root,p.TARGETS['business_context.py']).read_bytes(),self.old)
if __name__=='__main__':unittest.main()

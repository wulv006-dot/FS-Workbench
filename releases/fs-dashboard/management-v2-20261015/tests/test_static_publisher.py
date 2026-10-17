import unittest,tempfile,importlib.util,json,contextlib,os,shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'release/static-workspace-native-20261006-66ec73f42a1d'
spec=importlib.util.spec_from_file_location('mg_static',STAGE/'publish_static.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class Publisher(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'root';self.root.mkdir();self.stage=Path(self.tmp.name)/'fixture-stage';shutil.copytree(STAGE,self.stage,ignore=shutil.ignore_patterns('__pycache__'))
  # Synthetic runtime data only. Production target values never enter CI or Git.
  sample=b'{"fixture":"synthetic operational target, no business data"}\n'
  (self.stage/'assets/targets.json').write_bytes(sample);self.m=json.loads((STAGE/'contract.json').read_bytes())
  next(r for r in self.m['files'] if r['candidate']=='assets/targets.json')['sha256']=p.sha(sample)
  self.raw=json.dumps(self.m).encode();(self.stage/'contract.json').write_bytes(self.raw)
  original=p.HERE;p.HERE=self.stage;self.addCleanup(lambda:setattr(p,'HERE',original))
  base=ROOT/'release/static-workspace-native-20261006-0736519733a2/candidate'
  sources={p.FRAGMENT:base/'formal.conf',p.HUB:base/'hubnav.js','/opt/fs-hermes-fc/controller.py':ROOT/'release/management-v2-83764e001cd3/controller.py','/var/www/dashboard/fs-home/index.html':ROOT/'baseline/ui/home.html'}
  for target,source in sources.items():self.atomic(p.at(self.root,target),source.read_bytes(),0o644)
  self.fake=SimpleNamespace(atomic=self.atomic,locks=lambda root:contextlib.nullcontext(),directory_sync=lambda path:None)
 def atomic(self,path,data,mode):
  path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(mode)
 def test_inspect_and_success_readback(self):
  self.assertEqual(p.inspect(self.m,self.stage,self.root)['writes'],0)
  with patch.object(p,'base',return_value=self.fake),patch.object(p,'runtime') as runtime:
   out=p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  self.assertEqual(out['status'],'applied_awaiting_browser_acceptance');self.assertEqual(runtime.call_count,2)
  for r in self.m['files']:self.assertEqual(p.digest(p.at(self.root,r['target'])),r['sha256'])
  self.assertFalse(p.pending(self.root).exists())
 def test_nginx_failure_restores_original_mutables(self):
  with patch.object(p,'base',return_value=self.fake),patch.object(p,'runtime',side_effect=RuntimeError('nginx test failed')):
   with self.assertRaises(RuntimeError):p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  for r in self.m['files']:
   self.assertEqual(p.digest(p.at(self.root,r['target'])),r['beforeSha256'] if r['target'] in (p.FRAGMENT,p.HUB) else r['sha256'])
  self.assertFalse(p.pending(self.root).exists())
 def test_peer_change_stops_without_writes(self):
  p.at(self.root,p.HUB).write_text('peer version')
  with patch.object(p,'base',return_value=self.fake):
   with self.assertRaisesRegex(ValueError,'target_baseline'):p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
  self.assertEqual(p.at(self.root,p.HUB).read_text(),'peer version');self.assertFalse(p.pending(self.root).exists())
 def test_symlink_and_manifest_tamper_denied(self):
  target=p.at(self.root,p.HUB);target.rename(target.with_name('saved'));target.symlink_to(target.with_name('saved'))
  with self.assertRaisesRegex(ValueError,'symlink'):p.inspect(self.m,self.stage,self.root)
  m=dict(self.m,phase='production')
  with self.assertRaisesRegex(ValueError,'contract_changed'):p.validate(m,self.stage)
 def test_replay_not_allowed(self):
  with patch.object(p,'base',return_value=self.fake),patch.object(p,'runtime'):
   p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
   with self.assertRaises(ValueError):p.apply(self.m,self.stage,self.raw,p.sha(self.raw),self.root)
if __name__=='__main__':unittest.main()

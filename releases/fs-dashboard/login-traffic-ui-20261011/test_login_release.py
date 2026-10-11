import contextlib,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('login_publisher',Path(__file__).with_name('release_navigation.py'));r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class LoginRelease(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.stage=self.root/'stage';self.stage.mkdir()
  self.m={'schemaVersion':1,'scope':r.LOGIN_UI_SCOPE,'releaseReady':True,'files':[],'unchangedRequired':[{'path':'/var/www/dashboard/index.html','sha256':'a'*64}]}
  for rel,target in r.LOGIN_UI_TARGETS.items():
   before=('old:'+rel).encode();after=('new:'+rel).encode();p=r.rooted(self.root,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(before);src=self.stage/'candidate'/rel;src.parent.mkdir(parents=True,exist_ok=True);src.write_bytes(after)
   self.m['files'].append({'candidate':rel,'target':target,'beforeSha256':hashlib.sha256(before).hexdigest(),'sha256':hashlib.sha256(after).hexdigest()})
  self.raw=json.dumps(self.m).encode();self.sha=hashlib.sha256(self.raw).hexdigest()
  for name,value in [('guards',lambda *a:None),('retirement',lambda *a:None),('locks',lambda *a:contextlib.nullcontext()),('directory_sync',lambda *a:None)]:
   p=patch.object(r,name,value);p.start();self.addCleanup(p.stop)
 def apply(self):return r.apply(self.m,self.stage,self.sha,self.raw,'nav-20261011T010101Z',self.root)
 def test_exact_ui_apply_and_rollback_no_service_or_database(self):
  with patch.object(r,'restart_for') as restart:
   result=self.apply();self.assertEqual(result['staticFiles'],3);restart.assert_not_called()
   backup=Path(result['backup']);journal=json.loads((backup/'journal.json').read_text());r.rollback_journal(backup,journal,self.root)
  for row in self.m['files']:self.assertEqual(r.digest(r.rooted(self.root,row['target'])),row['beforeSha256'])
  self.assertFalse(any(self.root.rglob('*.sqlite3')))
 def test_drift_refuses_before_backup(self):
  r.rooted(self.root,self.m['files'][0]['target']).write_bytes(b'peer')
  with self.assertRaises(ValueError):self.apply()
  self.assertFalse((self.root/'var/backups').exists())
 def test_auth_runtime_cannot_enter_ui_scope(self):
  self.m['files'][0]['target']='/opt/auth-portal/auth_portal.py'
  with self.assertRaises(ValueError):r.validate(self.m,self.stage)
 def test_existing_baseline_required(self):
  self.m['files'][0]['beforeSha256']=None
  with self.assertRaises(ValueError):r.validate(self.m,self.stage)
 def test_candidate_tamper_refuses(self):
  (self.stage/'candidate'/self.m['files'][0]['candidate']).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.apply()
 def test_exact_production_manifest_has_no_target_protection_overlap(self):
  m=json.loads(Path(__file__).with_name('approved-manifest.json').read_text(encoding='utf-8'))
  self.assertFalse({r['target'] for r in m['files']} & {r['path'] for r in m['unchangedRequired']})
if __name__=='__main__':unittest.main()

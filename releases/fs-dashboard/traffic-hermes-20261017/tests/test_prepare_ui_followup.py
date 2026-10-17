import importlib.util,json,tempfile,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'prepare_ui_followup.py';spec=importlib.util.spec_from_file_location('ui_followup',P);ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
REPO=P.parents[3]
class Followup(unittest.TestCase):
 def fixture(self,folder):
  previous=folder/'previous';(previous/'assets').mkdir(parents=True);(previous/'candidate').mkdir();rid='workspace-native-20261006-9468e1d0efec';assets=[];blocks=[]
  for n in ui.NAMES:
   raw=(ui.URL+rid+'/shell.js').encode();(previous/'assets'/n).write_bytes(raw);assets.append({'candidate':'assets/'+n,'target':ui.STATIC+rid+'/'+n,'url':ui.URL+rid+'/'+n,'beforeSha256':None,'sha256':ui.sha(raw)})
   blocks.append('location = '+ui.URL+rid+'/'+n+' {\n auth_request /__nav_formal_native_session;\n disable_symlinks on;\n alias '+ui.STATIC+rid+'/'+n+';\n}')
  blocks.append('location = /dashboard/analytics/index.html {\n alias '+ui.STATIC+rid+'/index.html;\n}');blocks.append('location = /historical {\n return 204;\n}');config=('\n\n'.join(blocks)+'\n').encode();(previous/'candidate/formal.conf').write_bytes(config);home=(previous/'assets/home.html').read_bytes();(previous/'candidate/home.html').write_bytes(home)
  targets=[{'candidate':'candidate/formal.conf','target':ui.CONFIG,'beforeSha256':'0'*64,'sha256':ui.sha(config)},{'candidate':'candidate/home.html','target':ui.HOME,'beforeSha256':'0'*64,'sha256':ui.sha(home)}]
  m={'releaseId':rid,'releaseReady':False,'immutableAssets':assets,'targets':targets,'unchangedRequired':[{'path':'/protected/'+str(i),'sha256':'a'*64} for i in range(17)],'requiredBusinessLedger':{'releaseId':'ledger'}};raw=(json.dumps(m)+'\n').encode();(previous/'release-contract.json').write_bytes(raw);(previous/'release-manifest.json').write_bytes(raw);(previous/'release_workspace.py').write_text("CONTRACT_SHA = '"+ui.sha(raw)+"'")
  for n in ('release_navigation.py','release_navigation_base.py'):(previous/n).write_bytes(b'fixed test bridge')
  receipt={'releaseId':rid,'status':'applied-awaiting-real-desktop-URL-QA','assets':5,'entry_targets':2};formal=folder/'formal.conf';formal.write_bytes(config);return previous,receipt,formal,m,blocks
 def test_preserves_current_routes_and_protections(self):
  with tempfile.TemporaryDirectory() as f:
   folder=Path(f);previous,receipt,formal,old,blocks=self.fixture(folder);out=folder/'next';result=ui.prepare(REPO,previous,receipt,formal,out);m=json.loads((out/'release-manifest.json').read_text());config=(out/'candidate/formal.conf').read_text()
   self.assertEqual(m['unchangedRequired'],old['unchangedRequired']);self.assertEqual(m['requiredBusinessLedger'],old['requiredBusinessLedger']);self.assertEqual(len(m['immutableAssets']),5);self.assertEqual(len(m['targets']),2)
   for block in blocks:
    if '/dashboard/analytics/index.html {' not in block:self.assertIn(block,config)
   self.assertEqual(config.count('location = '),len(blocks)+5);self.assertEqual(m['targets'][0]['beforeSha256'],old['targets'][0]['sha256']);self.assertFalse(result['releaseReady'])
 def test_old_formal_and_wrong_receipt_are_rejected(self):
  with tempfile.TemporaryDirectory() as f:
   folder=Path(f);previous,receipt,formal,old,blocks=self.fixture(folder);receipt['releaseId']='wrong'
   with self.assertRaisesRegex(ValueError,'previous_not_verified_applied'):ui.prepare(REPO,previous,receipt,formal,folder/'next')
   receipt['releaseId']=old['releaseId'];formal.write_bytes(b'old pre-release formal')
   with self.assertRaisesRegex(ValueError,'current_formal_drift'):ui.prepare(REPO,previous,receipt,formal,folder/'next')
if __name__=='__main__':unittest.main()

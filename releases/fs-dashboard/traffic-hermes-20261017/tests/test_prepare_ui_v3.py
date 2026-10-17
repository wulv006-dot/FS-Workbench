import importlib.util,json,re,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parents[1]/'prepare_ui_v3.py';sys.path.insert(0,str(P.parent));spec=importlib.util.spec_from_file_location('ui_v3',P);ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
REPO=P.parents[3]
class V3Preparation(unittest.TestCase):
 def fixture(self,folder):
  previous=folder/'previous';(previous/'assets').mkdir(parents=True);(previous/'candidate').mkdir();rid='workspace-native-20261006-e0654eaced60';assets=[];blocks=[]
  for n in ui.prior.NAMES:
   raw=(ui.prior.URL+rid+'/shell.js').encode()
   if n=='shell.js':raw+=(";new URL(state.mode+'.css',new URL('"+ui.prior.URL+ui.THEME+"/',location.origin))").encode()
   (previous/'assets'/n).write_bytes(raw);assets.append({'candidate':'assets/'+n,'target':ui.prior.STATIC+rid+'/'+n,'url':ui.prior.URL+rid+'/'+n,'beforeSha256':None,'sha256':ui.sha(raw)})
   blocks.append('location = '+ui.prior.URL+rid+'/'+n+' {\n auth_request /__nav_formal_native_session;\n disable_symlinks on;\n alias '+ui.prior.STATIC+rid+'/'+n+';\n}')
  blocks.append('location = '+ui.prior.URL+ui.THEME+'/google.css {\n auth_request /__nav_formal_native_session;\n disable_symlinks on;\n alias '+ui.CSS_TARGET+';\n}')
  blocks.append('location = /dashboard/analytics/index.html {\n alias '+ui.prior.STATIC+rid+'/index.html;\n}');config=('\n\n'.join(blocks)+'\n').encode();(previous/'candidate/formal.conf').write_bytes(config);home=(previous/'assets/home.html').read_bytes();(previous/'candidate/home.html').write_bytes(home)
  targets=[{'candidate':'candidate/formal.conf','target':ui.prior.CONFIG,'beforeSha256':'0'*64,'sha256':ui.sha(config)},{'candidate':'candidate/home.html','target':ui.prior.HOME,'beforeSha256':'0'*64,'sha256':ui.sha(home)}];protected=[{'path':ui.CSS_TARGET,'sha256':'b'*64}]
  m={'releaseId':rid,'releaseReady':False,'immutableAssets':assets,'targets':targets,'unchangedRequired':protected,'requiredBusinessLedger':{'releaseId':'ledger'}};raw=(json.dumps(m)+'\n').encode();(previous/'release-contract.json').write_bytes(raw);(previous/'release-manifest.json').write_bytes(raw)
  publisher=(REPO/'releases/fs-dashboard/menu-cache-20261015/native/release_workspace.py').read_text(encoding='utf8');publisher=re.sub(r'^NAMES = .*$', 'NAMES = '+repr(set(ui.prior.NAMES)),publisher,flags=re.M);publisher=re.sub(r'^MUTABLE = .*$', 'MUTABLE = '+repr((ui.prior.CONFIG,ui.prior.HOME)),publisher,flags=re.M).replace("len(m['targets'])!=4","len(m['targets'])!=2");publisher=re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+ui.sha(raw)+"'",publisher);(previous/'release_workspace.py').write_text(publisher,encoding='utf8')
  bridge=(REPO/'ui-system/publishers/native_bridge.py').read_text(encoding='utf8').replace("Path(__file__).resolve().parents[1] / 'native/release_navigation_base.py'","Path(__file__).resolve().with_name('release_navigation_base.py')");(previous/'release_navigation.py').write_text(bridge,encoding='utf8');(previous/'release_navigation_base.py').write_bytes((REPO/'releases/fs-dashboard/menu-cache-20261015/native/release_navigation.py').read_bytes())
  receipt={'releaseId':rid,'status':'applied-awaiting-real-desktop-URL-QA','assets':5,'entry_targets':2};formal=folder/'formal.conf';formal.write_bytes(config);baseline={'files':[{'path':r['target'],'sha256':r['sha256'],'is_symlink':False}for r in assets+targets]+[{'path':r['path'],'sha256':r['sha256'],'is_symlink':False}for r in protected]};return previous,receipt,formal,baseline,blocks
 def test_six_exact_assets_preserve_old_routes_shared_css_and_target_scope(self):
  with tempfile.TemporaryDirectory() as f:
   folder=Path(f);previous,receipt,formal,baseline,blocks=self.fixture(folder);out=folder/'next';plan=ui.prepare(REPO,previous,receipt,formal,baseline,out);m=json.loads((out/'release-manifest.json').read_text(encoding='utf8'));self.assertEqual(plan['assets'],6);self.assertFalse(plan['sharedCssWrites']);self.assertEqual({r['candidate'] for r in m['immutableAssets']},{'assets/'+n for n in ui.NAMES});self.assertEqual(len(m['targets']),2)
   conf=(out/'candidate/formal.conf').read_text(encoding='utf8')
   for block in blocks:
    if '/dashboard/analytics/index.html {' not in block:self.assertIn(block,conf)
   self.assertEqual(conf.count('location = '),len(blocks)+6);self.assertIn("state.mode==='google'?base",(out/'assets/shell.js').read_text(encoding='utf8'))
   with patch.dict(sys.modules),patch.object(sys,'path',[str(out),*sys.path]):
    sys.modules.pop('release_navigation',None);spec=importlib.util.spec_from_file_location('v3_publisher',out/'release_workspace.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub);self.assertEqual(len(pub.validate(m,None)),8);self.assertEqual(pub.NAMES,set(ui.NAMES));bad=json.loads(json.dumps(m));bad['immutableAssets'].append(dict(bad['immutableAssets'][0]))
    with self.assertRaises(ValueError):pub.validate(bad,None)
 def test_runtime_sha_drift_and_shared_style_drift_are_rejected(self):
  with tempfile.TemporaryDirectory() as f:
   folder=Path(f);previous,receipt,formal,baseline,blocks=self.fixture(folder);baseline['files'][0]['sha256']='0'*64
   with self.assertRaisesRegex(ValueError,'current_runtime_drift'):ui.prepare(REPO,previous,receipt,formal,baseline,folder/'next')
   baseline['files'][0]['sha256']=json.loads((previous/'release-manifest.json').read_text(encoding='utf8'))['immutableAssets'][0]['sha256'];baseline['files'][-1]['sha256']='0'*64
   with self.assertRaisesRegex(ValueError,'current_runtime_drift'):ui.prepare(REPO,previous,receipt,formal,baseline,folder/'next')
if __name__=='__main__':unittest.main()

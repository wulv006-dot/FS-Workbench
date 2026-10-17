import importlib.util,json,tempfile,unittest,sys,ast
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parents[1]/'prepare_ui.py'
spec=importlib.util.spec_from_file_location('prepare_traffic_ui',P);ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
REPO=P.parents[3]

def baseline():
    files=[{'path':p,'sha256':h,'is_symlink':False} for p,h in ui.EXPECTED.items()]
    routes=[]
    for name in ('shell.js','google.js','index.html','home.html'):
        rid='workspace-native-20261006-fd4cfd0a70aa' if name=='google.js' else ui.ACTIVE
        routes.append('location = '+ui.URL+rid+'/'+name+' {\n    auth_request /__nav_formal_native_session;\n    disable_symlinks on;\n    alias '+ui.STATIC+rid+'/'+name+';\n}')
    return {'files':files,'routes':routes}

class PrepareUI(unittest.TestCase):
    def test_assets_are_bounded_and_dependencies_stay_pinned(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'candidate';plan=ui.prepare(REPO,baseline(),out)
            self.assertEqual({p.name for p in (out/'assets').iterdir()},set(ui.NAMES))
            self.assertFalse(plan['releaseReady']);self.assertFalse((out/'release-manifest.json').exists())
            shell=(out/'assets/shell.js').read_text(encoding='utf8')
            self.assertIn(ui.URL+ui.THEME+'/',shell);self.assertIn("new URL('navigation.json',logicBase)",shell)
            self.assertNotIn("new URL(state.mode+'.css',base)",shell)
            self.assertEqual((out/'exact-route-additions.conf').read_text().count('location = '),5)
            for name in ('index.html','home.html'):self.assertIn(plan['releaseId']+'/shell.js',(out/'assets'/name).read_text(encoding='utf8'))
    def test_changed_active_baseline_and_config_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            b=baseline();b['files'][0]['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'active_baseline_changed'):ui.prepare(REPO,b,Path(folder)/'out')
            config=Path(folder)/'formal.conf';config.write_bytes(b'old historical config')
            with self.assertRaisesRegex(ValueError,'active_formal_changed'):ui.prepare(REPO,baseline(),Path(folder)/'out',config)
    def test_reuse_and_inside_repo_output_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'output_exists'):ui.prepare(REPO,baseline(),folder)
        with self.assertRaisesRegex(ValueError,'output_must_be_outside_repository'):ui.prepare(REPO,baseline(),REPO/'candidate-output')
    def test_frozen_publisher_scope_guards_and_payload_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            b=baseline();config='\n'.join(b['routes'])+'\nlocation = /dashboard/analytics/index.html {\n    alias '+ui.STATIC+ui.ACTIVE+'/index.html;\n}\n'
            formal=Path(folder)/'formal.conf';formal.write_bytes(config.encode());expected=dict(ui.EXPECTED);expected[ui.CONFIG]=ui.sha(config.encode());b['files'][0]['sha256']=expected[ui.CONFIG]
            ledger={'releaseId':'test','version':1,'sha256':'a'*64,'publishedAt':'2026-10-17'};text=json.dumps(ledger)
            deps={'files':[{'path':'/var/lib/fs-dashboard-release/current.json','sha256':ui.sha(text.encode()),'text':text},{'path':'/var/www/dashboard/index.html','sha256':'a'*64}]+[{'path':ui.STATIC+ui.THEME+'/'+n,'sha256':'b'*64} for n in ('ui/fs-tokens.css','ui/fs-ui.css','ui/fs-theme.js','ui/native-alias.css','workspace.css','business.css','google.css')]}
            out=Path(folder)/'out'
            with patch.dict(ui.EXPECTED,expected,clear=True):plan=ui.prepare(REPO,b,out,formal,deps)
            self.assertEqual(plan['missing'],[]);manifest=json.loads((out/'release-manifest.json').read_text());self.assertFalse(manifest['releaseReady']);self.assertEqual(len(manifest['targets']),2)
            new=(out/'candidate/formal.conf').read_text()
            for block in b['routes']:self.assertIn(block,new)
            original=ast.parse((REPO/'releases/fs-dashboard/menu-cache-20261015/native/release_workspace.py').read_text());generated=ast.parse((out/'release_workspace.py').read_text())
            for name in ('inspect','guards','apply','rollback','restore','assert_current'):
                self.assertEqual(ast.dump(next(n for n in original.body if isinstance(n,ast.FunctionDef) and n.name==name)),ast.dump(next(n for n in generated.body if isinstance(n,ast.FunctionDef) and n.name==name)))
            with patch.dict(sys.modules),patch.object(sys,'path',[str(out),*sys.path]):
                sys.modules.pop('release_navigation',None);spec=importlib.util.spec_from_file_location('bounded_ui_publisher',out/'release_workspace.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
                self.assertEqual(len(pub.validate(manifest,None)),7);self.assertEqual(pub.NAMES,set(ui.NAMES));self.assertEqual(set(pub.MUTABLE),{ui.CONFIG,'/var/www/dashboard/fs-home/index.html'})
                bad=json.loads(json.dumps(manifest));bad['targets'][0]['target']='/etc/passwd'
                with self.assertRaisesRegex(ValueError,'Exact frozen release contract'):pub.validate(bad,None)
                with patch.object(pub,'trusted',lambda *args:None):
                    self.assertEqual(len(pub.validate(manifest,out)),7);(out/'assets/business.js').write_bytes(b'changed')
                    with self.assertRaisesRegex(ValueError,'Staged bytes drift'):pub.validate(manifest,out)
                (out/'release-contract.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'Frozen release contract SHA'):pub.validate(manifest,None)
if __name__=='__main__':unittest.main()

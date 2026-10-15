"""Exact release scope and asset preservation; no server calls."""
import copy,hashlib,importlib.util,json,os,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'native'))
import release_workspace as native
spec=importlib.util.spec_from_file_location('ui_publisher',HERE/'ui/release_navigation.py')
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
class Recovery(unittest.TestCase):
    def test_native_contract(self):
        m=json.loads((HERE/'native/release-manifest.json').read_text('utf-8'))
        self.assertEqual(len(native.validate(m,HERE/'native' if os.name=='posix' else None)),143)
        for row in m['immutableAssets']+m['targets']:
            self.assertEqual(hashlib.sha256((HERE/'native'/row['candidate']).read_bytes()).hexdigest(),row['sha256'])
    def test_ui_scope(self):
        m=json.loads((HERE/'ui/candidate-manifest.json').read_text('utf-8'))
        self.assertEqual(len(ui.validate(m,HERE/'ui')),5)
        bad=copy.deepcopy(m);bad['files'][0]['target']='/opt/g2gfollow/pricing.py'
        with self.assertRaises(ValueError):ui.validate(bad,HERE/'ui')
        bad=copy.deepcopy(m);bad['files'][0]['beforeSha256']=None
        with self.assertRaises(ValueError):ui.validate(bad,HERE/'ui')
    def test_only_registry_changes_native_behavior(self):
        live=json.loads((HERE/'baseline-fixture.json').read_text('utf-8'))
        new=json.loads((HERE/'build-summary.json').read_text('utf-8'))['version']
        for name,row in live['assets'].items():
            if name=='navigation.json':continue
            b=(HERE/'native/assets'/name).read_bytes().replace(new.encode(),live['version'].encode())
            self.assertEqual(hashlib.sha256(b).hexdigest(),row['sha256'],name)
    def test_old_destinations_preserved(self):
        old=json.loads((HERE/'baseline-fixture.json').read_text('utf-8'))
        new=json.loads((HERE/'ui/candidate/fs-home/navigation.json').read_text('utf-8'))
        old=json.loads(json.dumps(old,ensure_ascii=False).replace('LV决策大脑','Hermes智体'))
        self.assertEqual({t['id']:t for t in old['oldTools']},{t['id']:t for t in new['tools'] if t['id'] in {t['id'] for t in old['oldTools']}})
        self.assertEqual(next(s['title'] for s in new['sections'] if s['id']=='brain'),'Hermes智体')
        self.assertNotIn('LV决策大脑',(HERE/'ui/candidate/brain/index.html').read_text('utf-8'))
if __name__=='__main__':unittest.main()

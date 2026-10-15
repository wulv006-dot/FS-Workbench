"""Check the exact release boundary and unchanged backend policy."""
import hashlib,importlib.util,json,os,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

class Release(unittest.TestCase):
    def test_native_payload(self):
        sys.path.insert(0,str(HERE/'native'))
        import release_workspace as publisher
        manifest=json.loads((HERE/'native/release-manifest.json').read_text('utf-8'))
        rows=publisher.validate(manifest,HERE/'native' if os.name=='posix' else None)
        self.assertEqual(len(rows),143)
        for row in rows:self.assertEqual(sha(HERE/'native'/row['candidate']),row['sha256'])
        self.assertEqual({r['target'] for r in manifest['targets']},set(publisher.MUTABLE))

    def test_ui_payload(self):
        spec=importlib.util.spec_from_file_location('ui_publisher',HERE/'ui/release_navigation.py')
        publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
        manifest=json.loads((HERE/'ui/candidate-manifest.json').read_text('utf-8'))
        self.assertEqual(len(publisher.validate(manifest,HERE/'ui')),2)
        self.assertEqual({r['target'] for r in manifest['files']},{'/var/www/hub/hubnav.js','/opt/auth-portal/registration-runtime/20261007-ca6258ad/web/app.js'})
        self.assertFalse(manifest.get('runtimeRequired'))

    def test_source_and_guards(self):
        native=json.loads((HERE/'native/release-manifest.json').read_text('utf-8'))
        protected={r['path']:r['sha256'] for r in native['unchangedRequired']}
        for path in ('runtime.py','module_permissions.py','account_management.py'):
            self.assertIn('/opt/auth-portal/registration-runtime/20261007-ca6258ad/'+path,protected)
        self.assertEqual(sha(HERE/'source/runtime.js'),sha(HERE/'native/assets/runtime.js'))
        self.assertEqual(sha(HERE/'source/navigation.js'),sha(HERE/'native/candidate/fs-home/navigation.js'))
        self.assertEqual(sha(HERE/'source/hubnav.js'),sha(HERE/'ui/candidate/hubnav.js'))
        self.assertEqual(sha(HERE/'source/app.js'),sha(HERE/'ui/candidate/account-app.js'))

if __name__=='__main__':
    if os.name!='posix':print('Windows: Linux root ownership checks not executed; CI must run them.')
    unittest.main()

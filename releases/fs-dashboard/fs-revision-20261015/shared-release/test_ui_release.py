"""Candidate and failure boundary checks against the existing shared publisher."""
import copy,hashlib,importlib.util,json
from pathlib import Path
import tempfile,unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('shared_publisher',HERE/'release_navigation.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class UIRelease(unittest.TestCase):
    def setUp(self):self.manifest=json.loads((HERE/'candidate-manifest.json').read_text('utf-8'))
    def test_actual_payload_validates_and_has_no_mutating_services(self):
        p.validate(self.manifest,HERE)
        self.assertEqual(set(p.expected_files(self.manifest)),set(p.REVISION_UI_TARGETS))
        self.assertEqual(len(self.manifest['files']),9)
        self.assertEqual(self.manifest['runtimeRequired'],{})
    def test_wrong_bytes_and_extra_path_rejected(self):
        for field,value in [('sha256','0'*64),('target','/etc/passwd'),('beforeSha256',None)]:
            wrong=copy.deepcopy(self.manifest);wrong['files'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):p.validate(wrong,HERE)
        wrong=copy.deepcopy(self.manifest);wrong['files'].append(wrong['files'][0])
        with self.assertRaises(ValueError):p.validate(wrong,HERE)
    def test_registry_is_the_actual_shared_navigation_consumer_payload(self):
        target='/var/www/dashboard/fs-home/navigation.json'
        row=next(r for r in self.manifest['files'] if r['target']==target)
        raw=(HERE/'candidate'/row['candidate']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])
        self.assertEqual(raw,(HERE.parent/'frontend-release/stage/assets/navigation.json').read_bytes())
        self.assertFalse(any(r['path']==target for r in self.manifest['unchangedRequired']))
        live=json.loads((HERE/'navigation-live-baseline.json').read_text('utf-8-sig'))
        self.assertEqual(row['beforeSha256'],live['files'][target]['sha256'])
        for file in (HERE/'candidate/revision/hubnav.js',HERE.parent/'frontend-release/stage/candidate/fs-home/navigation.js'):
            code=file.read_text('utf-8')
            self.assertIn("fetch('/dashboard/fs-home/navigation.json'",code,str(file))
        registry=json.loads(raw);tools={t['id']:t for t in registry['tools']}
        self.assertEqual(tools['weekly']['path'],'/dashboard/fs-home/brain/index.html?report_kind=weekly#reports')
        self.assertEqual(next(s['ids'] for s in registry['sections'] if s['id']=='arpg'),['d4'])
        self.assertEqual(sum(t['path']=='/d4/' for t in registry['tools']),1)
        self.assertFalse(any(t['path'].startswith('/dashboard/marketing/') for t in registry['tools']))
    def test_changed_runtime_fails_cas_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'var/www/dashboard/index.html'
            target.parent.mkdir(parents=True);target.write_text('other owner newer bytes')
            contract=dict(unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256='0'*64)],runtimeRequired={})
            with self.assertRaises(ValueError):p.guards(contract,root)
            self.assertEqual(target.read_text(),'other owner newer bytes')

if __name__=='__main__':unittest.main()

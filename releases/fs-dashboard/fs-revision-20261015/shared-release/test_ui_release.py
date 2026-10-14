"""Candidate and failure boundary checks against the existing shared publisher."""
import copy,importlib.util,json
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
        self.assertEqual(len(self.manifest['files']),8)
        self.assertEqual(self.manifest['runtimeRequired'],{})
    def test_wrong_bytes_and_extra_path_rejected(self):
        for field,value in [('sha256','0'*64),('target','/etc/passwd'),('beforeSha256',None)]:
            wrong=copy.deepcopy(self.manifest);wrong['files'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):p.validate(wrong,HERE)
        wrong=copy.deepcopy(self.manifest);wrong['files'].append(wrong['files'][0])
        with self.assertRaises(ValueError):p.validate(wrong,HERE)
    def test_changed_runtime_fails_cas_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'var/www/dashboard/index.html'
            target.parent.mkdir(parents=True);target.write_text('other owner newer bytes')
            contract=dict(unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256='0'*64)],runtimeRequired={})
            with self.assertRaises(ValueError):p.guards(contract,root)
            self.assertEqual(target.read_text(),'other owner newer bytes')

if __name__=='__main__':unittest.main()

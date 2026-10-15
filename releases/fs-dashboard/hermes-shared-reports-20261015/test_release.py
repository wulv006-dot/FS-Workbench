import copy,importlib.util,json,unittest,tempfile,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('shared_release',HERE/'release_navigation.py');publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
class SharedRelease(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((HERE/'candidate-manifest.json').read_text());self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.stage=Path(self.tmp.name)
        for row in self.manifest['files']:
            target=self.stage/'candidate'/row['candidate'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(HERE/'candidate'/Path(row['candidate']).name,target)
    def test_exact_existing_five_file_scope(self):
        self.assertEqual(len(publisher.validate(self.manifest,self.stage)),5)
        self.assertEqual(set(publisher.HERMES_SHARED_TARGETS.values()),{r['target'] for r in self.manifest['files']})
        self.assertTrue(all(r['beforeSha256'] for r in self.manifest['files']))
    def test_scope_refuses_extra_file_or_missing_guard(self):
        for mutate in (lambda m:m['files'].append(copy.deepcopy(m['files'][0])),lambda m:m.update(unchangedRequired=[])):
            m=copy.deepcopy(self.manifest);mutate(m)
            with self.assertRaises(ValueError):publisher.validate(m,self.stage)
    def test_provider_and_schedule_boundary_remains_enforced(self):
        for field,value in (('businessWrites',True),('timersChanged',True),('imageId','different')):
            m=copy.deepcopy(self.manifest);m[field]=value
            with self.assertRaises(ValueError):publisher.validate(m,self.stage)
    def test_release_stays_unapproved_and_uses_admission_fence(self):
        self.assertFalse(self.manifest['releaseReady'])
        import inspect
        self.assertIn('HERMES_SHARED_SCOPE',inspect.getsource(publisher.hermes_admission_fence))
        self.assertIn('shared_report_trash_requires_review_before_rollback',inspect.getsource(publisher.rollback))
if __name__=='__main__':unittest.main()

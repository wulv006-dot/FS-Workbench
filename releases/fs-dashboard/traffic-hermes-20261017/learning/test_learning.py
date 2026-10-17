import importlib.util,json,tempfile,unittest
from pathlib import Path
import prepare_learning as prep

class LearningTests(unittest.TestCase):
    def test_whitelist_version_and_historical_boundary(self):
        spec=importlib.util.spec_from_file_location('learning_candidate',Path(__file__).with_name('business_context.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skills=root/'skills';profile=root/'profile';skills.mkdir();profile.mkdir()
            (root/'desktop-business-context.md').write_text('current owner context',encoding='utf8')
            # Module-adjacent loop is real candidate baseline; root context is isolated.
            for name in prep.NAMES:
                f=skills/'ops-report-brief/ops-report-family/references'/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('historical dated example '+name,encoding='utf8')
            # Avoid modifying the candidate's adjacent loop: execute exact loader from temporary directory.
            copied=root/'business_context.py';copied.write_bytes(Path(mod.__file__).read_bytes());(root/'learning-loop.md').write_text(prep.REVISION,encoding='utf8')
            spec=importlib.util.spec_from_file_location('isolated_learning',copied);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            text,sha,rows=m.learning_bundle(root,skills,profile);self.assertEqual(len(rows),4);self.assertIn('不得替代新任务冻结证据',text)
            self.assertEqual(sha,m.learning_bundle(root,skills,profile)[1])
            ignored=skills/'unapproved.md';ignored.write_text('must not enter',encoding='utf8');self.assertEqual(sha,m.learning_bundle(root,skills,profile)[1])
            f.write_text('revised historical example',encoding='utf8');self.assertNotEqual(sha,m.learning_bundle(root,skills,profile)[1])
            f.write_bytes(b'x'*131073)
            with self.assertRaisesRegex(ValueError,'invalid|large'):m.learning_bundle(root,skills,profile)

    def test_payload_drift_extra_target_and_gate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);files=[]
            for i,(target,before) in enumerate(zip(prep.TARGETS,prep.BASELINES)):
                name=str(i);(p/name).write_bytes(b'x');files.append(dict(target=target,beforeSha256=before,candidate=name,sha256=prep.SHA(b'x'),bytes=1,owner='0:0',mode='0o600'))
            m=dict(files=files,releaseReady=False,productionWrites=0,requiresLockedAdmissionGate=True)
            def save():(p/'learning-manifest.json').write_text(json.dumps(m),encoding='utf8')
            save();prep.check(p)
            m['requiresLockedAdmissionGate']=False;save()
            with self.assertRaises(ValueError):prep.check(p)
            m['requiresLockedAdmissionGate']=True;m['files'].append(dict(files[0]));save()
            with self.assertRaises(ValueError):prep.check(p)
            m['files'].pop();save();(p/'0').write_bytes(b'y')
            with self.assertRaisesRegex(ValueError,'payload_drift'):prep.check(p)

if __name__=='__main__':unittest.main()

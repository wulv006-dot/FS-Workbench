import copy
import hashlib
import unittest
import test_release as fixture


class DirectReleaseTests(unittest.TestCase):
    setUp=fixture.ReleaseTests.setUp

    def direct_manifest(self):
        value=fixture.ReleaseTests.wire_manifest(self)
        value['scope']=self.publisher.HERMES_DIRECT_SCOPE
        selected=[]
        for rel,target in self.publisher.HERMES_DIRECT_TARGETS.items():
            p=self.stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'reviewed fixture')
            selected.append({'candidate':rel,'target':target,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                             'beforeSha256':None if rel.endswith('/direct_provider.py') else 'b'*64})
        value['files']=selected
        targets=set(self.publisher.HERMES_DIRECT_TARGETS.values())
        protected={r['path']:r for r in value['unchangedRequired'] if r['path'] not in targets}
        for target in (set(self.publisher.HERMES_TARGETS.values())|set(self.publisher.HERMES_CAPABILITY_TARGETS.values())|self.publisher.CAP_PROTECTED_SESSION)-targets:
            protected.setdefault(target,{'path':target,'sha256':'c'*64})
        value['unchangedRequired']=list(protected.values())
        return value

    def test_only_one_new_code_file_six_current_sources_no_secret_target(self):
        value=self.direct_manifest()
        self.assertEqual(len(self.publisher.validate(value,self.stage)),7)
        self.assertEqual(sum(r['beforeSha256'] is None for r in value['files']),1)
        self.assertTrue(all('/secrets/' not in r['target'] for r in value['files']))
        for row in value['files']:
            bad=copy.deepcopy(value);bad['files'].remove(next(r for r in bad['files'] if r['candidate']==row['candidate']))
            with self.assertRaises(ValueError):self.publisher.validate(bad,self.stage)

    def test_original_shared_provider_and_all_other_dependencies_stay_fenced(self):
        value=self.direct_manifest()
        self.assertIn('/opt/fs-exact-range-20261001/ai_advisor_model.py',{r['path'] for r in value['unchangedRequired']})
        for row in value['unchangedRequired']:
            bad=copy.deepcopy(value);bad['unchangedRequired'].remove(next(r for r in bad['unchangedRequired'] if r['path']==row['path']))
            with self.subTest(path=row['path']),self.assertRaises(ValueError):self.publisher.validate(bad,self.stage)

    def test_missing_existing_baseline_or_write_flag_is_rejected(self):
        value=self.direct_manifest()
        for row in value['files']:
            if row['candidate'].endswith('/direct_provider.py'):continue
            bad=copy.deepcopy(value);next(r for r in bad['files'] if r['candidate']==row['candidate'])['beforeSha256']=None
            with self.assertRaises(ValueError):self.publisher.validate(bad,self.stage)
        bad=copy.deepcopy(value);bad['businessWrites']=True
        with self.assertRaises(ValueError):self.publisher.validate(bad,self.stage)

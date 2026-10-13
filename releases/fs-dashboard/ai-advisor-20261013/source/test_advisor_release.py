import copy,importlib.util,io,json,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('advisor_publisher',ROOT/'deploy/release_navigation.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class Release(unittest.TestCase):
    def test_exact_five_files_preserve_key_auth_collection(self):
        self.assertEqual(p.expected_files({'scope':p.ADVISOR_SCOPE}),{'advisor/'+n for n in ('range_api.py','fc_daily.py','ai_advisor.py','ai_advisor_model.py','boss_insights.py')})
        for n in ('fc_daily_model.py','clients.json','deepseek.key','access_policy.py','fc_detail_reader.py'):
            with self.assertRaises(ValueError):p.target_for('advisor/'+n)
        self.assertEqual(len(p.expected_files({'scope':p.DAILY_SCOPE})),3)
    def test_existing_service_only(self):
        calls=[]
        with patch.object(p.subprocess,'run',lambda argv,**kw:calls.append(argv)),patch.object(p.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'{"ok":true}')):
            p.restart_for({'scope':p.ADVISOR_SCOPE})
        self.assertEqual([x for x in calls if x[1]=='restart'],[['systemctl','restart','fs-business-range.service']])
    def test_hash_and_baseline_fail_closed(self):
        m=json.loads((ROOT/'deploy/approved-manifest.json').read_text())
        self.assertEqual(len(p.validate(m,ROOT/'deploy')),5)
        for transform in (lambda x:x['files'].pop(),lambda x:x['files'][0].update(sha256='0'*64),lambda x:x['files'][0].update(beforeSha256=None),lambda x:x.update(runtimeRequired={})):
            wrong=copy.deepcopy(m);transform(wrong)
            with self.assertRaises(ValueError):p.validate(wrong,ROOT/'deploy')
    def test_business_auth_model_source_protected(self):
        m=json.loads((ROOT/'deploy/approved-manifest.json').read_text())
        paths={r['path'] for r in m['unchangedRequired']}
        self.assertTrue({'/var/www/dashboard/index.html','/opt/fs-access-policy/access_policy.py','/opt/fs-exact-range-20261001/fc_daily_model.py','/opt/fs-exact-range-20261001/summary_bridge.py'}.issubset(paths))
        self.assertFalse(paths.intersection(r['target'] for r in m['files']))
    def test_both_sources_identical(self):
        m=json.loads((ROOT/'deploy/approved-manifest.json').read_text())
        for r in m['files']:self.assertEqual((ROOT/'source'/Path(r['target']).name).read_bytes(),(ROOT/'deploy/candidate'/r['candidate']).read_bytes())

if __name__=='__main__':unittest.main()

import copy,importlib.util,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deep_publisher',ROOT/'deploy/release_navigation.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class DeepRelease(unittest.TestCase):
    def setUp(self):
        self.m=json.loads((ROOT/'deploy/approved-manifest.json').read_text('utf-8'))

    def test_exact_ten_files_and_shared_provider_untouched(self):
        self.assertEqual(len(p.expected_files(self.m)),10)
        self.assertEqual(len(p.validate(self.m,ROOT/'deploy')),10)
        for name in ('boss_insights.py','ai_advisor_model.py','fc_daily_model.py','fc_detail_reader.py','deepseek.key','access_policy.py'):
            with self.assertRaises(ValueError):p.target_for('deep/'+name)
        self.assertEqual({Path(r['target']).name for r in self.m['files'] if r['beforeSha256'] is not None},{'range_api.py','fc_daily.py','ai_advisor.py'})

    def test_missing_dependency_or_changed_baseline_refuses(self):
        wrong=copy.deepcopy(self.m);wrong['unchangedRequired']=[x for x in wrong['unchangedRequired'] if not x['path'].endswith('/boss_insights.py')]
        with self.assertRaises(ValueError):p.validate(wrong,ROOT/'deploy')
        wrong=copy.deepcopy(self.m);wrong['files'][0]['beforeSha256']=None
        with self.assertRaises(ValueError):p.validate(wrong,ROOT/'deploy')

    def test_new_sources_match_and_no_business_mutation_targets(self):
        for r in self.m['files']:
            self.assertEqual((ROOT/'source'/Path(r['target']).name).read_bytes(),(ROOT/'deploy/candidate'/r['candidate']).read_bytes())
            self.assertTrue(r['target'].startswith('/opt/fs-exact-range-20261001/'))

    def test_frontend_only_replaces_authenticated_advisor_alias(self):
        import base64,re
        f=ROOT/'frontend'
        old=base64.b64decode(json.loads((f/'baseline-fixture.json').read_text())['files']['/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf']['bytesB64']).decode()
        new=(f/'candidate/formal.conf').read_text('utf-8')
        pattern=r'(?<=/var/lib/fs-navigation-formal-static/)workspace-native-20261006-[a-f0-9]{12}(?=/advisor.html)'
        # Only one existing route target changes; no auth, method, API or unrelated route edits.
        newversion=json.loads((f/'release-manifest.json').read_text())['releaseId']
        self.assertEqual(new.count(newversion),1)
        old_start=old.index('location = /dashboard/marketing/weekly/index.html {')
        oldversion=re.search(pattern,old[old_start:]).group(0)
        self.assertEqual(new.replace(newversion,oldversion),old)
        self.assertIn('auth_request /__auth_verify;',new[old_start:old_start+400])

    @unittest.skipUnless(os.name=='posix','Real Linux file locks required')
    def test_active_job_and_active_model_refuse_restart(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            provider=p.rooted(root,'/var/lib/fs-business-ranges/fc-daily/provider.lock');provider.parent.mkdir(parents=True);provider.touch()
            databases=[]
            for name in ('advisor/advisor.sqlite3','fc-daily/daily.sqlite3'):
                dbfile=p.rooted(root,'/var/lib/fs-business-ranges/'+name);dbfile.parent.mkdir(parents=True,exist_ok=True)
                with sqlite3.connect(str(dbfile)) as db:db.execute('CREATE TABLE jobs(state TEXT)')
                databases.append(dbfile)
            with p.model_release_lock(self.m,root):pass
            with sqlite3.connect(str(databases[0])) as db:db.execute("INSERT INTO jobs VALUES('running')")
            with self.assertRaisesRegex(ValueError,'active report'):
                with p.model_release_lock(self.m,root):self.fail('active job admitted')
            with sqlite3.connect(str(databases[0])) as db:db.execute('DELETE FROM jobs')
            with provider.open('a+b') as fd:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    with p.model_release_lock(self.m,root):self.fail('active model admitted')

if __name__=='__main__':unittest.main()

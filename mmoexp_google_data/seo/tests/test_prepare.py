import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mmoexp_google_data.seo import prepare,release


class Prepare(unittest.TestCase):
    def release_inputs(self):
        repo=Path(__file__).resolve().parents[3]
        nav=dict(schemaVersion=1,sections=[dict(id='analytics',ids=['unified-business'])],tools=[dict(id='unified-business',path='/dashboard/analytics/')])
        raw=(json.dumps(nav)+'\n').encode();formal=b'# Existing unrelated FS routes\n'
        baseline=dict(target_hashes={prepare.NAV:hashlib.sha256(raw).hexdigest(),prepare.FORMAL:hashlib.sha256(formal).hexdigest()},unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256='0'*64)])
        gb=1024**3
        config=dict(data_root='/var/lib/fs-seo',control_root='/var/lib/fs-seo-control',ai_root='/var/lib/fs-seo-ai',web_port=8957,
                    resource_policy=dict(warning_bytes=4*gb,operating_ceiling_bytes=16*gb,emergency_stop_bytes=24*gb,host_reserve_bytes=40*gb,measured_basis='test fixture'),memory_policy={'measured_basis':'test'},sources={'admin':True})
        return repo,baseline,formal,raw,config,nav

    def test_exact_scope_and_existing_navigation_are_preserved(self):
        repo,baseline,formal,raw,config,nav=self.release_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'release'
            result=prepare.build(repo,baseline,formal,raw,config,output)
            manifest=json.loads((output/'manifest.json').read_text())
            publisher=release.publisher(output,manifest)
            publisher.validate(manifest,output)
            actual=json.loads((output/'candidate/navigation.json').read_text())
            self.assertEqual(actual['tools'][:-1],nav['tools'])
            self.assertEqual(actual['sections'][0]['ids'][:-1],nav['sections'][0]['ids'])
            self.assertTrue((output/'candidate/routes.conf').read_bytes().startswith(formal))
            self.assertEqual(sum('OnCalendar=' in p.read_text() for p in (output/'candidate/units').iterdir()),1)
            self.assertNotIn('Hermes',(output/'candidate/units/fs-seo-daily.service').read_text())
            self.assertEqual(manifest['package'],result['package'])
            self.assertTrue((output/'candidate/runtime/mmoexp_google_data/seo/calendar.fc27.user-provided.json').exists())
            bad=dict(manifest,files=manifest['files']+[dict(candidate='evil',target='/etc/shadow',sha256='0'*64,beforeSha256=None)])
            with self.assertRaises(ValueError):publisher.validate(bad,output)
            with self.assertRaises(FileExistsError):prepare.build(repo,baseline,formal,raw,config,output)
            installed_formal=(output/'candidate/routes.conf').read_bytes()
            installed_nav=(output/'candidate/navigation.json').read_bytes()
            updated=dict(target_hashes={r['target']:r['sha256'] for r in manifest['files']},unchangedRequired=baseline['unchangedRequired'])
            second=Path(tmp)/'upgrade'
            prepare.build(repo,updated,installed_formal,installed_nav,dict(config,web_port=8958),second)
            next_manifest=json.loads((second/'manifest.json').read_text())
            release.publisher(second,next_manifest).validate(next_manifest,second)
            amended=(second/'candidate/routes.conf').read_text()
            self.assertEqual(amended.count('# >>> FS SEO daily >>>'),1)
            self.assertIn('127.0.0.1:8958',amended)
            self.assertNotIn('127.0.0.1:8957',amended)
            self.assertEqual(json.loads((second/'candidate/navigation.json').read_text()),actual)

    def test_explicit_order_facts_candidate_packages_both_reader_modules(self):
        repo,baseline,formal,raw,config,_=self.release_inputs()
        config['sources']['orders']={'enabled':True}
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'order-facts'
            prepare.build(repo,baseline,formal,raw,config,output)
            manifest=json.loads((output/'manifest.json').read_text())
            release.publisher(output,manifest).validate(manifest,output)
            self.assertEqual(json.loads((output/'candidate/config.json').read_text())['sources'],
                             {'admin':True,'orders':{'enabled':True}})
            for name in ('order_reader.py','order_source.py'):
                candidate='runtime/mmoexp_google_data/seo/'+name
                self.assertEqual((output/'candidate'/candidate).read_bytes(),
                                 (repo/'mmoexp_google_data/seo'/name).read_bytes())
                missing=dict(manifest,files=[row for row in manifest['files'] if row['candidate']!=candidate])
                with self.assertRaisesRegex(ValueError,'SEO_ORDER_FACTS_MODULES_REQUIRED'):
                    release.publisher(output,missing).validate(missing,output)
            reader=repo/'mmoexp_google_data/seo/order_reader.py'
            glob=Path.glob
            with patch.object(Path,'glob',lambda path,pattern: (p for p in glob(path,pattern) if p!=reader)):
                with self.assertRaisesRegex(ValueError,'SEO_ORDER_FACTS_MODULES_REQUIRED'):
                    prepare.build(repo,baseline,formal,raw,config,Path(tmp)/'missing-source')
            bad_config=output/'candidate/config.json'
            bad_config.write_text(json.dumps(dict(config,sources={'admin':True,'orders':{'enabled':'true'}})))
            with self.assertRaisesRegex(ValueError,'SEO_ORDER_FACTS_CONFIGURATION_INVALID'):
                release.publisher(output,manifest).validate(manifest,output)
            bad_config.write_text(json.dumps(dict(config,sources={'admin':False,'orders':{'enabled':True}})))
            with self.assertRaisesRegex(ValueError,'NATIVE_ADMIN_ESTIMATE_REQUIRED'):
                release.publisher(output,manifest).validate(manifest,output)
            self.assertEqual((output/'candidate/units/fs-seo-daily.timer').read_text(),
                             prepare.units('/unused')['fs-seo-daily.timer'])

    def test_unknown_order_source_configuration_does_not_expand_candidate(self):
        repo,baseline,formal,raw,config,_=self.release_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'order-facts'
            for invalid in (True,{'enabled':'true'},{'enabled':True,'source':'custom'}):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError,'SEO_ORDER_FACTS_CONFIGURATION_INVALID'):
                    config['sources']['orders']=invalid
                    prepare.build(repo,baseline,formal,raw,config,output)
                self.assertFalse(output.exists())
